# Baba Chat OCR pipeline

This worker converts scanned Baba story PDFs into per-book Markdown using local page rendering and Gemini through Google Cloud Vertex AI. For scanned comparative books where a local transcription is sufficient, `tools/corpus-ingest/convert_sources.py pdf-ocr` provides a parallel Tesseract fallback. Both paths are deliberately isolated from the Electron app and from `tools/baba-search` so extraction work can be reviewed before indexing.

## Authentication and billing

The worker uses Application Default Credentials through the `google-genai` SDK in Vertex mode. It does not accept, read, or print Gemini API keys. The Google Cloud project and location are supplied explicitly or through `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`.

The default model is `gemini-3.7-flash`. The default thinking level is `LOW`, and the default input media resolution is `ULTRA_HIGH`. The worker also provides the final 200 whitespace-delimited words from the immediately preceding completed page as continuity context. This context is supplied as untrusted text and the current page image remains authoritative. These settings can be overridden for a run with `--model`, `--thinking-level`, `--media-resolution`, and `--previous-page-context-words`, or with `GOOGLE_GENAI_MODEL`, `GOOGLE_GENAI_THINKING_LEVEL`, `GOOGLE_GENAI_MEDIA_RESOLUTION`, and `GOOGLE_GENAI_PREVIOUS_PAGE_CONTEXT_WORDS`.

The current `google-genai` API places thinking settings in `GenerateContentConfig.thinking_config`, using `ThinkingConfig.thinking_level`. It places input media resolution on the inline image part created by `Part.from_bytes(..., media_resolution=...)`. `ULTRA_HIGH` is a `PartMediaResolutionLevel` value, so the worker does not pass it through the SDK's top-level `MediaResolution` enum.

Install the isolated dependencies in a virtual environment outside the app runtime:

```bash
python3 -m venv /tmp/baba-vertex-ocr-venv
/tmp/baba-vertex-ocr-venv/bin/python -m pip install -r tools/vertex-ocr/requirements.txt
```

Poppler is also required for local rendering. The CLI uses `pdfinfo` and `pdftoppm` and does not modify the source PDFs.

The local fallback requires Poppler and Tesseract. It keeps hidden `<!-- page: N -->`
markers in the generated Markdown so the deterministic search parser can preserve
page order while keeping page numbers out of normal answer citations:

```bash
BABA_PYTHON=/path/to/bundled/python
"$BABA_PYTHON" tools/corpus-ingest/convert_sources.py pdf-ocr \
  --input /path/to/scanned-book.pdf \
  --output corpus/other-spiritual-books \
  --workers 6
```

The local fallback is intended for searchable coverage and does not apply the
editorial cleanup and continuity handling of the Gemini OCR prompt.

## CLI

The executable wrapper is `tools/vertex-ocr/ocr.py`.

Inspect a small plan without writing artifacts or contacting Vertex:

```bash
python3 tools/vertex-ocr/ocr.py \
  --input "/Users/alejandrocamus/Documents/dev/BABA-chat/Baba-Story-Books/101 Baba Stories.pdf" \
  --output corpus/stories/pilot \
  --page-range 1-2 \
  --project project-b6f20ad5-4225-410b-8aa \
  --location global \
  --dry-run
```

Run a small pilot with ten pages:

```bash
/tmp/baba-vertex-ocr-venv/bin/python tools/vertex-ocr/ocr.py \
  --input "/Users/alejandrocamus/Documents/dev/BABA-chat/Baba-Story-Books/101 Baba Stories.pdf" \
  --output corpus/stories/pilot \
  --page-range 1-10 \
  --project project-b6f20ad5-4225-410b-8aa \
  --location global \
  --model gemini-3.7-flash \
  --thinking-level LOW \
  --media-resolution ULTRA_HIGH \
  --previous-page-context-words 200 \
  --workers 1 \
  --max-in-flight 1
```

The CLI supports a single PDF or a directory of PDFs. Useful controls are:

- `--page-range 1-2,8` for one-based inclusive page selection.
- `--resume` to reuse matching state and raw page outputs after an interruption.
- `--workers N` for concurrent page workers.
- `--max-in-flight N` to cap submitted pages independently of the worker count.
- `--book-workers N` to cap concurrent books. This is independent of page workers.
- `--adaptive-book-workers` to start at two books and add two book workers after every two healthy completed books, up to `--book-workers`.
- `--render-dpi N` to control local PNG rendering quality.
- `--thinking-level LOW|MEDIUM|HIGH` to control Gemini 3 thinking.
- `--media-resolution LOW|MEDIUM|HIGH|ULTRA_HIGH` to control image tokenization quality.
- `--previous-page-context-words N` to include the final N words from the immediately preceding completed page. The default is 200. Set it to `0` to enable concurrent page processing.
- `--max-retries N` and `--backoff-seconds N` for transient render or Vertex failures.
- `--dry-run` to inspect the page plan without writing or calling Vertex.

