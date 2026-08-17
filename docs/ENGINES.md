# Engines — the retrieval mini-engines

> Reference for `rhizome/engines/`. The plan that produced them is
> `PLAN-reader-depth-rag-engines.md`; the thinking behind them is
> `PRD-constellatory-retrieval.md` (Phases 0/2/3/5 and the §6 harness).

## 1. What an engine is

An engine answers one question — *from this seed, what else in the corpus?* — with
one retrieval geometry. There are eleven because the question has more than one
honest answer: nearest-neighbour lookup (plain RAG) and the resonance band are both
retrieval, and the only way to *feel* the difference between them is to ask the
same passage both ways and read the two lists side by side. So the engines share
one contract, and the reader, the CLI, the API and the eval harness treat them
interchangeably: flip the switch, same seed, different geometry.

The contract (`rhizome/engines/base.py`), one line each:

- **`Seed`** — `text · vec · chunk_id · book_id · author · label`; `vec` may be
  None (lexical-only), `chunk_id` is None for a free-text *theme* seed.
- **`Context`** — the shared runtime: the exact numpy `store`, `embed_key`, the
  calibrated `noise_floor`, and lazily-built side indexes via `ctx.side(name, builder)`
  (BM25, the concept graph, annotations, the structural matrix). `Context.from_store()`
  for the real index, `Context.from_arrays(chunks, vecs)` for tests.
- **`Engine`** — `key · label · blurb · needs · params`, `ready(ctx) -> (ok, why)`,
  `candidates(seed, ctx, k=8, **params) -> list[dict]`.
- **Every pick** is a *copy* of a chunk dict decorated with `similarity` (cosine to
  the seed's surface vector), `rank` / `corpus_size` (position in the full descending
  similarity sort — the non-obviousness disclosure, shown 1-based as "#43 of 4110"),
  `score` (engine-native), `path` (the engine key; fused picks carry the union) and
  `why` (one human sentence).
- **Never pad** — return `[]` when nothing clears the engine's floors ("a machine
  that always finds a connection is lying", VISION.md). Never mutate the store's
  dicts. Be **deterministic** for a given (seed, ctx, params).

The registry (`rhizome/engines/__init__.py`) discovers every module that exposes a
module-level `ENGINE`; `ORDER` fixes the listing order, `DEFAULT_ENGINE = "band"`.

## 2. The engines

Params every engine accepts: `k`. The engine-specific knobs below are module
constants exposed through `params` so the API can coerce `?skip_top=4` by type.
The `why` examples are real, from `compare-engines --chunk being-and-truth#0036`
and the eval report's samples.

