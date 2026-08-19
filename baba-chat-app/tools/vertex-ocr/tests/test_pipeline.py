from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vertex_ocr.models import OCRResult
from vertex_ocr.pipeline import BookPipeline, PipelineConfig, PIPELINE_VERSION
from vertex_ocr.prompt import SKIP_PAGE_SENTINEL


class FakeRenderer:
    dpi = 120

    def __init__(self, page_count: int = 3) -> None:
        self.pages = page_count
        self.calls: list[int] = []

    def page_count(self, pdf_path: Path) -> int:
        del pdf_path
        return self.pages

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        del pdf_path
        self.calls.append(page_number)
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"page-{page_number:04d}.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([page_number]) * 64)
        return image_path


class FakeOCR:
    def __init__(
        self,
        *,
        fail_pages: set[int] | None = None,
        page_texts: dict[int, str] | None = None,
    ) -> None:
        self.fail_pages = fail_pages or set()
        self.page_texts = page_texts or {}
        self.calls: list[int] = []
        self.prompts: dict[int, str] = {}

    @staticmethod
    def _page_from_prompt(prompt: str) -> int:
        for line in prompt.splitlines():
            if line.startswith("PDF page:"):
                return int(line.split(":", 1)[1].strip())
        raise AssertionError("page was not included in prompt")

    def transcribe(self, image_path: Path, prompt: str) -> OCRResult:
        del image_path
        page = self._page_from_prompt(prompt)
        self.calls.append(page)
        self.prompts[page] = prompt
        if page in self.fail_pages:
            raise RuntimeError(f"fake failure for page {page}")
        return OCRResult(
            text=self.page_texts.get(
                page,
                f"Extracted prose for source segment {page}.",
            ),
            usage={"prompt_token_count": 10, "candidates_token_count": 8, "total_token_count": 18},
            response_id=f"fake-{page}",
        )


