# Baba Chat corpus search CLI

The app has one stable, read-only command for searching the local corpus:

```bash
tools/baba-search/baba-search search \
  --source default \
  --query '"divine love"' \
  --limit 8 \
  --context 180 \
  --json
```

The command uses local lexical search. It does not require embeddings, a
vector database, a network request, or an LLM call. An agent can issue several
searches with alternate wording and then synthesize an answer from the
returned passages.

## API mode

API mode gives the configured API model the embedded Baba research skill and a
single structured `baba_search` function. The model decides whether to call
`search`, `aggregate`, `fuzzy`, `connections`, `passage`, or a glossary
operation, and can make bounded follow-up calls after inspecting results.
Electron validates the operation, executes the corresponding local read-only
CLI command, strips local filesystem paths, and returns compact JSON to the
model. The model then writes the final plain-text answer directly to the app.
Codex is not involved in this mode.

The Settings screen defaults to DeepSeek's OpenAI-compatible endpoint and
`deepseek-v4-flash`. A custom OpenAI-compatible provider can be selected by
changing the provider, model, and base URL. The API key is stored through the
operating system secure storage. `BABA_LLM_API_KEY` is supported as a
development-only environment fallback.

For questions where one phrase may have related but different formulations,
use the `aggregate` command. It runs each query independently, merges the same
passage across query variants, records which variants found it, and defaults to
one passage per source document so a first hit cannot crowd out corroborating
documents.

When a rare term may contain a typo or transliteration variation, use the `fuzzy`
command:

```bash
tools/baba-search/baba-search fuzzy \
  --source all \
  --query 'kaoshiki nrtya' \
  --limit 8 \
  --json
```

`fuzzy` compares unknown query tokens with the normalized words in the selected
search index, reports likely replacements, and searches with a bounded set of
corrected queries. It keeps the original query in the search run and does not
silently change the user's wording. Suggestions are search hypotheses, not
definitions. New indexes store a compact term vocabulary; older indexes remain
usable through a deterministic fallback scan.

## Commands

Build or rebuild the generated index:

```bash
tools/baba-search/baba-search index --json
```

`build` is an alias for `index`. The default discourse source is
`/Users/alejandrocamus/Documents/dev/COMPLETE_SARKAR/HTML/Discourses` when it
exists. The portable configuration is through environment variables or
explicit paths:

```bash
BABA_DISCOURSES_DIR=/path/to/COMPLETE_SARKAR/HTML/Discourses \
BABA_STORIES_DIR=/path/to/corpus/stories \
tools/baba-search/baba-search index
```

Equivalent explicit options are `--discourse-root`, `--stories-root`,
`--other-spiritual-books-root`, and `--acharya-philosophy-root`. EPUBs and
text-based PDFs are converted locally before indexing. Scanned PDFs are first
processed by the resumable OCR pipeline. Both new book categories are kept out
of the default search scope.

For a scanned PDF that should be converted without a cloud call, the local
fallback is:

```bash
BABA_PYTHON=/path/to/bundled/python
"$BABA_PYTHON" tools/corpus-ingest/convert_sources.py pdf-ocr \
  --input /path/to/book.pdf \
  --output corpus/other-spiritual-books
```
Both roots are read-only. Generated SQLite files are written only under
`corpus/search` by default, and the index does not copy the source HTML or
Markdown files.

Import the validated Gemini knowledge graph while building the index:

```bash
tools/baba-search/baba-search index \
  --connections-root corpus/connections/full-corpus \
  --json
```

The graph is stored in the same SQLite index as the passages. It contains
claim nodes, relationship edges, themes, and links back to exact indexed
citations. Rebuilding the index without a graph artifact keeps normal lexical
search working and reports the graph as unavailable.

Show counts and index mode:

```bash
tools/baba-search/baba-search stats --json
```

Look up specialized terminology without loading the large glossary JSON into
the model context:

```bash
tools/baba-search/baba-search glossary lookup \
  --term "svadhyaya" \
  --json

tools/baba-search/baba-search glossary search \
  --query "kaosikii nrtya" \
  --limit 5 \
  --json
```

