# Chunking — the solid → liquid stack

> Design/working note for RhizomeDB's chunking layer. Build the chunking work
> from here. Companion implementation spec: `PRD-chunking.md`.

## The core idea: granularity is a dial, not a choice

Chunk granularity runs on a spectrum, and the two ends are the two retrieval
moods we care about:

```
SOLID  ─────────────────────────────────────────────────▶  LIQUID
proposition   sentence   semantic-chunk   contextual-chunk   parent passage
(atomic,                                                     (large, context-
 praxis,                                                      laden, flowing,
 "what is X")                                                 constellatory)
```

- The **propositional** end is *praxis*: atomic, stable claims — precise lookup,
  definitions, "what is dwelling," the things F1 is good at. It is the solid
  ground you can stand on.
- The **liquid** end is *constellation*: large, context-rich units where meaning
  flows across qualifications — where resonance and structural movement live.
- The key insight (yours): **increase the movement / aggregation and the
  propositional hardens into the constellatory liquid.** Same corpus, different
  resolution. So we don't pick one — we **index every level and let retrieval
  choose where on the dial to read.**

This is why propositions stay important even in an unconcealment engine: they are
the praxis floor the liquid retrieval can always re-condense onto (every fluid
connection should be re-groundable to a hard proposition + its source).

## The four strategies, placed on the dial

We are working on all four — each serves a different rung, not a competition:

1. **Proposition / dense-X** — decompose passages into atomic statements; index
   those. The *solid* rung. Powerful for praxis/lookup; **use with care** —
   in philosophy meaning often lives in the qualification, so a proposition must
   keep a pointer back to its full passage (never read alone).
2. **Semantic chunking** — start a new chunk at a topic-shift (embedding-similarity
   drop). The coherent *mid* rung. Best accuracy, ~10–14× slower to build.
3. **Hierarchical / parent-child (small-to-big)** — embed the small unit for
   precise matching, feed the LLM the larger parent. This *is* the dial's
   mechanism: match solid, read liquid.
4. **Contextual retrieval (Anthropic)** — prepend an LLM-generated one-line
   context ("from Heidegger's *Building Dwelling Thinking*, on dwelling as…") to
   each chunk before embedding. An *enrichment* applied across rungs; biggest
   single retrieval-quality lever, cheap relative to its gain.

## What we commit to (the chunking direction)

A **multi-resolution index**: the corpus chunked at several levels at once
(proposition ⊂ chunk ⊂ parent), every unit linked to its parent and children, and
each embedded in its own space. Retrieval (and each *format*) declares which rung
it reads — F1/praxis leans solid (proposition/chunk), constellatory leans liquid
(contextual-chunk/parent). Contextual enrichment layered on top; semantic
chunking as the chunk-level method when build-time allows.

## The chunk map

A way to *see the world of chunks*, not just store it. Each node = a chunk (at any
level); each node carries a **character** — what kind of passage it is
(definitional / argumentative / exegetical / illustrative / poetic-evocative /
citation / transitional / aporetic …) plus a one-line description. Edges =
parent↔child and semantic-neighbour. Rendered as an interactive map (like
`docs_map.html`), filterable by book, level, and character, sized by length.

Purpose: at a glance, grasp the *status of the corpus* — where it's dense vs
thin, what character dominates a book, where the propositional ground is solid vs
where only liquid passages exist. It becomes the chunking dashboard we build from.

## Open questions
- Proposition extraction cost over ~4k chunks (LLM pass) — sample first, or do it
  per-book on demand?
- Do propositions get their own embeddings/index, or only inherit the parent's?
- Character tagging: controlled vocabulary vs free description (start controlled).
- How `formats` declare their rung — a `granularity` field in the format spec.
