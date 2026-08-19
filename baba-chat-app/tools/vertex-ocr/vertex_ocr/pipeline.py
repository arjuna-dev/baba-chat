"""Resumable per-page OCR orchestration and page-free Markdown assembly."""

from __future__ import annotations

import concurrent.futures
import json
import os
import random
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import OCRResult, PageOutcome
from .prompt import OCR_PROMPT_VERSION, SKIP_PAGE_SENTINEL, build_ocr_prompt
from .quality import assess_markdown, is_skip_page_sentinel, normalize_markdown
from .storage import (
    atomic_write_json,
    atomic_write_text,
    read_json,
    safe_error_message,
    sha256_file,
    utc_now,
)
from .vertex import (
    DEFAULT_MEDIA_RESOLUTION,
    DEFAULT_MODEL,
    DEFAULT_THINKING_LEVEL,
    normalize_media_resolution,
    normalize_thinking_level,
)


PIPELINE_VERSION = "0.6.0"
STATE_VERSION = 3
RAW_CHECKPOINT_VERSION = 4
MANIFEST_VERSION = 3

_PAGE_MARKER_RE = re.compile(r"<!--\s*(?:pdf\s+)?page\s*:\s*\d+\s*-->", re.IGNORECASE)
_PAGE_HEADING_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+)?(?:pdf[ \t]+)?page(?:[ \t]*:[ \t]*|[ \t]+)"
    r"\d+[ \t]*#?[ \t]*(?:\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
_LEGACY_PROMPT_VERSIONS = frozenset({"2026-08-17-v6"})


def _content_identity_matches(actual: Any, expected: dict[str, Any]) -> bool:
    """Accept the prior prompt version because page-free assembly is backward compatible."""

    if actual == expected:
        return True
    if not isinstance(actual, dict):
        return False
    if actual.get("prompt_version") not in _LEGACY_PROMPT_VERSIONS:
        return False
    actual_without_prompt = {
        key: value for key, value in actual.items() if key != "prompt_version"
    }
    expected_without_prompt = {
        key: value for key, value in expected.items() if key != "prompt_version"
    }
    return actual_without_prompt == expected_without_prompt


class PageRenderer(Protocol):
    dpi: int

    def page_count(self, pdf_path: Path) -> int:
        ...

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        ...


class OCRClient(Protocol):
    def transcribe(self, image_path: Path, prompt: str) -> OCRResult:
        ...


class PipelineError(RuntimeError):
    """Raised when a run cannot safely continue or resume."""


@dataclass(frozen=True)
class PipelineConfig:
    model: str = DEFAULT_MODEL
    project: str | None = None
    location: str = "global"
    thinking_level: str = DEFAULT_THINKING_LEVEL
    media_resolution: str = DEFAULT_MEDIA_RESOLUTION
    render_dpi: int = 200
    workers: int = 1
    max_in_flight: int = 1
    max_retries: int = 3
    backoff_seconds: float = 1.0
    max_output_tokens: int = 8192
    previous_page_context_words: int = 200
    prompt_version: str = OCR_PROMPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "thinking_level", normalize_thinking_level(self.thinking_level))
        object.__setattr__(self, "media_resolution", normalize_media_resolution(self.media_resolution))
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        if self.max_in_flight < 1:
            raise ValueError("max_in_flight must be at least 1")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if self.max_output_tokens < 256:
            raise ValueError("max_output_tokens must be at least 256")
        if self.previous_page_context_words < 0:
            raise ValueError("previous_page_context_words cannot be negative")
        if self.previous_page_context_words > 0 and (
            self.workers != 1 or self.max_in_flight != 1
        ):
            raise ValueError(
                "previous_page_context_words > 0 requires workers=1 and max_in_flight=1; "
                "set previous_page_context_words to 0 to enable concurrent page processing"
            )

    def content_identity(self) -> dict[str, Any]:
        """Values that must not change while resuming a book."""

        return {
            "model": self.model,
            "project": self.project,
            "location": self.location,
            "thinking_level": self.thinking_level,
            "media_resolution": self.media_resolution,
            "render_dpi": self.render_dpi,
            "max_output_tokens": self.max_output_tokens,
            "previous_page_context_words": self.previous_page_context_words,
            "prompt_version": self.prompt_version,
        }


def slugify_book_title(title: str) -> str:
    """Create a stable ASCII filename stem from a PDF stem."""

    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-").lower()
    return normalized or "book"