`lookup` matches an exact normalized, canonical, or variant spelling.
`search` also finds a query phrase inside a longer candidate and performs
diacritic-insensitive token matching. Both commands default to
`corpus/search/glossary-candidates.json`; use `--glossary PATH` for another
file. The returned records include canonical forms, variants, reason codes,
and bounded evidence contexts. They are search-expansion clues, not a
definitions authority.

Run a deliberate lexical fan-out:

```bash
tools/baba-search/baba-search aggregate \
  --source discourses \
  --query '"create mind"' \
  --query '"manufactures" mind' \
  --query '"mind of its creator"' \
  --query '"physical strength" "psychic strength"' \
  --query '"laboratory" brain embryo' \
  --limit 12 \
  --per-query-limit 10 \
  --max-per-document 1 \
  --context 360 \
  --json
```

`--query` may be repeated up to 32 times. Duplicate query strings are
collapsed before searching. `--per-query-limit` controls how many results each
variant contributes. `--max-per-document 1` is useful for the first evidence
pass; use `0` when several passages from the same document are needed for close
reading.

Query relationships and themes across documents:

```bash
tools/baba-search/baba-search connections \
  --source all \
  --query 'yoga Patanjali' \
  --limit 8 \
  --json
```

The command returns relationship records, themes, and the linked claim
statements with their exact citations. Use `--claim-id` when following one
known claim. Graph records are derived research aids, not source quotations:
verify important claims with the passage command, and treat a possible
contradiction or an empty graph result as tentative rather than conclusive.

The connection search accepts the same source scopes as lexical search. The
`default` scope limits a relationship to claims whose linked sources are in
Discourses or Baba Stories. Use `all` to include the comparative spiritual
books and Ananda Marga Acharya philosophy.

Force the Python scan fallback during a build, useful for validating an
environment without SQLite FTS5:

```bash
tools/baba-search/baba-search index --no-fts5
```

## Search options

The search command accepts:

- `--source SCOPE`, where `SCOPE` is one category, `default`, `all`, or categories joined with `+`, default `default`
- `default` searches Discourses and Baba Stories. Use `all` to search every category, or a combination such as `discourses+other_spiritual_books` to search only those categories.
- `--query TEXT`, required
- `--limit N`, default `10`
- `--context N`, snippet context in characters, default `220`
- `--book TEXT` or `--book-title TEXT`, a case and diacritic-insensitive book substring filter
- `--title TEXT`, a case and diacritic-insensitive title substring filter
- `--json`, for machine-readable output

The aggregate command accepts the same source, context, book, title, and JSON
options, plus:

- repeated `--query TEXT`, required
- `--limit N`, maximum merged results, default `10`
- `--per-query-limit N`, retained results from each query, default `10`
- `--max-per-document N`, diversity cap, default `1`; `0` means unlimited

The connections command accepts:

- `--source SCOPE`, default `all`
- `--query TEXT`, a relationship, theme, or claim-text query
- `--claim-id ID`, an exact graph claim lookup instead of a text query
- `--limit N`, maximum relationship and theme records, default `10`
- `--json`, for machine-readable output

The fuzzy command accepts the same source, context, book, title, limit, and JSON
options, plus:

- `--per-query-limit N`, retained results for each corrected query, default `10`
- `--max-per-document N`, diversity cap, default `1`; `0` means unlimited
- `--per-token-limit N`, likely replacements retained for each unknown token, default `3`
- `--max-distance N`, maximum spelling edit distance; the default adapts to token length

Unquoted terms are an AND query. Quoted text is a phrase query and must occur
as adjacent tokens in a passage. Diacritics are ignored, so `siva` matches
`Śiva` and `Śiva`. Punctuation separates tokens for search while snippets
retain the original extracted text.

Examples:

```bash
tools/baba-search/baba-search search \
  --source discourses \
  --query 'siva meditation' \
  --title sadhana

tools/baba-search/baba-search search \
  --source stories \
  --query '"divine love"' \
  --book "A Story of Baba" \
  --json

tools/baba-search/baba-search search \
  --source other_spiritual_books \
  --query 'non-dual consciousness' \
  --json

tools/baba-search/baba-search search \
  --source acharya_philosophy \
  --query 'sadhana' \
  --json
```

