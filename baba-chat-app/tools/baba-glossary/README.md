# Baba glossary candidate extractor

This isolated worker scans the existing `COMPLETE_SARKAR` discourse HTML and
produces deterministic glossary candidates. It does not call Gemini or infer
definitions. The default run is offline; the optional download flags are the
only paths that use the network.

The extractor reuses the paragraph and title extraction helpers from
`tools/baba-search/baba_search.py`. It preserves the original surface spelling
in each candidate, while also providing a casefolded and diacritic-insensitive
`normalized_form` for later alias review.

## Quick start

From the Baba Chat repository:

```bash
python3 -m venv /tmp/baba-glossary-venv
/tmp/baba-glossary-venv/bin/python -m pip install -r tools/baba-glossary/requirements.txt

/tmp/baba-glossary-venv/bin/python tools/baba-glossary/baba_glossary.py \
  /Users/alejandrocamus/Documents/dev/COMPLETE_SARKAR/HTML/Discourses \
  --wordfreq \
  --coca /path/to/COCA/lemmas_60k_words.txt \
  --output corpus/search/glossary-candidates.json
```

This is the preferred merged baseline. `wordfreq` supplies a reproducible
Zipf-frequency lookup for encountered words, while the COCA file supplies an
explicit word-form list. A word is treated as ordinary English only when it is
present in the merged word lists or its `wordfreq` score meets the common-English
threshold of 2.5. Rare or unseen words remain candidates. A separate,
conservative derivational probe uses a 2.0 Zipf floor for ordinary forms such
as `reverentially` and `debilitation`; it is restricted to plain ASCII tokens
and never applies to diacritic-bearing spellings.

`wordfreq` is optional and is loaded lazily. If it is not installed, the
command fails with an install hint only when `--wordfreq` is requested. The
COCA input is also optional and can be supplied from a local TSV/text export or
`.xlsx` workbook.

Using a virtual environment avoids modifying an externally managed system
Python installation. If `wordfreq` is not needed, the command can also run
with the repository's regular `python3` installation and the built-in fallback.

The free COCA sample used by the default download option is:

`https://www.wordfrequency.info/samples/lemmas_60k_words.txt`

To download and cache that sample explicitly:

```bash
/tmp/baba-glossary-venv/bin/python tools/baba-glossary/baba_glossary.py \
  /Users/alejandrocamus/Documents/dev/COMPLETE_SARKAR/HTML/Discourses \
  --wordfreq \
  --download-coca \
  --output corpus/search/glossary-candidates.json
```

The free COCA sample is only a supplemental baseline, not a complete English
lexicon. The `--coca` option also accepts a larger authorized COCA word-form
export, including the tab-separated files and `.xlsx` exports supplied with a
licensed COCA data package. The full COCA word-form lists are not assumed to be
freely redistributable, so provide that larger export locally when available.
The parser accepts the tab-separated `word` column used by the COCA samples and
can read simple `.xlsx` exports without adding an Excel dependency.

On macOS, the installed Webster word list can be used directly:

```bash
tools/baba-glossary/baba-glossary \
  /Users/alejandrocamus/Documents/dev/COMPLETE_SARKAR/HTML/Discourses \
  --dictionary /usr/share/dict/words \
  --output corpus/search/glossary-candidates.json
```

The commonly used optional word list is:

`https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt`

To opt in to downloading that list, use:

```bash
tools/baba-glossary/baba-glossary \
  /path/to/Discourses \
  --download-dictionary \
  --dictionary-cache ~/.cache/baba-glossary/english-words.txt \
  --output glossary-candidates.json
```

The dictionary download flag is the only path that uses the network for that
dictionary. The file is checked for usable entries, written to a same-directory
temporary file, flushed and synced, and atomically renamed into place. A failed
download cannot replace an existing cache. COCA downloads use the same atomic
validation pattern.

## Candidate behavior

Candidate discovery is evidence-driven. Corpus frequency is not used to rank or
discard candidates. The worker records candidates when it sees:

- a token absent from the merged English baseline;
- a maximal run of two or more adjacent non-English-looking tokens, such as
  `kaoshiki nrtya`, as one multiword candidate;
