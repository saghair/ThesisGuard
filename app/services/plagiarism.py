from __future__ import annotations

from collections import Counter
from statistics import mean

import httpx

from app.config import settings
from app.schemas import PlagiarismReport
from app.services.parser import ParsedDocument


INTERNAL_REFERENCE_CORPUS = [
    {
        "title": "Sample Academic Writing Guide",
        "source": "internal://writing-guide",
        "text": "Academic research should present a clear methodology, validated results, and a conclusion linked directly to the stated objectives.",
    },
    {
        "title": "Sample Cybersecurity Thesis Snippet",
        "source": "internal://cybersecurity-sample",
        "text": "Information security aims to preserve confidentiality, integrity, and availability through policy, technical controls, and user awareness.",
    },
]


def _normalize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
    return [token for token in cleaned.split() if len(token) > 2]


def _jaccard_similarity(a: list[str], b: list[str]) -> float:
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


async def _call_external_plagiarism_api(text: str) -> dict | None:
    if not settings.plagiarism_api_url or not settings.plagiarism_api_key:
        return None

    payload = {"text": text}
    headers = {"Authorization": f"Bearer {settings.plagiarism_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(settings.plagiarism_api_url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


async def build_plagiarism_report(parsed: ParsedDocument) -> PlagiarismReport:
    external_result = await _call_external_plagiarism_api(parsed.full_text)
    if external_result:
        return PlagiarismReport(
            similarity_score=float(external_result.get("similarity_score", 0.0)),
            exact_match_score=float(external_result.get("exact_match_score", 0.0)),
            near_match_score=float(external_result.get("near_match_score", 0.0)),
            flagged_sources=external_result.get("flagged_sources", []),
            notes=external_result.get(
                "notes",
                ["External plagiarism provider result returned successfully."],
            ),
        )

    thesis_tokens = _normalize(parsed.full_text)
    thesis_counter = Counter(thesis_tokens)
    flagged_sources: list[dict] = []
    exact_scores: list[float] = []
    near_scores: list[float] = []

    for item in INTERNAL_REFERENCE_CORPUS:
        source_tokens = _normalize(item["text"])
        overlap = sum((thesis_counter & Counter(source_tokens)).values())
        exact_score = round((overlap / max(1, len(source_tokens))) * 100, 2)
        near_score = round(_jaccard_similarity(thesis_tokens, source_tokens) * 100, 2)
        exact_scores.append(exact_score)
        near_scores.append(near_score)
        if exact_score >= 15 or near_score >= 12:
            flagged_sources.append(
                {
                    "title": item["title"],
                    "source": item["source"],
                    "exact_match_score": exact_score,
                    "near_match_score": near_score,
                }
            )

    exact_match_score = round(mean(exact_scores), 2) if exact_scores else 0.0
    near_match_score = round(mean(near_scores), 2) if near_scores else 0.0
    similarity_score = round((exact_match_score * 0.65) + (near_match_score * 0.35), 2)

    return PlagiarismReport(
        similarity_score=similarity_score,
        exact_match_score=exact_match_score,
        near_match_score=near_match_score,
        flagged_sources=flagged_sources,
        notes=[
            "This prototype uses a local reference corpus fallback when no external plagiarism API is configured.",
            "For production accuracy, connect a web-scale plagiarism or similarity provider.",
        ],
    )
