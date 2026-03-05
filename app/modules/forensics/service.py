"""
Health Check AI — Forensics Module
Orchestration Service: coordinates investigation lifecycle,
task scheduling, finding aggregation, and report generation.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Base output directory for all forensic investigations
FORENSICS_OUTPUT_BASE = os.environ.get(
    "FORENSICS_OUTPUT_DIR",
    "/var/lib/healthcheck/forensics"
)


class ForensicsService:
    """
    Main orchestrator for forensic investigations.
    
    Lifecycle:
    1. create_investigation()   → Creates record, status=PENDING
    2. grant_consent()          → Records POPIA consent, status=CONSENT_GRANTED
    3. start_investigation()    → Runs tasks per scope, status=RUNNING
    4. (tasks run async)        → status=COMPLETE or FAILED
    5. generate_report()        → Produces readable PDF + JSON report
    
    Nothing proceeds past step 1 without step 2 being completed first.
    """

    def __init__(self, db_session=None):
        self.db = db_session

    # ── Scope → Task Map ──────────────────────────────────────────────────────

    SCOPE_TASKS = {
        "quick_triage": [
            # ~5-10 minutes. Read-only. Safe on a live system.
            {"tool_id": "osquery",   "task_type": "live_system_query",
             "description": "Interrogate live system state via osquery"},
            {"tool_id": "strings",   "task_type": "string_extraction",
             "description": "Extract strings from recently modified binaries"},
            {"tool_id": "yara",      "task_type": "yara_scan",
             "description": "YARA malware pattern scan on key directories"},
            {"tool_id": "tshark",    "task_type": "network_analysis",
             "description": "Analyse network traffic (60 second capture)"},
            {"tool_id": "sha256sum", "task_type": "integrity_hashing",
             "description": "Hash all collected evidence for chain of custody"},
        ],
        "standard": [
            # ~30-60 minutes. Disk artefact analysis added.
            {"tool_id": "osquery",        "task_type": "live_system_query"},
            {"tool_id": "tshark",         "task_type": "network_analysis"},
            {"tool_id": "yara",           "task_type": "yara_scan"},
            {"tool_id": "strings",        "task_type": "string_extraction"},
            {"tool_id": "sleuthkit",      "task_type": "disk_analysis",
             "description": "File system listing and deleted file detection"},
            {"tool_id": "bulk_extractor", "task_type": "bulk_extraction",
             "description": "Extract structured data from disk image"},
            {"tool_id": "sha256sum",      "task_type": "integrity_hashing"},
        ],
        "deep": [
            # 2+ hours. Full analysis including memory and file carving.
            {"tool_id": "osquery",        "task_type": "live_system_query"},
            {"tool_id": "tshark",         "task_type": "network_analysis"},
            {"tool_id": "yara",           "task_type": "yara_scan"},
            {"tool_id": "strings",        "task_type": "string_extraction"},
            {"tool_id": "volatility3",    "task_type": "memory_analysis",
             "description": "Full memory dump analysis"},
            {"tool_id": "sleuthkit",      "task_type": "disk_analysis"},
            {"tool_id": "bulk_extractor", "task_type": "bulk_extraction"},
            {"tool_id": "foremost",       "task_type": "file_carving",
             "description": "Recover deleted files via file carving"},
            {"tool_id": "sha256sum",      "task_type": "integrity_hashing"},
        ],
    }

    # ── Investigation Management ──────────────────────────────────────────────

    def create_investigation(
        self,
        client_id: str,
        scope: str,
        reason: str,
        initiated_by: str,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        device_os: Optional[str] = None,
    ) -> dict:
        """
        Creates a new forensic investigation in PENDING state.
        Consent must be granted before analysis can start.
        Returns the investigation record as a dict.
        """
        investigation_id = str(uuid.uuid4())
        output_dir = os.path.join(
            FORENSICS_OUTPUT_BASE,
            investigation_id
        )
        os.makedirs(output_dir, exist_ok=True)

        investigation = {
            "id":             investigation_id,
            "client_id":      client_id,
            "device_id":      device_id,
            "device_name":    device_name,
            "device_os":      device_os,
            "scope":          scope,
            "status":         "pending",
            "reason":         reason,
            "initiated_by":   initiated_by,
            "consent_granted": False,
            "output_directory": output_dir,
            "created_at":     datetime.utcnow().isoformat(),
            "tasks":          [],
            "finding_count":  0,
            "critical_count": 0,
            "high_count":     0,
        }

        # Write initial record to disk
        record_file = os.path.join(output_dir, "investigation.json")
        with open(record_file, "w") as f:
            json.dump(investigation, f, indent=2)

        logger.info(f"[forensics] Investigation created: {investigation_id} "
                    f"| client: {client_id} | scope: {scope}")
        logger.warning(f"[forensics] Investigation {investigation_id} is PENDING — "
                       f"awaiting POPIA consent before analysis can begin.")

        return investigation

    def grant_consent(
        self,
        investigation_id: str,
        consent_obtained_by: str,
        consent_method: str,
        consent_reference: str,
    ) -> dict:
        """
        Records POPIA consent for an investigation.
        Sets status to CONSENT_GRANTED — required before start_investigation().
        """
        record_file = self._record_file(investigation_id)
        investigation = self._load(record_file)

        if investigation["status"] != "pending":
            raise ValueError(
                f"Investigation {investigation_id} is not in PENDING state "
                f"(current: {investigation['status']}). Consent can only be "
                f"recorded for pending investigations."
            )

        investigation["consent_granted"]    = True
        investigation["consent_obtained_by"] = consent_obtained_by
        investigation["consent_method"]      = consent_method
        investigation["consent_reference"]   = consent_reference
        investigation["consent_timestamp"]   = datetime.utcnow().isoformat()
        investigation["status"]              = "consent_granted"

        self._save(record_file, investigation)

        logger.info(f"[forensics] Consent recorded for {investigation_id} "
                    f"by {consent_obtained_by} via {consent_method} (ref: {consent_reference})")
        return investigation

    async def start_investigation(
        self,
        investigation_id: str,
        tool_inputs: Optional[dict] = None,
    ) -> dict:
        """
        Starts the investigation. Consent must be granted first.
        Runs all tasks for the investigation scope.
        
        tool_inputs: optional dict of {tool_id: {kwarg: value}} for tool-specific config
                     e.g. {"volatility3": {"memory_image": "/path/to/ram.img"}}
        """
        record_file = self._record_file(investigation_id)
        investigation = self._load(record_file)

        if not investigation["consent_granted"]:
            raise PermissionError(
                f"Investigation {investigation_id} cannot start: "
                f"POPIA consent has not been recorded. "
                f"Call grant_consent() first."
            )

        if investigation["status"] not in ("consent_granted", "paused"):
            raise ValueError(
                f"Investigation is in state '{investigation['status']}' — "
                f"cannot start."
            )

        investigation["status"]     = "running"
        investigation["started_at"] = datetime.utcnow().isoformat()
        output_dir = investigation["output_directory"]
        scope      = investigation["scope"]
        self._save(record_file, investigation)

        logger.info(f"[forensics] Starting investigation {investigation_id} "
                    f"(scope: {scope})")

        # Run quick triage first (live collection)
        from app.modules.forensics.collectors.live_collector import QuickTriageCollector
        triage = QuickTriageCollector()
        triage_dir = os.path.join(output_dir, "triage")
        triage_manifest = triage.collect(triage_dir)
        logger.info(f"[forensics] Triage collected {len(triage_manifest['artifacts'])} artefacts")

        # Run tool-based tasks
        tasks_config = self.SCOPE_TASKS.get(scope, self.SCOPE_TASKS["quick_triage"])
        task_results = []
        all_findings = []

        from app.modules.forensics.tools.wrappers import get_tool_instance
        from app.modules.forensics.tool_registry import check_tool_availability, get_tool

        for task_cfg in tasks_config:
            tool_id   = task_cfg["tool_id"]
            task_type = task_cfg.get("task_type", tool_id)
            task_desc = task_cfg.get("description", "")

            # Check if tool is available
            tool_meta = get_tool(tool_id)
            if tool_meta:
                check_tool_availability(tool_meta)
                if not tool_meta.is_available:
                    logger.warning(f"[forensics] Tool not installed: {tool_id} — skipping")
                    task_results.append({
                        "tool_id":   tool_id,
                        "task_type": task_type,
                        "status":    "skipped",
                        "reason":    f"Tool '{tool_id}' not installed. "
                                     f"Install with: {tool_meta.install_cmd}",
                    })
                    continue

            tool_instance = get_tool_instance(tool_id)
            if not tool_instance:
                task_results.append({
                    "tool_id":   tool_id,
                    "task_type": task_type,
                    "status":    "skipped",
                    "reason":    "No wrapper available for this tool",
                })
                continue

            task_output_dir = os.path.join(output_dir, f"task_{tool_id}")
            os.makedirs(task_output_dir, exist_ok=True)

            # Build kwargs for this tool
            kwargs = {"output_dir": task_output_dir}
            if tool_inputs and tool_id in tool_inputs:
                kwargs.update(tool_inputs[tool_id])

            try:
                logger.info(f"[forensics] Running task: {tool_id} ({task_type})")
                result = tool_instance.run(**kwargs)
                all_findings.extend(result.findings)
                task_results.append({
                    "tool_id":        tool_id,
                    "task_type":      task_type,
                    "status":         "complete" if result.success else "failed",
                    "duration_secs":  result.duration_secs if hasattr(result, "duration_secs") else 0,
                    "summary":        result.summary,
                    "finding_count":  len(result.findings),
                    "artifact_count": len(result.artifacts),
                    "error":          result.error_output if not result.success else "",
                })
                logger.info(f"[forensics] {tool_id}: {result.summary}")
            except Exception as e:
                logger.exception(f"[forensics] Task {tool_id} raised exception: {e}")
                task_results.append({
                    "tool_id":   tool_id,
                    "task_type": task_type,
                    "status":    "failed",
                    "error":     str(e),
                })

        # Update investigation record
        critical = sum(1 for f in all_findings if f.get("severity") == "critical")
        high     = sum(1 for f in all_findings if f.get("severity") == "high")

        investigation["status"]        = "complete"
        investigation["completed_at"]  = datetime.utcnow().isoformat()
        investigation["tasks"]         = task_results
        investigation["findings"]      = all_findings
        investigation["finding_count"] = len(all_findings)
        investigation["critical_count"] = critical
        investigation["high_count"]     = high
        self._save(record_file, investigation)

        logger.info(
            f"[forensics] Investigation {investigation_id} complete. "
            f"Findings: {len(all_findings)} total, {critical} critical, {high} high."
        )
        return investigation

    def get_investigation(self, investigation_id: str) -> dict:
        record_file = self._record_file(investigation_id)
        return self._load(record_file)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _record_file(self, investigation_id: str) -> str:
        return os.path.join(
            FORENSICS_OUTPUT_BASE,
            investigation_id,
            "investigation.json"
        )

    def _load(self, path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Investigation record not found: {path}")
        with open(path) as f:
            return json.load(f)

    def _save(self, path: str, data: dict):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
