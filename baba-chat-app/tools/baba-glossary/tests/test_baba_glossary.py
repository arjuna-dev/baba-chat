from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


TOOL_ROOT = Path(__file__).resolve().parents[1]
import sys


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

import baba_glossary


SAMPLE_HTML = """<!doctype html>
<html>
<head><title>Glossary Test</title></head>
<body>
<!-- block a=title type=title -->Glossary Test<!-- /block -->
<!-- block a=p1 type=paragraph -->
<p>The Sanskrit word "svadhyāya" means reflective study. The spelling
svadhyaya also appears in the same discourse. The <i>kaoshiki nrtya</i>
practice is called a dance. The phrase "Ananda Marga" appears here
and [kaoshiki nrtya] is repeated.
<!-- /block -->
<!-- block a=p2 type=paragraph -->
<p>A rareword rareword rareword rareword is mentioned once. The form
svadhyaya is written without a diacritic.</p>
<!-- /block -->
</body>
</html>
"""


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class GlossaryTests(unittest.TestCase):
    def write_fixture(self, root: Path) -> tuple[Path, Path]:
        discourse_root = root / "Discourses"
        discourse_root.mkdir()
        (discourse_root / "sample.html").write_text(SAMPLE_HTML, encoding="utf-8")

        dictionary = root / "english.txt"
        dictionary.write_text(
            "\n".join(
                [
                    "a",
                    "also",
                    "and",
                    "appears",
                    "called",
                    "dance",
                    "diacritic",
                    "form",
                    "here",
                    "is",
                    "mean",
                    "mentioned",
                    "practice",
                    "same",
                    "sanskrit",
                    "spelling",
                    "study",
                    "term",
                    "the",
                    "call",
                    "written",
                    "without",
                    "word",
                    "woman",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return discourse_root, dictionary

    def test_extracts_specialized_terms_and_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discourse_root, dictionary_path = self.write_fixture(root)
            dictionary = baba_glossary.load_dictionary(dictionary_path)
            result = baba_glossary.build_glossary(discourse_root, dictionary)

        candidates = {
            item["normalized_form"]: item for item in result["candidates"]
        }
        self.assertEqual(result["document_count"], 1)
        self.assertEqual(result["paragraph_count"], 2)

        phrase = candidates["kaoshiki nrtya"]
        self.assertEqual(phrase["canonical_surface_form"], "kaoshiki nrtya")
        self.assertIn("multiword_non_english", phrase["reason_codes"])
        self.assertIn("italic", phrase["reason_codes"])
        self.assertNotIn("bracketed", phrase["reason_codes"])
        self.assertEqual(phrase["frequency"], 2)

        diacritic_variant = candidates["svadhyaya"]
        self.assertEqual(diacritic_variant["canonical_surface_form"], "svadhyāya")
        self.assertIn("svadhyaya", diacritic_variant["variants"])
        self.assertIn("definition_context", diacritic_variant["reason_codes"])
        self.assertIn("quoted", diacritic_variant["reason_codes"])
        self.assertEqual(diacritic_variant["frequency"], 3)

        self.assertNotIn("definition", diacritic_variant)
        self.assertTrue(diacritic_variant["evidence_contexts"])
        self.assertNotIn("means", candidates)
        self.assertNotIn("called", candidates)
        self.assertNotIn("women", candidates)

    def test_output_order_uses_evidence_not_frequency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discourse_root, dictionary_path = self.write_fixture(root)
            dictionary = baba_glossary.load_dictionary(dictionary_path)
            result = baba_glossary.build_glossary(discourse_root, dictionary)

        normalized = [item["normalized_form"] for item in result["candidates"]]
        self.assertLess(normalized.index("svadhyaya"), normalized.index("rareword"))

    def test_combining_diacritics_stay_attached_to_specialized_words(self):
        parsed = baba_glossary.tokens("S\u0301iva and A\u0301tma")
        self.assertEqual([token.surface for token in parsed], ["S\u0301iva", "and", "A\u0301tma"])
        self.assertEqual([token.normalized for token in parsed], ["siva", "and", "atma"])

    def test_default_dictionary_is_offline_builtin_fallback(self):
        with mock.patch.object(
            baba_glossary.urllib.request,
            "urlopen",
            side_effect=AssertionError("network must not be used"),
        ):
            dictionary = baba_glossary.load_dictionary()
        self.assertEqual(dictionary.mode, "builtin-minimal")
        self.assertIn("the", dictionary.words)

    def test_download_is_explicit_and_cached_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "cache" / "english.txt"
            opener = mock.Mock(return_value=FakeResponse(b"the\nword\nsvadhyaya\n"))
            with mock.patch.object(baba_glossary.urllib.request, "urlopen", opener):
                dictionary = baba_glossary.load_dictionary(
                    download=True,
                    cache_path=cache_path,
                    url="https://example.test/words.txt",
                )
            self.assertEqual(dictionary.mode, "downloaded")
            self.assertTrue(cache_path.is_file())
            self.assertIn("svadhyaya", dictionary.words)
            opener.assert_called_once()
            opener.reset_mock()
            cached = baba_glossary.load_dictionary(
                download=True,
                cache_path=cache_path,
                url="https://example.test/words.txt",
            )
            self.assertEqual(cached.words, dictionary.words)
            opener.assert_not_called()

    def test_coca_parser_uses_word_column(self):
        words = baba_glossary.parse_coca_lines(
            [
                "* COCA sample metadata",
                "lemRank\tlemma\tPoS\tlemFreq\twordFreq\tword",
                "5\tof\ti\t23159162\t23159162\tof",
                "15\tdo\tv\t8186412\t4501047\tdid",
            ]
        )
        self.assertEqual(words, frozenset({"of", "did"}))

    def test_coca_parser_supports_rank_word_frequency_rows(self):
        words = baba_glossary.parse_coca_lines(
            ["rank\tword\tfreq", "1\tthe\t50000000", "2\tkaoshiki\t1"]
        )
        self.assertEqual(words, frozenset({"the", "kaoshiki"}))

    def test_coca_xlsx_parser_reads_shared_strings(self):
        with tempfile.TemporaryDirectory() as temporary:
            workbook = Path(temporary) / "coca.xlsx"
            shared_strings = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>word</t></si><si><t>the</t></si><si><t>did</t></si>
</sst>
"""
            worksheet = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
    <row r="2"><c r="A2" t="s"><v>1</v></c></row>
    <row r="3"><c r="A3" t="s"><v>2</v></c></row>
  </sheetData>
</worksheet>
"""
            with zipfile.ZipFile(workbook, "w") as archive:
                archive.writestr("xl/sharedStrings.xml", shared_strings)
                archive.writestr("xl/worksheets/sheet1.xml", worksheet)
            self.assertEqual(
                baba_glossary.read_coca(workbook), frozenset({"the", "did"})
            )

    def test_coca_download_is_explicit_and_cached_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "cache" / "coca.txt"
            opener = mock.Mock(
                return_value=FakeResponse(
                    b"rank\tword\tfreq\n1\tthe\t50000000\n"
                )
            )
            with mock.patch.object(baba_glossary.urllib.request, "urlopen", opener):
                coca = baba_glossary.load_coca(
                    download=True,
                    cache_path=cache_path,
                    url="https://example.test/coca.txt",
                )
            self.assertEqual(coca.words, frozenset({"the"}))
            self.assertTrue(cache_path.is_file())
            opener.assert_called_once()
            opener.reset_mock()
            cached = baba_glossary.load_coca(
                download=True,
                cache_path=cache_path,
                url="https://example.test/coca.txt",
            )
            self.assertEqual(cached.words, coca.words)
            opener.assert_not_called()

    def test_wordfreq_threshold_recognizes_only_common_words(self):
        baseline = baba_glossary.DictionaryData(
            words=frozenset(),
            mode="wordfreq-only",
            wordfreq_language="en",
            wordfreq_threshold=2.5,
            wordfreq_derivational_threshold=2.0,
            wordfreq_lookup=lambda term: 5.0 if term == "ordinary" else 2.0,
        )
        self.assertFalse(
            baba_glossary.is_candidate_token(
                baba_glossary.tokens("ordinary")[0], baseline
            )
        )
        self.assertTrue(
            baba_glossary.is_candidate_token(
                baba_glossary.tokens("rareterm")[0], baseline
            )
        )

    def test_default_threshold_and_reported_english_words_are_not_candidates(self):
        self.assertEqual(baba_glossary.DEFAULT_WORDFREQ_THRESHOLD, 2.5)
        scores = {
            "reunification": 3.09,
            "revel": 3.11,
            "revels": 2.77,
            "reverberated": 2.30,
            "reverberate": 2.29,
            "reverentially": 1.51,
            "reverential": 2.14,
            "reverence": 3.22,
            "resuscitation": 2.93,
            "debilitation": 1.68,
            "debilitate": 1.70,
            "debilitating": 3.19,
            "zebra": 3.40,
            "zebras": 2.84,
        }
        baseline = baba_glossary.DictionaryData(
            words=frozenset(),
            mode="wordfreq-only",
            wordfreq_language="en",
            wordfreq_threshold=2.5,
            wordfreq_derivational_threshold=2.0,
            wordfreq_lookup=lambda term: scores.get(term, 0.0),
        )
        reported_words = [
            "reunification",
            "revel",
            "revels",
            "reverberated",
            "reverentially",
            "resuscitation",
            "debilitation",
            "zebra",
            "zebras",
        ]
        for word in reported_words:
            with self.subTest(word=word):
                self.assertFalse(
                    baba_glossary.is_candidate_token(
                        baba_glossary.tokens(word)[0], baseline
                    )
                )

    def test_reason_code_uses_english_baseline_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discourse_root, dictionary_path = self.write_fixture(root)
            result = baba_glossary.build_glossary(
                discourse_root, baba_glossary.load_dictionary(dictionary_path)
            )
        svadhyaya = next(
            item for item in result["candidates"] if item["normalized_form"] == "svadhyaya"
        )
        self.assertIn("not_in_english_baseline", svadhyaya["reason_codes"])
        self.assertNotIn(
            "not_in_english_" + "dictionary", svadhyaya["reason_codes"]
        )

    def test_bracketed_english_explanation_is_not_an_annotation_candidate(self):
        paragraph = baba_glossary.ParagraphRecord(
            anchor="p1",
            ordinal=0,
            text=(
                "This ordinary explanation contains [the yoga of pervasive "
                "association] and remains searchable paragraph text."
            ),
            raw_fragment="",
        )
        self.assertEqual(
            list(baba_glossary.annotation_surfaces(paragraph, None)), []
        )

        baseline = baba_glossary.DictionaryData(
            words=frozenset(
                {
                    "this",
                    "ordinary",
                    "explanation",
                    "contains",
                    "the",
                    "yoga",
                    "of",
                    "pervasive",
                    "association",
                    "and",
                    "remains",
                    "searchable",
                    "paragraph",
                    "text",
                }
            ),
            mode="explicit",
        )
        document = baba_glossary.DocumentRecord(
            relative_path="sample.html",
            title="Sample",
            paragraphs=(paragraph,),
        )
        candidates: dict[str, baba_glossary.CandidateAccumulator] = {}
        paragraph_tokens = baba_glossary.tokens(paragraph.text)
        for token in paragraph_tokens:
            if baba_glossary.is_candidate_token(token, baseline):
                baba_glossary.add_candidate(
                    candidates,
                    token.surface,
                    document,
                    paragraph,
                    {"not_in_english_baseline"},
                    occurrence_key=("token", token.start, token.end),
                    max_evidence=4,
                )
        for first, last in baba_glossary.surface_runs(
            paragraph.text, paragraph_tokens, baseline
        ):
            baba_glossary.add_candidate(
                candidates,
                paragraph.text[first.start : last.end],
                document,
                paragraph,
                {"multiword_non_english"},
                occurrence_key=("run", first.start, last.end),
                max_evidence=4,
            )
        self.assertNotIn("the yoga of pervasive association", candidates)

    def test_specialized_terms_in_brackets_use_normal_detection(self):
        paragraph = baba_glossary.ParagraphRecord(
            anchor="p1",
            ordinal=0,
            text="The specialized phrase [kaoshiki nrtya] remains searchable.",
            raw_fragment="",
        )
        baseline = baba_glossary.DictionaryData(
            words=frozenset({"the", "specialized", "phrase", "remains", "searchable"}),
            mode="explicit",
        )
        document = baba_glossary.DocumentRecord(
            relative_path="sample.html",
            title="Sample",
            paragraphs=(paragraph,),
        )
        candidates: dict[str, baba_glossary.CandidateAccumulator] = {}
        paragraph_tokens = baba_glossary.tokens(paragraph.text)
        for token in paragraph_tokens:
            if baba_glossary.is_candidate_token(token, baseline):
                baba_glossary.add_candidate(
                    candidates,
                    token.surface,
                    document,
                    paragraph,
                    {"not_in_english_baseline"},
                    occurrence_key=("token", token.start, token.end),
                    max_evidence=4,
                )
        for first, last in baba_glossary.surface_runs(
            paragraph.text, paragraph_tokens, baseline
        ):
            baba_glossary.add_candidate(
                candidates,
                paragraph.text[first.start : last.end],
                document,
                paragraph,
                {"multiword_non_english"},
                occurrence_key=("run", first.start, last.end),
                max_evidence=4,
            )
        phrase = candidates["kaoshiki nrtya"]
        self.assertIn("multiword_non_english", phrase.reason_codes)
        self.assertNotIn("bracketed", phrase.reason_codes)

    def test_short_annotated_phrase_survives_common_english_member(self):
        baseline = baba_glossary.DictionaryData(
            words=frozenset({"ordinary"}),
            mode="explicit",
        )
        document = baba_glossary.DocumentRecord(
            relative_path="sample.html",
            title="Sample",
            paragraphs=(),
        )
        paragraph = baba_glossary.ParagraphRecord(
            anchor="p1",
            ordinal=0,
            text="ordinary kaoshiki",
            raw_fragment="",
        )
        candidates: dict[str, baba_glossary.CandidateAccumulator] = {}
        baba_glossary.add_annotated_surface(
            candidates,
            "ordinary kaoshiki",
            "italic",
            document,
            paragraph,
            baseline,
            annotation_index=0,
            max_evidence=4,
        )
        self.assertIn("ordinary kaoshiki", candidates)

    def test_marked_and_defined_terms_can_survive_general_baseline(self):
        baseline = baba_glossary.DictionaryData(
            words=frozenset({"chakra", "energy", "ordinary", "term", "means"}),
            mode="explicit",
        )
        document = baba_glossary.DocumentRecord(
            relative_path="sample.html",
            title="Sample",
            paragraphs=(),
        )
        paragraph = baba_glossary.ParagraphRecord(
            anchor="p1",
            ordinal=0,
            text="The term chakra energy means a subtle force.",
            raw_fragment="<i>chakra energy</i>",
        )
        candidates: dict[str, baba_glossary.CandidateAccumulator] = {}
        baba_glossary.add_annotated_surface(
            candidates,
            "chakra energy",
            "italic",
            document,
            paragraph,
            baseline,
            annotation_index=0,
            max_evidence=4,
        )
        self.assertIn("chakra energy", candidates)

        known_definition = baba_glossary.nearby_definition_tokens(
            "zebra means an animal with stripes.",
            baba_glossary.tokens("zebra means an animal with stripes."),
            baba_glossary.DictionaryData(
                words=frozenset({"zebra", "means", "animal", "with", "stripes"}),
                mode="explicit",
            ),
        )
        self.assertEqual([token.normalized for token in known_definition], ["zebra"])

    def test_long_quoted_text_is_not_emitted_as_one_entry(self):
        baseline = baba_glossary.DictionaryData(
            words=frozenset({"ordinary", "english", "words", "through", "text"}),
            mode="explicit",
        )
        document = baba_glossary.DocumentRecord(
            relative_path="sample.html",
            title="Sample",
            paragraphs=(),
        )
        paragraph = baba_glossary.ParagraphRecord(
            anchor="p1",
            ordinal=0,
            text="ordinary kaoshiki words through ordinary text",
            raw_fragment="",
        )
        candidates: dict[str, baba_glossary.CandidateAccumulator] = {}
        long_quote = "ordinary kaoshiki words through ordinary text"
        baba_glossary.add_annotated_surface(
            candidates,
            long_quote,
            "quoted",
            document,
            paragraph,
            baseline,
            annotation_index=0,
            max_evidence=4,
        )
        self.assertNotIn("ordinary kaoshiki words through ordinary text", candidates)
        self.assertIn("kaoshiki", candidates)

    def test_merged_baseline_records_coca_and_wordfreq_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coca_path = root / "coca.txt"
            coca_path.write_text("rank\tword\nfreq\n1\tordinary\n", encoding="utf-8")
            with mock.patch.object(
                baba_glossary,
                "make_wordfreq_lookup",
                return_value=lambda term: 5.0 if term == "frequent" else 0.0,
            ):
                baseline = baba_glossary.load_english_baseline(
                    wordfreq=True,
                    coca_path=coca_path,
                )
        self.assertEqual(baseline.mode, "merged")
        self.assertIn("ordinary", baseline.words)
        self.assertTrue(baseline.contains("frequent"))
        self.assertFalse(baseline.contains("rareterm"))
        self.assertEqual(
            [source["kind"] for source in baseline.sources],
            ["dictionary", "coca", "wordfreq"],
        )

    def test_cli_renders_json_to_output_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discourse_root, dictionary_path = self.write_fixture(root)
            output_path = root / "glossary.json"
            exit_code = baba_glossary.main(
                [
                    str(discourse_root),
                    "--dictionary",
                    str(dictionary_path),
                    "--output",
                    str(output_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            parsed = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["dictionary"]["mode"], "explicit")
            self.assertIn("candidates", parsed)


if __name__ == "__main__":
    unittest.main()
