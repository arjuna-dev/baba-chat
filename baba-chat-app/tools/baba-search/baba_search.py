#!/usr/bin/env python3
"""Local lexical search for the Baba Chat source corpora.

The index stores extracted passages and provenance metadata in a local SQLite
database.  SQLite FTS5 is used when available to narrow the candidate set, but
all matching, scoring, phrase handling, and snippet generation are performed
in Python.  That keeps the result contract deterministic and gives the same
semantics to the FTS5 and scan fallbacks.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator, Sequence


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_PATH = APP_ROOT / "corpus" / "search" / "baba-search.sqlite3"
DEFAULT_DISCOURSE_CANDIDATES = (
    Path("/Users/alejandrocamus/Documents/dev/COMPLETE_SARKAR/HTML/Discourses"),
    APP_ROOT / "corpus" / "discourses",
)
DEFAULT_STORIES_PATH = APP_ROOT / "corpus" / "stories"
DEFAULT_OTHER_SPIRITUAL_BOOKS_PATH = APP_ROOT / "corpus" / "other-spiritual-books"
DEFAULT_ACHARYA_PHILOSOPHY_PATH = APP_ROOT / "corpus" / "acharya-philosophy"
DEFAULT_GLOSSARY_PATH = APP_ROOT / "corpus" / "search" / "glossary-candidates.json"
DEFAULT_CONNECTIONS_ROOT = APP_ROOT / "corpus" / "connections" / "full-corpus"
SCHEMA_VERSION = "4"
CORPUS_SOURCES = (
    "discourses",
    "stories",
    "other_spiritual_books",
    "acharya_philosophy",
)
DEFAULT_SEARCH_SOURCES = ("discourses", "stories")
SOURCE_CHOICES = (*CORPUS_SOURCES, "default", "all")
SOURCE_CITATION_PREFIXES = {
    "discourses": "Discourses",
    "stories": "Stories",
    "other_spiritual_books": "Other-Spiritual-Books",
    "acharya_philosophy": "Acharya-Philosophy",
}
SOURCE_META_PREFIXES = {
    "discourses": "discourse",
    "stories": "stories",
    "other_spiritual_books": "other_spiritual_books",
    "acharya_philosophy": "acharya_philosophy",
}
MIN_DISCOURSE_PARAGRAPH_LENGTH = 30
DEFAULT_LIMIT = 10
DEFAULT_CONTEXT = 220
MAX_LIMIT = 1000
DEFAULT_PER_QUERY_LIMIT = 10
DEFAULT_MAX_PER_DOCUMENT = 1
MAX_AGGREGATE_QUERIES = 32
DEFAULT_FUZZY_PER_TOKEN_LIMIT = 3
DEFAULT_FUZZY_MAX_DISTANCE: int | None = None
MAX_FUZZY_QUERY_VARIANTS = 8
MIN_FUZZY_TOKEN_LENGTH = 3
STORY_CHUNK_MAX_BLOCKS = 4
STORY_CHUNK_MAX_CHARACTERS = 2400
DEFAULT_CONNECTIONS_SOURCE = "all"

# Document-level term frequency is the primary relevance signal. The other
# weights remain useful for breaking ties between documents with similar
# corpus-wide frequency.
DOCUMENT_MATCH_WEIGHT = 1_000_000
DOCUMENT_PHRASE_WEIGHT = 100_000
LOCAL_PHRASE_WEIGHT = 10_000
TITLE_MATCH_WEIGHT = 1_000
BOOK_MATCH_WEIGHT = 500
TEXT_MATCH_WEIGHT = 100

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
RAW_TOKEN_RE = re.compile(
    r"[^\W_]+(?:[\u0300-\u036f]+[^\W_]+)*", re.UNICODE
)
WHITESPACE_RE = re.compile(r"\s+")
STORY_ATX_HEADING_RE = re.compile(
    r"^\s{0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$"
)
STORY_SETEXT_HEADING_RE = re.compile(r"^\s*(?:=+|-+)\s*$")
STORY_LIST_ITEM_RE = re.compile(
    r"^\s{0,3}(?P<marker>[-+*]|\d+[.)])\s+(?P<text>.+?)\s*$"
)
STORY_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?(?P<text>.*)$")
STORY_FENCE_RE = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")
STORY_PAGE_COMMENT_RE = re.compile(
    r"^\s*<!--\s*(?:page|p|baba-ocr-page)\s*"
    r"(?::|=|-|\s)\s*0*\d+\s*-->\s*$",
    re.IGNORECASE,
)
STORY_PAGE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\[\s*)?(?:pdf\s+)?page\s*"
    r"(?::|=|-|\s)+0*\d+\s*(?:\])?\s*$",
    re.IGNORECASE,
)


class BabaSearchError(RuntimeError):
    """A user-facing CLI error."""


@dataclass(frozen=True)
class Passage:
    source: str
    title: str
    book: str
    relative_path: str
    absolute_path: str
    anchor: str
    ordinal: int
    text: str
    page: int | None = None


@dataclass(frozen=True)
class StoryBlock:
    kind: str
    text: str


@dataclass(frozen=True)
class QueryPlan:
    terms: tuple[str, ...]
    phrases: tuple[tuple[str, ...], ...]


def normalize(text: str) -> str:
    """Return a lower-case, diacritic-insensitive search representation."""

    pieces: list[str] = []
    for char in text:
        decomposed = unicodedata.normalize("NFD", char)
        base = "".join(
            unit for unit in decomposed if not unicodedata.combining(unit)
        )
        pieces.append(base.casefold())
    return "".join(pieces)


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize text and map each normalized character to its source index."""

    normalized: list[str] = []
    source_indexes: list[int] = []
    for source_index, char in enumerate(text):
        decomposed = unicodedata.normalize("NFD", char)
        base = "".join(
            unit for unit in decomposed if not unicodedata.combining(unit)
        ).casefold()
        normalized.append(base)
        source_indexes.extend([source_index] * len(base))
    return "".join(normalized), source_indexes


def tokenize(text: str) -> list[str]:
    return [match.group(0) for match in TOKEN_RE.finditer(normalize(text))]


def normalize_glossary_term(text: str) -> str:
    """Normalize a glossary term for exact and token matching."""

    return normalize_whitespace(normalize(text))


def _glossary_field_values(
    candidate: dict[str, object], field: str
) -> list[str]:
    value = candidate.get(field)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _glossary_aliases(
    candidate: dict[str, object],
) -> list[tuple[str, str, str, tuple[str, ...]]]:
    """Return searchable aliases as kind, surface, normalized, and tokens."""

    aliases: list[tuple[str, str, str, tuple[str, ...]]] = []
    fields = (
        ("normalized", "normalized_form"),
        ("canonical", "canonical_surface_form"),
        ("variant", "variants"),
    )
    for kind, field in fields:
        for surface in _glossary_field_values(candidate, field):
            normalized = normalize_glossary_term(surface)
            tokens = tuple(tokenize(surface))
            if normalized and tokens:
                aliases.append((kind, surface, normalized, tokens))
    return aliases


def load_glossary(glossary_path: Path) -> list[dict[str, object]]:
    """Load the candidate array without opening or changing the SQLite index."""

    path = glossary_path.expanduser().resolve()
    if not path.is_file():
        raise BabaSearchError(f"Glossary file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise BabaSearchError(
            f"Glossary is not valid JSON: {path} ({exc.msg})"
        ) from exc
    except OSError as exc:
        raise BabaSearchError(f"Could not read glossary {path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise BabaSearchError(
            f"Glossary must contain a top-level candidates array: {path}"
        )
    candidates = payload["candidates"]
    if not all(isinstance(candidate, dict) for candidate in candidates):
        raise BabaSearchError(f"Glossary candidates must be JSON objects: {path}")
    return candidates  # type: ignore[return-value]


def _validate_glossary_limit(limit: int) -> None:
    if limit < 1 or limit > MAX_LIMIT:
        raise BabaSearchError(f"limit must be between 1 and {MAX_LIMIT}")


def _glossary_output(
    operation: str,
    glossary_path: Path,
    query_key: str,
    raw_query: str,
    limit: int,
    results: Sequence[dict[str, object]],
) -> dict[str, object]:
    return {
        "command": "glossary",
        "operation": operation,
        "glossary": str(glossary_path.expanduser().resolve()),
        query_key: raw_query,
        "normalized_query": normalize_glossary_term(raw_query),
        "limit": limit,
        "result_count": len(results),
        "results": list(results),
    }


def glossary_lookup(
    glossary_path: Path,
    term: str,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, object]:
    """Find candidates whose canonical or variant term exactly matches term."""

    _validate_glossary_limit(limit)
    normalized_term = normalize_glossary_term(term)
    if not normalized_term:
        raise BabaSearchError("term must contain at least one searchable term")

    candidates = load_glossary(glossary_path)
    matches: list[tuple[tuple[object, ...], dict[str, object]]] = []
    kind_rank = {"normalized": 0, "canonical": 1, "variant": 2}
    for index, candidate in enumerate(candidates):
        matching_ranks = [
            kind_rank[kind]
            for kind, _, alias, _ in _glossary_aliases(candidate)
            if alias == normalized_term
        ]
        if not matching_ranks:
            continue
        canonical = str(candidate.get("canonical_surface_form", ""))
        normalized = str(candidate.get("normalized_form", ""))
        sort_key = (
            min(matching_ranks),
            normalize_glossary_term(normalized),
            normalize_glossary_term(canonical),
            index,
        )
        matches.append((sort_key, candidate))

    matches.sort(key=lambda item: item[0])
    results = [candidate for _, candidate in matches[:limit]]
    return _glossary_output(
        "lookup", glossary_path, "term", term, limit, results
    )


def _strip_wrapping_quotes(text: str) -> str:
    value = normalize_whitespace(text)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _contains_token_sequence(
    haystack: Sequence[str], needle: Sequence[str]
) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(
        tuple(haystack[start : start + width]) == tuple(needle)
        for start in range(len(haystack) - width + 1)
    )


def _glossary_search_rank(
    candidate: dict[str, object], query: str
) -> tuple[object, ...] | None:
    normalized_query = normalize_glossary_term(_strip_wrapping_quotes(query))
    query_tokens = tuple(tokenize(query))
    if not normalized_query or not query_tokens:
        return None

    best: tuple[object, ...] | None = None
    kind_rank = {"normalized": 0, "canonical": 1, "variant": 2}
    for kind, _, alias, alias_tokens in _glossary_aliases(candidate):
        if alias == normalized_query:
            key = (kind_rank[kind], 0, normalize_glossary_term(alias))
        elif _contains_token_sequence(alias_tokens, query_tokens):
            key = (3, len(alias_tokens) - len(query_tokens), alias)
        elif all(token in alias_tokens for token in set(query_tokens)):
            key = (4, len(alias_tokens) - len(query_tokens), alias)
        else:
            continue
        if best is None or key < best:
            best = key
    return best


def glossary_search(
    glossary_path: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, object]:
    """Search candidate terms by exact aliases, phrases, and query tokens."""

    _validate_glossary_limit(limit)
    normalized_query = normalize_glossary_term(_strip_wrapping_quotes(query))
    if not normalized_query or not tokenize(query):
        raise BabaSearchError("query must contain at least one searchable term")

    candidates = load_glossary(glossary_path)
    matches: list[tuple[tuple[object, ...], dict[str, object]]] = []
    for index, candidate in enumerate(candidates):
        rank = _glossary_search_rank(candidate, query)
        if rank is None:
            continue
        canonical = str(candidate.get("canonical_surface_form", ""))
        normalized = str(candidate.get("normalized_form", ""))
        sort_key = (
            *rank,
            normalize_glossary_term(normalized),
            normalize_glossary_term(canonical),
            index,
        )
        matches.append((sort_key, candidate))

    matches.sort(key=lambda item: item[0])
    results = [candidate for _, candidate in matches[:limit]]
    return _glossary_output(
        "search", glossary_path, "query", query, limit, results
    )


def token_spans(normalized_text: str) -> list[tuple[str, int, int]]:
    return [
        (match.group(0), match.start(), match.end())
        for match in TOKEN_RE.finditer(normalized_text)
    ]


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def html_to_text(fragment: str) -> str:
    """Strip markup while retaining boundaries between block-like elements."""

    with_boundaries = re.sub(
        r"<\s*(?:br|p|/p|div|/div|li|/li|tr|/tr|td|/td|h[1-6]|/h[1-6])\b[^>]*>",
        " ",
        fragment,
        flags=re.IGNORECASE,
    )
    without_tags = re.sub(r"<[^>]+>", " ", with_boundaries)
    return normalize_whitespace(html.unescape(without_tags))


def humanize_filename(stem: str) -> str:
    return normalize_whitespace(re.sub(r"[_-]+", " ", stem)).strip() or stem


def extract_html_title(content: str) -> str:
    """Reuse the title fallback order from COMPLETE_SARKAR."""

    patterns = (
        r"<!--\s*block\s+a=title\s+type=title\s*-->(.*?)<!--\s*/block\s*-->",
        r"<div[^>]*class\s*=\s*[\"'][^\"']*\bdiscourse_title\b[^\"']*[\"'][^>]*>(.*?)</div>",
        r"<title[^>]*>(.*?)</title>",
        r"<(?:p|div|h1)[^>]*class\s*=\s*(?:[\"'][^\"']*\btitle\b[^\"']*[\"']|[^\s>]*\btitle\b[^\s>]*)[^>]*>(.*?)</(?:p|div|h1)>",
    )
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        title = html_to_text(match.group(1))
        title = re.sub(r"^EE7[.\d]*\s*[-\u2013]\s*", "", title).strip()
        if title:
            return title
    return ""


