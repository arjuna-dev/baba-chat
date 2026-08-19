# Baba Chat architecture

Baba Chat keeps retrieval local and transparent. It does not require embeddings or a vector database.

## Runtime flow

1. The user independently toggles Discourses, Baba Stories, Other Spiritual Books, and Ananda Marga Acharya Philosophy. Discourses and Baba Stories are selected by default, while Everything toggles all four categories on or off.
2. The renderer serializes the selected categories as `default`, `all`, or a `+`-joined scope inside `<BABA_SOURCE_SCOPE>`.
3. The embedded Baba corpus skill tells Codex to run several focused `baba-search` queries and to use the graph command when a question depends on relationships across claims or documents.
4. The local CLI searches the indexed corpus and returns ranked excerpts with stable provenance. Its optional graph tables contain validated claims, cross-document relationships, themes, and links to the exact indexed passages.
5. Codex treats graph relationships as hypotheses, verifies important citations with the passage command, synthesizes a developed answer, ends with an optional follow-up question, and emits exact source markers for supported claims.
6. The renderer turns source markers into readable links. Clicking one asks the local CLI for that citation and opens a source reader with the exact paragraph or story section highlighted. The original file can also be opened from the reader.

When API mode is enabled, the runtime bypasses Codex entirely:

1. The renderer sends the current task, prompts, bounded history, source scope, provider settings, and working directory to Electron main through a narrow IPC method.
2. Electron main sends the API model the Baba research skill and a narrow `baba_search` function schema. The model decides which bounded local operation to call.
3. Electron validates each function call, runs the corresponding read-only CLI command, removes local filesystem paths, and sends compact JSON results back to the API model.
4. The model can make further focused calls, such as using `connections` to find cross-document relationships and `passage` to verify citations, before returning the complete plain-text answer.
5. The renderer uses the same source-marker and highlighted source-reader flow for API answers.

The app keeps two interaction surfaces:

- Chat is the guided, reader-friendly interface.
- Terminal is an explicit opt-in view that runs the real Codex CLI in a restricted Electron PTY bridge.

Starting the app never starts a terminal process. Closing the terminal view or the application tears down its child process.

## Content pipeline

Discourses are imported from the existing COMPLETE_SARKAR HTML corpus. Story books are converted from PDF pages to clean Markdown with Vertex AI. EPUBs, text-based PDFs, and DOCX sources are converted locally and programmatically to Markdown; scanned PDFs use the Vertex OCR preparation pipeline. The public Markdown has no PDF page markers or page headings for OCR books. Internal OCR checkpoints and manifests retain page state, while the search index splits each book into deterministic sections and bounded paragraph windows. The default runtime scope remains Discourses plus Baba Stories, while Other Spiritual Books and Acharya Philosophy are explicit categories.

OCR is an offline preparation step, not part of a reader's chat request. Its state and intermediate artifacts are resumable so a failed batch does not spend credits twice.

## Trust boundaries

- Vertex credentials remain in Google Application Default Credentials and are never packaged with the app.
- Codex authentication remains managed by the existing Codex app-server flow.
- Renderer code has no direct shell access. The preload exposes narrow, typed IPC methods.
- Corpus search is read-only and returns snippets instead of changing source material.
- The knowledge graph is an optional, generated research aid. Its records retain claim citations and are never treated as an independent source of truth.
- The API key is encrypted with Electron's `safeStorage` and is never included in Codex child-process environment variables, command arguments, or repository files.
- API mode limits tool rounds, tool output, prompt, history, and answer sizes, and never forwards absolute search paths to the API model.

## Retrieval contract

The authoritative behavior for native Codex chat and API mode is defined by the app base prompt and the embedded `baba-corpus-research` skill. API mode passes that skill to the provider and maps its search procedures to the structured local function. Search should use bounded concise attempts when needed, including names, synonyms, transliterations, exact phrases, and narrower follow-up terms. Graph relationships and themes should be verified against their citations, and an empty graph result is not proof of absence. If the corpus does not support an answer, the app should say so plainly rather than infer a quotation or teaching.
