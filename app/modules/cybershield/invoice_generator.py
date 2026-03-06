"""
CyberShield Invoice PDF Generator.
Generates a professional ZA Support invoice for monthly CyberShield subscription.
"""
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.pdfgen import canvas as canvas_module

# ── Colours ───────────────────────────────────────────────────────────────────
TEAL    = colors.HexColor("#27504D")
GREEN   = colors.HexColor("#0FEA7A")
DARK    = colors.HexColor("#333333")
MID     = colors.HexColor("#4A4D4E")
ROW_ALT = colors.HexColor("#E8F4F3")
RED     = colors.HexColor("#CC0000")

PAGE_W, PAGE_H = A4
L_MARGIN = 20 * mm
R_MARGIN = 20 * mm
T_MARGIN = 15 * mm
B_MARGIN = 15 * mm
BODY_W   = PAGE_W - L_MARGIN - R_MARGIN

VAT_RATE = Decimal("0.15")


def _style(name, **kwargs):
    return ParagraphStyle(name, **kwargs)


def generate_cybershield_invoice(
    client_name: str,
    practice_name: str,
    client_email: Optional[str],
    month_label: str,
    amount_excl: Decimal,
    invoice_ref: str,
    due_date: Optional[date] = None,
    isp_name: Optional[str] = None,
) -> bytes:
    buf = io.BytesIO()

    # ── Canvas callbacks ──────────────────────────────────────────────────────
    def draw_page(c: canvas_module.Canvas, doc):
        w, h = PAGE_W, PAGE_H
        # Teal header bar
        c.setFillColor(TEAL)
        c.rect(0, h - 22 * mm, w, 22 * mm, fill=1, stroke=0)
        # Green accent
        c.setFillColor(GREEN)
        c.rect(0, h - 22 * mm - 0.8 * mm, w, 0.8 * mm, fill=1, stroke=0)
        # Header text
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(L_MARGIN, h - 13 * mm, "ZA SUPPORT")
        c.setFont("Helvetica", 8)
        c.drawRightString(w - R_MARGIN, h - 9 * mm, "Practice IT. Perfected.")
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#B2D8D3"))
        c.drawRightString(w - R_MARGIN, h - 15 * mm, "admin@zasupport.com  |  064 529 5863  |  zasupport.com")
        # Footer
        c.setFont("Helvetica", 7)
        c.setFillColor(MID)
        c.drawString(L_MARGIN, 10 * mm, "Vizibiliti Intelligent Solutions (Pty) Ltd  |  1 Hyde Park Lane, Hyde Park, Johannesburg, 2196")
        c.drawRightString(w - R_MARGIN, 10 * mm, f"Page {doc.page}")

    # ── Document ──────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=T_MARGIN + 22 * mm, bottomMargin=B_MARGIN + 12 * mm,
    )

    # ── Styles ────────────────────────────────────────────────────────────────
    s_h1   = _style("H1", fontName="Helvetica-Bold", fontSize=18, textColor=TEAL,  spaceAfter=2)
    s_sub  = _style("SB", fontName="Helvetica",      fontSize=10, textColor=MID,   spaceAfter=6)
    s_body = _style("BD", fontName="Helvetica",      fontSize=10, leading=14, textColor=DARK, spaceAfter=4)
    s_sm   = _style("SM", fontName="Helvetica",      fontSize=9,  leading=13, textColor=MID,  spaceAfter=3)
    s_bold = _style("BL", fontName="Helvetica-Bold", fontSize=10, textColor=DARK,  spaceAfter=4)

    story = []

    # ── Invoice header ────────────────────────────────────────────────────────
    now = datetime.now()
    issue_date = now.strftime("%d/%m/%Y")
    due_str    = due_date.strftime("%d/%m/%Y") if due_date else "On receipt"

    meta_data = [
        ["TAX INVOICE",      ""],
        ["Invoice No:",       invoice_ref],
        ["Issue Date:",       issue_date],
        ["Due Date:",         due_str],
        ["Period:",           month_label],
    ]
    meta_tbl = Table(meta_data, colWidths=[35 * mm, BODY_W - 35 * mm])
    meta_tbl.setStyle(TableStyle([
        ("SPAN",        (0, 0), (1, 0)),
        ("FONTNAME",    (0, 0), (1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (1, 0), 18),
        ("TEXTCOLOR",   (0, 0), (1, 0), TEAL),
        ("FONTNAME",    (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",   (0, 1), (0, -1), MID),
        ("TEXTCOLOR",   (1, 1), (1, -1), DARK),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── Bill to ───────────────────────────────────────────────────────────────
    story.append(Paragraph("BILLED TO", _style("BT", fontName="Helvetica-Bold", fontSize=8, textColor=MID)))
    story.append(Paragraph(practice_name or client_name, _style("BN", fontName="Helvetica-Bold", fontSize=11, textColor=DARK)))
    story.append(Paragraph(client_name, s_sm))
    if client_email:
        story.append(Paragraph(client_email, s_sm))
    if isp_name:
        story.append(Paragraph(f"ISP: {isp_name}", s_sm))
    story.append(Spacer(1, 8 * mm))

    # ── Line items ────────────────────────────────────────────────────────────
    vat      = (amount_excl * VAT_RATE).quantize(Decimal("0.01"))
    total    = amount_excl + vat

    items_header = [["Description", "Period", "Qty", "Amount (R)"]]
    items_rows = [[
        "CyberShield Network Security Service",
        month_label,
        "1",
        f"{amount_excl:,.2f}",
    ]]
    items_data = items_header + items_rows

    items_tbl = Table(items_data, colWidths=[80 * mm, 40 * mm, 15 * mm, 35 * mm])
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR",    (0, 1), (-1, -1), DARK),
        ("ALIGN",        (2, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("LINEBELOW",    (0, 0), (-1, 0), 2, GREEN),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Totals ────────────────────────────────────────────────────────────────
    totals_data = [
        ["", "Subtotal (excl. VAT)", f"R {amount_excl:,.2f}"],
        ["", "VAT (15%)",            f"R {vat:,.2f}"],
        ["", "TOTAL DUE",            f"R {total:,.2f}"],
    ]
    totals_tbl = Table(totals_data, colWidths=[BODY_W - 80 * mm, 40 * mm, 40 * mm])
    totals_tbl.setStyle(TableStyle([
        ("FONTNAME",     (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME",     (1, 2), (2, 2),   "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",    (1, 0), (1, -1),  MID),
        ("TEXTCOLOR",    (2, 0), (2, 1),   DARK),
        ("TEXTCOLOR",    (2, 2), (2, 2),   TEAL),
        ("FONTSIZE",     (2, 2), (2, 2),   11),
        ("ALIGN",        (1, 0), (2, -1),  "RIGHT"),
        ("LINEABOVE",    (1, 2), (2, 2),   1, TEAL),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width=BODY_W, color=colors.HexColor("#E2E8F0")))
    story.append(Spacer(1, 6 * mm))

    # ── Payment details ───────────────────────────────────────────────────────
    story.append(Paragraph("Payment Details", s_bold))
    payment_rows = [
        ["Bank:",        "FNB (First National Bank)"],
        ["Account name:", "Vizibiliti Intelligent Solutions (Pty) Ltd"],
        ["Account No:",  "Please contact admin@zasupport.com for banking details"],
        ["Reference:",   invoice_ref],
    ]
    pay_tbl = Table(payment_rows, colWidths=[35 * mm, BODY_W - 35 * mm])
    pay_tbl.setStyle(TableStyle([
        ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",     (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",    (0, 0), (0, -1), MID),
        ("TEXTCOLOR",    (1, 0), (1, -1), DARK),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(pay_tbl)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(
        "This invoice is tax-deductible as a practice operating expense. "
        "Please retain for your POPIA compliance records. "
        "For queries, contact admin@zasupport.com or 064 529 5863.",
        s_sm,
    ))

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buf.getvalue()