def extract_html_book(content: str) -> str:
    """Extract the first publication name from the discourse references."""

    publication_marker = re.compile(r"Published\s+in\s*:?")
    link_pattern = re.compile(
        r"<a\b[^>]*>(.*?)</a\s*>", flags=re.IGNORECASE | re.DOTALL
    )
    for marker in publication_marker.finditer(content):
        tail = content[marker.end() :]
        boundaries = [
            position
            for position in (
                tail.find("<!-- /References -->"),
                tail.lower().find("</div>"),
                tail.lower().find("</body>"),
            )
            if position >= 0
        ]
        section = tail[: min(boundaries)] if boundaries else tail
        link = link_pattern.search(section)
        if link:
            book = html_to_text(link.group(1))
            if book:
                return book

    # Safe fallback for a variant that has the references class but no
    # explicit closing References comment. It still requires the publication
    # label, so an unrelated "here" link cannot become a book name.
    references_pattern = re.compile(
        r"<div[^>]*class\s*=\s*[\"'][^\"']*discourse_references[^\"']*[\"'][^>]*>"
        r"(.*?)</div\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for references in references_pattern.finditer(content):
        section = references.group(1)
        if not publication_marker.search(section):
            continue
        link = link_pattern.search(section)
        if link:
            book = html_to_text(link.group(1))
            if book:
                return book
    return ""


def extract_html_paragraphs(content: str) -> list[tuple[str, str]]:
    """Extract paragraph blocks and their existing HTML anchors."""

    pattern = re.compile(
        r"<!--\s*block\s+a=([^\s]+)\s+type=paragraph\s*-->(.*?)"
        r"<!--\s*/block\s*-->",
        flags=re.IGNORECASE | re.DOTALL,
    )
    paragraphs: list[tuple[str, str]] = []
    for match in pattern.finditer(content):
        anchor = match.group(1).strip().strip('"\'')
        text = html_to_text(match.group(2))
        if len(text) >= MIN_DISCOURSE_PARAGRAPH_LENGTH:
            paragraphs.append((anchor, text))
    return paragraphs


def discourse_passages(path: Path, source_root: Path) -> tuple[str, str, list[Passage]]:
    content = path.read_text(encoding="utf-8", errors="replace")
    title = extract_html_title(content) or humanize_filename(path.stem)
    book = extract_html_book(content)
    try:
        relative_to_root = path.relative_to(source_root).as_posix()
    except ValueError:
        relative_to_root = path.name
    relative_path = f"Discourses/{relative_to_root}"
    paragraph_data = extract_html_paragraphs(content)
    passages = [
        Passage(
            source="discourses",
            title=title,
            book=book,
            relative_path=relative_path,
            absolute_path=str(path.resolve()),
            anchor=anchor,
            ordinal=ordinal,
            text=text,
        )
        for ordinal, (anchor, text) in enumerate(paragraph_data)
    ]
    return title, book, passages


def extract_front_matter_title(content: str) -> str:
    match = re.match(r"\s*---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        title_match = re.match(r"\s*title\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
        if title_match:
            return normalize_whitespace(title_match.group(1).strip("\"'"))
    return ""


def markdown_to_text(markdown: str) -> str:
    """Convert OCR Markdown to searchable, citation-friendly plain text."""

    text = re.sub(r"^\s*```[^\n]*\n", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"^\s*```\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_~]", "", text)
    return normalize_whitespace(html.unescape(text))


def is_story_page_metadata_line(line: str) -> bool:
    """Return whether a line is page furniture that should never be indexed."""

    return bool(
        STORY_PAGE_COMMENT_RE.match(line) or STORY_PAGE_HEADING_RE.match(line)
    )


def _story_heading(line: str) -> tuple[int, str] | None:
    match = STORY_ATX_HEADING_RE.match(line)
    if not match or is_story_page_metadata_line(line):
        return None
    heading_text = markdown_to_text(match.group(2))
    if not heading_text:
        return None
    return len(match.group(1)), heading_text


def _render_story_block(kind: str, lines: Sequence[str]) -> str:
    """Render one Markdown block while retaining useful structural cues."""

    if kind == "heading":
        heading = _story_heading(lines[0])
        if heading is None:
            return ""
        level, text = heading
        return f"{'#' * level} {text}"

    if kind == "list":
        rendered: list[str] = []
        for line in lines:
            match = STORY_LIST_ITEM_RE.match(line)
            if match:
                marker = match.group("marker")
                if marker in {"+", "*"}:
                    marker = "-"
                item_text = markdown_to_text(match.group("text"))
                if item_text:
                    rendered.append(f"{marker} {item_text}")
            else:
                continuation = markdown_to_text(line)
                if continuation:
                    rendered.append(continuation)
        return "\n".join(rendered).strip()

    if kind == "quote":
        rendered = []
        for line in lines:
            match = STORY_BLOCKQUOTE_RE.match(line)
            quote_text = markdown_to_text(match.group("text") if match else line)
            if quote_text:
                rendered.append(f"> {quote_text}")
        return "\n".join(rendered).strip()

    return normalize_whitespace(markdown_to_text("\n".join(lines)))


def story_markdown_blocks(markdown: str) -> list[StoryBlock]:
    """Parse meaningful Markdown blocks without relying on PDF page breaks."""

    blocks: list[StoryBlock] = []
    current_kind: str | None = None
    current_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current_kind, current_lines
        if current_kind is not None and current_lines:
            text = _render_story_block(current_kind, current_lines)
            if text:
                blocks.append(StoryBlock(current_kind, text))
        current_kind = None
        current_lines = []

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()

        if is_story_page_metadata_line(line):
            index += 1
            continue

        if in_fence:
            current_lines.append(line)
            if STORY_FENCE_RE.match(line):
                in_fence = False
            index += 1
            continue

        if not line.strip() or re.fullmatch(r"\s*<!--.*?-->\s*", line):
            flush()
            index += 1
            continue

        heading = _story_heading(line)
        if heading is not None:
            flush()
            level, heading_text = heading
            blocks.append(StoryBlock("heading", f"{'#' * level} {heading_text}"))
            index += 1
            continue

        if (
            index + 1 < len(lines)
            and line.strip()
            and STORY_SETEXT_HEADING_RE.match(lines[index + 1])
            and not is_story_page_metadata_line(lines[index + 1])
        ):
            heading_text = markdown_to_text(line)
            if heading_text:
                flush()
                blocks.append(StoryBlock("heading", f"## {heading_text}"))
                index += 2
                continue

        if STORY_FENCE_RE.match(line):
            if current_kind != "code":
                flush()
                current_kind = "code"
            current_lines.append(line)
            in_fence = True
            index += 1
            continue

        if STORY_LIST_ITEM_RE.match(line):
            kind = "list"
        elif STORY_BLOCKQUOTE_RE.match(line):
            kind = "quote"
        else:
            kind = "paragraph"

        if current_kind != kind:
            # Wrapped list lines are part of the list block, even when they
            # are indented and do not repeat the bullet marker.
            if not (
                current_kind == "list"
                and kind == "paragraph"
                and re.match(r"^\s{2,}\S", line)
            ):
                flush()
                current_kind = kind
        current_lines.append(line)
        index += 1

    flush()
    return blocks


def _story_sections(
    blocks: Sequence[StoryBlock],
) -> list[tuple[str | None, list[StoryBlock]]]:
    sections: list[tuple[str | None, list[StoryBlock]]] = []
    heading: str | None = None
    body: list[StoryBlock] = []
    for block in blocks:
        if block.kind == "heading":
            if heading is not None or body:
                sections.append((heading, body))
            heading = block.text
            body = []
        else:
            body.append(block)
    if heading is not None or body:
        sections.append((heading, body))
    return sections


def _pack_story_units(
    units: Sequence[str], separator: str, max_characters: int
) -> list[str]:
    packed: list[str] = []
    current = ""
    for raw_unit in units:
        unit = raw_unit.strip()
        if not unit:
            continue
        if len(unit) > max_characters:
            if current:
                packed.append(current)
                current = ""
            words = unit.split()
            word_chunk = ""
            for word in words:
                candidate = f"{word_chunk} {word}".strip()
                if word_chunk and len(candidate) > max_characters:
                    packed.append(word_chunk)
                    word_chunk = word
                else:
                    word_chunk = candidate
            if word_chunk:
                current = word_chunk
            continue
        candidate = f"{current}{separator}{unit}" if current else unit
        if current and len(candidate) > max_characters:
            packed.append(current)
            current = unit
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def _split_story_block(
    block: StoryBlock, max_characters: int = STORY_CHUNK_MAX_CHARACTERS
) -> list[str]:
    if len(block.text) <= max_characters:
        return [block.text]
    if block.kind in {"list", "quote"}:
        return _pack_story_units(block.text.splitlines(), "\n", max_characters)
    sentences = re.split(r"(?<=[.!?])\s+", block.text)
    return _pack_story_units(sentences, " ", max_characters)


def _story_section_chunks(
    heading: str | None, blocks: Sequence[StoryBlock]
) -> list[str]:
    parts: list[str] = []
    part_max_characters = STORY_CHUNK_MAX_CHARACTERS
    if heading:
        part_max_characters = max(
            1, STORY_CHUNK_MAX_CHARACTERS - len(heading) - 2
        )
    for block in blocks:
        parts.extend(_split_story_block(block, part_max_characters))

    current: list[str] = [heading] if heading else []
    current_body_count = 0
    current_characters = len(heading) if heading else 0
    chunks: list[str] = []
    for part in parts:
        separator_length = 2 if current else 0
        exceeds_window = (
            current_body_count > 0
            and (
                current_body_count >= STORY_CHUNK_MAX_BLOCKS
                or current_characters + separator_length + len(part)
                > STORY_CHUNK_MAX_CHARACTERS
            )
        )
        if exceeds_window:
            chunks.append("\n\n".join(current).strip())
            current = [heading] if heading else []
            current_body_count = 0
            current_characters = len(heading) if heading else 0
            separator_length = 2 if current else 0
        current.append(part)
        current_body_count += 1
        current_characters += separator_length + len(part)

    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def markdown_passages(
    path: Path,
    source_root: Path,
    source: str,
    citation_prefix: str,
) -> tuple[str, str, list[Passage]]:
    content = path.read_text(encoding="utf-8", errors="replace")
    title = extract_front_matter_title(content)
    front_matter_match = re.match(
        r"\s*---\s*\n(.*?)\n---\s*(?:\n|$)", content, flags=re.DOTALL
    )
    content_without_front_matter = (
        content[front_matter_match.end() :] if front_matter_match else content
    )
    blocks = story_markdown_blocks(content_without_front_matter)
    if not title:
        first_heading = next(
            (block for block in blocks if block.kind == "heading"), None
        )
        if first_heading is not None:
            title = markdown_to_text(first_heading.text)
    title = title or humanize_filename(path.stem)
    book = title
    if (
        blocks
        and blocks[0].kind == "heading"
        and re.match(r"^#\s", blocks[0].text)
        and normalize(markdown_to_text(blocks[0].text)) == normalize(title)
    ):
        # The document-level title is already represented by the title and
        # book fields. Do not create a title-only passage before the first
        # meaningful section.
        blocks = blocks[1:]

    try:
        relative_to_root = path.relative_to(source_root).as_posix()
    except ValueError:
        relative_to_root = path.name
    relative_path = f"{citation_prefix}/{relative_to_root}"
    passages: list[Passage] = []
    for section_number, (heading, section_blocks) in enumerate(
        _story_sections(blocks), start=1
    ):
        for chunk_number, text in enumerate(
            _story_section_chunks(heading, section_blocks), start=1
        ):
            passages.append(
                Passage(
                    source=source,
                    title=title,
                    book=book,
                    relative_path=relative_path,
                    absolute_path=str(path.resolve()),
                    anchor=f"section-{section_number}/chunk-{chunk_number}",
                    ordinal=len(passages),
                    text=text,
                    page=None,
                )
            )
    return title, book, passages


def story_passages(path: Path, source_root: Path) -> tuple[str, str, list[Passage]]:
    """Parse a Baba story Markdown file using the legacy public contract."""

    return markdown_passages(path, source_root, "stories", "Stories")


def other_spiritual_book_passages(
    path: Path, source_root: Path
) -> tuple[str, str, list[Passage]]:
    return markdown_passages(
        path,
        source_root,
        "other_spiritual_books",
        SOURCE_CITATION_PREFIXES["other_spiritual_books"],
    )


def acharya_philosophy_passages(
    path: Path, source_root: Path
) -> tuple[str, str, list[Passage]]:
    return markdown_passages(
        path,
        source_root,
        "acharya_philosophy",
        SOURCE_CITATION_PREFIXES["acharya_philosophy"],
    )


def iter_files(root: Path | None, suffixes: Sequence[str]) -> Iterator[Path]:
    if root is None or not root.is_dir():
        return
    suffix_set = {suffix.lower() for suffix in suffixes}
    paths = (
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffix_set
    )
    yield from sorted(paths, key=lambda item: item.relative_to(root).as_posix().casefold())


def resolve_discourse_root(value: str | os.PathLike[str] | None) -> Path | None:
    if value:
        root = Path(value).expanduser().resolve()
        if (root / "Discourses").is_dir():
            root = root / "Discourses"
        return root
    env_value = os.environ.get("BABA_DISCOURSES_DIR")
    if env_value:
        return resolve_discourse_root(env_value)
    for candidate in DEFAULT_DISCOURSE_CANDIDATES:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def resolve_stories_root(value: str | os.PathLike[str] | None) -> Path | None:
    if value:
        root = Path(value).expanduser().resolve()
        return root
    env_value = os.environ.get("BABA_STORIES_DIR")
    if env_value:
        return resolve_stories_root(env_value)
    return DEFAULT_STORIES_PATH.resolve() if DEFAULT_STORIES_PATH.is_dir() else None


def resolve_other_spiritual_books_root(
    value: str | os.PathLike[str] | None,
) -> Path | None:
    if value:
        return Path(value).expanduser().resolve()
    env_value = os.environ.get("BABA_OTHER_SPIRITUAL_BOOKS_DIR")
    if env_value:
        return resolve_other_spiritual_books_root(env_value)
    return (
        DEFAULT_OTHER_SPIRITUAL_BOOKS_PATH.resolve()
        if DEFAULT_OTHER_SPIRITUAL_BOOKS_PATH.is_dir()
        else None
    )


def resolve_acharya_philosophy_root(
    value: str | os.PathLike[str] | None,
) -> Path | None:
    if value:
        return Path(value).expanduser().resolve()
    env_value = os.environ.get("BABA_ACHARYA_PHILOSOPHY_DIR")
    if env_value:
        return resolve_acharya_philosophy_root(env_value)
    return (
        DEFAULT_ACHARYA_PHILOSOPHY_PATH.resolve()
        if DEFAULT_ACHARYA_PHILOSOPHY_PATH.is_dir()
        else None
    )


def resolve_connections_root(
    value: str | os.PathLike[str] | None,
) -> Path | None:
    """Resolve the optional Gemini graph artifact directory for index builds."""

    if value:
        return Path(value).expanduser().resolve()
    env_value = os.environ.get("BABA_CONNECTIONS_DIR")
    if env_value:
        return resolve_connections_root(env_value)
    return (
        DEFAULT_CONNECTIONS_ROOT.resolve()
        if DEFAULT_CONNECTIONS_ROOT.is_dir()
        else None
    )


def validate_source(source: str) -> None:
    source_scope_sources(source)


def source_scope_sources(source: str) -> tuple[str, ...]:
    """Return the indexed source categories included by a public scope.

    A scope may name one category, one of the aliases ``default`` or ``all``,
    or multiple categories joined with ``+``.  The legacy ``both`` alias is
    accepted so saved prompts and older clients continue to work.
    """

    if not isinstance(source, str) or not source.strip():
        raise BabaSearchError(
            "source must name one or more categories joined with +, or be default or all"
        )

    normalized_source = source.strip().casefold()
    if normalized_source in {"both", "default"}:
        return DEFAULT_SEARCH_SOURCES
    if normalized_source == "all":
        return CORPUS_SOURCES

    requested_sources = tuple(
        part.strip() for part in re.split(r"[+,]", normalized_source) if part.strip()
    )
    invalid_sources = tuple(
        part for part in requested_sources if part not in CORPUS_SOURCES
    )
    if not requested_sources or invalid_sources:
        choices = ", ".join(SOURCE_CHOICES)
        raise BabaSearchError(
            f"source must be a category, default, all, or a + combination of categories; "
            f"valid names are: {choices}"
        )

    requested_set = set(requested_sources)
    return tuple(source_name for source_name in CORPUS_SOURCES if source_name in requested_set)


def normalize_source_scope(source: str) -> str:
    """Return the stable CLI spelling for a source scope."""

    sources = source_scope_sources(source)
    if sources == DEFAULT_SEARCH_SOURCES:
        return "default"
    if sources == CORPUS_SOURCES:
        return "all"
    return "+".join(sources)


def source_scope_argument(value: str) -> str:
    """Argparse converter for single or combined source scopes."""

    try:
        return normalize_source_scope(value)
    except BabaSearchError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def source_where_clause(source: str, column: str = "source") -> tuple[str, list[str]]:
    """Return a SQL WHERE fragment and parameters for a public source scope."""

    sources = source_scope_sources(source)
    if sources == CORPUS_SOURCES:
        return "", []
    placeholders = ", ".join("?" for _ in sources)
    return f"{column} IN ({placeholders})", list(sources)


def fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE temp.baba_fts_probe USING fts5(value)"
        )
        conn.execute("DROP TABLE temp.baba_fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def create_schema(conn: sqlite3.Connection, use_fts5: bool) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE passages (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            book TEXT NOT NULL DEFAULT '',
            relative_path TEXT NOT NULL,
            absolute_path TEXT NOT NULL,
            anchor TEXT NOT NULL,
            page INTEGER,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            normalized_book TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            UNIQUE (source, relative_path, anchor, normalized_text)
        );
        CREATE INDEX passages_source_path_idx
            ON passages (source, relative_path);
        CREATE INDEX passages_source_book_idx
            ON passages (source, normalized_book);
        CREATE INDEX passages_source_title_idx
            ON passages (source, normalized_title);
        CREATE TABLE search_terms (
            source TEXT NOT NULL,
            term TEXT NOT NULL,
            document_frequency INTEGER NOT NULL,
            term_frequency INTEGER NOT NULL,
            PRIMARY KEY (source, term)
        );
        CREATE INDEX search_terms_term_idx
            ON search_terms(term);
        CREATE TABLE graph_claims (
            claim_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            document_id TEXT NOT NULL,
            passage_id TEXT NOT NULL,
            citation TEXT NOT NULL,
            claim_type TEXT NOT NULL DEFAULT '',
            statement TEXT NOT NULL DEFAULT '',
            quote TEXT NOT NULL DEFAULT '',
            key_terms_json TEXT NOT NULL DEFAULT '[]',
            modality TEXT NOT NULL DEFAULT '',
            attribution TEXT NOT NULL DEFAULT '',
            qualifiers TEXT NOT NULL DEFAULT '',
            selection_basis TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL DEFAULT '',
            source_title TEXT NOT NULL DEFAULT '',
            source_book TEXT NOT NULL DEFAULT '',
            source_path TEXT NOT NULL DEFAULT '',
            source_anchor TEXT NOT NULL DEFAULT '',
            source_page INTEGER,
            source_absolute_path TEXT NOT NULL DEFAULT '',
            source_passage_found INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX graph_claims_source_idx
            ON graph_claims(source);
        CREATE INDEX graph_claims_citation_idx
            ON graph_claims(citation);
        CREATE TABLE graph_connections (
            connection_id TEXT PRIMARY KEY,
            connection_type TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            explanation TEXT NOT NULL DEFAULT '',
            claim_ids_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL
        );
        CREATE INDEX graph_connections_type_idx
            ON graph_connections(connection_type);
        CREATE TABLE graph_connection_claims (
            connection_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (connection_id, claim_id),
            FOREIGN KEY (connection_id) REFERENCES graph_connections(connection_id)
        );
        CREATE INDEX graph_connection_claims_claim_idx
            ON graph_connection_claims(claim_id);
        CREATE TABLE graph_themes (
            theme_id TEXT PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            claim_ids_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL
        );
        CREATE TABLE graph_theme_claims (
            theme_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (theme_id, claim_id),
            FOREIGN KEY (theme_id) REFERENCES graph_themes(theme_id)
        );
        CREATE INDEX graph_theme_claims_claim_idx
            ON graph_theme_claims(claim_id);
        """
    )
    if use_fts5:
        conn.execute(
            """
            CREATE VIRTUAL TABLE passages_fts USING fts5(
                normalized_title,
                normalized_book,
                normalized_text,
                content='passages',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )


def _graph_string(value: object) -> str:
    return value if isinstance(value, str) else str(value or "")


def _graph_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_graph_string(item) for item in value if isinstance(item, str)]


def _graph_claim_ids(value: object) -> list[str]:
    return _graph_string_list(value)


def _graph_citation_parts(
    citation: str,
    document_id: str,
) -> tuple[str, str, str]:
    """Return source category, indexed relative path, and passage anchor."""

    source = ""
    relative_path = ""
    anchor = ""
    path_part, separator, anchor_part = citation.partition("#")
    for candidate_source, prefix in SOURCE_CITATION_PREFIXES.items():
        prefix_with_slash = f"{prefix}/"
        if path_part.startswith(prefix_with_slash):
            source = candidate_source
            relative_path = path_part
            anchor = anchor_part if separator else ""
            break

    if not source and ":" in document_id:
        candidate_source, document_path = document_id.split(":", 1)
        if candidate_source in CORPUS_SOURCES:
            source = candidate_source
            relative_path = document_path
            if separator:
                anchor = anchor_part

    return source, relative_path, anchor


def _graph_source_passage(
    conn: sqlite3.Connection,
    source: str,
    relative_path: str,
    anchor: str,
    passage_id: str,
) -> sqlite3.Row | None:
    if source and relative_path and anchor:
        row = conn.execute(
            """
            SELECT title, book, relative_path, anchor, page, text, absolute_path
            FROM passages
            WHERE source = ? AND relative_path = ? AND anchor = ?
            ORDER BY ordinal, id
            LIMIT 1
            """,
            (source, relative_path, anchor),
        ).fetchone()
        if row is not None:
            return row

    passage_match = re.fullmatch(r"p(\d+)", passage_id)
    if not (source and relative_path and passage_match):
        return None
    ordinal = int(passage_match.group(1)) - 1
    if ordinal < 0:
        return None
    return conn.execute(
        """
        SELECT title, book, relative_path, anchor, page, text, absolute_path
        FROM passages
        WHERE source = ? AND relative_path = ? AND ordinal = ?
        ORDER BY id
        LIMIT 1
        """,
        (source, relative_path, ordinal),
    ).fetchone()


def _read_graph_json(path: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise BabaSearchError(
            f"Graph artifact is not valid JSON: {path} ({exc.msg})"
        ) from exc
    except OSError as exc:
        raise BabaSearchError(f"Could not read graph artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BabaSearchError(f"Graph artifact must contain a JSON object: {path}")
    return payload


def ingest_graph_artifact(
    conn: sqlite3.Connection,
    connections_root: Path | None,
) -> dict[str, str]:
    """Ingest the optional validated Gemini graph into the write-time index."""

    metadata = {
        "connections_root": str(connections_root) if connections_root else "",
        "connections_status": "absent",
        "connections_claims": "0",
        "connections_connections": "0",
        "connections_themes": "0",
        "connections_source_passages": "0",
        "connections_warnings": "0",
    }
    if connections_root is None or not connections_root.is_dir():
        return metadata

    claims_path = connections_root / "claims.json"
    if not claims_path.is_file():
        return metadata

    claims_payload = _read_graph_json(claims_path)
    raw_claims = claims_payload.get("items")
    if raw_claims is None:
        raw_claims = claims_payload.get("claims", [])
    if not isinstance(raw_claims, list):
        raise BabaSearchError(
            f"Graph claims artifact must contain an items array: {claims_path}"
        )

    warning_count = 0
    source_passage_count = 0
    accepted_claims: list[dict[str, object]] = []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            warning_count += 1
            continue
        claim_id = _graph_string(raw_claim.get("claim_id")).strip()
        if not claim_id:
            warning_count += 1
            continue
        document_id = _graph_string(raw_claim.get("document_id"))
        passage_id = _graph_string(raw_claim.get("passage_id"))
        citation = _graph_string(raw_claim.get("citation"))
        source, relative_path, anchor = _graph_citation_parts(
            citation, document_id
        )
        if not source and ":" in document_id:
            source = document_id.split(":", 1)[0]
        source_row = _graph_source_passage(
            conn, source, relative_path, anchor, passage_id
        )
        if source_row is not None:
            source_passage_count += 1

        conn.execute(
            """
            INSERT OR REPLACE INTO graph_claims(
                claim_id, source, document_id, passage_id, citation, claim_type,
                statement, quote, key_terms_json, modality, attribution,
                qualifiers, selection_basis, source_text, source_title,
                source_book, source_path, source_anchor, source_page,
                source_absolute_path, source_passage_found, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                source,
                document_id,
                passage_id,
                citation,
                _graph_string(raw_claim.get("type")),
                _graph_string(raw_claim.get("statement")),
                _graph_string(raw_claim.get("quote")),
                json.dumps(
                    _graph_string_list(raw_claim.get("key_terms")),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                _graph_string(raw_claim.get("modality")),
                _graph_string(raw_claim.get("attribution")),
                _graph_string(raw_claim.get("qualifiers")),
                _graph_string(raw_claim.get("selection_basis")),
                str(source_row["text"]) if source_row is not None else "",
                str(source_row["title"]) if source_row is not None else "",
                str(source_row["book"]) if source_row is not None else "",
                str(source_row["relative_path"])
                if source_row is not None
                else relative_path,
                str(source_row["anchor"]) if source_row is not None else anchor,
                source_row["page"] if source_row is not None else None,
                str(source_row["absolute_path"])
                if source_row is not None
                else "",
                1 if source_row is not None else 0,
                json.dumps(raw_claim, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        accepted_claims.append(raw_claim)

    relationships_path = connections_root / "relationships" / "result.json"
    relationship_payload: dict[str, object] = {}
    if relationships_path.is_file():
        relationship_payload = _read_graph_json(relationships_path)

    raw_connections = relationship_payload.get("connections", [])
    if raw_connections is None:
        raw_connections = relationship_payload.get("relationships", [])
    if not isinstance(raw_connections, list):
        raise BabaSearchError(
            f"Graph relationship artifact must contain a connections array: {relationships_path}"
        )
    for raw_connection in raw_connections:
        if not isinstance(raw_connection, dict):
            warning_count += 1
            continue
        connection_id = _graph_string(raw_connection.get("connection_id")).strip()
        if not connection_id:
            warning_count += 1
            continue
        claim_ids = _graph_claim_ids(raw_connection.get("claim_ids"))
        conn.execute(
            """
            INSERT OR REPLACE INTO graph_connections(
                connection_id, connection_type, confidence, summary,
                explanation, claim_ids_json, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                connection_id,
                _graph_string(raw_connection.get("type")),
                _graph_string(raw_connection.get("confidence")),
                _graph_string(raw_connection.get("summary")),
                _graph_string(raw_connection.get("explanation")),
                json.dumps(claim_ids, ensure_ascii=False, separators=(",", ":")),
                json.dumps(
                    raw_connection, ensure_ascii=False, separators=(",", ":")
                ),
            ),
        )
        for position, claim_id in enumerate(claim_ids):
            conn.execute(
                """
                INSERT OR REPLACE INTO graph_connection_claims(
                    connection_id, claim_id, position
                ) VALUES (?, ?, ?)
                """,
                (connection_id, claim_id, position),
            )

    raw_themes = relationship_payload.get("themes", [])
    if not isinstance(raw_themes, list):
        raise BabaSearchError(
            f"Graph relationship artifact must contain a themes array: {relationships_path}"
        )
    for raw_theme in raw_themes:
        if not isinstance(raw_theme, dict):
            warning_count += 1
            continue
        theme_id = _graph_string(raw_theme.get("theme_id")).strip()
        if not theme_id:
            warning_count += 1
            continue
        claim_ids = _graph_claim_ids(raw_theme.get("claim_ids"))
        conn.execute(
            """
            INSERT OR REPLACE INTO graph_themes(
                theme_id, label, summary, claim_ids_json, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                theme_id,
                _graph_string(raw_theme.get("label")),
                _graph_string(raw_theme.get("summary")),
                json.dumps(claim_ids, ensure_ascii=False, separators=(",", ":")),
                json.dumps(raw_theme, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        for position, claim_id in enumerate(claim_ids):
            conn.execute(
                """
                INSERT OR REPLACE INTO graph_theme_claims(theme_id, claim_id, position)
                VALUES (?, ?, ?)
                """,
                (theme_id, claim_id, position),
            )

    metadata.update(
        {
            "connections_status": (
                "indexed" if relationships_path.is_file() else "claims-only"
            ),
            "connections_claims": str(len(accepted_claims)),
            "connections_connections": str(
                sum(1 for item in raw_connections if isinstance(item, dict))
            ),
            "connections_themes": str(
                sum(1 for item in raw_themes if isinstance(item, dict))
            ),
            "connections_source_passages": str(source_passage_count),
            "connections_warnings": str(warning_count),
        }
    )
    return metadata


def insert_meta(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)", values.items()
    )


def build_index(
    index_path: Path,
    discourse_root: Path | None,
    stories_root: Path | None,
    force_fts5: bool | None = None,
    other_spiritual_books_root: Path | None = None,
    acharya_philosophy_root: Path | None = None,
    connections_root: Path | None = None,
) -> dict[str, object]:
    """Build a new index file without touching either source corpus."""

    if (
        discourse_root is None
        and stories_root is None
        and other_spiritual_books_root is None
        and acharya_philosophy_root is None
    ):
        raise BabaSearchError(
            "No corpus sources found. Set BABA_DISCOURSES_DIR or pass "
            "one or more corpus root options."
        )
    if discourse_root is not None and not discourse_root.is_dir():
        raise BabaSearchError(f"Discourse source directory not found: {discourse_root}")
    if stories_root is not None and not stories_root.is_dir():
        raise BabaSearchError(f"Story source directory not found: {stories_root}")
    if other_spiritual_books_root is not None and not other_spiritual_books_root.is_dir():
        raise BabaSearchError(
            "Other spiritual books source directory not found: "
            f"{other_spiritual_books_root}"
        )
    if acharya_philosophy_root is not None and not acharya_philosophy_root.is_dir():
        raise BabaSearchError(
            "Acharya philosophy source directory not found: "
            f"{acharya_philosophy_root}"
        )

    index_path = index_path.expanduser().resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{index_path.stem}.", suffix=".tmp", dir=index_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)

    source_files_seen = {source: 0 for source in CORPUS_SOURCES}
    source_files_with_passages = {source: 0 for source in CORPUS_SOURCES}
    source_passages = {source: 0 for source in CORPUS_SOURCES}
    source_duplicates = {source: 0 for source in CORPUS_SOURCES}
    term_stats: dict[tuple[str, str], list[int]] = {}

    try:
        conn = sqlite3.connect(temp_path)
        conn.row_factory = sqlite3.Row
        # The build writes to a separate temporary database and replaces the
        # published index only after the build succeeds. Avoiding a second
        # on-disk journal keeps peak usage manageable for the large corpus.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        use_fts5 = fts5_available(conn) if force_fts5 is None else force_fts5
        create_schema(conn, use_fts5)

        def record_search_terms(passage: Passage) -> None:
            fields = " ".join((passage.title, passage.book, passage.text))
            counts = Counter(tokenize(fields))
            for term, frequency in counts.items():
                key = (passage.source, term)
                aggregate = term_stats.setdefault(key, [0, 0])
                aggregate[0] += 1
                aggregate[1] += frequency

        def add_passage(passage: Passage) -> bool:
            normalized_title = normalize(passage.title)
            normalized_book = normalize(passage.book)
            normalized_text = normalize(passage.text)
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO passages(
                    source, title, book, relative_path, absolute_path, anchor,
                    page, ordinal, text, normalized_title, normalized_book,
                    normalized_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    passage.source,
                    passage.title,
                    passage.book,
                    passage.relative_path,
                    passage.absolute_path,
                    passage.anchor,
                    passage.page,
                    passage.ordinal,
                    passage.text,
                    normalized_title,
                    normalized_book,
                    normalized_text,
                ),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                record_search_terms(passage)
            return inserted

        for path in iter_files(discourse_root, (".html",)):
            source_files_seen["discourses"] += 1
            _, _, passages = discourse_passages(path, discourse_root)  # type: ignore[arg-type]
            inserted = 0
            for passage in passages:
                if add_passage(passage):
                    inserted += 1
                else:
                    source_duplicates["discourses"] += 1
            source_passages["discourses"] += inserted
            if inserted:
                source_files_with_passages["discourses"] += 1

        markdown_sources = (
            ("stories", stories_root, story_passages),
            (
                "other_spiritual_books",
                other_spiritual_books_root,
                other_spiritual_book_passages,
            ),
            (
                "acharya_philosophy",
                acharya_philosophy_root,
                acharya_philosophy_passages,
            ),
        )
        for source, source_root, parser in markdown_sources:
            for path in iter_files(source_root, (".md", ".markdown")):
                source_files_seen[source] += 1
                _, _, passages = parser(path, source_root)  # type: ignore[arg-type]
                inserted = 0
                for passage in passages:
                    if add_passage(passage):
                        inserted += 1
                    else:
                        source_duplicates[source] += 1
                source_passages[source] += inserted
                if inserted:
                    source_files_with_passages[source] += 1

        if term_stats:
            conn.executemany(
                """
                INSERT INTO search_terms(
                    source, term, document_frequency, term_frequency
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (source, term, values[0], values[1])
                    for (source, term), values in term_stats.items()
                ],
            )

        if use_fts5:
            conn.execute(
                """
                INSERT INTO passages_fts(rowid, normalized_title, normalized_book, normalized_text)
                SELECT id, normalized_title, normalized_book, normalized_text
                FROM passages
                ORDER BY id
                """
            )

        graph_metadata = ingest_graph_artifact(conn, connections_root)
        built_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "index_mode": "fts5" if use_fts5 else "scan",
            "built_at_utc": built_at,
        }
        metadata.update(graph_metadata)
        source_roots = {
            "discourses": discourse_root,
            "stories": stories_root,
            "other_spiritual_books": other_spiritual_books_root,
            "acharya_philosophy": acharya_philosophy_root,
        }
        for source in CORPUS_SOURCES:
            prefix = SOURCE_META_PREFIXES[source]
            root = source_roots[source]
            metadata.update(
                {
                    f"{prefix}_root": str(root) if root else "",
                    f"{prefix}_files_seen": str(source_files_seen[source]),
                    f"{prefix}_files_with_passages": str(
                        source_files_with_passages[source]
                    ),
                    f"{prefix}_passages": str(source_passages[source]),
                    f"{prefix}_duplicates": str(source_duplicates[source]),
                }
            )
        insert_meta(conn, metadata)
        conn.commit()
        conn.close()
        os.replace(temp_path, index_path)
    except Exception:
        try:
            conn.close()  # type: ignore[unbound-local]
        except (NameError, sqlite3.Error):
            pass
        temp_path.unlink(missing_ok=True)
        raise

    return stats(index_path)


def connect_read_only(index_path: Path) -> sqlite3.Connection:
    index_path = index_path.expanduser().resolve()
    if not index_path.is_file():
        raise BabaSearchError(
            f"Search index not found: {index_path}. Run 'baba-search index' first."
        )
    uri = f"file:{index_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise BabaSearchError(f"Could not open search index: {exc}") from exc


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error as exc:
        raise BabaSearchError("The search index is missing its metadata table") from exc
    return {row["key"]: row["value"] for row in rows}


def integer_meta(meta: dict[str, str], key: str) -> int:
    try:
        return int(meta.get(key, "0"))
    except ValueError:
        return 0


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def graph_index_stats(
    conn: sqlite3.Connection,
    meta: dict[str, str],
) -> dict[str, object]:
    graph_tables = (
        "graph_claims",
        "graph_connections",
        "graph_connection_claims",
        "graph_themes",
        "graph_theme_claims",
    )
    if not all(_table_exists(conn, table) for table in graph_tables):
        return {
            "available": False,
            "status": "not_indexed",
            "root": "",
            "claims": 0,
            "connections": 0,
            "themes": 0,
            "linked_claims": 0,
            "source_passages": 0,
            "warnings": 0,
        }
    return {
        "available": meta.get("connections_status") in {"indexed", "claims-only"},
        "status": meta.get("connections_status", "absent"),
        "root": meta.get("connections_root", ""),
        "claims": int(
            conn.execute("SELECT COUNT(*) AS count FROM graph_claims").fetchone()["count"]
        ),
        "connections": int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM graph_connections"
            ).fetchone()["count"]
        ),
        "themes": int(
            conn.execute("SELECT COUNT(*) AS count FROM graph_themes").fetchone()["count"]
        ),
        "linked_claims": int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT claim_id) AS count
                FROM (
                    SELECT claim_id FROM graph_connection_claims
                    UNION ALL
                    SELECT claim_id FROM graph_theme_claims
                )
                """
            ).fetchone()["count"]
        ),
        "source_passages": integer_meta(meta, "connections_source_passages"),
        "warnings": integer_meta(meta, "connections_warnings"),
    }


def stats(index_path: Path) -> dict[str, object]:
    conn = connect_read_only(index_path)
    try:
        meta = read_meta(conn)
        total_passages = int(
            conn.execute("SELECT COUNT(*) AS count FROM passages").fetchone()["count"]
        )
        total_characters = int(
            conn.execute("SELECT COALESCE(SUM(LENGTH(text)), 0) AS count FROM passages")
            .fetchone()["count"]
        )
        source_rows = conn.execute(
            """
            SELECT source, COUNT(*) AS passages, COUNT(DISTINCT relative_path) AS documents
            FROM passages
            GROUP BY source
            ORDER BY source
            """
        ).fetchall()
        source_stats: dict[str, dict[str, object]] = {}
        for source in CORPUS_SOURCES:
            prefix = SOURCE_META_PREFIXES[source]
            source_stats[source] = {
                "files_seen": integer_meta(meta, f"{prefix}_files_seen"),
                "files_with_passages": integer_meta(
                    meta, f"{prefix}_files_with_passages"
                ),
                "documents": 0,
                "passages": 0,
                "duplicates": integer_meta(meta, f"{prefix}_duplicates"),
            }
        for row in source_rows:
            source_stats.setdefault(
                str(row["source"]),
                {
                    "files_seen": 0,
                    "files_with_passages": 0,
                    "documents": 0,
                    "passages": 0,
                    "duplicates": 0,
                },
            )
            source_stats[row["source"]]["documents"] = int(row["documents"])
            source_stats[row["source"]]["passages"] = int(row["passages"])
        try:
            index_mode = meta.get("index_mode", "scan")
            fts5_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'passages_fts'"
            ).fetchone()
            fts5_present = bool(fts5_table)
        except sqlite3.Error:
            fts5_present = False
        return {
            "index_path": str(index_path.expanduser().resolve()),
            "index_bytes": index_path.stat().st_size,
            "schema_version": meta.get("schema_version", ""),
            "index_mode": index_mode,
            "fts5_present": fts5_present,
            "built_at_utc": meta.get("built_at_utc", ""),
            "source_roots": {
                source: meta.get(f"{SOURCE_META_PREFIXES[source]}_root", "")
                for source in CORPUS_SOURCES
            },
            "passages": total_passages,
            "characters": total_characters,
            "sources": source_stats,
            "graph": graph_index_stats(conn, meta),
        }
    finally:
        conn.close()


def parse_query(raw_query: str) -> QueryPlan:
    parts: list[tuple[bool, str]] = []
    pattern = re.compile(r'"([^"]+)"|\'([^\']+)\'|(\S+)')
    for match in pattern.finditer(raw_query):
        quoted_text = match.group(1) or match.group(2)
        if quoted_text is not None:
            parts.append((True, quoted_text))
        else:
            parts.append((False, match.group(3)))

    terms: list[str] = []
    phrases: list[tuple[str, ...]] = []
    for is_phrase, part in parts:
        part_terms = tokenize(part)
        if not part_terms:
            continue
        if is_phrase and len(part_terms) > 1:
            phrases.append(tuple(part_terms))
        for term in part_terms:
            if term not in terms:
                terms.append(term)
    if not terms:
        raise BabaSearchError("Query must contain at least one searchable term")
    return QueryPlan(terms=tuple(terms), phrases=tuple(phrases))


def fts_query(plan: QueryPlan) -> str:
    # Each term is quoted so punctuation or FTS operators in user input cannot
    # change the query.  Phrase validation is repeated in Python below.
    return " AND ".join(f'"{term}"' for term in plan.terms)


def phrase_spans(
    spans: list[tuple[str, int, int]], phrase: tuple[str, ...]
) -> list[tuple[int, int]]:
    if not phrase or len(spans) < len(phrase):
        return []
    matches: list[tuple[int, int]] = []
    width = len(phrase)
    for start in range(len(spans) - width + 1):
        window = spans[start : start + width]
        if tuple(token for token, _, _ in window) == phrase:
            matches.append((window[0][1], window[-1][2]))
    return matches


def term_spans(
    spans: list[tuple[str, int, int]], term: str
) -> list[tuple[int, int]]:
    return [(start, end) for token, start, end in spans if token == term]


def original_span(
    source_text: str, normalized_text: str, mapping: list[int], span: tuple[int, int]
) -> tuple[int, int]:
    start, end = span
    if not mapping or start >= len(mapping):
        return 0, min(len(source_text), max(1, end))
    source_start = mapping[start]
    source_end = mapping[min(end - 1, len(mapping) - 1)] + 1
    return source_start, source_end


def make_snippet(
    source_text: str,
    normalized_text: str,
    span: tuple[int, int],
    context: int,
) -> tuple[str, str]:
    mapping = normalize_with_map(source_text)[1]
    source_start, source_end = original_span(
        source_text, normalized_text, mapping, span
    )
    start = max(0, source_start - context)
    end = min(len(source_text), source_end + context)
    snippet = source_text[start:end].strip()
    if start > 0:
        snippet = "... " + snippet
    if end < len(source_text):
        snippet = snippet + " ..."
    matched = source_text[source_start:source_end]
    return snippet, matched


def document_match_counts(
    conn: sqlite3.Connection,
    candidate_rows: Sequence[sqlite3.Row],
    plan: QueryPlan,
) -> dict[tuple[str, str], tuple[int, int]]:
    """Count query terms and phrases across each candidate's source document.

    The body text is counted across every indexed passage in the same source
    file. Titles and book names are intentionally excluded because they are
    repeated on every passage row and would otherwise be multiplied by the
    number of passages in the document.
    """

    document_keys = sorted(
        {
            (str(row["source"]), str(row["relative_path"]))
            for row in candidate_rows
        }
    )
    if not document_keys:
        return {}

    counts: dict[tuple[str, str], list[int]] = {
        key: [0, 0] for key in document_keys
    }
    # Keep each query below SQLite's usual bound-variable and expression-tree
    # limits even when a common term produces many candidate documents.
    for offset in range(0, len(document_keys), 250):
        batch = document_keys[offset : offset + 250]
        where_clause = " OR ".join(
            "(source = ? AND relative_path = ?)" for _ in batch
        )
        params: list[str] = [value for key in batch for value in key]
        rows = conn.execute(
            "SELECT source, relative_path, normalized_text "
            "FROM passages WHERE " + where_clause,
            params,
        ).fetchall()
        for row in rows:
            key = (str(row["source"]), str(row["relative_path"]))
            spans = token_spans(str(row["normalized_text"]))
            counts[key][0] += sum(
                len(term_spans(spans, term)) for term in plan.terms
            )
            counts[key][1] += sum(
                len(phrase_spans(spans, phrase)) for phrase in plan.phrases
            )

    return {key: (values[0], values[1]) for key, values in counts.items()}


def _field_matches(
    normalized_fields: dict[str, str], plan: QueryPlan
) -> tuple[dict[str, list[tuple[int, int]]], dict[str, int], int]:
    spans_by_field = {
        field: token_spans(value) for field, value in normalized_fields.items()
    }
    term_counts: dict[str, int] = {term: 0 for term in plan.terms}
    phrase_count = 0
    for term in plan.terms:
        term_count = sum(
            len(term_spans(spans, term)) for spans in spans_by_field.values()
        )
        if term_count == 0:
            return {}, {}, -1
        term_counts[term] = term_count
    phrase_spans_by_field: dict[str, list[tuple[int, int]]] = {
        field: [] for field in normalized_fields
    }
    for phrase in plan.phrases:
        matches = []
        for field, spans in spans_by_field.items():
            matches.extend(phrase_spans(spans, phrase))
        if not matches:
            return {}, {}, -1
        for field, spans in spans_by_field.items():
            phrase_spans_by_field[field].extend(phrase_spans(spans, phrase))
        phrase_count += len(matches)
    return phrase_spans_by_field, term_counts, phrase_count


def _natural_anchor_key(anchor: str) -> tuple[object, ...]:
    pieces = re.split(r"(\d+)", anchor.casefold())
    result: list[object] = []
    for piece in pieces:
        result.append(int(piece) if piece.isdigit() else piece)
    return tuple(result)


def score_row(
    row: sqlite3.Row,
    plan: QueryPlan,
    context: int,
    book_filter: str | None,
    title_filter: str | None,
    document_match_count: int = 0,
    document_phrase_count: int = 0,
) -> dict[str, object] | None:
    normalized_book_filter = normalize(book_filter) if book_filter else None
    normalized_title_filter = normalize(title_filter) if title_filter else None
    if normalized_book_filter and normalized_book_filter not in row["normalized_book"]:
        return None
    if normalized_title_filter and normalized_title_filter not in row["normalized_title"]:
        return None

    normalized_fields = {
        "title": row["normalized_title"],
        "book": row["normalized_book"],
        "text": row["normalized_text"],
    }
    phrase_by_field, term_counts, phrase_count = _field_matches(
        normalized_fields, plan
    )
    if phrase_count < 0:
        return None

    spans_by_field = {
        field: token_spans(value) for field, value in normalized_fields.items()
    }
    field_term_counts = {
        field: sum(
            len(term_spans(spans, term))
            for term in plan.terms
        )
        for field, spans in spans_by_field.items()
    }
    all_match_spans: dict[str, list[tuple[int, int]]] = {
        field: list(phrase_by_field.get(field, []))
        for field in normalized_fields
    }
    for field, spans in spans_by_field.items():
        for term in plan.terms:
            all_match_spans[field].extend(term_spans(spans, term))

    matched_fields = [field for field in ("text", "title", "book") if all_match_spans[field]]
    snippet_field = matched_fields[0] if matched_fields else "text"
    if not all_match_spans[snippet_field]:
        return None
    first_span = min(all_match_spans[snippet_field], key=lambda item: (item[0], item[1]))

    source_text_by_field = {
        "title": row["title"],
        "book": row["book"],
        "text": row["text"],
    }
    snippet, matched_text = make_snippet(
        source_text_by_field[snippet_field],
        normalized_fields[snippet_field],
        first_span,
        context,
    )
    total_term_matches = sum(term_counts.values())
    title_matches = field_term_counts["title"]
    book_matches = field_term_counts["book"]
    text_matches = field_term_counts["text"]
    score = (
        document_match_count * DOCUMENT_MATCH_WEIGHT
        + document_phrase_count * DOCUMENT_PHRASE_WEIGHT
        + phrase_count * LOCAL_PHRASE_WEIGHT
        + title_matches * TITLE_MATCH_WEIGHT
        + book_matches * BOOK_MATCH_WEIGHT
        + text_matches * TEXT_MATCH_WEIGHT
        + total_term_matches
    )
    page = row["page"]
    relative_path = row["relative_path"]
    anchor = row["anchor"]
    citation = f"{relative_path}#{anchor}" if anchor else relative_path
    return {
        "passage_id": row["id"],
        "score": score,
        "source": row["source"],
        "title": row["title"],
        "book": row["book"] or None,
        "file": relative_path,
        "path": relative_path,
        "anchor": anchor,
        "page": page,
        "snippet": snippet,
        "matched_text": matched_text,
        "matched_in": snippet_field,
        "matched_terms": list(plan.terms),
        "match_count": total_term_matches,
        "document_match_count": document_match_count,
        "document_phrase_count": document_phrase_count,
        "phrase_match": bool(plan.phrases),
        "source_path": row["absolute_path"],
        "citation": citation,
        "_sort_path": relative_path.casefold(),
        "_sort_anchor": _natural_anchor_key(anchor),
        "_id": row["id"],
    }


def search_index(
    index_path: Path,
    source: str,
    raw_query: str,
    limit: int = DEFAULT_LIMIT,
    context: int = DEFAULT_CONTEXT,
    book_filter: str | None = None,
    title_filter: str | None = None,
) -> dict[str, object]:
    validate_source(source)
    if limit < 1 or limit > MAX_LIMIT:
        raise BabaSearchError(f"limit must be between 1 and {MAX_LIMIT}")
    if context < 0:
        raise BabaSearchError("context must be zero or greater")
    plan = parse_query(raw_query)
    conn = connect_read_only(index_path)
    try:
        meta = read_meta(conn)
        source_where, source_params = source_where_clause(source, "p.source")
        source_clause = f" AND {source_where}" if source_where else ""
        params: list[object] = list(source_params)

        filter_clause = ""
        if book_filter:
            filter_clause += " AND p.normalized_book LIKE ?"
            params.append(f"%{normalize(book_filter)}%")
        if title_filter:
            filter_clause += " AND p.normalized_title LIKE ?"
            params.append(f"%{normalize(title_filter)}%")

        use_fts5 = meta.get("index_mode") == "fts5"
        candidate_rows: list[sqlite3.Row]
        if use_fts5:
            query = fts_query(plan)
            sql = (
                "SELECT p.* FROM passages AS p "
                "WHERE p.id IN (SELECT rowid FROM passages_fts WHERE passages_fts MATCH ?)"
                + source_clause
                + filter_clause
                + " ORDER BY p.id"
            )
            try:
                candidate_rows = conn.execute(sql, [query, *params]).fetchall()
            except sqlite3.OperationalError:
                candidate_rows = conn.execute(
                    "SELECT p.* FROM passages AS p WHERE 1 = 1"
                    + source_clause
                    + filter_clause
                    + " ORDER BY p.id",
                    params,
                ).fetchall()
        else:
            candidate_rows = conn.execute(
                "SELECT p.* FROM passages AS p WHERE 1 = 1"
                + source_clause
                + filter_clause
                + " ORDER BY p.id",
                params,
            ).fetchall()

        document_counts = document_match_counts(conn, candidate_rows, plan)

        results: list[dict[str, object]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in candidate_rows:
            document_match_count, document_phrase_count = document_counts.get(
                (str(row["source"]), str(row["relative_path"])),
                (0, 0),
            )
            result = score_row(
                row,
                plan,
                context,
                book_filter,
                title_filter,
                document_match_count=document_match_count,
                document_phrase_count=document_phrase_count,
            )
            if result is None:
                continue
            dedupe_key = (
                str(result["source"]),
                str(result["file"]),
                str(result["anchor"]),
                normalize(str(row["text"])),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(result)

        results.sort(
            key=lambda item: (
                -int(item["document_match_count"]),
                -int(item["document_phrase_count"]),
                -int(item["score"]),
                str(item["_sort_path"]),
                item["_sort_anchor"],
                int(item["_id"]),
            )
        )
        for rank, result in enumerate(results[:limit], start=1):
            result["rank"] = rank
        public_results = [
            {key: value for key, value in result.items() if not key.startswith("_")}
            for result in results[:limit]
        ]
        return {
            "query": raw_query,
            "parsed_terms": list(plan.terms),
            "phrases": [" ".join(phrase) for phrase in plan.phrases],
            "source": source,
            "book": book_filter,
            "title": title_filter,
            "limit": limit,
            "context": context,
            "index_mode": meta.get("index_mode", "scan"),
            "result_count": len(public_results),
            "results": public_results,
        }
    finally:
        conn.close()


def passage_by_citation(
    index_path: Path,
    citation: str,
    context_passages: int = 4,
) -> dict[str, object]:
    """Return one indexed source passage and a small surrounding file window."""

    if context_passages < 0 or context_passages > 12:
        raise BabaSearchError("context-passages must be between 0 and 12")

    normalized_citation = citation.strip()
    citation_prefix_pattern = "|".join(
        re.escape(prefix) for prefix in SOURCE_CITATION_PREFIXES.values()
    )
    match = re.fullmatch(
        rf"({citation_prefix_pattern})/(.+?)(?:#(.+))?", normalized_citation
    )
    if not match:
        raise BabaSearchError(
            "Citation must look like Discourses/File.html#anchor, "
            "Stories/File.md#anchor, Other-Spiritual-Books/File.md#anchor, "
            "or Acharya-Philosophy/File.md#anchor"
        )

    citation_prefix = match.group(1)
    source = next(
        source
        for source, prefix in SOURCE_CITATION_PREFIXES.items()
        if prefix.casefold() == citation_prefix.casefold()
    )
    relative_path = f"{SOURCE_CITATION_PREFIXES[source]}/{match.group(2)}"
    anchor = (match.group(3) or "").strip()
    if not anchor:
        raise BabaSearchError("Citation must include a passage anchor")

    conn = connect_read_only(index_path)
    try:
        selected_row = conn.execute(
            """
            SELECT id, source, title, book, relative_path, absolute_path,
                   anchor, page, ordinal, text
            FROM passages
            WHERE source = ? AND relative_path = ? AND anchor = ?
            ORDER BY ordinal, id
            LIMIT 1
            """,
            (source, relative_path, anchor),
        ).fetchone()
        if selected_row is None:
            raise BabaSearchError(f"Source passage not found: {normalized_citation}")

        target_ordinal = int(selected_row["ordinal"])
        context_rows = conn.execute(
            """
            SELECT id, anchor, ordinal, text
            FROM passages
            WHERE source = ?
              AND relative_path = ?
              AND ordinal BETWEEN ? AND ?
            ORDER BY ordinal, id
            """,
            (
                source,
                relative_path,
                max(0, target_ordinal - context_passages),
                target_ordinal + context_passages,
            ),
        ).fetchall()

        passages = [
            {
                "passage_id": int(row["id"]),
                "anchor": row["anchor"],
                "ordinal": int(row["ordinal"]),
                "text": row["text"],
                "selected": int(row["id"]) == int(selected_row["id"]),
            }
            for row in context_rows
        ]
        return {
            "command": "passage",
            "citation": normalized_citation,
            "source": selected_row["source"],
            "title": selected_row["title"],
            "book": selected_row["book"] or None,
            "file": selected_row["relative_path"],
            "path": selected_row["relative_path"],
            "anchor": selected_row["anchor"],
            "page": selected_row["page"],
            "source_path": selected_row["absolute_path"],
            "passage_id": int(selected_row["id"]),
            "text": selected_row["text"],
            "passages": passages,
        }
    finally:
        conn.close()


def _graph_json_list(value: object) -> list[object]:
    if not isinstance(value, str):
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _graph_claim_output(row: sqlite3.Row) -> dict[str, object]:
    source_text = str(row["source_text"] or "")
    source_path = str(row["source_path"] or "")
    source_absolute_path = str(row["source_absolute_path"] or "")
    return {
        "claim_id": row["claim_id"],
        "source": row["source"],
        "document_id": row["document_id"],
        "passage_id": row["passage_id"],
        "citation": row["citation"],
        "type": row["claim_type"],
        "statement": row["statement"],
        "quote": row["quote"],
        "key_terms": _graph_json_list(row["key_terms_json"]),
        "modality": row["modality"],
        "attribution": row["attribution"],
        "qualifiers": row["qualifiers"],
        "selection_basis": row["selection_basis"],
        "source_text": source_text or None,
        "source_text_found": bool(row["source_passage_found"]),
        "source_title": row["source_title"] or None,
        "source_book": row["source_book"] or None,
        "source_file": source_path or None,
        "source_anchor": row["source_anchor"] or None,
        "source_page": row["source_page"],
        "source_path": source_absolute_path or None,
    }


def _graph_query_score(text: str, plan: QueryPlan) -> int | None:
    _, term_counts, phrase_count = _field_matches(
        {"text": normalize(text)}, plan
    )
    if phrase_count < 0:
        return None
    return phrase_count * 100_000 + sum(term_counts.values())


def _graph_record_text(
    fields: Sequence[str],
    claim_ids: Sequence[str],
    claims_by_id: dict[str, sqlite3.Row],
) -> str:
    pieces = list(fields)
    for claim_id in claim_ids:
        row = claims_by_id.get(claim_id)
        if row is None:
            continue
        pieces.extend(
            (
                str(row["statement"]),
                str(row["quote"]),
                " ".join(
                    str(term) for term in _graph_json_list(row["key_terms_json"])
                ),
            )
        )
    return " ".join(piece for piece in pieces if piece)


def _graph_claims_for_ids(
    claim_ids: Sequence[str],
    claims_by_id: dict[str, sqlite3.Row],
) -> list[dict[str, object]]:
    return [
        _graph_claim_output(claims_by_id[claim_id])
        for claim_id in claim_ids
        if claim_id in claims_by_id
    ]


def connections_lookup(
    index_path: Path,
    source: str = DEFAULT_CONNECTIONS_SOURCE,
    query: str | None = None,
    claim_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, object]:
    """Retrieve graph relationships and themes from the read-only index."""

    normalized_source = normalize_source_scope(source)
    if limit < 1 or limit > MAX_LIMIT:
        raise BabaSearchError(f"limit must be between 1 and {MAX_LIMIT}")
    if query is None and claim_id is None:
        raise BabaSearchError("connections requires --query or --claim-id")
    if query is not None and not normalize_whitespace(query):
        raise BabaSearchError("query must contain searchable text")
    if claim_id is not None and not claim_id.strip():
        raise BabaSearchError("claim-id must contain text")

    plan = parse_query(query) if query is not None else None
    conn = connect_read_only(index_path)
    try:
        meta = read_meta(conn)
        graph = graph_index_stats(conn, meta)
        base_payload: dict[str, object] = {
            "command": "connections",
            "source": normalized_source,
            "query": query,
            "claim_id": claim_id,
            "limit": limit,
            "graph_status": graph["status"],
            "graph_root": graph["root"],
            "connections": [],
            "themes": [],
            "claims": [],
        }
        if not graph["available"]:
            base_payload.update(
                {
                    "result_count": 0,
                    "connection_count": 0,
                    "theme_count": 0,
                    "claim_count": 0,
                }
            )
            return base_payload

        sources = set(source_scope_sources(normalized_source))
        claim_rows = conn.execute(
            "SELECT * FROM graph_claims ORDER BY claim_id"
        ).fetchall()
        claims_by_id = {str(row["claim_id"]): row for row in claim_rows}
        if claim_id is not None:
            target_claim = claims_by_id.get(claim_id)
            if target_claim is None:
                raise BabaSearchError(f"Claim ID not found in graph: {claim_id}")
            if str(target_claim["source"]) not in sources:
                raise BabaSearchError(
                    f"Claim ID is outside source scope {normalized_source}: {claim_id}"
                )

        def in_scope(claim_ids: Sequence[str]) -> bool:
            return bool(claim_ids) and all(
                claim_id_value in claims_by_id
                and str(claims_by_id[claim_id_value]["source"]) in sources
                for claim_id_value in claim_ids
            )

        connection_candidates: list[tuple[int, str, sqlite3.Row, list[str]]] = []
        connection_rows = conn.execute(
            "SELECT * FROM graph_connections ORDER BY connection_id"
        ).fetchall()
        for row in connection_rows:
            claim_ids = [
                str(value) for value in _graph_json_list(row["claim_ids_json"])
            ]
            if not in_scope(claim_ids):
                continue
            if claim_id is not None and claim_id not in claim_ids:
                continue
            score = 0
            if plan is not None:
                score_value = _graph_query_score(
                    _graph_record_text(
                        (
                            str(row["connection_type"]),
                            str(row["confidence"]),
                            str(row["summary"]),
                            str(row["explanation"]),
                        ),
                        claim_ids,
                        claims_by_id,
                    ),
                    plan,
                )
                if score_value is None:
                    continue
                score = score_value
            connection_candidates.append(
                (score, str(row["connection_id"]), row, claim_ids)
            )

        theme_candidates: list[tuple[int, str, sqlite3.Row, list[str]]] = []
        theme_rows = conn.execute(
            "SELECT * FROM graph_themes ORDER BY theme_id"
        ).fetchall()
        for row in theme_rows:
            claim_ids = [
                str(value) for value in _graph_json_list(row["claim_ids_json"])
            ]
            if not in_scope(claim_ids):
                continue
            if claim_id is not None and claim_id not in claim_ids:
                continue
            score = 0
            if plan is not None:
                score_value = _graph_query_score(
                    _graph_record_text(
                        (str(row["label"]), str(row["summary"])),
                        claim_ids,
                        claims_by_id,
                    ),
                    plan,
                )
                if score_value is None:
                    continue
                score = score_value
            theme_candidates.append((score, str(row["theme_id"]), row, claim_ids))

        connection_candidates.sort(key=lambda item: (-item[0], item[1]))
        theme_candidates.sort(key=lambda item: (-item[0], item[1]))
        selected_connections = connection_candidates[:limit]
        selected_themes = theme_candidates[:limit]

        connection_outputs = []
        selected_claim_ids: set[str] = set()
        for score, _, row, claim_ids in selected_connections:
            selected_claim_ids.update(claim_ids)
            connection_outputs.append(
                {
                    "connection_id": row["connection_id"],
                    "type": row["connection_type"],
                    "confidence": row["confidence"],
                    "summary": row["summary"],
                    "explanation": row["explanation"],
                    "claim_ids": claim_ids,
                    "claims": _graph_claims_for_ids(claim_ids, claims_by_id),
                    "match_score": score,
                }
            )

        theme_outputs = []
        for score, _, row, claim_ids in selected_themes:
            selected_claim_ids.update(claim_ids)
            theme_outputs.append(
                {
                    "theme_id": row["theme_id"],
                    "label": row["label"],
                    "summary": row["summary"],
                    "claim_ids": claim_ids,
                    "claims": _graph_claims_for_ids(claim_ids, claims_by_id),
                    "match_score": score,
                }
            )

        if claim_id is not None:
            selected_claim_ids.add(claim_id)
        linked_claims = _graph_claims_for_ids(
            sorted(selected_claim_ids), claims_by_id
        )
        base_payload.update(
            {
                "connections": connection_outputs,
                "themes": theme_outputs,
                "claims": linked_claims,
                "result_count": len(connection_outputs) + len(theme_outputs),
                "connection_count": len(connection_outputs),
                "theme_count": len(theme_outputs),
                "claim_count": len(linked_claims),
            }
        )
        return base_payload
    finally:
        conn.close()


def load_search_vocabulary(
    index_path: Path,
    source: str,
    book_filter: str | None = None,
    title_filter: str | None = None,
) -> dict[str, dict[str, int]]:
    """Load normalized corpus terms and their occurrence counts.

    New indexes contain a compact term table. Older indexes are supported by a
    deterministic passage scan, which keeps the fuzzy command usable before an
    index rebuild.
    """

    validate_source(source)

    conn = connect_read_only(index_path)
    try:
        vocabulary: dict[str, dict[str, int]] = {}
        can_use_term_table = not book_filter and not title_filter
        if can_use_term_table:
            source_where, source_params = source_where_clause(source)
            source_clause = f" WHERE {source_where}" if source_where else ""
            params: list[object] = list(source_params)
            try:
                rows = conn.execute(
                    "SELECT term, document_frequency, term_frequency "
                    "FROM search_terms" + source_clause,
                    params,
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    raise
            else:
                for row in rows:
                    entry = vocabulary.setdefault(
                        str(row["term"]),
                        {"document_frequency": 0, "term_frequency": 0},
                    )
                    entry["document_frequency"] += int(row["document_frequency"])
                    entry["term_frequency"] += int(row["term_frequency"])
                return vocabulary

        source_where, source_params = source_where_clause(source)
        clauses: list[str] = [source_where] if source_where else []
        params = list(source_params)
        if book_filter:
            clauses.append("normalized_book LIKE ?")
            params.append(f"%{normalize(book_filter)}%")
        if title_filter:
            clauses.append("normalized_title LIKE ?")
            params.append(f"%{normalize(title_filter)}%")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            "SELECT source, normalized_title, normalized_book, normalized_text "
            "FROM passages" + where,
            params,
        )
        for row in rows:
            fields = " ".join(
                (
                    str(row["normalized_title"]),
                    str(row["normalized_book"]),
                    str(row["normalized_text"]),
                )
            )
            counts = Counter(tokenize(fields))
            for term, frequency in counts.items():
                entry = vocabulary.setdefault(
                    term,
                    {"document_frequency": 0, "term_frequency": 0},
                )
                entry["document_frequency"] += 1
                entry["term_frequency"] += frequency
        return vocabulary
    finally:
        conn.close()


def _levenshtein_distance(
    left: str,
    right: str,
    max_distance: int | None = None,
) -> int:
    """Return the edit distance between two normalized terms."""

    if left == right:
        return 0
    if max_distance is not None and abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _adaptive_fuzzy_distance(term: str) -> int:
    length = len(term)
    if length <= 5:
        return 1
    if length <= 10:
        return 2
    if length <= 16:
        return 3
    return 4


def fuzzy_term_matches(
    term: str,
    vocabulary: dict[str, dict[str, int]],
    *,
    limit: int = DEFAULT_FUZZY_PER_TOKEN_LIMIT,
    max_distance: int | None = DEFAULT_FUZZY_MAX_DISTANCE,
) -> list[dict[str, object]]:
    """Find likely corpus terms for one misspelled query token."""

    normalized_term = normalize(term)
    if len(normalized_term) < MIN_FUZZY_TOKEN_LENGTH:
        return []
    if normalized_term in vocabulary:
        return []
    if limit < 1 or limit > 10:
        raise BabaSearchError("fuzzy per-token limit must be between 1 and 10")
    allowed_distance = (
        max_distance
        if max_distance is not None
        else _adaptive_fuzzy_distance(normalized_term)
    )
    if allowed_distance < 1 or allowed_distance > 8:
        raise BabaSearchError("fuzzy max distance must be between 1 and 8")

    matches: list[dict[str, object]] = []
    for candidate, counts in vocabulary.items():
        if len(candidate) < MIN_FUZZY_TOKEN_LENGTH:
            continue
        if abs(len(candidate) - len(normalized_term)) > allowed_distance:
            continue
        distance = _levenshtein_distance(
            normalized_term,
            candidate,
            max_distance=allowed_distance,
        )
        if distance > allowed_distance:
            continue
        similarity = SequenceMatcher(None, normalized_term, candidate).ratio()
        matches.append(
            {
                "term": candidate,
                "distance": distance,
                "similarity": round(similarity, 4),
                "document_frequency": counts["document_frequency"],
                "term_frequency": counts["term_frequency"],
            }
        )

    matches.sort(
        key=lambda item: (
            int(item["distance"]),
            -float(item["similarity"]),
            -int(item["document_frequency"]),
            -int(item["term_frequency"]),
            str(item["term"]),
        )
    )
    return matches[:limit]


def _query_token_spans(raw_query: str) -> list[tuple[int, int, str, str]]:
    return [
        (match.start(), match.end(), match.group(0), normalize(match.group(0)))
        for match in RAW_TOKEN_RE.finditer(raw_query)
    ]


def _replace_query_tokens(
    raw_query: str,
    spans: Sequence[tuple[int, int, str, str]],
    replacements: Sequence[str],
) -> str:
    pieces: list[str] = []
    cursor = 0
    for (start, end, _, _), replacement in zip(spans, replacements):
        pieces.append(raw_query[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(raw_query[cursor:])
    return "".join(pieces)


def _fuzzy_query_variants(
    raw_query: str,
    vocabulary: dict[str, dict[str, int]],
    *,
    per_token_limit: int,
    max_distance: int | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    spans = _query_token_spans(raw_query)
    options: list[list[str]] = []
    suggestions: list[dict[str, object]] = []
    seen_unknown_tokens: set[str] = set()

    for _, _, raw_token, normalized_token in spans:
        matches = fuzzy_term_matches(
            raw_token,
            vocabulary,
            limit=per_token_limit,
            max_distance=max_distance,
        )
        if not matches:
            options.append([raw_token])
            continue
        options.append([str(match["term"]) for match in matches])
        if normalized_token not in seen_unknown_tokens:
            suggestions.append(
                {
                    "input_token": raw_token,
                    "normalized_input": normalized_token,
                    "matches": matches,
                }
            )
            seen_unknown_tokens.add(normalized_token)

    expanded_queries: list[dict[str, object]] = []
    seen_queries = {_canonical_query_key(raw_query)}
    for replacements in product(*options) if options else ():
        if all(
            replacement == span[2]
            for replacement, span in zip(replacements, spans)
        ):
            continue
        query = _replace_query_tokens(raw_query, spans, replacements)
        query_key = _canonical_query_key(query)
        if query_key in seen_queries:
            continue
        seen_queries.add(query_key)
        substitutions = [
            {
                "from": span[2],
                "to": replacement,
            }
            for replacement, span in zip(replacements, spans)
            if replacement != span[2]
        ]
        expanded_queries.append(
            {
                "query": query,
                "substitutions": substitutions,
            }
        )
        if len(expanded_queries) >= MAX_FUZZY_QUERY_VARIANTS:
            break
    return suggestions, expanded_queries


def fuzzy_search(
    index_path: Path,
    source: str,
    raw_query: str,
    limit: int = DEFAULT_LIMIT,
    per_query_limit: int = DEFAULT_PER_QUERY_LIMIT,
    context: int = DEFAULT_CONTEXT,
    book_filter: str | None = None,
    title_filter: str | None = None,
    max_per_document: int = DEFAULT_MAX_PER_DOCUMENT,
    per_token_limit: int = DEFAULT_FUZZY_PER_TOKEN_LIMIT,
    max_distance: int | None = DEFAULT_FUZZY_MAX_DISTANCE,
) -> dict[str, object]:
    """Search passages after proposing close spellings for unknown tokens."""

    if per_token_limit < 1 or per_token_limit > 10:
        raise BabaSearchError("fuzzy per-token limit must be between 1 and 10")
    if max_distance is not None and (max_distance < 1 or max_distance > 8):
        raise BabaSearchError("fuzzy max distance must be between 1 and 8")

    vocabulary = load_search_vocabulary(
        index_path,
        source,
        book_filter=book_filter,
        title_filter=title_filter,
    )
    suggestions, expanded_queries = _fuzzy_query_variants(
        raw_query,
        vocabulary,
        per_token_limit=per_token_limit,
        max_distance=max_distance,
    )
    queries = [raw_query] + [
        str(expanded["query"]) for expanded in expanded_queries
    ]
    payload = aggregate_search(
        index_path,
        source,
        queries,
        limit=limit,
        per_query_limit=per_query_limit,
        context=context,
        book_filter=book_filter,
        title_filter=title_filter,
        max_per_document=max_per_document,
    )
    payload.update(
        {
            "command": "fuzzy",
            "query": raw_query,
            "fuzzy_per_token_limit": per_token_limit,
            "fuzzy_max_distance": max_distance,
            "suggestions": suggestions,
            "expanded_queries": expanded_queries,
        }
    )
    return payload


def _canonical_query_key(raw_query: str) -> str:
    return normalize(normalize_whitespace(raw_query))


def _aggregate_passage_key(result: dict[str, object]) -> tuple[str, ...]:
    passage_id = result.get("passage_id")
    if passage_id is not None:
        return ("passage", str(passage_id))
    return (
        str(result.get("source", "")),
        str(result.get("file", "")),
        str(result.get("anchor", "")),
        normalize(str(result.get("snippet", ""))),
    )


def aggregate_search(
    index_path: Path,
    source: str,
    queries: Sequence[str],
    limit: int = DEFAULT_LIMIT,
    per_query_limit: int = DEFAULT_PER_QUERY_LIMIT,
    context: int = DEFAULT_CONTEXT,
    book_filter: str | None = None,
    title_filter: str | None = None,
    max_per_document: int = DEFAULT_MAX_PER_DOCUMENT,
) -> dict[str, object]:
    """Run a bounded lexical fan-out and merge identical passages.

    Each query is searched independently, so a phrase or synonym that does
    not co-occur with the wording of another query can still contribute a
    passage.  The merge uses the stable local passage id, records which query
    variants found each passage, and optionally limits passages per document
    to keep the final result set diverse.
    """

    validate_source(source)
    if limit < 1 or limit > MAX_LIMIT:
        raise BabaSearchError(f"limit must be between 1 and {MAX_LIMIT}")
    if per_query_limit < 1 or per_query_limit > MAX_LIMIT:
        raise BabaSearchError(
            f"per-query-limit must be between 1 and {MAX_LIMIT}"
        )
    if context < 0:
        raise BabaSearchError("context must be zero or greater")
    if max_per_document < 0:
        raise BabaSearchError("max-per-document must be zero or greater")

    unique_queries: list[str] = []
    seen_queries: set[str] = set()
    for query in queries:
        if not normalize_whitespace(query):
            raise BabaSearchError("Each aggregate query must contain text")
        query_key = _canonical_query_key(query)
        if query_key in seen_queries:
            continue
        seen_queries.add(query_key)
        unique_queries.append(query)
    if not unique_queries:
        raise BabaSearchError("At least one --query is required")
    if len(unique_queries) > MAX_AGGREGATE_QUERIES:
        raise BabaSearchError(
            f"At most {MAX_AGGREGATE_QUERIES} unique aggregate queries are allowed"
        )

    candidates: dict[tuple[str, ...], dict[str, object]] = {}
    query_runs: list[dict[str, object]] = []
    index_mode = "scan"

    for query in unique_queries:
        payload = search_index(
            index_path,
            source,
            query,
            limit=per_query_limit,
            context=context,
            book_filter=book_filter,
            title_filter=title_filter,
        )
        index_mode = str(payload["index_mode"])
        run_results = payload["results"]
        query_runs.append(
            {
                "query": query,
                "result_count": int(payload["result_count"]),
                "top_citations": [
                    str(result["citation"])
                    for result in run_results[:3]  # type: ignore[index]
                ],
            }
        )
        for result_value in run_results:  # type: ignore[union-attr]
            result = dict(result_value)
            key = _aggregate_passage_key(result)
            rank = int(result["rank"])
            score = int(result["score"])
            evidence = {
                "query": query,
                "rank": rank,
                "score": score,
            }
            entry = candidates.get(key)
            if entry is None:
                candidates[key] = {
                    "best_result": result,
                    "best_rank": rank,
                    "best_score": score,
                    "matched_queries": [query],
                    "query_evidence": [evidence],
                    "rrf_score": 100_000 / (60 + rank),
                }
                continue

            matched_queries = entry["matched_queries"]
            query_evidence = entry["query_evidence"]
            matched_queries.append(query)  # type: ignore[union-attr]
            query_evidence.append(evidence)  # type: ignore[union-attr]
            entry["rrf_score"] = float(entry["rrf_score"]) + (
                100_000 / (60 + rank)
            )
            if (score, -rank) > (
                int(entry["best_score"]),
                -int(entry["best_rank"]),
            ):
                entry["best_result"] = result
                entry["best_rank"] = rank
                entry["best_score"] = score

    ranked_candidates: list[dict[str, object]] = []
    for entry in candidates.values():
        result = dict(entry["best_result"])  # type: ignore[arg-type]
        matched_queries = list(entry["matched_queries"])  # type: ignore[arg-type]
        query_evidence = list(entry["query_evidence"])  # type: ignore[arg-type]
        query_hits = len(matched_queries)
        aggregate_score = (
            query_hits * 1_000_000
            + int(round(float(entry["rrf_score"])))
            + int(entry["best_score"])
        )
        document_key = f"{result['source']}:{result['file']}"
        result.update(
            {
                "query_hits": query_hits,
                "matched_queries": matched_queries,
                "query_evidence": query_evidence,
                "best_rank": int(entry["best_rank"]),
                "best_score": int(entry["best_score"]),
                "aggregate_score": aggregate_score,
                "document_key": document_key,
            }
        )
        result["_sort_path"] = str(result["file"]).casefold()
        result["_sort_anchor"] = _natural_anchor_key(str(result["anchor"]))
        ranked_candidates.append(result)

    ranked_candidates.sort(
        key=lambda item: (
            -int(item["aggregate_score"]),
            -int(item["query_hits"]),
            -int(item["best_rank"]),
            str(item["_sort_path"]),
            item["_sort_anchor"],
            int(item["passage_id"]),
        )
    )

    selected: list[dict[str, object]] = []
    document_counts: dict[str, int] = {}
    for result in ranked_candidates:
        document_key = str(result["document_key"])
        if (
            max_per_document
            and document_counts.get(document_key, 0) >= max_per_document
        ):
            continue
        document_counts[document_key] = document_counts.get(document_key, 0) + 1
        selected.append(result)
        if len(selected) >= limit:
            break

    public_results: list[dict[str, object]] = []
    for rank, result in enumerate(selected, start=1):
        result["rank"] = rank
        public_results.append(
            {
                key: value
                for key, value in result.items()
                if not key.startswith("_")
            }
        )

    return {
        "queries": unique_queries,
        "query_count": len(unique_queries),
        "source": source,
        "book": book_filter,
        "title": title_filter,
        "limit": limit,
        "per_query_limit": per_query_limit,
        "max_per_document": max_per_document,
        "context": context,
        "index_mode": index_mode,
        "candidate_count": len(ranked_candidates),
        "distinct_documents": len(document_counts),
        "query_runs": query_runs,
        "result_count": len(public_results),
        "results": public_results,
    }


def print_human_search(payload: dict[str, object]) -> None:
    results = payload["results"]
    if not results:
        print("No matches.")
        return
    print(
        f"{payload['result_count']} result(s) for {payload['query']!r} "
        f"in {payload['source']}"
    )
    for result in results:  # type: ignore[union-attr]
        book = f" | {result['book']}" if result["book"] else ""
        print(
            f"\n{result['rank']}. [{result['source']}] {result['title']}{book} "
            f"(score {result['score']})"
        )
        print(f"   {result['citation']}")
        print(f"   {result['snippet']}")


def print_human_aggregate(payload: dict[str, object]) -> None:
    results = payload["results"]
    print(
        f"{payload['result_count']} aggregate result(s) from "
        f"{payload['query_count']} query variant(s) in {payload['source']}"
    )
    if not results:
        print("No matches.")
        return
    for result in results:  # type: ignore[union-attr]
        book = f" | {result['book']}" if result["book"] else ""
        matched_queries = ", ".join(result["matched_queries"])  # type: ignore[arg-type]
        print(
            f"\n{result['rank']}. [{result['source']}] {result['title']}{book} "
            f"(aggregate score {result['aggregate_score']}; "
            f"{result['query_hits']} query hit(s))"
        )
        print(f"   {result['citation']}")
        print(f"   Found by: {matched_queries}")
        print(f"   {result['snippet']}")


def print_human_fuzzy(payload: dict[str, object]) -> None:
    suggestions = payload.get("suggestions", [])
    if suggestions:
        print(f"Likely corpus spellings for {payload['query']!r}:")
        for suggestion in suggestions:  # type: ignore[union-attr]
            input_token = suggestion["input_token"]
            matches = suggestion["matches"]
            formatted = ", ".join(
                f"{match['term']} (distance {match['distance']})"
                for match in matches
            )
            print(f"  {input_token}: {formatted}")
    else:
        print(f"No fuzzy spelling suggestions for {payload['query']!r}.")

    results = payload["results"]
    if not results:
        print("No matches.")
        return
    print(
        f"\n{payload['result_count']} fuzzy result(s) from "
        f"{payload['query_count']} query variant(s) in {payload['source']}"
    )
    for result in results:  # type: ignore[union-attr]
        book = f" | {result['book']}" if result["book"] else ""
        matched_queries = ", ".join(result["matched_queries"])
        print(
            f"\n{result['rank']}. [{result['source']}] {result['title']}{book} "
            f"(aggregate score {result['aggregate_score']}; "
            f"{result['query_hits']} query hit(s))"
        )
        print(f"   {result['citation']}")
        print(f"   Found by: {matched_queries}")
        print(f"   {result['snippet']}")


def print_human_stats(payload: dict[str, object]) -> None:
    print(f"Index: {payload['index_path']}")
    print(f"Mode: {payload['index_mode']} (FTS5 present: {payload['fts5_present']})")
    print(f"Size: {payload['index_bytes']} bytes")
    print(f"Passages: {payload['passages']}")
    print(f"Characters: {payload['characters']}")
    sources = payload["sources"]
    for source in CORPUS_SOURCES:
        details = sources[source]  # type: ignore[index]
        print(
            f"{source}: {details['files_seen']} files seen, "
            f"{details['documents']} documents, {details['passages']} passages"
        )
    graph = payload.get("graph")
    if isinstance(graph, dict):
        print(
            "Graph: "
            f"{graph['status']} ({graph['claims']} claims, "
            f"{graph['connections']} connections, {graph['themes']} themes)"
        )


def _short_glossary_evidence(candidate: dict[str, object]) -> str:
    evidence = candidate.get("evidence_contexts")
    if not isinstance(evidence, list) or not evidence:
        return ""
    first = evidence[0]
    if not isinstance(first, dict):
        return ""
    title = str(first.get("title", "")).strip()
    context = normalize_whitespace(str(first.get("context", "")))
    if len(context) > 180:
        context = context[:177].rstrip() + "..."
    if title and context:
        return f"{title}: {context}"
    return title or context


def print_human_glossary(payload: dict[str, object]) -> None:
    results = payload["results"]
    operation = payload["operation"]
    query_key = "term" if operation == "lookup" else "query"
    query = payload[query_key]
    if not results:
        print(f"No glossary matches for {query!r}.")
        return
    print(f"{payload['result_count']} glossary match(es) for {query!r}")
    for rank, candidate in enumerate(results, start=1):  # type: ignore[union-attr]
        canonical = str(candidate.get("canonical_surface_form", ""))
        normalized = str(candidate.get("normalized_form", ""))
        print(f"\n{rank}. {canonical} [{normalized}]")
        variants = candidate.get("variants")
        if isinstance(variants, list) and variants:
            print(f"   Variants: {', '.join(str(item) for item in variants)}")
        reasons = candidate.get("reason_codes")
        if isinstance(reasons, list) and reasons:
            print(f"   Reasons: {', '.join(str(item) for item in reasons)}")
        evidence = _short_glossary_evidence(candidate)
        if evidence:
            print(f"   Evidence: {evidence}")


def print_human_connections(payload: dict[str, object]) -> None:
    if payload.get("graph_status") not in {"indexed", "claims-only"}:
        print(f"Graph is {payload.get('graph_status', 'unavailable')}.")
        return
    print(
        f"{payload['connection_count']} connection(s), "
        f"{payload['theme_count']} theme(s) for "
        f"{payload.get('query') or payload.get('claim_id')!r}"
    )
    for connection in payload["connections"]:  # type: ignore[union-attr]
        print(
            f"\n{connection['connection_id']} "
            f"[{connection['type']}, {connection['confidence']}]"
        )
        print(f"   {connection['summary']}")
        print(f"   {connection['explanation']}")
        for claim in connection["claims"][:3]:
            print(f"   - {claim['citation']}: {claim['statement']}")
    for theme in payload["themes"]:  # type: ignore[union-attr]
        print(f"\n{theme['theme_id']} {theme['label']}")
        print(f"   {theme['summary']}")
        for claim in theme["claims"][:3]:
            print(f"   - {claim['citation']}: {claim['statement']}")


def add_index_path_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--index",
        "--index-path",
        dest="index_path",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help=f"SQLite index path (default: {DEFAULT_INDEX_PATH})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="baba-search",
        description=(
            "Read-only lexical search over discourses, Baba stories, other "
            "spiritual books, and Ananda Marga Acharya philosophy."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser(
        "index", aliases=["build"], help="Build or rebuild the local search index"
    )
    add_index_path_argument(index_parser)
    index_parser.add_argument(
        "--discourse-root",
        "--discourses",
        dest="discourse_root",
        type=Path,
        help="Read-only HTML/Discourses source directory",
    )
    index_parser.add_argument(
        "--stories-root",
        "--stories",
        dest="stories_root",
        type=Path,
        help="Read-only OCR Markdown story directory",
    )
    index_parser.add_argument(
        "--other-spiritual-books-root",
        "--other-books",
        dest="other_spiritual_books_root",
        type=Path,
        help="Read-only Markdown directory for non-Ananda Marga spiritual books",
    )
    index_parser.add_argument(
        "--acharya-philosophy-root",
        "--acharya-philosophy",
        dest="acharya_philosophy_root",
        type=Path,
        help="Read-only Markdown directory for Ananda Marga Acharya philosophy",
    )
    index_parser.add_argument(
        "--connections-root",
        "--graph-root",
        dest="connections_root",
        type=Path,
        help=(
            "Optional Gemini graph artifact directory; defaults to the current "
            f"full-corpus artifact when present ({DEFAULT_CONNECTIONS_ROOT})"
        ),
    )
    index_parser.add_argument(
        "--no-fts5",
        action="store_true",
        help="Force the deterministic Python scan fallback",
    )
    index_parser.add_argument("--json", action="store_true", help="Emit JSON")

    search_parser = subparsers.add_parser("search", help="Search indexed passages")
    add_index_path_argument(search_parser)
    search_parser.add_argument(
        "--source",
        type=source_scope_argument,
        default="default",
        metavar="SCOPE",
        help="Corpus scope: one category, default, all, or categories joined with + (default: default)",
    )
    search_parser.add_argument("--query", required=True, help="Search text; quote phrases")
    search_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum results (default: {DEFAULT_LIMIT})"
    )
    search_parser.add_argument(
        "--context",
        type=int,
        default=DEFAULT_CONTEXT,
        help=f"Snippet context in characters (default: {DEFAULT_CONTEXT})",
    )
    search_parser.add_argument(
        "--book",
        "--book-title",
        dest="book",
        help="Case and diacritic-insensitive substring filter for the book",
    )
    search_parser.add_argument(
        "--title", help="Case and diacritic-insensitive substring filter for the title"
    )
    search_parser.add_argument("--json", action="store_true", help="Emit JSON")

    passage_parser = subparsers.add_parser(
        "passage", help="Read one indexed source passage with nearby context"
    )
    add_index_path_argument(passage_parser)
    passage_parser.add_argument(
        "--citation",
        required=True,
        help="Exact citation such as Discourses/File.html#3 or Other-Spiritual-Books/File.md#section-1/chunk-1",
    )
    passage_parser.add_argument(
        "--context-passages",
        type=int,
        default=4,
        help="Nearby passages to include on each side (default: 4)",
    )
    passage_parser.add_argument("--json", action="store_true", help="Emit JSON")

    fuzzy_parser = subparsers.add_parser(
        "fuzzy",
        help="Find close corpus spellings and search with the likely corrections",
    )
    add_index_path_argument(fuzzy_parser)
    fuzzy_parser.add_argument(
        "--source",
        type=source_scope_argument,
        default="default",
        metavar="SCOPE",
        help="Corpus scope: one category, default, all, or categories joined with + (default: default)",
    )
    fuzzy_parser.add_argument(
        "--query",
        required=True,
        help="Original search text, including an optional quoted phrase",
    )
    fuzzy_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum results (default: {DEFAULT_LIMIT})"
    )
    fuzzy_parser.add_argument(
        "--per-query-limit",
        type=int,
        default=DEFAULT_PER_QUERY_LIMIT,
        help=f"Results retained from each fuzzy query (default: {DEFAULT_PER_QUERY_LIMIT})",
    )
    fuzzy_parser.add_argument(
        "--max-per-document",
        type=int,
        default=DEFAULT_MAX_PER_DOCUMENT,
        help="Maximum merged passages per source document; 0 means unlimited (default: 1)",
    )
    fuzzy_parser.add_argument(
        "--per-token-limit",
        type=int,
        default=DEFAULT_FUZZY_PER_TOKEN_LIMIT,
        help=f"Likely spellings retained per unknown token (default: {DEFAULT_FUZZY_PER_TOKEN_LIMIT})",
    )
    fuzzy_parser.add_argument(
        "--max-distance",
        type=int,
        default=DEFAULT_FUZZY_MAX_DISTANCE,
        help="Maximum spelling edit distance; adaptive by word length by default",
    )
    fuzzy_parser.add_argument(
        "--context",
        type=int,
        default=DEFAULT_CONTEXT,
        help=f"Snippet context in characters (default: {DEFAULT_CONTEXT})",
    )
    fuzzy_parser.add_argument(
        "--book",
        "--book-title",
        dest="book",
        help="Case and diacritic-insensitive substring filter for the book",
    )
    fuzzy_parser.add_argument(
        "--title", help="Case and diacritic-insensitive substring filter for the title"
    )
    fuzzy_parser.add_argument("--json", action="store_true", help="Emit JSON")

    aggregate_parser = subparsers.add_parser(
        "aggregate",
        aliases=["search-many"],
        help="Run multiple lexical queries and merge their passage results",
    )
    add_index_path_argument(aggregate_parser)
    aggregate_parser.add_argument(
        "--source",
        type=source_scope_argument,
        default="default",
        metavar="SCOPE",
        help="Corpus scope: one category, default, all, or categories joined with + (default: default)",
    )
    aggregate_parser.add_argument(
        "--query",
        action="append",
        required=True,
        help="Search variant; repeat this option for fan-out queries",
    )
    aggregate_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum merged results (default: {DEFAULT_LIMIT})"
    )
    aggregate_parser.add_argument(
        "--per-query-limit",
        type=int,
        default=DEFAULT_PER_QUERY_LIMIT,
        help=f"Results retained from each query (default: {DEFAULT_PER_QUERY_LIMIT})",
    )
    aggregate_parser.add_argument(
        "--max-per-document",
        type=int,
        default=DEFAULT_MAX_PER_DOCUMENT,
        help="Maximum merged passages per source document; 0 means unlimited (default: 1)",
    )
    aggregate_parser.add_argument(
        "--context",
        type=int,
        default=DEFAULT_CONTEXT,
        help=f"Snippet context in characters (default: {DEFAULT_CONTEXT})",
    )
    aggregate_parser.add_argument(
        "--book",
        "--book-title",
        dest="book",
        help="Case and diacritic-insensitive substring filter for the book",
    )
    aggregate_parser.add_argument(
        "--title", help="Case and diacritic-insensitive substring filter for the title"
    )
    aggregate_parser.add_argument("--json", action="store_true", help="Emit JSON")

    stats_parser = subparsers.add_parser("stats", help="Show index statistics")
    add_index_path_argument(stats_parser)
    stats_parser.add_argument("--json", action="store_true", help="Emit JSON")

    connections_parser = subparsers.add_parser(
        "connections",
        help="Retrieve Gemini graph relationships and themes",
    )
    add_index_path_argument(connections_parser)
    connections_parser.add_argument(
        "--source",
        type=source_scope_argument,
        default=DEFAULT_CONNECTIONS_SOURCE,
        metavar="SCOPE",
        help=(
            "Filter by source category, default, all, or categories joined with + "
            f"(default: {DEFAULT_CONNECTIONS_SOURCE})"
        ),
    )
    connections_parser.add_argument(
        "--query",
        help="Search connection and theme text, including linked claim statements",
    )
    connections_parser.add_argument(
        "--claim-id",
        help="Return one exact stable claim and its related connections and themes",
    )
    connections_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum connections and themes returned in each section (default: {DEFAULT_LIMIT})",
    )
    connections_parser.add_argument("--json", action="store_true", help="Emit JSON")

    glossary_parser = subparsers.add_parser(
        "glossary", help="Look up and search glossary candidate terms"
    )
    glossary_subparsers = glossary_parser.add_subparsers(
        dest="glossary_command", required=True
    )

    def add_glossary_arguments(
        command_parser: argparse.ArgumentParser, value_name: str
    ) -> None:
        command_parser.add_argument(
            "--glossary",
            type=Path,
            default=DEFAULT_GLOSSARY_PATH,
            help=f"Glossary JSON path (default: {DEFAULT_GLOSSARY_PATH})",
        )
        command_parser.add_argument(
            value_name,
            required=True,
            help=f"Glossary {value_name} to match",
        )
        command_parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Maximum results (default: {DEFAULT_LIMIT})",
        )
        command_parser.add_argument("--json", action="store_true", help="Emit JSON")

    glossary_lookup_parser = glossary_subparsers.add_parser(
        "lookup", help="Find an exact canonical, variant, or normalized term"
    )
    add_glossary_arguments(glossary_lookup_parser, "--term")

    glossary_search_parser = glossary_subparsers.add_parser(
        "search", help="Search glossary terms by phrase and token matches"
    )
    add_glossary_arguments(glossary_search_parser, "--query")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"index", "build"}:
            discourse_root = resolve_discourse_root(args.discourse_root)
            stories_root = resolve_stories_root(args.stories_root)
            other_spiritual_books_root = resolve_other_spiritual_books_root(
                args.other_spiritual_books_root
            )
            acharya_philosophy_root = resolve_acharya_philosophy_root(
                args.acharya_philosophy_root
            )
            connections_root = resolve_connections_root(args.connections_root)
            payload = build_index(
                args.index_path,
                discourse_root,
                stories_root,
                force_fts5=False if args.no_fts5 else None,
                other_spiritual_books_root=other_spiritual_books_root,
                acharya_philosophy_root=acharya_philosophy_root,
                connections_root=connections_root,
            )
            if args.json:
                print(json.dumps({"command": "index", "stats": payload}, ensure_ascii=False))
            else:
                print_human_stats(payload)
            return 0
        if args.command == "stats":
            payload = stats(args.index_path)
            if args.json:
                print(json.dumps({"command": "stats", "stats": payload}, ensure_ascii=False))
            else:
                print_human_stats(payload)
            return 0
        if args.command == "connections":
            payload = connections_lookup(
                args.index_path,
                args.source,
                query=args.query,
                claim_id=args.claim_id,
                limit=args.limit,
            )
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print_human_connections(payload)
            return 0
        if args.command == "search":
            payload = search_index(
                args.index_path,
                args.source,
                args.query,
                limit=args.limit,
                context=args.context,
                book_filter=args.book,
                title_filter=args.title,
            )
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print_human_search(payload)
            return 0
        if args.command == "passage":
            payload = passage_by_citation(
                args.index_path,
                args.citation,
                context_passages=args.context_passages,
            )
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print(f"{payload['title']}\n{payload['citation']}\n\n{payload['text']}")
            return 0
        if args.command == "fuzzy":
            payload = fuzzy_search(
                args.index_path,
                args.source,
                args.query,
                limit=args.limit,
                per_query_limit=args.per_query_limit,
                context=args.context,
                book_filter=args.book,
                title_filter=args.title,
                max_per_document=args.max_per_document,
                per_token_limit=args.per_token_limit,
                max_distance=args.max_distance,
            )
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print_human_fuzzy(payload)
            return 0
        if args.command in {"aggregate", "search-many"}:
            payload = aggregate_search(
                args.index_path,
                args.source,
                args.query,
                limit=args.limit,
                per_query_limit=args.per_query_limit,
                context=args.context,
                book_filter=args.book,
                title_filter=args.title,
                max_per_document=args.max_per_document,
            )
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print_human_aggregate(payload)
            return 0
        if args.command == "glossary":
            if args.glossary_command == "lookup":
                payload = glossary_lookup(
                    args.glossary, args.term, limit=args.limit
                )
            elif args.glossary_command == "search":
                payload = glossary_search(
                    args.glossary, args.query, limit=args.limit
                )
            else:
                parser.error(f"Unknown glossary command: {args.glossary_command}")
            if args.json:
                print(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            else:
                print_human_glossary(payload)
            return 0
        parser.error(f"Unknown command: {args.command}")
    except BabaSearchError as exc:
        print(f"baba-search: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as exc:
        print(f"baba-search: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
