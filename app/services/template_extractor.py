from __future__ import annotations
from pathlib import Path
from collections import Counter
from statistics import mean

from app.services.parser import parse_docx, parse_pdf


def extract_template_from_file(path: Path, template_name: str) -> dict:
    """
    Read an example thesis file and extract formatting rules
    to use as a template configuration.
    """
    suffix = path.suffix.lower()
    if suffix == ".docx":
        parsed = parse_docx(path)
    elif suffix == ".pdf":
        from app.services.parser import parse_pdf
        parsed = parse_pdf(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    # ── Font family ───────────────────────────────────────────────
    all_fonts = [
        name for p in parsed.paragraphs
        for name in p.font_names
        if p.text and not p.style_name.lower().startswith("heading")
    ]
    font_counts = Counter(all_fonts)
    allowed_fonts = [font for font, _ in font_counts.most_common(2)] if font_counts else ["Times New Roman"]

    # ── Font size ─────────────────────────────────────────────────
    body_sizes = [
        size for p in parsed.paragraphs
        for size in p.font_sizes_pt
        if p.text and not p.style_name.lower().startswith("heading") and size < 14
    ]
    if body_sizes:
        avg_size = round(mean(body_sizes))
        allowed_font_sizes = [avg_size]
    else:
        allowed_font_sizes = [12]

    # ── Line spacing ──────────────────────────────────────────────
    spacings = [
        s for p in parsed.paragraphs
        for s in p.line_spacings
        if p.text
    ]
    if spacings:
        avg_spacing = round(mean(spacings) * 2) / 2  # round to nearest 0.5
        line_spacing = max(1.0, min(3.0, avg_spacing))
    else:
        line_spacing = 1.5

    # ── Margins ───────────────────────────────────────────────────
    margins_cm = {"top": 2.5, "bottom": 2.5, "left": 3.0, "right": 2.5}
    if parsed.page_margins_cm:
        for side in ("top", "bottom", "left", "right"):
            val = parsed.page_margins_cm.get(side)
            if val and 1.0 <= val <= 5.0:
                margins_cm[side] = round(val, 1)

    # ── Sections (from headings) ──────────────────────────────────
    # Use detected headings as required sections
    seen = set()
    required_sections = []
    for heading in parsed.heading_texts:
        clean = heading.strip()
        if clean and clean.lower() not in seen and len(clean) < 60:
            seen.add(clean.lower())
            required_sections.append(clean)

    # ── Heading patterns ──────────────────────────────────────────
    heading_patterns = []
    for h in required_sections:
        lower = h.lower()
        if lower.startswith("chapter"):
            heading_patterns.append(h)
        elif any(lower.startswith(kw) for kw in ["section", "part"]):
            heading_patterns.append(h)

    # ── Build template config ─────────────────────────────────────
    config = {
        "name": template_name,
        "document_type": "thesis",
        "allowed_fonts": allowed_fonts if allowed_fonts else ["Times New Roman"],
        "allowed_font_sizes": allowed_font_sizes,
        "line_spacing": line_spacing,
        "margins_cm": margins_cm,
        "required_sections": required_sections[:15],  # cap at 15
        "heading_patterns": heading_patterns[:10],
        "citation_style": None,
        "notes": f"Auto-extracted from example file. Detected {len(required_sections)} sections, font: {', '.join(allowed_fonts[:2])}, size: {allowed_font_sizes[0]}pt, spacing: {line_spacing}.",
    }

    return config
