"""Cheap, transparent heuristics for spotting suspicious OCR pages."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from .prompt import SKIP_PAGE_SENTINEL


def normalize_markdown(text: str) -> str:
    """Remove transport noise while preserving the model's Markdown structure."""

    if not isinstance(text, str):
        raise TypeError("OCR output must be text")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = normalized.strip().split("\n")
    if len(lines) >= 2:
        first = lines[0].strip().lower()
        if first in {"```", "```md", "```markdown"} and lines[-1].strip() == "```":
            lines = lines[1:-1]
    normalized = "\n".join(lines).strip()
    if not normalized:
        raise ValueError("OCR output was empty")
    return normalized + "\n"


def is_skip_page_sentinel(text: str) -> bool:
    """Return whether normalized model output is exactly the page-skip sentinel."""

    return text.strip() == SKIP_PAGE_SENTINEL


def _looks_like_non_text_note(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "non-text",
        "non text",
        "illustration",
        "no readable text",
        "no text transcribed",
        "image or illustration",
    )
    return any(marker in lowered for marker in markers)


def assess_markdown(text: str) -> dict[str, Any]:
    """Return deterministic warning signals without declaring OCR truth or falsehood."""

    characters = len(text)
    words = len(re.findall(r"\b[\w'_-]+\b", text, flags=re.UNICODE))
    lines = [line for line in text.splitlines() if line.strip()]
    replacement_count = text.count("\ufffd")
    control_count = sum(
        1
        for char in text
        if unicodedata.category(char) == "Cc" and char not in {"\n", "\t"}
    )
    line_counts = Counter(line.strip() for line in lines if len(line.strip()) >= 8)
    repeated_line_ratio = 0.0
    if lines:
        repeated_lines = sum(count for count in line_counts.values() if count > 1)
        repeated_line_ratio = repeated_lines / len(lines)

    warnings: list[str] = []
    if replacement_count:
        warnings.append("replacement_characters")
    if control_count:
        warnings.append("control_characters")
    if characters > 60_000:
        warnings.append("unusually_long_page_output")
    if repeated_line_ratio >= 0.6 and len(lines) >= 4:
        warnings.append("repeated_lines")
    if words < 3 and not _looks_like_non_text_note(text):
        warnings.append("very_short_output")

    return {
        "status": "warning" if warnings else "ok",
        "warnings": warnings,
        "character_count": characters,
        "word_count": words,
        "line_count": len(lines),
        "replacement_character_count": replacement_count,
        "control_character_count": control_count,
        "repeated_line_ratio": round(repeated_line_ratio, 4),
    }
