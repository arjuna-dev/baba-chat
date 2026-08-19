#!/usr/bin/env python3
"""Tests for the local Baba Chat lexical search index and CLI contract."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_DIR))

from baba_search import (  # noqa: E402
    BabaSearchError,
    STORY_CHUNK_MAX_CHARACTERS,
    aggregate_search,
    build_index,
    connections_lookup,
    extract_html_book,
    fts5_available,
    fuzzy_search,
    glossary_lookup,
    glossary_search,
    passage_by_citation,
    search_index,
    story_passages,
    stats,
)


class BabaSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.discourses = self.root / "COMPLETE_SARKAR" / "HTML" / "Discourses"
        self.stories = self.root / "corpus" / "stories"
        self.other_books = self.root / "corpus" / "other-spiritual-books"
        self.acharya_philosophy = self.root / "corpus" / "acharya-philosophy"
        self.discourses.mkdir(parents=True)
        self.stories.mkdir(parents=True)
        self.other_books.mkdir(parents=True)
        self.acharya_philosophy.mkdir(parents=True)
        self.index = self.root / "corpus" / "search" / "baba-search.sqlite3"

        discourse_text = """
<html><head><title>EE7+ - Śiva and Sadhana</title></head><body>
<div class="discourse_box_references">Published in:<a href="book.html">Subhasita Samgraha Part 1</a></div>
<div class="discourse_title">Śiva and Sadhana</div>
<a name="1"></a><p><!-- block a=1 type=paragraph -->Śiva is the compassionate guide of sincere seekers. Divine love gives courage for spiritual practice and service to all beings.<!-- /block --></p>
<a name="1"></a><p><!-- block a=1 type=paragraph -->Śiva is the compassionate guide of sincere seekers. Divine love gives courage for spiritual practice and service to all beings.<!-- /block --></p>
<a name="2"></a><p><!-- block a=2 type=paragraph -->A short note.<!-- /block --></p>
</body></html>
"""
        self.discourse_file = self.discourses / "Siva_and_Sadhana.html"
        self.discourse_file.write_text(discourse_text, encoding="utf-8")
        self.discourse_before = self.discourse_file.read_bytes()

        story_text = """---
title: A Story of Baba
---
# A Story of Baba

<!-- page: 1 -->
Baba's divine love was steady and generous. This page describes how a fearful child found courage.

<!-- page: 2 -->
The child remembered that compassionate love and served everyone with a calm mind.
"""
        self.story_file = self.stories / "A Story of Baba.md"
        self.story_file.write_text(story_text, encoding="utf-8")
        self.story_before = self.story_file.read_bytes()

        self.other_book_file = self.other_books / "Comparative Source.md"
        self.other_book_file.write_text(
            """---
title: Comparative Source
---
# Comparative Source

## Non-dual comparison

This comparative source contains a distinctive advaita comparison for the explicit category.
""",
            encoding="utf-8",
        )
        self.acharya_file = self.acharya_philosophy / "Acharya Notes.md"
        self.acharya_file.write_text(
            """---
title: Acharya Notes
---
# Acharya Notes

## Ananda Marga perspective

