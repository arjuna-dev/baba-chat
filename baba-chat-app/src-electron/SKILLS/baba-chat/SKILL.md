---
name: baba-corpus-research
description: Search the local Baba corpus categories and answer with source-grounded citations.
---

# Baba corpus research

Use this workflow whenever a user asks about content that may appear in the local discourses, story books, comparative spiritual books, or Ananda Marga Acharya philosophy.

1. Read the current turn's `<BABA_SOURCE_SCOPE>` value. It may be `default`, `all`, one category, or a `+`-joined combination such as `discourses+other_spiritual_books`.
2. Do not stop at the first relevant passage. Plan a bounded fan-out across exact wording, verb and noun synonyms, entailment variants, conceptual opposites, and broader follow-up terms.
3. If a rare or specialized query token looks misspelled, or the exact search is weak or empty, use the fuzzy recovery command before concluding that no passage exists:
   `tools/baba-search/baba-search fuzzy --source <scope> --query "<original query>" --json`.
   It compares unknown tokens with words in the indexed corpus, reports likely spellings, and searches with a few corrected queries. Treat the corrections as search hypotheses only. Keep the original wording in mind and do not silently rewrite the user's question.
4. Use the glossary only when terminology clues or source context are still needed. Do not read the entire `corpus/search/glossary-candidates.json` directly; it is large and is not a definitions database. First run an exact terminology lookup:
   `tools/baba-search/baba-search glossary lookup --term "<term>" --json`
   Then run broader candidate discovery for the relevant phrase:
   `tools/baba-search/baba-search glossary search --query "<phrase>" --json`.
   Treat the returned `canonical_surface_form`, `normalized_form`, `variants`, `reason_codes`, and evidence contexts as clues for search expansion only, not as an authority for definitions. Search multiword specialized terms as a single phrase, including when two or more non-English terms occur together; do not split them into separate terms unless also running a separate broader search.
5. Pass useful fuzzy replacements, glossary aliases, and the user's original wording into the local aggregator as separate queries when further corroboration is needed. For example:
   `tools/baba-search/baba-search aggregate --source <scope> --query "<exact phrase>" --query "<synonym variant>" --query "<broader variant>" --max-per-document 1 --json`.
6. Use three to six compact searches. Inspect `matched_queries`, `query_evidence`, and distinct `document_key` values. If the first pass points to a document that needs more context, run a targeted follow-up with `--max-per-document 0` or a higher cap.
7. Search both sides of a qualification. For example, when a passage says something cannot be manufactured, also search what a manufactured object may possess, what its creator possesses, and related physical or psychic terms.
8. Use the knowledge graph for questions that require synthesis across multiple claims or source documents, especially when the user asks for a cross-source comparison, conceptual parallels, shared themes, whether one teaching supports, qualifies, or contrasts with another, or possible contradictions, tensions, exceptions, or unresolved differences. Run:
   `tools/baba-search/baba-search connections --source <scope> --query "<question>" --json`
   Use the user's question, or a focused comparison derived from it, as `--query`. Pass the current `<BABA_SOURCE_SCOPE>` value unchanged as `<scope>`; do not broaden the selected source scope just because the graph could contain relationships in other categories. Use ordinary search when a direct passage is enough, and use the graph when the answer depends on relationships among passages or documents.
9. Treat every graph relationship and theme as a hypothesis for investigation, not as an established fact. Graph results are grounded in `claim_ids`. For every relationship that may affect the answer, check each relevant claim against the citations returned by the graph. If the returned citations are not sufficient, retrieve the exact source text with:
   `tools/baba-search/baba-search passage --citation "<citation>" --json`
   Verify the original wording, source, and direction of the relationship before relying on it. A model-labeled support, qualification, contrast, or possible contradiction can be a false positive or an overstatement. Present it as tentative when the passages do not clearly establish it. Never expose claim IDs, graph metadata, or other internal retrieval mechanics in the answer.
10. The absence of a graph relationship is not proof that no relationship, contradiction, or relevant passage exists. The graph is finite and may miss a connection. If it returns nothing or the evidence is weak, continue with targeted ordinary searches and state that the selected corpus did not establish the answer when appropriate.
11. Synthesize corroborating or contrasting passages instead of selecting only the top-ranked result.
12. Inspect the returned provenance before answering.
13. Cite the discourse title plus paragraph anchor, the story book title, or the selected book category and section anchor. Do not expose PDF page numbers in answers.
14. When evidence is weak or absent, state that the selected corpus did not establish the answer.

## Answer shape

- Give a developed, reader-facing answer rather than a one-sentence retrieval summary. For substantive questions, aim for 4 to 7 purposeful paragraphs, usually around 450 to 800 words when the evidence supports that depth.
- Start with the direct answer, then explain the main ideas, connect corroborating or qualifying teachings, and distinguish source teaching from synthesis.
- Prefer paraphrase. Use only short quotations when the exact wording is important.
- Never mention chunks, snippets, evidence items, search results, passage ids, or internal retrieval mechanics in the answer.
- End every substantive answer with one optional follow-up question that invites the reader to continue exploring.
- For every source-based claim, add the exact citation marker returned by search, for example `[[BABA_SOURCE:Discourses/File.html#3]]`, `[[BABA_SOURCE:Stories/File.md#section-1/chunk-1]]`, `[[BABA_SOURCE:Other-Spiritual-Books/File.md#section-1/chunk-1]]`, or `[[BABA_SOURCE:Acharya-Philosophy/File.md#section-1/chunk-1]]`. The app turns these markers into readable source links. Do not invent, alter, or explain the marker syntax.

Never fabricate a quotation or citation. Do not silently broaden the source scope selected by the user. The default scope intentionally excludes Other Spiritual Books and Acharya Philosophy unless the user selects one of those categories or explicitly selects all.

## API mode

API mode bypasses Codex. The configured API agent receives this research skill
and a structured `baba_search` function. It decides which bounded search,
fuzzy, graph, passage, or glossary operation is useful. Electron validates and
executes the corresponding local read-only CLI command, returns compact JSON
results, and repeats the exchange until the provider has enough evidence to
write the final answer. The provider should follow the same source-grounded
citation and uncertainty rules as native Baba Chat.