class PipelineTests(unittest.TestCase):
    def _config(self) -> PipelineConfig:
        return PipelineConfig(
            model="test-model",
            project="test-project",
            location="global",
            render_dpi=120,
            workers=2,
            max_in_flight=2,
            max_retries=0,
            backoff_seconds=0,
            previous_page_context_words=0,
        )

    def _context_config(self) -> PipelineConfig:
        return PipelineConfig(
            model="test-model",
            project="test-project",
            location="global",
            render_dpi=120,
            workers=1,
            max_in_flight=1,
            max_retries=0,
            backoff_seconds=0,
            previous_page_context_words=200,
        )

    def test_run_writes_ordered_markdown_raw_cache_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Small Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"
            renderer = FakeRenderer(page_count=3)
            client = FakeOCR(
                page_texts={
                    1: "<!-- page: 1 -->\n\n### PDF page 1\n\nFirst extracted passage.",
                    2: "Second extracted passage.",
                }
            )
            pipeline = BookPipeline(config=self._config(), renderer=renderer, ocr_client=client)

            manifest = pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2],
            )

            self.assertEqual(manifest["summary"]["completed_page_count"], 2)
            self.assertFalse(manifest["summary"]["complete"])
            self.assertEqual(manifest["pipeline_version"], PIPELINE_VERSION)
            self.assertCountEqual(client.calls, [1, 2])
            markdown = (output_dir / "small-book.md").read_text(encoding="utf-8")
            self.assertIn('ocr_thinking_level: "LOW"', markdown)
            self.assertIn('ocr_media_resolution: "ULTRA_HIGH"', markdown)
            self.assertIn("First extracted passage.\n\nSecond extracted passage.", markdown)
            self.assertNotIn("<!-- page:", markdown)
            self.assertNotIn("### PDF page", markdown)
            self.assertNotIn("# Page ", markdown)
            for field in (
                "source_page_count",
                "requested_pages",
                "attempted_pages",
                "completed_pages",
                "skipped_pages",
                "failed_pages",
                "completed_page_count",
                "skipped_page_count",
                "failed_page_count",
                "previous_page_context_words",
            ):
                self.assertNotIn(f"{field}:", markdown)
            self.assertTrue((output_dir / ".ocr/small-book/pages/page-0001.json").is_file())
            self.assertTrue((output_dir / "small-book.manifest.json").is_file())

            raw = json.loads(
                (output_dir / ".ocr/small-book/pages/page-0001.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                raw["text"],
                "<!-- page: 1 -->\n\n### PDF page 1\n\nFirst extracted passage.\n",
            )
            self.assertEqual(raw["raw_version"], 4)
            self.assertEqual(raw["content_identity"]["thinking_level"], "LOW")
            self.assertEqual(raw["content_identity"]["media_resolution"], "ULTRA_HIGH")
            self.assertEqual(raw["content_identity"]["previous_page_context_words"], 0)
            self.assertEqual(raw["previous_page_context_words"], 0)
            self.assertIsNone(raw["previous_page_number"])
            self.assertNotIn("credential", json.dumps(raw).lower())

            manifest = json.loads(
                (output_dir / "small-book.manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["run"]["thinking_level"], "LOW")
            self.assertEqual(manifest["run"]["media_resolution"], "ULTRA_HIGH")
            self.assertEqual(manifest["run"]["previous_page_context_words"], 0)
            self.assertEqual(manifest["run"]["content_identity"]["model"], "test-model")
            self.assertEqual(manifest["manifest_version"], 3)
            state = json.loads(
                (output_dir / ".ocr/small-book/state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["state_version"], 3)
            self.assertEqual(state["pipeline_version"], PIPELINE_VERSION)

    def test_skipped_page_is_checkpointed_omitted_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Skip Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"
            client = FakeOCR(
                page_texts={
                    1: "First extracted passage.",
                    2: SKIP_PAGE_SENTINEL,
                    3: "Third extracted passage.",
                }
            )
            pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=3),
                ocr_client=client,
            )

            manifest = pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2, 3],
            )

            self.assertEqual(manifest["summary"]["completed_page_count"], 2)
            self.assertEqual(manifest["summary"]["skipped_page_count"], 1)
            self.assertEqual(manifest["summary"]["skipped_pages"], [2])
            self.assertEqual(manifest["summary"]["failed_page_count"], 0)
            self.assertTrue(manifest["summary"]["complete"])

            markdown = (output_dir / "skip-book.md").read_text(encoding="utf-8")
            self.assertIn("complete: true", markdown)
            self.assertIn("First extracted passage.\n\nThird extracted passage.", markdown)
            self.assertNotIn("<!-- page:", markdown)
            self.assertNotIn("PDF page", markdown)
            for field in (
                "source_page_count",
                "requested_pages",
                "attempted_pages",
                "completed_pages",
                "skipped_pages",
                "failed_pages",
                "completed_page_count",
                "skipped_page_count",
                "failed_page_count",
                "previous_page_context_words",
            ):
                self.assertNotIn(f"{field}:", markdown)

            raw_page_two_path = output_dir / ".ocr/skip-book/pages/page-0002.json"
            raw_page_two = json.loads(raw_page_two_path.read_text(encoding="utf-8"))
            self.assertEqual(raw_page_two["raw_version"], 4)
            self.assertEqual(raw_page_two["status"], "skipped")
            self.assertEqual(raw_page_two["skip_sentinel"], SKIP_PAGE_SENTINEL)
            self.assertEqual(raw_page_two["usage"]["total_token_count"], 18)
            self.assertEqual(raw_page_two["previous_page_number"], 1)
            page_records = {record["page_number"]: record for record in manifest["pages"]}
            self.assertEqual(page_records[1]["status"], "complete")
            self.assertEqual(page_records[2]["status"], "skipped")
            self.assertEqual(page_records[3]["status"], "complete")
            self.assertNotIn("<previous_page_context>", client.prompts[3])

    def test_skipped_page_checkpoint_recovers_on_resume_without_rerun_or_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Recover Skip Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"

            first_client = FakeOCR(fail_pages={3}, page_texts={2: SKIP_PAGE_SENTINEL})
            first_pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=3),
                ocr_client=first_client,
            )
            first_manifest = first_pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2, 3],
            )
            self.assertEqual(first_manifest["summary"]["skipped_page_count"], 1)
            self.assertEqual(first_manifest["summary"]["failed_page_count"], 1)

            state_path = output_dir / ".ocr/recover-skip-book/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            del state["pages"]["2"]
            state_path.write_text(json.dumps(state), encoding="utf-8")

            second_client = FakeOCR(page_texts={3: "recovered page three"})
            second_pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=3),
                ocr_client=second_client,
            )
            resumed_manifest = second_pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2, 3],
                resume=True,
            )

            self.assertEqual(second_client.calls, [3])
            self.assertEqual(resumed_manifest["summary"]["completed_page_count"], 2)
            self.assertEqual(resumed_manifest["summary"]["skipped_page_count"], 1)
            self.assertEqual(resumed_manifest["summary"]["failed_page_count"], 0)
            self.assertTrue(resumed_manifest["summary"]["complete"])
            self.assertNotIn("<previous_page_context>", second_client.prompts[3])
            recovered_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(recovered_state["pages"]["2"]["status"], "skipped")

    def test_previous_page_context_uses_the_exact_tail_and_immediate_predecessor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Context Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"
            previous_text = " ".join(f"context-word-{index}" for index in range(250))
            client = FakeOCR(page_texts={1: previous_text, 2: "page two"})
            pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=3),
                ocr_client=client,
            )

            manifest = pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2],
            )

            self.assertEqual(manifest["summary"]["completed_page_count"], 2)
            self.assertNotIn("<previous_page_context>", client.prompts[1])
            page_two_prompt = client.prompts[2]
            self.assertIn("Continuity context from PDF page 1", page_two_prompt)
            self.assertIn("context-word-50 context-word-51", page_two_prompt)
            self.assertIn("context-word-249", page_two_prompt)
            self.assertNotIn("context-word-49 context-word-50", page_two_prompt)

            raw_page_two = json.loads(
                (output_dir / ".ocr/context-book/pages/page-0002.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(raw_page_two["previous_page_number"], 1)
            self.assertEqual(raw_page_two["previous_page_context_word_count"], 200)

    def test_noncontiguous_page_selection_omits_unavailable_immediate_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Noncontiguous Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            client = FakeOCR()
            pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=3),
                ocr_client=client,
            )

            pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=root / "output",
                page_selection=[1, 3],
            )

            self.assertNotIn("<previous_page_context>", client.prompts[1])
            self.assertNotIn("<previous_page_context>", client.prompts[3])

    def test_resume_reuses_completed_previous_page_raw_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Resume Context Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"
            previous_text = " ".join(f"resume-word-{index}" for index in range(220))

            first_client = FakeOCR(
                fail_pages={2},
                page_texts={1: previous_text},
            )
            first_pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=2),
                ocr_client=first_client,
            )
            first_pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2],
            )

            second_client = FakeOCR(page_texts={2: "recovered page two"})
            second_pipeline = BookPipeline(
                config=self._context_config(),
                renderer=FakeRenderer(page_count=2),
                ocr_client=second_client,
            )
            resumed_manifest = second_pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2],
                resume=True,
            )

            self.assertEqual(second_client.calls, [2])
            self.assertEqual(resumed_manifest["summary"]["completed_page_count"], 2)
            self.assertIn("Continuity context from PDF page 1", second_client.prompts[2])
            self.assertIn("resume-word-20 resume-word-21", second_client.prompts[2])
            self.assertNotIn("resume-word-19 resume-word-20", second_client.prompts[2])

    def test_resume_skips_complete_pages_and_retries_only_failed_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Resume Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"

            first_client = FakeOCR(fail_pages={2})
            pipeline = BookPipeline(config=self._config(), renderer=FakeRenderer(), ocr_client=first_client)
            first_manifest = pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2],
            )
            self.assertEqual(first_manifest["summary"]["completed_page_count"], 1)
            self.assertEqual(first_manifest["summary"]["failed_page_count"], 1)

            second_client = FakeOCR()
            second_renderer = FakeRenderer()
            resumed = BookPipeline(
                config=self._config(), renderer=second_renderer, ocr_client=second_client
            )
            second_manifest = resumed.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1, 2],
                resume=True,
            )
            self.assertEqual(second_client.calls, [2])
            self.assertEqual(second_manifest["summary"]["completed_page_count"], 2)
            self.assertEqual(second_manifest["summary"]["failed_page_count"], 0)

    def test_resume_reuses_legacy_v6_checkpoint_for_page_free_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Legacy Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"
            legacy_config = PipelineConfig(
                model="test-model",
                project="test-project",
                location="global",
                render_dpi=120,
                workers=2,
                max_in_flight=2,
                max_retries=0,
                backoff_seconds=0,
                previous_page_context_words=0,
                prompt_version="2026-08-17-v6",
            )
            legacy_pipeline = BookPipeline(
                config=legacy_config,
                renderer=FakeRenderer(page_count=1),
                ocr_client=FakeOCR(
                    page_texts={1: "<!-- page: 1 -->\n\nLegacy extracted passage."}
                ),
            )
            legacy_pipeline.run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1],
            )

            state_path = output_dir / ".ocr/legacy-book/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            del state["pages"]["1"]
            state_path.write_text(json.dumps(state), encoding="utf-8")

            resumed_client = FakeOCR()
            resumed_manifest = BookPipeline(
                config=self._config(),
                renderer=FakeRenderer(page_count=1),
                ocr_client=resumed_client,
            ).run_book(
                pdf_path=pdf_path,
                output_dir=output_dir,
                page_selection=[1],
                resume=True,
            )

            self.assertEqual(resumed_client.calls, [])
            self.assertTrue(resumed_manifest["summary"]["complete"])
            markdown = (output_dir / "legacy-book.md").read_text(encoding="utf-8")
            self.assertIn("Legacy extracted passage.", markdown)
            self.assertNotIn("<!-- page:", markdown)

    def test_resume_rejects_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Changed Book.pdf"
            pdf_path.write_bytes(b"original")
            output_dir = root / "output"
            pipeline = BookPipeline(config=self._config(), renderer=FakeRenderer(), ocr_client=FakeOCR())
            pipeline.run_book(pdf_path=pdf_path, output_dir=output_dir, page_selection=[1])
            pdf_path.write_bytes(b"changed")

            with self.assertRaisesRegex(RuntimeError, "Source PDF changed"):
                pipeline.run_book(
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    page_selection=[1],
                    resume=True,
                )

    def test_resume_rejects_orphaned_artifacts_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Orphaned Book.pdf"
            pdf_path.write_bytes(b"original")
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "orphaned-book.md").write_text("old output\n", encoding="utf-8")
            pipeline = BookPipeline(config=self._config(), renderer=FakeRenderer(), ocr_client=FakeOCR())

            with self.assertRaisesRegex(RuntimeError, "no state file"):
                pipeline.run_book(
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    page_selection=[1],
                    resume=True,
                )

    def test_previous_page_context_rejects_concurrent_workers(self) -> None:
        with self.assertRaisesRegex(ValueError, "previous_page_context_words cannot be negative"):
            PipelineConfig(previous_page_context_words=-1)

        with self.assertRaisesRegex(
            ValueError,
            "previous_page_context_words > 0 requires workers=1 and max_in_flight=1",
        ):
            PipelineConfig(previous_page_context_words=200, workers=2, max_in_flight=1)

        with self.assertRaisesRegex(
            ValueError,
            "previous_page_context_words > 0 requires workers=1 and max_in_flight=1",
        ):
            PipelineConfig(previous_page_context_words=200, workers=1, max_in_flight=2)

        concurrent_config = PipelineConfig(previous_page_context_words=0, workers=2, max_in_flight=2)
        self.assertEqual(concurrent_config.previous_page_context_words, 0)

    def test_resume_rejects_changed_thinking_or_media_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            pdf_path = root / "Changed Settings Book.pdf"
            pdf_path.write_bytes(b"fake pdf input")
            output_dir = root / "output"
            pipeline = BookPipeline(config=self._config(), renderer=FakeRenderer(), ocr_client=FakeOCR())
            pipeline.run_book(pdf_path=pdf_path, output_dir=output_dir, page_selection=[1])

            changed_config = PipelineConfig(
                model="test-model",
                project="test-project",
                location="global",
                thinking_level="HIGH",
                media_resolution="HIGH",
                render_dpi=120,
                workers=2,
                max_in_flight=2,
                max_retries=0,
                backoff_seconds=0,
                previous_page_context_words=0,
            )
            resumed = BookPipeline(
                config=changed_config,
                renderer=FakeRenderer(),
                ocr_client=FakeOCR(),
            )
            with self.assertRaisesRegex(RuntimeError, "Content settings changed"):
                resumed.run_book(
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    page_selection=[1],
                    resume=True,
                )


if __name__ == "__main__":
    unittest.main()
