from __future__ import annotations
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from app.schemas import SubmissionReport


PURPLE = colors.HexColor("#7c6af7")
SUCCESS = colors.HexColor("#68d391")
DANGER  = colors.HexColor("#fc8181")
WARNING = colors.HexColor("#f6ad55")
DARK    = colors.HexColor("#1a1a24")
MUTED   = colors.HexColor("#6b6b8a")
WHITE   = colors.white


def generate_pdf_report(report: SubmissionReport, output_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    title_style   = ParagraphStyle("title",   fontSize=22, textColor=PURPLE,  fontName="Helvetica-Bold", spaceAfter=4)
    h2_style      = ParagraphStyle("h2",      fontSize=14, textColor=PURPLE,  fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6)
    h3_style      = ParagraphStyle("h3",      fontSize=11, textColor=DARK,    fontName="Helvetica-Bold", spaceBefore=8,  spaceAfter=4)
    body_style    = ParagraphStyle("body",    fontSize=9,  textColor=DARK,    fontName="Helvetica",      spaceAfter=4, leading=14)
    muted_style   = ParagraphStyle("muted",   fontSize=8,  textColor=MUTED,   fontName="Helvetica",      spaceAfter=3)
    mono_style    = ParagraphStyle("mono",    fontSize=7,  textColor=colors.HexColor("#4fd1c5"), fontName="Courier", spaceAfter=4, leading=10)

    story = []

    # Header
    story.append(Paragraph("ThesisGuard", title_style))
    story.append(Paragraph("Verification Report", ParagraphStyle("sub", fontSize=13, textColor=MUTED, fontName="Helvetica", spaceAfter=4)))
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE, spaceAfter=12))

    # Meta table
    meta = [
        ["File", report.original_filename],
        ["Template", report.template_name],
        ["Submission ID", str(report.submission_id)],
        ["Generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")],
        ["SHA-256", report.file_hash_sha256[:32] + "..."],
    ]
    meta_table = Table(meta, colWidths=[3.5*cm, 13*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("TEXTCOLOR",   (0,0), (0,-1),  MUTED),
        ("TEXTCOLOR",   (1,0), (1,-1),  DARK),
        ("FONTNAME",    (0,0), (0,-1),  "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#f8f8ff"), WHITE]),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # Scores summary
    c  = report.compliance
    ai = report.ai_risk
    pl = report.plagiarism

    score_color = SUCCESS if c.compliance_score >= 75 else (WARNING if c.compliance_score >= 50 else DANGER)
    ai_color    = SUCCESS if ai.risk_level == "low" else (WARNING if ai.risk_level == "medium" else DANGER)
    pl_color    = SUCCESS if pl.similarity_score < 15 else (WARNING if pl.similarity_score < 30 else DANGER)

    scores_data = [
        ["COMPLIANCE SCORE", "AI RISK", "SIMILARITY"],
        [f"{c.compliance_score}/100", f"{ai.risk_score}%  ({ai.risk_level.upper()})", f"{pl.similarity_score}%"],
    ]
    scores_table = Table(scores_data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    scores_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  DARK),
        ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0),  8),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("FONTNAME",      (0,1), (-1,1),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,1), (-1,1),  16),
        ("TEXTCOLOR",     (0,1), (0,1),   score_color),
        ("TEXTCOLOR",     (1,1), (1,1),   ai_color),
        ("TEXTCOLOR",     (2,1), (2,1),   pl_color),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#e0e0f0")),
    ]))
    story.append(scores_table)
    story.append(Spacer(1, 14))

    # Summary
    story.append(Paragraph("Summary", h2_style))
    for part in report.final_summary.split(" | "):
        story.append(Paragraph(part.strip(), body_style))
    story.append(Spacer(1, 8))

    # Compliance errors
    if c.errors:
        story.append(Paragraph("Compliance Errors", h2_style))
        for e in c.errors:
            story.append(Paragraph(f"✖ {e.label}", h3_style))
            story.append(Paragraph(e.details, body_style))
            if e.location_hint:
                story.append(Paragraph(f"Location: {e.location_hint}", muted_style))

    # Compliance warnings
    if c.warnings:
        story.append(Paragraph("Compliance Warnings", h2_style))
        for w in c.warnings:
            story.append(Paragraph(f"⚠ {w.label}", h3_style))
            story.append(Paragraph(w.details, body_style))
            if w.location_hint:
                story.append(Paragraph(f"Location: {w.location_hint}", muted_style))

    # Passed checks
    if c.passed_checks:
        story.append(Paragraph("Passed Checks", h2_style))
        for p in c.passed_checks:
            story.append(Paragraph(f"✓  {p}", ParagraphStyle("pass", fontSize=9, textColor=SUCCESS, fontName="Helvetica", spaceAfter=3)))

    # AI Risk
    story.append(Paragraph("AI Risk Analysis", h2_style))
    for note in ai.notes:
        story.append(Paragraph(note, body_style))
    if ai.flagged_segments:
        for seg in ai.flagged_segments[:10]:
            story.append(Paragraph(f"⚑ {seg.label}", h3_style))
            story.append(Paragraph(seg.details, body_style))

    # Plagiarism
    story.append(Paragraph("Similarity / Plagiarism", h2_style))
    for note in pl.notes:
        story.append(Paragraph(note, body_style))
    if pl.flagged_sources:
        for src in pl.flagged_sources:
            story.append(Paragraph(f"⚑ {src.get('title','Unknown')}", h3_style))
            story.append(Paragraph(f"Exact: {src.get('exact_match_score')}%  Near: {src.get('near_match_score')}%", body_style))

    # Grammar
    if report.grammar and report.grammar.total_issues > 0:
        story.append(Paragraph("Grammar Issues", h2_style))
        for issue in report.grammar.issues[:20]:
            story.append(Paragraph(f"• {issue.short_message}", h3_style))
            story.append(Paragraph(issue.message, body_style))
            if issue.suggestions:
                story.append(Paragraph(f"Suggestions: {', '.join(issue.suggestions[:3])}", muted_style))

    # File hash
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=8))
    story.append(Paragraph("File Integrity (SHA-256)", muted_style))
    story.append(Paragraph(report.file_hash_sha256, mono_style))

    doc.build(story)
