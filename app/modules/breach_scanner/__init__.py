"""
Compromised Data Scanner Module — Health Check v11

Retrospective endpoint forensic scanner that analyses local machine data
to detect indicators of compromise (IOCs). Scans the filesystem, installed
apps, browser extensions, email attachments, startup/persistence mechanisms,
running processes, and network connections — then corroborates every finding
against external threat intelligence (VirusTotal, AbuseIPDB, YARA signatures,
known-malware hash databases) to confirm or deny whether the finding is
malicious.

Key capabilities:
  - Filesystem deep scan: suspicious executables, hidden files, known malware
    paths, recently modified binaries, unsigned code
  - Email attachment analysis: Office macros, embedded executables, suspicious
    PDFs, password-protected archives, phishing link extraction
  - App & plugin audit: installed software vs known-compromised versions,
    browser extensions, third-party plugins, sideloaded apps
  - Persistence detection: launch agents/daemons, login items, cron jobs,
    startup programs, browser hijacks, scheduled tasks
  - Process & network inspection: running processes with unsigned binaries,
    connections to known C2 infrastructure, DNS anomalies, data exfil patterns
  - Threat intelligence corroboration: every finding cross-referenced against
    VirusTotal, AbuseIPDB, YARA rules, MITRE ATT&CK TTPs, and hash databases
  - POPIA consent gate: no scanning without recorded consent

Activate: add scanner_router to main.py with prefix /api/v1/breach-scanner
"""

MODULE_NAME = "breach_scanner"
MODULE_VERSION = "1.0.0"