| key | label | geometry | needs | params (name=default) | extra pick fields | `why`, for real |
|---|---|---|---|---|---|---|
| `plain` | Nearest (plain RAG) | Top-k by cosine, no exclusions, no spread — the seed's own book and its near-verbatim quotations all count; the baseline the others are read against. | vectors | `include_seed=False` | — | `#2 nearest by surface similarity` |
| `band` | Resonance band | `Store.connections()` unchanged: drop near-duplicates (≥ `dedup_sim`), skip the `skip_top` most-similar, stop below `min_sim`, exclude the seed's own book, then MMR-diversify; the parity oracle (`tests/test_engines.py` proves the wrapper is byte-identical). | vectors | `skip_top=8 pool=120 mmr_lambda=0.4 min_sim=0.15 dedup_sim=0.97 exclude_same_book=True exclude_same_author=False` | — | `in the resonance band — #43 of 4110 by similarity, past the obvious top matches, from another book` |
| `spread` | Resonance band · set-spread | The same band, but the k picks are chosen as a *set*: greedy DPP MAP on `L = q qᵀ ⊙ S` (q = exp(α·sim), so quality pulls to the seed while the determinant pushes the set apart) or greedy facility-location coverage; no MMR. | vectors | `select=dpp alpha=3.0` + the band knobs | `select covers band_size` | `set-spread pick 1/3 (dpp) — covers 70 of 120 band passages, sim 0.80, #43 of 4110 by similarity` |
| `lexical` | Keyword (BM25) | Pure-Python Okapi BM25 (k1 1.5, b 0.75) over `\w+` tokens minus a small stoplist; a chunk seed becomes its top-n *distinctive* terms by tf·idf, a theme seed its own tokens; needs no vectors. | chunks | `exclude_same_book=False n_terms=12` | `terms` | `keyword match: man, resistance, hireling, adherents, absolute, dispersal (+4 more)` |
| `hybrid` | Dense + keyword (RRF) | Reciprocal-rank fusion (`Σ 1/(60+rank)`) of the dense top-N and the BM25 top-N; a passage both geometries agree on rises, either alone still surfaces. | vectors, chunks | `rrf_k=60 pool=50 exclude_same_book=False` | `dense_rank lexical_rank matched_terms` | `dense #4 + keyword #1 (man, resistance, hireling)` |
| `echo` | Echoes in this book | Same book only — chunks ≥ `gap` positions away in the book's own order, minus repeats and noise, MMR-spread across sections; a theme seed returns `[]` unless `book_id` is given. | vectors | `gap=12 min_sim=0.30 dedup_sim=0.97 mmr_lambda=0.6 pool=120 book_id=None` | `distance heading` | `same book, 15 passages away (APPENDIX II) — sim 0.79` |
| `concept` | Concept graph | Personalised PageRank (numpy power iteration, α 0.15, 30 steps) over the bipartite chunk–concept graph from `concepts.json`, plus `edge:<target>` bridge nodes from `edges.jsonl` weighted by origin (note 1.5 > judged 1.0); a pick must share a concept with the seed; cross-book by default. | concepts | `exclude_same_book=True alpha=0.15 iters=30 min_activation=1e-6 use_edges=True` | `concepts activation` | `via concepts: sciences, knowledge, history` |
| `walk` | Line of flight | A wander: hop 1 is the strongest band pick from the seed into an unvisited book (visited books excluded *before* the skip-top cut), hop 2 the same step from that passage, and so on; k is the number of hops, the list is the path, and it stops when no unvisited book clears the floor. | vectors | `revisit_books=False skip_top=8 min_sim=0.15` | `hop from_id hop_similarity` | `hop 2 from Nietzsche, Volumes I & II — sim 0.82 to the previous step` |
| `marks` | My marks | The reader's own highlights and notes (`workspace.list_annotations()`) embedded as *quote + note*; cosine from the seed to the mark, the pick is the passage the mark sits on, the `why` is the mark; the mark vectors rebuild when the annotation list changes. | vectors, annotations | `min_sim=0.25 exclude_same_book=False` | `annotation_id kind color quote note mark_similarity` | `your highlight — "With this do we now know the _fundamental question of philosophy?_ No— but we k…"` |
| `structural` | Structural (persisted HyDE) | A build step names each chunk's *move* with the LLM and embeds those abstractions into a second matrix (`index/structural_<embed>.npy/.jsonl`); a chunk seed queries with its own stored row, so no LLM at query time; the disclosure is the gap between structural and surface similarity. | structural | `min_struct=0.20 dedup_struct=0.97 exclude_same_book=True` | `structural_similarity surface_similarity gap abstraction` | `same move (0.71 structural vs 0.48 surface): “<abstraction>”` — the format string, not a run; the index is not built here |
| `fused` | Constellation (fused) | Union of every ready constellatory path (band · concept · marks · structural, `pool_each` picks from each), RRF-merged with provenance weights marks 1.5 > structural 1.2 > concept 1.1 > band 1.0, re-ranked by `relevance × surprise` (surprise = 1 + 0.5·(1−sim) + 0.25·[other book]), quotations and noise dropped, the top 3k facility-spread, k survive. | vectors | `pool_each=12 min_sim=0.15 dedup_sim=0.97 spread_factor=3` | `paths contributions relevance surprise cross_book` + pass-through extras | `concept + band — via concepts: sciences, knowledge, nietzsche` |

Two reading notes. `plain`, `lexical` and `hybrid` are the *lookup* end of the dial
and deliberately keep the seed's own book — they are the "obvious" the band throws
away, made visible. `echo` is the other omission made visible: the same book, but far
away. Everything else is cross-book by construction.

## 3. The willingness to find nothing

`MIN_SIM` (0.15) is a per-candidate floor and, with bge-base, it never fires:
embedding spaces are anisotropic and *everything* scores above 0.15. The harness's
first run showed it plainly — every vector engine answered gibberish with eight
confident picks (`noise_fp_rate` 1.00 across the board).

