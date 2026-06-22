# RhizomeDB

A connection engine for philosophical texts.

This is **not** normal retrieval-augmented generation. Normal RAG answers a
question by fetching the passages most *similar* to it — which surfaces the
obvious, usually same-author neighbours. RhizomeDB does almost the opposite: it
surfaces passages that are **distant enough to be surprising yet resonant enough
to be genuine** — unexpected connections *across* authors and works, in the
spirit of Deleuze & Guattari's *rhizome* (any point connectable to any other).
A connection is only kept if it arises **from the flow of the theory itself**;
forced links — those resting on shared vocabulary or a manufactured reading —
are rejected.

The output is not an answer. It's an **invitation to explore**: a short essay
that traces the lines of flight between passages, each one cited.

## How it works

```
books/ ─► converted/*.md ─► chunk ─► embed (local, fastembed/ONNX) ─► index/
                                                                        │
  seed (theme | random passage | chunk id) ─────────────────────────────┘
        │
        ▼  ① candidate generation — the rhizomatic geometry
        │     cross-author only · skip the obvious nearest neighbours ·
        │     keep the "resonance band" · MMR-diversify across books
        ▼  ② bridge-judging (Claude Opus 4.8)
        │     genuine resonance, or forced? forced links are dropped
        ▼  ③ synthesis — weave survivors into a cited exploration
        ▼  ④ wander (optional) — follow a connection as the next seed
```

The geometry (steps ①) is the heart: similarity gives a thematic neighbourhood,
but we **skip the top matches** (too obvious / near-duplicate), keep a band of
related-but-distant passages, exclude the seed's own author, and use **MMR** to
spread the picks across different books and conceptual angles. Then an LLM acts
as the *not-forced* filter and the writer.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Embeddings run fully locally (no API key, no network after the model downloads
once). The judging + synthesis steps use the Claude API:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or `ant auth login`
```

Without a key, `explore` still runs and prints the raw **resonance band**
(geometry only) — useful for seeing the mechanism.

## Build the index

```bash
.venv/bin/python -m rhizome.cli build      # catalog -> chunk -> embed
```

This writes `catalog.json`, `index/chunks.jsonl`, and `index/embeddings.npy`.
Re-run after adding books to `converted/` (drop new books in `books/`, run
`convert_books.py`, then `build`). Edit `catalog.json` to fix any author/title
for books the catalogue couldn't identify.

## Explore

```bash
# seed from a theme or question
.venv/bin/python -m rhizome.cli explore --theme "the flight of the gods"

# seed from a random passage — "surprise me"
.venv/bin/python -m rhizome.cli explore --random

# seed from a specific passage
.venv/bin/python -m rhizome.cli explore --chunk being-and-truth#0042

# walk the rhizome: follow the strongest connection as the next seed
.venv/bin/python -m rhizome.cli wander --random --steps 3
```

Useful flags: `--candidates N` (size of the band to judge), `--seed N`
(reproducible randomness).

## Frontend

A zero-dependency local web app explains the pipeline, shows the real source of
each stage (pulled live via `inspect.getsource`, so it never drifts), and
streams each run live — seed → resonance geometry → judging → synthesis:

```bash
.venv/bin/python serve.py        # open http://localhost:8000
```

It works in geometry-only mode without a key; set `ANTHROPIC_API_KEY` first to
light up the judging + synthesis stages. The retrieval backend is on full
display: every retrieved passage with its book/author/page/similarity, and the
genuine-vs-forced verdict per candidate.

## Tuning the connections

All the geometry knobs live in `rhizome/config.py`:

| Knob | Meaning |
|---|---|
| `SKIP_TOP` | how many of the most-similar (obvious) matches to drop |
| `POOL` | size of the resonance band MMR draws from |
| `N_CANDIDATES` | how many connections to propose per seed |
| `MMR_LAMBDA` | < 0.5 favours diversity across books over closeness to seed |
| `MIN_SIM` | floor below which candidates are noise, not resonance |
| `EXCLUDE_SAME_AUTHOR` | never connect an author to themselves |

If connections feel too obvious, raise `SKIP_TOP` or lower `MMR_LAMBDA`. If they
feel like noise, raise `MIN_SIM`.

## Layout

```
books/                 original PDFs / EPUBs / MOBIs (untouched)
converted/             Markdown (one file per book)  ← see convert_books.py
catalog.json           author / title / year per book
index/                 chunks.jsonl + embeddings.npy
rhizome/               the engine
  config.py            paths + tunable geometry
  catalog.py           corpus metadata
  chunk.py             Markdown → passages (+ page/heading provenance)
  embed.py             local ONNX embeddings
  store.py             in-memory index + rhizomatic retrieval geometry
  llm.py               Claude judging (structured) + synthesis
  engine.py            seed → candidates → judge → synthesize → wander
  cli.py               command line
```