This is a distinctive acharya perspective for the separate philosophy category.
""",
            encoding="utf-8",
        )

        self.connections_root = self.root / "corpus" / "connections" / "full-corpus"
        (self.connections_root / "relationships").mkdir(parents=True)
        story_anchor = story_passages(self.story_file, self.stories)[2][0].anchor
        self.discourse_claim_id = (
            "discourses:Discourses/Siva_and_Sadhana.html#p0001#claim-alpha"
        )
        self.story_claim_id = (
            "stories:Stories/A Story of Baba.md#p0001#claim-beta"
        )
        self.connections_root.joinpath("claims.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "result_type": "validated-claims",
                    "items": [
                        {
                            "claim_id": self.discourse_claim_id,
                            "document_id": "discourses:Discourses/Siva_and_Sadhana.html",
                            "passage_id": "p0001",
                            "citation": "Discourses/Siva_and_Sadhana.html#1",
                            "type": "proposition",
                            "statement": "Śiva guides sincere seekers with compassionate love.",
                            "quote": "Śiva is the compassionate guide of sincere seekers.",
                            "key_terms": ["Śiva", "compassionate love", "seekers"],
                            "modality": "asserted",
                            "attribution": "primary_speaker",
                            "qualifiers": "none",
                            "selection_basis": "distinctive_proposition",
                        },
                        {
                            "claim_id": self.story_claim_id,
                            "document_id": "stories:Stories/A Story of Baba.md",
                            "passage_id": "p0001",
                            "citation": f"Stories/A Story of Baba.md#{story_anchor}",
                            "type": "proposition",
                            "statement": "Divine love gives courage for service.",
                            "quote": "Baba's divine love was steady and generous.",
                            "key_terms": ["divine love", "courage", "service"],
                            "modality": "asserted",
                            "attribution": "story_narrator",
                            "qualifiers": "none",
                            "selection_basis": "causal_claim",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.connections_root.joinpath("relationships", "result.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "result_type": "cross-document-relationships",
                    "connections": [
                        {
                            "connection_id": "conn-test-001",
                            "type": "supports",
                            "confidence": "high",
                            "summary": "Compassionate love connects spiritual courage and service.",
                            "explanation": "The discourse and story describe love as a source of courage that supports service.",
                            "claim_ids": [self.discourse_claim_id, self.story_claim_id],
                        }
                    ],
                    "themes": [
                        {
                            "theme_id": "theme-test-001",
                            "label": "Love, courage, and service",
                            "summary": "Spiritual love is linked with courageous service.",
                            "claim_ids": [self.discourse_claim_id, self.story_claim_id],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.glossary_file = self.root / "glossary-candidates.json"
        self.glossary_file.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "candidate_count": 4,
                    "candidates": [
                        {
                            "normalized_form": "kaoshiki nrtya",
                            "canonical_surface_form": "Kaoshiki Nrtya",
                            "variants": ["kaosikii nrtya"],
                            "reason_codes": ["multiword_non_english"],
                            "evidence_contexts": [
                                {
                                    "title": "Dance and Spiritual Practice",
                                    "context": "Kaoshiki Nrtya is a spiritual dance.",
                                }
                            ],
                            "document_count": 2,
                            "frequency": 4,
                            "surface_frequency": {"Kaoshiki Nrtya": 4},
                        },
                        {
                            "normalized_form": "sadhana",
                            "canonical_surface_form": "Sádhaná",
                            "variants": ["sadhana"],
                            "reason_codes": ["diacritic"],
                            "evidence_contexts": [
                                {
                                    "title": "Sadhana",
                                    "context": "Sadhana means sustained spiritual effort.",
                                }
                            ],
                            "document_count": 3,
                            "frequency": 9,
                            "surface_frequency": {"Sádhaná": 9},
                        },
                        {
                            "normalized_form": "yoga practice",
                            "canonical_surface_form": "Yoga Practice",
                            "variants": [],
                            "reason_codes": ["multiword_non_english"],
                            "evidence_contexts": [
                                {
                                    "title": "Yoga",
                                    "context": "Yoga practice requires discipline.",
                                }
                            ],
                            "document_count": 1,
                            "frequency": 2,
                            "surface_frequency": {"Yoga Practice": 2},
                        },
                        {
                            "normalized_form": "advanced yoga practice",
                            "canonical_surface_form": "Advanced Yoga Practice",
                            "variants": [],
                            "reason_codes": ["definition_context"],
                            "evidence_contexts": [
                                {
                                    "title": "Advanced Yoga",
                                    "context": "Advanced yoga practice calls for care.",
                                }
                            ],
                            "document_count": 1,
                            "frequency": 1,
                            "surface_frequency": {"Advanced Yoga Practice": 1},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_extracts_titles_books_anchors_and_deduplicates(self) -> None:
        payload = build_index(self.index, self.discourses, self.stories, force_fts5=False)
        self.assertEqual(payload["index_mode"], "scan")
        self.assertEqual(payload["sources"]["discourses"]["files_seen"], 1)
        self.assertEqual(payload["sources"]["discourses"]["documents"], 1)
        self.assertEqual(payload["sources"]["discourses"]["passages"], 1)
        self.assertEqual(payload["sources"]["discourses"]["duplicates"], 1)
        self.assertEqual(payload["sources"]["stories"]["passages"], 1)
        self.assertEqual(self.discourse_file.read_bytes(), self.discourse_before)
        self.assertEqual(self.story_file.read_bytes(), self.story_before)

    def test_index_ingests_graph_and_links_claims_to_exact_source_text(self) -> None:
        payload = build_index(
            self.index,
            self.discourses,
            self.stories,
            force_fts5=False,
            connections_root=self.connections_root,
        )

        self.assertEqual(payload["graph"]["status"], "indexed")
        self.assertEqual(payload["graph"]["claims"], 2)
        self.assertEqual(payload["graph"]["connections"], 1)
        self.assertEqual(payload["graph"]["themes"], 1)
        self.assertEqual(payload["graph"]["source_passages"], 2)

        result = connections_lookup(
            self.index,
            source="all",
            query="compassionate guide",
            limit=5,
        )

        self.assertEqual(result["graph_status"], "indexed")
        self.assertEqual(result["connection_count"], 1)
        self.assertEqual(result["theme_count"], 1)
        connection = result["connections"][0]
        self.assertEqual(connection["connection_id"], "conn-test-001")
        self.assertEqual(connection["type"], "supports")
        self.assertEqual(connection["confidence"], "high")
        self.assertEqual(
            connection["claim_ids"],
            [self.discourse_claim_id, self.story_claim_id],
        )
        discourse_claim = next(
            claim
            for claim in connection["claims"]
            if claim["claim_id"] == self.discourse_claim_id
        )
        self.assertEqual(
            discourse_claim["citation"],
            "Discourses/Siva_and_Sadhana.html#1",
        )
        self.assertTrue(discourse_claim["source_text_found"])
        self.assertIn("compassionate guide", discourse_claim["source_text"])
        self.assertEqual(result["claims"][0]["claim_id"], self.discourse_claim_id)

    def test_connections_claim_id_returns_related_records_and_source_scope(self) -> None:
        build_index(
            self.index,
            self.discourses,
            self.stories,
            force_fts5=False,
            connections_root=self.connections_root,
        )

        result = connections_lookup(
            self.index,
            source="default",
            claim_id=self.story_claim_id,
            limit=5,
        )

        self.assertEqual(result["query"], None)
        self.assertEqual(result["claim_id"], self.story_claim_id)
        self.assertEqual(result["connection_count"], 1)
        self.assertEqual(result["theme_count"], 1)
        self.assertEqual(result["claim_count"], 2)
        self.assertEqual(
            result["themes"][0]["theme_id"],
            "theme-test-001",
        )
        story_claim = next(
            claim for claim in result["claims"] if claim["claim_id"] == self.story_claim_id
        )
        self.assertEqual(story_claim["source"], "stories")
        self.assertIn("divine love", story_claim["source_text"])

    def test_index_without_graph_artifact_is_still_valid(self) -> None:
        payload = build_index(self.index, self.discourses, self.stories, force_fts5=False)
        self.assertEqual(payload["graph"]["status"], "absent")
        self.assertEqual(payload["graph"]["claims"], 0)

        result = connections_lookup(
            self.index,
            source="all",
            query="anything",
        )
        self.assertEqual(result["graph_status"], "absent")
        self.assertEqual(result["result_count"], 0)

    def test_new_categories_are_indexed_but_excluded_from_default_scope(self) -> None:
        build_index(
            self.index,
            self.discourses,
            self.stories,
            force_fts5=False,
            other_spiritual_books_root=self.other_books,
            acharya_philosophy_root=self.acharya_philosophy,
        )

        default_result = search_index(
            self.index,
            source="default",
            raw_query="distinctive advaita",
            limit=5,
        )
        self.assertEqual(default_result["result_count"], 0)

        other_result = search_index(
            self.index,
            source="other_spiritual_books",
            raw_query="distinctive advaita",
            limit=5,
        )
        self.assertEqual(other_result["result_count"], 1)
        self.assertEqual(
            other_result["results"][0]["citation"],
            "Other-Spiritual-Books/Comparative Source.md#section-1/chunk-1",
        )

        acharya_result = search_index(
            self.index,
            source="acharya_philosophy",
            raw_query="distinctive acharya",
            limit=5,
        )
        self.assertEqual(acharya_result["result_count"], 1)
        self.assertEqual(
            acharya_result["results"][0]["citation"],
            "Acharya-Philosophy/Acharya Notes.md#section-1/chunk-1",
        )

        all_result = search_index(
            self.index,
            source="all",
            raw_query="distinctive",
            limit=5,
        )
        self.assertEqual(
            {result["source"] for result in all_result["results"]},
            {"other_spiritual_books", "acharya_philosophy"},
        )

        combined_result = search_index(
            self.index,
            source="other_spiritual_books+acharya_philosophy",
            raw_query="distinctive",
            limit=5,
        )
        self.assertEqual(
            {result["source"] for result in combined_result["results"]},
            {"other_spiritual_books", "acharya_philosophy"},
        )

    def test_diacritic_insensitive_search_and_provenance(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        payload = search_index(
            self.index,
            source="discourses",
            raw_query="siva",
            limit=5,
            context=24,
        )
        self.assertEqual(payload["result_count"], 1)
        result = payload["results"][0]
        self.assertEqual(result["title"], "Śiva and Sadhana")
        self.assertEqual(result["book"], "Subhasita Samgraha Part 1")
        self.assertEqual(result["anchor"], "1")
        self.assertEqual(result["file"], "Discourses/Siva_and_Sadhana.html")
        self.assertEqual(result["citation"], "Discourses/Siva_and_Sadhana.html#1")
        self.assertEqual(result["matched_in"], "text")
        self.assertIn("Śiva", result["snippet"])

    def test_passage_reader_returns_selected_anchor_and_nearby_context(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)

        payload = passage_by_citation(
            self.index,
            "Discourses/Siva_and_Sadhana.html#1",
            context_passages=2,
        )

        self.assertEqual(payload["command"], "passage")
        self.assertEqual(payload["title"], "Śiva and Sadhana")
        self.assertEqual(payload["source"], "discourses")
        self.assertEqual(payload["anchor"], "1")
        self.assertEqual(payload["citation"], "Discourses/Siva_and_Sadhana.html#1")
        self.assertEqual(payload["passage_id"], payload["passages"][0]["passage_id"])
        self.assertTrue(payload["passages"][0]["selected"])
        self.assertIn("compassionate guide", payload["text"])

    def test_passage_reader_rejects_unknown_citation(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)

        with self.assertRaisesRegex(BabaSearchError, "Source passage not found"):
            passage_by_citation(
                self.index,
                "Discourses/Siva_and_Sadhana.html#999",
            )

    def test_fuzzy_search_recovers_a_misspelled_corpus_term(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        payload = fuzzy_search(
            self.index,
            source="discourses",
            raw_query="sadhna",
            limit=5,
            context=24,
        )

        self.assertEqual(payload["command"], "fuzzy")
        self.assertEqual(payload["query"], "sadhna")
        self.assertEqual(payload["suggestions"][0]["input_token"], "sadhna")
        self.assertEqual(
            payload["suggestions"][0]["matches"][0]["term"], "sadhana"
        )
        self.assertTrue(payload["results"])
        self.assertIn("sadhana", payload["queries"])

    def test_fuzzy_search_supports_an_index_without_the_term_table(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        with sqlite3.connect(self.index) as connection:
            connection.execute("DROP TABLE search_terms")
            connection.commit()

        payload = fuzzy_search(
            self.index,
            source="discourses",
            raw_query="sadhna",
            limit=5,
        )

        self.assertTrue(payload["results"])
        self.assertEqual(
            payload["suggestions"][0]["matches"][0]["term"], "sadhana"
        )

    def test_publication_book_stops_at_first_link(self) -> None:
        content = """