So the contract grew a gate on the seed's *best* match. `Context.noise_floor` is a
per-model calibrated cosine (`config.NOISE_FLOOR = {"bge-base": 0.50}`, read by
`Context.from_store`); `base.clears_noise_floor(seed, ctx)` is False when nothing in
the corpus other than the seed itself resonates above it. `BaseEngine` wraps every
subclass's `candidates()` so a seed that clears nothing returns `[]` before the
engine's own geometry runs. The calibration, measured on the real corpus (4110
chunks, `rhizome/config.py`):

| seed kind | best cosine to the corpus |
|---|---|
| word-salad themes | 0.41 – 0.52 |
| real short themes | 0.55 – 0.78 |
| passage seeds, best cross-book match (min over 400) | ≥ 0.73 |

0.50 sits between the salad and the questions. Models without a calibration are
ungated (`None`), and `Context.from_arrays` (tests) is ungated too.

Two engines opt out (`noise_gate = False`): **`plain`**, because the baseline must
always answer — that is the point of it, the contrast the others are read against —
and **`lexical`**, which gates on term matches rather than cosine (an incoherent
theme that happens to contain a real word still gets a keyword hit; that is what
BM25 *is*). After the gate `noise_fp_rate` fell from 1.00 to 0.33 for the vector
engines; the remaining third is two seeds — the pure gibberish `zxq vlorp tandril…`
(0.512) and `lorem ipsum…` (0.522) — that clear the floor by a hair, while the recipe
and the parking-lot receipt (0.415, 0.416) do not. Real words about the wrong things
are easier to reject than nonsense; that is a fact about the embedding, and 0.50 is
where the line falls today.

When the gate fires the API does not return a bare empty list. `/connect` (and the
`note` SSE event of `/explore`) says why:

```
Nothing in the corpus resonates with this seed above the noise floor
(best match 0.444 < 0.50) — so no connection is offered.
```

— so "nothing" reads as a finding, not a failure. Other empties get the engine's own
reason (`Nothing cleared the Line of flight engine's floors for this seed.`).

## 4. Using them

### CLI

```bash
.venv/bin/python -m rhizome.cli engines
```
```
key          label                            ready  reason
band         Resonance band                   yes
spread       Resonance band · set-spread      yes
plain        Nearest (plain RAG)              yes
lexical      Keyword (BM25)                   yes
hybrid       Dense + keyword (RRF)            yes
echo         Echoes in this book              yes
concept      Concept graph                    yes
walk         Line of flight                   yes
marks        My marks                         yes
structural   Structural (persisted HyDE)      no     structural index not built (run: python -m rhizome.cli build-structural — needs an LLM key)
fused        Constellation (fused)            yes
```

One engine, one seed, geometry only (`--theme`, `--chunk`, `--note` or `--random`
seed the engine; `--json` prints the API items):

```bash
.venv/bin/python -m rhizome.cli connect --engine walk --chunk being-and-truth#0036 --candidates 4
```
```
SEED — being-and-truth#0036 (Martin Heidegger, Being and Truth)
    But philosophy arises from the _ownmost urgency and strength of humanity_ , and
    _not_ of _God_ . It is not absolute knowledge either in its content or in its form. …

Line of flight [walk] — 4 pick(s):

  [0] Martin Heidegger — Nietzsche, Volumes I & II, p.402   (sim 0.801 · #43 of 4110 · score 0.8012)
      why: hop 1 from Being and Truth — sim 0.80 to the previous step
      hop: 1
      To be sure, elsewhere we read: "To 'humanize' the world, that is to say, to feel
      ourselves increasingly as masters in it-" …

  [1] Martin Heidegger — What Is Called Thinking?, p.93   (sim 0.761 · #365 of 4110 · score 0.8227)
      why: hop 2 from Nietzsche, Volumes I & II — sim 0.82 to the previous step
      hop: 2 …

  [2] Michael Inwood — The Heidegger Dictionary   (sim 0.712 · #1617 of 4110 · score 0.7868)
      why: hop 3 from What Is Called Thinking? — sim 0.79 to the previous step …

  [3] Charles Bambach — Heidegger on Poetic Thinking   (sim 0.709 · #1708 of 4110 · score 0.8033)
      why: hop 4 from The Heidegger Dictionary — sim 0.80 to the previous step …
```

Notice the two similarity columns: `sim` is always against the *original* seed (the
axis every engine shares — by hop 4 the walk is at #1708 of 4110 from where it
started), while `score` is the hop's own cosine to the previous step.

