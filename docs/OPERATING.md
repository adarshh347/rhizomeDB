# How we work — the operating model

A shared model for running this project in parallel, across sessions. You read,
think, and converse; I build, research, curate, and orchestrate between our
talks. Nothing here needs to be rushed — depth over speed.

## The five workstreams

1. **Reading & annotation** — *(you lead; a reader-agent assists).* You read the
   books in the flow and annotate in the schema (`SCHEMA.md`). A machine
   reader-agent can annotate other texts in parallel (mechanistic, but it widens
   coverage). Both land in `notes/` → `rhizome.cli notes` → annotations → graph.
   Reserve the `mythought` tag for *you* alone; agents never use it.

2. **Engine building** — *(I lead).* The `rhizome/` modules: geometry,
   structural-HyDE, judge, graph, notes. Every change is verified before it's
   called done. New mechanisms are prototyped *and checked*, not just written.

3. **Research** — *(I lead, often via agents).* Tightly-scoped questions that
   feed the frameworks, each returning a cited brief into `notes_theory/`
   (e.g. `structural_retrieval_research.md`). Verified references only.

4. **Documentation curation** — *(I lead).* As plans and subplans multiply, I
   keep the corpus legible: structure, compress, cross-link, prune. The study
   guide and theory notes are living, not write-once.

5. **The context window** — *(automated).* `tools/docgraph.py` regenerates
   `build/docs_map.html`, an interactive map of every document and how they connect —
   so the whole can be grasped at a glance. Regenerate whenever the doc corpus
   shifts (or schedule it).

## What I do autonomously between our conversations

Research passes · documentation curation · prototyping + checking new frameworks
· spawning task-scoped agents (readers, researchers) · regenerating the
context-window map · keeping cross-session memory current. I surface results when
we next talk; I don't sit idle waiting for instructions.

## Agents — how we use them

Agents are **task-scoped**, not persistent daemons: each is spawned for one job
(read & annotate a text; research a question), does it, and returns a short
report (not a file-dump — the artifacts land on disk). Run several in parallel.
The **reader-agent** is the closest thing to a continuous reader; it's
mechanistic, which is exactly why the feedback loop matters:

> You converse → you correct a bad call or confirm a good one → I refine the
> agent's prompt, the schema, or the geometry heuristics → the next run is
> better. The human-in-the-loop is the learning signal.

## The feedback loop (how this gets smarter)

Your corrections aren't one-offs — they become refinements: to the schema, to
the judge/abstraction prompts, to the `near-X / far-Y` retrieval dials, and to
cross-session **memory** so a new session resumes with the current state.

## Commands (the rituals)

```
rhizome notes                 # parse annotated notes -> annotations + digest
rhizome graph                 # rebuild the concept graph (authored + note + judged)
rhizome explore --note <id>   # evoke from a note's sutra/anchor
rhizome explore --structural  # retrieve on the seed's underlying form (structural-HyDE)
rhizome wander --random --steps 3
python3 tools/docgraph.py      # regenerate the context-window map (build/docs_map.html)
python3 tools/panel.py         # static guided panel snapshot (build/panel.html)
python3 -m rhizome.server      # LIVE panel -> http://127.0.0.1:8765 (auto-updating; leave it on)
```

The **live panel** (`rhizome/server.py`) is the always-on surface: a stdlib
server (nothing to install) + a React page that polls every 8s, so status, the
one-card-at-a-time deck, the concept graph, and reading coverage stay current as
you work — and an "Evoke / Surprise me" box runs explorations in the browser.
Random/chunk seeds need no extra deps; free-text & `structural` need `fastembed`
(+ an LLM key for judging). This is what "keeps running in the background" — the
server does, not me; for periodic *me*-work, use scheduled tasks.

## Open / parked

- **Naming** the whole faculty (beyond "retrieval") — *parked, to discuss.*
  Front-runner from your tradition: *Pratibhā*; alternates *Spanda / Darśana*;
  Western: *Heuretics / Topos / Organon*.
- Tighten judged edges to passage-to-passage (currently passage→work).
- `near-move / far-domain` asymmetric retrieval (see the research brief) — the
  proven, operational form of the constellatory dial.
