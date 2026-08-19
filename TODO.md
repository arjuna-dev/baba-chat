# Baba Chat TODO

This is the standing content backlog for the Baba Chat project. I will refer back to it as we continue developing the corpus and category structure.

## Baba story sources

- [ ] Get more digitalized Baba story books, including the follow-up to *Advent of a Mystery*.
- [ ] Add the Baba stories personally collected by the user. Current location: pending, since the source path was blank in the request (`''`).
- [x] Add the compiled Dada Ik Baba story book from `../Dada Ik/Dada-Ik-all-compiled.docx`.
- [ ] Run speech-to-text on the Baba story interviews found on Spotify.
- [ ] Run speech-to-text on Baba stories from YouTube.

## Philosophy by Acaryas

- [x] Add Philosophy by Acaryas as a separate small category.
  - [ ] Add Dada Chandranath's videos to this category.
  - [x] Add the two local books from `../Philosophy-by-Ananda-Marga-Acharyas` to this category.

## Corpus-wide Gemini analysis

- [x] Implement and run the full corpus connections workflow using Gemini: extract propositions from each book, compare them across the corpus, and store cited connections, contrasts, and possible contradictions for later use by the search agent.
  - [x] Build and run the five-discourse high-precision extraction pilot with a sixth cross-discourse aggregate call.
  - [x] Run the first full-corpus experiment with resumable extraction batches and one global cross-corpus relationship pass.
  - [x] Integrate the validated claims and relationship graph into runtime search and the agent prompt.
  - [ ] Evaluate graph retrieval quality and consider a targeted contradiction-only analysis pass.
