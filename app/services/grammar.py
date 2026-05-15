from __future__ import annotations

import httpx

from app.config import settings
from app.schemas import GrammarReport, GrammarSuggestion
from app.services.parser import ParsedDocument

# Categories to skip — these are stylistic and not errors in academic writing
SKIP_CATEGORIES = {"TYPOGRAPHY", "PUNCTUATION_SPACING", "REDUNDANCY_DASHES"}

# Rules to skip (too noisy for academic text)
SKIP_RULES = {
    "EN_QUOTES", "DASH_RULE", "COMMA_PARENTHESIS_WHITESPACE",
    "WHITESPACE_RULE", "DOUBLE_PUNCTUATION",
}

# Severity mapping by LanguageTool type
SEVERITY_MAP = {
    "grammar": "error",
    "spelling": "error",
    "style": "warning",
    "typographical": "warning",
    "punctuation": "warning",
    "other": "warning",
}


async def build_grammar_report(parsed: ParsedDocument) -> GrammarReport:
    """
    Call the LanguageTool public API (free, no key required) and return
    a structured grammar report with suggestions for each issue.
    """
    notes: list[str] = []

    # Truncate to 20k chars — LanguageTool free API limit
    text = parsed.full_text[:20000]
    if len(parsed.full_text) > 20000:
        notes.append(
            "The document was truncated to 20,000 characters for grammar checking "
            "due to free API limits. The first portion of the document was analysed."
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.languagetool_url,
                data={
                    "text": text,
                    "language": "en-US",
                    "enabledOnly": "false",
                    "level": "picky",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        notes.append("Grammar check timed out. LanguageTool may be temporarily unavailable.")
        return _empty_report(notes)
    except Exception as exc:
        notes.append(f"Grammar check unavailable: {exc}. The rest of the report is unaffected.")
        return _empty_report(notes)

    matches = data.get("matches", [])
    issues: list[GrammarSuggestion] = []
    error_count = 0
    warning_count = 0
    suggestion_count = 0

    for match in matches:
        rule = match.get("rule", {})
        rule_id = rule.get("id", "")
        category = rule.get("category", {}).get("id", "OTHER")

        # Skip noisy/irrelevant rules
        if rule_id in SKIP_RULES or category in SKIP_CATEGORIES:
            continue

        issue_type = match.get("type", {}).get("typeName", "other").lower()
        severity = SEVERITY_MAP.get(issue_type, "warning")

        replacements = [r["value"] for r in match.get("replacements", [])[:4]]
        offset = match.get("offset", 0)
        length = match.get("length", 0)
        original = text[offset: offset + length]

        # Build context: show surrounding text
        ctx_start = max(0, offset - 40)
        ctx_end = min(len(text), offset + length + 40)
        context_raw = text[ctx_start:ctx_end].replace("\n", " ")
        context = f"...{context_raw}..." if ctx_start > 0 else context_raw

        message = match.get("message", "")
        short_message = match.get("shortMessage", "") or message[:80]

        issues.append(GrammarSuggestion(
            message=message,
            short_message=short_message,
            original=original,
            suggestions=replacements,
            offset=offset,
            length=length,
            rule_id=rule_id,
            category=category,
            context=context,
        ))

        if severity == "error":
            error_count += 1
        elif severity == "warning":
            warning_count += 1
        else:
            suggestion_count += 1

    # Summary note
    if issues:
        notes.append(
            f"LanguageTool found {len(issues)} issue(s): "
            f"{error_count} grammar/spelling error(s), "
            f"{warning_count} style warning(s). "
            "Suggestions are shown for each issue — review and apply as appropriate."
        )
    else:
        notes.append(
            "No grammar or spelling issues detected by LanguageTool. "
            "The text passed automated language quality checks."
        )

    return GrammarReport(
        total_issues=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        suggestion_count=suggestion_count,
        issues=issues[:60],  # cap at 60 to keep report readable
        notes=notes,
    )


def _empty_report(notes: list[str]) -> GrammarReport:
    return GrammarReport(
        total_issues=0,
        error_count=0,
        warning_count=0,
        suggestion_count=0,
        issues=[],
        notes=notes,
    )