<div class="discourse_references">
Published in:<br />
<a href="book.html">Microvitum in a Nutshell [a compilation]</a><!-- /References -->
</div>
<div class="discourse_box_notes">Notes: official source: wrong extra text</div>
"""
        self.assertEqual(
            extract_html_book(content),
            "Microvitum in a Nutshell [a compilation]",
        )

    def test_phrase_multi_term_and_source_filters(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        phrase = search_index(
            self.index,
            source="stories",
            raw_query='"divine love"',
            limit=5,
        )
        self.assertEqual(phrase["result_count"], 1)
        self.assertEqual(phrase["phrases"], ["divine love"])
        self.assertTrue(phrase["results"][0]["phrase_match"])
        self.assertIsNone(phrase["results"][0]["page"])

        multi_term = search_index(
            self.index,
            source="all",
            raw_query="compassionate service",
            limit=5,
            title_filter="Sadhana",
        )
        self.assertEqual(multi_term["result_count"], 1)
        self.assertEqual(multi_term["results"][0]["source"], "discourses")

        book_filter = search_index(
            self.index,
            source="all",
            raw_query="divine",
            limit=5,
            book_filter="subhasita",
        )
        self.assertEqual(book_filter["result_count"], 1)
        self.assertEqual(book_filter["results"][0]["source"], "discourses")

    def test_fts5_and_scan_have_same_ordered_public_results(self) -> None:
        probe = sqlite3.connect(":memory:")
        has_fts5 = fts5_available(probe)
        probe.close()
        if not has_fts5:
            self.skipTest("SQLite FTS5 is not available")

        scan_index = self.root / "scan.sqlite3"
        fts_index = self.root / "fts.sqlite3"
        build_index(scan_index, self.discourses, self.stories, force_fts5=False)
        build_index(fts_index, self.discourses, self.stories, force_fts5=True)
        scan_payload = search_index(scan_index, "all", "love", limit=10)
        fts_payload = search_index(fts_index, "all", "love", limit=10)
        self.assertEqual(scan_payload["results"], fts_payload["results"])

    def test_aggregate_fanout_deduplicates_and_keeps_distinct_documents(self) -> None:
        first_source = self.discourses / "Laboratory_Mind.html"
        first_source.write_text(
            """