- a candidate in quotes or italics; or
- an unknown candidate near a definition-like cue such as `means`, `refers to`,
  or `is called`.

Long quotations are treated as evidence rather than as one giant glossary
entry. Specialized tokens and multiword runs inside them are retained. The
same normal token and adjacent-run logic also scans text inside parentheses,
square brackets, and braces, but bracketed spans are not emitted as annotation
candidates. This means a bracketed English explanation such as `the yoga of
pervasive association` is not preserved merely because it is bracketed, while
an unknown term such as `[kaoshiki nrtya]` can still produce the normal token
and `multiword_non_english` candidates. A maximal adjacent run of two or more
non-English-looking tokens remains one candidate, such as `kaoshiki nrtya`,
regardless of how often that phrase occurs in the Baba corpus. Short marked
terms and terms immediately before a definition cue can also be preserved
when a general English baseline contains one of their words. This evidence is
bounded so ordinary long quotations do not become glossary entries.

Each output record includes the first deterministic surface form, normalized
form, attested variants, reason codes, up to four bounded source contexts,
document count, frequency, and surface-frequency metadata. No definition field
is generated. Frequency is metadata only and never filters out a one-off term.

## Output shape

```json
{
  "canonical_surface_form": "kaoshiki nrtya",
  "normalized_form": "kaoshiki nrtya",
  "variants": [],
  "reason_codes": [
    "italic",
    "multiword_non_english"
  ],
  "priority_score": 12,
  "evidence_contexts": [],
  "document_count": 1,
  "frequency": 1,
  "surface_frequency": {
    "kaoshiki nrtya": 1
  }
}
```

The result is intended as an input to a later review or normalization step.
This worker never silently changes the source text and never decides a
definition.

## Gemini audit overlay

The deterministic candidate file can be reviewed by Gemini with context. The
reviewer sends every candidate's variants, reason codes, aggregate counts, and all
bounded source excerpts. The large surface-frequency maps are omitted because they
do not help decide whether a term is useful for typo recovery. Since the generated
file is larger than one model context, the complete candidate set is split into
long-context batches. A candidate and all of its evidence always stay together.

The default 450,000-token input budget leaves room for instructions and the JSON
response. For the current glossary this is approximately 13 million input tokens
across 29 batches, so the operation is deliberately a multi-request audit rather
than one literal request containing the raw 80 MB JSON file.

Install the optional Vertex dependency in an isolated environment:

```bash
python3 -m venv /tmp/baba-glossary-gemini-venv
/tmp/baba-glossary-gemini-venv/bin/python -m pip install \
  -r tools/baba-glossary/requirements-gemini.txt
```

Inspect the input size without contacting Gemini:

```bash
/tmp/baba-glossary-gemini-venv/bin/python tools/baba-glossary/baba-glossary-review \
  --glossary corpus/search/glossary-candidates.json \
  --dry-run
```

Run the review through Vertex AI using Application Default Credentials:

```bash
/tmp/baba-glossary-gemini-venv/bin/python tools/baba-glossary/baba-glossary-review \
  --glossary corpus/search/glossary-candidates.json \
  --input-token-budget 450000 \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --location global \
  --model gemini-3.7-flash \
  --output corpus/search/glossary-gemini-review.json
```

The report contains only validated `remove_ordinary_english` findings. A term that
is omitted remains in the deterministic glossary. The prompt asks Gemini to report
only high-confidence removals after reading the source excerpts, so there is no
separate `needs_context` bucket: uncertainty means keep the candidate. Candidate
numbers are tied to the input SHA-256, so a report cannot be safely applied to a
different glossary build. The report also records each batch's size and token usage.

## Baseline semantics

The English baseline is a union of independent signals:

- the built-in minimal list, or a user-supplied/downloaded newline dictionary;
- an optional COCA word-form list; and
- optional `wordfreq` Zipf scores for the requested language.

The `wordfreq` threshold is a one-way common-English test. It must not be
interpreted as proof that a low-frequency word is specialized. A one-off
Ananda Marga term is still retained when it is absent from the common baseline.
The generated JSON records the baseline sources, the 2.5 common-word threshold,
and the 2.0 derivational threshold so later runs are auditable.

## Tests

```bash
python3 -m unittest discover -s tools/baba-glossary/tests -v
```