def parse_page_range(spec: str | None, page_count: int) -> list[int]:
    """Parse one-based ranges such as ``1-3,8`` in sorted order."""

    if page_count < 1:
        raise ValueError("PDF has no pages")
    if spec is None or not spec.strip() or spec.strip().lower() in {"all", "*"}:
        return list(range(1, page_count + 1))

    pages: set[int] = set()
    for piece in spec.split(","):
        piece = piece.strip()
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", piece)
        if not match:
            raise ValueError(f"Invalid page range component: {piece!r}")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start > end:
            raise ValueError(f"Page range starts after it ends: {piece!r}")
        if start < 1 or end > page_count:
            raise ValueError(f"Page range {piece!r} is outside 1-{page_count}")
        pages.update(range(start, end + 1))
    return sorted(pages)


def collect_pdfs(input_path: Path) -> list[Path]:
    """Collect one PDF or all PDFs recursively from a directory."""

    resolved = input_path.expanduser().resolve()
    if resolved.is_file():
        if resolved.suffix.lower() != ".pdf":
            raise PipelineError(f"Input file is not a PDF: {resolved}")
        return [resolved]
    if not resolved.is_dir():
        raise PipelineError(f"Input path does not exist: {resolved}")
    pdfs = sorted(
        (path for path in resolved.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: str(path).casefold(),
    )
    if not pdfs:
        raise PipelineError(f"No PDF files found under {resolved}")
    return pdfs


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _last_words(text: str, word_count: int) -> str:
    """Return exactly the final ``word_count`` whitespace-delimited words."""

    if word_count <= 0:
        return ""
    return " ".join(text.split()[-word_count:])


def _frontmatter(
    *,
    title: str,
    source_name: str,
    source_sha256: str,
    complete: bool,
    config: PipelineConfig,
    generated_at: str,
) -> str:
    return "\n".join(
        [
            "---",
            f"title: {_yaml_string(title)}",
            f"source_pdf: {_yaml_string(source_name)}",
            f"source_sha256: {_yaml_string(source_sha256)}",
            f"complete: {'true' if complete else 'false'}",
            f"ocr_model: {_yaml_string(config.model)}",
            f"vertex_project: {_yaml_string(config.project) if config.project else 'null'}",
            f"vertex_location: {_yaml_string(config.location)}",
            f"ocr_thinking_level: {_yaml_string(config.thinking_level)}",
            f"ocr_media_resolution: {_yaml_string(config.media_resolution)}",
            f"render_dpi: {config.render_dpi}",
            f"ocr_prompt_version: {_yaml_string(config.prompt_version)}",
            f"generated_at: {_yaml_string(generated_at)}",
            "---",
            "",
        ]
    )


def _clean_assembled_page_text(text: str) -> str:
    """Remove page metadata before page text is exposed in the book Markdown."""

    text = _PAGE_MARKER_RE.sub("", text)
    text = _PAGE_HEADING_RE.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _build_markdown(
    *,
    title: str,
    source_name: str,
    source_sha256: str,
    page_count: int,
    state_pages: dict[str, Any],
    raw_dir: Path,
    config: PipelineConfig,
    generated_at: str,
) -> str:
    attempted_pages = sorted(int(page) for page in state_pages)
    completed_pages = sorted(
        int(page) for page, record in state_pages.items() if record.get("status") == "complete"
    )
    skipped_pages = sorted(
        int(page) for page, record in state_pages.items() if record.get("status") == "skipped"
    )
    failed_pages = sorted(
        int(page) for page, record in state_pages.items() if record.get("status") == "failed"
    )
    complete = len(completed_pages) + len(skipped_pages) == page_count and not failed_pages
    page_texts: list[str] = []

    for page_number in attempted_pages:
        record = state_pages[str(page_number)]
        if record.get("status") != "complete":
            continue
        raw_path = raw_dir / f"page-{page_number:04d}.json"
        try:
            raw = read_json(raw_path)
            text = raw.get("text", "")
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(text, str) or is_skip_page_sentinel(text):
            continue
        cleaned = _clean_assembled_page_text(text)
        if cleaned:
            page_texts.append(cleaned)

    frontmatter = _frontmatter(
        title=title,
        source_name=source_name,
        source_sha256=source_sha256,
        complete=complete,
        config=config,
        generated_at=generated_at,
    ).rstrip("\n")
    body = "\n\n".join(page_texts)
    if not body:
        return frontmatter + "\n"
    return f"{frontmatter}\n\n{body}\n"


def _numeric_usage_total(records: list[dict[str, Any]], key: str) -> int:
    total = 0
    for record in records:
        value = record.get("usage", {}).get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


class BookPipeline:
    """Run one book with atomic per-page checkpoints and deterministic assembly."""

    def __init__(
        self,
        *,
        config: PipelineConfig,
        renderer: PageRenderer,
        ocr_client: OCRClient | None,
        sleep_fn: Any = time.sleep,
        random_fn: Any = random.random,
    ) -> None:
        self.config = config
        self.renderer = renderer
        self.ocr_client = ocr_client
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn

    def _state_paths(self, output_dir: Path, slug: str) -> tuple[Path, Path, Path]:
        cache_root = output_dir / ".ocr" / slug
        return cache_root / "state.json", cache_root / "pages", cache_root

    def _new_state(
        self,
        *,
        pdf_path: Path,
        source_sha256: str,
        page_count: int,
        slug: str,
    ) -> dict[str, Any]:
        now = utc_now()
        return {
            "state_version": STATE_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "slug": slug,
            "source": {
                "name": pdf_path.name,
                "sha256": source_sha256,
                "page_count": page_count,
            },
            "content_identity": self.config.content_identity(),
            "previous_page_context_words": self.config.previous_page_context_words,
            "created_at": now,
            "updated_at": now,
            "pages": {},
        }

    def _validate_resume_state(
        self,
        *,
        state: dict[str, Any],
        source_sha256: str,
        page_count: int,
        slug: str,
    ) -> None:
        if state.get("state_version") != STATE_VERSION:
            raise PipelineError("OCR state version is not supported")
        source = state.get("source") or {}
        if source.get("sha256") != source_sha256:
            raise PipelineError("Source PDF changed since the previous run; use a new output directory")
        if int(source.get("page_count", -1)) != page_count:
            raise PipelineError("Source PDF page count changed since the previous run")
        if state.get("slug") != slug:
            raise PipelineError("OCR state belongs to a different book slug")
        if not _content_identity_matches(
            state.get("content_identity"), self.config.content_identity()
        ):
            raise PipelineError(
                "Content settings changed since the previous run; use a new output directory "
                "or keep model, project, location, thinking level, media resolution, DPI, "
                "output limit, and prompt version unchanged"
            )

    @staticmethod
    def _recover_cached_pages(
        state: dict[str, Any],
        raw_dir: Path,
        source_sha256: str,
        content_identity: dict[str, Any],
    ) -> None:
        """Recover a page checkpoint if the process died after writing raw JSON."""

        if not raw_dir.is_dir():
            return
        for raw_path in sorted(raw_dir.glob("page-*.json")):
            try:
                raw = read_json(raw_path)
                page_number = int(raw["page_number"])
                status = raw.get("status")
                if (
                    raw.get("source_pdf_sha256") != source_sha256
                    or not _content_identity_matches(raw.get("content_identity"), content_identity)
                ):
                    continue
                if status == "complete":
                    text = raw.get("text")
                    if not isinstance(text, str) or not text.strip() or is_skip_page_sentinel(text):
                        continue
                elif status == "skipped":
                    if raw.get("skip_sentinel") != SKIP_PAGE_SENTINEL:
                        continue
                else:
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                continue
            current = state.setdefault("pages", {}).get(str(page_number), {})
            if current.get("status") == "complete":
                continue
            state["pages"][str(page_number)] = {
                "status": status,
                "raw_file": str(raw_path),
                "quality": raw.get("quality", {}),
                "rendered_image_sha256": raw.get("rendered_image_sha256"),
                "rendered_image_bytes": raw.get("rendered_image_bytes"),
                "usage": raw.get("usage", {}),
                "response_id": raw.get("response_id"),
                "model_version": raw.get("model_version"),
                "retry_count": raw.get("retry_count", 0),
                "previous_page_context_words": raw.get("previous_page_context_words"),
                "previous_page_number": raw.get("previous_page_number"),
                "previous_page_context_word_count": raw.get(
                    "previous_page_context_word_count", 0
                ),
                "started_at": raw.get("started_at"),
                "completed_at": raw.get("completed_at"),
            }

    def _process_page(
        self,
        *,
        pdf_path: Path,
        page_number: int,
        page_count: int,
        temp_root: Path,
        previous_page_context: str | None = None,
        previous_page_number: int | None = None,
    ) -> PageOutcome:
        started_at = utc_now()
        last_error: str | None = None
        retry_count = 0
        image_sha256: str | None = None
        image_bytes: int | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                page_temp_dir = temp_root / f"page-{page_number:04d}-attempt-{attempt:02d}"
                image_path = self.renderer.render_page(pdf_path, page_number, page_temp_dir)
                image_bytes = image_path.stat().st_size
                image_sha256 = sha256_file(image_path)
                if self.ocr_client is None:
                    raise PipelineError("No Vertex OCR client is configured for a non-dry run")
                prompt = build_ocr_prompt(
                    pdf_path.stem,
                    page_number,
                    page_count,
                    previous_page_context=previous_page_context,
                    previous_page_number=previous_page_number,
                )
                response = self.ocr_client.transcribe(image_path, prompt)
                text = normalize_markdown(response.text)
                completed_at = utc_now()
                if is_skip_page_sentinel(text):
                    return PageOutcome(
                        page_number=page_number,
                        status="skipped",
                        text=None,
                        started_at=started_at,
                        completed_at=completed_at,
                        rendered_image_sha256=image_sha256,
                        rendered_image_bytes=image_bytes,
                        usage=response.usage,
                        response_id=response.response_id,
                        model_version=response.model_version,
                        retry_count=retry_count,
                    )
                return PageOutcome(
                    page_number=page_number,
                    status="complete",
                    text=text,
                    started_at=started_at,
                    completed_at=completed_at,
                    rendered_image_sha256=image_sha256,
                    rendered_image_bytes=image_bytes,
                    usage=response.usage,
                    response_id=response.response_id,
                    model_version=response.model_version,
                    retry_count=retry_count,
                )
            except Exception as exc:
                last_error = safe_error_message(exc)
                if attempt >= self.config.max_retries:
                    break
                retry_count += 1
                delay = min(self.config.backoff_seconds * (2**attempt), 30.0)
                if delay:
                    delay *= 0.8 + (0.4 * self.random_fn())
                    self.sleep_fn(delay)

        return PageOutcome(
            page_number=page_number,
            status="failed",
            text=None,
            started_at=started_at,
            completed_at=utc_now(),
            rendered_image_sha256=image_sha256,
            rendered_image_bytes=image_bytes,
            retry_count=retry_count,
            error=last_error or "Unknown OCR failure",
        )

    def _write_page_checkpoint(
        self,
        *,
        pages_dir: Path,
        state: dict[str, Any],
        source_sha256: str,
        outcome: PageOutcome,
        previous_page_number: int | None,
        previous_page_context_word_count: int,
    ) -> None:
        page_key = str(outcome.page_number)
        if outcome.status == "complete" and outcome.text is not None:
            quality = assess_markdown(outcome.text)
            raw = {
                "raw_version": RAW_CHECKPOINT_VERSION,
                "page_number": outcome.page_number,
                "status": outcome.status,
                "source_pdf_sha256": source_sha256,
                "content_identity": self.config.content_identity(),
                "text": outcome.text,
                "quality": quality,
                "rendered_image_sha256": outcome.rendered_image_sha256,
                "rendered_image_bytes": outcome.rendered_image_bytes,
                "usage": outcome.usage,
                "response_id": outcome.response_id,
                "model_version": outcome.model_version,
                "retry_count": outcome.retry_count,
                "previous_page_context_words": self.config.previous_page_context_words,
                "previous_page_number": previous_page_number,
                "previous_page_context_word_count": previous_page_context_word_count,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
            }
            raw_path = pages_dir / f"page-{outcome.page_number:04d}.json"
            atomic_write_json(raw_path, raw)
            state["pages"][page_key] = {
                "status": "complete",
                "raw_file": str(raw_path),
                "quality": quality,
                "rendered_image_sha256": outcome.rendered_image_sha256,
                "rendered_image_bytes": outcome.rendered_image_bytes,
                "usage": outcome.usage,
                "response_id": outcome.response_id,
                "model_version": outcome.model_version,
                "retry_count": outcome.retry_count,
                "previous_page_context_words": self.config.previous_page_context_words,
                "previous_page_number": previous_page_number,
                "previous_page_context_word_count": previous_page_context_word_count,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
            }
        elif outcome.status == "skipped":
            quality = {
                "status": "skipped",
                "warnings": [],
                "character_count": 0,
                "word_count": 0,
                "line_count": 0,
            }
            raw = {
                "raw_version": RAW_CHECKPOINT_VERSION,
                "page_number": outcome.page_number,
                "status": outcome.status,
                "source_pdf_sha256": source_sha256,
                "content_identity": self.config.content_identity(),
                "text": None,
                "skip_sentinel": SKIP_PAGE_SENTINEL,
                "quality": quality,
                "rendered_image_sha256": outcome.rendered_image_sha256,
                "rendered_image_bytes": outcome.rendered_image_bytes,
                "usage": outcome.usage,
                "response_id": outcome.response_id,
                "model_version": outcome.model_version,
                "retry_count": outcome.retry_count,
                "previous_page_context_words": self.config.previous_page_context_words,
                "previous_page_number": previous_page_number,
                "previous_page_context_word_count": previous_page_context_word_count,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
            }
            raw_path = pages_dir / f"page-{outcome.page_number:04d}.json"
            atomic_write_json(raw_path, raw)
            state["pages"][page_key] = {
                "status": "skipped",
                "raw_file": str(raw_path),
                "quality": quality,
                "rendered_image_sha256": outcome.rendered_image_sha256,
                "rendered_image_bytes": outcome.rendered_image_bytes,
                "usage": outcome.usage,
                "response_id": outcome.response_id,
                "model_version": outcome.model_version,
                "retry_count": outcome.retry_count,
                "previous_page_context_words": self.config.previous_page_context_words,
                "previous_page_number": previous_page_number,
                "previous_page_context_word_count": previous_page_context_word_count,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
            }
        else:
            state["pages"][page_key] = {
                "status": "failed",
                "error": outcome.error,
                "rendered_image_sha256": outcome.rendered_image_sha256,
                "rendered_image_bytes": outcome.rendered_image_bytes,
                "retry_count": outcome.retry_count,
                "previous_page_context_words": self.config.previous_page_context_words,
                "previous_page_number": previous_page_number,
                "previous_page_context_word_count": previous_page_context_word_count,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
            }

    def _manifest(
        self,
        *,
        pdf_path: Path,
        source_sha256: str,
        page_count: int,
        requested_pages: list[int],
        state: dict[str, Any],
        output_dir: Path,
        slug: str,
        started_at: str,
        resumed: bool,
    ) -> dict[str, Any]:
        page_records = [
            {"page_number": int(page), **record}
            for page, record in sorted(state.get("pages", {}).items(), key=lambda item: int(item[0]))
        ]
        complete = [record for record in page_records if record.get("status") == "complete"]
        skipped = [record for record in page_records if record.get("status") == "skipped"]
        failed = [record for record in page_records if record.get("status") == "failed"]
        warning_pages = [
            record["page_number"]
            for record in complete
            if record.get("quality", {}).get("warnings")
        ]
        run_complete = len(complete) + len(skipped) == page_count and not failed
        return {
            "manifest_version": MANIFEST_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "book": {
                "title": pdf_path.stem,
                "slug": slug,
                "source_pdf": pdf_path.name,
                "source_sha256": source_sha256,
                "source_page_count": page_count,
                "markdown_file": str(output_dir / f"{slug}.md"),
            },
            "run": {
                "started_at": started_at,
                "updated_at": utc_now(),
                "resumed": resumed,
                "content_identity": self.config.content_identity(),
                "model": self.config.model,
                "project": self.config.project,
                "location": self.config.location,
                "thinking_level": self.config.thinking_level,
                "media_resolution": self.config.media_resolution,
                "render_dpi": self.config.render_dpi,
                "previous_page_context_words": self.config.previous_page_context_words,
                "workers": self.config.workers,
                "max_in_flight": self.config.max_in_flight,
                "max_retries": self.config.max_retries,
                "prompt_version": self.config.prompt_version,
            },
            "requested_pages": requested_pages,
            "pages": page_records,
            "summary": {
                "requested_page_count": len(requested_pages),
                "attempted_page_count": len(page_records),
                "completed_page_count": len(complete),
                "skipped_page_count": len(skipped),
                "skipped_pages": sorted(record["page_number"] for record in skipped),
                "failed_page_count": len(failed),
                "complete": run_complete,
                "quality_warning_page_count": len(warning_pages),
                "quality_warning_pages": sorted(warning_pages),
                "total_rendered_image_bytes": sum(
                    int(record.get("rendered_image_bytes") or 0) for record in page_records
                ),
                "total_output_characters": sum(
                    int(record.get("quality", {}).get("character_count") or 0) for record in complete
                ),
                "usage": {
                    "prompt_token_count": _numeric_usage_total(page_records, "prompt_token_count"),
                    "candidates_token_count": _numeric_usage_total(
                        page_records, "candidates_token_count"
                    ),
                    "total_token_count": _numeric_usage_total(page_records, "total_token_count"),
                },
            },
        }

    def _write_artifacts(
        self,
        *,
        pdf_path: Path,
        source_sha256: str,
        page_count: int,
        requested_pages: list[int],
        state: dict[str, Any],
        output_dir: Path,
        slug: str,
        started_at: str,
        resumed: bool,
        state_path: Path,
        pages_dir: Path,
    ) -> dict[str, Any]:
        state["updated_at"] = utc_now()
        atomic_write_json(state_path, state)
        generated_at = state["updated_at"]
        markdown = _build_markdown(
            title=pdf_path.stem,
            source_name=pdf_path.name,
            source_sha256=source_sha256,
            page_count=page_count,
            state_pages=state["pages"],
            raw_dir=pages_dir,
            config=self.config,
            generated_at=generated_at,
        )
        markdown_path = output_dir / f"{slug}.md"
        manifest_path = output_dir / f"{slug}.manifest.json"
        atomic_write_text(markdown_path, markdown)
        manifest = self._manifest(
            pdf_path=pdf_path,
            source_sha256=source_sha256,
            page_count=page_count,
            requested_pages=requested_pages,
            state=state,
            output_dir=output_dir,
            slug=slug,
            started_at=started_at,
            resumed=resumed,
        )
        atomic_write_json(manifest_path, manifest)
        return manifest

    def _previous_page_context(
        self,
        *,
        state: dict[str, Any],
        pages_dir: Path,
        source_sha256: str,
        page_number: int,
    ) -> tuple[str | None, int | None]:
        """Load only the completed raw artifact for the immediately prior PDF page."""

        if self.config.previous_page_context_words <= 0 or page_number <= 1:
            return None, None

        previous_page_number = page_number - 1
        record = state.get("pages", {}).get(str(previous_page_number), {})
        if record.get("status") != "complete":
            return None, None

        raw_path = pages_dir / f"page-{previous_page_number:04d}.json"
        if not raw_path.is_file():
            return None, None
        try:
            raw = read_json(raw_path)
        except (OSError, ValueError, TypeError):
            return None, None
        if (
            raw.get("page_number") != previous_page_number
            or raw.get("source_pdf_sha256") != source_sha256
            or not _content_identity_matches(
                raw.get("content_identity"), self.config.content_identity()
            )
        ):
            return None, None
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            return None, None
        context = _last_words(text, self.config.previous_page_context_words)
        if not context:
            return None, None
        return context, previous_page_number

    def run_book(
        self,
        *,
        pdf_path: Path,
        output_dir: Path,
        page_selection: list[int] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Run selected pages for one PDF and return its manifest."""

        pdf_path = pdf_path.expanduser().resolve()
        output_dir = output_dir.expanduser().resolve()
        if not pdf_path.is_file():
            raise PipelineError(f"Input PDF does not exist: {pdf_path}")
        page_count = self.renderer.page_count(pdf_path)
        selected = page_selection or list(range(1, page_count + 1))
        if any(page < 1 or page > page_count for page in selected):
            raise PipelineError(f"Page selection is outside 1-{page_count}")
        selected = sorted(set(selected))
        source_sha256 = sha256_file(pdf_path)
        slug = slugify_book_title(pdf_path.stem)
        output_dir.mkdir(parents=True, exist_ok=True)
        state_path, pages_dir, cache_root = self._state_paths(output_dir, slug)
        markdown_path = output_dir / f"{slug}.md"
        manifest_path = output_dir / f"{slug}.manifest.json"

        has_existing_artifacts = any(
            path.exists() for path in (state_path, markdown_path, manifest_path, cache_root)
        )
        if has_existing_artifacts and not resume:
            raise PipelineError(
                f"Output already exists for {pdf_path.name}. Use --resume to continue safely: {output_dir}"
            )
        if has_existing_artifacts and resume and not state_path.exists():
            raise PipelineError(
                f"Existing OCR artifacts have no state file for {pdf_path.name}; "
                "use a new output directory instead of overwriting them"
            )

        if state_path.exists():
            try:
                state = read_json(state_path)
            except (OSError, ValueError) as exc:
                raise PipelineError(f"Could not read OCR state: {exc}") from exc
            self._validate_resume_state(
                state=state,
                source_sha256=source_sha256,
                page_count=page_count,
                slug=slug,
            )
            # The page content identity is unchanged, so existing OCR pages remain
            # resumable while the regenerated Markdown adopts the current format.
            state["pipeline_version"] = PIPELINE_VERSION
            state["content_identity"] = self.config.content_identity()
        else:
            state = self._new_state(
                pdf_path=pdf_path,
                source_sha256=source_sha256,
                page_count=page_count,
                slug=slug,
            )
        self._recover_cached_pages(
            state,
            pages_dir,
            source_sha256,
            self.config.content_identity(),
        )

        requested_set = set(selected)
        pending: list[int] = []
        for page_number in selected:
            current = state.setdefault("pages", {}).get(str(page_number), {})
            raw_path = pages_dir / f"page-{page_number:04d}.json"
            if current.get("status") in {"complete", "skipped"} and raw_path.is_file():
                continue
            pending.append(page_number)
            state["pages"][str(page_number)] = {
                **current,
                "status": "pending",
                "previous_page_context_words": self.config.previous_page_context_words,
            }

        started_at = utc_now()
        manifest = self._write_artifacts(
            pdf_path=pdf_path,
            source_sha256=source_sha256,
            page_count=page_count,
            requested_pages=selected,
            state=state,
            output_dir=output_dir,
            slug=slug,
            started_at=started_at,
            resumed=resume,
            state_path=state_path,
            pages_dir=pages_dir,
        )

        if pending and self.ocr_client is None:
            raise PipelineError("A Vertex OCR client is required when pages still need processing")

        if pending:
            with tempfile.TemporaryDirectory(prefix="baba-vertex-ocr-") as temp_name:
                temp_root = Path(temp_name)
                iterator = iter(pending)
                futures: dict[
                    concurrent.futures.Future[PageOutcome], tuple[int | None, int]
                ] = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.workers) as executor:
                    while futures or pending:
                        while len(futures) < min(self.config.max_in_flight, len(pending)):
                            try:
                                page_number = next(iterator)
                            except StopIteration:
                                pending = []
                                break
                            previous_page_context, previous_page_number = self._previous_page_context(
                                state=state,
                                pages_dir=pages_dir,
                                source_sha256=source_sha256,
                                page_number=page_number,
                            )
                            previous_page_context_word_count = (
                                len(previous_page_context.split())
                                if previous_page_context
                                else 0
                            )
                            future = executor.submit(
                                self._process_page,
                                pdf_path=pdf_path,
                                page_number=page_number,
                                page_count=page_count,
                                temp_root=temp_root,
                                previous_page_context=previous_page_context,
                                previous_page_number=previous_page_number,
                            )
                            futures[future] = (
                                previous_page_number,
                                previous_page_context_word_count,
                            )
                        if not futures:
                            break
                        done, _ = concurrent.futures.wait(
                            futures,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                        for future in done:
                            previous_page_number, previous_page_context_word_count = futures.pop(future)
                            outcome = future.result()
                            self._write_page_checkpoint(
                                pages_dir=pages_dir,
                                state=state,
                                source_sha256=source_sha256,
                                outcome=outcome,
                                previous_page_number=previous_page_number,
                                previous_page_context_word_count=previous_page_context_word_count,
                            )
                            manifest = self._write_artifacts(
                                pdf_path=pdf_path,
                                source_sha256=source_sha256,
                                page_count=page_count,
                                requested_pages=selected,
                                state=state,
                                output_dir=output_dir,
                                slug=slug,
                                started_at=started_at,
                                resumed=resume,
                                state_path=state_path,
                                pages_dir=pages_dir,
                            )

        # Rebuild once more so the returned manifest reflects all state even when no page was pending.
        manifest = self._write_artifacts(
            pdf_path=pdf_path,
            source_sha256=source_sha256,
            page_count=page_count,
            requested_pages=selected,
            state=state,
            output_dir=output_dir,
            slug=slug,
            started_at=started_at,
            resumed=resume,
            state_path=state_path,
            pages_dir=pages_dir,
        )
        # requested_set is intentionally computed above to make the selected-page boundary explicit.
        del requested_set
        return manifest
