from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.schemas import SubmissionReport


def save_report(report: SubmissionReport, destination: Path) -> None:
    destination.write_text(
        json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def build_final_summary(report: SubmissionReport) -> str:
    c = report.compliance
    ai = report.ai_risk
    pl = report.plagiarism

    lines: list[str] = []
    lines.append(
        f"Verification completed on {datetime.utcnow().strftime('%Y-%m-%d at %H:%M UTC')} "
        f"for '{report.original_filename}' (template: '{report.template_name}')."
    )

    # ── Compliance summary ────────────────────────────────────────────────────
    score = c.compliance_score
    if score >= 90:
        comp_verdict = "excellent — the document is highly compliant with the template"
    elif score >= 75:
        comp_verdict = "good — the document meets most requirements with minor issues"
    elif score >= 55:
        comp_verdict = "moderate — several issues need to be addressed before acceptance"
    else:
        comp_verdict = "poor — the document has significant compliance issues that must be corrected"

    lines.append(
        f"COMPLIANCE ({score}/100 — {comp_verdict}): "
        f"{len(c.errors)} error(s) and {len(c.warnings)} warning(s) were found. "
        f"{len(c.passed_checks)} check(s) passed."
    )

    if c.errors:
        error_labels = "; ".join(f.label for f in c.errors[:3])
        if len(c.errors) > 3:
            error_labels += f" and {len(c.errors) - 3} more"
        lines.append(f"Critical errors: {error_labels}.")

    if c.warnings:
        warn_labels = "; ".join(f.label for f in c.warnings[:3])
        if len(c.warnings) > 3:
            warn_labels += f" and {len(c.warnings) - 3} more"
        lines.append(f"Warnings: {warn_labels}.")

    # ── AI risk summary ───────────────────────────────────────────────────────
    ai_colour = {"low": "no significant", "medium": "some", "high": "substantial"}[ai.risk_level]
    lines.append(
        f"AI-RISK ({ai.risk_score}% — {ai.risk_level.upper()}): "
        f"The analysis detected {ai_colour} AI-generation indicators. "
        f"{len(ai.flagged_segments)} of the analysed text segment(s) were flagged. "
        "This result is advisory only and must not be used as sole evidence of misconduct."
    )

    # ── Plagiarism summary ────────────────────────────────────────────────────
    if pl.similarity_score < 15:
        sim_verdict = "low similarity — no significant matches detected"
    elif pl.similarity_score < 30:
        sim_verdict = "moderate similarity — some matching content found"
    else:
        sim_verdict = "high similarity — substantial matching content detected"

    lines.append(
        f"SIMILARITY ({pl.similarity_score}% — {sim_verdict}): "
        f"Exact match: {pl.exact_match_score}%, near match: {pl.near_match_score}%. "
        f"{len(pl.flagged_sources)} source(s) flagged."
        + (" Note: only an internal reference corpus was used — connect an external provider for full web-scale checking." 
           if "local reference corpus" in " ".join(pl.notes) else "")
    )

    # ── Overall verdict ───────────────────────────────────────────────────────
    if score >= 85 and ai.risk_level == "low" and pl.similarity_score < 15:
        verdict = "OVERALL VERDICT: The submission is structurally strong and low-risk. It is ready for human reviewer inspection."
    elif score >= 70 and ai.risk_level != "high" and pl.similarity_score < 30:
        verdict = "OVERALL VERDICT: The submission is acceptable for review but requires the author to address the flagged issues before final submission."
    elif score < 55 or c.errors:
        verdict = "OVERALL VERDICT: The submission should be returned to the author. Critical compliance errors must be resolved before it can proceed to review."
    else:
        verdict = "OVERALL VERDICT: The submission requires careful human review due to multiple concerns detected across one or more categories."

    lines.append(verdict)

    return " | ".join(lines)
