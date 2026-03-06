"""
CyberShield PDF Report Generator — 4-page monthly security report.
Follows the confirmed template spec from cybershield-template.md.
"""
import io
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.pdfgen import canvas as canvas_module

# ── Colours ───────────────────────────────────────────────────────────────────
TEAL    = colors.HexColor("#27504D")
GREEN   = colors.HexColor("#0FEA7A")
DARK    = colors.HexColor("#333333")
MID     = colors.HexColor("#4A4D4E")
ROW_ALT = colors.HexColor("#E8F4F3")
RED     = colors.HexColor("#CC0000")
MET_GREEN = colors.HexColor("#16A34A")

# ── Page constants ────────────────────────────────────────────────────────────
L_MARGIN = 20 * mm
R_MARGIN = 20 * mm
T_MARGIN = 15 * mm
B_MARGIN = 15 * mm
PAGE_W, PAGE_H = A4

BODY_W = PAGE_W - L_MARGIN - R_MARGIN

FEATURES = [
    ("Advanced Threat Detection", "Real-time network monitoring identifies suspicious traffic, intrusion attempts and malware communications before they reach your practice."),
    ("Patient Data Protection", "Continuous monitoring for unauthorised data exfiltration — alerts trigger immediately if diagnostic images or patient records attempt to leave your network."),
    ("24/7 Network Monitoring", "ZA Support monitors your network around the clock. Critical alerts are escalated immediately; routine issues are addressed at next business day."),
    ("Breach Prevention", "Inbound email scanning flags attachments containing diagnostic images sent to incorrect recipients, preventing accidental POPIA violations."),
    ("Written Security Agreement", "A formal service-level agreement documents your practice's security controls — a POPIA compliance requirement under HPCSA guidelines."),
    ("Compliance Dashboard", "Monthly security reports provide documented evidence of your security posture — essential for any Information Regulator audit or HPCSA inspection."),
    ("Health Check Integration", "CyberShield links automatically with your existing ZA Support Health Check subscription for a unified view of device and network security."),
]

COMPLIANCE = [
    ("POPIA Section 19 — Security Safeguards",     "NOT MET", "MET"),
    ("HPCSA Guideline 6.4 — Data Security",         "NOT MET", "MET"),
    ("Network Intrusion Detection",                  "NOT MET", "MET"),
    ("Unauthorised Access Monitoring",               "NOT MET", "MET"),
    ("Incident Response Documentation",              "NOT MET", "MET"),
    ("Monthly Security Reporting",                   "NOT MET", "MET"),
    ("Patient Data Exfiltration Controls",           "NOT MET", "MET"),
    ("Written Security Agreement (HPCSA/POPIA)",     "NOT MET", "MET"),
]

SCENARIOS = [
    ("1", "Fake Pathology Link",
     "A staff member receives an email appearing to be from a pathology lab with a link to view results. CyberShield's real-time monitoring detects the connection attempt to a known phishing domain and blocks it before credentials are entered."),
    ("2", "Ransomware Attachment",
     "A malicious attachment is opened by reception staff. CyberShield identifies the ransomware's network communication pattern within seconds, isolates the affected device from the network, and alerts ZA Support — preventing spread to the patient file server."),
    ("3", "Lost or Stolen Phone",
     "A doctor's phone containing patient WhatsApp messages is reported stolen. CyberShield's audit log provides documented evidence of what data was accessible — essential for your POPIA Section 22 breach notification obligation."),
    ("4", "Diagnostic Files Emailed Incorrectly",
     "An X-ray is accidentally attached to an email addressed to the wrong patient. CyberShield flags the transmission and alerts ZA Support before the email is delivered, enabling immediate recall and POPIA incident documentation."),
    ("5", "Foreign Network Access Attempt",
     "An overseas IP attempts repeated authentication against your practice management system. CyberShield detects the pattern, blocks the source, and logs the incident with timestamps — providing the evidence trail required by the Information Regulator."),
    ("6", "Information Regulator Audit",
     "The Information Regulator requests evidence of your security controls following a patient complaint. Your CyberShield monthly reports provide 12 months of documented security posture, incident logs, and remediation records — demonstrating ongoing POPIA compliance."),
]


def _style(name, **kwargs):
    return ParagraphStyle(name, **kwargs)


