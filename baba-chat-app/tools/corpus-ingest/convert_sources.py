#!/usr/bin/env python3
"""Convert EPUB, text-based PDF, and DOCX sources into searchable Markdown.

This converter is deliberately local. EPUB and DOCX extraction do not call an
LLM. Text PDFs use pypdf, while scanned PDFs can use the existing Vertex OCR
pipeline or the local Tesseract fallback instead of being silently written as
empty Markdown.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import unquote
from zipfile import ZipFile

from docx import Document
from lxml import etree, html as lxml_html
from pypdf import PdfReader


WHITESPACE_RE = re.compile(r"\s+")
PAREN_SOURCE_RE = re.compile(r"\s*\([^)]*(?:z-library|1lib|z-lib)[^)]*\)\s*$", re.IGNORECASE)
TRAILING_EXT_RE = re.compile(r"\.(?:epub|pdf|docx)$", re.IGNORECASE)
BLOCK_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "table",
}
CONTAINER_TAGS = {
    "body",
    "div",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "aside",
}
SKIP_TAGS = {"script", "style", "nav", "svg", "img", "audio", "video"}


class ConversionError(RuntimeError):
    """A source could not be converted locally."""


class PdfNeedsOcr(ConversionError):
    """The PDF has no usable text layer and should go through Vertex OCR."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value.replace("\xa0", " ")).strip()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "source"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def frontmatter(fields: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {yaml_string(value)}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def readable_stem(path: Path) -> str:
    value = TRAILING_EXT_RE.sub("", path.name)
    value = PAREN_SOURCE_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or path.stem