<html><head><title>Laboratory Mind</title></head><body>
<div class="discourse_box_references">Published in:<a href="book.html">Mind and Matter</a></div>
<div class="discourse_title">Laboratory Mind</div>
<!-- block a=1 type=paragraph -->The entire physical body can be created in a laboratory, but it is beyond the scope of human endeavour to create mind.<!-- /block -->
</body></html>
""",
            encoding="utf-8",
        )
        second_source = self.discourses / "Manufactured_Mind.html"
        second_source.write_text(
            """
<html><head><title>Manufactured Mind</title></head><body>
<div class="discourse_box_references">Published in:<a href="book.html">Mind and Matter</a></div>
<div class="discourse_title">Manufactured Mind</div>
<!-- block a=2 type=paragraph -->Whatever a person manufactures contains only physical strength; it does not possess any psychic strength. A future object may possess a mind, but the mind of its creator will be stronger.<!-- /block -->
</body></html>
""",
            encoding="utf-8",
        )
        build_index(self.index, self.discourses, self.stories, force_fts5=False)

        payload = aggregate_search(
            self.index,
            source="discourses",
            queries=(
                '"create mind"',
                '"mind of its creator"',
                '"physical strength" "psychic strength"',
            ),
            limit=10,
            per_query_limit=5,
            context=180,
            max_per_document=1,
        )

        self.assertEqual(payload["query_count"], 3)
        self.assertEqual(payload["distinct_documents"], 2)
        self.assertEqual(payload["result_count"], 2)
        citations = {result["citation"] for result in payload["results"]}
        self.assertIn("Discourses/Laboratory_Mind.html#1", citations)
        self.assertIn("Discourses/Manufactured_Mind.html#2", citations)
        manufactured = next(
            result
            for result in payload["results"]
            if result["title"] == "Manufactured Mind"
        )
        self.assertEqual(manufactured["query_hits"], 2)
        self.assertIn('"mind of its creator"', manufactured["matched_queries"])
        self.assertIn(
            '"physical strength" "psychic strength"',
            manufactured["matched_queries"],
        )

    def test_aggregate_wrapper_emits_cross_query_metadata(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [
                str(wrapper),
                "aggregate",
                "--index",
                str(self.index),
                "--source",
                "stories",
                "--query",
                '"divine love"',
                "--query",
                "fearful child",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["query_count"], 2)
        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(payload["results"][0]["query_hits"], 2)

    def test_story_sections_preserve_markdown_structure_without_page_metadata(self) -> None:
        story_file = self.stories / "Structured Story.md"
        story_file.write_text(
            """---
