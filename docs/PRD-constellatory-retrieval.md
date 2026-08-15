# PRD / Research Brief — Constellatory Retrieval & the Vector-Store Layer

> Where the retrieval lane is now, which vector-DB architectures actually serve
> *constellatory* retrieval (as opposed to ordinary RAG), and how to integrate
> and test them. Grounded in the current code (`rhizome/store.py`,
> `engine.py`, `embed.py`, `graph.py`, `config.py`) and the vision
> (`docs/VISION.md`, `ROADMAP.md`, `SCHEMA.md`, `CHUNKING.md`). Research current
> to 2026; treat the fast-moving items (flagged **[2025+]**) as living.

---

## 0. The one idea to hold onto

RhizomeDB is **not** doing retrieval-augmented lookup, so it should **not** adopt a
vector database the way a normal RAG app does. Standard vector DBs are engineered to
return the *k nearest* passages as fast as possible. Constellatory retrieval wants
almost the opposite: the **related-but-distant** band, **diversified** across books,
**structurally** matched, with the obvious near-duplicates **demoted**, and every
result **grounded and attributed**. `store.connections()` already encodes this
inversion (skip-top, dedup ceiling, min-sim floor, MMR, same-book exclusion).

Two consequences frame everything below:

1. **Speed is not the reason to adopt a vector DB here.** At ~4,100 chunks — even at
   100k across many traditions — the brute-force `vecs @ seed_vec` matmul in
   `store.py` is effectively instant and returns *exact* scores, which the resonance
   band actually needs (a band and an MMR pool want true similarities, not an ANN
   approximation of the top-k). So we do **not** rip out the numpy store. We keep it
   as the exact-scoring core and *add* capabilities around it.

2. **The reason to adopt vector-DB architecture is its retrieval primitives** —
   named/multi-vector storage, late-interaction matching, hybrid sparse+dense,
   set-level diversity, and a graph path — each of which maps to a *specific*
   constellatory need. The plan is to acquire those primitives behind one retrieval
   interface, not to migrate storage engines for their own sake.

---

## 1. What exists today (extracted from the repo)

**Embedding.** Local, offline ONNX via `fastembed` (`embed.py`). Default `bge-base`
(768-d), plus `minilm`, `bge-small`, `snowflake-arctic-m` in a registry
(`config.EMBED_MODELS`). Vectors L2-normalised so cosine = dot product. Asymmetric
models get a query-side instruction prefix; the corpus side does not. Persisted as a
flat `index/embeddings.npy` (N×dim float32), row *i* ↔ chunk *i*.

**Store + geometry** (`store.py`). One in-memory matrix. `connections(seed_vec)`:
computes all cosines, then builds the **resonance band** — drop anything ≥
`DEDUP_SIM` (0.97, a verbatim quotation of the seed), skip the `SKIP_TOP` (8) most
similar (the "obvious"), stop below `MIN_SIM` (0.15, noise floor), exclude the seed's
own *book* (not author — intra-corpus surprise is the aim). Then **MMR**
(`MMR_LAMBDA` 0.4, diversity-favouring) picks `N_CANDIDATES` (8) that are each
resonant with the seed but diverse from one another. Every result carries its
`similarity` and its `rank` in the full corpus sort — the proof that a pick was a
mid-band resonance and not a top hit.

**Engine** (`engine.py`). `explore()`: resolve a seed (theme / chunk / random) →
optional **Structural-HyDE** (LLM abstracts the seed's *move*, re-embed on that, so
lexically-distant but structurally-kindred passages come within reach) → band
candidates → **LLM judge** (keep genuine, drop `forced_risk == high`) → synthesize →
optionally **persist judged bridges** to the graph. `wander()` follows the strongest
confirmed connection as the next seed — a line of flight through the rhizome.

**The concept graph** (`graph.py`) — described in its own docstring as "a **second
retrieval path**." Embedding geometry can only surface what is *near*; the
connections worth having are often structural and lexically distant. So an
**attributed** edge store accretes: hand-authored `SEED_EDGES`, one edge per
`correlate` reading-note annotation, and every bridge the judge confirms
(`edges_judged.jsonl`, append-only). Each edge records *who asserts it and where*
(`origin ∈ {authored, note, judged}`, `provenance`) — contested/contradictory links
are held without being flattened to "truth."