Every ready engine on one seed, plus how much they agree:

```bash
.venv/bin/python -m rhizome.cli compare-engines --chunk being-and-truth#0036 --candidates 3
```
```
Resonance band [band]  1.59 ms
  [0] Martin Heidegger — Nietzsche, Volumes I & II, p.402   (sim 0.801 · #43 of 4110 · score 0.8012)
      why: in the resonance band — #43 of 4110 by similarity, past the obvious top matches, from another book
  …
Nearest (plain RAG) [plain]  0.49 ms
  [0] Martin Heidegger — Being and Truth   (sim 0.849 · #2 of 4110 · score 0.8489)
      why: #2 nearest by surface similarity
  …
Concept graph [concept]  16.93 ms
  [0] Martin Heidegger — What Is Called Thinking?, p.160   (sim 0.743 · #724 of 4110 · score 0.000579)
      why: via concepts: sciences, knowledge, history
  …
Constellation (fused) [fused]  7.93 ms
  [0] Martin Heidegger — Being and Truth   (sim 0.809 · #28 of 4110 · score 0.1643)
      why: marks — your highlight — “The _historical path into the essence of philosophy_ —there is no other, for th…”
  [1] Martin Heidegger — Nietzsche, Volumes I & II, p.328   (sim 0.778 · #148 of 4110 · score 0.1584)
      why: concept + band — via concepts: sciences, knowledge, nietzsche
  …
Jaccard overlap of pick sets:
                 band   spread    plain  lexical   hybrid     echo  concept     walk    marks    fused
band             1.00     0.20     0.00     0.00     0.00     0.00     0.00     0.20     0.00     0.00
plain            0.00     0.00     1.00     0.20     0.20     0.20     0.00     0.00     0.20     0.00
lexical          0.00     0.00     0.20     1.00     0.50     0.00     0.00     0.00     0.20     0.00
concept          0.00     0.00     0.00     0.00     0.00     0.00     1.00     0.00     0.00     0.00
marks            0.00     0.00     0.20     0.20     0.20     0.00     0.00     0.00     1.00     0.50
```

The matrix is the "same question, different geometries" moment in numbers: the
lookup engines (`plain`, `lexical`, `hybrid`, `echo`) overlap one another and nothing
else; the band family (`band`, `spread`, `walk`) overlap one another; `concept` agrees
with no one, which is exactly what a non-vector path should look like.

The rest:

```bash
.venv/bin/python -m rhizome.cli eval-engines [--k 8] [--engines band,walk] [--refresh]   # §5
.venv/bin/python -m rhizome.cli build-structural [--model bge-base] [--sample N] [--book ID …]
```

`build-structural` needs an LLM key (GROQ / GEMINI / ANTHROPIC); abstractions are
cached by content hash in `index/cache_structural.json` and flushed every 64 calls,
so an interrupted run resumes for free and `--sample`/`--book` warm the cache for a
later full build.

### HTTP (`/api/v2`)

| route | what it returns |
|---|---|
| `GET /engines` | `{"engines": [card…], "default": "band"}` — each card `key · label · blurb · needs · params · ready · reason` (the reader shows `reason` instead of a dead option) |
| `GET /connect?engine=walk&mode=chunk&value=being-and-truth%230036&candidates=4` | `{engine, seed, items, params, ms, note}` — `items` in the reader's ITEM shape (`chunk_id · author · title · page · text · similarity · rank · corpus_size · score · path · why` + the engine's extras); `params` is what the engine actually ran with; `note` is the empty-reason or null. Engine knobs ride along as extra query params (`&skip_top=4`), coerced by the declared type. `mode` is `chunk`, `theme` or `random`. |
| `GET /connect/compare?mode=chunk&value=…&candidates=3[&engines=band,walk]` | `{seed, results: [{key, label, items, ms, error?}], overlap: {keys, matrix}}` — Jaccard of the pick sets |
| `GET /explore?…&engine=concept` | the existing SSE run, candidates routed through the chosen engine; a new `engine` event, `candidates.params.engine`, and every item carrying `path · why · rank` + extras, so judge and synthesis (with a key) apply to any engine's picks |
| `GET /engines/eval` | the cached harness report (`index/eval_engines.json`); 404 with the CLI hint until built |

### The reader

The Connections rail (`frontend/src/reader/ConnectionsPanel.tsx`) is where the
engines are meant to be felt:

