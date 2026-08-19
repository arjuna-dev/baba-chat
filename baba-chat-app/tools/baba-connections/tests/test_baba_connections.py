from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))

from baba_connections import (  # noqa: E402
    build_aggregate_prompt,
    build_extraction_prompt,
    build_mixed_extraction_prompt,
    build_mixed_relationship_prompt,
    deterministic_claim_id,
    load_mixed_document,
    load_discourse,
    validate_aggregate,
    validate_extraction,
    validate_mixed_extraction,
)


class ConnectionsPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "Discourses"
        self.root.mkdir()
        self.stories_root = Path(self.temp_dir.name) / "stories"
        self.other_books_root = Path(self.temp_dir.name) / "other-books"
        self.acharya_root = Path(self.temp_dir.name) / "acharya"
        self.stories_root.mkdir()
        self.other_books_root.mkdir()
        self.acharya_root.mkdir()
        self.path = self.root / "Test_Discourse.html"
        self.path.write_text(
            """<html><head><title>Test Discourse</title></head><body>
<div class="discourse_title">Test Discourse</div>
<!-- block a=1 type=paragraph -->A short but meaningful definition.<!-- /block -->
<!-- block a=2 type=paragraph -->The source says that disciplined action changes the direction of the mind when it is guided by a clear ideal.<!-- /block -->
</body></html>""",
            encoding="utf-8",
        )
        self.source = load_discourse(self.path, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_load_discourse_keeps_short_nonempty_paragraphs_and_stable_ids(self) -> None:
        self.assertEqual(self.source.title, "Test Discourse")
        self.assertEqual(
            [paragraph.paragraph_id for paragraph in self.source.paragraphs],
            ["p0001", "p0002"],
        )
        self.assertEqual(self.source.paragraphs[0].anchor, "1")
        self.assertTrue(self.source.source_id.startswith("discourses:Discourses/"))

    def test_extraction_prompt_is_conservative_and_contains_all_paragraphs(self) -> None:
        prompt = build_extraction_prompt(self.source)
        self.assertIn("Precision is more important than recall", prompt)
        self.assertIn("An empty `items` array is valid", prompt)
        self.assertIn('"paragraph_id":"p0001"', prompt)
        self.assertIn('"paragraph_id":"p0002"', prompt)

    def test_validate_extraction_rejects_unsupported_quotes_and_assigns_claim_ids(self) -> None:
        raw = {
            "items": [
                {
                    "type": "definition",
                    "statement": "The source gives a definition.",
                    "quote": "A short but meaningful definition.",
                    "paragraph_id": "p0001",
                    "modality": "asserted",
                    "attribution": "primary_speaker",
                    "qualifiers": "",
                    "key_terms": [],
                    "selection_basis": "distinctive_definition",
                },
                {
                    "type": "proposition",
                    "statement": "This is unsupported.",
                    "quote": "This sentence does not exist.",
                    "paragraph_id": "p0002",
                    "modality": "asserted",
                    "attribution": "primary_speaker",
                    "qualifiers": "",
                    "key_terms": [],
                    "selection_basis": "non_obvious_proposition",
                },
            ]
        }
        result = validate_extraction(raw, self.source)
        self.assertEqual(result["validation"]["accepted_item_count"], 1)
        self.assertEqual(result["validation"]["rejected_item_count"], 1)
        self.assertIn("#p0001#c01", result["items"][0]["claim_id"])

    def test_mixed_documents_share_citations_and_deterministic_claim_ids(self) -> None:
        story_path = self.stories_root / "Story.md"
        story_path.write_text(
            """---
title: Story
---
# Story

The narrator describes a distinctive act of compassion that changed the life of a seeker.
""",
            encoding="utf-8",
        )
        other_path = self.other_books_root / "Source.md"
        other_path.write_text(
            """---
title: Source
---
# Source

The author defines consciousness as the witness of changing mental states.
""",
            encoding="utf-8",
        )
        roots = {
            "discourses": self.root,
            "stories": self.stories_root,
            "other_spiritual_books": self.other_books_root,
            "acharya_philosophy": self.acharya_root,
        }
        story = load_mixed_document(
            "stories", "Story.md", category_roots=roots
        )
        other = load_mixed_document(
            "other_spiritual_books", "Source.md", category_roots=roots
        )

        prompt, input_payload = build_mixed_extraction_prompt([story, other], max_items=2)
        self.assertIn(story.document_id, prompt)
        self.assertIn(other.document_id, prompt)
        self.assertEqual(input_payload["documents"][0]["category"], "stories")

        passage = story.passages[0]
        raw = {
            "items": [
                {
                    "document_id": story.document_id,
                    "type": "unique_concept",
                    "statement": "Compassion changes a seeker's life.",
                    "quote": passage.text,
                    "passage_id": passage.passage_id,
                    "modality": "reported",
                    "attribution": "narrator",
                    "qualifiers": "",
                    "key_terms": ["compassion"],
                    "selection_basis": "unique_concept",
                }
            ]
        }
        result = validate_mixed_extraction(raw, [story, other], max_items=2)
        claim = result["items"][0]
        self.assertEqual(claim["citation"], f"{story.relative_path}#{passage.anchor}")
        self.assertEqual(
            claim["claim_id"],
            deterministic_claim_id(story.document_id, passage.passage_id, passage.text),
        )
        self.assertIn("#claim-", claim["claim_id"])

    def test_aggregate_validation_drops_unknown_references(self) -> None:
        claim_ids = {"source-a#p0001#c01", "source-b#p0002#c01"}
        raw = {
            "connections": [
                {
                    "type": "possible_contradiction",
                    "claim_ids": ["source-a#p0001#c01", "source-b#p0002#c01"],
                    "summary": "Two claims may conflict.",
                    "explanation": "The claims use incompatible conditions.",
                    "confidence": "tentative",
                },
                {
                    "type": "supports",
                    "claim_ids": ["source-a#p0001#c01", "unknown"],
                    "summary": "Invalid.",
                    "explanation": "Invalid.",
                    "confidence": "medium",
                },
            ],
            "themes": [
                {
                    "label": "Mind and action",
                    "claim_ids": ["source-a#p0001#c01", "source-b#p0002#c01"],
                    "summary": "Both claims address action and mind.",
                }
            ],
        }
        result = validate_aggregate(raw, claim_ids)
        self.assertEqual(len(result["connections"]), 1)
        self.assertEqual(result["connections"][0]["connection_id"], "conn-001")
        self.assertEqual(len(result["themes"]), 1)
        self.assertTrue(result["validation"]["warnings"])

    def test_aggregate_validation_drops_within_discourse_relationships(self) -> None:
        claim_ids = {
            "source-a#p0001#c01",
            "source-a#p0002#c01",
            "source-b#p0001#c01",
        }
        raw = {
            "connections": [
                {
                    "type": "extends",
                    "claim_ids": ["source-a#p0001#c01", "source-a#p0002#c01"],
                    "summary": "Internal relationship.",
                    "explanation": "This stays inside one discourse.",
                    "confidence": "high",
                },
                {
                    "type": "extends",
                    "claim_ids": ["source-a#p0001#c01", "source-b#p0001#c01"],
                    "summary": "Cross-discourse relationship.",
                    "explanation": "This spans two source files.",
                    "confidence": "medium",
                },
            ],
            "themes": [
                {
                    "label": "Internal",
                    "claim_ids": ["source-a#p0001#c01", "source-a#p0002#c01"],
                    "summary": "Internal theme.",
                },
                {
                    "label": "Cross-source",
                    "claim_ids": ["source-a#p0001#c01", "source-b#p0001#c01"],
                    "summary": "Cross-source theme.",
                },
            ],
        }
        result = validate_aggregate(raw, claim_ids)
        self.assertEqual(len(result["connections"]), 1)
        self.assertEqual(len(result["themes"]), 1)
        self.assertEqual(result["scope"], "cross-discourse-only")
        self.assertTrue(
            any("within one discourse" in warning for warning in result["validation"]["warnings"])
        )

    def test_aggregate_prompt_requires_non_forced_connections(self) -> None:
        extraction = {
            "source": self.source.metadata(),
            "items": [
                {
                    "claim_id": "discourses:Discourses/Test_Discourse.html#p0001#c01",
                    "statement": "A claim.",
                    "quote": "A short but meaningful definition.",
                }
            ],
        }
        prompt = build_aggregate_prompt([extraction, extraction])
        self.assertIn("Do not force a connection", prompt)
        self.assertIn("possible_contradiction", prompt)
        self.assertIn("claim_id", prompt)

    def test_mixed_relationship_prompt_uses_validated_claims_only(self) -> None:
        story_path = self.stories_root / "Story.md"
        story_path.write_text(
            """---
title: Story
---
# Story

The narrator describes a distinctive act of compassion that changed the life of a seeker.
""",
            encoding="utf-8",
        )
        other_path = self.other_books_root / "Source.md"
        other_path.write_text(
            """---
title: Source
---
# Source

The author defines consciousness as the witness of changing mental states.
""",
            encoding="utf-8",
        )
        roots = {
            "discourses": self.root,
            "stories": self.stories_root,
            "other_spiritual_books": self.other_books_root,
            "acharya_philosophy": self.acharya_root,
        }
        story = load_mixed_document("stories", "Story.md", category_roots=roots)
        other = load_mixed_document(
            "other_spiritual_books", "Source.md", category_roots=roots
        )
        story_claim = {
            "claim_id": f"{story.document_id}#p0001#claim-story",
            "document_id": story.document_id,
            "category": story.category,
            "citation": f"{story.relative_path}#1",
            "quote": story.passages[0].text,
            "statement": "Compassion changes a seeker's life.",
        }
        other_claim = {
            "claim_id": f"{other.document_id}#p0001#claim-other",
            "document_id": other.document_id,
            "category": other.category,
            "citation": f"{other.relative_path}#1",
            "quote": other.passages[0].text,
            "statement": "Consciousness witnesses changing states.",
        }
        prompt, payload = build_mixed_relationship_prompt(
            {
                "documents": [story.metadata(), other.metadata()],
                "items": [
                    {**story_claim, "source_path": "/local/story.md"},
                    other_claim,
                ],
            }
        )
        self.assertIn("VALIDATED_MIXED_CORPUS_CLAIMS", prompt)
        self.assertIn(story_claim["claim_id"], prompt)
        self.assertIn(other_claim["claim_id"], prompt)
        self.assertEqual(payload["result_type"], "validated-mixed-corpus-claims")
        self.assertNotIn("source_path", payload["claims"][0])

    def test_aggregate_validation_limits_relationship_size_when_requested(self) -> None:
        claim_ids = {f"source-{index}#p0001#c01" for index in range(6)}
        raw = {
            "connections": [
                {
                    "type": "conceptual_parallel",
                    "claim_ids": sorted(claim_ids),
                    "summary": "Too broad.",
                    "explanation": "The proposed group is larger than the experiment permits.",
                    "confidence": "tentative",
                }
            ],
            "themes": [],
        }
        result = validate_aggregate(
            raw,
            claim_ids,
            result_type="cross-corpus-relationships",
            scope="cross-document-only",
            max_claims_per_connection=5,
        )
        self.assertEqual(result["result_type"], "cross-corpus-relationships")
        self.assertEqual(result["connections"], [])
        self.assertTrue(result["validation"]["warnings"])


if __name__ == "__main__":
    unittest.main()