The regression shape for a question about whether humans can manufacture mind
is intentionally spread across wording families. The exact phrase about the
scope of human endeavour and the separate passage about physical and psychic
strength are different lexical hits, so run both and inspect the merged
results. Do not stop when the first query returns a plausible answer.

## JSON integration contract

Search JSON is an object with the original query, parsed terms, filters,
index mode, and a `results` array. Each result contains:

```json
{
  "rank": 1,
  "score": 10102,
  "source": "discourses",
  "title": "Siva and Sadhana",
  "book": "Subhasita Samgraha Part 1",
  "file": "Discourses/Siva_and_Sadhana.html",
  "path": "Discourses/Siva_and_Sadhana.html",
  "anchor": "1",
  "page": null,
  "snippet": "... original extracted text ...",
  "matched_text": "Śiva",
  "matched_in": "text",
  "matched_terms": ["siva"],
  "match_count": 2,
  "phrase_match": false,
  "source_path": "/absolute/read-only/source/file.html",
  "citation": "Discourses/Siva_and_Sadhana.html#1"
}
```

`citation` is the compact provenance string to show in an answer. Use
`source_path` when the app needs to open the original file. For stories,
`anchor` is a page-independent value such as `section-1/chunk-1`, `page` is
`null`, and the citation looks like `Stories/Book.md#section-1/chunk-1`.
The other category prefixes are `Other-Spiritual-Books/` and
`Acharya-Philosophy/`.

The `passage` command reads one exact citation and returns the selected indexed
passage plus a small window of nearby passages. Baba Chat uses it to open a
readable source view with the cited paragraph or story section highlighted:

```bash
tools/baba-search/baba-search passage \
  --citation 'Discourses/Siva_and_Sadhana.html#1' \
  --json
```

The reader hides internal story chunk terminology from the user-facing label;
the highlighted source text remains the exact indexed passage.

Every result also has a local `passage_id` that is stable within the published
index. Aggregate results add
`query_hits`, `matched_queries`, `query_evidence`, `best_rank`, `best_score`,
`aggregate_score`, and `document_key`. `matched_queries` makes it visible when
independent wording converges on the same passage. `query_evidence` contains
the per-query rank and score, while `document_key` supports deliberate source
diversification.

Ranking is deterministic. Phrase matches receive the strongest weight,
followed by title matches, book matches, body matches, and total term
occurrences. Ties are resolved by relative path, natural anchor order, and
index row id. Identical source, anchor, and passage text are returned once.
Aggregate ranking rewards query coverage first, then reciprocal rank across
the query variants and the strongest individual match. This makes a passage
found by several independent variants more visible while retaining precise
single-query hits.

## Source extraction contract

Discourse HTML follows the existing COMPLETE_SARKAR format. The indexer uses
the title block, `discourse_title`, and HTML `<title>` fallbacks, extracts
`type=paragraph` blocks, keeps their `a=...` anchors, decodes entities, and
filters paragraphs shorter than 30 characters just as the existing search
index builder does. The first `Published in` reference becomes the book field.

Story Markdown is indexed as deterministic, page-independent passages. YAML
front matter is stripped before parsing. Meaningful Markdown headings start a
new section, and paragraph-like blocks such as paragraphs, lists, quotes, and
captions are grouped into bounded searchable windows. Long blocks are split at
sentence or word boundaries when needed. The searchable text retains useful
heading, list, and quote structure.

Legacy OCR page comments and page headings are ignored when encountered, but
they are not required and are never emitted into passage text. Titles can come
from YAML front matter or the first level-one heading, with a filename
fallback. Story passages use stable internal anchors such as
`section-1/chunk-1`, and their `page` field is always `null`.

## Generated artifact

The default index is `corpus/search/baba-search.sqlite3`. It contains only
extracted passage text, normalized search text, and provenance metadata. It
never modifies or copies the source corpora. The `corpus/search` directory is
the only generated output location used by the CLI.
