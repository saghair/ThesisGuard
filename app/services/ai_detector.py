from __future__ import annotations

from statistics import mean

import httpx

from app.config import settings
from app.schemas import AIRiskReport, SectionFlag
from app.services.parser import ParsedDocument

SAPLING_URL = "https://api.sapling.ai/api/v1/aidetect"


def _split_segments(text: str, limit: int = 1200) -> list[str]:
    parts = [p.strip() for p in text.split("\n") if len(p.strip()) > 60]
    segments: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) + 1 <= limit:
            current = f"{current}\n{part}".strip()
        else:
            if current:
                segments.append(current)
            current = part
    if current:
        segments.append(current)
    return segments[:12]


def _score_reasons(segment: str) -> tuple[float, list[str]]:
    words = segment.split()
    if not words:
        return 0.0, []

    reasons: list[str] = []
    score = 0.0

    sentence_count = max(1, segment.count(".") + segment.count("!") + segment.count("?"))
    avg_sentence_len = len(words) / sentence_count
    if 16 <= avg_sentence_len <= 28:
        score += 28
        reasons.append(
            f"unusually uniform sentence length (avg {round(avg_sentence_len, 1)} words/sentence)"
        )

    unique_ratio = len(set(w.lower().strip(",.;:!?()[]{}") for w in words)) / len(words)
    if unique_ratio < 0.62:
        score += 22
        reasons.append(f"low vocabulary diversity ({round(unique_ratio * 100)}% unique words)")

    connectors = [
        "therefore", "moreover", "furthermore", "in conclusion", "overall",
        "additionally", "consequently", "nevertheless", "it is worth noting",
        "it is important to note", "in summary", "to summarize",
    ]
    connector_count = sum(segment.lower().count(t) for t in connectors)
    if connector_count >= 3:
        score += 18
        found = [t for t in connectors if t in segment.lower()]
        reasons.append(f"high density of formal connectors ({', '.join(found[:4])})")

    if len(words) >= 180:
        score += 12
        reasons.append(f"long segment ({len(words)} words) with consistent style")

    structural = (
        segment.count("Firstly") + segment.count("Secondly") + segment.count("Finally")
        + segment.count("First,") + segment.count("Second,") + segment.count("Third,")
    )
    if structural >= 2:
        score += 15
        reasons.append("rigid enumeration structure (Firstly/Secondly/Finally pattern)")

    hedges = [
        "it is worth", "it should be noted", "it is important",
        "one could argue", "it can be seen", "as mentioned above", "as previously stated",
    ]
    hedge_count = sum(segment.lower().count(h) for h in hedges)
    if hedge_count >= 2:
        score += 10
        reasons.append(f"repeated hedging phrases ({hedge_count} instances)")

    return min(95.0, score), reasons


async def _call_sapling(text: str) -> dict | None:
    """Call Sapling AI detector API."""
    if not settings.sapling_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                SAPLING_URL,
                json={
                    "key": settings.sapling_api_key,
                    "text": text[:5000],  # Sapling free tier limit
                },
            )
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


async def build_ai_risk_report(parsed: ParsedDocument) -> AIRiskReport:
    segments = _split_segments(parsed.full_text)
    flagged_segments: list[SectionFlag] = []
    scores: list[float] = []

    notes = [
        "AI-risk scores are statistical estimates to assist reviewers — not proof of AI use.",
        "Short passages, reference lists, and standard academic phrases naturally score lower.",
        "A high score warrants closer human review, not automatic rejection.",
    ]

    # ── Try Sapling first ─────────────────────────────────────────────────────
    sapling_result = await _call_sapling(parsed.full_text)

    if sapling_result and "score" in sapling_result:
        overall_score = sapling_result["score"]  # 0.0 to 1.0
        score_pct = round(overall_score * 100, 1)
        scores.append(score_pct)

        # Sapling returns sentence-level scores too
        sentence_scores = sapling_result.get("sentence_scores", [])
        for i, (sentence, sent_score) in enumerate(sentence_scores):
            if sent_score >= 0.75:
                preview = sentence[:120]
                flagged_segments.append(SectionFlag(
                    label=f"Sapling: High AI probability sentence",
                    severity="error" if sent_score >= 0.90 else "warning",
                    details=(
                        f"Sapling assigned {round(sent_score * 100, 1)}% AI probability. "
                        f"This sentence shows strong patterns of AI-generated text. "
                        f"Preview: \"{preview}\""
                    ),
                    location_hint=f"Sentence {i + 1}",
                ))

        notes.insert(0, (
            f"Sapling AI analysis: overall AI probability {score_pct}%. "
            f"{len(flagged_segments)} high-risk sentence(s) flagged."
        ))

    # ── Fall back to local heuristic if Sapling not available ────────────────
    if not scores:
        notes.insert(0, "Sapling API not configured — using built-in heuristic analysis.")
        for index, segment in enumerate(segments, start=1):
            score, reasons = _score_reasons(segment)
            scores.append(score)

            if score >= 55:
                preview = segment[:120].replace("\n", " ").strip()
                if len(segment) > 120:
                    preview += "…"
                reason_text = "; ".join(reasons) if reasons else "No specific indicators."
                flagged_segments.append(SectionFlag(
                    label=f"Segment {index} — AI-generation risk ({round(score)}%)",
                    severity="warning" if score < 75 else "error",
                    details=(
                        f"Risk score: {round(score, 1)}%. "
                        f"Indicators: {reason_text}. "
                        f"Preview: \"{preview}\""
                    ),
                    location_hint=f"Segment {index} of {len(segments)}",
                ))

    final_score = round(mean(scores), 2) if scores else 0.0

    if final_score >= 75:
        level = "high"
        level_note = (
            f"Overall AI-risk: {final_score}% (HIGH). "
            f"{len(flagged_segments)} segment(s) flagged. "
            "This does not confirm AI use — a human examiner must review the flagged sections."
        )
    elif final_score >= 45:
        level = "medium"
        level_note = (
            f"Overall AI-risk: {final_score}% (MEDIUM). "
            f"{len(flagged_segments)} segment(s) showed AI-like patterns. "
            "Closer review of flagged sections is recommended."
        )
    else:
        level = "low"
        level_note = (
            f"Overall AI-risk: {final_score}% (LOW). "
            "Writing patterns are broadly consistent with human authorship."
        )

    notes.insert(0, level_note)

    return AIRiskReport(
        risk_level=level,
        risk_score=final_score,
        flagged_segments=flagged_segments,
        notes=notes,
    )