- **Picker** — a compact select in the rail head, blurb on hover; the choice is kept
  in `localStorage` and mirrored as `?engine=<key>` in the reader URL (dropped when
  it is the default), so a link carries its geometry. Not-ready engines stay listed
  with their `reason` ("structural isn't ready: structural index not built…").
- **Disclosure per pick** — the `why` line, the resonance meter, and `#rank of N`
  next to it (1-based, tooltip: "how non-obvious the pick is"). A `walk` renders as
  a numbered chain of hops; a `marks` pick shows the quote/note and an *open note*
  action back to the annotation; `concept` picks list their shared concepts as chips.
- **Compare** — the toggle in the rail head fetches `/connect/compare` for the current
  seed and stacks every ready engine's top three (a stacked list, not a table — the
  20rem rail cannot hold one), the selected engine highlighted with how many picks
  each other engine shares with it.
- **Connect from selection** — the selection toolbar's *Connect* seeds the engine
  from the selected text (theme mode), so a sentence, not only a chunk, can be a seed.
- When an engine returns nothing the rail shows the `note` ("Nothing in the corpus
  resonates…"), not an empty box.

## 5. The eval harness

`rhizome/eval_engines.py` — PRD §6c, the automatable subset. Ordinary retrieval
eval asks "did the gold passage come back?"; a constellatory engine is measured on
proxies for *non-obvious* resonance instead. Every registered engine runs over the
same deterministic seed set (every ⌊N/40⌋-th chunk) plus six incoherent theme
seeds (`NOISE_SEEDS`: word salad, a pancake recipe, lorem ipsum), so the rows are
comparable. The report goes to `index/eval_engines.json`; `--engines a,b` refreshes
those rows inside the stored report rather than clobbering the table.

| column | meaning |
|---|---|
| `seeds` | chunk seeds run |
| `mean_k` | mean picks returned (k = 8 asked) — below k means the engine stopped early |
| `empty` | share of seeds where the engine found nothing at all |
| `rank%` | mean corpus rank of the picks as a percentage (0 = the top hit; a band engine should live mid-band) |
| `med_rank` | the same, as a raw median rank |
| `ild` | intra-list diversity: mean pairwise (1 − cos) across each pick set — the set-spread proxy |
| `books/k` | distinct books per pick set, divided by picks |
| `x-book` | share of picks from a book other than the seed's |
| `noise_fp` | share of incoherent seeds still answered — willingness to find nothing; lower is better |
| `bridge_r` | held-out bridge recall@k: judged edges in `edges_judged.jsonl` whose source and provenance are both chunk ids |
| `ms` | wall time per seed |

The current table (`.venv/bin/python -c "from rhizome import eval_engines as e; print(e.format_table(e.load_report()))"`):

```
Constellatory engine eval  ·  embed=bge-base  ·  k=8  ·  40 chunk seeds + 6 noise seeds  ·  0 held-out bridges  ·  built 2026-08-15T21:30:04+00:00

engine      seeds  mean_k  empty  rank%  med_rank    ild  books/k  x-book  noise_fp  bridge_r     ms
----------  -----  ------  -----  -----  --------  -----  -------  ------  --------  --------  -----
band           40    8.00   0.00   4.7%       160  0.274     0.48    1.00      0.33       n/a    2.2
spread         40    8.00   0.00   3.9%       132  0.273     0.49    1.00      0.33       n/a  146.0
plain          40    8.00   0.00   0.1%         4  0.157     0.18    0.12      1.00       n/a    0.3
lexical        40    8.00   0.00   5.8%        14  0.205     0.18    0.11      0.67       n/a   13.2
hybrid         40    8.00   0.00   1.1%         5  0.171     0.17    0.10      0.33       n/a    1.8
echo           40    8.00   0.00   1.3%        22  0.222     0.12    0.00      0.00       n/a    2.4
concept        40    8.00   0.00  35.1%       962  0.266     0.37    1.00      0.00       n/a    2.5
walk           40    7.00   0.00  25.5%       690  0.241     1.00    1.00      0.33       n/a    3.3
marks          40    6.00   0.00  47.0%      1946  0.183     0.17    0.85      0.33       n/a    2.4
structural  not ready: structural index not built (run: python -m rhizome.cli build-structural — needs an LLM key)
fused          40    8.00   0.00  39.3%      1498  0.262     0.37    0.95      0.33       n/a    7.2
```

How to read it:

- **`plain` rank% ≈ 0 by design** — median rank 4, `x-book` 0.12: it is the top hits,
  mostly from the seed's own book. `hybrid` and `lexical` sit next to it (the lookup
  end). `echo` is 0.00 cross-book because it is defined that way.