When previous-page context is enabled, the worker rejects `--workers` or `--max-in-flight` values greater than `1`. The next page needs the completed text from the immediately preceding page, so serial execution is required for correctness. Context is omitted for page 1, for a failed, skipped, or unavailable preceding page, and for a noncontiguous selection such as `1,3` when page 2 is not available.

Book-level concurrency remains safe with previous-page context because each book keeps its own pages serial while independent books run in parallel. For a full run, use a conservative cap and let the adaptive scheduler ramp only after healthy completed-book manifests, for example `--book-workers 8 --adaptive-book-workers`. A book is healthy for ramping only when it has no failed pages and no page retries. Any unhealthy result pauses the ramp while the remaining work continues at the current target.

The first run refuses to overwrite an existing book artifact. Resume is allowed only when the source PDF hash, page count, model, project, location, thinking level, media resolution, render DPI, output limit, previous-page context word count, and prompt version still match. Existing v6 raw checkpoints are also accepted by the v7 page-free assembler because the output-format change is backward compatible.

## Output layout

For an output directory such as `corpus/stories/pilot`, each book produces:

```text
corpus/stories/pilot/
  101-baba-stories.md
  101-baba-stories.manifest.json
  run-manifest.json
  .ocr/
    101-baba-stories/
      state.json
      pages/
        page-0001.json
        page-0002.json
```

The public Markdown file contains clean YAML frontmatter and one readable book body. Its frontmatter keeps book-level provenance and OCR settings, but contains no page lists, page counts, page markers, or other page-number metadata. Completed page text is joined in source order with safe blank-line spacing. Skipped and failed pages are omitted from the public body; their status and page numbers remain available in the manifest and internal state.

The source PDF page order is preserved internally while the book is assembled. For a facing-page scan, the prompt asks Gemini to place the left page before the right page. The v7 prompt asks for a clean editorial Markdown edition: it corrects spelling, grammar, punctuation, spacing, capitalization, scanning artifacts, and obvious typos; reconstructs cropped, obscured, or missing fragments when the intended wording is strongly supported by context; and uses only a minimal `[Missing text]` marker for substantial content that cannot be recovered. It removes standalone page numbers, repeated book titles and chapter titles in headers or footers, repetitive page furniture, and scanner marks. Meaningful titles, headings, quotations, paragraphs, lists, captions, labels, tables, and footnotes are preserved. Ordinary prose line wraps are reflowed and words split only by a printed line break are joined. When available, the final 200 words from the immediately preceding completed page are included only as untrusted continuity context, must not be repeated, and cannot override the current image. If a page contains only blank space, page furniture, scanner marks, or a standalone page number, the model returns exactly `[[SKIP_PAGE]]`; pages with substantive text, captions, labels, footnotes, or meaningful illustrations are never skipped. The model returns only clean Markdown and does not emit page numbers, page headings, HTML comments, or provenance markers. The pipeline keeps page metadata only in its internal checkpoints and manifest. A page with a meaningful illustration receives a short factual description only when useful, otherwise the non-text placeholder is emitted.

## Resumability and validation

Each successful or skipped page has an atomic JSON checkpoint containing its status, rendered image hash and byte size, content identity, previous-page context settings and usage metadata, timestamps, and a response identifier when Vertex supplies one. A skipped checkpoint records the exact sentinel and is reused on `--resume` without another request. The state file is also written atomically after every page completion. The state content identity includes the model, project, location, thinking level, media resolution, render DPI, output limit, previous-page context word count, and prompt version. If a process dies after writing a raw page but before updating state, the next `--resume` run can recover that raw page only when both the source hash and content identity match. A resumed page uses the already completed raw artifact for page N-1 when it is present and valid, but skipped pages never provide continuity context. A full run is complete when every source page is either `complete` or `skipped` and no page is `failed`; a partial page selection remains incomplete until the source page count is covered.

Quality checks are intentionally heuristic and transparent. They flag replacement characters, control characters, unusually long output, repeated lines, and suspiciously short output. A warning does not discard a page. The per-book manifest reports page status, quality warnings, rendered image bytes, output characters, and token usage when the API returns it. It does not attempt to estimate cost because Vertex pricing depends on the selected model and current billing terms.

Tests use a fake renderer and fake OCR client for orchestration. The SDK-specific test constructs the configured `GenerateContentConfig` and inline image `Part` when `google-genai` is installed. Tests do not call Vertex or require credentials, and cover range parsing, Markdown normalization, quality warnings, ordered page-free assembly, complete and skipped raw cache creation, exact skip sentinel detection, skipped-page recovery and resume behavior, internal manifest and frontmatter checks, clean prompt safeguards, previous-page context inclusion and omission, exact tail truncation, resume context reuse, source-change protection, concurrency validation, and SDK enum mapping.

Run them from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/vertex-ocr/tests -v
```
