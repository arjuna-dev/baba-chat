# Baba Chat

Baba Chat is a desktop research assistant for the discourses and life stories of Prabhat Ranjan Sarkar, with optional comparative spiritual books and Ananda Marga Acharya philosophy. It combines an Electron chat interface with Codex app-server, local lexical corpus search, and a Vertex AI OCR preparation pipeline.

## Content sources

- Discourses: imported and indexed from `/Users/alejandrocamus/Documents/dev/COMPLETE_SARKAR/HTML/Discourses`
- Story PDFs: read from `/Users/alejandrocamus/Documents/dev/BABA-chat/Baba-Story-Books`
- Story Markdown: generated under `corpus/stories`
- Dada Ik compiled stories: converted from `../Dada Ik/Dada-Ik-all-compiled.docx` into `corpus/stories/dada-ik`
- Other Spiritual Books: EPUBs and converted PDFs from `../Other-Spiritual-Books`, stored under `corpus/other-spiritual-books`. This is not part of the default search scope.
- Philosophy by Ananda Marga Acharyas: converted from `../Philosophy-by-Ananda-Marga-Acharyas`, stored under `corpus/acharya-philosophy`. This is not part of the default search scope.
- Search artifacts: generated under `corpus/search`

The runtime search is local and uses no embeddings or vector database. Codex can issue multiple lexical queries, inspect snippets, refine its terminology, and query the optional Gemini-generated knowledge graph for cross-document themes and relationships. Graph records link back to exact source citations and are treated as hypotheses to verify, not as independent authority.

## Development

```bash
npm install
npm run rebuild:native
npm run dev:electron
```

The native rebuild targets `node-pty`, which powers the optional embedded Codex CLI terminal.

The normal chat uses the user's Codex or ChatGPT login through `codex app-server`. Vertex AI is used separately for OCR and relies on Google Application Default Credentials.

## API mode

API mode is a direct Electron-to-provider path: it does not start Codex or route the provider response through Codex. The API model receives the embedded Baba research skill and decides when to call the local `baba_search` function. Electron executes only validated, read-only search commands, returns compact results, and then renders the provider's complete plain-text answer directly in Baba Chat.

DeepSeek is the default provider and uses `https://api.deepseek.com` with `deepseek-v4-flash`. The provider, model, base URL, and output budget are configurable in Settings. The API key is encrypted with the operating system secure storage and is never passed to Codex or written to the repository. For development, `BABA_LLM_API_KEY` can be used as an environment fallback.

The API client also accepts `BABA_LLM_PROVIDER`, `BABA_LLM_MODEL`, `BABA_LLM_BASE_URL`, and `BABA_LLM_MAX_OUTPUT_TOKENS` as development defaults. See `docs/architecture.md` for the trust boundary and API tool-call flow.

See `docs/search-cli.md`, `docs/ocr-pipeline.md`, and `docs/embedded-terminal.md` for the individual subsystems once generated.

## Safety and provenance

The original PDFs remain the source of truth. OCR output is assembled as clean, page-free Markdown; internal OCR checkpoints and manifests retain page information for resumability and auditability. Runtime search commands are read-only, and the optional embedded terminal does not start until the user activates it.