**Multi-resolution — the solid→liquid dial** (`chunking.py`, `config.py`,
`CHUNKING.md`). Same corpus at linked granularities: `parent` (~500 w, LIQUID /
constellatory) ⊃ `chunk` (~240 w, the working unit, == legacy `chunks.jsonl`) ⊃
`proposition` (atomic statements, SOLID / praxis). Every unit carries
`parent_id`/`child_ids`; `parents_of()` implements small-to-big (match the precise
unit, hand the LLM its larger parent). The chunk level is never rebuilt (it would
desync `embeddings.npy` and break stable ids / saved annotations).

**Concepts** (`concepts.py`): tf-idf heuristic + LLM extractor → `concepts.json`
(concept ↔ chunks). **Baseline plain RAG** (`rag.py`): the deliberate opposite —
top-k nearest, no exclusions — kept so the contrast with constellatory retrieval is
visible and measurable.

**Evaluation today** (`eval_embed.py`): an in-domain gold set
(`eval/embed_gold.jsonl`, query → the passage that answers it, labelled by *lexical*
search so labels are independent of any embedding) scored with Recall@{1,3,5,10},
MRR, median rank — **plain cosine**, to measure whether a *model* understands the
corpus. There is **no** harness yet for the constellatory layer itself (disclosure,
groundedness, non-obviousness) — the roadmap lists it as queued (A: "groundedness ×
disclosure, chamatkāra as the human signal").

**The honest gaps.**
- The store is single-vector, single-space. Structural-HyDE is recomputed by an LLM
  *every* run instead of living as a persisted structural space.
- MMR is pairwise-greedy; it models redundancy against already-picked items only, not
  set-level diversity.
- The graph is a *store*, not yet a *retrieval path*: nothing traverses it to
  generate candidates. `explore()` reads embeddings; it does not walk edges.
- No late-interaction / token-level matching — the mechanism best suited to
  "structural rhyme."
- Evaluation covers the SOLID lookup end only; the LIQUID constellatory end (the
  actual product) is unmeasured.

Everything below targets those five gaps.

---

## 2. Constellatory needs → retrieval primitives (the mapping)

This table is the spine of the plan: each row is a thing the vision demands, the
primitive that serves it, and where it lives in the code.

| Constellatory need (vision) | Retrieval primitive | Today | Target |
|---|---|---|---|
| Surface *structural* rhyme, not surface words | **second "structural" vector per unit** + **late-interaction (ColBERT/MaxSim)** | Structural-HyDE recomputed per run | Persisted structural space; token-level rerank |
| Related-but-distant "resonance band" | large candidate **pool** + exact scores + band cuts | ✓ brute-force + band | keep exact core; widen pool cheaply |
| Diverse across books & ideas | **set-level diversity** (DPP / submodular), not just pairwise | MMR (pairwise greedy) | DPP / facility-location selection |
| The solid→liquid dial | **hybrid dense+sparse**, mode by dial position | per-level dense only | sparse/BM25 at the solid end; dense band at liquid |
| Bridges embeddings can't see | **graph as a first-class path** (spreading activation / PPR) | graph stored, not walked | activate the attributed graph, fuse with vectors |
| Surprise that is *disciplined* | **provenance-weighted ranking** + **willingness to find nothing** | judge drops forced; edges attributed | weak-ties / betweenness surprise score + provenance weights |
| Grounded, cited, attributed | **payload/metadata storage** alongside vectors | jsonl records | keep provenance first-class in whatever store |
| Read at any resolution | **per-level indexes** + small-to-big | ✓ levels + `parents_of` | per-level named vectors / collections |

Note the crucial asymmetry the dial implies: **sparse/keyword retrieval helps the
SOLID end and hurts the LIQUID end.** BM25 surfaces lexical near-matches — exactly the
"obvious" the constellatory band throws away. So hybrid isn't "always on"; the
retrieval *mode* is a function of the dial position. F1 / praxis / proposition →
hybrid or sparse-leaning; constellatory / parent → dense band, structural vector,
graph activation, sparse *off*.

---

## 3. Vector-DB architectures, mapped to those needs (2026 research)

### 3a. Engines — the local-first field

The binding constraint is **truly embedded, offline, single-user on a laptop**. At
this corpus size ANN index quality is nearly irrelevant (brute force is instant), so
the axes that matter are: named/multi-vector, native hybrid + fusion, native
diversity, provenance-friendly payloads, and *actually* in-process.

| Engine | Embedded/in-proc | Named + multi-vector | Hybrid + fusion | Native diversity | Verdict for us |
|---|---|---|---|---|---|
| **LanceDB** | ✓ true (file-based, serverless) | ✓ multi-column **+ multivector/ColBERT** | ✓ FTS + RRF/linear/**ColBERT rerank** | rerankers, no MMR primitive | **Top pick** — cleanest match to *all* needs incl. surface+structural vectors, in one embedded lib |
| **Qdrant (local mode)** | ✓ Python in-proc; **Edge** (Rust embedded) beta **[2025+]** | ✓ **named vectors + multivector (MaxSim)** | ✓ sparse + **RRF/DBSF** | ✓ **native MMR + grouping** | **Co-pick** — richest primitives; only local-mode/Edge-beta friction |
| **sqlite-vec** | ✓ single-file extension | ✗ (separate tables), no LI | pair with FTS5 (BM25) | ✗ | Lightest embed; hand-roll everything; pre-1.0 |
| **Milvus Lite** | ✓ but Linux/macOS only | ✓ multi-vector + BM25 | ✓ Weighted/RRF | grouping, not MMR | Capable but OS-limited subset |
| **DuckDB VSS** | ✓ | ✗ | FTS + SQL | ✗ | Only if pipeline already DuckDB; persistent ANN unsafe |
| **VectorChord (Postgres)** | server (local ok), AGPL | ✓ + ColBERT MaxSim | ✓ **native BM25 + RRF** | ✗ | Best if you want SQL/relational metadata + a local PG |
| **Chroma** | ✓ | ✗ **no multi-vector** | partial | ✗ | Easiest DX, but no multi-vector kills the surface+structural design |
| **Weaviate / Vespa** | server-oriented | ✓ deep (ColBERT/ColPali, MUVERA) | ✓ deepest | grouping | Most powerful, worst fit for a laptop single-user app |
| **Turbopuffer** | ✗ cloud-only | — | — | — | Disqualified (no offline mode) |

**Bottom line:** only **LanceDB** and **Qdrant (local)** give you *named/multi-vector*
**and** *embedded operation* **and** *native hybrid+fusion* in one package today.
Those are the two to prototype. LanceDB wins on "genuinely a file, no process";
Qdrant wins on native diversity + grouping. (Note **Kùzu**, the obvious embedded
graph+vector answer, was **archived Oct 2025** — see §3c.)

### 3b. Late interaction — the primitive for "structural rhyme" **[2025+]**

Single-vector dense retrieval *pools* all tokens into one vector; the signal that
makes two passages structurally kin can be averaged away. **Late interaction** keeps
one vector per token and scores by **MaxSim** (each query token takes its max over
document tokens, summed) — a soft, learned term-matching that rewards a few strong
token-level alignments rather than global proximity. This is exactly the mechanism to
catch a passage that *moves* like the seed while sharing little vocabulary — the thing
Structural-HyDE is reaching for with an LLM round-trip.

Small models make this laptop-viable now:

| Model | Size | Note |
|---|---|---|
| **mxbai-edge-colbert-v0** (17M / 32M) | 275 / 366 MB | Oct 2025; 17M beats ColBERTv2 on BEIR; excellent long-context; CPU-viable |
| **answerai-colbert-small-v1** | 33M | Beats `bge-base` on BEIR; the standard small reranker |
| **GTE-ModernColBERT-v1** | ~150M | Strongest of the small class; ModernBERT 8k context |
| ColBERTv2 (+ PLAID) | ~110M | Reference baseline |

Two ways to use it, cheapest first: **(1) rerank** — dense/band first stage retrieves
a pool, MaxSim reranks; you store multi-vectors for nothing, only compute at query
time. **(2) native multivector index** (Qdrant/LanceDB) — full late-interaction
retrieval, at a storage cost mitigated by int8/binary token quantization (~4×) or
**MUVERA** fixed-dim encoding (big memory cut, some recall loss). For our scale,
**quantized rerank first**; native multivector only if it earns its keep in eval.

### 3c. Graph + vector fusion — the biggest conceptual win **[2025+]**

The vision explicitly wants the concept graph to be a *retrieval path*, and the code
already accretes an **attributed** graph. What's missing is traversal. The 2026
literature converges on two mechanisms, both a natural fit:

- **Spreading activation** (arXiv 2512.15922, Dec 2025; 2606.30133, 2026): activation
  spreads BFS from seed nodes through **query-weighted edges** with decay; nodes over
  threshold retrieve their passages. No LLM-guided traversal, cheap, and *trivially
  attributable* — weight edges by who asserted them.
- **Personalized PageRank** (HippoRAG / HippoRAG 2, arXiv 2502.14802, 2025): seed from
  query-matched nodes, random-walk teleport ranks the whole graph by association —
  one-shot multi-hop, purpose-built for surfacing non-obvious bridges.

And the **surprise** signal has real prior art: Granovetter's **weak ties** (bridging
ties give access to novel information) and **betweenness centrality** (high-betweenness
edges are the bridges *between* otherwise separate clusters). A defensible
"serendipity" score for a candidate connection: *it crosses communities / traverses a
high-betweenness edge* × *provenance weight of the linking edges* × *inverse trivial
similarity* — i.e. deliberately invert standard RAG so the obvious near-duplicate
loses. **No off-the-shelf system treats edge provenance as first-class** (GraphRAG's
community summaries actively lose it) — that is rhizome's differentiator to build, not
buy.

**Storage for the graph path (local).** Given Kùzu's Oct-2025 archival, the safe,
stable choice is **NetworkX in-process** (pure-Python; ships PPR, betweenness,
community detection) over the existing `edges.jsonl`, with vectors staying in
LanceDB/Qdrant/numpy. Reach for a Kùzu fork (`ryugraph`/`bighorn`) or a local
**Neo4j + GDS** only if graph *scale* or batteries-included algorithms later demand
it. Heavy **Microsoft GraphRAG** is the wrong tool: expensive LLM-authored community
summaries that *interpolate rather than cite* — the opposite of the groundedness
ethic. If a hierarchical-summary layer is ever wanted, **RAPTOR** (recursive
cluster-summary tree) or **LightRAG** (incremental, dual-level, cheap) are the
grounded-friendlier references.

---

## 4. Recommended architecture

A single **retrieval abstraction** with the numpy exact-scorer as the reference
implementation, and three retrieval *paths* fused by a ranking layer that encodes the
constellatory ethic. Nothing here forces a storage migration; each capability is
additive and independently testable.

```
                                  ┌─────────────────────────────────────────┐
   seed (theme / chunk / random)  │            RETRIEVAL PATHS                │
            │                     │                                           │
            ▼                     │  1. dense band     (surface vector)       │
   ┌──────────────────┐          │     exact cosine → resonance band          │
   │ seed resolution  │──────────▶  2. structural     (structural vector      │
   │ + level (dial)   │          │     persisted HyDE/abstraction space)      │
   └──────────────────┘          │  3. graph activation (attributed edges:    │
            │                     │     spreading-activation / PPR)            │
            │                     └───────────────────┬───────────────────────┘
            ▼                                         ▼
   ┌──────────────────┐              ┌─────────────────────────────────┐
   │  candidate pool  │─────────────▶│  FUSE + RE-RANK                  │
   │ (union of paths) │              │  • late-interaction MaxSim (opt) │
   └──────────────────┘              │  • provenance / weak-tie surprise│
                                     │  • set-level diversity (DPP)     │
                                     └────────────────┬────────────────┘
                                                      ▼
                                         judge → synthesize → accrete → wander
                                         (unchanged; the ethic already lives here)
```

**Path 1 — dense band.** Today's `store.connections()`, unchanged as the core. Keep
numpy for exact scores; the band and pool need them.

**Path 2 — structural vector.** Persist a *second* vector per unit — the
Structural-HyDE abstraction (or a late-interaction token set) — computed once at build
time, not per query. This is a **named vector** (Qdrant) or a **second column**
(LanceDB). It turns the run-time LLM abstraction into an index, and lets a seed be
matched on its *move* directly.

**Path 3 — graph activation.** Seed the attributed graph at the concepts/nodes the
seed touches; spread activation (or PPR) over provenance-weighted edges; the passages
of activated nodes join the candidate pool *flagged by origin* (authored / note /
judged). This finally makes the graph the "second retrieval path" its own docstring
promises.

**Fuse + re-rank.** Union the pools, then rank by a constellatory score that is
explicitly *not* max-similarity: relevance (band membership) × structural agreement
(MaxSim, optional) × surprise (crosses books/communities, high-betweenness bridge) ×
provenance weight (human note > judge > co-occurrence), with near-duplicates demoted
(already done by `DEDUP_SIM`). Replace pairwise MMR with **DPP or facility-location**
selection for genuine set-level spread. Preserve the **willingness to find nothing**:
if nothing clears the floors, return empty — a machine that always finds a profound
connection is lying (`VISION.md`).

**Recommended concrete stack (v1):** **LanceDB** (embedded; surface + structural
columns; optional multivector; FTS for the solid end) **+ NetworkX** over the existing
`edges.jsonl` (activation/betweenness) **+ the numpy exact-scorer retained** for band
scoring and as the parity oracle. Qdrant-local is the fallback if native MMR/grouping
and named vectors prove more ergonomic in the prototype bake-off (Phase 1).

**What we deliberately do *not* do:** adopt a server DB (Weaviate/Vespa/Milvus-full),
adopt Microsoft GraphRAG, or delete the numpy store. None serve a local-first,
groundedness-first, single-reader instrument.

---

## 5. Phased integration plan

Each phase is a **one-off**, independently shippable, guarded by a test, and leaves
the current engine working if abandoned.

**Phase 0 — Retrieval interface + parity harness (enabling).**
Introduce a `Retriever` protocol (`candidates(seed, level, mode) -> list[dict]`) with
`NumpyStore` as the reference impl — a pure refactor of `store.connections()` behind
an interface, zero behaviour change. Add a **parity test**: any future backend must
reproduce `NumpyStore`'s band on a fixed seed set within tolerance. *Ship criterion:
byte-identical candidates to today.*

**Phase 1 — Embedded store bake-off (LanceDB vs Qdrant-local).**
Load the existing `embeddings.npy` into both; reimplement the band as a re-rank over a
retrieved pool; verify parity vs numpy. Decide the v1 engine on ergonomics for named
vectors + diversity + payload/provenance. *Ship criterion: parity + a one-command
build path; numpy still default.*

**Phase 2 — Structural vector (persisted HyDE).**
Add a `structural` named vector/column: at build time, abstract each unit's *move*
(reuse `llm.abstract_seed`), embed, store. Add a `structural` retrieval mode; fuse
with the dense band. *Ship criterion: on held-out `correlate` edges (see §6),
structural path raises bridge-recall over dense-only.*

**Phase 3 — Graph as a retrieval path.**
NetworkX over `edges.jsonl` + `concepts.json`; spreading-activation / PPR from seed
nodes; provenance-weighted; passages of activated nodes enter the pool, origin-flagged.
Add a betweenness/weak-tie **surprise** score to the re-ranker. *Ship criterion:
the engine rediscovers held-out human `correlate` bridges it was not given.*

**Phase 4 — Late-interaction rerank.**
Add `answerai-colbert-small` or `mxbai-edge-colbert` as an optional MaxSim re-rank over
the pool (quantized, CPU). Gate behind eval — keep only if it lifts disclosure quality.
*Ship criterion: net positive on the constellatory harness (§6), acceptable latency.*

**Phase 5 — Diversity upgrade + dial-aware hybrid.**
Swap pairwise MMR for **DPP / facility-location** set selection. Wire **BM25/FTS** in
for the SOLID end only (F1 / proposition), sparse *off* for constellatory. *Ship
criterion: higher intra-list diversity at equal/again-judged relevance; solid-end
lookup recall up with sparse on.*

Phases 2–5 are independent — reorder by appetite. Phase 3 (graph path) is the highest
*conceptual* payoff and aligns most tightly with the vision; Phase 2 is the cheapest
*mechanical* win.

---

## 6. Testing & evaluation strategy

The product is the LIQUID end, and it is currently unmeasured. Testing has to cover
three very different questions, and most of the value is in the second and third.

### 6a. Correctness / parity (guards, automatable)
- **Band parity**: every new backend reproduces `NumpyStore`'s candidates on a fixed
  seed set (Phase 0 harness). Non-negotiable regression gate.
- **ANN recall vs exact** *(only if an ANN index is ever enabled)*: recall@k of the
  index against brute-force. At this corpus size, prefer exact/flat and skip ANN
  entirely — document the decision so no one "optimises" it in later.
- **Groundedness/citation**: automated check that every surfaced connection resolves
  to a real chunk id + citation metadata (author/work/page). The vision's first
  non-negotiable; cheap to assert.

### 6b. The SOLID end — extend what exists
`eval_embed.py` already does in-domain Recall@{1,3,5,10} / MRR / median-rank over a
lexically-labelled gold set. Keep it as the **model-and-mode** scorer; run it per
backend and per level. Add a **hybrid** row (dense vs +BM25) to confirm sparse helps
the solid end. This end has a right answer, so standard IR metrics apply.

### 6c. The LIQUID end — the constellatory / disclosure harness (new; roadmap A)
The connection has no single right answer, so measure the *properties* the vision
names — **grounded × disclosing × non-obvious × willing-to-find-nothing** — with a mix
of automatable proxies and judged signals.

**The keystone eval — held-out bridge recall (offline, automatable, no new labels).**
The repo already contains gold bridges: `SEED_EDGES`, every `correlate` annotation,
and confirmed `edges_judged`. **Hold one out**, seed the engine from its source, and
ask whether constellatory retrieval surfaces the *target* passage/work it was not told
about. This is a clean, reproducible "can it rediscover a human's leap" metric —
report recall@k of held-out bridges, per path (dense / structural / graph / fused).
It directly tests the product thesis and needs zero manual labelling.

**Automatable disclosure proxies** (borrowed from IR/recsys diversity literature):
- **Non-obviousness / novelty**: the corpus `rank` already recorded per result — a
  good pick sits in the mid-band, not the top. Report the rank distribution; penalise
  top-hits and near-dupes.
- **Intra-list diversity (ILD)**: mean pairwise dissimilarity of the returned set —
  are picks spread across books/ideas?
- **α-nDCG / subtopic recall**: reward novelty/coverage, penalise redundancy — the
  standard diversity-IR metrics, computed against concept tags from `concepts.json`.
- **Serendipity = unexpected × relevant**: combine low direct similarity with the
  judge's `connected & confidence` — a connection that is both surprising and
  defensible.
- **Willingness to find nothing**: on deliberately *incoherent* seeds (random noise,
  cross-domain gibberish), the engine should return **empty or low-confidence**. A
  quantified false-positive rate — the "a machine that always finds a connection is
  lying" test.

**Judged signals** (the human half of the loop):
- **LLM-judge panel** (already in `engine.py`): report confirmed-vs-forced rates, and
  guard against a judge that rubber-stamps by seeding it with known-bad pairs.
- **chamatkāra as the human signal** (roadmap A): the `chamatkara` annotation intensity
  marks where the corpus lit up for the reader — the ground-truth "disclosure quality"
  label no relevance metric captures. Track the rate at which engine-surfaced
  connections earn a `chamatkara` mark when read.

### 6d. Ablations (how we actually decide)
Fix a seed set; run the matrix — {dense, +structural, +graph, +late-interaction} ×
{MMR, DPP} — and compare on the 6c metrics + held-out bridge recall. This is how each
phase earns its keep or is reverted. Bake it into a `rhizome eval constellatory`
command next to `eval_embed`, emitting a small report + the doc-map style HTML so the
comparison is legible.

**Acceptance for the whole effort:** each added path measurably raises held-out bridge
recall and/or disclosure proxies *without* raising the incoherent-seed false-positive
rate — surprise that stays disciplined.

---

## 7. Decisions needed & risks

- **◆ v1 engine**: LanceDB (recommended) vs Qdrant-local. Resolve empirically in
  Phase 1; both keep numpy as the parity oracle.
- **◆ Structural path shape**: a single persisted "structural" dense vector (cheap,
  Phase 2) vs full late-interaction multivectors (richer, heavier, Phase 4). Start
  with the former; let eval pull in the latter.
- **◆ Graph engine**: NetworkX-in-process (recommended, stable) vs a Kùzu fork vs
  local Neo4j+GDS. Only escalate past NetworkX if scale/algorithms demand it.
- **Risk — Kùzu abandonment [2025+]**: do not build on archived Kùzu; if a Kùzu fork
  is chosen later, pin to `ryugraph`/`bighorn` and treat as provisional.
- **Risk — fast-moving late-interaction models**: the small-ColBERT field is churning
  monthly; keep the model behind the embedder registry so swaps are one line.
- **Risk — over-engineering**: at this corpus size none of this is needed for *speed*.
  Guard against adopting machinery that adds ops burden without moving a 6c metric —
  the eval harness is what keeps the project honest here, same as its own ethic.

---

## 8. The other lane (reader) — scope note

This brief covers the **retrieval / engine** lane only, per the request. The **reader
/ annotation** lane (the audits in `docs/audits/`, `reader_service.py`, `anchor.py`,
the marginalia UI) is the human half that *feeds* this engine — its `correlate` /
`sutra` / `chamatkara` marks are literally the training and evaluation signal in §6.
A parallel research brief for that lane (annotation-anchoring robustness, the
long-running whole-book reader-agent, the marginalia/notes-rail rendering defects the
audit found) can follow the same shape: extract → research → phased plan → test. Say
the word and I'll produce it.