title: Structured Story
---
# Structured Story

<!-- page: 1 -->
## Arrival

The first meaningful paragraph introduces the arrival.

- A list item keeps its structure.
- A second list item remains searchable.

> A quoted passage remains clearly marked.

### PDF page 2

A caption describes a painted portrait of Baba.

## Reflection

The second section contains a reflective closing paragraph.
""",
            encoding="utf-8",
        )

        title, book, passages = story_passages(story_file, self.stories)

        self.assertEqual(title, "Structured Story")
        self.assertEqual(book, "Structured Story")
        self.assertEqual(
            [passage.anchor for passage in passages],
            ["section-1/chunk-1", "section-2/chunk-1"],
        )
        self.assertTrue(all(passage.page is None for passage in passages))
        first_text = passages[0].text
        self.assertIn("## Arrival", first_text)
        self.assertIn("- A list item keeps its structure.", first_text)
        self.assertIn("> A quoted passage remains clearly marked.", first_text)
        self.assertIn("A caption describes a painted portrait of Baba.", first_text)
        self.assertNotIn("page: 1", first_text.lower())
        self.assertNotIn("pdf page 2", first_text.lower())

    def test_story_paragraphs_are_grouped_into_bounded_chunks(self) -> None:
        story_file = self.stories / "Windowed Story.md"
        paragraphs = [
            "Alpha lantern paragraph establishes the first part of the journey.",
            "Beta river paragraph continues the journey with a careful observation.",
            "Gamma mountain paragraph describes the next setting in the story.",
            "Delta garden paragraph records a conversation beside the old gate.",
            "Epsilon sunrise paragraph closes the section with a quiet resolution.",
        ]
        story_file.write_text(
            "---\ntitle: Windowed Story\n---\n## Journey\n\n"
            + "\n\n".join(paragraphs)
            + "\n",
            encoding="utf-8",
        )

        _, _, passages = story_passages(story_file, self.stories)

        self.assertEqual(
            [passage.anchor for passage in passages],
            ["section-1/chunk-1", "section-1/chunk-2"],
        )
        self.assertLessEqual(
            max(len(passage.text) for passage in passages),
            STORY_CHUNK_MAX_CHARACTERS,
        )
        self.assertIn("Alpha lantern", passages[0].text)
        self.assertIn("Delta garden", passages[0].text)
        self.assertIn("Epsilon sunrise", passages[1].text)
        self.assertTrue(all(passage.page is None for passage in passages))

    def test_aggregate_can_return_multiple_chunks_from_one_story_book(self) -> None:
        story_file = self.stories / "Aggregate Story.md"
        paragraphs = [
            "Alpha lantern opens the first chapter of this story.",
            "Beta river carries the characters toward the village.",
            "Gamma mountain stands beyond the village road.",
            "Delta garden marks the place where the travelers rest.",
            "Omega river closes the story beside the evening fire.",
        ]
        story_file.write_text(
            "---\ntitle: Aggregate Story\n---\n## Journey\n\n"
            + "\n\n".join(paragraphs)
            + "\n",
            encoding="utf-8",
        )
        build_index(self.index, self.discourses, self.stories, force_fts5=False)

        payload = aggregate_search(
            self.index,
            source="stories",
            queries=("alpha lantern", "omega river"),
            limit=10,
            per_query_limit=10,
            max_per_document=0,
        )

        self.assertEqual(payload["result_count"], 2)
        self.assertEqual(payload["distinct_documents"], 1)
        self.assertEqual(
            {result["anchor"] for result in payload["results"]},
            {"section-1/chunk-1", "section-1/chunk-2"},
        )
        self.assertTrue(all(result["page"] is None for result in payload["results"]))

    def test_glossary_lookup_matches_normalized_term_and_preserves_evidence(self) -> None:
        payload = glossary_lookup(self.glossary_file, "SADHANA")

        self.assertEqual(payload["operation"], "lookup")
        self.assertEqual(payload["result_count"], 1)
        result = payload["results"][0]
        self.assertEqual(result["canonical_surface_form"], "Sádhaná")
        self.assertEqual(result["normalized_form"], "sadhana")
        self.assertEqual(result["evidence_contexts"][0]["title"], "Sadhana")

    def test_glossary_lookup_matches_variant_phrase(self) -> None:
        payload = glossary_lookup(self.glossary_file, "kaosikii nrtya")

        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(
            payload["results"][0]["normalized_form"], "kaoshiki nrtya"
        )

    def test_glossary_search_ranks_exact_phrase_before_longer_phrase(self) -> None:
        payload = glossary_search(self.glossary_file, '"yoga practice"', limit=10)

        self.assertEqual(payload["result_count"], 2)
        self.assertEqual(
            [result["normalized_form"] for result in payload["results"]],
            ["yoga practice", "advanced yoga practice"],
        )

    def test_glossary_search_matches_diacritic_insensitive_tokens(self) -> None:
        payload = glossary_search(self.glossary_file, "sádhana")

        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(payload["results"][0]["normalized_form"], "sadhana")

    def test_glossary_missing_or_malformed_file_and_limit_are_errors(self) -> None:
        with self.assertRaisesRegex(BabaSearchError, "Glossary file not found"):
            glossary_lookup(self.root / "missing.json", "sadhana")

        malformed = self.root / "malformed.json"
        malformed.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(BabaSearchError, "top-level candidates array"):
            glossary_search(malformed, "sadhana")

        with self.assertRaisesRegex(BabaSearchError, "between 1 and"):
            glossary_search(self.glossary_file, "sadhana", limit=0)

    def test_glossary_wrapper_emits_compact_json_without_index_argument(self) -> None:
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [
                str(wrapper),
                "glossary",
                "lookup",
                "--glossary",
                str(self.glossary_file),
                "--term",
                "kaosikii nrtya",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["operation"], "lookup")
        self.assertEqual(payload["result_count"], 1)
        self.assertNotIn('": ', completed.stdout.split("\n", 1)[0])

    def test_glossary_wrapper_reports_missing_file(self) -> None:
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [
                str(wrapper),
                "glossary",
                "search",
                "--glossary",
                str(self.root / "missing.json"),
                "--query",
                "sadhana",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("Glossary file not found", completed.stderr)

    def test_executable_wrapper_emits_json(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [
                str(wrapper),
                "search",
                "--index",
                str(self.index),
                "--source",
                "stories",
                "--query",
                "fearful child",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["source"], "stories")
        self.assertEqual(payload["result_count"], 1)

    def test_executable_help_lists_fuzzy_command(self) -> None:
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [str(wrapper), "-h"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("fuzzy", completed.stdout)

    def test_executable_help_lists_connections_command(self) -> None:
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [str(wrapper), "-h"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("connections", completed.stdout)

    def test_connections_wrapper_supports_query_and_claim_id(self) -> None:
        build_index(
            self.index,
            self.discourses,
            self.stories,
            force_fts5=False,
            connections_root=self.connections_root,
        )
        wrapper = MODULE_DIR / "baba-search"
        query_run = subprocess.run(
            [
                str(wrapper),
                "connections",
                "--index",
                str(self.index),
                "--source",
                "all",
                "--query",
                "compassionate guide",
                "--limit",
                "5",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        query_payload = json.loads(query_run.stdout)
        self.assertEqual(query_payload["command"], "connections")
        self.assertEqual(query_payload["connection_count"], 1)
        self.assertEqual(
            query_payload["connections"][0]["connection_id"],
            "conn-test-001",
        )

        claim_run = subprocess.run(
            [
                str(wrapper),
                "connections",
                "--index",
                str(self.index),
                "--claim-id",
                self.story_claim_id,
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        claim_payload = json.loads(claim_run.stdout)
        self.assertEqual(claim_payload["claim_id"], self.story_claim_id)
        self.assertEqual(claim_payload["theme_count"], 1)
        self.assertIn(
            self.story_claim_id,
            claim_payload["connections"][0]["claim_ids"],
        )

    def test_search_help_describes_combined_source_scopes(self) -> None:
        wrapper = MODULE_DIR / "baba-search"
        completed = subprocess.run(
            [str(wrapper), "search", "-h"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("joined with +", completed.stdout)

    def test_stats_reports_built_index(self) -> None:
        build_index(self.index, self.discourses, self.stories, force_fts5=False)
        payload = stats(self.index)
        self.assertEqual(payload["passages"], 2)
        self.assertEqual(payload["sources"]["discourses"]["files_seen"], 1)
        self.assertEqual(payload["sources"]["stories"]["documents"], 1)


if __name__ == "__main__":
    unittest.main()
