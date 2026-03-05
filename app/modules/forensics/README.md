# Forensics Module — Health Check AI

**Software-only forensic analysis as an optional Health Check module.**

---

## What This Module Does

When a client machine shows signs of compromise, ransomware, data exfiltration, or policy violation, this module runs a structured forensic analysis using established open-source tools and produces a report you can use for incident response, POPIA notification decisions, or disciplinary processes.

It does not replace a forensic specialist. It captures, organises, and presents indicators — a qualified person reviews them.

---

## What It Does NOT Do

- **Hardware forensics** — write-blockers, chip-level extraction, and physical evidence handling are coordinated separately at the time of the investigation.
- **Confirm incidents** — all findings are labelled as indicators requiring human review.
- **Bypass POPIA** — consent is required before any data collection begins, and the consent record is permanent.

---

## Tools Included (30+)

| Category | Tools |
|---|---|
| Memory Forensics | Volatility 3, WinPmem |
| Disk & File System | Sleuth Kit (TSK), Foremost, PhotoRec, Bulk Extractor, dc3dd, dcfldd, ddrescue |
| Timeline Analysis | Plaso (log2timeline) |
| Network Forensics | TShark/Wireshark, tcpdump, Nmap, Zeek |
| Malware Analysis | YARA, ClamAV, strings, Binwalk, ssdeep, pefile, python-magic, exiftool |
| Log Analysis | Chainsaw (Windows events), python-evtx, Loki IoC scanner |
| Live System | osquery, Velociraptor, artifactcollector |
| Registry Analysis | RegRipper, regipy, python-registry |
| macOS Artifacts | mac_apt, OSXCollector |
| Hashing & Integrity | sha256sum, hashdeep, rhash |
| Python Libraries | dfvfs, pytsk3, libregf, libevtx, liblnk, libscca, construct |

The module detects which tools are installed and gracefully skips tools that are not available. You can install tools incrementally.

---

## Module Structure

```
app/modules/forensics/
├── __init__.py              # Public API, activation flag
├── router.py                # FastAPI endpoints
├── models.py                # Database models + Pydantic schemas
├── service.py               # Investigation orchestration
├── tool_registry.py         # Tool catalogue + availability detection
├── tools/
│   └── wrappers.py          # Individual tool implementations
├── collectors/
│   └── live_collector.py    # Volatile evidence collection (RAM-first order)
└── reports/
    └── report_generator.py  # PDF + JSON + text report generation

migrations/
└── forensics_001_initial.sql  # Database migration (run once to activate)

install_tools.sh               # Tool installation script
```

---

## Activation

### Step 1 — Run the database migration

```bash
psql $DATABASE_URL < migrations/forensics_001_initial.sql
```

### Step 2 — Install forensic tools on the server

```bash
chmod +x install_tools.sh
sudo ./install_tools.sh
```

Install only a category:
```bash
sudo ./install_tools.sh memory
sudo ./install_tools.sh disk
sudo ./install_tools.sh network
sudo ./install_tools.sh malware
sudo ./install_tools.sh live
```

### Step 3 — Add the router to your main FastAPI app

In `main.py` (or wherever you configure Health Check AI routes):

```python
from app.modules.forensics import forensics_router, FORENSICS_AVAILABLE

if FORENSICS_AVAILABLE:
    app.include_router(
        forensics_router,
        prefix="/api/v1/forensics",
        tags=["Forensics"]
    )
```

Or unconditionally if the module is always deployed:

```python
from app.modules.forensics import forensics_router
app.include_router(forensics_router, prefix="/api/v1/forensics", tags=["Forensics"])
```

### Step 4 — Verify tools are detected

```
GET /api/v1/forensics/tools/summary
```

---

## Investigation Workflow

Every investigation follows this lifecycle. The consent gate cannot be bypassed.

```
1. POST /api/v1/forensics/investigations
   → Creates investigation in PENDING state
   → No data collected yet

2. POST /api/v1/forensics/investigations/{id}/consent
   → Records POPIA consent (who obtained it, how, reference number)
   → Advances to CONSENT_GRANTED
   → This record is permanent

3. POST /api/v1/forensics/investigations/{id}/start
   → Begins analysis in background
   → Evidence collected volatile-first: RAM → processes → network → disk
   → Advances to RUNNING then COMPLETE

4. GET /api/v1/forensics/investigations/{id}
   → Poll for status and findings summary

5. POST /api/v1/forensics/investigations/{id}/report
   → Generates PDF + JSON + text report
   → All with ZA Support branding and POPIA disclaimer

6. GET /api/v1/forensics/investigations/{id}/report/pdf
   → Download the PDF report
```

