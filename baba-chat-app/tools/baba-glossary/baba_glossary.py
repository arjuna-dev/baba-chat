#!/usr/bin/env python3
"""Deterministic glossary-candidate discovery for COMPLETE_SARKAR HTML.

This module deliberately does not call a language model and does not infer
definitions. It records evidence that a surface form may be specialized so a
later, human-reviewed normalization step can decide what belongs in a search
glossary.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

import xml.etree.ElementTree as ET


APP_ROOT = Path(__file__).resolve().parents[2]
SEARCH_MODULE_PATH = APP_ROOT / "tools" / "baba-search" / "baba_search.py"
DEFAULT_DICTIONARY_URL = (
    "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
)
DEFAULT_COCA_URL = "https://www.wordfrequency.info/samples/lemmas_60k_words.txt"
DEFAULT_WORDFREQ_LANGUAGE = "en"
DEFAULT_WORDFREQ_THRESHOLD = 2.5
DEFAULT_WORDFREQ_DERIVATIONAL_THRESHOLD = 2.0
MIN_DERIVATIONAL_SOURCE_SCORE = 1.0
DEFAULT_MAX_EVIDENCE = 4
MIN_HIGHLIGHT_TOKENS = 1
MAX_HIGHLIGHT_TOKENS = 8
MAX_MIXED_ANNOTATED_PHRASE_TOKENS = 4
MAX_CONTEXT_CHARS = 480

TOKEN_RE = re.compile(
    r"[^\W_\u0300-\u036f]+(?:[\u0300-\u036f]+[^\W_\u0300-\u036f]*)*"
    r"(?:[’'][^\W_\u0300-\u036f]+(?:[\u0300-\u036f]+[^\W_\u0300-\u036f]*)*)?",
    re.UNICODE,
)
RAW_PARAGRAPH_RE = re.compile(
    r"<!--\s*block\s+a=([^\s]+)\s+type=paragraph\s*-->(.*?)"
    r"<!--\s*/block\s*-->",
    flags=re.IGNORECASE | re.DOTALL,
)
ITALIC_RE = re.compile(
    r"<(?:i|em)\b[^>]*>(.*?)</(?:i|em)\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
DOUBLE_QUOTE_RE = re.compile(r'["“](?P<body>[^"”\n]{1,240})["”]')
SINGLE_QUOTE_RE = re.compile(
    r"(?<![\w])['‘](?P<body>[^'’\n]{1,240})['’](?![\w])"
)
DEFINITION_CUE_RE = re.compile(
    r"\b(?:means?|refers?\s+to|is\s+(?:called|known\s+as|defined\s+as)|"
    r"are\s+(?:called|known\s+as)|also\s+known\s+as|denotes?|meaning)\b",
    flags=re.IGNORECASE,
)
WORDLIKE_RE = re.compile(r"[^\W_]+", re.UNICODE)

# This is intentionally small. It is a deterministic no-network fallback,
# not an attempt to ship an English dictionary. Users who need broad coverage
# should pass --dictionary or explicitly opt in to --download-dictionary.
BUILTIN_MINIMAL_ENGLISH_WORDS = frozenset(
    """
    a about above after again against all also am an and any are around as at
    be because been before being below between both but by called can could did
    do does doing down each for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just keep known
    like made make many may me means might more most my myself no nor not now of
    on once only or other our ours ourselves out over own same see she should so
    some such than that the their theirs them themselves then there these they
    this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours yourself yourselves
    word words term terms text language english hindu hinduism sanskrit story
    stories discourse discourses book books practice practices life called
    definition means meaning refers known name names person people place future
    present past physical mental psychic mind body creator object human humans
    create created creating manufacture manufactured manufacturing science
    source passage paragraph quote quoted page pages chapter section part
    between into from about says said say spoke speaking referred using use used
    """.split()
)

REASON_WEIGHTS = {
    "definition_context": 6,
    "multiword_non_english": 5,
    "quoted": 4,
    "italic": 4,
    "not_in_english_baseline": 2,
}

DEFINITION_SUBJECT_STOPWORDS = frozenset(
    "a an and also as called definition defined form from in is its known meaning "
    "means name of one or practice refers term the this to word words".split()
)
DEFINITION_BRIDGING_WORDS = frozenset({"are", "is", "was", "were"})

COMMON_IRREGULAR_ENGLISH_BASES = {
    "are": "be",
    "been": "be",
    "being": "be",
    "children": "child",
    "did": "do",
    "does": "do",
    "feet": "foot",
    "geese": "goose",
    "has": "have",
    "having": "have",
    "is": "be",
    "men": "man",
    "mice": "mouse",
    "people": "person",
    "teeth": "tooth",
    "was": "be",
    "women": "woman",
    "were": "be",
}


class GlossaryError(RuntimeError):
    """A user-facing glossary CLI error."""


@dataclass(frozen=True)
class Token:
    surface: str
    start: int
    end: int

    @property
    def normalized(self) -> str:
        return normalize_term(self.surface)


@dataclass(frozen=True)
class ParagraphRecord:
    anchor: str
    ordinal: int
    text: str
    raw_fragment: str


@dataclass(frozen=True)
class DocumentRecord:
    relative_path: str
    title: str
    paragraphs: tuple[ParagraphRecord, ...]


@dataclass(frozen=True)
class DictionaryData:
    words: frozenset[str]
    mode: str
    path: str | None = None
    url: str | None = None
    sources: tuple[dict[str, object], ...] = ()
    wordfreq_language: str | None = None
    wordfreq_threshold: float | None = None
    wordfreq_derivational_threshold: float | None = None
    wordfreq_lookup: Callable[[str], float] | None = field(
        default=None, repr=False, compare=False
    )

    def contains(self, normalized: str, surface: str | None = None) -> bool:
        """Return whether a term is common English in the merged baseline.

        Explicit word lists and COCA entries are membership signals. The
        wordfreq signal is deliberately thresholded to common English only:
        words below the threshold, including rare English words, remain
        eligible glossary candidates rather than being silently discarded.
        """

        forms = english_lookup_forms(normalized)
        if forms & self.words:
            return True
        if self.wordfreq_lookup is not None and self.wordfreq_threshold is not None:
            for form in forms:
                try:
                    if self.wordfreq_lookup(form) >= self.wordfreq_threshold:
                        return True
                except (TypeError, ValueError):
                    continue
            if (
                self.wordfreq_derivational_threshold is not None
                and can_use_derivational_wordfreq(surface or normalized)
            ):
                direct_score = max(
                    (
                        wordfreq_score(self.wordfreq_lookup, form)
                        for form in forms
                    ),
                    default=0.0,
                )
                if direct_score >= MIN_DERIVATIONAL_SOURCE_SCORE:
                    for form in wordfreq_derivational_forms(normalized):
                        if (
                            wordfreq_score(self.wordfreq_lookup, form)
                            >= self.wordfreq_derivational_threshold
                        ):
                            return True
        return False


@dataclass(frozen=True)
class CocaData:
    words: frozenset[str]
    path: str
    url: str | None = None
    format: str = "text"


@dataclass
class CandidateAccumulator:
    normalized_form: str
    canonical_surface_form: str
    variants_seen: set[str] = field(default_factory=set)
    reason_codes: set[str] = field(default_factory=set)
    frequency: int = 0
    surface_frequency: Counter[str] = field(default_factory=Counter)
    documents: set[str] = field(default_factory=set)
    evidence_by_location: dict[tuple[str, int], dict[str, object]] = field(
        default_factory=dict
    )
    occurrence_keys: set[tuple[object, ...]] = field(default_factory=set)

    def add(
        self,
        surface: str,
        document: DocumentRecord,
        paragraph: ParagraphRecord,
        reasons: Iterable[str],
        *,
        occurrence_key: tuple[object, ...] | None = None,
        count_occurrence: bool = True,
        max_evidence: int = DEFAULT_MAX_EVIDENCE,
    ) -> None:
        cleaned = clean_surface(surface)
        if not cleaned:
            return
        normalized = normalize_term(cleaned)
        if not normalized or normalized != self.normalized_form:
            return

        self.variants_seen.add(cleaned)
        reason_set = set(reasons)
        self.reason_codes.update(reason_set)
        self.documents.add(document.relative_path)

        if count_occurrence and occurrence_key is not None:
            if occurrence_key not in self.occurrence_keys:
                self.occurrence_keys.add(occurrence_key)
                self.frequency += 1
                self.surface_frequency[cleaned] += 1

        location_key = (document.relative_path, paragraph.ordinal)
        evidence = self.evidence_by_location.get(location_key)
        if evidence is None:
            if len(self.evidence_by_location) >= max_evidence:
                return
            evidence = {
                "document": document.relative_path,
                "title": document.title,
                "anchor": paragraph.anchor,
                "paragraph_ordinal": paragraph.ordinal,
                "context": excerpt(paragraph.text),
                "reason_codes": set(),
            }
            self.evidence_by_location[location_key] = evidence
        evidence_reasons = evidence["reason_codes"]
        assert isinstance(evidence_reasons, set)
        evidence_reasons.update(reason_set)

    def priority_score(self) -> int:
        reason_score = sum(REASON_WEIGHTS.get(reason, 0) for reason in self.reason_codes)
        document_score = min(len(self.documents), 5)
        token_score = min(len(self.normalized_form.split()), 4)
        return reason_score + document_score + token_score

    def to_record(self) -> dict[str, object]:
        variants = sorted(
            variant
            for variant in self.variants_seen
            if variant != self.canonical_surface_form
        )
        evidence_contexts: list[dict[str, object]] = []
        for key in sorted(self.evidence_by_location):
            evidence = dict(self.evidence_by_location[key])
            reason_codes = evidence.get("reason_codes", set())
            evidence["reason_codes"] = sorted(reason_codes)
            evidence_contexts.append(evidence)

        return {
            "canonical_surface_form": self.canonical_surface_form,
            "normalized_form": self.normalized_form,
            "variants": variants,
            "reason_codes": sorted(self.reason_codes),
            "priority_score": self.priority_score(),
            "evidence_contexts": evidence_contexts,
            "document_count": len(self.documents),
            "frequency": self.frequency,
            "surface_frequency": {
                key: self.surface_frequency[key]
                for key in sorted(self.surface_frequency)
            },
        }


def normalize_term(text: str) -> str:
    """Normalize case, diacritics, and spacing without inventing spellings."""

    text = html.unescape(text).replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s+", " ", text).strip()
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    without_marks = without_marks.casefold()
    without_marks = re.sub(r"\s+", " ", without_marks).strip()
    return without_marks.strip(" \t\r\n.,;:!?()[]{}\"'“”‘’")


def clean_surface(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" \t\r\n.,;:!?()[]{}\"“”‘’")


def excerpt(text: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def tokens(text: str) -> list[Token]:
    return [
        Token(match.group(0), match.start(), match.end())
        for match in TOKEN_RE.finditer(text)
    ]


def has_letters(text: str) -> bool:
    return any(char.isalpha() for char in text)


def english_lookup_forms(normalized: str) -> frozenset[str]:
    """Return conservative English forms for dictionary comparison.

    The macOS Webster list and many newline word lists contain lemmas but not
    every ordinary inflection. These forms prevent common English words from
    becoming glossary candidates without trying to spell-correct specialist
    terms.
    """

    forms = {normalized}
    irregular = COMMON_IRREGULAR_ENGLISH_BASES.get(normalized)
    if irregular:
        forms.add(irregular)

    if normalized.endswith("ies") and len(normalized) > 4:
        forms.add(normalized[:-3] + "y")
    if normalized.endswith("ied") and len(normalized) > 4:
        forms.add(normalized[:-3] + "y")
    if normalized.endswith("es") and len(normalized) > 4:
        forms.add(normalized[:-2])
    if normalized.endswith("s") and len(normalized) > 3:
        forms.add(normalized[:-1])
    if normalized.endswith("ed") and len(normalized) > 4:
        forms.add(normalized[:-2])
        forms.add(normalized[:-1])
    if normalized.endswith("ing") and len(normalized) > 5:
        stem = normalized[:-3]
        forms.add(stem)
        forms.add(stem + "e")
    if normalized.endswith("er") and len(normalized) > 4:
        forms.add(normalized[:-2])
        forms.add(normalized[:-2] + "e")
    if normalized.endswith("est") and len(normalized) > 5:
        forms.add(normalized[:-3])
        forms.add(normalized[:-3] + "e")
    return frozenset(form for form in forms if form)


def can_use_derivational_wordfreq(surface: str) -> bool:
    """Limit morphology guesses to plain alphabetic English-looking tokens.

    This deliberately excludes diacritic-bearing and punctuated spellings so a
    common English root cannot accidentally erase a Sanskrit or Ananda Marga
    term from the candidate set.
    """

    decomposed = unicodedata.normalize("NFD", surface)
    if any(unicodedata.combining(char) for char in decomposed):
        return False
    return surface.isascii() and surface.isalpha()


def wordfreq_derivational_forms(normalized: str) -> frozenset[str]:
    """Return a small, conservative family of English derivational forms.

    These are lookup probes only. They do not rewrite source text or generate
    glossary entries. The finite suffix rules cover common relationships such
    as ``reverberated -> reverberate``, ``reverentially -> reverential`` or
    ``reverence``, and ``debilitation -> debilitating``.
    """

    forms: set[str] = set()
    if len(normalized) < 7 or not normalized.isascii() or not normalized.isalpha():
        return frozenset()

    if normalized.endswith("ly") and len(normalized) > 6:
        stem = normalized[:-2]
        forms.add(stem)
        if stem.endswith("ential") and len(stem) > 6:
            forms.add(stem[:-6] + "ence")
        if stem.endswith("ical") and len(stem) > 4:
            forms.add(stem[:-4] + "ic")

    if normalized.endswith("ed") and len(normalized) > 6:
        stem = normalized[:-2]
        forms.add(stem)
        forms.add(stem + "e")
        forms.add(stem + "ing")

    if normalized.endswith("ing") and len(normalized) > 7:
        stem = normalized[:-3]
        forms.add(stem)
        forms.add(stem + "e")

    if normalized.endswith("ation") and len(normalized) > 8:
        stem = normalized[:-5]
        forms.add(stem + "ate")
        forms.add(stem + "ating")

    if normalized.endswith("tion") and len(normalized) > 7:
        stem = normalized[:-4]
        forms.add(stem + "te")
        forms.add(stem + "ting")

    return frozenset(form for form in forms if form != normalized)


def wordfreq_score(lookup: Callable[[str], float], term: str) -> float:
    try:
        return float(lookup(term))
    except (TypeError, ValueError):
        return 0.0


def has_diacritics(text: str) -> bool:
    decomposed = unicodedata.normalize("NFD", text)
    return any(unicodedata.combining(char) for char in decomposed)


def is_candidate_token(
    token: Token,
    dictionary_words: frozenset[str] | DictionaryData,
    *,
    allow_short: bool = False,
) -> bool:
    minimum_length = 2 if allow_short else 3
    if not has_letters(token.surface) or len(token.normalized) < minimum_length:
        return False
    if isinstance(dictionary_words, DictionaryData):
        is_english = dictionary_words.contains(token.normalized, token.surface)
        is_english_base = dictionary_words.contains(
            token.normalized[:-2], token.surface
        )
    else:
        is_english = bool(english_lookup_forms(token.normalized) & dictionary_words)
        is_english_base = bool(
            english_lookup_forms(token.normalized[:-2]) & dictionary_words
        )
    if is_english:
        return False
    if token.normalized.endswith("'s") and is_english_base:
        return False
    return True


def load_search_module():
    """Load the existing search extractor without importing the CLI package."""

    if not SEARCH_MODULE_PATH.is_file():
        raise GlossaryError(
            f"Existing discourse extractor not found at {SEARCH_MODULE_PATH}"
        )
    spec = importlib.util.spec_from_file_location("baba_search_for_glossary", SEARCH_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise GlossaryError(f"Could not load discourse extractor at {SEARCH_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def humanize_filename(stem: str) -> str:
    return re.sub(r"[_-]+", " ", stem).strip() or stem


def extract_raw_paragraphs(content: str, search_module) -> list[tuple[str, str, str]]:
    """Return raw blocks aligned with baba-search paragraph extraction."""

    records: list[tuple[str, str, str]] = []
    for match in RAW_PARAGRAPH_RE.finditer(content):
        anchor = match.group(1).strip().strip("\"'")
        fragment = match.group(2)
        text = search_module.html_to_text(fragment)
        if len(text) >= search_module.MIN_DISCOURSE_PARAGRAPH_LENGTH:
            records.append((anchor, text, fragment))
    return records


def iter_documents(root: Path, search_module) -> Iterator[DocumentRecord]:
    if not root.is_dir():
        raise GlossaryError(f"Discourse root is not a directory: {root}")

    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".html", ".htm"}
    )
    for path in paths:
        content = path.read_text(encoding="utf-8", errors="replace")
        extracted = search_module.extract_html_paragraphs(content)
        raw = extract_raw_paragraphs(content, search_module)
        if len(extracted) != len(raw):
            # Keep the established extractor authoritative if a future HTML
            # variation changes the local raw-block alignment.
            raw = [
                (anchor, text, "") for anchor, text in extracted
            ]
        paragraphs = tuple(
            ParagraphRecord(
                anchor=anchor,
                ordinal=ordinal,
                text=text,
                raw_fragment=raw[ordinal][2],
            )
            for ordinal, (anchor, text) in enumerate(extracted)
        )
        title = search_module.extract_html_title(content) or humanize_filename(path.stem)
        relative_path = path.relative_to(root).as_posix()
        yield DocumentRecord(relative_path, title, paragraphs)


def default_dictionary_cache_path() -> Path:
    cache_root = os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "baba-glossary" / "english-words.txt"
    return Path.home() / ".cache" / "baba-glossary" / "english-words.txt"


def parse_dictionary_lines(lines: Iterable[str]) -> frozenset[str]:
    words: set[str] = set()
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        entry = entry.split("\t", 1)[0].strip()
        normalized = normalize_term(entry)
        if normalized and " " not in normalized and has_letters(normalized):
            words.add(normalized)
    if not words:
        raise GlossaryError("The dictionary did not contain any usable words")
    return frozenset(words)


def read_dictionary(path: Path) -> frozenset[str]:
    if not path.is_file():
        raise GlossaryError(f"Dictionary file not found: {path}")
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return parse_dictionary_lines(handle)
    except OSError as exc:
        raise GlossaryError(f"Could not read dictionary {path}: {exc}") from exc


def default_coca_cache_path() -> Path:
    cache_root = os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "baba-glossary" / "coca-lemmas-60k.txt"
    return Path.home() / ".cache" / "baba-glossary" / "coca-lemmas-60k.txt"


def _coca_word_from_fields(
    fields: Sequence[str],
    word_index: int | None,
) -> str | None:
    if word_index is not None:
        if word_index >= len(fields):
            return None
        value = fields[word_index]
    elif len(fields) >= 2 and fields[0].strip().isdigit():
        value = fields[1]
    else:
        value = fields[0] if fields else ""
    normalized = normalize_term(value)
    if (
        normalized
        and " " not in normalized
        and has_letters(normalized)
        and not normalized.isdigit()
    ):
        return normalized
    return None


def parse_coca_lines(lines: Iterable[str]) -> frozenset[str]:
    """Parse COCA sample TSV/text files into normalized word forms.

    The free COCA sample uses a header with a `word` column, while other COCA
    exports commonly use `rank`, `word`, and frequency columns. Headerless
    files are handled by taking the first field, or the second field when the
    first field is a numeric rank. Frequencies are intentionally not retained:
    COCA is used as a common-English membership baseline, not as a reason to
    remove rare domain terms.
    """

    words: set[str] = set()
    word_index: int | None = None
    header_seen = False
    for raw_line in lines:
        line = raw_line.lstrip("\ufeff").strip()
        if not line or line.startswith(("#", "*", "-")):
            continue
        fields = line.split("\t")
        if len(fields) == 1:
            fields = re.split(r"\s+", line)
        normalized_headers = [normalize_term(field) for field in fields]
        if not header_seen and any(
            header in {"word", "word form", "wordform", "form"}
            for header in normalized_headers
        ):
            for index, header in enumerate(normalized_headers):
                if header in {"word", "word form", "wordform", "form"}:
                    word_index = index
                    break
            header_seen = True
            continue
        if not header_seen and any(
            header in {"lemrank", "rank", "lemma", "pos", "lemfreq", "wordfreq"}
            for header in normalized_headers
        ):
            # Some exports have a lemma column but no literal `word` header.
            # Prefer lemma as a useful fallback for the English baseline.
            for index, header in enumerate(normalized_headers):
                if header in {"lemma", "word", "wordform", "form"}:
                    word_index = index
                    break
            header_seen = True
            continue

        word = _coca_word_from_fields(fields, word_index)
        if word:
            words.add(word)
    if not words:
        raise GlossaryError("The COCA file did not contain any usable word forms")
    return frozenset(words)


def _xlsx_cell_text(cell: ET.Element, shared_strings: Sequence[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(cell.itertext())
    value = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (IndexError, ValueError):
            return ""
    return value.text


def parse_coca_xlsx(path: Path) -> frozenset[str]:
    """Read simple COCA `.xlsx` exports without requiring openpyxl."""

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(item.itertext())
                    for item in shared_root.findall(f"{namespace}si")
                ]
            rows: list[str] = []
            worksheet_names = sorted(
                name
                for name in archive.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            )
            for worksheet_name in worksheet_names:
                root = ET.fromstring(archive.read(worksheet_name))
                for row in root.findall(f".//{namespace}row"):
                    fields = [
                        _xlsx_cell_text(cell, shared_strings)
                        for cell in row.findall(f"{namespace}c")
                    ]
                    if fields:
                        rows.append("\t".join(fields))
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise GlossaryError(f"Could not read COCA workbook {path}: {exc}") from exc
    return parse_coca_lines(rows)


def read_coca(path: Path) -> frozenset[str]:
    if not path.is_file():
        raise GlossaryError(f"COCA file not found: {path}")
    try:
        if path.suffix.casefold() in {".xlsx", ".xlsm"}:
            return parse_coca_xlsx(path)
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return parse_coca_lines(handle)
    except OSError as exc:
        raise GlossaryError(f"Could not read COCA file {path}: {exc}") from exc


def make_wordfreq_lookup(language: str = DEFAULT_WORDFREQ_LANGUAGE) -> Callable[[str], float]:
    """Load the optional `wordfreq` Zipf-frequency backend lazily."""

    try:
        from wordfreq import zipf_frequency
    except ImportError as exc:
        raise GlossaryError(
            "The wordfreq backend is not installed. Run "
            "python3 -m pip install -r tools/baba-glossary/requirements.txt"
        ) from exc

    @lru_cache(maxsize=100_000)
    def lookup(term: str) -> float:
        return float(zipf_frequency(term, language))

    return lookup


def _atomic_download(
    url: str,
    cache_path: Path,
    *,
    urlopen: Callable[..., object] | None = None,
) -> None:
    cache_path = cache_path.expanduser().resolve()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    opener = urlopen or urllib.request.urlopen
    temporary_path: Path | None = None
    try:
        with opener(url, timeout=30) as response:  # type: ignore[attr-defined]
            payload = response.read()  # type: ignore[attr-defined]
        if isinstance(payload, str):
            text = payload
        else:
            text = payload.decode("utf-8")
        # Validate before replacing a previous cache. A failed or HTML error
        # response must never destroy a known-good dictionary file.
        parse_dictionary_lines(text.splitlines())
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, cache_path)
        temporary_path = None
    except GlossaryError:
        raise
    except Exception as exc:
        raise GlossaryError(f"Could not download dictionary from {url}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _atomic_download_coca(
    url: str,
    cache_path: Path,
    *,
    urlopen: Callable[..., object] | None = None,
) -> None:
    """Download a COCA text or workbook into a validated cache atomically."""

    cache_path = cache_path.expanduser().resolve()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    opener = urlopen or urllib.request.urlopen
    temporary_path: Path | None = None
    try:
        with opener(url, timeout=30) as response:  # type: ignore[attr-defined]
            payload = response.read()  # type: ignore[attr-defined]
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = payload
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=cache_path.suffix or ".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())

        if cache_path.suffix.casefold() in {".xlsx", ".xlsm"}:
            parse_coca_xlsx(temporary_path)
        else:
            parse_coca_lines(payload_bytes.decode("utf-8").splitlines())
        os.replace(temporary_path, cache_path)
        temporary_path = None
    except GlossaryError:
        raise
    except Exception as exc:
        raise GlossaryError(f"Could not download COCA data from {url}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def load_dictionary(
    dictionary_path: Path | None = None,
    *,
    download: bool = False,
    cache_path: Path | None = None,
    url: str = DEFAULT_DICTIONARY_URL,
) -> DictionaryData:
    if dictionary_path is not None and download:
        raise GlossaryError("Use --dictionary or --download-dictionary, not both")
    if dictionary_path is not None:
        resolved = dictionary_path.expanduser().resolve()
        return DictionaryData(
            words=read_dictionary(resolved),
            mode="explicit",
            path=str(resolved),
            sources=(
                {
                    "kind": "dictionary",
                    "mode": "explicit",
                    "path": str(resolved),
                },
            ),
        )
    if download:
        resolved_cache = (cache_path or default_dictionary_cache_path()).expanduser().resolve()
        if not resolved_cache.is_file():
            _atomic_download(url, resolved_cache)
        return DictionaryData(
            words=read_dictionary(resolved_cache),
            mode="downloaded",
            path=str(resolved_cache),
            url=url,
            sources=(
                {
                    "kind": "dictionary",
                    "mode": "downloaded",
                    "path": str(resolved_cache),
                    "url": url,
                },
            ),
        )
    return DictionaryData(
        words=BUILTIN_MINIMAL_ENGLISH_WORDS,
        mode="builtin-minimal",
        sources=(
            {
                "kind": "dictionary",
                "mode": "builtin-minimal",
            },
        ),
    )


def load_coca(
    coca_path: Path | None = None,
    *,
    download: bool = False,
    cache_path: Path | None = None,
    url: str = DEFAULT_COCA_URL,
) -> CocaData:
    if coca_path is not None and download:
        raise GlossaryError("Use --coca or --download-coca, not both")
    if coca_path is not None:
        resolved = coca_path.expanduser().resolve()
        return CocaData(words=read_coca(resolved), path=str(resolved), format=resolved.suffix.lstrip(".") or "text")
    resolved_cache = (cache_path or default_coca_cache_path()).expanduser().resolve()
    if download and not resolved_cache.is_file():
        _atomic_download_coca(url, resolved_cache)
    if not resolved_cache.is_file():
        raise GlossaryError(
            "COCA support was requested but no file was supplied. Use --coca "
            "or opt in with --download-coca."
        )
    return CocaData(
        words=read_coca(resolved_cache),
        path=str(resolved_cache),
        url=url if download else None,
        format=resolved_cache.suffix.lstrip(".") or "text",
    )


def load_english_baseline(
    dictionary_path: Path | None = None,
    *,
    download_dictionary: bool = False,
    dictionary_cache_path: Path | None = None,
    dictionary_url: str = DEFAULT_DICTIONARY_URL,
    wordfreq: bool = False,
    wordfreq_language: str = DEFAULT_WORDFREQ_LANGUAGE,
    wordfreq_threshold: float = DEFAULT_WORDFREQ_THRESHOLD,
    wordfreq_derivational_threshold: float = DEFAULT_WORDFREQ_DERIVATIONAL_THRESHOLD,
    coca_path: Path | None = None,
    download_coca: bool = False,
    coca_cache_path: Path | None = None,
    coca_url: str = DEFAULT_COCA_URL,
) -> DictionaryData:
    """Merge the offline dictionary, optional COCA, and optional wordfreq.

    The returned object remains compatible with the original DictionaryData
    API. The wordfreq callable is kept in memory only and never serialized.
    """

    baseline = load_dictionary(
        dictionary_path,
        download=download_dictionary,
        cache_path=dictionary_cache_path,
        url=dictionary_url,
    )
    words = set(baseline.words)
    sources = list(baseline.sources)
    coca_data: CocaData | None = None
    if coca_path is not None or download_coca:
        coca_data = load_coca(
            coca_path,
            download=download_coca,
            cache_path=coca_cache_path,
            url=coca_url,
        )
        words.update(coca_data.words)
        sources.append(
            {
                "kind": "coca",
                "path": coca_data.path,
                "url": coca_data.url,
                "format": coca_data.format,
                "word_count": len(coca_data.words),
            }
        )

    lookup: Callable[[str], float] | None = None
    if wordfreq:
        if wordfreq_threshold <= 0:
            raise GlossaryError("--wordfreq-threshold must be greater than zero")
        if wordfreq_derivational_threshold <= 0:
            raise GlossaryError(
                "--wordfreq-derivational-threshold must be greater than zero"
            )
        lookup = make_wordfreq_lookup(wordfreq_language)
        sources.append(
            {
                "kind": "wordfreq",
                "language": wordfreq_language,
                "zipf_threshold": wordfreq_threshold,
                "derivational_zipf_threshold": wordfreq_derivational_threshold,
            }
        )

    if not sources or (not wordfreq and coca_data is None):
        return baseline
    return DictionaryData(
        words=frozenset(words),
        mode="merged",
        path=baseline.path,
        url=baseline.url,
        sources=tuple(sources),
        wordfreq_language=wordfreq_language if wordfreq else None,
        wordfreq_threshold=wordfreq_threshold if wordfreq else None,
        wordfreq_derivational_threshold=(
            wordfreq_derivational_threshold if wordfreq else None
        ),
        wordfreq_lookup=lookup,
    )


def qualified_token_runs(
    paragraph_text: str,
    paragraph_tokens: Sequence[Token],
    qualifies: Callable[[Token], bool],
) -> Iterator[tuple[Token, Token]]:
    """Yield maximal runs of tokens selected by a caller-provided predicate."""

    run: list[Token] = []
    for token in paragraph_tokens:
        if not qualifies(token):
            if len(run) >= 2:
                yield run[0], run[-1]
            run = []
            continue
        if run:
            separator = paragraph_text[run[-1].end : token.start]
            if not re.fullmatch(r"[\s/-]+", separator):
                if len(run) >= 2:
                    yield run[0], run[-1]
                run = []
        run.append(token)
    if len(run) >= 2:
        yield run[0], run[-1]


def surface_runs(
    paragraph_text: str,
    paragraph_tokens: Sequence[Token],
    dictionary_words: frozenset[str] | DictionaryData,
) -> Iterator[tuple[Token, Token]]:
    """Yield maximal runs of adjacent non-English-looking tokens."""

    yield from qualified_token_runs(
        paragraph_text,
        paragraph_tokens,
        lambda token: is_candidate_token(token, dictionary_words, allow_short=True),
    )


def annotation_surfaces(
    paragraph: ParagraphRecord,
    search_module,
) -> Iterator[tuple[str, str]]:
    """Yield quoted or explicitly marked spans with their evidence category.

    Bracketed text is intentionally not an annotation source. It remains in
    ``paragraph.text`` and is therefore still scanned by the ordinary token
    and adjacent-token-run passes in ``build_glossary``.
    """

    for match in DOUBLE_QUOTE_RE.finditer(paragraph.text):
        yield "quoted", match.group("body")
    for match in SINGLE_QUOTE_RE.finditer(paragraph.text):
        body = match.group("body")
        if re.search(r"\s", body):
            yield "quoted", body
    if paragraph.raw_fragment:
        for match in ITALIC_RE.finditer(paragraph.raw_fragment):
            visible = search_module.html_to_text(match.group(1))
            if visible:
                yield "italic", visible


def surface_near_definition_cue(paragraph_text: str, surface: str) -> bool:
    """Return whether a marked span is close to a definition cue."""

    if not surface:
        return False
    for match in re.finditer(re.escape(surface), paragraph_text, flags=re.IGNORECASE):
        for cue in DEFINITION_CUE_RE.finditer(paragraph_text):
            if abs(cue.start() - match.end()) <= 72 or abs(match.start() - cue.end()) <= 72:
                return True
    return False


def annotation_token_is_specialized(
    token: Token,
    dictionary: frozenset[str] | DictionaryData,
) -> bool:
    """Select marked tokens that deserve review beyond baseline membership."""

    if is_candidate_token(token, dictionary, allow_short=True):
        return True
    if has_diacritics(token.surface):
        return True
    if isinstance(dictionary, DictionaryData) and dictionary.wordfreq_lookup is not None:
        direct_score = max(
            wordfreq_score(dictionary.wordfreq_lookup, form)
            for form in english_lookup_forms(token.normalized)
        )
        return (
            dictionary.wordfreq_threshold is not None
            and 0 < direct_score < dictionary.wordfreq_threshold
        )
    return False


def definition_subject_tokens(
    paragraph_text: str,
    paragraph_tokens: Sequence[Token],
    cue: re.Match[str],
) -> tuple[Token, ...]:
    """Return a short term immediately before a definition cue.

    Only the subject side of a cue is considered. This keeps the definition
    evidence useful for a baseline-known term without turning the explanation
    or a quoted passage after ``means`` into glossary entries.
    """

    before = [token for token in paragraph_tokens if token.end <= cue.start()]
    subject: list[Token] = []
    for token in reversed(before):
        if cue.start() - token.end > 72:
            break
        if subject:
            separator = paragraph_text[token.end : subject[0].start]
            if re.search(r"[.!?;:]", separator):
                break
        normalized = token.normalized
        if not subject and normalized in DEFINITION_BRIDGING_WORDS:
            continue
        if normalized in DEFINITION_SUBJECT_STOPWORDS:
            break
        subject.insert(0, token)
        if len(subject) >= MAX_HIGHLIGHT_TOKENS:
            break
    return tuple(subject)


def nearby_definition_tokens(
    paragraph_text: str,
    paragraph_tokens: Sequence[Token],
    dictionary_words: frozenset[str] | DictionaryData,
) -> Iterator[Token]:
    yielded: set[tuple[int, int]] = set()
    for cue in DEFINITION_CUE_RE.finditer(paragraph_text):
        subject = definition_subject_tokens(paragraph_text, paragraph_tokens, cue)
        for token in paragraph_tokens:
            if token.normalized in DEFINITION_SUBJECT_STOPWORDS:
                continue
            if not is_candidate_token(token, dictionary_words, allow_short=True):
                if token not in subject:
                    continue
            cue_start = cue.start()
            cue_end = cue.end()
            if token.end <= cue_start:
                distance = cue_start - token.end
            elif token.start >= cue_end:
                distance = token.start - cue_end
            else:
                distance = 0
            if distance <= 72 and (token.start, token.end) not in yielded:
                yielded.add((token.start, token.end))
                yield token


def definition_subject_spans(
    paragraph_text: str,
    paragraph_tokens: Sequence[Token],
) -> Iterator[tuple[Token, Token]]:
    """Yield short multiword subjects immediately before definition cues."""

    seen: set[tuple[int, int]] = set()
    for cue in DEFINITION_CUE_RE.finditer(paragraph_text):
        subject = definition_subject_tokens(paragraph_text, paragraph_tokens, cue)
        if len(subject) < 2:
            continue
        key = (subject[0].start, subject[-1].end)
        if key not in seen:
            seen.add(key)
            yield subject[0], subject[-1]


def add_candidate(
    candidates: dict[str, CandidateAccumulator],
    surface: str,
    document: DocumentRecord,
    paragraph: ParagraphRecord,
    reasons: Iterable[str],
    *,
    occurrence_key: tuple[object, ...] | None = None,
    count_occurrence: bool = True,
    max_evidence: int,
) -> CandidateAccumulator | None:
    cleaned = clean_surface(surface)
    normalized = normalize_term(cleaned)
    if not normalized:
        return None
    candidate = candidates.get(normalized)
    if candidate is None:
        candidate = CandidateAccumulator(normalized, cleaned)
        candidates[normalized] = candidate
    candidate.add(
        cleaned,
        document,
        paragraph,
        reasons,
        occurrence_key=occurrence_key,
        count_occurrence=count_occurrence,
        max_evidence=max_evidence,
    )
    return candidate


def add_annotated_surface(
    candidates: dict[str, CandidateAccumulator],
    surface: str,
    annotation_reason: str,
    document: DocumentRecord,
    paragraph: ParagraphRecord,
    dictionary_words: frozenset[str] | DictionaryData,
    *,
    annotation_index: int,
    max_evidence: int,
) -> None:
    annotation_tokens = tokens(surface)
    unknown_tokens = [
        token
        for token in annotation_tokens
        if is_candidate_token(token, dictionary_words, allow_short=True)
    ]
    specialized_tokens = [
        token
        for token in annotation_tokens
        if annotation_token_is_specialized(token, dictionary_words)
    ]
    definition_evidence = surface_near_definition_cue(paragraph.text, surface)
    if not specialized_tokens and not definition_evidence:
        return
    if not specialized_tokens and definition_evidence:
        # A short marked span immediately defined in the text is explicit
        # specialist evidence even when every token is in the baseline.
        specialized_tokens = list(annotation_tokens)

    if (
        specialized_tokens
        and MIN_HIGHLIGHT_TOKENS <= len(annotation_tokens) <= MAX_HIGHLIGHT_TOKENS
        and (
            len(specialized_tokens) == len(annotation_tokens)
            or definition_evidence
            or (
                unknown_tokens
                and (
                    annotation_reason == "italic"
                    or len(annotation_tokens) == 2
                )
            )
        )
    ):
        normalized = normalize_term(surface)
        count_occurrence = normalized not in candidates
        add_candidate(
            candidates,
            surface,
            document,
            paragraph,
            {annotation_reason},
            occurrence_key=(
                "annotation",
                document.relative_path,
                paragraph.ordinal,
                annotation_reason,
                annotation_index,
            ),
            count_occurrence=count_occurrence,
            max_evidence=max_evidence,
        )
        return

    # Italic short spans are often specialist phrases that mix one domain token
    # with a common English headword. Preserve the phrase as a unit instead of
    # letting the common word split it apart. Keep quoted spans conservative so
    # an ordinary sentence is not emitted as a term.
    if (
        specialized_tokens
        and 2 <= len(annotation_tokens) <= MAX_MIXED_ANNOTATED_PHRASE_TOKENS
        and (annotation_reason == "italic" or len(annotation_tokens) == 2)
    ):
        normalized = normalize_term(surface)
        count_occurrence = normalized not in candidates
        add_candidate(
            candidates,
            surface,
            document,
            paragraph,
            {annotation_reason},
            occurrence_key=(
                "mixed-annotation",
                document.relative_path,
                paragraph.ordinal,
                annotation_reason,
                annotation_index,
            ),
            count_occurrence=count_occurrence,
            max_evidence=max_evidence,
        )
        return

    # Long quoted passages are evidence, not glossary entries. Preserve the
    # specialized words and multiword runs found inside them instead.
    for token in specialized_tokens:
        add_candidate(
            candidates,
            token.surface,
            document,
            paragraph,
            {annotation_reason},
            occurrence_key=(
                "annotation-token",
                document.relative_path,
                paragraph.ordinal,
                token.start,
                token.end,
            ),
            count_occurrence=False,
            max_evidence=max_evidence,
        )
    specialized_positions = {(token.start, token.end) for token in specialized_tokens}
    for first, last in qualified_token_runs(
        surface,
        annotation_tokens,
        lambda token: (token.start, token.end) in specialized_positions,
    ):
        add_candidate(
            candidates,
            surface[first.start : last.end],
            document,
            paragraph,
            {annotation_reason, "multiword_non_english"},
            occurrence_key=(
                "annotation-run",
                document.relative_path,
                paragraph.ordinal,
                first.start,
                last.end,
            ),
            count_occurrence=False,
            max_evidence=max_evidence,
        )


def build_glossary(
    discourse_root: Path,
    dictionary: DictionaryData,
    *,
    max_evidence: int = DEFAULT_MAX_EVIDENCE,
) -> dict[str, object]:
    search_module = load_search_module()
    candidates: dict[str, CandidateAccumulator] = {}
    documents = list(iter_documents(discourse_root.expanduser().resolve(), search_module))
    paragraph_count = 0

    for document in documents:
        for paragraph in document.paragraphs:
            paragraph_count += 1
            paragraph_tokens = tokens(paragraph.text)
            base_normalized_in_paragraph: set[str] = set()

            for token in paragraph_tokens:
                if not is_candidate_token(token, dictionary):
                    continue
                base_normalized_in_paragraph.add(token.normalized)
                add_candidate(
                    candidates,
                    token.surface,
                    document,
                    paragraph,
                    {"not_in_english_baseline"},
                    occurrence_key=(
                        "token",
                        document.relative_path,
                        paragraph.ordinal,
                        token.start,
                        token.end,
                    ),
                    max_evidence=max_evidence,
                )

            for first, last in surface_runs(
                paragraph.text, paragraph_tokens, dictionary
            ):
                surface = paragraph.text[first.start : last.end]
                add_candidate(
                    candidates,
                    surface,
                    document,
                    paragraph,
                    {"multiword_non_english"},
                    occurrence_key=(
                        "run",
                        document.relative_path,
                        paragraph.ordinal,
                        first.start,
                        last.end,
                    ),
                    max_evidence=max_evidence,
                )

            for annotation_index, (reason, surface) in enumerate(
                annotation_surfaces(paragraph, search_module)
            ):
                add_annotated_surface(
                    candidates,
                    surface,
                    reason,
                    document,
                    paragraph,
                    dictionary,
                    annotation_index=annotation_index,
                    max_evidence=max_evidence,
                )

            for first, last in definition_subject_spans(
                paragraph.text, paragraph_tokens
            ):
                add_candidate(
                    candidates,
                    paragraph.text[first.start : last.end],
                    document,
                    paragraph,
                    {"definition_context"},
                    occurrence_key=(
                        "definition-span",
                        document.relative_path,
                        paragraph.ordinal,
                        first.start,
                        last.end,
                    ),
                    count_occurrence=False,
                    max_evidence=max_evidence,
                )

            for token in nearby_definition_tokens(
                paragraph.text, paragraph_tokens, dictionary
            ):
                add_candidate(
                    candidates,
                    token.surface,
                    document,
                    paragraph,
                    {"definition_context"},
                    occurrence_key=(
                        "definition",
                        document.relative_path,
                        paragraph.ordinal,
                        token.start,
                        token.end,
                    ),
                    count_occurrence=False,
                    max_evidence=max_evidence,
                )

    ordered_candidates = sorted(
        candidates.values(),
        key=lambda candidate: (
            -candidate.priority_score(),
            -len(candidate.documents),
            -len(candidate.normalized_form.split()),
            candidate.normalized_form,
            candidate.canonical_surface_form,
        ),
    )
    return {
        "schema_version": "1",
        "source_root": str(discourse_root.expanduser().resolve()),
        "dictionary": {
            "mode": dictionary.mode,
            "path": dictionary.path,
            "url": dictionary.url,
            "word_count": len(dictionary.words),
            "sources": list(dictionary.sources),
            "wordfreq_language": dictionary.wordfreq_language,
            "wordfreq_threshold": dictionary.wordfreq_threshold,
            "wordfreq_derivational_threshold": dictionary.wordfreq_derivational_threshold,
        },
        "document_count": len(documents),
        "paragraph_count": paragraph_count,
        "candidate_count": len(ordered_candidates),
        "candidates": [candidate.to_record() for candidate in ordered_candidates],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract deterministic glossary candidates from COMPLETE_SARKAR "
            "discourse HTML without LLM calls. Network is opt-in."
        )
    )
    parser.add_argument(
        "discourse_root",
        type=Path,
        help="Root directory containing COMPLETE_SARKAR discourse HTML files.",
    )
    dictionary_group = parser.add_mutually_exclusive_group()
    dictionary_group.add_argument(
        "--dictionary",
        type=Path,
        help="Explicit newline-delimited English dictionary file.",
    )
    dictionary_group.add_argument(
        "--download-dictionary",
        action="store_true",
        help=(
            "Opt in to downloading the documented English word list; network is "
            "never used without this flag."
        ),
    )
    parser.add_argument(
        "--dictionary-cache",
        type=Path,
        help=(
            "Cache path for --download-dictionary. Defaults to "
            "XDG_CACHE_HOME/baba-glossary/english-words.txt or "
            "~/.cache/baba-glossary/english-words.txt."
        ),
    )
    parser.add_argument(
        "--dictionary-url",
        default=DEFAULT_DICTIONARY_URL,
        help=f"Opt-in download URL (default: {DEFAULT_DICTIONARY_URL}).",
    )
    coca_group = parser.add_mutually_exclusive_group()
    coca_group.add_argument(
        "--coca",
        type=Path,
        help=(
            "Authorized local COCA word-form export, including larger licensed "
            "exports. Supports TSV samples and .xlsx files; the free sample is "
            "supplemental only."
        ),
    )
    coca_group.add_argument(
        "--download-coca",
        action="store_true",
        help=(
            "Opt in to downloading the documented free COCA sample; network is "
            "never used without this flag."
        ),
    )
    parser.add_argument(
        "--coca-cache",
        type=Path,
        help=(
            "Cache path for --download-coca. Defaults to "
            "XDG_CACHE_HOME/baba-glossary/coca-lemmas-60k.txt or "
            "~/.cache/baba-glossary/coca-lemmas-60k.txt."
        ),
    )
    parser.add_argument(
        "--coca-url",
        default=DEFAULT_COCA_URL,
        help=f"Opt-in COCA download URL (default: {DEFAULT_COCA_URL}).",
    )
    parser.add_argument(
        "--wordfreq",
        action="store_true",
        help=(
            "Use the optional wordfreq Zipf-frequency backend. Install it with "
            "tools/baba-glossary/requirements.txt."
        ),
    )
    parser.add_argument(
        "--wordfreq-language",
        default=DEFAULT_WORDFREQ_LANGUAGE,
        help=f"wordfreq language code (default: {DEFAULT_WORDFREQ_LANGUAGE}).",
    )
    parser.add_argument(
        "--wordfreq-threshold",
        type=float,
        default=DEFAULT_WORDFREQ_THRESHOLD,
        help=(
            "Minimum Zipf score treated as common English. Lower or unseen "
            "terms remain glossary candidates (default: "
            f"{DEFAULT_WORDFREQ_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--wordfreq-derivational-threshold",
        type=float,
        default=DEFAULT_WORDFREQ_DERIVATIONAL_THRESHOLD,
        help=(
            "Minimum Zipf score for a conservative derived English base/root "
            "probe (default: "
            f"{DEFAULT_WORDFREQ_DERIVATIONAL_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--max-evidence",
        type=int,
        default=DEFAULT_MAX_EVIDENCE,
        help=f"Maximum evidence contexts per candidate (default: {DEFAULT_MAX_EVIDENCE}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this file instead of stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_evidence < 1:
        parser.error("--max-evidence must be at least 1")
    if args.wordfreq_threshold <= 0:
        parser.error("--wordfreq-threshold must be greater than zero")
    if args.wordfreq_derivational_threshold <= 0:
        parser.error("--wordfreq-derivational-threshold must be greater than zero")

    try:
        dictionary = load_english_baseline(
            args.dictionary,
            download_dictionary=args.download_dictionary,
            dictionary_cache_path=args.dictionary_cache,
            dictionary_url=args.dictionary_url,
            wordfreq=args.wordfreq,
            wordfreq_language=args.wordfreq_language,
            wordfreq_threshold=args.wordfreq_threshold,
            wordfreq_derivational_threshold=args.wordfreq_derivational_threshold,
            coca_path=args.coca,
            download_coca=args.download_coca,
            coca_cache_path=args.coca_cache,
            coca_url=args.coca_url,
        )
        result = build_glossary(
            args.discourse_root,
            dictionary,
            max_evidence=args.max_evidence,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            output_path = args.output.expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except GlossaryError as exc:
        parser.exit(2, f"baba-glossary: error: {exc}\n")
    except OSError as exc:
        parser.exit(2, f"baba-glossary: error: {exc}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
