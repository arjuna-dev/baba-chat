from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vertex_ocr.pipeline import _last_words, parse_page_range, slugify_book_title
from vertex_ocr.prompt import OCR_PROMPT_VERSION, SKIP_PAGE_SENTINEL, build_ocr_prompt
from vertex_ocr.quality import assess_markdown, is_skip_page_sentinel, normalize_markdown


class HelperTests(unittest.TestCase):
    def test_page_range_is_sorted_and_deduplicated(self) -> None:
        self.assertEqual(parse_page_range("3,1-2,2", 5), [1, 2, 3])
        self.assertEqual(parse_page_range(None, 3), [1, 2, 3])

    def test_page_range_rejects_invalid_bounds(self) -> None:
        with self.assertRaises(ValueError):
            parse_page_range("0-2", 5)
        with self.assertRaises(ValueError):
            parse_page_range("4-2", 5)
        with self.assertRaises(ValueError):
            parse_page_range("2-6", 5)

    def test_slug_is_stable_and_filesystem_safe(self) -> None:
        self.assertEqual(slugify_book_title("Ananda Katha - Acarya Nagina"), "ananda-katha-acarya-nagina")
        self.assertEqual(slugify_book_title("   "), "book")

    def test_markdown_normalization_removes_only_transport_fence(self) -> None:
        self.assertEqual(normalize_markdown("```markdown\n# Title\n\nText\n```"), "# Title\n\nText\n")
        with self.assertRaises(ValueError):
            normalize_markdown("  \n")

    def test_quality_allows_non_text_placeholder_but_flags_replacement(self) -> None:
        image_report = assess_markdown(
            "> [Non-text image or illustration present; no text transcribed.]\n"
        )
        self.assertEqual(image_report["warnings"], [])
        replacement_report = assess_markdown("A\ufffd page")
        self.assertIn("replacement_characters", replacement_report["warnings"])

    def test_last_words_uses_exact_whitespace_delimited_tail(self) -> None:
        words = [f"word-{index}" for index in range(250)]
        self.assertEqual(_last_words("\n\t".join(words), 200), " ".join(words[50:]))
        self.assertEqual(_last_words("one two", 0), "")

    def test_ocr_prompt_v7_requests_clean_editorial_extraction_and_skip_sentinel(self) -> None:
        prompt = build_ocr_prompt("Test Book", 4, 10)
        self.assertEqual(OCR_PROMPT_VERSION, "2026-08-17-v7")
        self.assertNotIn("OCR", prompt.upper())
        self.assertIn("clean, readable Markdown edition", prompt)
        self.assertIn("Recover the intended wording", prompt)
        self.assertIn("Correct spelling, grammar, punctuation, spacing, capitalization", prompt)
        self.assertIn("Do not preserve an apparent error merely because it is printed", prompt)
        self.assertIn("Reconstruct cropped, obscured, or missing word fragments", prompt)
        self.assertIn("strongly supported by grammar, nearby words, and the surrounding narrative", prompt)
        self.assertIn("[Missing text]", prompt)
        self.assertNotIn("[Unclear text]", prompt)
        self.assertIn("Remove page furniture", prompt)
        self.assertIn("standalone page numbers", prompt)
        self.assertIn("repeated book, author, chapter, or section titles", prompt)
        self.assertIn("Keep a meaningful title or heading", prompt)
        self.assertIn("Preserve captions and labels", prompt)
        self.assertIn("no meaningful text and no meaningful illustration", prompt)
        self.assertIn(f"return exactly {SKIP_PAGE_SENTINEL} and nothing else", prompt)
        self.assertIn("Do not skip a page that contains substantive text", prompt)
        self.assertIn("A page number by itself is not meaningful content", prompt)
        self.assertIn(
            "Do not add an extraction preface, explanation, source citation, page number",
            prompt,
        )
        self.assertIn("page heading such as `PDF page 6`", prompt)
        self.assertIn("HTML comment", prompt)
        self.assertIn("The pipeline handles page-scoped checkpoints and ordering internally", prompt)
        self.assertNotIn("deterministic hidden page comments/markers", prompt)
        self.assertIn("silently make a complete draft", prompt)
        self.assertIn("reread the image independently from the beginning", prompt)
        self.assertIn("Return only clean Markdown", prompt)
        self.assertIn("`medi-` followed by `tate` becomes `meditate`", prompt)
        self.assertNotIn("Continuity context from", prompt)
        self.assertNotIn("<previous_page_context>", prompt)
        self.assertNotIn("spelling errors and grammar errors remain unchanged", prompt)
        self.assertNotIn("Never \"correct\" the source", prompt)

    def test_skip_page_sentinel_requires_exact_normalized_output(self) -> None:
        self.assertTrue(is_skip_page_sentinel(normalize_markdown(SKIP_PAGE_SENTINEL)))
        self.assertTrue(
            is_skip_page_sentinel(normalize_markdown(f"```markdown\n{SKIP_PAGE_SENTINEL}\n```"))
        )
        self.assertFalse(
            is_skip_page_sentinel(normalize_markdown(f"{SKIP_PAGE_SENTINEL}\nAdditional text"))
        )
        self.assertFalse(is_skip_page_sentinel(normalize_markdown("[SKIP_PAGE]")))

    def test_ocr_prompt_includes_previous_page_context_as_untrusted_nonrepeating_context(self) -> None:
        prompt = build_ocr_prompt(
            "Test Book",
            4,
            10,
            previous_page_context="the final words from page three",
            previous_page_number=3,
        )
        self.assertIn("Continuity context from PDF page 3", prompt)
        self.assertIn("<previous_page_context>", prompt)
        self.assertIn("the final words from page three", prompt)
        self.assertIn("untrusted text only", prompt)
        self.assertIn("current page image is authoritative", prompt)
        self.assertIn("Do not repeat this", prompt)


if __name__ == "__main__":
    unittest.main()