---

## Analysis Scopes

| Scope | Duration | What Runs |
|---|---|---|
| `quick_triage` | 5–10 min | osquery, YARA, strings, short network capture, integrity hashing |
| `standard` | 30–60 min | + Sleuth Kit disk analysis, Bulk Extractor |
| `deep` | 2+ hours | + Volatility memory analysis, Foremost file carving |

---

## Evidence Collection Order

The collector always captures volatile evidence first (it disappears when the machine is rebooted or powered off):

1. Running processes
2. Network connections + ARP + routing
3. Open files
4. Logged-in users + login history
5. Startup items / persistence mechanisms
6. Shell history
7. System information + installed software
8. DNS configuration
9. Recently modified files (last 7 days)
10. System logs (auth, syslog, firewall)

---

## Report Output

Each report includes:

- **Investigation header** — scope, client, device, initiated by, reason
- **Consent record** — who obtained consent, method, reference, timestamp
- **Chain of custody manifest** — SHA-256 hash of every collected artifact
- **Findings summary** — count by severity (critical / high / medium / low / info)
- **Executive summary** — plain language, written for a non-technical reader
- **Detailed findings** — each indicator with source tool, raw evidence line, severity
- **Tool results table** — which tools ran, duration, exit code, summary
- **POPIA disclaimer** — findings are indicators, not confirmed incidents; confidential

---

## POPIA Compliance Notes

- **Consent gate**: The service layer raises `PermissionError` if `consent_granted = False`. This cannot be bypassed.
- **Consent record**: Fields `consent_timestamp`, `consent_obtained_by`, `consent_method`, `consent_reference` are set once and never updated.
- **Audit log**: Every action (consent recorded, analysis started, finding reviewed, report generated) is logged to `forensic_audit_log`. This table is append-only — never grant UPDATE or DELETE to the application role.
- **Data minimisation**: Define a retention policy for forensic reports. POPIA requires you only keep personal information for as long as necessary.
- **Report handling**: Reports contain personal information. Treat them as confidential documents subject to POPIA.

---

## Things to Complete Before Production

The following items require decisions based on your specific deployment:

1. **Role-based access control** — Who in Health Check AI can create investigations? Who can view findings? Who can generate reports? Integrate with your existing auth system.

2. **POPIA consent form** — Create a standardised written consent form for clients to sign. The module records the reference number — the physical or digital form is your responsibility.

3. **Report retention policy** — Decide how long forensic reports are kept. Implement automated deletion or archiving.

4. **Evidence storage location** — The `output_directory` defaults to `/var/lib/healthcheck/forensics/`. For production, this should be on encrypted, access-controlled storage.

5. **Notification workflow** — If findings indicate a POPIA data breach, you need a process to notify the Information Regulator within 72 hours. The report provides the evidence; the notification workflow is separate.

6. **Scope for your use cases** — Define clearly: is this for incident response on client machines, workshop diagnostics for devices in for repair, or internal investigations? Each has different consent requirements and legal weight.

---

## Integration with Health Check AI

The module links to existing Health Check AI records via `client_id` and `device_id` fields. These are string references — implement the foreign key joins based on your core schema.

Suggested integration trigger (add to Health Check AI alert handling):

```python
# When a device raises a CRITICAL security alert
if alert.category == "security" and alert.severity == "critical":
    # Log that forensic investigation is available
    # Do NOT auto-start — always require human decision + consent
    notify_account_manager(
        client_id=alert.client_id,
        device_id=alert.device_id,
        message=f"Critical security alert on {alert.device_hostname}. "
                f"Forensic investigation available via Health Check. "
                f"Requires client consent before analysis can begin."
    )
```

---

*Forensics Module — Health Check AI | ZA Support | Practice IT. Perfected.*
*admin@zasupport.com | 064 529 5863 | 1 Hyde Park Lane, Hyde Park, Johannesburg, 2196*