def generate_cybershield_pdf(
    client_name: str,
    practice_name: str,
    isp_name: Optional[str],
    month_label: str,
    shield_event_count: int = 0,
    isp_outage_count: int = 0,
) -> bytes:
    buf = io.BytesIO()

    # ── Canvas callbacks for headers/footers ──────────────────────────────────
    def draw_cover(c: canvas_module.Canvas, doc):
        w, h = PAGE_W, PAGE_H
        # Full teal background
        c.setFillColor(TEAL)
        c.rect(0, 0, w, h, fill=1, stroke=0)
        # Green top bar
        c.setFillColor(GREEN)
        c.rect(0, h - 6 * mm, w, 6 * mm, fill=1, stroke=0)
        # Dark footer bar
        c.setFillColor(colors.HexColor("#1E3E3B"))
        c.rect(0, 0, w, 28 * mm, fill=1, stroke=0)

        # "ZA SUPPORT" top-left in green bar
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(L_MARGIN, h - 4.5 * mm, "ZA SUPPORT")

        # Service title
        c.setFont("Helvetica-Bold", 24)
        c.setFillColor(colors.white)
        title = "CyberShield"
        c.drawCentredString(w / 2, h * 0.52, title)

        c.setFont("Helvetica", 14)
        c.setFillColor(colors.HexColor("#B2D8D3"))
        c.drawCentredString(w / 2, h * 0.52 - 20, "Monthly Security Report")

        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#B2D8D3"))
        c.drawCentredString(w / 2, h * 0.52 - 40, month_label)

        # Prepared for
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#B2D8D3"))
        c.drawCentredString(w / 2, h * 0.30, "Prepared for")
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(colors.white)
        c.drawCentredString(w / 2, h * 0.30 - 16, practice_name or client_name)

        # Footer contact
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#B2D8D3"))
        c.drawCentredString(w / 2, 18 * mm, "ZA Support | Practice IT. Perfected.")
        c.drawCentredString(w / 2, 12 * mm, "admin@zasupport.com  |  064 529 5863  |  zasupport.com")

    def draw_body(c: canvas_module.Canvas, doc):
        w, h = PAGE_W, PAGE_H
        # Header bar
        c.setFillColor(TEAL)
        c.rect(0, h - 18 * mm, w, 18 * mm, fill=1, stroke=0)
        # Green accent line
        c.setFillColor(GREEN)
        c.rect(0, h - 18 * mm - 0.8 * mm, w, 0.8 * mm, fill=1, stroke=0)
        # Header text
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(L_MARGIN, h - 11 * mm, "ZA SUPPORT")
        c.setFont("Helvetica", 8)
        c.drawRightString(w - R_MARGIN, h - 11 * mm, f"CyberShield  |  {month_label}")

        # Footer
        c.setFont("Helvetica", 7)
        c.setFillColor(MID)
        c.drawString(L_MARGIN, 10 * mm, "064 529 5863  |  admin@zasupport.com  |  zasupport.com")
        c.drawRightString(w - R_MARGIN, 10 * mm, f"Page {doc.page}")

    # ── Document setup ────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=T_MARGIN + 18 * mm, bottomMargin=B_MARGIN + 12 * mm,
    )

    # ── Styles ────────────────────────────────────────────────────────────────
    s_heading  = _style("H", fontName="Helvetica-Bold", fontSize=14, textColor=TEAL, spaceAfter=8)
    s_subhead  = _style("SH", fontName="Helvetica-Bold", fontSize=11, textColor=DARK, spaceAfter=6)
    s_body     = _style("B", fontName="Helvetica", fontSize=10, leading=14, textColor=MID, spaceAfter=6)
    s_small    = _style("SM", fontName="Helvetica", fontSize=9, leading=12, textColor=MID, spaceAfter=4)
    s_feature  = _style("FT", fontName="Helvetica", fontSize=9, leading=13, textColor=MID, spaceAfter=4)

    story = []

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE 1 — COVER (canvas only, story starts on page 2)
    # ─────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE 2 — SERVICE ASSESSMENT
    # ─────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Service Assessment", s_heading))
    practice_label = (practice_name or client_name).upper()
    story.append(Paragraph(f"CYBERSHIELD FOR {practice_label}", s_subhead))
    story.append(Spacer(1, 4 * mm))

    setup_data = [
        ["Practice",    practice_name or client_name],
        ["Network",     isp_name or "ZA Support monitored network"],
        ["Security",    f"CyberShield active — {shield_event_count} event{'s' if shield_event_count != 1 else ''} this month"],
        ["Compliance",  "POPIA / HPCSA — active monitoring"],
    ]
    setup_tbl = Table(setup_data, colWidths=[40 * mm, 125 * mm])
    setup_tbl.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",   (0, 0), (0, -1), TEAL),
        ("TEXTCOLOR",   (1, 0), (1, -1), DARK),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(KeepTogether([setup_tbl]))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Assessment Summary", s_subhead))
    summary_text = (
        f"This report covers the period for {month_label}. "
        f"During this period, ZA Support's CyberShield service monitored your network and recorded "
        f"{shield_event_count} security event{'s' if shield_event_count != 1 else ''} "
        f"and {isp_outage_count} ISP connectivity incident{'s' if isp_outage_count != 1 else ''}. "
        f"All events were logged, assessed and resolved in accordance with your service agreement."
    )
    story.append(Paragraph(summary_text, s_body))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Current Compliance Position", s_subhead))
    compliance_text = (
        "Your practice's network security posture is actively managed under the CyberShield service. "
        "The controls listed on page 3 satisfy the requirements of POPIA Section 19 (security safeguards) "
        "and HPCSA Guideline 6.4 (electronic patient data). This report constitutes your monthly compliance "
        "documentation and should be retained for a minimum of 3 years in accordance with POPIA record-keeping obligations."
    )
    story.append(Paragraph(compliance_text, s_body))

    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE 3 — FEATURES & COMPLIANCE
    # ─────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("What CyberShield Includes", s_heading))
    story.append(Spacer(1, 2 * mm))
    for name, desc in FEATURES:
        story.append(Paragraph(f"<b>{name}</b>  {desc}", s_feature))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Compliance Comparison", s_heading))
    story.append(Spacer(1, 2 * mm))

    comp_header = [["Requirement", "Without CyberShield", "With CyberShield"]]
    comp_rows = [[req, before, after] for req, before, after in COMPLIANCE]
    comp_data = comp_header + comp_rows
    comp_tbl = Table(comp_data, colWidths=[80 * mm, 40 * mm, 45 * mm])
    comp_style = TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), ROW_ALT),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR",   (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR",   (1, 1), (1, -1), RED),
        ("TEXTCOLOR",   (2, 1), (2, -1), MET_GREEN),
        ("FONTNAME",    (1, 1), (2, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("LINEBELOW",   (0, 0), (-1, 0), 2, GREEN),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ])
    comp_tbl.setStyle(comp_style)
    story.append(KeepTogether([comp_tbl]))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Next Steps", s_subhead))
    story.append(Paragraph(
        "CyberShield is available at <b>R 1,499/month</b> (excl. VAT), tax-deductible as a practice operating expense. "
        "Deployment requires 2–3 hours outside patient hours and integrates with your existing ZA Support subscription. "
        "Contact ZA Support to activate or continue your CyberShield service.",
        s_small,
    ))

    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE 4 — APPENDIX: RISK SCENARIOS
    # ─────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Appendix: Risk Scenarios", s_heading))
    story.append(Paragraph("PRACTICAL SITUATIONS EVERY MEDICAL PRACTICE FACES", s_subhead))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "The following scenarios illustrate real-world risks that CyberShield is designed to detect, contain and document. "
        "Each represents a situation that could result in a POPIA Section 22 breach notification or HPCSA disciplinary action "
        "without active security monitoring.",
        s_small,
    ))
    story.append(Spacer(1, 4 * mm))

    s_num = _style("NUM", fontName="Helvetica-Bold", fontSize=14, textColor=TEAL)
    s_scenario_title = _style("ST", fontName="Helvetica-Bold", fontSize=10, textColor=DARK)
    s_scenario_body  = _style("SB", fontName="Helvetica", fontSize=9, leading=13, textColor=MID, spaceAfter=10)

    for num, title, desc in SCENARIOS:
        block = [
            Paragraph(num, s_num),
            Paragraph(title, s_scenario_title),
            Paragraph(desc, s_scenario_body),
        ]
        story.append(KeepTogether(block))

    # Build with correct page templates
    def _on_page(c, doc):
        if doc.page == 1:
            draw_cover(c, doc)
        else:
            draw_body(c, doc)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
