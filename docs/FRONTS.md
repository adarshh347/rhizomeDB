# RhizomeDB × Rhizome Reader — Development Fronts

> The multi-front plan: where things can be developed, in what stages, and what
> each stage is expected to deliver. Two ends of one project: **the engine**
> (intelligent meaning — beyond similarity/RAG) and **the reader** (the medium
> the user lives in — UX, embodiment). Semant (`../semant`) is the sibling to
> learn from on the reader end. Drafted 2026-07-19. Companion docs: ROADMAP
> (status ledger), FORMATS (pipeline lines), CHUNKING/PRD-chunking, the three
> reader PRDs (ai-annotations, behavioral-reading, research-writer),
> semant's `notes_theory/structural_retrieval_research.md` + `constellatory_retrieval.md`.

Status of the codebase this plan starts from: engine complete through F1 +
constellatory geometry + structural-HyDE + judged-bridge accretion; multi-res
chunking scaffolded in `config.py`/`chunking.py`/`enrich.py` but not fully
built/run; reader UI exists (library/book/plateau) with annotations, chat,
concept graph; three reader PRDs written but unbuilt; F2 declared but not
started.

---

## Front 1 — Advanced retrieval (F2: the researched RAG line)

*The "left off" front. Goal: retrieval that reaches structurally-kindred,
lexically-distant passages — the connections embeddings can't feel.*

- **S1 — Factored structural signatures + near-move/far-domain.** The single
  highest-leverage change (per the research brief). LLM emits per-passage
  `{tension it stages, move it performs, domain it speaks from}`; index the
  signature fields; retrieval matches strongly on *move* while maximising
  distance on *domain*. This is the operational dial between
  real-but-unobvious and forced. Cached LLM pass over the corpus (batch,
  content-hash cache, `--sample`/`--book` scoping like R8).
