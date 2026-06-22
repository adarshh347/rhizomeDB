# RhizomeDB — Annotation Schema

A small markup for reading notes. As you read and annotate, these tags let the
engine **act on your reading** — turning your marginalia into seeds, edges,
tasks, and intensity signals instead of inert text. This is the human half of
the loop: you supply the structural judgement embeddings can't, the engine
supplies memory and fan-out.

Parsed by `rhizome/notes.py`; run `python -m rhizome.cli notes` to extract.

## Syntax

Three interchangeable forms (use whatever is fastest while reading):

- **Block** — `<tag> … </tag>`  (canonical)
- **Paren block** — `(tag) … (/tag)`  (faster to type by hand)
- **Inline suffix** — `…a sentence.(tag)`  — tags the sentence it's attached to

Tags **nest** (a `chamat` may contain a `des`, a `suggest`, an `action`). Typos
and aliases are normalised (`sutrra`→`sutra`, `chamat`→`chamatkara`,
`mythoughts`→`mythought`). Unclosed blocks auto-close at the end of their parent.

## The tags

| Tag (aliases) | Meaning | Engine role |
|---|---|---|
| `anchor` (`anch`) | a load-bearing claim — the spine of a passage | **seed** — high-value starting point for evocation |
| `sutra` (`sutrra`) | a compressed, quotable formulation | **seed** — the densest seeds; "the strangeness is the beginning" |
| `reveal` (`rev`) | a perspective-shift ("stop seeing X, start seeing Y") | **pattern** — a structural move; candidate for structural matching |
| `assert` | a claim being made | claim |
| `correlate` (`corr`) | a connection across traditions/texts (Heidegger ↔ chamatkāra) | **edge** — a human-authored bridge; the graph's most valuable input |
| `chamatkara` (`chamat`) | a moment of aesthetic flash / sudden wonder | **intensity** — disclosure-quality signal; marks where the corpus *lights up* |
| `mythought` (`mythoughts`) | your own original thinking, not the text's | **voice** — attributed to you; never confused with the source |
| `suggest` | a direction for you or for the engine | **direction** — a research/build lead |
| `action` | something to make, write, or do | **task** — goes to the action queue |
| `describe` (`des`) | exposition / paraphrase of the text | context |

## Why this matters (the design point)

The hard problem of constellatory evocation is that the connections worth having
are often **not** in the embedding neighbourhood — they're structural, and the
machine can't feel them. Your annotations inject that structure directly:

- a `correlate` is a **bridge embeddings would never surface** (Heidegger's
  "leap" ↔ Abhinavagupta's *chamatkāra*) — authored by a reader in the flow.
- a `sutra`/`anchor` is a **better seed** than a random chunk — you've already
  judged it load-bearing.
- a `chamatkara` marks **disclosure intensity** — training signal for what
  "stimulating" looks like, which no relevance metric captures.
- an `action`/`suggest` keeps the **generative-to-actionable** pipeline alive
  (articles to write, terminologies to mine, schools to restructure).

So the schema isn't note-taking decoration — it's how your reading becomes the
engine's structural layer, one annotation at a time.

## Downstream (built / planned)

- **built:** parse → `index/annotations.jsonl` + a digest (counts, edges, tasks,
  seeds, your voice).
- **next:** `correlate` → persisted edges in the concept graph · `sutra`/`anchor`
  → `explore --note <id>` seeds · `action` → a tracked queue · `chamatkara` →
  intensity weighting in the disclosure metric.
