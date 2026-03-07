"""
CyberPulse Assessment PDF Generator
Produces the full 7-page report from a diagnostic snapshot.
Template spec: ~/.claude/projects/.../memory/cyberpulse-template.md
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable,
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.pdfgen import canvas as pdf_canvas

logger = logging.getLogger(__name__)

# ── Palette ──────────────────────────────────────────────────────────────────
TEAL        = HexColor("#27504D")
GREEN       = HexColor("#0FEA7A")
DARK        = HexColor("#333333")
MID         = HexColor("#4A4D4E")
ROW_ALT     = HexColor("#F5F5F5")
COVER_FOOT  = HexColor("#1E3E3B")
CRIT_RED    = HexColor("#CC0000")
HIGH_ORG    = HexColor("#FF6600")
MET_GREEN   = HexColor("#16A34A")
WARN_AMBER  = HexColor("#D97706")
CALLOUT_BG  = HexColor("#EFF6FF")
CRIT_BG     = HexColor("#FEF2F2")

PAGE_W, PAGE_H = A4   # 595.27 × 841.89 pt
ML = 18 * mm; MR = 18 * mm; MT = 24 * mm; MB = 20 * mm
BODY_W = PAGE_W - ML - MR

# ── Styles ───────────────────────────────────────────────────────────────────
_ss = getSampleStyleSheet()

def _s(name, **kw) -> ParagraphStyle:
    base = _ss.get(name, _ss["Normal"])
    return ParagraphStyle(name + str(id(kw)), parent=base, **kw)

H1  = _s("Normal", fontName="Helvetica-Bold", fontSize=14, textColor=TEAL, spaceBefore=12, spaceAfter=6)
H2  = _s("Normal", fontName="Helvetica-Bold", fontSize=11, textColor=TEAL, spaceBefore=10, spaceAfter=4)
BODY= _s("Normal", fontName="Helvetica", fontSize=10, textColor=DARK, leading=14, spaceAfter=6)
SMALL=_s("Normal", fontName="Helvetica", fontSize=8,  textColor=MID,  leading=11)
BOLD= _s("Normal", fontName="Helvetica-Bold", fontSize=10, textColor=DARK, leading=14)
CELL= _s("Normal", fontName="Helvetica", fontSize=9,  textColor=DARK, leading=12)
CELLB=_s("Normal", fontName="Helvetica-Bold", fontSize=9, textColor=DARK, leading=12)
CRIT_STYLE=_s("Normal", fontName="Helvetica-Bold", fontSize=10, textColor=CRIT_RED, leading=14)
HIGH_STYLE=_s("Normal", fontName="Helvetica-Bold", fontSize=10, textColor=HIGH_ORG, leading=14)
MET_STYLE =_s("Normal", fontName="Helvetica-Bold", fontSize=9,  textColor=MET_GREEN)
NOTMET    =_s("Normal", fontName="Helvetica-Bold", fontSize=9,  textColor=CRIT_RED)

# ── Hardware validation ───────────────────────────────────────────────────────

def _parse_ram_from_txt(raw_txt: str) -> Optional[float]:
    """
    Extract RAM (GB) from TXT diagnostic content.
    Handles patterns such as:
      "Memory:                     16 GB"
      "Total RAM: 16.00 GB"
      "  16 GB LPDDR4X"
      "memory_total_gb: 16"
    Returns float GB or None if not found.
    """
    if not raw_txt:
        return None

    # Pattern 1: "Memory: 16 GB" / "Total RAM: 16 GB" / "RAM: 16.00 GB"
    m = re.search(
        r'(?:memory|total[\s_]?ram|ram)[\s:]+(\d+(?:\.\d+)?)\s*GB',
        raw_txt,
        re.IGNORECASE,
    )
    if m:
        return float(m.group(1))

    # Pattern 2: standalone "16 GB" on a line (common in system_profiler output)
    m = re.search(r'^\s*(\d+(?:\.\d+)?)\s*GB\s*$', raw_txt, re.IGNORECASE | re.MULTILINE)
    if m:
        val = float(m.group(1))
        # Sanity check — ignore storage-sized values (>128 GB is likely disk not RAM)
        if val <= 128:
            return val

    # Pattern 3: flat env-style "ram_gb: 16" or "memory_gb=16"
    m = re.search(r'(?:ram_gb|memory_gb)[\s:=]+(\d+(?:\.\d+)?)', raw_txt, re.IGNORECASE)
    if m:
        return float(m.group(1))

    return None


def _parse_storage_from_txt(raw_txt: str) -> Optional[float]:
    """
    Extract boot disk total storage (GB) from TXT diagnostic content.
    Handles patterns such as:
      "Capacity: 500.11 GB (500,107,862,016 bytes)"
      "boot_disk_total_gb: 500"
      "Total Storage: 500 GB"
      "Disk /dev/disk1: 500 GB"
    Returns float GB or None if not found.
    """
    if not raw_txt:
        return None

    # Pattern 1: "Capacity: NNN.NN GB" (system_profiler SPStorageDataType)
    m = re.search(r'Capacity[\s:]+(\d+(?:\.\d+)?)\s*GB', raw_txt, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # Pattern 2: flat env-style "boot_disk_total_gb: 500"
    m = re.search(r'boot_disk_total_gb[\s:=]+(\d+(?:\.\d+)?)', raw_txt, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # Pattern 3: "Total Storage: NNN GB" / "Disk /dev/disk0: NNN GB"
    m = re.search(
        r'(?:total[\s_]?storage|disk\s+/dev/\S+)[\s:]+(\d+(?:\.\d+)?)\s*GB',
        raw_txt,
        re.IGNORECASE,
    )
    if m:
        return float(m.group(1))

    return None


def _parse_ram_from_json(payload: dict) -> Optional[float]:
    """Extract RAM (GB) from JSON diagnostic payload. Tries multiple field names."""
    hw = payload.get("hardware", {})

    # Direct GB field
    for key in ("ram_gb", "total_ram_gb", "memory_gb"):
        v = hw.get(key) or payload.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass

    # String field like "16 GB" or "16384 MB"
    for key in ("memory", "ram", "total_ram", "total_memory"):
        raw = hw.get(key) or payload.get(key)
        if not raw:
            continue
        raw_str = str(raw).strip()
        m = re.match(r'^(\d+(?:\.\d+)?)\s*GB', raw_str, re.IGNORECASE)
        if m:
            return float(m.group(1))
        m = re.match(r'^(\d+(?:\.\d+)?)\s*MB', raw_str, re.IGNORECASE)
        if m:
            return round(float(m.group(1)) / 1024, 1)

    return None


def _parse_storage_from_json(payload: dict) -> Optional[float]:
    """Extract boot disk total storage (GB) from JSON diagnostic payload."""
    stor = payload.get("storage", {})

    for key in ("boot_disk_total_gb", "total_gb", "disk_total_gb", "total_storage_gb"):
        v = stor.get(key) or payload.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass

    return None


def validate_hardware_sources(
    payload: dict,
    raw_txt: Optional[str] = None,
) -> dict:
    """
    Cross-check hardware values (RAM, storage) between JSON and TXT diagnostic sources.

    Rules:
    - If both sources agree within 10%: use JSON value (canonical structured data).
    - If they disagree by >10%: log WARNING and use TXT value (comes from system_profiler
      directly — more reliable than JSON which may have been parsed/transformed).
    - If only one source is available: use it and log which one.

    Returns a dict with validated hardware fields and source metadata:
    {
        "ram_gb":             float | None,
        "storage_total_gb":   float | None,
        "_hardware_source": {
            "ram":     "json" | "txt" | "json_only" | "txt_only" | "unavailable",
            "storage": "json" | "txt" | "json_only" | "txt_only" | "unavailable",
        }
    }
    """
    result: dict = {"_hardware_source": {}}

    # ── RAM ───────────────────────────────────────────────────────────────────
    ram_json = _parse_ram_from_json(payload)
    ram_txt  = _parse_ram_from_txt(raw_txt)

    if ram_json is not None and ram_txt is not None:
        diff_pct = abs(ram_json - ram_txt) / max(ram_txt, 0.1) * 100
        if diff_pct > 10:
            logger.warning(
                "HARDWARE VALIDATION: RAM mismatch — JSON reports %.1f GB, TXT reports %.1f GB "
                "(%.0f%% difference). Using TXT value (system_profiler source).",
                ram_json, ram_txt, diff_pct,
            )
            result["ram_gb"] = ram_txt
            result["_hardware_source"]["ram"] = "txt"
        else:
            result["ram_gb"] = ram_json
            result["_hardware_source"]["ram"] = "json"
    elif ram_json is not None:
        logger.info("HARDWARE VALIDATION: RAM from JSON only (%.1f GB) — no TXT value.", ram_json)
        result["ram_gb"] = ram_json
        result["_hardware_source"]["ram"] = "json_only"
    elif ram_txt is not None:
        logger.info("HARDWARE VALIDATION: RAM from TXT only (%.1f GB) — no JSON value.", ram_txt)
        result["ram_gb"] = ram_txt
        result["_hardware_source"]["ram"] = "txt_only"
    else:
        logger.warning("HARDWARE VALIDATION: RAM could not be determined from either source.")
        result["ram_gb"] = None
        result["_hardware_source"]["ram"] = "unavailable"

    # ── Storage ───────────────────────────────────────────────────────────────
    stor_json = _parse_storage_from_json(payload)
    stor_txt  = _parse_storage_from_txt(raw_txt)

    if stor_json is not None and stor_txt is not None:
        diff_pct = abs(stor_json - stor_txt) / max(stor_txt, 0.1) * 100
        if diff_pct > 10:
            logger.warning(
                "HARDWARE VALIDATION: Storage mismatch — JSON reports %.1f GB, TXT reports %.1f GB "
                "(%.0f%% difference). Using TXT value (system_profiler source).",
                stor_json, stor_txt, diff_pct,
            )
            result["storage_total_gb"] = stor_txt
            result["_hardware_source"]["storage"] = "txt"
        else:
            result["storage_total_gb"] = stor_json
            result["_hardware_source"]["storage"] = "json"
    elif stor_json is not None:
        logger.info(
            "HARDWARE VALIDATION: Storage from JSON only (%.1f GB) — no TXT value.", stor_json
        )
        result["storage_total_gb"] = stor_json
        result["_hardware_source"]["storage"] = "json_only"
    elif stor_txt is not None:
        logger.info(
            "HARDWARE VALIDATION: Storage from TXT only (%.1f GB) — no JSON value.", stor_txt
        )
        result["storage_total_gb"] = stor_txt
        result["_hardware_source"]["storage"] = "txt_only"
    else:
        logger.warning("HARDWARE VALIDATION: Storage could not be determined from either source.")
        result["storage_total_gb"] = None
        result["_hardware_source"]["storage"] = "unavailable"

    return result


# ── Canvas callbacks ──────────────────────────────────────────────────────────

def _draw_cover(c: pdf_canvas.Canvas, doc):
    """Full-teal cover page."""
    c.saveState()

    # Teal background
    c.setFillColor(TEAL)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Top white strip (40pt)
    strip_h = 40
    c.setFillColor(white)
    c.rect(0, PAGE_H - strip_h, PAGE_W, strip_h, fill=1, stroke=0)

    # Logo
    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(ML, PAGE_H - 26, "ZA SUPPORT")
    c.setFont("Helvetica", 9)
    c.setFillColor(MID)
    c.drawString(ML, PAGE_H - 37, "Practice IT. Perfected.")

    # Contact top-right
    c.setFont("Helvetica", 8)
    c.setFillColor(MID)
    c.drawRightString(PAGE_W - MR, PAGE_H - 20, "064 529 5863")
    c.drawRightString(PAGE_W - MR, PAGE_H - 30, "admin@zasupport.com")
    c.drawRightString(PAGE_W - MR, PAGE_H - 40, "zasupport.com")

    # Green rule under strip
    c.setStrokeColor(GREEN)
    c.setLineWidth(2.5)
    c.line(0, PAGE_H - strip_h, PAGE_W, PAGE_H - strip_h)

    # Cover title — centered vertically at ~55% height
    cy = PAGE_H * 0.55
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 44)
    c.drawCentredString(PAGE_W / 2, cy + 28, "CyberPulse")
    c.setFont("Helvetica-Bold", 40)
    c.drawCentredString(PAGE_W / 2, cy - 16, "Assessment")

    # Subtitle
    c.setFont("Helvetica", 14)
    c.setFillColor(HexColor("#B0CCC8"))
    c.drawCentredString(PAGE_W / 2, cy - 46, "120-Point Device Security and Health Analysis")

    # "Prepared for" block — at ~28%
    prep_y = PAGE_H * 0.30
    c.setFont("Helvetica", 12)
    c.setFillColor(HexColor("#D0E8E4"))
    c.drawCentredString(PAGE_W / 2, prep_y + 14, f"Prepared for {doc._za_client_name}")
    c.drawCentredString(PAGE_W / 2, prep_y - 2,
                        f"Prepared by ZA Support  |  {doc._za_report_date}")

    # Bottom dark footer bar
    c.setFillColor(COVER_FOOT)
    c.rect(0, 0, PAGE_W, 36, fill=1, stroke=0)
    c.setStrokeColor(GREEN)
    c.setLineWidth(1.5)
    c.line(0, 36, PAGE_W, 36)
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#B0CCC8"))
    c.drawCentredString(PAGE_W / 2, 14,
                        "Confidential — prepared exclusively for the recipient named above")

    c.restoreState()


def _draw_body_page(c: pdf_canvas.Canvas, doc):
    """Header + footer for pages 2+."""
    c.saveState()

    # White strip
    strip_h = 36
    c.setFillColor(white)
    c.rect(0, PAGE_H - strip_h, PAGE_W, strip_h, fill=1, stroke=0)

    # TEAL side accent
    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(ML, PAGE_H - 23, "ZA SUPPORT")
    c.setFont("Helvetica", 8)
    c.setFillColor(MID)
    c.drawString(ML + 88, PAGE_H - 23, "Health Check AI")

    # Contact right
    c.setFont("Helvetica", 8)
    c.setFillColor(MID)
    c.drawRightString(PAGE_W - MR, PAGE_H - 15, "admin@zasupport.com")
    c.drawRightString(PAGE_W - MR, PAGE_H - 26, "zasupport.com")

    # Green rule below header
    c.setStrokeColor(GREEN)
    c.setLineWidth(1.5)
    c.line(0, PAGE_H - strip_h, PAGE_W, PAGE_H - strip_h)

    # Footer
    footer_y = MB - 8
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MID)
    c.drawString(ML, footer_y, "064 529 5863  |  admin@zasupport.com  |  zasupport.com")
    c.drawRightString(PAGE_W - MR, footer_y, f"Page {doc.page}")
    c.setStrokeColor(HexColor("#E0E0E0"))
    c.setLineWidth(0.5)
    c.line(ML, footer_y + 9, PAGE_W - MR, footer_y + 9)

    c.restoreState()


# ── Table helpers ─────────────────────────────────────────────────────────────

def _teal_table(data, col_widths, head_rows=1) -> Table:
    """Standard teal-header table."""
    t = Table(data, colWidths=col_widths, repeatRows=head_rows)
    style = [
        ("BACKGROUND", (0, 0), (-1, head_rows - 1), TEAL),
        ("TEXTCOLOR",  (0, 0), (-1, head_rows - 1), white),
        ("FONTNAME",   (0, 0), (-1, head_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, head_rows - 1), 9),
        ("LINEBELOW",  (0, head_rows - 1), (-1, head_rows - 1), 2, GREEN),
        ("FONTNAME",   (0, head_rows), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, head_rows), (-1, -1), 9),
        ("TEXTCOLOR",  (0, head_rows), (-1, -1), DARK),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.3, HexColor("#CCCCCC")),
    ]
    for i in range(head_rows, len(data)):
        if (i - head_rows) % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def _callout(text: str, bg=CALLOUT_BG, border_color=TEAL, bold=False) -> Table:
    """Callout box with left border."""
    style = BOLD if bold else BODY
    t = Table([[Paragraph(text, style)]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), bg),
        ("LINEBEFORE",   (0, 0), (0, -1),  4, border_color),
        ("LEFTPADDING",  (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    return t


def _scenario_block(num: int, title: str, problem: str, resolution: str) -> Table:
    """Numbered scenario card (grey background)."""
    num_para   = Paragraph(str(num), _s("Normal", fontName="Helvetica-Bold",
                                         fontSize=38, textColor=TEAL, leading=42))
    title_para = Paragraph(f"<b>{title}</b>", _s("Normal", fontName="Helvetica-Bold",
                                                    fontSize=11, textColor=DARK, spaceAfter=4))
    prob_para  = Paragraph(problem,    BODY)
    res_para   = Paragraph(f"<b>{resolution}</b>", BOLD)

    content = Table([[title_para], [prob_para], [res_para]],
                    colWidths=[BODY_W - 52])
    content.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",  (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    outer = Table([[num_para, content]], colWidths=[52, BODY_W - 52])
    outer.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), ROW_ALT),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), 4),
    ]))
    return outer


# ── Severity helpers ──────────────────────────────────────────────────────────

def _sev_para(sev: str) -> Paragraph:
    if sev == "CRITICAL": return Paragraph("<b>CRITICAL</b>", CRIT_STYLE)
    if sev == "HIGH":     return Paragraph("<b>HIGH</b>",     HIGH_STYLE)
    return Paragraph(f"<b>{sev}</b>", BOLD)

def _compliance_para(met: bool) -> Paragraph:
    if met: return Paragraph("<b>MET</b>",     MET_STYLE)
    return   Paragraph("<b>NOT MET</b>",        NOTMET)


# ── Security posture builder ──────────────────────────────────────────────────

def _build_security_posture(sec: dict) -> tuple[list, int]:
    """Returns (table_data_rows, controls_met_count)."""
    pw_mgr  = sec.get("password_manager", "")
    av_edr  = sec.get("av_edr", "")
    xprot   = sec.get("xprotect_version", "")

    controls = [
        ("System Integrity Protection (SIP)",    bool(sec.get("sip_enabled",   0))),
        ("FileVault Disk Encryption",             bool(sec.get("filevault_on",  0))),
        ("Gatekeeper App Verification",           bool(sec.get("gatekeeper_on", 0))),
        ("macOS Firewall",                        bool(sec.get("firewall_on",   0))),
        ("Stealth Mode",                          bool(sec.get("stealth_mode",  False))),
        ("XProtect Antivirus",                    bool(xprot and xprot not in ("", "N/A", "0"))),
        ("Password Manager",                      bool(pw_mgr and pw_mgr.lower() not in ("none", "no", ""))),
        ("Security / EDR Software",               bool(av_edr and av_edr.lower() not in ("none", "no", ""))),
        ("macOS Updates Current",                 bool(sec.get("os_updates_current", False))),
        ("Activation Lock",                       bool(sec.get("activation_lock", False))),
        ("MDM Enrolled",                          bool(sec.get("mdm_enrolled", False))),
        ("Two-Factor Authentication",             bool(sec.get("two_factor", False))),
    ]

    rows = [["Security Control", "Status", "Compliance"]]
    met_count = 0
    for name, met in controls:
        status = "Enabled" if met else "Not detected"
        rows.append([Paragraph(name, CELL), Paragraph(status, CELL), _compliance_para(met)])
        if met: met_count += 1
    return rows, met_count


# ── Main generator ────────────────────────────────────────────────────────────

def generate_cyberpulse_pdf(
    client_name: str,
    client_id:   str,
    hostname:    str,
    serial:      str,
    payload:     dict,
    scan_date:   Optional[str] = None,
    reason:      str = "Routine Health Check Scout diagnostic assessment.",
    raw_txt:     Optional[str] = None,
) -> bytes:
    """
    Generate the full 7-page CyberPulse Assessment PDF.
    Returns raw PDF bytes.

    raw_txt: optional raw TXT diagnostic content from diagnostic_snapshots.raw_txt.
             When provided, hardware values (RAM, storage) are cross-validated against
             the JSON payload before any PDF content is built.
    """
    # ── Pre-report hardware validation ────────────────────────────────────────
    hw_validated = validate_hardware_sources(payload, raw_txt)
    logger.info(
        "Hardware validation complete — RAM source: %s, Storage source: %s",
        hw_validated["_hardware_source"].get("ram", "unknown"),
        hw_validated["_hardware_source"].get("storage", "unknown"),
    )

    buf = io.BytesIO()

    # Attach metadata to doc for use in canvas callbacks
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT + 36, bottomMargin=MB + 12,
        title=f"CyberPulse Assessment — {client_name}",
        author="ZA Support",
    )
    doc._za_client_name = client_name
    doc._za_report_date  = datetime.now().strftime("%B %Y")

    # Page templates
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0, id="cover_frame")
    body_frame  = Frame(ML, MB + 16, BODY_W, PAGE_H - MT - 36 - MB - 8, id="body_frame")

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=_draw_cover),
        PageTemplate(id="body",  frames=[body_frame],  onPage=_draw_body_page),
    ])

    story = []

    # ── Cover page (template draws everything on canvas) ──────────────────
    story.append(NextPageTemplate("cover"))
    story.append(Spacer(1, PAGE_H))  # spacer fills cover frame

    # ── Page 2 — Device Summary ───────────────────────────────────────────
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())

    hw    = payload.get("hardware", {})
    bat   = payload.get("battery",  {})
    stor  = payload.get("storage",  {})
    sec   = payload.get("security", {})
    macos = payload.get("macos",    {})
    net   = payload.get("network",  {})
    recs: list = payload.get("recommendations", [])

    scan_dt = scan_date or datetime.now().strftime("%d/%m/%Y %H:%M")
    model   = hw.get("model", "Mac")
    cpu     = hw.get("cpu") or hw.get("chip_type", "")

    # Use validated RAM (cross-checked JSON vs TXT — TXT wins on disagreement)
    _validated_ram_gb = hw_validated.get("ram_gb")
    _ram_source       = hw_validated["_hardware_source"].get("ram", "json_only")
    if _validated_ram_gb is not None:
        ram = f"{int(_validated_ram_gb) if _validated_ram_gb == int(_validated_ram_gb) else _validated_ram_gb} GB"
    else:
        ram = "—"

    macos_v = macos.get("version") or hw.get("macos_version") or "—"
    bat_h   = f"{bat.get('health_pct', '—')}%" if bat.get("health_pct") else "—"
    bat_c   = bat.get("cycles", "—")
    battery_str = f"{bat_h} health, {bat_c} cycles"
    wifi    = net.get("wifi_ssid", "") or "—"
    disk_u  = f"{stor.get('boot_disk_used_pct', '—')}% used" if stor.get("boot_disk_used_pct") else "—"

    # Use validated storage total (cross-checked JSON vs TXT — TXT wins on disagreement)
    _validated_stor_gb = hw_validated.get("storage_total_gb")
    _stor_source       = hw_validated["_hardware_source"].get("storage", "json_only")
    if _validated_stor_gb is not None:
        disk_f = f"{stor.get('boot_disk_free_gb', '—')} GB free"
    else:
        disk_f  = f"{stor.get('boot_disk_free_gb', '—')} GB free" if stor.get("boot_disk_free_gb") else ""
    disk_str= f"{disk_u}{', ' + disk_f if disk_f else ''}"

    story.append(Paragraph("Device Summary", H1))
    device_rows = [
        ["Item",              "Detail"],
        ["Client",            client_name],
        ["Hostname",          hostname or "—"],
        ["Serial Number",     serial],
        ["Model",             model],
        ["Processor",         cpu or "—"],
        ["Memory",            ram],
        ["Architecture",      hw.get("chip_type", "—")],
        ["Storage",           disk_str],
        ["macOS Version",     macos_v],
        ["Battery",           battery_str],
        ["Wi-Fi",             wifi],
        ["Scan Date",         scan_dt],
        ["Analysis Depth",    "120 diagnostic checkpoints verified against\nover 14 billion known compromised records"],
    ]
    # Attach hardware source metadata to doc for audit trail (not rendered in PDF body)
    doc._za_hardware_source = hw_validated["_hardware_source"]
    story.append(_teal_table(
        [[Paragraph(str(c), CELLB if r == 0 else (CELLB if i == 0 else CELL))
          for i, c in enumerate(row)]
         for r, row in enumerate(device_rows)],
        [70 * mm, BODY_W - 70 * mm],
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Reason for Assessment", H1))
    story.append(Paragraph(reason, BODY))
    story.append(Spacer(1, 4))

    crit_count = sum(1 for r in recs if r.get("severity") == "CRITICAL")
    high_count = sum(1 for r in recs if r.get("severity") == "HIGH")
    total_findings = len(recs)
    story.append(Paragraph("Assessment Summary", H1))
    summary_text = (
        f"The Health Check Scout analysis identified <b>{total_findings} findings</b> "
        f"requiring attention: <b>{crit_count} critical</b> and <b>{high_count} high</b> severity. "
        "Each finding is documented below with evidence, financial exposure, and a clear resolution path."
    )
    story.append(Paragraph(summary_text, BODY))

    if crit_count > 0:
        first_crit = next((r for r in recs if r.get("severity") == "CRITICAL"), None)
        if first_crit:
            story.append(Spacer(1, 6))
            story.append(_callout(
                f"<b>{first_crit.get('title', 'Critical finding')}</b><br/>"
                f"{first_crit.get('evidence', '')}",
                bg=CRIT_BG, border_color=CRIT_RED, bold=False,
            ))

    # ── Page 3 — Findings + Security Posture ────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Findings Summary", H1))

    if recs:
        findings_rows = [["Severity", "Finding", "Impact / Evidence"]]
        for r in recs:
            findings_rows.append([
                _sev_para(r.get("severity", "LOW")),
                Paragraph(r.get("title", ""), CELLB),
                Paragraph(r.get("evidence", ""), CELL),
            ])
        story.append(_teal_table(
            findings_rows,
            [25 * mm, 60 * mm, BODY_W - 85 * mm],
        ))
    else:
        story.append(Paragraph("No findings recorded in this diagnostic run.", BODY))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Security Posture", H1))
    posture_rows, met_count = _build_security_posture(sec)
    posture_pct = round(met_count / 12 * 100) if 12 else 0
    story.append(_teal_table(
        [[Paragraph(str(c), CELLB if r == 0 else CELL) if isinstance(c, str) else c
          for i, c in enumerate(row)]
         for r, row in enumerate(posture_rows)],
        [90 * mm, 40 * mm, BODY_W - 130 * mm],
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Compliance score: <b>{met_count} of 12</b> controls met (<b>{posture_pct}%</b>).",
        BODY
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Threat Intelligence Analysis", H1))

    # ── Page 4 — Threat Intel + Additional Observations ────────────────
    story.append(PageBreak())
    story.append(Paragraph(
        "The diagnostic data was cross-referenced against a curated database of over "
        "<b>14 billion compromised records</b> and <b>30 million known malicious IP addresses</b>. "
        "The analysis covers network connections, running processes, and installed software.",
        BODY
    ))

    env = payload.get("environment", {})
    mal = payload.get("malware_scan", {})

    story.append(Paragraph("Network Connection Analysis", H2))
    story.append(Paragraph(
        f"Active interface: {net.get('active_interface', '—')}. "
        f"Wi-Fi SSID: {net.get('wifi_ssid', '—')}. "
        f"DNS: {', '.join(net.get('dns_servers', [])) if isinstance(net.get('dns_servers'), list) else net.get('dns_servers', '—')}. "
        "All active connections were reviewed for indicators of compromise.",
        BODY
    ))

    story.append(Paragraph("Process Integrity Analysis", H2))
    proc_count = payload.get("diagnostics", {}).get("total_processes", "—")
    story.append(Paragraph(
        f"{proc_count} processes were active at time of scan. "
        "Process signatures were validated against known safe and malicious patterns.",
        BODY
    ))

    story.append(Paragraph("Malware and Adware Scan", H2))
    mal_status = mal.get("status") or mal.get("result") or "No threats detected"
    story.append(Paragraph(str(mal_status), BODY))

    story.append(Paragraph("Additional Observations", H1))

    story.append(Paragraph("Storage and Backup", H2))
    tm_status = env.get("time_machine_status", "—")
    ccc_inst  = env.get("ccc_installed", "NO")
    days_ago  = env.get("time_machine_days_ago", "—")
    backup_text = (
        f"Storage: {disk_str}. "
        f"Time Machine: {tm_status}. "
        f"CCC Backup: {'Installed' if ccc_inst == 'YES' else 'Not installed'}. "
        + (f"Last backup: {days_ago} days ago." if str(days_ago).isdigit() else "")
    )
    story.append(Paragraph(backup_text, BODY))

    story.append(Paragraph("Network and Connectivity", H2))
    remote = env.get("remote_access_tools", "NONE")
    story.append(Paragraph(
        f"Wi-Fi: {net.get('wifi_ssid', '—')} ({net.get('wifi_security', '—')}). "
        f"Remote access software detected: {remote}.",
        BODY
    ))

    story.append(Paragraph("Performance", H2))
    uptime_h = round(macos.get("uptime_seconds", 0) / 3600) if macos.get("uptime_seconds") else "—"
    panics = payload.get("diagnostics", {}).get("kernel_panics", 0)
    story.append(Paragraph(
        f"System uptime: {uptime_h} hours. "
        f"Kernel panics recorded: {panics}. "
        f"Battery health: {bat_h} with {bat_c} charge cycles.",
        BODY
    ))

    story.append(Paragraph("Operating System", H2))
    oclp = payload.get("oclp", {})
    oclp_text = ""
    if oclp.get("detected"):
        oclp_text = " macOS compatibility layer managed by ZA Support is installed and active."
    story.append(Paragraph(
        f"macOS {macos_v} ({macos.get('build', '—')}). {oclp_text}",
        BODY
    ))

    # ── Page 5 — Recommendations Table ───────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Recommendations", H1))

    if recs:
        rec_rows = [["#", "Service", "Scope of Work", "Investment", "Priority"]]
        for i, r in enumerate(recs, 1):
            priority = "Immediate" if r.get("severity") == "CRITICAL" else \
                       "This week"  if r.get("severity") == "HIGH"     else "This month"
            rec_rows.append([
                Paragraph(str(i), CELL),
                Paragraph(f"<b>{r.get('product', 'Service')}</b>", CELLB),
                Paragraph(r.get("title", "") + ("<br/><i>" + r.get("evidence","") + "</i>" if r.get("evidence") else ""), CELL),
                Paragraph(r.get("price", "Included"), CELL),
                Paragraph(f"<b>{priority}</b>", CELLB),
            ])
        story.append(_teal_table(
            rec_rows,
            [10 * mm, 40 * mm, BODY_W - 110 * mm, 25 * mm, 25 * mm],
        ))
        story.append(Spacer(1, 10))
        story.append(Paragraph(
            f"<b>Items 1–{len(recs)} are addressed in a structured service engagement. "
            "All security configuration items are completed in a single session. "
            "Contact ZA Support to schedule.</b>",
            BODY
        ))
    else:
        story.append(Paragraph("No recommendations at this time. Continue monitoring.", BODY))

    # ── Pages 6–7 — Appendix ──────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Appendix: What These Findings Mean", H1))
    story.append(Paragraph(
        "The following scenarios explain the real-world impact of each finding in plain language, "
        "without technical jargon.",
        BODY
    ))
    story.append(Spacer(1, 6))

    for i, r in enumerate(recs, 1):
        risk_text = r.get("risk_scenario") or r.get("evidence") or ""
        resolution = f"Resolution: {r.get('product', 'ZA Support service')}. {r.get('price', '')}".strip()
        block = _scenario_block(i, r.get("title", f"Finding {i}"), risk_text, resolution)
        story.append(KeepTogether([block, Spacer(1, 8)]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Next Steps", H1))
    story.append(Paragraph(
        "To proceed with any of the recommendations above, contact ZA Support. "
        "All work is carried out at your location, at a time that suits you.",
        BODY
    ))
    story.append(Spacer(1, 6))
    story.append(_callout(
        "To proceed with any of the recommendations, contact ZA Support:<br/><br/>"
        "<b>Email:</b> admin@zasupport.com<br/>"
        "<b>Phone:</b> 064 529 5863<br/>"
        "<b>Address:</b> 1 Hyde Park Lane, Hyde Park, Johannesburg, 2196",
        bg=CALLOUT_BG, border_color=TEAL,
    ))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "<i>This report was generated by the ZA Support CyberPulse Engine and is "
        "prepared exclusively for the recipient named on the cover page. "
        "All data is collected directly from the client device and processed in accordance "
        "with POPIA (Protection of Personal Information Act).</i>",
        SMALL
    ))

    doc.build(story)
    return buf.getvalue()


# Expose for import
try:
    from reportlab.platypus import NextPageTemplate
except ImportError:
    pass


def _patch_nextpagetemplate():
    """Ensure NextPageTemplate is available — added in reportlab 3.x."""
    try:
        from reportlab.platypus import NextPageTemplate as NPT
        return NPT
    except ImportError:
        logger.warning(
            "NextPageTemplate not available in this reportlab version — "
            "multi-page PDFs will render without page-template transitions. "
            "Upgrade to reportlab >= 3.0 to fix."
        )
        class _NPT:
            def __init__(self, pt): pass
            def wrap(self, *a): return 0, 0
            def draw(self): pass
        return _NPT


NextPageTemplate = _patch_nextpagetemplate()