def unique_output_path(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{slugify(stem)}.md"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{slugify(stem)}-{counter}.md"
        counter += 1
    return candidate


def _tag(element: object) -> str:
    tag = getattr(element, "tag", "")
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def render_inline(element: object) -> str:
    """Render an XHTML element's inline content without duplicating blocks."""

    node = element
    pieces: list[str] = [getattr(node, "text", "") or ""]
    for child in node:
        child_tag = _tag(child)
        if child_tag in SKIP_TAGS:
            continue
        if child_tag == "br":
            pieces.append("\n")
        else:
            child_text = render_inline(child)
            if child_tag in {"strong", "b"} and child_text.strip():
                child_text = f"**{child_text.strip()}**"
            elif child_tag in {"em", "i", "cite"} and child_text.strip():
                child_text = f"*{child_text.strip()}*"
            pieces.append(child_text)
        pieces.append(getattr(child, "tail", "") or "")
    return "".join(pieces)


def _render_table(table: object) -> str:
    rows: list[str] = []
    for row in table.xpath(".//*[local-name()='tr']"):
        cells: list[str] = []
        for cell in row.xpath("./*[local-name()='th' or local-name()='td']"):
            cell_text = clean_whitespace(render_inline(cell))
            if cell_text:
                cells.append(cell_text)
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _render_list(list_element: object) -> str:
    ordered = _tag(list_element) == "ol"
    rows: list[str] = []
    number = 1
    for item in list_element.xpath("./*[local-name()='li']"):
        item_text = clean_whitespace(render_inline(item))
        if item_text:
            marker = f"{number}." if ordered else "-"
            rows.append(f"{marker} {item_text}")
            number += 1
        for nested in item.xpath("./*[local-name()='ul' or local-name()='ol']"):
            nested_text = _render_list(nested)
            if nested_text:
                rows.extend(f"  {line}" for line in nested_text.splitlines())
    return "\n".join(rows)


def _render_block(element: object) -> str:
    tag = _tag(element)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        text = clean_whitespace(render_inline(element))
        return f"{'#' * int(tag[1])} {text}" if text else ""
    if tag in {"ul", "ol"}:
        return _render_list(element)
    if tag == "blockquote":
        text = clean_whitespace(render_inline(element))
        return f"> {text}" if text else ""
    if tag == "pre":
        text = (render_inline(element) or "").strip()
        return f"```\n{text}\n```" if text else ""
    if tag == "table":
        return _render_table(element)
    text = clean_whitespace(render_inline(element))
    return text


def html_blocks(root: object) -> list[str]:
    """Extract block-level Markdown without duplicating container text."""

    blocks: list[str] = []

    def visit(node: object) -> None:
        for child in node:
            tag = _tag(child)
            if tag in SKIP_TAGS:
                continue
            if tag in BLOCK_TAGS:
                rendered = _render_block(child)
                if rendered:
                    blocks.append(rendered)
                continue
            if tag in CONTAINER_TAGS:
                direct_children = list(child)
                if any(_tag(grandchild) in BLOCK_TAGS or _tag(grandchild) in CONTAINER_TAGS for grandchild in direct_children):
                    visit(child)
                else:
                    rendered = clean_whitespace(render_inline(child))
                    if rendered:
                        blocks.append(rendered)
                continue
            rendered = clean_whitespace(render_inline(child))
            if rendered:
                blocks.append(rendered)

    visit(root)
    deduplicated: list[str] = []
    for block in blocks:
        if not block.strip():
            continue
        if deduplicated and clean_whitespace(deduplicated[-1]) == clean_whitespace(block):
            continue
        deduplicated.append(block.strip())
    return deduplicated


def _epub_opf(zf: ZipFile) -> tuple[str, object, dict[str, dict[str, str]]]:
    container = etree.fromstring(zf.read("META-INF/container.xml"))
    rootfile = container.xpath("//*[local-name()='rootfile']")[0]
    opf_path = str(rootfile.get("full-path"))
    opf = etree.fromstring(zf.read(opf_path))
    manifest: dict[str, dict[str, str]] = {}
    for item in opf.xpath("//*[local-name()='manifest']/*[local-name()='item']"):
        manifest[str(item.get("id"))] = {
            "href": str(item.get("href", "")),
            "media_type": str(item.get("media-type", "")),
        }
    return opf_path, opf, manifest


def _epub_metadata(opf: object) -> tuple[str, str]:
    title = ""
    creator = ""
    for element in opf.xpath("//*[local-name()='title']"):
        if element.text and element.text.strip():
            title = clean_whitespace(element.text)
            break
    for element in opf.xpath("//*[local-name()='creator']"):
        if element.text and element.text.strip():
            creator = clean_whitespace(element.text)
            break
    return title, creator


def convert_epub(path: Path, output_dir: Path, title_override: str = "") -> Path:
    with ZipFile(path) as zf:
        opf_path, opf, manifest = _epub_opf(zf)
        metadata_title, creator = _epub_metadata(opf)
        title = title_override.strip() or metadata_title or readable_stem(path)
        spine_ids = [
            str(itemref.get("idref"))
            for itemref in opf.xpath("//*[local-name()='spine']/*[local-name()='itemref']")
        ]
        opf_dir = posixpath.dirname(opf_path)
        blocks: list[str] = []
        for item_id in spine_ids:
            item = manifest.get(item_id)
            if not item or "html" not in item["media_type"].lower() and "xhtml" not in item["media_type"].lower():
                continue
            member = posixpath.normpath(posixpath.join(opf_dir, unquote(item["href"])))
            try:
                root = lxml_html.fromstring(zf.read(member))
            except (KeyError, ValueError, etree.XMLSyntaxError):
                continue
            for node in root.xpath("//*[local-name()='script' or local-name()='style' or local-name()='nav' or local-name()='svg' or local-name()='img']"):
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
            item_blocks = html_blocks(root)
            if not item_blocks:
                continue
            item_title = ""
            title_nodes = root.xpath("//*[local-name()='title']")
            if title_nodes and title_nodes[0].text:
                item_title = clean_whitespace(title_nodes[0].text)
            if item_title and not re.fullmatch(r"(?:part|chapter|section)?[_ -]?\d+", item_title, re.IGNORECASE):
                first = clean_whitespace(item_blocks[0].lstrip("# "))
                if first.casefold() != item_title.casefold():
                    blocks.append(f"## {item_title}")
            blocks.extend(item_blocks)

    body = "\n\n".join(block for block in blocks if block.strip()).strip()
    if not body:
        raise ConversionError(f"EPUB contained no readable text: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_output_path(output_dir, title)
    metadata = {
        "title": title,
        "author": creator,
        "source_epub": path.name,
        "source_sha256": sha256_file(path),
        "conversion_method": "local-epub-xhtml",
    }
    output_path.write_text(frontmatter(metadata) + f"# {title}\n\n" + body + "\n", encoding="utf-8")
    return output_path


def _pdf_title(path: Path, reader: PdfReader) -> str:
    value = readable_stem(path)
    if value:
        return value
    metadata = reader.metadata
    return clean_whitespace(str(metadata.title)) if metadata and metadata.title else path.stem


def _pdf_page_text(text: str) -> str:
    lines = [clean_whitespace(line) for line in text.replace("\f", "\n").splitlines()]
    lines = [line for line in lines if line and not re.fullmatch(r"\d{1,4}", line)]
    if not lines:
        return ""
    return clean_whitespace(" ".join(lines))


def convert_text_pdf(path: Path, output_dir: Path, title_override: str = "") -> Path:
    reader = PdfReader(str(path))
    title = title_override.strip() or _pdf_title(path, reader)
    page_texts = [_pdf_page_text(page.extract_text() or "") for page in reader.pages]
    nonempty = [text for text in page_texts if text]
    if not nonempty:
        raise PdfNeedsOcr(f"PDF has no extractable text: {path}")
    body_parts: list[str] = []
    for page_number, text in enumerate(page_texts, start=1):
        if text:
            body_parts.append(f"<!-- page: {page_number} -->\n\n{text}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_output_path(output_dir, title)
    metadata = {
        "title": title,
        "source_pdf": path.name,
        "source_sha256": sha256_file(path),
        "conversion_method": "local-pypdf-text",
    }
    output_path.write_text(frontmatter(metadata) + f"# {title}\n\n" + "\n\n".join(body_parts) + "\n", encoding="utf-8")
    return output_path


def _local_ocr_page(
    pdf_path: Path,
    page_number: int,
    render_dpi: int,
    pdftoppm: str,
    tesseract: str,
    temp_root: Path,
) -> tuple[int, str]:
    page_dir = temp_root / f"page-{page_number:04d}"
    page_dir.mkdir(parents=True, exist_ok=True)
    image_base = page_dir / "page"
    subprocess.run(
        [
            pdftoppm,
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-png",
            "-r",
            str(render_dpi),
            "-singlefile",
            str(pdf_path),
            str(image_base),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result = subprocess.run(
        [tesseract, "page.png", "stdout", "-l", "eng", "--psm", "3"],
        check=True,
        cwd=page_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return page_number, result.stdout.strip()


def convert_scanned_pdf_locally(
    path: Path,
    output_dir: Path,
    title_override: str = "",
    workers: int = 4,
    render_dpi: int = 220,
) -> Path:
    """OCR a scanned PDF with local Poppler and Tesseract, without an LLM."""

    if workers < 1:
        raise ConversionError("workers must be at least 1")
    if render_dpi < 100:
        raise ConversionError("render-dpi must be at least 100")
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        raise ConversionError("local scanned-PDF OCR requires both pdftoppm and tesseract")

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    title = title_override.strip() or _pdf_title(path, reader)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_output_path(output_dir, title)

    with tempfile.TemporaryDirectory(prefix="baba-local-ocr-") as temp_name:
        temp_root = Path(temp_name)
        page_text: dict[int, str] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _local_ocr_page,
                    path,
                    page_number,
                    render_dpi,
                    pdftoppm,
                    tesseract,
                    temp_root,
                )
                for page_number in range(1, page_count + 1)
            ]
            for completed, future in enumerate(
                concurrent.futures.as_completed(futures), start=1
            ):
                page_number, text = future.result()
                page_text[page_number] = text
                print(
                    f"local OCR: {path.name}: {completed}/{page_count} pages",
                    file=sys.stderr,
                    flush=True,
                )

    body_parts = [
        f"<!-- page: {page_number} -->\n\n{page_text[page_number]}"
        for page_number in range(1, page_count + 1)
        if page_text.get(page_number)
    ]
    metadata = {
        "title": title,
        "source_pdf": path.name,
        "source_sha256": sha256_file(path),
        "conversion_method": "local-tesseract",
        "ocr_engine": "tesseract",
        "render_dpi": str(render_dpi),
        "source_page_count": str(page_count),
    }
    output_path.write_text(
        frontmatter(metadata) + f"# {title}\n\n" + "\n\n".join(body_parts) + "\n",
        encoding="utf-8",
    )
    return output_path


def _docx_runs(paragraph: object) -> str:
    pieces: list[str] = []
    for run in paragraph.runs:
        text = run.text or ""
        if not text:
            continue
        if run.bold:
            text = f"**{text}**"
        if run.italic:
            text = f"*{text}*"
        pieces.append(text)
    return clean_whitespace("".join(pieces) or paragraph.text)


def _looks_like_docx_heading(text: str, first: bool) -> bool:
    if first:
        return True
    if len(text) > 90 or len(text.split()) > 14:
        return False
    if text.endswith((".", ",", ";", ":")):
        return False
    return True


def convert_docx(path: Path, output_dir: Path, title: str) -> Path:
    document = Document(str(path))
    blocks: list[str] = []
    first = True
    for paragraph in document.paragraphs:
        text = _docx_runs(paragraph)
        if not text:
            continue
        style_name = paragraph.style.name.lower() if paragraph.style else ""
        if style_name.startswith("heading"):
            level_match = re.search(r"(\d+)", style_name)
            level = int(level_match.group(1)) if level_match else 2
            blocks.append(f"{'#' * min(level, 6)} {text}")
        elif _looks_like_docx_heading(text, first):
            blocks.append(f"# {text}" if first else f"## {text}")
        else:
            blocks.append(text)
        first = False
    if not blocks:
        raise ConversionError(f"DOCX contained no readable paragraphs: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_output_path(output_dir, title)
    metadata = {
        "title": title,
        "source_docx": path.name,
        "source_sha256": sha256_file(path),
        "conversion_method": "local-python-docx",
    }
    output_path.write_text(frontmatter(metadata) + "\n".join(blocks) + "\n", encoding="utf-8")
    return output_path


def iter_inputs(root: Path, suffix: str) -> Iterator[Path]:
    if root.is_file():
        if root.suffix.lower() == suffix:
            yield root
        return
    yield from sorted(
        (path for path in root.rglob(f"*{suffix}") if path.is_file()),
        key=lambda path: path.as_posix().casefold(),
    )


def command_epub(args: argparse.Namespace) -> int:
    paths = list(iter_inputs(args.input, ".epub"))
    if not paths:
        raise ConversionError(f"No EPUB files found under {args.input}")
    for path in paths:
        output = convert_epub(path, args.output)
        print(json.dumps({"source": str(path), "output": str(output)}, ensure_ascii=False))
    return 0


def command_pdf(args: argparse.Namespace) -> int:
    paths = list(iter_inputs(args.input, ".pdf"))
    if not paths:
        raise ConversionError(f"No PDF files found under {args.input}")
    ocr_needed: list[str] = []
    converted = 0
    for path in paths:
        try:
            output = convert_text_pdf(path, args.output)
        except PdfNeedsOcr:
            ocr_needed.append(str(path))
            continue
        print(json.dumps({"source": str(path), "output": str(output), "method": "pypdf"}, ensure_ascii=False))
        converted += 1
    if ocr_needed:
        print(json.dumps({"needs_ocr": ocr_needed}, ensure_ascii=False), file=sys.stderr)
    return 1 if ocr_needed else 0


def command_pdf_ocr(args: argparse.Namespace) -> int:
    output = convert_scanned_pdf_locally(
        args.input,
        args.output,
        args.title,
        workers=args.workers,
        render_dpi=args.render_dpi,
    )
    print(json.dumps({"source": str(args.input), "output": str(output)}, ensure_ascii=False))
    return 0


def command_docx(args: argparse.Namespace) -> int:
    output = convert_docx(args.input, args.output, args.title)
    print(json.dumps({"source": str(args.input), "output": str(output)}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    epub = subparsers.add_parser("epub", help="Convert EPUB XHTML to Markdown")
    epub.add_argument("--input", required=True, type=Path, help="EPUB file or directory")
    epub.add_argument("--output", required=True, type=Path, help="Markdown output directory")
    epub.set_defaults(handler=command_epub)

    pdf = subparsers.add_parser("pdf", help="Convert text-based PDFs to Markdown")
    pdf.add_argument("--input", required=True, type=Path, help="PDF file or directory")
    pdf.add_argument("--output", required=True, type=Path, help="Markdown output directory")
    pdf.set_defaults(handler=command_pdf)

    pdf_ocr = subparsers.add_parser(
        "pdf-ocr",
        aliases=["ocr-pdf"],
        help="Convert a scanned PDF to Markdown with local Tesseract OCR",
    )
    pdf_ocr.add_argument("--input", required=True, type=Path, help="Scanned PDF file")
    pdf_ocr.add_argument("--output", required=True, type=Path, help="Markdown output directory")
    pdf_ocr.add_argument("--title", default="", help="Optional title override")
    pdf_ocr.add_argument(
        "--workers", type=int, default=4, help="Concurrent local OCR workers (default: 4)"
    )
    pdf_ocr.add_argument(
        "--render-dpi", type=int, default=220, help="PDF render resolution (default: 220)"
    )
    pdf_ocr.set_defaults(handler=command_pdf_ocr)

    docx = subparsers.add_parser("docx", help="Convert DOCX paragraphs to Markdown")
    docx.add_argument("--input", required=True, type=Path, help="DOCX file")
    docx.add_argument("--output", required=True, type=Path, help="Markdown output directory")
    docx.add_argument("--title", required=True, help="Title written into Markdown front matter")
    docx.set_defaults(handler=command_docx)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.handler(args))
    except (ConversionError, OSError, ValueError, KeyError) as exc:
        print(f"conversion error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
