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

This writes `data/catalog.json`, `index/chunks.jsonl`, and `index/embeddings.npy`.
Re-run after adding books to `data/converted/` (drop new books in `books/`, run
`scripts/convert_books.py`, then `build`). Edit `data/catalog.json` to fix any
author/title for books the catalogue couldn't identify.

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

## Frontend & backend

One backend: a versioned **FastAPI** app (`rhizome/api.py`) that serves both the
reader-v2 anchoring spine and the whole exploration/panel surface — the live SSE
run (seed → resonance geometry → judging → synthesis), embedding compare, the
workflow source-view (pulled live via `inspect.getsource`, so it never drifts),
sessions, chat, and reading-rhythm behaviour. Everything above the transport
lives in `rhizome/reader_service.py` + `rhizome/anchor.py`; the routes are thin.

The UI is a **Vite + React + TypeScript** SPA in `frontend/`, talking to the API
under `/api/v2`. First augment an existing index with spine offsets and migrate
legacy quote annotations, then run the two dev servers:

```bash
.venv/bin/python -m rhizome.cli spine          # one-time: add chunk offsets
.venv/bin/python -m rhizome.cli serve --reload # API on http://127.0.0.1:8010
                                               # (docs at /docs)

cd frontend && npm install && npm run dev      # UI on http://127.0.0.1:5174
```

`npm run build` emits `frontend/dist/`, which the API then serves directly at
`/` (no second server in production). The retrieval backend stays on full
display, and quote resolution returns an *orphan* instead of guessing when a
match is weak or ambiguous — a wrong note is worse than a missing one.

It works in geometry-only mode without a key; set `ANTHROPIC_API_KEY` (or a
Gemini/Groq key) to light up judging, synthesis, chat, and the Plateau study map.

### Native renderers

A book renders in its original format when its source file is present under
`books/` (PDF via **PDF.js**, EPUB via **epub.js** — both vendored through npm,
no CDN), and always as **Markdown off the spine** otherwise. The format switch
lives in the reader bar; every renderer shares one selection toolbar, notes
rail, and resolver, so a highlight in any format anchors to the spine, records a
format-native locator (PDF `{page, quads}` · EPUB `{cfi}` · MD spine offsets),
and lands in the same `annotations.jsonl`.

The **Spine** toggle reveals the two-layer view (R6): the reading surface's right
rail becomes a navigable index of the book's chunks — the units the connection
engine actually reads — each with its id, character span, and preview. Click one
to jump to it in the native view; conversely `/read/<book>?chunk=<id>` opens the
book scrolled to that passage, so any chunk id anywhere is a shareable location.
A light/dark/auto theme toggle sits in the top bar. `npm install` copies PDF.js's
standard-font + cmap data into `frontend/public/pdfjs/` (postinstall) so base-14
and non-Latin PDFs render locally.

The corpus source files live in R2 (`books/` is gitignored). To exercise the
PDF/EPUB renderers on a fresh checkout without them, generate a couple of
faithful samples through the real pipeline:

```bash
PYTHONPATH=. .venv/bin/python scripts/make_sample_books.py
```

### Uploading a book

Drop a PDF / EPUB / MOBI onto the library (or `POST /api/v2/books/upload`). It
runs through the same convert → chunk → index pipeline (`rhizome/ingest.py`),
lands under `books/uploads/` + `data/converted/uploads/` (both gitignored,
runtime-only), and opens **natively and immediately** — a highlight anchors to
the spine right away. It joins the *vector* index (for `explore`) only when
embeddings are rebuilt; reading needs only the chunk index. MOBI is extracted to
EPUB (Calibre's `ebook-convert` if present, else the pure-Python `mobi` lib).

### Importing annotations

Annotations made elsewhere take on the same life as native ones — each importer
is a parser feeding the one quote resolver (`rhizome/imports.py`):

- **Embedded PDF highlights** — `Import ▾ → Embedded PDF highlights` reads the
  book's `/Annots` (Highlight/Underline/StrikeOut/Squiggly + popup notes), lifts
  the covered text and note, resolves against the spine, and repaints the mark
  at its original quads. Idempotent (re-import updates, never duplicates).
- **Markdown / Obsidian** — paste notes; `==highlights==` and `>` blockquotes
  (with an optional note line) each become a quote.

Every imported mark carries an `origin` tag (`import-pdf` / `import-md`, R12). A
quote that can't be anchored lands in the **orphan queue** rather than being
dropped (R11): pin it to a passage — candidates are suggested by word overlap —
or dismiss it.

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
README.md              this file
requirements.txt       Python dependencies
books/                 original PDFs / EPUBs / MOBIs (untouched, gitignored)
data/                  corpus + metadata + human inputs
  catalog.json         author / title / year per book
  converted/           Markdown, one file per book  ← see scripts/convert_books.py
  notes/               annotated reading notes (the human half of the loop)
  eval/                in-domain embedding gold set
index/                 generated: chunks.jsonl + embeddings.npy (gitignored)
build/                 generated: self-contained HTML maps (gitignored)
scripts/               convert_books.py · upload_to_r2.py (one-off pipeline)
docs/                  CHUNKING · FORMATS · OPERATING · ROADMAP · SCHEMA · VISION · PRD-chunking
frontend/              Vite + React + TS SPA (the reader + panel UI)
tools/                 chunkmap · conceptmap · docgraph · panel generators
rhizome/               the engine + the backend
  config.py            paths + tunable geometry
  catalog.py           corpus metadata
  chunk.py / chunking.py   Markdown → passages (+ multi-resolution levels) + spine offsets
  embed.py             local ONNX embeddings (multi-model)
  concepts.py          core-concept extraction (content lens)
  store.py             in-memory index + rhizomatic retrieval geometry
  llm.py               Claude judging (structured) + synthesis
  engine.py            seed → candidates → judge → synthesize → wander
  anchor.py            durable quote → spine resolver (W3C selectors, orphan-safe)
  workspace.py         annotations / chats / sessions persistence
  reader_service.py    domain logic behind the HTTP boundary
  api.py               FastAPI app (the one backend)
  cli.py               command line
```
