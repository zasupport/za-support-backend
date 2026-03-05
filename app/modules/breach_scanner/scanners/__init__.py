"""
Device-side scanners — each inspects a specific attack surface on the endpoint.

All scanners produce list[RawFinding] and are orchestrated by scan_orchestrator.py.
Designed to run via the Health Check agent on macOS, Windows, and Linux.
"""

from .filesystem_scanner import FilesystemScanner
from .email_scanner import EmailScanner
from .app_auditor import AppAuditor
from .persistence_scanner import PersistenceScanner
from .process_scanner import ProcessScanner
from .network_scanner import NetworkScanner

__all__ = [
    "FilesystemScanner",
    "EmailScanner",
    "AppAuditor",
    "PersistenceScanner",
    "ProcessScanner",
    "NetworkScanner",
]
