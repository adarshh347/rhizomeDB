# Formats — parallel pipeline lines

A **format** is a named, self-contained recipe for turning a query into an
answer + its evidence. We keep several alive at once (F1, F2, …), run the same
question through each, and compare. The point of formats:

- **Parallel, not sequential.** F2 doesn't replace F1; both stay runnable. New
  ideas become new formats rather than edits that erase the old behaviour.
- **Reproducible baselines.** Every saved run records *which format* produced it,
  so "did the new idea actually help?" is always answerable against the old one.
- **A comparison surface.** The real test of any format is the same query run
  through it and its predecessor, judged on the two axes we care about —
  **groundedness × disclosure** (is it anchored to real passages, and does it
  reveal something a plain answer wouldn't?).

The registry lives in `rhizome/formats.py`; this doc is the human-readable spec.

---

## The format contract (what every format must expose)

Same in, comparable out — so formats are swappable and rankable:

- **in:** a query (a question or a line of thought) + `k`.
- **out:** an answer (or evocation), the **evidence passages** with scores, and
  (optionally) follow-ups. Always *show the basis* — never a bare answer.
- **declared:** its retrieval method, its generation/layers, its knobs, and the
  *one thing it is testing* relative to the previous format.

---

## F1 — Simple RAG + surface diagnostics  *(active)*

The baseline line: plain retrieval, a long grounded answer, with **experimental
surface-similarity metrics overlaid** so we can *see* how retrieval behaves.

- **retrieval:** top-k nearest by cosine (no diversification, no exclusions) —
  `rhizome/rag.py`, served at `POST /api/ask` / page `/ask`.
- **surface layer (the experiment):** for each passage, **DIRECT** (cosine to the
  surface query), **DIRECT-DISSIM** (`1 − DIRECT`), **STRUCT** (cosine to an LLM
  abstraction of the query's *underlying move*). Surfaced in the `serve.py`
  (`:8000`) view. The prize to watch: **high STRUCT + high DIRECT-DISSIM** = same
  shape of thought, different words.
- **generation:** long answer with `[n]` citations + 5 LLM follow-ups.
- **what F1 is testing:** what pure nearest-neighbour fetches, and the
  *lexical-vs-structural gap* (STRUCT vs DIRECT) — the evidence base for F2.
- **known limits (→ motivate F2):** STRUCT is only *measured* on surface-retrieved
  passages (so structurally-kin-but-surface-far passages are never fetched);
  STRUCT is a single-abstraction proxy; no rerank, justification, or faithfulness.

## F2 — Researched RAG  *(planned — direction, not yet fixed)*

A better pipeline informed by `notes_theory/structural_retrieval_research.md`.
Candidate upgrades, to be chosen and tested against F1:

- **dual-axis retrieval** (surface *and* structural embeddings, merged) — so the
  high-STRUCT/low-DIRECT passages actually *enter* the pool, not just get scored.
- **constellation-score ranking** (`STRUCT × DIRECT-DISSIM`, or `α·STRUCT − β·DIRECT`).
- cross-encoder / LLM **rerank** before the expensive layers.
- **differential justification** (one call, each pick contrasted against the others).
- **comparison matrix + tension** layer.
- **faithfulness / attribution** check on all generated prose.
- **model router + token economy** (cheap model for sub-tasks, trim, cache).

F2's test: *does researched retrieval beat F1 on surprise AND groundedness?*

## F3+ — open

Later lines (e.g. a fully **constellatory** format, a **graph-traversal** format,
a **dialectic** format). Each gets an entry below as it's defined.

---

## Adding a format

1. Add an entry to `FORMATS` in `rhizome/formats.py` (id, name, status, essence,
   retrieval, layers, what it tests, entrypoints).
2. Give it a runner that honours the contract above.
3. Add a section here describing it and *how it differs from the prior format*.
4. Run the comparison set (shared questions like "what is dwelling") through it
   and its predecessor; record the outputs.
