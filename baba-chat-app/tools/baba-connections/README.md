# Baba connections pipeline

This tool supports three deliberately conservative experiments:

1. The legacy discourse pilot makes one Gemini request per discourse, then a
   sixth request compares the validated claims.
2. The mixed-corpus pilot makes one Gemini request containing ten documents from
   Discourses, Baba Stories, Other Spiritual Books, and Acharya Philosophy. It
   then makes a second, much smaller Gemini request over the validated claims to
   find cross-document relationships and themes.

3. The full-corpus run processes all canonical documents in resumable
   context-sized extraction batches, then makes one global relationship request
   over the combined validated claims.

The first pass does not group by book and does not repeat a discourse that may
appear in multiple publications. The second pass does not receive the raw HTML;
it receives only claims that passed local evidence validation.

## Authentication

The tool uses Vertex AI through the Google Gen AI Python SDK and does not read an
API key. It uses the Application Default Credentials configured by gcloud:

```bash
gcloud auth application-default login
gcloud config set project PROJECT_ID
```

The project can also be supplied with `--project` or `GOOGLE_CLOUD_PROJECT`.

Install the isolated dependencies in a temporary environment:

```bash
python3 -m venv /tmp/baba-connections-venv
/tmp/baba-connections-venv/bin/python -m pip install \
  -r tools/baba-connections/requirements.txt
```

## Run the mixed ten-document extraction

The default mixed run submits exactly one Gemini request containing ten selected
documents. Use `--dry-run` first to inspect the input and prompt sizes.

```bash
/tmp/baba-connections-venv/bin/python tools/baba-connections/baba-connections \
  --mixed \
  --max-items-per-discourse 8 \
  --max-output-tokens 12000 \
  --output corpus/connections/mixed-10
```

To choose a different set, repeat `--mixed-document` exactly ten times using
`CATEGORY=PATH`:

```bash
/tmp/baba-connections-venv/bin/python tools/baba-connections/baba-connections \
  --mixed \
  --mixed-document 'discourses=Prana_Dharma.html' \
  --mixed-document 'stories=full-3.7/my-time-with-baba.md' \
  --output corpus/connections/custom-mixed-10
```

The example is abbreviated. A real run must provide ten specifications.

## Run the full canonical corpus

The full mode covers the canonical Discourses, Baba Stories, Other Spiritual
Books, and Acharya Philosophy directories. It keeps each source document's
passages together as far as the context budget allows, and never places two
chunks from the same source document in one extraction batch. Claim IDs still
refer to the original document and passage, even when a large document is split
across batches.

Run a dry run first when using a new corpus snapshot:

```bash
/tmp/baba-connections-venv/bin/python tools/baba-connections/baba-connections \
  --full-corpus \
  --dry-run \
  --output corpus/connections/full-corpus-dry
```

A fresh full-corpus run can be started with:

```bash
/tmp/baba-connections-venv/bin/python tools/baba-connections/baba-connections \
  --full-corpus \
  --max-items-per-discourse 4 \
  --max-output-tokens 12000 \
  --full-relationship-max-output-tokens 32768 \
  --full-max-relationships 40 \
  --full-max-themes 12 \
  --output corpus/connections/full-corpus
```

Use `--resume` after an interrupted run. It reuses batch `claims.json` files
whose source hashes still match and only submits missing stages. The extraction
pass is deliberately selective: it asks for non-trivial definitions,
propositions, causal claims, prescriptions, distinctions, classifications,
unique concepts, and important qualifications. The global pass ranks the
strongest relationships and themes instead of trying to emit every weak pair.

## Run the legacy five plus one pilot

From the application directory:

```bash
/tmp/baba-connections-venv/bin/python tools/baba-connections/baba-connections \
  --output corpus/connections/pilot-5
```

The default five files are:

- `The_Science_of_Action.html`
- `Knowledge_and_Progress.html`
- `Human_Society_Is_One_and_Indivisible_1.html`
- `Prana_Dharma.html`
- `Action_Reaction_and_Doership.html`

To choose five different files, repeat `--file` exactly five times:

```bash
/tmp/baba-connections-venv/bin/python tools/baba-connections/baba-connections \
  --file The_Science_of_Action.html \
  --file Knowledge_and_Progress.html \
  --file Prana_Dharma.html \
  --file Matter_and_Spirit.html \
  --file A_Guide_to_Human_Conduct.html \
  --output corpus/connections/custom-pilot
```

Use `--dry-run` to inspect prompt sizes without contacting Gemini. Use
`--resume` to reuse matching completed calls. Use `--force` only when a fresh
run is intended.

## Output layout

The mixed run writes:

```text
mixed-10/
  source_bundle.json
  extraction_prompt.txt
  extraction_response.raw.txt
  claims.json
  relationships/
    claims_input.json
    prompt.txt
    response.raw.txt
    result.json
  run-manifest.json
```

The full-corpus run writes:

```text
full-corpus/
  batches/
    batch-0001/
      source_bundle.json
      extraction_prompt.txt
      extraction_response.raw.txt
      claims.json
    ...
  claims.json
  relationships/
    claims_input.json
    prompt.txt
    response.raw.txt
    result.json
  run-manifest.json
```

The legacy run writes:

```text
pilot-5/
  run-manifest.json
  prompts/01-*.txt
  responses/01-*.raw.txt
  extractions/01-*.json
  aggregate/input.json
  aggregate/prompt.txt
  aggregate/response.raw.txt
  aggregate/result.json
```

The mixed `source_bundle.json` is assembled locally from the original corpus
files. It is the source-document payload placed inside the first Gemini prompt.
It is not Gemini output. Its `result_type` is `source-document-bundle` so the
file's role is explicit.

The mixed `claims.json` is the first model output after local validation. It
contains only claims whose quotes were found locally in the supplied passages.
Each accepted claim includes a deterministic claim ID, document ID, category,
source citation, passage anchor, exact quote, and source SHA-256.

The relationship pass receives `relationships/claims_input.json`, which is a
compact claims-only payload derived from `claims.json`. It does not receive the
full source bundle again. The resulting `relationships/result.json` contains
`connections` whose `claim_ids` point to two or more claims, plus optional
cross-document themes. A relationship can involve up to five claims. The
validator rejects unknown claim IDs and relationships that stay inside one
document.

The combined claims document sent to the legacy aggregate call is
`aggregate/input.json`. The five source-specific claim files are in the
`extractions` directory.

Individual extraction records contain stable `claim_id` values built from the
discourse source ID and paragraph ID. Each accepted claim retains its exact
quote, original paragraph anchor, modality, attribution, qualifiers, and the
reason it was considered non-trivial.

The legacy aggregate result contains only validated references to those claim IDs:

```json
{
  "connections": [
    {
      "connection_id": "conn-001",
      "type": "qualifies",
      "claim_ids": ["...", "..."],
      "summary": "One claim limits the scope of another.",
      "explanation": "...",
      "confidence": "medium"
    }
  ],
  "themes": []
}
```

An empty connections array is valid. Every accepted connection and theme must
span at least two discourse files. The prompt explicitly prohibits forced
connections and asks Gemini to use `possible_contradiction` only when the claims
are materially incompatible under similar conditions.

The source HTML is read only. The tool saves outputs under `corpus/connections`
and never changes the search index or discourse files.

The full-corpus relationship result is currently an auditable knowledge artifact
and is not yet injected into the runtime search index or agent prompt. Its
relationship and theme records point to stable claim IDs; join those IDs with
`claims.json` to recover the exact quote and source citation.

## Tests

```bash
python3 -m unittest discover -s tools/baba-connections/tests -v
```
