from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vertex_ocr.cli import _manifest_is_healthy, build_parser
from vertex_ocr.pipeline import PipelineConfig


class CliTests(unittest.TestCase):
    def test_new_defaults_use_gemini_37_flash_and_high_fidelity_input(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_GENAI_PREVIOUS_PAGE_CONTEXT_WORDS": "200"}):
            args = build_parser().parse_args(["--input", "book.pdf"])
        self.assertEqual(args.model, "gemini-3.7-flash")
        self.assertEqual(args.thinking_level, "LOW")
        self.assertEqual(args.media_resolution, "ULTRA_HIGH")
        self.assertEqual(args.previous_page_context_words, 200)

    def test_previous_page_context_setting_reads_flag_and_environment(self) -> None:
        args = build_parser().parse_args(
            ["--input", "book.pdf", "--previous-page-context-words", "0"]
        )
        self.assertEqual(args.previous_page_context_words, 0)

        with patch.dict(os.environ, {"GOOGLE_GENAI_PREVIOUS_PAGE_CONTEXT_WORDS": "37"}):
            env_args = build_parser().parse_args(["--input", "book.pdf"])
        self.assertEqual(env_args.previous_page_context_words, 37)

    def test_adaptive_book_worker_flags_are_explicit(self) -> None:
        args = build_parser().parse_args(
            [
                "--input",
                "books",
                "--book-workers",
                "8",
                "--adaptive-book-workers",
            ]
        )
        self.assertEqual(args.book_workers, 8)
        self.assertTrue(args.adaptive_book_workers)

    def test_only_retry_free_books_are_healthy_for_ramping(self) -> None:
        healthy = {
            "summary": {"failed_page_count": 0},
            "pages": [{"retry_count": 0}, {"retry_count": 0}],
        }
        retried = {
            "summary": {"failed_page_count": 0},
            "pages": [{"retry_count": 1}],
        }
        failed = {
            "summary": {"failed_page_count": 1},
            "pages": [{"retry_count": 0}],
        }
        self.assertTrue(_manifest_is_healthy(healthy))
        self.assertFalse(_manifest_is_healthy(retried))
        self.assertFalse(_manifest_is_healthy(failed))

    def test_setting_values_are_canonicalized_by_pipeline_config(self) -> None:
        args = build_parser().parse_args(
            [
                "--input",
                "book.pdf",
                "--thinking-level",
                "medium",
                "--media-resolution",
                "ultra-high",
            ]
        )
        config = PipelineConfig(
            model=args.model,
            thinking_level=args.thinking_level,
            media_resolution=args.media_resolution,
            previous_page_context_words=args.previous_page_context_words,
        )
        self.assertEqual(config.thinking_level, "MEDIUM")
        self.assertEqual(config.media_resolution, "ULTRA_HIGH")


if __name__ == "__main__":
    unittest.main()
