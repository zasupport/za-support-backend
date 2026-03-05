"""
Health Check AI — Forensics Module
Orchestration Service: coordinates investigation lifecycle,
task scheduling, finding aggregation, and report generation.

Storage: PostgreSQL (forensic_investigations, forensic_findings, forensic_audit_log)
Output artefacts: /tmp/za_forensics/{investigation_id}/ (ephemeral, for current session)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FORENSICS_OUTPUT_BASE = os.environ.get("FORENSICS_OUTPUT_DIR", "/tmp/za_forensics")


class ForensicsService:
    """
    Main orchestrator for forensic investigations.

    Lifecycle:
    1. create_investigation()   → PENDING
    2. grant_consent()          → CONSENT_GRANTED
    3. start_investigation()    → RUNNING → COMPLETE
    4. generate_report()        → PDF + JSON reports
    """

    SCOPE_TASKS = {
        "quick_triage": [
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

    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session

    # ── Investigation Lifecycle ────────────────────────────────────────────────

    async def create_investigation(self, request) -> dict:
        """Creates a new forensic investigation in PENDING state."""
        investigation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        record = {
            "id":               investigation_id,
            "client_id":        request.client_id,
            "device_id":        getattr(request, "device_id", None),
            "device_hostname":  getattr(request, "device_name", None),
            "device_os":        getattr(request, "device_os", None),
            "scope":            getattr(request, "scope", "quick_triage"),
            "status":           "pending",
            "reason":           request.reason,
            "initiated_by":     request.initiated_by,
            "consent_granted":  False,
            "output_directory": os.path.join(FORENSICS_OUTPUT_BASE, investigation_id),
            "created_at":       now,
            "tasks":            [],
            "findings":         [],
            "finding_count":    0,
            "critical_count":   0,
            "high_count":       0,
        }

        if self.db:
            self.db.execute(
                """
                INSERT INTO forensic_investigations
                    (id, client_id, device_id, device_hostname, device_os,
                     scope, status, initiated_by, reason, created_at)
                VALUES
                    (:id, :client_id, :device_id, :device_hostname, :device_os,
                     :scope, 'pending'::investigation_status, :initiated_by, :reason, NOW())
                """,
                {
                    "id":            investigation_id,
                    "client_id":     record["client_id"],
                    "device_id":     record["device_id"],
                    "device_hostname": record["device_hostname"],
                    "device_os":     record["device_os"],
                    "scope":         str(record["scope"]).replace("AnalysisScope.", ""),
                    "initiated_by":  record["initiated_by"],
                    "reason":        record["reason"],
                },
            )
            self.db.commit()

        self._save_local(investigation_id, record)
        logger.info(f"[forensics] Investigation created: {investigation_id}")
        return record

    async def grant_consent(self, investigation_id: str, request) -> dict:
        """Records POPIA consent. Advances status to CONSENT_GRANTED."""
        record = await self.get_investigation(investigation_id)
        if not record:
            raise ValueError(f"Investigation {investigation_id} not found.")

        if record["status"] not in ("pending",):
            raise ValueError(
                f"Investigation is '{record['status']}' — consent can only be recorded for pending investigations."
            )

        record["consent_granted"]     = True
        record["consent_obtained_by"] = getattr(request, "consent_obtained_by", "")
        record["consent_method"]      = getattr(request, "consent_method", "")
        record["consent_reference"]   = getattr(request, "consent_reference", "")
        record["consent_timestamp"]   = datetime.now(timezone.utc).isoformat()
        record["status"]              = "consent_granted"

        if self.db:
            self.db.execute(
                """
                UPDATE forensic_investigations
                SET status = 'consent_granted'::investigation_status,
                    consent_obtained_by = :by, consent_method = :method,
                    consent_reference = :ref, consent_timestamp = NOW()
                WHERE id = :id
                """,
                {
                    "id":     investigation_id,
                    "by":     record["consent_obtained_by"],
                    "method": record["consent_method"],
                    "ref":    record["consent_reference"],
                },
            )
            self.db.commit()

        self._save_local(investigation_id, record)
        logger.info(f"[forensics] Consent recorded for {investigation_id}")
        return record

    async def start_investigation(self, investigation_id: str, tool_inputs: Optional[dict] = None) -> dict:
        """Starts the investigation. Consent must be granted first."""
        record = await self.get_investigation(investigation_id)
        if not record:
            raise ValueError(f"Investigation {investigation_id} not found.")

        if not record.get("consent_granted"):
            raise PermissionError(
                f"Investigation {investigation_id} cannot start: POPIA consent not recorded. "
                "Call grant_consent() first."
            )

        if record["status"] not in ("consent_granted", "paused"):
            raise ValueError(f"Investigation is '{record['status']}' — cannot start.")

        output_dir = record.get("output_directory", os.path.join(FORENSICS_OUTPUT_BASE, investigation_id))
        os.makedirs(output_dir, exist_ok=True)

        record["status"]     = "running"
        record["started_at"] = datetime.now(timezone.utc).isoformat()

        if self.db:
            self.db.execute(
                "UPDATE forensic_investigations SET status='running'::investigation_status, started_at=NOW() WHERE id=:id",
                {"id": investigation_id},
            )
            self.db.commit()

        scope       = str(record.get("scope", "quick_triage")).replace("AnalysisScope.", "")
        tasks_cfg   = self.SCOPE_TASKS.get(scope, self.SCOPE_TASKS["quick_triage"])
        task_results, all_findings = [], []

        from app.modules.forensics.tool_registry import check_tool_availability, get_tool
        try:
            from app.modules.forensics.tools.wrappers import get_tool_instance
        except ImportError:
            get_tool_instance = lambda tid: None  # noqa: E731

        for task_cfg in tasks_cfg:
            tool_id   = task_cfg["tool_id"]
            task_type = task_cfg.get("task_type", tool_id)

            tool_meta = get_tool(tool_id)
            if tool_meta:
                check_tool_availability(tool_meta)
                if not tool_meta.is_available:
                    task_results.append({"tool_id": tool_id, "task_type": task_type,
                                         "status": "skipped", "reason": f"'{tool_id}' not installed"})
                    continue

            tool_instance = get_tool_instance(tool_id) if get_tool_instance else None
            if not tool_instance:
                task_results.append({"tool_id": tool_id, "task_type": task_type,
                                     "status": "skipped", "reason": "No wrapper available"})
                continue

            task_dir = os.path.join(output_dir, f"task_{tool_id}")
            os.makedirs(task_dir, exist_ok=True)
            kwargs = {"output_dir": task_dir}
            if tool_inputs and tool_id in tool_inputs:
                kwargs.update(tool_inputs[tool_id])

            try:
                result = tool_instance.run(**kwargs)
                all_findings.extend(result.findings)
                task_results.append({
                    "tool_id":       tool_id,
                    "task_type":     task_type,
                    "status":        "complete" if result.success else "failed",
                    "summary":       result.summary,
                    "finding_count": len(result.findings),
                    "error":         result.error_output if not result.success else "",
                })
            except Exception as exc:
                task_results.append({"tool_id": tool_id, "task_type": task_type,
                                     "status": "failed", "error": str(exc)})

        critical = sum(1 for f in all_findings if str(f.get("severity", "")).lower() == "critical")
        high     = sum(1 for f in all_findings if str(f.get("severity", "")).lower() == "high")

        record.update({
            "status":         "complete",
            "completed_at":   datetime.now(timezone.utc).isoformat(),
            "tasks":          task_results,
            "findings":       all_findings,
            "finding_count":  len(all_findings),
            "critical_count": critical,
            "high_count":     high,
        })

        if self.db:
            self.db.execute(
                """
                UPDATE forensic_investigations
                SET status='complete'::investigation_status, completed_at=NOW(),
                    finding_count=:fc, critical_count=:cc, high_count=:hc
                WHERE id=:id
                """,
                {"id": investigation_id, "fc": len(all_findings), "cc": critical, "hc": high},
            )
            for f in all_findings:
                self.db.execute(
                    """
                    INSERT INTO forensic_findings
                        (investigation_id, tool_id, finding_type, severity,
                         description, artifact_path, raw_data)
                    VALUES
                        (:inv, :tool, :ftype, :sev::finding_severity,
                         :desc, :artifact, :raw::jsonb)
                    """,
                    {
                        "inv":      investigation_id,
                        "tool":     f.get("tool_id", "unknown"),
                        "ftype":    f.get("type", "indicator"),
                        "sev":      str(f.get("severity", "info")).lower(),
                        "desc":     f.get("description", ""),
                        "artifact": f.get("artifact_path"),
                        "raw":      json.dumps(f),
                    },
                )
            self.db.commit()

        self._save_local(investigation_id, record)
        logger.info(f"[forensics] Investigation {investigation_id} complete — {len(all_findings)} findings.")
        return record

    async def get_investigation(self, investigation_id: str) -> Optional[dict]:
        """Load investigation from DB (fallback: local /tmp)."""
        if self.db:
            row = self.db.execute(
                "SELECT * FROM forensic_investigations WHERE id = :id",
                {"id": investigation_id},
            ).fetchone()
            if row:
                d = dict(row._mapping)
                # Enrich with findings and tasks from local cache if available
                local = self._load_local(investigation_id)
                d["findings"] = local.get("findings", []) if local else []
                d["tasks"]    = local.get("tasks", []) if local else []
                return d

        return self._load_local(investigation_id)

    async def list_investigations(
        self,
        status: Optional[str] = None,
        client_id: Optional[str] = None,
        device_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list:
        """List investigations with optional filters."""
        if self.db:
            filters, params = [], {}
            if status:
                filters.append("status = :status::investigation_status")
                params["status"] = str(status)
            if client_id:
                filters.append("client_id = :client_id")
                params["client_id"] = client_id
            if device_id:
                filters.append("device_id = :device_id")
                params["device_id"] = device_id

            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            params["limit"]  = limit
            params["offset"] = offset
            rows = self.db.execute(
                f"SELECT * FROM forensic_investigations {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
                params,
            ).fetchall()
            return [dict(r._mapping) for r in rows]

        # Fallback: scan /tmp
        results = []
        base = Path(FORENSICS_OUTPUT_BASE)
        if base.exists():
            for d in base.iterdir():
                rec = self._load_local(d.name)
                if rec:
                    if status and rec.get("status") != str(status):
                        continue
                    if client_id and rec.get("client_id") != client_id:
                        continue
                    results.append(rec)
        return sorted(results, key=lambda r: r.get("created_at", ""), reverse=True)[offset:offset + limit]

    async def get_findings(
        self,
        investigation_id: str,
        severity: Optional[str] = None,
        reviewed: Optional[bool] = None,
    ) -> list:
        """Return findings for an investigation."""
        if self.db:
            filters = ["investigation_id = :id"]
            params  = {"id": investigation_id}
            if severity:
                filters.append("severity = :sev::finding_severity")
                params["sev"] = severity.lower()
            if reviewed is not None:
                filters.append("reviewed_at IS " + ("NOT NULL" if reviewed else "NULL"))
            rows = self.db.execute(
                f"SELECT * FROM forensic_findings WHERE {' AND '.join(filters)} ORDER BY severity",
                params,
            ).fetchall()
            return [dict(r._mapping) for r in rows]

        rec = await self.get_investigation(investigation_id)
        if not rec:
            return []
        findings = rec.get("findings", [])
        if severity:
            findings = [f for f in findings if str(f.get("severity", "")).lower() == severity.lower()]
        return findings

    async def get_tasks(self, investigation_id: str) -> list:
        """Return task execution details for an investigation."""
        rec = await self.get_investigation(investigation_id)
        if not rec:
            return []
        return rec.get("tasks", [])

    async def review_finding(
        self,
        investigation_id: str,
        finding_id: str,
        reviewed_by: str,
        is_false_positive: bool = False,
        notes: Optional[str] = None,
    ) -> dict:
        """Mark a finding as reviewed by an analyst."""
        if self.db:
            self.db.execute(
                """
                UPDATE forensic_findings
                SET reviewed_at = NOW(), reviewed_by = :by,
                    is_false_positive = :fp, review_notes = :notes
                WHERE id = :id AND investigation_id = :inv
                """,
                {"id": finding_id, "inv": investigation_id,
                 "by": reviewed_by, "fp": is_false_positive, "notes": notes},
            )
            self.db.commit()
            row = self.db.execute(
                "SELECT * FROM forensic_findings WHERE id = :id", {"id": finding_id}
            ).fetchone()
            if not row:
                raise ValueError(f"Finding {finding_id} not found.")
            return dict(row._mapping)

        raise ValueError(f"Finding {finding_id} not found (no DB session).")

    async def cancel_investigation(self, investigation_id: str, reason: str) -> dict:
        """Cancel a pending or running investigation."""
        rec = await self.get_investigation(investigation_id)
        if not rec:
            raise ValueError(f"Investigation {investigation_id} not found.")

        if rec.get("status") in ("complete", "cancelled"):
            raise ValueError(f"Cannot cancel investigation in state '{rec['status']}'.")

        rec["status"]       = "cancelled"
        rec["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        rec["cancel_reason"] = reason

        if self.db:
            self.db.execute(
                "UPDATE forensic_investigations SET status='cancelled'::investigation_status WHERE id=:id",
                {"id": investigation_id},
            )
            self.db.commit()

        self._save_local(investigation_id, rec)
        return rec

    # ── Report Generation ──────────────────────────────────────────────────────

    async def generate_report(self, investigation_id: str) -> dict:
        """Generate PDF and JSON reports for a completed investigation."""
        rec = await self.get_investigation(investigation_id)
        if not rec:
            raise ValueError(f"Investigation {investigation_id} not found.")

        if rec.get("status") not in ("complete",):
            raise ValueError(
                f"Investigation is '{rec.get('status')}' — report can only be generated for completed investigations."
            )

        output_dir = rec.get("output_directory", os.path.join(FORENSICS_OUTPUT_BASE, investigation_id))
        os.makedirs(output_dir, exist_ok=True)

        json_path = os.path.join(output_dir, "report.json")
        pdf_path  = os.path.join(output_dir, "report.pdf")

        # Write JSON report
        report_data = {
            "report_type":     "forensic_investigation",
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "generated_by":    "Health Check AI — Forensics Module",
            "investigation":   rec,
            "findings":        await self.get_findings(investigation_id),
            "tasks":           await self.get_tasks(investigation_id),
            "popia_disclaimer": (
                "This report contains personal and potentially sensitive information "
                "collected under POPIA Section 11 consent. Handle in accordance with "
                "your data governance policy. Retention: 3 years."
            ),
        }
        with open(json_path, "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        # Write PDF report
        _generate_pdf_report(rec, report_data, pdf_path)

        # Store report paths in record
        rec["report_pdf"]  = pdf_path
        rec["report_json"] = json_path
        rec["report_generated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_local(investigation_id, rec)

        if self.db:
            self.db.execute(
                "UPDATE forensic_investigations SET report_generated_at=NOW() WHERE id=:id",
                {"id": investigation_id},
            )
            self.db.commit()

        return {"pdf": pdf_path, "json": json_path}

    async def get_report(self, investigation_id: str) -> Optional[dict]:
        """Return report file paths for an investigation."""
        rec = await self.get_investigation(investigation_id)
        if not rec:
            return None
        pdf  = rec.get("report_pdf")
        json_p = rec.get("report_json")
        if not pdf and not json_p:
            return None
        return {"pdf": pdf, "json": json_p}

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _local_path(self, investigation_id: str) -> str:
        return os.path.join(FORENSICS_OUTPUT_BASE, investigation_id, "investigation.json")

    def _save_local(self, investigation_id: str, data: dict):
        path = self._local_path(investigation_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _load_local(self, investigation_id: str) -> Optional[dict]:
        path = self._local_path(investigation_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)


# ── PDF Report Generator ───────────────────────────────────────────────────────

def _generate_pdf_report(investigation: dict, report_data: dict, output_path: str):
    """Generate a professional PDF forensic report using reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether,
        )

        TEAL   = colors.HexColor("#27504D")
        GREEN  = colors.HexColor("#0FEA7A")
        AMBER  = colors.HexColor("#D97706")
        RED    = colors.HexColor("#CC0000")
        LIGHT  = colors.HexColor("#F5F5F5")

        SEV_COLORS = {
            "critical": RED,
            "high":     AMBER,
            "medium":   colors.HexColor("#FFCC00"),
            "low":      colors.HexColor("#00CC00"),
            "info":     colors.HexColor("#2563EB"),
        }

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            leftMargin=18*mm, rightMargin=18*mm,
            topMargin=24*mm, bottomMargin=20*mm,
        )

        styles = getSampleStyleSheet()
        title_style  = ParagraphStyle("title",  parent=styles["Title"],
                                       textColor=colors.white, fontSize=22, leading=28, spaceAfter=4)
        h1_style     = ParagraphStyle("h1",     parent=styles["Heading1"],
                                       textColor=TEAL, fontSize=14, spaceAfter=6, spaceBefore=12)
        body_style   = ParagraphStyle("body",   parent=styles["Normal"],
                                       fontSize=10, leading=14, spaceAfter=4)
        label_style  = ParagraphStyle("label",  parent=styles["Normal"],
                                       fontSize=9, textColor=colors.HexColor("#4A4D4E"))
        small_style  = ParagraphStyle("small",  parent=styles["Normal"],
                                       fontSize=8, textColor=colors.HexColor("#666666"))

        story = []

        # ── Cover Block ──────────────────────────────────────────────────────
        cover_data = [
            [Paragraph("<font color='white'><b>FORENSIC INVESTIGATION REPORT</b></font>", title_style)],
            [Paragraph(f"<font color='white'>Investigation ID: {investigation.get('id', '')[:8]}...</font>",
                       ParagraphStyle("sub", parent=styles["Normal"], textColor=colors.white, fontSize=11))],
            [Paragraph(f"<font color='white'>Generated: {datetime.now().strftime('%d/%m/%Y %H:%M UTC')}</font>",
                       ParagraphStyle("sub2", parent=styles["Normal"], textColor=colors.white, fontSize=10))],
        ]
        cover_table = Table(cover_data, colWidths=[174*mm])
        cover_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL),
            ("TOPPADDING",    (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ]))
        story.append(cover_table)
        story.append(Spacer(1, 6*mm))

        # ── Investigation Summary ────────────────────────────────────────────
        story.append(Paragraph("Investigation Summary", h1_style))
        story.append(HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4))

        meta_rows = [
            ["Client ID",    investigation.get("client_id", "—")],
            ["Device",       investigation.get("device_hostname") or investigation.get("device_id") or "—"],
            ["OS",           investigation.get("device_os") or "—"],
            ["Scope",        str(investigation.get("scope", "quick_triage")).replace("_", " ").title()],
            ["Status",       str(investigation.get("status", "")).upper()],
            ["Initiated By", investigation.get("initiated_by", "—")],
            ["Reason",       investigation.get("reason", "—")],
            ["Started",      str(investigation.get("started_at", "—"))[:19]],
            ["Completed",    str(investigation.get("completed_at", "—"))[:19]],
            ["Findings",     str(investigation.get("finding_count", 0))],
            ["Critical",     str(investigation.get("critical_count", 0))],
            ["High",         str(investigation.get("high_count", 0))],
        ]
        meta_table = Table(
            [[Paragraph(f"<b>{r[0]}</b>", label_style), Paragraph(str(r[1]), body_style)] for r in meta_rows],
            colWidths=[40*mm, 134*mm],
        )
        meta_table.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 6*mm))

        # ── Consent Record ────────────────────────────────────────────────────
        story.append(Paragraph("POPIA Consent Record", h1_style))
        story.append(HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4))

        consent_rows = [
            ["Consent Granted",  "Yes" if investigation.get("consent_granted") else "NO — INVESTIGATION INVALID"],
            ["Obtained By",      investigation.get("consent_obtained_by", "—")],
            ["Method",           investigation.get("consent_method", "—")],
            ["Reference",        investigation.get("consent_reference", "—")],
            ["Timestamp",        str(investigation.get("consent_timestamp", "—"))[:19]],
        ]
        consent_table = Table(
            [[Paragraph(f"<b>{r[0]}</b>", label_style), Paragraph(str(r[1]), body_style)] for r in consent_rows],
            colWidths=[40*mm, 134*mm],
        )
        consent_table.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ]))
        story.append(consent_table)
        story.append(Spacer(1, 6*mm))

        # ── Task Results ─────────────────────────────────────────────────────
        tasks = report_data.get("tasks", [])
        if tasks:
            story.append(Paragraph("Tool Task Results", h1_style))
            story.append(HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4))
            task_header = [
                Paragraph("<b>Tool</b>", label_style),
                Paragraph("<b>Task Type</b>", label_style),
                Paragraph("<b>Status</b>", label_style),
                Paragraph("<b>Findings</b>", label_style),
                Paragraph("<b>Notes</b>", label_style),
            ]
            task_rows = [task_header]
            for t in tasks:
                status_color = GREEN if t.get("status") == "complete" else (AMBER if t.get("status") == "skipped" else RED)
                task_rows.append([
                    Paragraph(t.get("tool_id", ""), small_style),
                    Paragraph(t.get("task_type", ""), small_style),
                    Paragraph(f"<font color='#{status_color.hexval()[1:]}'><b>{t.get('status','').upper()}</b></font>", small_style),
                    Paragraph(str(t.get("finding_count", "—")), small_style),
                    Paragraph((t.get("summary") or t.get("reason") or t.get("error") or "")[:80], small_style),
                ])
            task_table = Table(task_rows, colWidths=[28*mm, 32*mm, 22*mm, 18*mm, 74*mm])
            task_table.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),   TEAL),
                ("TEXTCOLOR",     (0, 0), (-1, 0),   colors.white),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1),  [colors.white, LIGHT]),
                ("TOPPADDING",    (0, 0), (-1, -1),  4),
                ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
                ("LEFTPADDING",   (0, 0), (-1, -1),  4),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
            ]))
            story.append(task_table)
            story.append(Spacer(1, 6*mm))

        # ── Findings ─────────────────────────────────────────────────────────
        findings = report_data.get("findings", [])
        if findings:
            story.append(Paragraph(f"Findings ({len(findings)} total)", h1_style))
            story.append(HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4))

            for i, finding in enumerate(findings, 1):
                sev = str(finding.get("severity", "info")).lower()
                sev_col = SEV_COLORS.get(sev, colors.grey)
                block = [
                    [
                        Paragraph(f"<b>{i}. {finding.get('type', 'Indicator').replace('_', ' ').title()}</b>",
                                  ParagraphStyle("fh", parent=styles["Normal"], fontSize=10, textColor=TEAL)),
                        Paragraph(f"<b>{sev.upper()}</b>",
                                  ParagraphStyle("fs", parent=styles["Normal"], fontSize=9,
                                                 textColor=colors.white)),
                    ],
                    [Paragraph(finding.get("description", ""), body_style), ""],
                ]
                f_table = Table(block, colWidths=[148*mm, 26*mm])
                f_table.setStyle(TableStyle([
                    ("BACKGROUND",    (1, 0), (1, 0),   sev_col),
                    ("BACKGROUND",    (0, 0), (0, 0),   LIGHT),
                    ("SPAN",          (0, 1), (1, 1)),
                    ("TOPPADDING",    (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                    ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
                ]))
                story.append(KeepTogether(f_table))
                story.append(Spacer(1, 2*mm))
        else:
            story.append(Paragraph("Findings", h1_style))
            story.append(HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=4))
            story.append(Paragraph("No indicators of compromise were detected during this investigation.", body_style))
            story.append(Spacer(1, 4*mm))

        # ── POPIA Disclaimer ──────────────────────────────────────────────────
        story.append(Spacer(1, 4*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"<i>POPIA Notice: This report contains personal information collected under explicit "
            f"consent (POPIA Section 11). It is confidential and intended solely for the "
            f"authorised recipient. Retain for 3 years per ZA Support data governance policy. "
            f"Generated by Health Check AI — Forensics Module on "
            f"{datetime.now().strftime('%d/%m/%Y at %H:%M UTC')}.</i>",
            small_style,
        ))

        doc.build(story)
        logger.info(f"[forensics] PDF report generated: {output_path}")

    except Exception as exc:
        logger.error(f"[forensics] PDF generation failed: {exc}")
        # Write a plain text fallback
        with open(output_path.replace(".pdf", ".txt"), "w") as f:
            f.write(f"Forensic Investigation Report\n{'='*40}\n")
            f.write(json.dumps(report_data, indent=2, default=str))
