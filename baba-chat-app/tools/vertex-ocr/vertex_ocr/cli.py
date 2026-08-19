"""Command line interface for the resumable Vertex OCR worker."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import sys
from pathlib import Path
from typing import Any

from .pipeline import (
    BookPipeline,
    PipelineConfig,
    PipelineError,
    PIPELINE_VERSION,
    MANIFEST_VERSION,
    collect_pdfs,
    parse_page_range,
    slugify_book_title,
)
from .render import PdfRenderer
from .storage import atomic_write_json, sha256_file, utc_now
from .vertex import (
    DEFAULT_MEDIA_RESOLUTION,
    DEFAULT_MODEL,
    DEFAULT_THINKING_LEVEL,
    VertexGeminiOCR,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _manifest_is_healthy(manifest: dict[str, Any]) -> bool:
    """Return whether a completed book is safe to use for adaptive ramping."""

    summary = manifest.get("summary", {})
    if not isinstance(summary, dict):
        return False
    try:
        if int(summary.get("failed_page_count", 0) or 0) > 0:
            return False
    except (TypeError, ValueError):
        return False

    pages = manifest.get("pages", [])
    if not isinstance(pages, list):
        return False
    for page in pages:
        if not isinstance(page, dict):
            return False
        try:
            if int(page.get("retry_count", 0) or 0) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _run_book(
    *,
    pdf_path: Path,
    renderer: PdfRenderer,
    vertex_client: VertexGeminiOCR,
    config: PipelineConfig,
    page_range: str | None,
    output_dir: Path,
    resume: bool,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Run one book and return either its manifest or a deterministic failure record."""

    try:
        page_count = renderer.page_count(pdf_path)
        selected = parse_page_range(page_range, page_count)
        pipeline = BookPipeline(
            config=config,
            renderer=renderer,
            ocr_client=vertex_client,
        )
        manifest = pipeline.run_book(
            pdf_path=pdf_path,
            output_dir=output_dir,
            page_selection=selected,
            resume=resume,
        )
        return manifest, None
    except (PipelineError, OSError, ValueError) as exc:
        return None, {"source_pdf": pdf_path.name, "error": str(exc)}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without initializing Google credentials."""

    repo_root = Path(__file__).resolve().parents[3]
    default_output = repo_root / "corpus" / "stories"
    parser = argparse.ArgumentParser(
        description="Render PDF pages locally and OCR them into resumable Markdown via Vertex Gemini.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="A PDF file or a directory containing PDF files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Artifact directory (default: {default_output}).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GOOGLE_GENAI_MODEL", DEFAULT_MODEL),
        help="Vertex Gemini model name.",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="Google Cloud project ID. Defaults to GOOGLE_CLOUD_PROJECT.",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        help="Vertex location (default: global or GOOGLE_CLOUD_LOCATION).",
    )
    parser.add_argument(
        "--thinking-level",
        default=os.environ.get("GOOGLE_GENAI_THINKING_LEVEL", DEFAULT_THINKING_LEVEL),
        help="Gemini thinking level: LOW, MEDIUM, or HIGH (default: LOW).",
    )
    parser.add_argument(
        "--media-resolution",
        default=os.environ.get("GOOGLE_GENAI_MEDIA_RESOLUTION", DEFAULT_MEDIA_RESOLUTION),
        help="Input image resolution: LOW, MEDIUM, HIGH, or ULTRA_HIGH (default: ULTRA_HIGH).",
    )
    parser.add_argument(
        "--previous-page-context-words",
        type=_nonnegative_int,
        default=os.environ.get("GOOGLE_GENAI_PREVIOUS_PAGE_CONTEXT_WORDS", "200"),
        help=(
            "Number of final words from the immediately previous completed page to provide "
            "as continuity context (default: 200; set to 0 to enable concurrency)."
        ),
    )
    parser.add_argument(
        "--page-range",
        default=None,
        help="One-based page range, for example 1-2,5. Defaults to all pages.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse matching state and per-page raw outputs, retrying incomplete pages.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect inputs and print the planned requests without writing or calling Vertex.",
    )
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help="Maximum concurrent page workers (default: 1).",
    )
    parser.add_argument(
        "--max-in-flight",
        type=_positive_int,
        default=None,
        help="Maximum submitted page requests at once (default: workers).",
    )
    parser.add_argument(
        "--book-workers",
        type=_positive_int,
        default=1,
        help="Maximum concurrent books (default: 1).",
    )
    parser.add_argument(
        "--adaptive-book-workers",
        action="store_true",
        help=(
            "Start with 2 books, add 2 book workers after every two healthy completed books, "
            "and never exceed --book-workers."
        ),
    )
    parser.add_argument(
        "--render-dpi",
        type=_positive_int,
        default=200,
        help="Local Poppler render DPI (default: 200).",
    )
    parser.add_argument(
        "--max-retries",
        type=_nonnegative_int,
        default=3,
        help="Retries after a render or Vertex error (default: 3).",
    )
    parser.add_argument(
        "--backoff-seconds",
        type=_nonnegative_float,
        default=1.0,
        help="Initial exponential retry backoff in seconds (default: 1).",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=_positive_int,
        default=8192,
        help="Maximum output tokens per page request (default: 8192).",
    )
    return parser


def _dry_run_plan(
    *,
    pdfs: list[Path],
    renderer: PdfRenderer,
    page_range: str | None,
    output_dir: Path,
    config: PipelineConfig,
    book_workers: int,
    adaptive_book_workers: bool,
) -> dict[str, Any]:
    books: list[dict[str, Any]] = []
    for pdf_path in pdfs:
        page_count = renderer.page_count(pdf_path)
        selected = parse_page_range(page_range, page_count)
        books.append(
            {
                "source_pdf": pdf_path.name,
                "source_bytes": pdf_path.stat().st_size,
                "source_sha256": sha256_file(pdf_path),
                "source_page_count": page_count,
                "selected_pages": selected,
                "slug": slugify_book_title(pdf_path.stem),
            }
        )
    return {
        "dry_run": True,
        "output_dir": str(output_dir.resolve()),
        "model": config.model,
        "project": config.project,
        "location": config.location,
        "thinking_level": config.thinking_level,
        "media_resolution": config.media_resolution,
        "previous_page_context_words": config.previous_page_context_words,
        "render_dpi": config.render_dpi,
        "workers": config.workers,
        "max_in_flight": config.max_in_flight,
        "book_workers": book_workers,
        "adaptive_book_workers": adaptive_book_workers,
        "books": books,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    max_in_flight = args.max_in_flight or args.workers
    try:
        config = PipelineConfig(
            model=args.model,
            project=args.project,
            location=args.location,
            thinking_level=args.thinking_level,
            media_resolution=args.media_resolution,
            previous_page_context_words=args.previous_page_context_words,
            render_dpi=args.render_dpi,
            workers=args.workers,
            max_in_flight=max_in_flight,
            max_retries=args.max_retries,
            backoff_seconds=args.backoff_seconds,
            max_output_tokens=args.max_output_tokens,
        )
        pdfs = collect_pdfs(args.input)
        renderer = PdfRenderer(dpi=args.render_dpi)
        if args.dry_run:
            print(
                json.dumps(
                    _dry_run_plan(
                        pdfs=pdfs,
                        renderer=renderer,
                        page_range=args.page_range,
                        output_dir=args.output,
                        config=config,
                        book_workers=args.book_workers,
                        adaptive_book_workers=args.adaptive_book_workers,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not config.project:
            parser.error("--project or GOOGLE_CLOUD_PROJECT is required unless --dry-run is used")

        vertex_client = VertexGeminiOCR(
            project=config.project,
            location=config.location,
            thinking_level=config.thinking_level,
            media_resolution=config.media_resolution,
            model=config.model,
            max_output_tokens=config.max_output_tokens,
        )
        summaries: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        run_started_at = utc_now()
        try:
            book_workers = args.book_workers
            target_workers = min(2, book_workers) if args.adaptive_book_workers else book_workers
            healthy_since_ramp = 0
            pending = deque(enumerate(pdfs))
            active: dict[Any, int] = {}
            results: dict[int, tuple[dict[str, Any] | None, dict[str, str] | None]] = {}
            completed_count = 0

            print(
                f"OCR scheduler: {len(pdfs)} book(s), target {target_workers}, "
                f"maximum {book_workers}; pages remain serial within each book.",
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=book_workers) as executor:
                while pending or active:
                    while pending and len(active) < target_workers:
                        index, pdf_path = pending.popleft()
                        future = executor.submit(
                            _run_book,
                            pdf_path=pdf_path,
                            renderer=renderer,
                            vertex_client=vertex_client,
                            config=config,
                            page_range=args.page_range,
                            output_dir=args.output,
                            resume=args.resume,
                        )
                        active[future] = index
                        print(
                            f"OCR started {pdf_path.name} ({index + 1}/{len(pdfs)}; "
                            f"active {len(active)}/{target_workers})",
                            flush=True,
                        )

                    completed, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in sorted(completed, key=lambda item: active[item]):
                        index = active.pop(future)
                        pdf_path = pdfs[index]
                        try:
                            manifest, failure = future.result()
                        except Exception as exc:  # pragma: no cover - defensive worker boundary
                            manifest = None
                            failure = {
                                "source_pdf": pdf_path.name,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        results[index] = (manifest, failure)
                        completed_count += 1
                        healthy = manifest is not None and _manifest_is_healthy(manifest)
                        if args.adaptive_book_workers:
                            if healthy:
                                healthy_since_ramp += 1
                                if healthy_since_ramp >= 2 and target_workers < book_workers:
                                    target_workers = min(target_workers + 2, book_workers)
                                    healthy_since_ramp = 0
                                    print(
                                        f"OCR scheduler: ramped book target to {target_workers} "
                                        f"after two healthy books.",
                                        flush=True,
                                    )
                            else:
                                healthy_since_ramp = 0

                        health_label = "healthy" if healthy else "unhealthy"
                        print(
                            f"OCR completed {pdf_path.name} ({completed_count}/{len(pdfs)}; "
                            f"{health_label}; active {len(active)}/{target_workers})",
                            flush=True,
                        )
                        if failure is not None:
                            print(
                                f"OCR failed for {pdf_path.name}: {failure['error']}",
                                file=sys.stderr,
                                flush=True,
                            )

            for index, pdf_path in enumerate(pdfs):
                manifest, failure = results[index]
                if manifest is not None:
                    summaries.append(
                        {
                            "source_pdf": pdf_path.name,
                            "manifest": str(
                                args.output.resolve()
                                / f"{slugify_book_title(pdf_path.stem)}.manifest.json"
                            ),
                            "summary": manifest["summary"],
                        }
                    )
                elif failure is not None:
                    failures.append(failure)
        finally:
            vertex_client.close()

        run_manifest = {
            "manifest_version": MANIFEST_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "run_started_at": run_started_at,
            "run_updated_at": utc_now(),
            "input": str(args.input.expanduser().resolve()),
            "output_dir": str(args.output.expanduser().resolve()),
            "resume": args.resume,
            "dry_run": False,
            "content_identity": config.content_identity(),
            "model": config.model,
            "project": config.project,
            "location": config.location,
            "thinking_level": config.thinking_level,
            "media_resolution": config.media_resolution,
            "previous_page_context_words": config.previous_page_context_words,
            "page_range": args.page_range,
            "book_workers": args.book_workers,
            "adaptive_book_workers": args.adaptive_book_workers,
            "books": summaries,
            "failures": failures,
        }
        args.output.mkdir(parents=True, exist_ok=True)
        atomic_write_json(args.output / "run-manifest.json", run_manifest)
        print(json.dumps(run_manifest, ensure_ascii=False, indent=2))
        return 1 if failures else 0
    except (PipelineError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2
