"""
Health Check AI — Forensics Module
Report Generator: Produces structured, human-readable forensic reports.
Output: JSON (machine-readable) + plain text (human-readable).
PDF generation via reportlab if available.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEVERITY_LABELS = {
    "critical": "CRITICAL",
    "high":     "HIGH",
    "medium":   "MEDIUM",
    "low":      "LOW",
    "info":     "INFO",
}


class ForensicsReportGenerator:
    """
    Generates readable forensics reports from investigation results.
    
    Structure:
    1. Cover / metadata
    2. Executive summary (non-technical)
    3. Findings by severity
    4. Tool results summary
    5. Evidence inventory with chain of custody hashes
    6. Disclaimer
    """

    def generate(self, investigation: dict, output_dir: str) -> dict:
        """
        Generate both text and JSON reports.
        Returns paths to generated files.
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        findings  = investigation.get("findings", [])
        tasks     = investigation.get("tasks", [])
        client_id = investigation.get("client_id", "Unknown")

        sorted_findings = sorted(
            findings,
            key=lambda f: SEVERITY_ORDER.get(f.get("severity", "info"), 99)
        )

        # ── JSON Report ───────────────────────────────────────────────────────
        json_report = {
            "report_metadata": {
                "generated_at":       datetime.utcnow().isoformat(),
                "generated_by":       "ZA Support Health Check AI — Forensics Module",
                "investigation_id":   investigation.get("id"),
                "client_id":          client_id,
                "device_name":        investigation.get("device_name"),
                "scope":              investigation.get("scope"),
                "status":             investigation.get("status"),
            },
            "consent": {
                "granted":       investigation.get("consent_granted"),
                "obtained_by":   investigation.get("consent_obtained_by"),
                "method":        investigation.get("consent_method"),
                "reference":     investigation.get("consent_reference"),
                "timestamp":     investigation.get("consent_timestamp"),
            },
            "timeline": {
                "investigation_created":  investigation.get("created_at"),
                "analysis_started":       investigation.get("started_at"),
                "analysis_completed":     investigation.get("completed_at"),
            },
            "summary": {
                "total_findings":    investigation.get("finding_count", 0),
                "critical_findings": investigation.get("critical_count", 0),
                "high_findings":     investigation.get("high_count", 0),
                "medium_findings":   sum(1 for f in findings if f.get("severity") == "medium"),
                "low_findings":      sum(1 for f in findings if f.get("severity") == "low"),
                "info_findings":     sum(1 for f in findings if f.get("severity") == "info"),
                "tasks_run":         len([t for t in tasks if t.get("status") == "complete"]),
                "tasks_skipped":     len([t for t in tasks if t.get("status") == "skipped"]),
                "tasks_failed":      len([t for t in tasks if t.get("status") == "failed"]),
            },
            "findings": sorted_findings,
            "tasks":    tasks,
            "disclaimer": (
                "All findings in this report are INDICATORS that require human review. "
                "A finding does not constitute a confirmed incident, infection, or policy violation. "
                "This report is produced by automated analysis tools and must be reviewed by "
                "a qualified professional before any conclusions or actions are taken. "
                "This report was generated in accordance with POPIA requirements and "
                "is to be handled as confidential information."
            ),
        }

        json_path = os.path.join(output_dir, f"forensics_report_{timestamp}.json")
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)

        # ── Text Report ───────────────────────────────────────────────────────
        text_path = os.path.join(output_dir, f"forensics_report_{timestamp}.txt")
        with open(text_path, "w") as f:
            f.write(self._text_report(investigation, sorted_findings, tasks, json_report))

        # ── Try PDF ───────────────────────────────────────────────────────────
        pdf_path = None
        try:
            pdf_path = self._generate_pdf(
                investigation, sorted_findings, tasks, json_report,
                output_dir, timestamp
            )
        except Exception as e:
            logger.warning(f"[forensics] PDF generation failed: {e}. Text report available.")

        return {
            "json_path": json_path,
            "text_path": text_path,
            "pdf_path":  pdf_path,
            "timestamp": timestamp,
        }

    # ── Text Report ───────────────────────────────────────────────────────────

    def _text_report(self, inv: dict, findings: list, tasks: list, report: dict) -> str:
        lines = []
        sep   = "=" * 72
        thin  = "-" * 72

        # Header
        lines += [
            sep,
            "  ZA SUPPORT — DIGITAL FORENSICS INVESTIGATION REPORT",
            "  Health Check AI | Forensics Module",
            sep,
            "",
            f"  Investigation ID : {inv.get('id')}",
            f"  Client           : {inv.get('client_id')}",
            f"  Device           : {inv.get('device_name', 'Not specified')}",
            f"  Scope            : {inv.get('scope', '').replace('_', ' ').title()}",
            f"  Reason           : {inv.get('reason', '')}",
            f"  Initiated by     : {inv.get('initiated_by', '')}",
            f"  Status           : {inv.get('status', '').upper()}",
            "",
            thin,
            "  CONSENT RECORD (POPIA)",
            thin,
            f"  Consent granted  : {'YES' if inv.get('consent_granted') else 'NO'}",
            f"  Obtained from    : {inv.get('consent_obtained_by', 'N/A')}",
            f"  Method           : {inv.get('consent_method', 'N/A')}",
            f"  Reference        : {inv.get('consent_reference', 'N/A')}",
            f"  Timestamp        : {inv.get('consent_timestamp', 'N/A')}",
            "",
            thin,
            "  TIMELINE",
            thin,
            f"  Created          : {inv.get('created_at', 'N/A')}",
            f"  Started          : {inv.get('started_at', 'N/A')}",
            f"  Completed        : {inv.get('completed_at', 'N/A')}",
            "",
        ]

        # Summary stats
        s = report["summary"]
        lines += [
            sep,
            "  FINDINGS SUMMARY",
            sep,
            f"  Total findings   : {s['total_findings']}",
            f"  CRITICAL         : {s['critical_findings']}",
            f"  HIGH             : {s['high_findings']}",
            f"  MEDIUM           : {s['medium_findings']}",
            f"  LOW              : {s['low_findings']}",
            f"  INFO             : {s['info_findings']}",
            "",
            f"  Tools run        : {s['tasks_run']}",
            f"  Tools skipped    : {s['tasks_skipped']} (not installed)",
            f"  Tools failed     : {s['tasks_failed']}",
            "",
        ]

        # Executive summary (non-technical)
        lines += [
            sep,
            "  EXECUTIVE SUMMARY",
            sep,
        ]
        lines += self._executive_summary_text(inv, findings)
        lines.append("")

        # Findings detail
        if findings:
            lines += [
                sep,
                "  DETAILED FINDINGS",
                sep,
                "  NOTE: All findings are indicators requiring human review.",
                "  They do not constitute confirmed incidents.",
                "",
            ]
            for i, f in enumerate(findings, 1):
                sev  = f.get("severity", "info").upper()
                lines += [
                    f"  [{i}] [{sev}] {f.get('title', '')}",
                    f"       Category : {f.get('category', '')}",
                    f"       Source   : {f.get('source_tool', 'N/A')}",
                ]
                if f.get("detail"):
                    lines.append(f"       Detail   : {f.get('detail', '')}")
                if f.get("raw_indicator"):
                    raw = f.get("raw_indicator", "")[:200]
                    lines.append(f"       Raw      : {raw}")
                lines.append("")
        else:
            lines += [
                sep,
                "  FINDINGS",
                sep,
                "  No indicators were detected during this analysis.",
                "  This does not guarantee a clean system — it indicates that",
                "  the tools run did not match known malicious patterns.",
                "",
            ]

        # Tool results
        if tasks:
            lines += [
                sep,
                "  TOOL RESULTS",
                sep,
            ]
            for t in tasks:
                status_label = {
                    "complete": "✓ COMPLETE",
                    "failed":   "✗ FAILED",
                    "skipped":  "○ SKIPPED",
                    "running":  "→ RUNNING",
                }.get(t.get("status", ""), t.get("status", "").upper())
                lines.append(
                    f"  {status_label:<14} {t.get('tool_id', ''):<18} "
                    f"{t.get('summary', t.get('reason', ''))[:50]}"
                )
                if t.get("status") == "skipped":
                    lines.append(f"               Reason: {t.get('reason', '')}")
            lines.append("")

        # Disclaimer
        lines += [
            sep,
            "  DISCLAIMER",
            sep,
            "  All findings in this report are INDICATORS that require human review.",
            "  A finding does not constitute a confirmed incident, infection, or",
            "  policy violation. This report must be reviewed by a qualified",
            "  professional before any conclusions or actions are taken.",
            "",
            "  This report is CONFIDENTIAL and contains information subject to",
            "  POPIA (Protection of Personal Information Act, No. 4 of 2013).",
            "  Unauthorised disclosure is a POPIA violation.",
            "",
            f"  Generated: {datetime.utcnow().isoformat()} UTC",
            f"  By: ZA Support Health Check AI — Forensics Module",
            "  ZA Support | admin@zasupport.com | 064 529 5863",
            "  1 Hyde Park Lane, Hyde Park, Johannesburg, 2196",
            sep,
        ]

        return "\n".join(lines)

    def _executive_summary_text(self, inv: dict, findings: list) -> list:
        """Non-technical summary written for a client or manager."""
        critical = [f for f in findings if f.get("severity") == "critical"]
        high     = [f for f in findings if f.get("severity") == "high"]
        medium   = [f for f in findings if f.get("severity") == "medium"]

        lines = []
        total = len(findings)

        if total == 0:
            lines += [
                "  The forensic analysis of this system did not detect any known",
                "  malicious patterns or indicators of compromise.",
                "",
                "  This means the automated tools did not find signatures that match",
                "  known malware, suspicious network activity, or data exfiltration",
                "  indicators. A clean result does not guarantee the system is",
                "  completely free of threats — some advanced threats may not be",
                "  detected by automated analysis alone.",
            ]
        else:
            lines.append(
                f"  The forensic analysis identified {total} indicator(s) that require review."
            )
            lines.append("")

            if critical:
                lines += [
                    f"  CRITICAL PRIORITY ({len(critical)} indicator(s)):",
                    "  These indicators suggest activity that requires immediate attention.",
                    "  Examples include ransomware signatures, active remote access tools,",
                    "  or confirmed credential theft attempts.",
                ]
                for f in critical[:3]:
                    lines.append(f"  • {f.get('title', '')}")
                lines.append("")

            if high:
                lines += [
                    f"  HIGH PRIORITY ({len(high)} indicator(s)):",
                    "  Indicators consistent with malicious tools or suspicious behaviour.",
                ]
                for f in high[:3]:
                    lines.append(f"  • {f.get('title', '')}")
                lines.append("")

            if medium:
                lines += [
                    f"  MEDIUM PRIORITY ({len(medium)} indicator(s)):",
                    "  Indicators that warrant review but may have legitimate explanations.",
                ]
                lines.append("")

            lines += [
                "  IMPORTANT: All findings listed above are indicators detected by",
                "  automated pattern matching. They must be reviewed by a qualified",
                "  professional before any conclusion is drawn or action is taken.",
                "  False positives are possible.",
            ]

        return lines

    # ── PDF Report ────────────────────────────────────────────────────────────

    def _generate_pdf(
        self,
        inv: dict,
        findings: list,
        tasks: list,
        report: dict,
        output_dir: str,
        timestamp: str,
    ) -> Optional[str]:
        """Generate a branded ZA Support PDF report using reportlab."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor, white, black
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            PageBreak, KeepTogether
        )
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

        PAGE_W, PAGE_H = A4
        TEAL      = HexColor("#27504D")
        GREEN     = HexColor("#0FEA7A")
        DARK_TEXT = HexColor("#333333")
        MID_TEXT  = HexColor("#4A4D4E")
        ROW_ALT   = HexColor("#E8F4F3")
        RED_TEXT  = HexColor("#CC0000")
        ORANGE    = HexColor("#D97706")
        AMBER_BG  = HexColor("#FFF7ED")
        BLUE_BG   = HexColor("#EFF6FF")
        BLUE_BD   = HexColor("#2563EB")
        SEV_CRITICAL = HexColor("#CC0000")
        SEV_HIGH     = HexColor("#EA580C")
        SEV_MEDIUM   = HexColor("#D97706")
        SEV_LOW      = HexColor("#16A34A")
        SEV_INFO     = HexColor("#6B7280")
        LIGHT_BG  = HexColor("#F5F5F5")

        SEV_COLOUR = {
            "critical": SEV_CRITICAL,
            "high":     SEV_HIGH,
            "medium":   SEV_MEDIUM,
            "low":      SEV_LOW,
            "info":     SEV_INFO,
        }

        pdf_path = os.path.join(output_dir, f"Forensics Report {timestamp}.pdf")
        doc = SimpleDocTemplate(
            pdf_path, pagesize=A4,
            leftMargin=18*mm, rightMargin=18*mm,
            topMargin=24*mm, bottomMargin=20*mm,
        )
        W = PAGE_W - 36*mm

        # Styles
        styles = getSampleStyleSheet()
        body   = ParagraphStyle("body",   fontName="Helvetica", fontSize=9.5,
                                 textColor=DARK_TEXT, leading=14, spaceAfter=4)
        h1     = ParagraphStyle("h1",     fontName="Helvetica-Bold", fontSize=12,
                                 textColor=TEAL, spaceBefore=8, spaceAfter=4,
                                 keepWithNext=True)
        small  = ParagraphStyle("small",  fontName="Helvetica", fontSize=8.5,
                                 textColor=MID_TEXT, leading=12)
        cell   = ParagraphStyle("cell",   fontName="Helvetica", fontSize=9,
                                 textColor=DARK_TEXT, leading=13)
        h_cell = ParagraphStyle("h_cell", fontName="Helvetica-Bold", fontSize=9,
                                 textColor=white, leading=12)
        bold   = ParagraphStyle("bold",   fontName="Helvetica-Bold", fontSize=9.5,
                                 textColor=DARK_TEXT, leading=14)
        disc   = ParagraphStyle("disc",   fontName="Helvetica-Oblique", fontSize=8.5,
                                 textColor=MID_TEXT, leading=12)

        def header_footer(canvas, doc):
            canvas.saveState()
            # Header bar
            canvas.setFillColor(TEAL)
            canvas.rect(0, PAGE_H - 18*mm, PAGE_W, 18*mm, fill=1, stroke=0)
            canvas.setFillColor(GREEN)
            canvas.rect(0, PAGE_H - 18.8*mm, PAGE_W, 0.8*mm, fill=1, stroke=0)
            canvas.setFillColor(white)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(18*mm, PAGE_H - 12*mm, "ZA SUPPORT")
            canvas.setFont("Helvetica", 7.5)
            canvas.drawRightString(PAGE_W - 18*mm, PAGE_H - 9*mm,
                                   "admin@zasupport.com  |  064 529 5863")
            canvas.drawRightString(PAGE_W - 18*mm, PAGE_H - 13*mm,
                                   "1 Hyde Park Lane, Hyde Park, Johannesburg, 2196")
            # Footer
            canvas.setFillColor(MID_TEXT)
            canvas.setFont("Helvetica", 7)
            canvas.drawString(18*mm, 12*mm,
                              "ZA Support  |  admin@zasupport.com  |  064 529 5863")
            canvas.drawRightString(PAGE_W - 18*mm, 12*mm,
                                   f"Page {doc.page}")
            canvas.restoreState()

        def draw_cover(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(TEAL)
            canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            canvas.setFillColor(GREEN)
            canvas.rect(0, PAGE_H - 6*mm, PAGE_W, 6*mm, fill=1, stroke=0)
            canvas.setFillColor(white)
            canvas.setFont("Helvetica-Bold", 18)
            canvas.drawString(24*mm, PAGE_H - 28*mm, "ZA SUPPORT")
            canvas.setFont("Helvetica", 9)
            canvas.drawString(24*mm, PAGE_H - 35*mm, "Practice IT. Perfected.")
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(PAGE_W - 24*mm, PAGE_H - 28*mm,
                                   "admin@zasupport.com  |  064 529 5863")
            canvas.drawRightString(PAGE_W - 24*mm, PAGE_H - 35*mm,
                                   "1 Hyde Park Lane, Hyde Park, Johannesburg, 2196")
            canvas.setFillColor(GREEN)
            canvas.rect(24*mm, PAGE_H - 46*mm, PAGE_W - 48*mm, 0.5*mm, fill=1, stroke=0)
            # Title
            canvas.setFillColor(white)
            canvas.setFont("Helvetica-Bold", 26)
            canvas.drawCentredString(PAGE_W/2, PAGE_H*0.52,
                                     "Digital Forensics Report")
            canvas.setFont("Helvetica", 14)
            canvas.setFillColor(HexColor("#A8D5D1"))
            canvas.drawCentredString(PAGE_W/2, PAGE_H*0.52 - 22,
                                     "Health Check AI — Forensics Module")
            # Client + date
            canvas.setFillColor(HexColor("#CCCCCC"))
            canvas.setFont("Helvetica", 10)
            canvas.drawCentredString(PAGE_W/2, PAGE_H*0.36,
                                     f"Prepared for: {inv.get('client_id', 'Unknown Client')}")
            canvas.drawCentredString(PAGE_W/2, PAGE_H*0.36 - 16,
                                     f"Investigation: {inv.get('id', '')[:20]}...")
            canvas.drawCentredString(PAGE_W/2, PAGE_H*0.36 - 32,
                                     f"Prepared by ZA Support  |  {datetime.utcnow().strftime('%B %Y')}")
            # Footer bar
            canvas.setFillColor(HexColor("#1E3E3B"))
            canvas.rect(0, 0, PAGE_W, 18*mm, fill=1, stroke=0)
            canvas.setFillColor(HexColor("#999999"))
            canvas.setFont("Helvetica", 7)
            canvas.drawCentredString(PAGE_W/2, 7*mm,
                                     "admin@zasupport.com  |  064 529 5863  |  "
                                     "1 Hyde Park Lane, Hyde Park, Johannesburg, 2196")
            canvas.restoreState()

        story = [PageBreak(), Spacer(1, 6*mm)]

        # ── Investigation Details ──────────────────────────────────────────
        story.append(Paragraph("Investigation Details", h1))
        details_data = [
            [Paragraph("Field", h_cell),    Paragraph("Value", h_cell)],
            ["Investigation ID",             inv.get("id", "")],
            ["Client",                       inv.get("client_id", "")],
            ["Device",                       inv.get("device_name", "Not specified")],
            ["Analysis Scope",               inv.get("scope", "").replace("_", " ").title()],
            ["Reason",                       inv.get("reason", "")],
            ["Initiated By",                 inv.get("initiated_by", "")],
            ["Status",                       inv.get("status", "").upper()],
        ]
        details_table = Table(
            details_data,
            colWidths=[50*mm, W - 50*mm],
            repeatRows=1
        )
        details_table.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,0), TEAL),
            ("TEXTCOLOR",   (0,0), (-1,0), white),
            ("LINEBELOW",   (0,0), (-1,0), 2, GREEN),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, ROW_ALT]),
            ("FONTNAME",    (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTSIZE",    (0,0), (-1,-1), 9),
            ("VALIGN",      (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING",(0,0), (-1,-1), 8),
            ("TOPPADDING",  (0,0), (-1,-1), 6),
            ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ]))
        story.append(KeepTogether([Paragraph("Investigation Details", h1), details_table]))
        story.append(Spacer(1, 4*mm))

        # ── Consent Record ────────────────────────────────────────────────
        consent_text = (
            f"<b>POPIA Consent Reference</b><br/>"
            f"Consent obtained from: {inv.get('consent_obtained_by', 'N/A')}<br/>"
            f"Method: {inv.get('consent_method', 'N/A')}  |  "
            f"Reference: {inv.get('consent_reference', 'N/A')}<br/>"
            f"Recorded: {inv.get('consent_timestamp', 'N/A')}"
        )
        consent_style = ParagraphStyle("cs", fontName="Helvetica", fontSize=9,
                                        textColor=DARK_TEXT, leading=13)
        consent_table = Table(
            [[Paragraph(consent_text, consent_style)]],
            colWidths=[W]
        )
        consent_table.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,-1), BLUE_BG),
            ("LINEBEFORE",  (0,0), (0,-1), 4, BLUE_BD),
            ("LEFTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING",  (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ]))
        story.append(KeepTogether([Paragraph("Consent Record", h1), consent_table]))
        story.append(Spacer(1, 4*mm))

        # ── Findings ──────────────────────────────────────────────────────
        story.append(Paragraph("Findings", h1))
        story.append(Paragraph(
            "All findings below are <b>indicators</b> detected by automated analysis. "
            "They require human review and do not constitute confirmed incidents.",
            small
        ))
        story.append(Spacer(1, 3*mm))

        if findings:
            for i, f in enumerate(findings, 1):
                sev   = f.get("severity", "info")
                colour = SEV_COLOUR.get(sev, SEV_INFO)
                content = [
                    Paragraph(f"<b>{SEVERITY_LABELS.get(sev, sev.upper())}  —  "
                               f"{f.get('title', '')}</b>", cell),
                    Spacer(1, 2*mm),
                    Paragraph(f"Category: {f.get('category', '')}  |  "
                               f"Source: {f.get('source_tool', 'N/A')}",
                               ParagraphStyle("sc", fontName="Helvetica", fontSize=8,
                                               textColor=MID_TEXT)),
                ]
                if f.get("detail"):
                    content += [
                        Spacer(1, 1*mm),
                        Paragraph(f.get("detail", ""), small),
                    ]
                if f.get("raw_indicator"):
                    raw = f.get("raw_indicator", "")[:200]
                    raw_style = ParagraphStyle("raw", fontName="Courier", fontSize=7.5,
                                               textColor=MID_TEXT, leading=11)
                    content += [Spacer(1, 1*mm), Paragraph(raw, raw_style)]

                finding_table = Table(
                    [[content]],
                    colWidths=[W]
                )
                finding_table.setStyle(TableStyle([
                    ("BACKGROUND",  (0,0), (-1,-1), LIGHT_BG),
                    ("LINEBEFORE",  (0,0), (0,-1), 4, colour),
                    ("LEFTPADDING", (0,0), (-1,-1), 10),
                    ("TOPPADDING",  (0,0), (-1,-1), 8),
                    ("BOTTOMPADDING",(0,0), (-1,-1), 8),
                    ("VALIGN",      (0,0), (-1,-1), "TOP"),
                ]))
                story.append(KeepTogether([finding_table, Spacer(1, 3*mm)]))
        else:
            no_findings = Table(
                [[Paragraph("No indicators were detected. See disclaimer for limitations.", body)]],
                colWidths=[W]
            )
            no_findings.setStyle(TableStyle([
                ("BACKGROUND",  (0,0), (-1,-1), BLUE_BG),
                ("LINEBEFORE",  (0,0), (0,-1), 4, BLUE_BD),
                ("LEFTPADDING", (0,0), (-1,-1), 12),
                ("TOPPADDING",  (0,0), (-1,-1), 10),
                ("BOTTOMPADDING",(0,0), (-1,-1), 10),
            ]))
            story.append(no_findings)

        # ── Tool Results ──────────────────────────────────────────────────
        story.append(Spacer(1, 4*mm))
        tasks_data = [
            [Paragraph("Tool", h_cell), Paragraph("Type", h_cell),
             Paragraph("Status", h_cell), Paragraph("Summary", h_cell)],
        ]
        for t in tasks:
            status = t.get("status", "")
            status_colour = {
                "complete": HexColor("#16A34A"),
                "failed":   RED_TEXT,
                "skipped":  MID_TEXT,
            }.get(status, DARK_TEXT)
            tasks_data.append([
                Paragraph(t.get("tool_id", ""), cell),
                Paragraph(t.get("task_type", ""), cell),
                Paragraph(
                    f'<font color="#{status_colour.hexval()[1:]}">'
                    f'{status.upper()}</font>', cell
                ),
                Paragraph((t.get("summary") or t.get("reason", ""))[:60], small),
            ])

        if len(tasks_data) > 1:
            tasks_table = Table(
                tasks_data,
                colWidths=[30*mm, 35*mm, 22*mm, W - 87*mm],
                repeatRows=1
            )
            tasks_table.setStyle(TableStyle([
                ("BACKGROUND",  (0,0), (-1,0), TEAL),
                ("TEXTCOLOR",   (0,0), (-1,0), white),
                ("LINEBELOW",   (0,0), (-1,0), 2, GREEN),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, ROW_ALT]),
                ("FONTSIZE",    (0,0), (-1,-1), 8.5),
                ("VALIGN",      (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("TOPPADDING",  (0,0), (-1,-1), 5),
                ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ]))
            story.append(KeepTogether([Paragraph("Tool Results", h1), tasks_table]))

        # ── Disclaimer ────────────────────────────────────────────────────
        story.append(Spacer(1, 6*mm))
        disc_text = (
            "<i>All findings in this report are indicators that require human review. "
            "A finding does not constitute a confirmed incident, infection, or policy violation. "
            "This report is produced by automated analysis tools and must be reviewed by a qualified "
            "professional before any conclusions or actions are taken. "
            "This report is CONFIDENTIAL and subject to POPIA (No. 4 of 2013). "
            "Unauthorised disclosure is a POPIA violation. "
            f"Generated: {datetime.utcnow().isoformat()} UTC by ZA Support Health Check AI.</i>"
        )
        story.append(Paragraph(disc_text, disc))

        doc.build(story, onFirstPage=draw_cover, onLaterPages=header_footer)
        logger.info(f"[forensics] PDF report generated: {pdf_path}")
        return pdf_path
