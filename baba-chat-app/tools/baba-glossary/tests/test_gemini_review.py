from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

import gemini_review


class GeminiReviewTests(unittest.TestCase):
    def sample_payload(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "candidates": [
                {
                    "canonical_surface_form": "kaoshiki nrtya",
                    "normalized_form": "kaoshiki nrtya",
                    "reason_codes": ["italic", "multiword_non_english"],
                    "evidence_contexts": [
                        {"context": "This must not enter the compact audit prompt."}
                    ],
                    "surface_frequency": {"kaoshiki nrtya": 3},
                },
                {
                    "canonical_surface_form": "ordinary",
                    "normalized_form": "ordinary",
                    "reason_codes": ["not_in_english_baseline"],
                    "evidence_contexts": [],
                    "surface_frequency": {"ordinary": 1},
                },
            ],
        }

    def test_context_rich_prompt_includes_evidence_and_omits_frequency_maps(self):
        candidates = gemini_review.compact_candidates(self.sample_payload())
        prompt = gemini_review.build_review_prompt(candidates, glossary_sha256="abc")

        self.assertEqual(len(candidates), 2)
        self.assertIn('"term":"kaoshiki nrtya"', prompt)
        self.assertIn('"term":"ordinary"', prompt)
        self.assertIn("This must not enter", prompt)
        self.assertIn('"evidence"', prompt)
        self.assertNotIn("surface_frequency", prompt)

    def test_batches_keep_each_candidate_with_its_evidence(self):
        candidates = gemini_review.compact_candidates(self.sample_payload())
        batches = gemini_review.pack_candidate_batches(
            candidates,
            max_input_tokens=2_100,
        )

        self.assertGreaterEqual(len(batches), 2)
        self.assertEqual(
            [candidate["candidate_number"] for batch in batches for candidate in batch],
            [1, 2],
        )
        self.assertEqual(
            batches[0][0]["evidence_contexts"][0]["text"],
            "This must not enter the compact audit prompt.",
        )

    def test_validation_resolves_candidate_identity_and_rejects_bad_references(self):
        candidates = gemini_review.compact_candidates(self.sample_payload())
        review = gemini_review.validate_review(
            {
                "findings": [
                    {
                        "candidate_number": 2,
                        "action": "remove_ordinary_english",
                        "reason": "This is an ordinary English word.",
                        "confidence": "high",
                    },
                    {
                        "candidate_number": 999,
                        "action": "remove_ordinary_english",
                        "reason": "Unknown candidate.",
                        "confidence": "high",
                    },
                ]
            },
            candidates,
        )

        finding = review["findings"][0]
        self.assertEqual(finding["normalized_form"], "ordinary")
        self.assertEqual(finding["candidate_key"], gemini_review.candidate_key("ordinary"))
        self.assertEqual(review["summary"]["action_counts"], {"remove_ordinary_english": 1})
        self.assertEqual(len(review["validation_warnings"]), 1)

    def test_review_glossary_preserves_input_hash_and_uses_injected_generator(self):
        with tempfile.TemporaryDirectory() as temporary:
            glossary_path = Path(temporary) / "glossary.json"
            glossary_path.write_text(
                json.dumps(self.sample_payload(), ensure_ascii=False), encoding="utf-8"
            )
            seen: dict[str, object] = {}

            def fake_generator(prompt: str, **kwargs: object):
                seen["prompt"] = prompt
                seen["kwargs"] = kwargs
                return (
                    json.dumps(
                        {
                            "findings": [
                                {
                                    "candidate_number": 2,
                                    "action": "remove_ordinary_english",
                                    "reason": "It is ordinary English.",
                                    "confidence": "high",
                                }
                            ]
                        }
                    ),
                    {"total_token_count": 42},
                )

            result = gemini_review.review_glossary(
                glossary_path,
                project="project-test",
                generator=fake_generator,
            )

            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(result["batch_count"], 1)
            self.assertEqual(result["usage"]["total_token_count"], 42)
            self.assertEqual(
                result["review"]["findings"][0]["normalized_form"], "ordinary"
            )
            self.assertIn("kaoshiki nrtya", seen["prompt"])
            self.assertEqual(seen["kwargs"]["project"], "project-test")


if __name__ == "__main__":
    unittest.main()
