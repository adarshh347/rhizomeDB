# Plan — Reader in depth + the RAG mini-engines

> Grounded in `docs/PRD-constellatory-retrieval.md` (Phases 0/3/5 + the §6 harness),
> the three audits in `docs/audits/`, and the code as of `13c0962`. Written before
> building; the "Status" column is filled in as increments land.
>
> **Amendments made while building** (each is in the code and in `docs/ENGINES.md`):
> the *noise-floor gate* (§1) was not in the plan — the harness's first run showed
> every vector engine answering gibberish, so a per-model calibrated floor on the
> seed's best match became part of the contract; `walk` builds its own per-hop
> band (visited books excluded *before* the cut) instead of post-filtering
> `Store.connections`; the compare view is a stacked list, not a table, because a
> three-column table cannot fit the 20rem rail.

## 0. What this delivers

1. **A retrieval interface** (`rhizome/engines/`) with the numpy exact-scorer as the
   reference — PRD Phase 0 — and **eleven mini-engines** behind it, each a
   self-contained retrieval *strategy* that answers the same question ("from this
   passage, what else in the corpus?") with a different geometry, so the reader can
   feel the difference between ordinary RAG and constellatory retrieval **live**.
2. **The reader talks to all of them.** The Connections rail gets an engine picker,
   per-pick disclosure (path · why · rank in corpus), and engine-specific renderings
   (a walk renders as hops; *my marks* link back to the annotation).
3. **A constellatory eval harness** (`rhizome eval-engines`) so every engine is
   measured on the PRD §6c proxies — novelty (rank distribution), intra-list
   diversity, book spread, willingness-to-find-nothing — and the numbers land in
   the UI, not just a terminal.
4. Two reader defects the audit found that are cheap and visible: **U7** (the closing
   `》` glyph sits on the first segment of a split mark) and **U9** (raw Markdown in
   rail/marginalia previews).

Everything is additive. `Store.connections()` is untouched; the `band` engine wraps
it and a parity test proves the wrapper returns byte-identical picks.

## 1. The contract (Phase 0)

```
rhizome/engines/
  base.py        Seed · Context · Engine protocol · finish()/rank helpers
  __init__.py    registry: auto-discovers every module exposing ENGINE
  plain.py band.py spread.py lexical.py hybrid.py echo.py
  concept.py walk.py marks.py structural.py fused.py
```

- `Seed` — `{vec, text, book_id, author, chunk_id, label}` (vec may be None for a
  chunk-less lexical seed).
- `Context` — the shared runtime: `store` (a `Store`, exact numpy scorer), `chunks`,
  `embed_key`, and lazily-built side indexes (`bm25`, `concepts`, `annotations`,
  `structural`). `Context.from_arrays(chunks, vecs)` builds one from memory for tests.
- `Engine` — `key · label · blurb · needs · params` + `ready(ctx) -> (bool, why)` +
  `candidates(seed, ctx, k, **params) -> list[dict]`.
- Every pick is a **chunk dict copy** with: `similarity` (cosine to the seed's
  surface vector when one exists), `rank` / `corpus_size` (position in the full
  similarity sort — the non-obviousness disclosure), `score` (engine-native),
  `path` (engine key), `why` (one human sentence), and optional extras
  (`hop`, `annotation_id`, `concepts`, `sources`).
- **Willingness to find nothing** is part of the contract: engines return `[]` when
  nothing clears their floors; they never pad.

## 2. The engines

| key | label | geometry | needs | why it exists |
|---|---|---|---|---|
| `plain` | Nearest (plain RAG) | top-k cosine, no exclusions | vectors | the baseline the others are measured against |
| `band` | Resonance band | `Store.connections` (skip-top · dedup ceiling · min-sim floor · same-book excl. · MMR) | vectors | today's engine, unchanged — the parity oracle |
| `spread` | Resonance band · set-spread | same band, **facility-location / DPP** set selection instead of pairwise MMR | vectors | PRD Phase 5 diversity upgrade |
| `lexical` | Keyword (BM25) | pure-Python BM25 over chunk tokens; seed = the passage's distinctive terms | chunks only | the SOLID end; also the "obvious" the band throws away, made visible |
| `hybrid` | Dense + keyword | RRF of dense top-N and BM25 top-N | vectors | dial-aware hybrid for lookup |
| `echo` | Echoes in this book | **same book only**, far from the seed (≥ gap chunks / other section), band-style | vectors | intra-corpus constellation the default excludes |
| `concept` | Concept graph | bipartite chunk–concept graph (`concepts.json`) + attributed `edges.jsonl`; **personalised PageRank** from the seed; cross-book; `why` = shared concepts | concepts | PRD Phase 3 — the graph as a retrieval path |
| `walk` | Line of flight | geometry-only *wander*: seed → best band pick → its best pick …, never revisiting a book; picks carry `hop` | vectors | the rhizome as a path, not a set |
| `marks` | My marks | embed the reader's own highlights/notes; cosine from seed, cross-book; `why` = the note | vectors + workspace | the human half of the loop feeding retrieval |
| `structural` | Structural (persisted HyDE) | build step abstracts each chunk's *move* with the LLM → second vector matrix; query on the seed's stored structural vector (no LLM at query time) | LLM at build | PRD Phase 2 — the abstraction becomes an index |
| `fused` | Constellation (fused) | union of band ∪ concept ∪ marks (∪ structural if built), re-ranked by relevance × surprise (cross-book · mid-band rank · provenance weight human > judged > concept > dense), then set-spread; empty if nothing clears | vectors | PRD §4 — the fuse + re-rank layer |

Params every engine accepts: `k`. Engine-specific knobs (gap, hops, fusion weights)
live as module constants with a `params` schema so the API can expose them.

## 3. Backend surface

- `GET /api/v2/engines` — every engine: key, label, blurb, needs, ready, reason, params.
- `GET /api/v2/connect?engine=&mode=chunk|theme&value=&candidates=` — JSON, geometry
  only, no LLM. Used by tests, the compare view, the eval harness.
- `GET /api/v2/connect/compare?mode=&value=` — every ready engine's picks for one seed
  + a pairwise overlap matrix (how much do the strategies agree?).
- `GET /api/v2/explore?…&engine=` — the existing SSE run now routes candidates through
  the chosen engine, so judge/synthesis (when a key is set) apply to any engine's
  picks. New `engine` event; candidates carry `path`, `why`, `rank`, extras.
- `GET /api/v2/engines/eval` — the cached constellatory harness report.
- CLI: `engines`, `connect`, `compare-engines`, `eval-engines`, `build-structural`.

## 4. Reader surface

- **Engine picker** in the Connections rail head (compact select; blurb as tooltip;
  choice persisted in `localStorage`, `?engine=` in the URL for shareable links).
- **Per-pick disclosure**: `why` line, `path` badge when the engine is fused,
  `#rank of N` next to the meter, hop numbers for `walk`, note text + "open note" for
  `marks`, shared concepts for `concept`.
- **Compare** toggle: for the current seed, a compact table of every ready engine's
  top-3 with the overlap matrix (the "same question, different geometries" moment).
- **Selection → Connect**: the selection toolbar gains *Connect* — seed the engine
  from selected text (theme mode) so a sentence, not only a chunk, can be a seed.
- U7: emit `mark-end` on the last segment of a mark; move the closing glyph there.
- U9: strip Markdown emphasis/links in rail previews and margin notes.

## 5. Eval harness (PRD §6c, automatable subset)

`rhizome/eval_engines.py`: a fixed deterministic seed set (every Nth chunk, N chosen
to give ~40 seeds) + 6 incoherent seeds (gibberish themes). Per engine report:
`n_seeds · mean_k · empty_rate · mean_rank_pct · median_rank · ild (mean pairwise
1−cos) · book_spread (distinct books / k) · cross_book_rate · noise_fp_rate
(non-empty on incoherent seeds) · ms_per_seed`. Held-out bridge recall runs when
`edges_judged.jsonl` has chunk-addressed bridges; otherwise reported as `n/a` with the
count. Writes `index/eval_engines.json`; CLI prints a table; API serves it.

## 6. Increments and gates

| # | Increment | Gate | Status |
|---|---|---|---|
| 1 | Contract + `plain` + `band` + parity test | `band` byte-identical to `Store.connections` on 30 seeds; unittest green | ✓ `818a01b` — parity on fixture + real index (30 seeds) |
| 2 | `lexical` `hybrid` `echo` `spread` `walk` `marks` `concept` `structural` `fused` | each has unit tests on `Context.from_arrays`; each returns `[]` on an empty band; registry lists 11 | ✓ `1104fe9` — 11 registered, 10 ready on the real index (structural needs an LLM key to build) |
| 3 | API + CLI + `run_explore(engine=)` | `/engines`, `/connect`, `/connect/compare` covered by `tests/test_api.py`-style tests | ✓ `1104fe9` — `tests/test_api_engines.py`; band via `/explore` verified byte-identical |
| 4 | Eval harness | `eval-engines` runs on the real index; report in `index/`; `/engines/eval` serves it | ✓ `1104fe9` + `7cc8056` — first finding: noise_fp 1.00 → calibrated noise floor → 0.33 |
| 5 | Reader: picker · disclosure · compare · Connect-from-selection · U7 · U9 | `tsc --noEmit` + `vite build` clean; live check in the browser per engine | ✓ `ab8d770` — verified live at 1568px (band, walk, marks, fused, structural-not-ready, compare, Connect-from-selection, U7, U9); narrow viewport still unobserved |
| 6 | Docs: README section, this plan's status column, `docs/ENGINES.md` | | ✓ this commit |

## 7. Out of scope (deliberately)

LanceDB/Qdrant bake-off (PRD Phase 1 — no speed need at 4k chunks), late-interaction
rerank (Phase 4 — needs a new model + eval first), server DBs, GraphRAG. NetworkX is
avoided too: the concept graph is small enough for a numpy power-iteration PPR.
