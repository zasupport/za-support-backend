"""
CyberShield Invoice PDF Generator.
Produces a clean 1-page A4 invoice for monthly CyberShield billing.
"""
import io
from datetime import date
from decimal import Decimal
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfgen import canvas as canvas_module

TEAL    = colors.HexColor("#27504D")
GREEN   = colors.HexColor("#0FEA7A")
DARK    = colors.HexColor("#333333")
MID     = colors.HexColor("#4A4D4E")
ROW_ALT = colors.HexColor("#E8F4F3")
RED     = colors.HexColor("#CC0000")

L_MARGIN = 20 * mm
R_MARGIN = 20 * mm
T_MARGIN = 15 * mm
B_MARGIN = 15 * mm
PAGE_W, PAGE_H = A4
BODY_W = PAGE_W - L_MARGIN - R_MARGIN


def _style(name, **kw):
    return ParagraphStyle(name, **kw)


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
    """
    Generates a 1-page invoice PDF.
    Returns raw bytes.
    """
    buf = io.BytesIO()
    vat_rate = Decimal("0.15")
    vat_amount = (amount_excl * vat_rate).quantize(Decimal("0.01"))
    amount_incl = amount_excl + vat_amount

    def draw_page(c: canvas_module.Canvas, doc):
        w, h = PAGE_W, PAGE_H
        # Header bar
        c.setFillColor(TEAL)
        c.rect(0, h - 22 * mm, w, 22 * mm, fill=1, stroke=0)
        # Green accent line
        c.setFillColor(GREEN)
        c.rect(0, h - 22 * mm - 1 * mm, w, 1 * mm, fill=1, stroke=0)
        # Company name
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(L_MARGIN, h - 13 * mm, "ZA SUPPORT")
        c.setFont("Helvetica", 8)
        c.drawString(L_MARGIN, h - 19 * mm, "Vizibiliti Intelligent Solutions (Pty) Ltd  |  admin@zasupport.com  |  064 529 5863  |  zasupport.com")
        # "INVOICE" right-aligned
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", 18)
        c.drawRightString(w - R_MARGIN, h - 14 * mm, "INVOICE")
        # Footer
        c.setFont("Helvetica", 7)
        c.setFillColor(MID)
        c.drawString(L_MARGIN, 10 * mm, "1 Hyde Park Lane, Hyde Park, Johannesburg, 2196  |  VAT Reg: pending")
        c.drawRightString(w - R_MARGIN, 10 * mm, "Vizibiliti Intelligent Solutions (Pty) Ltd  t/a ZA Support")

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=T_MARGIN + 24 * mm,
        bottomMargin=B_MARGIN + 12 * mm,
    )

    s_label = _style("LBL", fontName="Helvetica-Bold", fontSize=9, textColor=TEAL)
    s_val   = _style("VAL", fontName="Helvetica", fontSize=9, textColor=DARK)
    s_small = _style("SM",  fontName="Helvetica", fontSize=8, textColor=MID)
    s_note  = _style("NT",  fontName="Helvetica", fontSize=8, textColor=MID, spaceAfter=4)

    story = []

    # ── Invoice meta block ─────────────────────────────────────────────────────
    invoice_date_str = date.today().strftime("%d/%m/%Y")
    due_str = due_date.strftime("%d/%m/%Y") if due_date else "On receipt"

    meta_data = [
        [Paragraph("Invoice Number", s_label), Paragraph(invoice_ref, s_val),
         Paragraph("Invoice Date", s_label),   Paragraph(invoice_date_str, s_val)],
        [Paragraph("Period", s_label),         Paragraph(month_label, s_val),
         Paragraph("Due Date", s_label),        Paragraph(due_str, s_val)],
    ]
    meta_tbl = Table(meta_data, colWidths=[35 * mm, 55 * mm, 35 * mm, 45 * mm])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [ROW_ALT, colors.white]),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── Billed to ──────────────────────────────────────────────────────────────
    billed_data = [
        [Paragraph("BILLED TO", s_label)],
        [Paragraph(practice_name or client_name, s_val)],
    ]
    if client_email:
        billed_data.append([Paragraph(client_email, s_small)])
    billed_tbl = Table(billed_data, colWidths=[BODY_W])
    billed_tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, -1), ROW_ALT),
    ]))
    story.append(billed_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── Line items ─────────────────────────────────────────────────────────────
    header = [
        Paragraph("Description", _style("H", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
        Paragraph("Qty", _style("H", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
        Paragraph("Unit Price (excl. VAT)", _style("H", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
        Paragraph("Amount (excl. VAT)", _style("H", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
    ]
    network_desc = f"CyberShield Network Security Service — {month_label}"
    if isp_name:
        network_desc += f" ({isp_name})"
    lines = [
        header,
        [Paragraph(network_desc, s_val),
         Paragraph("1", s_val),
         Paragraph(f"R {amount_excl:,.2f}", s_val),
         Paragraph(f"R {amount_excl:,.2f}", s_val)],
    ]
    line_tbl = Table(lines, colWidths=[85 * mm, 15 * mm, 45 * mm, 45 * mm])
    line_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TEAL),
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("LINEBELOW",     (0, 0), (-1, 0), 2, GREEN),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(line_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Totals block ──────────────────────────────────────────────────────────
    totals_data = [
        [Paragraph("Subtotal (excl. VAT)", s_val), Paragraph(f"R {amount_excl:,.2f}", s_val)],
        [Paragraph("VAT (15%)", s_val),             Paragraph(f"R {vat_amount:,.2f}", s_val)],
        [Paragraph("<b>TOTAL DUE (incl. VAT)</b>", _style("TOT", fontName="Helvetica-Bold", fontSize=10, textColor=TEAL)),
         Paragraph(f"<b>R {amount_incl:,.2f}</b>",  _style("TOT2", fontName="Helvetica-Bold", fontSize=10, textColor=TEAL))],
    ]
    tot_tbl = Table(totals_data, colWidths=[BODY_W - 50 * mm, 50 * mm])
    tot_tbl.setStyle(TableStyle([
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("LINEABOVE",     (0, 2), (-1, 2), 1.5, TEAL),
        ("BACKGROUND",    (0, 2), (-1, 2), ROW_ALT),
    ]))
    story.append(tot_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── Payment details ────────────────────────────────────────────────────────
    story.append(Paragraph("Payment Details", _style("PH", fontName="Helvetica-Bold", fontSize=10, textColor=TEAL, spaceAfter=4)))
    pay_data = [
        ["Bank", "FNB"],
        ["Account Name", "Vizibiliti Intelligent Solutions (Pty) Ltd"],
        ["Account Number", "62XXXXXXXXXX"],
        ["Branch Code", "250655"],
        ["Reference", invoice_ref],
    ]
    pay_tbl = Table(pay_data, colWidths=[40 * mm, 130 * mm])
    pay_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",     (0, 0), (0, -1), TEAL),
        ("TEXTCOLOR",     (1, 0), (1, -1), DARK),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    story.append(pay_tbl)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Please use your invoice reference as the payment reference. "
        "Payment is due within 7 days of invoice date. "
        "This invoice is tax-deductible as a practice operating expense.",
        s_note,
    ))

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buf.getvalue()