- **S2 — Symmetric structural space + dual-axis merge.** Embed the corpus's
  structure strings themselves (structure-against-structure, never
  structure-query vs surface-text — HyDE's lesson), then merge surface + structural
  candidate pools so high-STRUCT/low-DIRECT passages actually *enter* retrieval
  instead of only being scored after the fact (F1's known limit).
- **S3 — Constellation scoring + SME-style rerank.** Rank by
  `STRUCT × DIRECT-DISSIM` (or `α·STRUCT − β·DIRECT`); on the top-k, a light
  LLM structure-abduction check — "is there a real shared relational mapping,
  and is it deep?" — as forced-match filter and bridge-namer in one. Register
  the whole thing as **F2** in `formats.py`, run the comparison set vs F1.
- **S4 — Pipeline hygiene.** Differential justification (one contrastive
  call), faithfulness/attribution pass on generated prose, model router +
  token economy. Only after S1–S3 prove out.

Expected state per stage: S1 = signatures on disk + a `--structural-factored`
retrieval flag; S2 = a second embedding index + merged pool; S3 = F2 active
and beating/losing to F1 *measurably*; S4 = F2 trustworthy enough to be the
default exploratory line.

## Front 2 — The solid→liquid dial (multi-resolution chunking)

*Sequenced in PRD-chunking; config scaffolding already in place.*

- **S1 — Hierarchical data model.** `parent/chunk/proposition` levels with
  parent/child links, backward-compatible `chunks.jsonl`. No LLM needed.
- **S2 — Chunk map.** `tools/chunkmap.py` → `chunkmap.html` over existing
  chunks: immediate visual value, the chunking dashboard to build from.
- **S3 — Contextual enrichment.** The blurb-prepend pass (biggest single
  retrieval-quality lever, cheap, cacheable). Toggle `CONTEXTUAL_ENRICH`.
- **S4 — Propositions + semantic chunking + character tags.** The solid rung
  (with the mandatory pointer back to the parent passage), embedding-drop
  chunking, controlled-vocabulary characters; then format integration —
  `praxis` reads proposition, `liquid` reads parent (both already declared in
  `formats.py`).

## Front 3 — Evaluation & the null-result discipline

*Without this, F1 vs F2 vs liquid is vibes. Everything else reports to it.*

- **S1 — Comparison harness.** Run the `COMPARISON_SET` through every active
  format; persist runs with format id; side-by-side view in the panel.
- **S2 — Two-axis scoring.** Groundedness (citation-faithful, both sides
  really instantiate the bridge) × disclosure (would plain top-k have found
  it; does it cash out concretely). LLM-assisted, human-confirmed.
- **S3 — Chamatkāra as the human signal.** One-tap "this landed / forced" on
  every surfaced connection, accumulating a labelled set; wire the null result
  in everywhere (a retriever that always finds a profound connection is lying).
- **S4 — Feedback into dials.** Labels tune `SKIP_TOP`/`MMR_LAMBDA`/window
  bounds and the judge prompt; the labelled set becomes eval scaffolding for
  every future format (SCAR/StoryAnalogy-style sanity checks for structure
  strings).

## Front 4 — Knowledge graph & traversal

- **S1 — Tighten judged edges to passage→passage** (currently passage→work) —
  small, already queued in ROADMAP.
- **S2 — Relations as first-class.** Edges carry the *move* shared, not just
  the topic (AnalogyKB lesson); notes' `correlate` edges + judged edges + the
  writer's typed relations (`grounds/contrasts/tension/…`) converge into one
  attributed edge vocabulary.
- **S3 — Traversal-aware wander.** HippoRAG-style Personalized PageRank over
  the accreted graph as an alternative wander policy: associative multi-hop
  rather than fresh geometry each step; trajectory conditioning (the query
  vector as a function of the journey, not a fixed seed).
- **S4 — Contradiction-tolerant / hyperedge modelling.** Only when the edge
  store's flat records start to pinch.

## Front 5 — Rhizome Reader (the embodiment end)

*The medium the reader lives in. The three PRDs are the staged backlog; semant
supplies the interaction language.*

- **S1 — Companion notes** (PRD-ai-annotations): stable msg ids → annotate AI
  answers → "From the companion" rail, parallel-but-linked to reading notes.
  Smallest PRD, completes the annotation surface.
- **S2 — Reading Rhythm Phase 0** (PRD-behavioral-reading R1–R3 + R6a/b):
  passive capture → stats-only hotspots → end-of-session candidate sparks.
  Ship the cheap phase first and *test whether the signal matches where you
  know you were gripped* — if not, stop cheaply. Then dwell-weighted seeds
  (R6c) feed Front 1's engine directly: the body's reading biases retrieval.
- **S3 — Research Writer MVP** (PRD-research-writer): recency/concept lenses →
  outline-first, three-voice, cited essay → grounding pass. The output end of
  the loop (read → spark → relate → write → re-read).
- **S4 — Relational authoring graph + engine enrichment** (writer R2–R3), then
  rhythm Phases 1–2 (regimes, self-portrait, personal salience model) and the
  writer's revision-as-conversation. The reader becomes the atlas VISION
  describes: an accreting record of one mind's encounters.

## Front 6 — Semant transfer (learn · port · CLI-ify)

*Three distinct kinds of value in the sibling repo.*

- **S1 — Design language.** Port the Drishtikone token system
  (`design-system/tokens.css`: paper/ink neutrals, Fraunces + Inter, fluid
  scale, light/dark) as the reader's canonical tokens — the current reader CSS
  predates it. Adopt the Aletheia popup's interaction patterns where they map:
  lens-bars with confidence, **rendered uncertainty** ("the earth that
  resists"), question-loops that ask rather than assert — exactly the
  offer-as-question ethic of constellatory retrieval.
- **S2 — Concept ports (image → text).** The strongest semant ideas re-read
  for a reading instrument: *punctum prompt* → "what in this passage pierces
  you?" at spark-capture time; *encounter capture* → save passage + lens +
  note + punctum (aligns with Reading Rhythm); *multi-lens readings that may
  disagree* → 2–3 interpretive voices on a passage (formal / phenomenological
  / structural), disagreement itself a disclosure; *temporal return* →
  resurface old annotations ("does it still pierce you?"); *aesthetic
  fingerprint* → the dwell×character self-portrait already planned in the
  rhythm PRD.
- **S3 — CLI-ification of directly usable features.** Where a semant feature
  works as-is, wrap it as a callable command instead of rebuilding UI:
  `rhizome lens <chunk-id> [--lens phenomenological]` (multi-lens reading of a
  passage), `rhizome return` (temporal resurfacing), `rhizome fingerprint`
  (the longitudinal self-portrait from annotations + rhythm data). Same
  pattern as the existing `notes/graph/explore/wander` rituals; the reader UI
  can call the same endpoints later.
- **S4 — Architecture learnings.** What semant does well structurally and the
  reader should inherit as it grows: routers/services/schemas separation on
  the backend, a thin `services/*.js` API layer on the frontend, a design
  system as standalone token+component gallery pages. Adopt incrementally —
  no rewrite; `serve.py`+stdlib remains right at this scale.

## Front 7 — Corpus & research (standing)

- **S1 — Corpus hygiene**: chunk-hygiene rebuild; convert-pipeline hardening
  as new books arrive.
- **S2 — Second tradition**: Abhinavagupta / Bhartṛhari corpus — the
  cross-tradition constellation VISION names; ColBERT-style token matching
  worth testing for Sanskrit terms (*dhvani/spanda*).
- **S3 — Open research**, schedulable as standing briefs: a computational
  treatment of **dhvani-as-suggested-resonance** (the survey found this is
  open ground — a genuine contribution, not a re-implementation); metaphor
  source→target mapping as a cheap structure signature; embedding-model
  comparison in the resonance band (registry already supports it).

---

## Sequencing & dependencies (what to actually do next)

The fronts run in parallel, but the load-bearing order:

1. **F1-adjacent quick wins:** Front 2 S1–S2 (data model + chunk map — no
   LLM, immediate visual value) and Front 4 S1 (passage→passage edges).
2. **The advanced-RAG core:** Front 1 S1 (factored signatures +
   near-move/far-domain) — the proven, cheapest-highest-leverage move — with
   Front 3 S1 (comparison harness) stood up *at the same time*, so F2 is
   measured from its first run.
3. **Reader momentum:** Front 6 S1 (tokens + Aletheia patterns — cheap,
   changes the feel of the medium) and Front 5 S1 (companion notes).
4. **Then:** Front 2 S3 (contextual enrichment) feeding Front 1 S2 (dual-axis),
   Front 5 S2 (rhythm Phase 0) feeding dwell-weighted seeds, Front 5 S3
   (writer MVP) closing the read→write loop.

Cross-front couplings to keep in view: chunk *levels* (Front 2) are what the
`liquid` format and the engine read (Front 1); rhythm hotspots (Front 5) are
engine seeds (Front 1); every surfaced connection (Front 1/4) should carry the
one-tap chamatkāra control (Front 3); lens readings (Front 6) reuse the
Aletheia question-loop ethic that is already the engine's "offer as a
question" safeguard.
