from __future__ import annotations

import re
from collections import Counter
from statistics import mean
from difflib import SequenceMatcher

from app.schemas import ComplianceReport, SectionFlag
from app.services.parser import ParsedDocument


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _fuzzy_match(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0-1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _section_found(required: str, found_sections: list[str], threshold: float = 0.82) -> tuple[bool, str | None]:
    """
    Check if a required section exists in found_sections.
    Returns (found: bool, matched_heading: str | None).
    Uses exact normalised match first, then fuzzy fallback.
    """
    req_norm = _normalize(required)
    for s in found_sections:
        if req_norm in _normalize(s) or _normalize(s) in req_norm:
            return True, s
        if _fuzzy_match(req_norm, _normalize(s)) >= threshold:
            return True, s
    return False, None


# ── Typo / grammar dictionary ─────────────────────────────────────────────────

TYPO_HINTS: dict[str, str] = {
    # Classic misspellings
    " teh ": "'teh' should be 'the'",
    " recieve ": "'recieve' should be 'receive'",
    " seperate ": "'seperate' should be 'separate'",
    " occured ": "'occured' should be 'occurred'",
    " accomodate ": "'accomodate' should be 'accommodate'",
    " begining ": "'begining' should be 'beginning'",
    " beleive ": "'beleive' should be 'believe'",
    " calender ": "'calender' should be 'calendar'",
    " cemetary ": "'cemetary' should be 'cemetery'",
    " conscous ": "'conscous' should be 'conscious'",
    " definately ": "'definately' should be 'definitely'",
    " embarass ": "'embarass' should be 'embarrass'",
    " existance ": "'existance' should be 'existence'",
    " foward ": "'foward' should be 'forward'",
    " goverment ": "'goverment' should be 'government'",
    " grammer ": "'grammer' should be 'grammar'",
    " harrass ": "'harrass' should be 'harass'",
    " independant ": "'independant' should be 'independent'",
    " knowlege ": "'knowlege' should be 'knowledge'",
    " liason ": "'liason' should be 'liaison'",
    " maintainance ": "'maintainance' should be 'maintenance'",
    " millenium ": "'millenium' should be 'millennium'",
    " neccessary ": "'neccessary' should be 'necessary'",
    " noticable ": "'noticable' should be 'noticeable'",
    " occassion ": "'occassion' should be 'occasion'",
    " persistance ": "'persistance' should be 'persistence'",
    " priviledge ": "'priviledge' should be 'privilege'",
    " publically ": "'publically' should be 'publicly'",
    " recomend ": "'recomend' should be 'recommend'",
    " relevent ": "'relevent' should be 'relevant'",
    " remeber ": "'remeber' should be 'remember'",
    " repitition ": "'repitition' should be 'repetition'",
    " reserach ": "'reserach' should be 'research'",
    " sieze ": "'sieze' should be 'seize'",
    " succesful ": "'succesful' should be 'successful'",
    " suprise ": "'suprise' should be 'surprise'",
    " tendancy ": "'tendancy' should be 'tendency'",
    " thier ": "'thier' should be 'their'",
    " transfered ": "'transfered' should be 'transferred'",
    " untill ": "'untill' should be 'until'",
    " wierd ": "'wierd' should be 'weird'",
    # Academic writing issues
    " alot ": "'alot' should be 'a lot' (two words)",
    " cant ": "Missing apostrophe: 'cant' should be 'can't'",
    " dont ": "Missing apostrophe: 'dont' should be 'don't'",
    " wont ": "Missing apostrophe: 'wont' should be 'won't'",
    " its a ": "Possible confusion: check if 'its' should be 'it's'",
}

# Informal / non-academic phrases
INFORMAL_PHRASES: list[tuple[str, str]] = [
    ("a lot of", "Consider replacing 'a lot of' with 'numerous', 'many', or 'significant'"),
    ("things like", "Vague phrasing — consider being more specific"),
    ("stuff like", "Informal phrasing — avoid in academic writing"),
    ("kind of", "Informal hedge — consider 'somewhat' or restructuring the sentence"),
    ("sort of", "Informal hedge — consider 'somewhat' or restructuring the sentence"),
    ("you can see", "Avoid second-person — rephrase to passive or third-person"),
    ("you should", "Avoid second-person — rephrase to passive or third-person"),
    ("i think", "First-person 'I think' is informal — consider 'this study argues' or 'evidence suggests'"),
    ("i believe", "First-person 'I believe' is informal — consider 'this study contends'"),
    ("we think", "Informal — consider 'this study suggests' or a passive construction"),
    ("very unique", "'Unique' is absolute — 'very unique' is redundant"),
    ("end result", "'End result' is redundant — use 'result'"),
    ("past history", "'Past history' is redundant — use 'history'"),
]

# Minimum word counts per section type
SECTION_MIN_WORDS: dict[str, int] = {
    "abstract": 100,
    "introduction": 200,
    "methodology": 200,
    "conclusion": 150,
    "references": 50,
    "literature review": 300,
    "discussion": 150,
}


# ── Main ──────────────────────────────────────────────────────────────────────

def build_compliance_report(parsed: ParsedDocument, template: dict) -> ComplianceReport:
    passed_checks: list[str] = []
    warnings: list[SectionFlag] = []
    errors: list[SectionFlag] = []

    file_type = getattr(parsed, "file_type", "docx")
    is_pdf = file_type == "pdf"

    # ── 1. Required sections ──────────────────────────────────────────────────
    required_sections = template.get("required_sections", [])
    found_section_names = parsed.sections

    # Build a map of section name → text block for word-count checks
    section_text_map: dict[str, str] = {}
    current_section = None
    current_lines: list[str] = []
    for para in parsed.paragraphs:
        if para.style_name.lower().startswith("heading") or para.text in found_section_names:
            if current_section and current_lines:
                section_text_map[current_section.lower()] = " ".join(current_lines)
            current_section = para.text
            current_lines = []
        elif para.text and current_section:
            current_lines.append(para.text)
    if current_section and current_lines:
        section_text_map[current_section.lower()] = " ".join(current_lines)

    for section in required_sections:
        found, matched = _section_found(section, found_section_names)
        if not found:
            # Give a helpful suggestion if it's a common section name
            suggestion = ""
            close = sorted(
                found_section_names,
                key=lambda s: _fuzzy_match(_normalize(section), _normalize(s)),
                reverse=True,
            )
            if close and _fuzzy_match(_normalize(section), _normalize(close[0])) > 0.5:
                suggestion = f" Did you mean '{close[0]}'?"
            errors.append(SectionFlag(
                label="Missing required section",
                severity="error",
                details=(
                    f"The section '{section}' is required by the template but was not found in the document.{suggestion} "
                    f"Ensure the heading is styled as 'Heading 1' or 'Heading 2' in Word so it can be detected."
                ),
                location_hint="Document structure",
            ))
        else:
            passed_checks.append(f"Required section present: '{section}' (detected as '{matched}')")

            # Word count check for known sections
            sec_key = section.lower()
            min_words = None
            for key, minimum in SECTION_MIN_WORDS.items():
                if key in sec_key:
                    min_words = minimum
                    break

            if min_words:
                content = section_text_map.get(matched.lower() if matched else "", "")
                word_count = len(content.split()) if content else 0
                if word_count == 0:
                    warnings.append(SectionFlag(
                        label="Empty section",
                        severity="warning",
                        details=(
                            f"The '{section}' section appears to have no content under its heading. "
                            f"This section is expected to contain at least {min_words} words."
                        ),
                        location_hint=f"Section: {section}",
                    ))
                elif word_count < min_words:
                    warnings.append(SectionFlag(
                        label="Section may be too short",
                        severity="warning",
                        details=(
                            f"The '{section}' section contains approximately {word_count} words, "
                            f"which is below the recommended minimum of {min_words} words for this section type."
                        ),
                        location_hint=f"Section: {section}",
                    ))
                else:
                    passed_checks.append(f"'{section}' word count is adequate ({word_count} words)")

    # ── 2. Font family ────────────────────────────────────────────────────────
    all_font_names = [name for p in parsed.paragraphs for name in p.font_names if p.text]
    if all_font_names:
        font_counter = Counter(all_font_names)
        most_common_fonts = font_counter.most_common(5)
        allowed_fonts = set(template.get("allowed_fonts", []))
        disallowed = [(font, count) for font, count in most_common_fonts if font not in allowed_fonts]

        if disallowed:
            total = sum(font_counter.values())
            details_parts = []
            for font, count in disallowed:
                pct = round(count / total * 100)
                details_parts.append(f"'{font}' ({pct}% of runs)")
            warnings.append(SectionFlag(
                label="Non-compliant font usage detected",
                severity="warning",
                details=(
                    f"The following fonts are not allowed by the template: {', '.join(details_parts)}. "
                    f"The template requires: {', '.join(sorted(allowed_fonts))}. "
                    f"Select all text (Ctrl+A) and apply the correct font in Word before resubmitting."
                ),
                location_hint="Body text — multiple paragraphs",
            ))
        else:
            top_font = most_common_fonts[0][0] if most_common_fonts else "Unknown"
            passed_checks.append(f"Font usage is compliant (primary font: '{top_font}')")
    else:
        if is_pdf:
            warnings.append(SectionFlag(
                label="Font metadata limited (PDF)",
                severity="warning",
                details=(
                    "PDF files do not always embed precise font names. "
                    "Font compliance checking is less reliable for PDFs. "
                    "Consider resubmitting as DOCX for a more accurate font check."
                ),
                location_hint="Body text",
            ))
        else:
            warnings.append(SectionFlag(
                label="Font data unavailable",
                severity="warning",
                details=(
                    "No explicit font metadata was found in the document. "
                    "This can happen if the document uses default theme fonts without explicit overrides. "
                    "Open the document in Word, select all text, and confirm the font is set explicitly."
                ),
                location_hint="Body text",
            ))

    # ── 3. Font size ──────────────────────────────────────────────────────────
    # Exclude likely heading sizes (>= 14pt) from body text size check
    body_font_sizes = [
        size for p in parsed.paragraphs for size in p.font_sizes_pt
        if p.text and not p.style_name.lower().startswith("heading") and size < 14.0
    ]
    if body_font_sizes:
        avg_size = round(mean(body_font_sizes), 1)
        allowed_sizes = set(template.get("allowed_font_sizes", []))
        size_counter = Counter(round(s) for s in body_font_sizes)
        most_common_size, most_common_count = size_counter.most_common(1)[0]

        if round(avg_size) not in allowed_sizes:
            pct = round(most_common_count / len(body_font_sizes) * 100)
            warnings.append(SectionFlag(
                label="Body font size does not match template",
                severity="warning",
                details=(
                    f"The most common body font size is {most_common_size}pt ({pct}% of text runs), "
                    f"but the template requires {sorted(allowed_sizes)}pt. "
                    f"Select all body text in Word and set the font size to {sorted(allowed_sizes)[0]}pt."
                ),
                location_hint="Body text",
            ))
        else:
            passed_checks.append(f"Body font size is compliant (avg {avg_size}pt, template allows {sorted(allowed_sizes)}pt)")

    # ── 4. Line spacing ───────────────────────────────────────────────────────
    expected_spacing = float(template.get("line_spacing", 1.5))
    spacing_values = [s for p in parsed.paragraphs for s in p.line_spacings if p.text]

    if spacing_values:
        avg_spacing = round(mean(spacing_values), 2)
        off_count = sum(1 for s in spacing_values if abs(s - expected_spacing) > 0.2)
        off_pct = round(off_count / len(spacing_values) * 100)

        if abs(avg_spacing - expected_spacing) > 0.2:
            warnings.append(SectionFlag(
                label="Line spacing does not match template",
                severity="warning",
                details=(
                    f"The average line spacing detected is {avg_spacing} "
                    f"({off_pct}% of paragraphs are non-compliant). "
                    f"The template requires {expected_spacing} line spacing. "
                    f"In Word: select all (Ctrl+A) → Home → Line Spacing → {expected_spacing}."
                ),
                location_hint="Paragraph formatting",
            ))
        else:
            passed_checks.append(f"Line spacing is compliant (avg {avg_spacing}, template: {expected_spacing})")
    else:
        if is_pdf:
            warnings.append(SectionFlag(
                label="Line spacing not available (PDF)",
                severity="warning",
                details=(
                    "Line spacing values cannot be reliably extracted from PDF files. "
                    "This check was skipped. Resubmit as DOCX for a full line spacing check."
                ),
                location_hint="Paragraph formatting",
            ))
        else:
            warnings.append(SectionFlag(
                label="Line spacing could not be determined",
                severity="warning",
                details=(
                    "The document does not expose line spacing values in a readable format. "
                    f"Ensure the document uses '{expected_spacing}' line spacing set via "
                    "Paragraph → Line Spacing → Multiple in Word."
                ),
                location_hint="Paragraph formatting",
            ))

    # ── 5. Margins ────────────────────────────────────────────────────────────
    expected_margins = template.get("margins_cm", {})
    if parsed.page_margins_cm:
        margin_issues = []
        margin_ok = []
        for side, expected_value in expected_margins.items():
            actual = parsed.page_margins_cm.get(side)
            if actual is None:
                continue
            diff = round(actual - expected_value, 2)
            if abs(diff) > 0.15:
                direction = "too wide" if diff > 0 else "too narrow"
                margin_issues.append(
                    f"{side.capitalize()} margin is {actual}cm ({direction} by {abs(diff)}cm — expected {expected_value}cm)"
                )
            else:
                margin_ok.append(side)

        if margin_issues:
            errors.append(SectionFlag(
                label="Page margin mismatch",
                severity="error",
                details=(
                    f"{'; '.join(margin_issues)}. "
                    f"Fix in Word via: Layout → Margins → Custom Margins."
                ),
                location_hint="Page setup",
            ))
        else:
            passed_checks.append(f"All page margins are compliant ({', '.join(margin_ok)})")
    else:
        warnings.append(SectionFlag(
            label="Margin data unavailable",
            severity="warning",
            details=(
                "Page margin information could not be extracted from this document. "
                + ("PDF margin detection is approximate — verify manually." if is_pdf
                   else "Ensure the document is not protected and try re-saving it in Word.")
            ),
            location_hint="Page setup",
        ))

    # ── 6. Heading patterns ───────────────────────────────────────────────────
    for pattern in template.get("heading_patterns", []):
        matched_heading = next(
            (h for h in parsed.heading_texts if pattern.lower() in h.lower()), None
        )
        if not matched_heading:
            warnings.append(SectionFlag(
                label="Expected heading pattern not found",
                severity="warning",
                details=(
                    f"No heading contained the text '{pattern}'. "
                    f"The template expects this pattern to appear as a chapter or section heading. "
                    f"Found headings: {', '.join(parsed.heading_texts[:6]) or 'none detected'}."
                ),
                location_hint="Heading structure",
            ))
        else:
            passed_checks.append(f"Heading pattern '{pattern}' found: '{matched_heading}'")

    # ── 7. Typos ──────────────────────────────────────────────────────────────
    padded_text = f" {parsed.full_text.lower()} "
    typos_found: list[str] = []
    for token, hint in TYPO_HINTS.items():
        if token in padded_text:
            typos_found.append(hint)

    if typos_found:
        warnings.append(SectionFlag(
            label=f"Possible spelling/grammar issues ({len(typos_found)} found)",
            severity="warning",
            details=(
                "The following issues were detected: "
                + "; ".join(typos_found)
                + ". Run a spell-check in Word before resubmitting."
            ),
            location_hint="Text content",
        ))
    else:
        passed_checks.append("No common spelling issues detected")

    # ── 8. Informal language ──────────────────────────────────────────────────
    informal_found: list[str] = []
    lower_text = parsed.full_text.lower()
    for phrase, advice in INFORMAL_PHRASES:
        if phrase in lower_text:
            informal_found.append(advice)

    if informal_found:
        warnings.append(SectionFlag(
            label=f"Informal or non-academic language detected ({len(informal_found)} instances)",
            severity="warning",
            details="; ".join(informal_found),
            location_hint="Text content",
        ))

    # ── 9. Document length sanity check ──────────────────────────────────────
    total_words = len(parsed.full_text.split())
    if total_words < 1000:
        warnings.append(SectionFlag(
            label="Document appears very short",
            severity="warning",
            details=(
                f"The document contains approximately {total_words} words, "
                "which is unusually short for a thesis. "
                "Verify the correct file was uploaded and that all content was included."
            ),
            location_hint="Document",
        ))
    else:
        passed_checks.append(f"Document length is reasonable ({total_words:,} words)")

    # ── Score ─────────────────────────────────────────────────────────────────
    error_deduction = min(60.0, 12.0 * len(errors))
    warning_deduction = min(40.0, 3.5 * len(warnings))
    compliance_score = max(0.0, round(100.0 - error_deduction - warning_deduction, 2))

    return ComplianceReport(
        compliance_score=compliance_score,
        passed_checks=passed_checks,
        warnings=warnings,
        errors=errors,
        extracted_sections=parsed.sections,
    )