- **`band` / `spread` are mid-band** — median rank 130–160 of 4110, every pick from
  another book, ild ~0.27 (the highest set-spread of any engine, so MMR and DPP are
  earning their keep). `spread` is a hair further out and a hair more diverse than
  `band` at ~70× the cost (the DPP over a 120-passage band); worth it in the rail,
  not in a loop.
- **`concept` and `walk` reach furthest** — median rank 962 and 690: passages the
  vectors would never have ranked near the top, reached through a shared idea or a
  chain of hops. `walk` is 1.00 books/k by construction (one new book per hop) and its
  `mean_k` of 7 shows it stopping when the unvisited books run out.
- **`marks` is bounded by the workspace** — mean_k 6, ild 0.18: there are only so many
  marks, and they cluster where the reader has been reading.
- **`noise_fp`** was 1.00 for every vector engine before the noise-floor gate and is
  0.33 after (§3). `plain` stays at 1.00 on purpose; `lexical` at 0.67 gates on words,
  and four of the six seeds contain real ones. `concept` and `echo` are 0.00 for
  structural reasons (no concept overlaps; a theme has no home book).
- **`bridge_r` is n/a** until `edges_judged.jsonl` has chunk-addressed bridges (source
  and provenance both chunk ids). Today it has none; the column and `n_bridges` are
  wired and waiting.

## 6. Adding an engine

1. New module `rhizome/engines/<key>.py`; the registry finds it by itself.
2. `class MyEngine(BaseEngine)` with `key · label · blurb · needs · params`.
3. Implement `candidates(self, seed, ctx, *, k=config.N_CANDIDATES, **params)`;
   build picks with `decorate(idx, ctx, path=self.key, why=…, score=…, sims=, rank=)`
   or, if you rank on something other than cosine, copy the chunk and call
   `finish(picks, seed, ctx)` to back-fill `similarity` / `rank` / `corpus_size`.
4. Side data goes through `ctx.side("name", builder)` so a server pays once; override
   `ready()` to say *why not* when it is missing.
5. Set `noise_gate = False` only if the engine must always answer or gates on
   something other than cosine; otherwise the floor wraps you automatically.
6. Return `[]` when nothing clears your floors. Never pad.
7. `ENGINE = MyEngine()` at module level; add the key to `ORDER` if it should sit
   somewhere particular in the picker.
8. Tests on `Context.from_arrays(*fixture_corpus.make_corpus())` in
   `tests/test_engine_<key>.py`; the contract test in `tests/test_engines.py`
   (fields present, deterministic, copies, ≤ k) runs against every registered engine
   without being told.

## 7. Known limits, and next

- **`structural` needs an LLM key to build.** Everything else in this document ran
  without one; the structural row is "not ready" until `build-structural` has been
  run (~4k abstractions, cached, resumable). Once built, `fused` folds it in at weight
  1.2 without any change.
- **`concept` quality is bounded by the extractor.** `index/concepts.json` is the
  heuristic tf·idf pass (`mode: heuristic`, 160 concepts) — hence `why: via concepts:
  sciences, knowledge, history`, which is true and a little dull. `rhizome concepts
  --llm` is the upgrade path; the engine does not care which built the file.
- **`marks` has a floor of its own** (`min_sim` 0.25) and a ceiling the harness shows:
  it can only be as wide as the reader's marks. That is the point, but it means the
  engine grows with use rather than with the corpus.
- **Theme seeds and `skip_top`.** A theme seed goes through the same band as a
  passage — the eight most-similar are skipped as "obvious". For a passage that is
  right; for a question the eight most-similar may be the answers. `?skip_top=0` on
  `/connect` is the workaround; the principled fix is a seed-kind-aware default.
- **Not done, deliberately** (PRD phases): the LanceDB/Qdrant bake-off (Phase 1 —
  no speed need at 4k chunks; the numpy exact scorer is the reference), and the
  late-interaction / cross-encoder rerank (Phase 4 — needs a model and an eval
  first). Bridge recall waits on judged, chunk-addressed edges.
