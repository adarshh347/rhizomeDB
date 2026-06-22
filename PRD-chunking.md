# PRD — Multi-resolution chunking + chunk map (RhizomeDB)

> Paste into Claude Code. Build the chunking layer described here. Design rationale
> lives in `CHUNKING.md`; honour the existing codebase conventions.

## 1. Context

RhizomeDB chunks converted books (`converted/**/*.md`) into `index/chunks.jsonl`
via `rhizome/chunk.py` (records: `id, book_id, author, title, heading, page,
text`), embeds them (`rhizome/embed.py`, bge-base, normalized, `index/embeddings.npy`),
and retrieves via `rhizome/store.py`. We want chunking to become **multi-resolution**:
the same corpus indexed at several granularities on a SOLID→LIQUID dial
(proposition → semantic-chunk → contextual-chunk → parent passage), so different
retrieval moods/formats read at the rung they need. Plus a **chunk map** to
visualize the world of chunks.

## 2. Goals
- Index the corpus at multiple linked granularities, not one.
- Implement the four strategies: proposition/dense-X, semantic, hierarchical
  parent-child, contextual-retrieval enrichment.
- Tag each chunk with a **character** + one-line description.
- Build a **chunk map** (data + interactive HTML) to see the corpus at a glance.
- Keep everything backward-compatible: current `chunks.jsonl` + `/ask` + engine
  must keep working; new levels are additive.

## 3. Non-goals
- No change to the constellatory engine's logic or the LLM judge.
- No new embedding *model* (separate experiment). Reuse `embed.embed_query`/build.
- Not required to re-embed everything on every run — make levels build on demand.

## 4. Requirements

**R1 — Multi-resolution data model.** Introduce a `level` field and parent/child
links. Produce, per book:
- `parent` units (≈ current 240-word chunks, or larger ~400–500w "passages"),
- `chunk` units (the working mid unit; current behaviour),
- `proposition` units (atomic statements).
Each record: `{id, level, parent_id, child_ids[], book_id, author, title,
heading, page, text, context_blurb?, character?, character_desc?}`.
Store per level: `index/chunks_<level>.jsonl` + `index/emb_<level>.npy` (aligned
rows). Keep `index/chunks.jsonl` as an alias/symlink of the `chunk` level for
backward-compat. IDs stable within a level (`{book}#{level[:1]}{n:04d}`).

**R2 — The four chunkers (selectable in `config`).**
- `proposition`: LLM decomposes a parent passage into atomic, self-contained
  statements; each keeps `parent_id` (a proposition is NEVER read without a link
  back to its passage). Cheap model; batch by passage.
- `semantic`: split a book into chunks at sentence-embedding-similarity drops
  (cosine below a threshold = topic shift). Config: `SEMANTIC_THRESHOLD`. This is
  the `chunk`-level method when enabled; fall back to current recursive chunker.
- `hierarchical` (small-to-big): always maintain `parent_id`/`child_ids` so
  retrieval can match a small unit and return its parent. This is the core dial
  mechanism, not optional.
- `contextual` (enrichment, R3).
Add `config` flags: `CHUNK_LEVELS = ["parent","chunk","proposition"]`,
`CHUNK_METHOD = "recursive"|"semantic"`, `CONTEXTUAL_ENRICH = True/False`.

**R3 — Contextual enrichment.** For each chunk, generate a ≤1-sentence context
("from {author}, {title}, {heading} — on {topic}") with a cheap LLM, store as
`context_blurb`, and embed `context_blurb + "\n" + text` (not raw text). Keep raw
`text` for display. Make it toggleable and cached (don't regenerate if unchanged).

**R4 — Chunk character.** For each `chunk`/`parent` unit, an LLM tags a
`character` from a controlled set — `definitional, argumentative, exegetical,
illustrative, poetic, citation, transitional, aporetic, historical, polemical` —
plus a one-line `character_desc`. Batch (many chunks per call → token economy),
cache, allow `--sample N` for a first partial pass over ~4k chunks.

**R5 — The chunk map.** A generator `tools/chunkmap.py` → `chunkmap.html`
(self-contained, vendor-local scripts like the panel; no CDN). Nodes = chunks
(all levels), coloured by `character`, shaped/grouped by `level`, sized by length;
edges = parent↔child (solid) and top semantic-neighbour (dashed). Controls:
filter by book, level, character; click a node → its text, character, blurb,
links. Also emit `index/chunkmap.json` (the graph data) for reuse. Show summary
stats: counts per level, per character, per book; "thin vs dense" coverage.

**R6 — Retrieval/format integration.** `store.connections`/`rag.retrieve` gain a
`level` arg (default `chunk`); add a `granularity` field to format specs in
`rhizome/formats.py` (e.g. F1 reads `chunk`; a praxis mode reads `proposition`; a
liquid mode reads `parent`). Small-to-big: a helper that, given matched small
units, returns their parent passages for the LLM context.

**R7 — Build flow.** Extend `rhizome/cli.py`: `build --levels parent,chunk,proposition`,
`enrich --contextual`, `characterize [--sample N]`, `chunkmap`. Each step
idempotent and resumable; print per-book counts + token usage (use the existing
`llm` usage accounting).

**R8 — Cost/token guards.** All LLM passes (proposition, contextual, character)
must: batch aggressively, use the cheap/failover model, cache by content hash,
support `--sample`/`--book <id>` to scope, and report tokens used. Never re-run
an enrichment whose input is unchanged.

## 5. Acceptance criteria
- `build --levels parent,chunk,proposition` produces three aligned
  `chunks_<level>.jsonl` + `emb_<level>.npy`; every proposition has a valid
  `parent_id`; every chunk has `child_ids`/`parent_id`.
- `/ask` and the engine still work unchanged (chunk level is the default).
- `chunkmap.html` opens offline, renders nodes coloured by character, filters by
  book/level/character, and a node click shows text + character + links.
- Contextual + character passes are cached (a second run does ~0 LLM calls) and
  print token usage.
- A retrieval call with `level="parent"` returns larger units than `level="proposition"`.

## 6. Sequencing
1. R1 data model + R2 hierarchical parent/child (no LLM) + backward-compat.
2. R5 chunk map over existing chunks (immediate visual value).
3. R3 contextual enrichment (biggest retrieval-quality win).
4. R2 proposition + semantic; R4 character; R6 format integration.
5. R8 guards throughout.

## 7. Open questions (decide as you build)
- Parent size: keep 240w as parent, or introduce a larger ~500w parent above it?
- Proposition embeddings: own index (R1) or inherit parent vector? (Default: own.)
- Semantic threshold default — calibrate on one book first.
