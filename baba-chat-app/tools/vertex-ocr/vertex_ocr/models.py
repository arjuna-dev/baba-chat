"""Small data objects shared by the OCR pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OCRResult:
    """Text and safe metadata returned by a page transcription request."""

    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    model_version: str | None = None


@dataclass(frozen=True)
class PageOutcome:
    """Result of rendering and transcribing one PDF page."""

    page_number: int
    status: str
    text: str | None
    started_at: str
    completed_at: str
    rendered_image_sha256: str | None = None
    rendered_image_bytes: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    model_version: str | None = None
    retry_count: int = 0
    error: str | None = None

