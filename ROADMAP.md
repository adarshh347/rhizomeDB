# RhizomeDB — Intentions & Roadmap

Everything you've intended, so we can talk and organise. Status: ✓ done · ◑ in
progress · ○ queued · ◆ decision needed. Type tags mark *how* a thing runs —
especially **long-running** (can run for an hour+ in the background, unattended)
vs **one-off** vs **recurring** vs **continuous** (a service you leave on).

---

## A. The engine (core build)
- ◑ **Formats** — parallel pipeline lines (F1 = simple RAG + surface diagnostics, *active*; F2 = researched RAG, *planned*). See `FORMATS.md` / `rhizome/formats.py` *(ongoing)*
- ✓ Constellatory geometry — resonance band, skip-top, MMR, near-dup guard *(one-off)*
- ✓ Intra-corpus connection (cross-book, same-author allowed) *(one-off)*
- ✓ Structural-HyDE — retrieve on the *form* of a thought, not its words *(one-off; needs a live run)*
- ✓ Judged-bridge accretion — engine remembers what it confirms *(one-off)*
- ○ **near-move / far-domain** asymmetric retrieval — the proven constellatory dial (from the research brief) *(one-off, next)*
- ○ Tighten judged edges to passage→passage (currently passage→work) *(one-off)*
- ○ Evaluation harness — groundedness × disclosure, chamatkāra as the human signal *(one-off, then recurring)*

## B. Reading & annotation (you lead)
- ✓ Annotation schema / your "commands structure" — formalised + parser *(done; will evolve)*
- ◑ You read & annotate in the flow *(continuous — your practice)*
- ✓ Reader-agent: reads & annotates a text *(demonstrated, short)*
- ○ **Long-running reader** — an agent that reads a *whole book* section by section, annotating as it goes *(**long-running**, ~hour; needs your go-ahead)*
- ✓ Referencing convention — anchor notes by quote, not page/id *(decided)*

## C. Corpus
- ✓ Heidegger loaded (8 books, ~4,100 chunks) *(done)*
- ✓ Chunk-hygiene filter *(one-off; applies on next rebuild)*
- ○ Books in cloud storage (Drive/R2) — optional, only when off-laptop *(one-off)*
- ○ Second tradition when wanted — Indian (Abhinavagupta, Bhartṛhari) *(optional)*

## D. Knowledge graph
- ✓ Edge store — authored + note + judged, attributed *(done)*
- ◑ Graph accretes from notes + explorations *(continuous, automatic)*
- ○ Contradiction-tolerant / hyperedge modelling *(later)*

## E. Research (I run, often via agents)
- ✓ Study guide / reading list + how-to-read *(done; living)*
- ✓ Structural-retrieval research brief *(done)*
- ○ Standing research on open questions, feeding the frameworks *(**recurring / schedulable**)*

## F. Writing & archive (from your `action`/`suggest` annotations)
- ○ Article: craft & the hand — putting craft into technological "blooming" *(one-off)*
- ○ Direction: chamatkāra extends Heidegger → media theory (media as space-time relaxation) *(research+writing)*
- ○ Direction: restructure media / Utpala-Abhinava Vedānta schools at the Heideggerian level *(research+writing)*
- ○ Direction: mine unexplored *desi* terminologies to expand Abhinavaguptan thinking *(research)*

## G. Documentation & the context window
- ✓ Theory notes (constellatory, study guide, vision) *(living)*
- ✓ Doc-graph map `docs_map.html` *(✓ v1; **recurring** — regenerate as docs grow)*
- ◑ **Guided panel** — directs you one-by-one, what to read, pipeline status, visual *(building now)*
- ○ Live "work & test" server — run explorations from the browser *(next; needs your env)*
- ○ Doc curation — keep the md corpus compressed & legible *(**recurring**)*

## H. Meta
- ◆ **Naming** the faculty (beyond "retrieval") — *Pratibhā* (front-runner), Spanda, Darśana; or Heuretics/Topos/Organon — *parked, to discuss*
- ✓ Operating model — workstreams, agents, feedback loop *(`OPERATING.md`)*
- ◑ Feedback loop — your corrections refine schema, prompts, dials, memory *(continuous)*

---

## The long-running / continuous things (what you meant by "runs for an hour")
These are the ones to *set going* in the background, not do in one shot:
1. **Whole-book reader-agent** — annotate an entire book end to end. *(~hour, on demand)*
2. **Standing research** — a scheduled pass on an open question, leaving a brief. *(recurring)*
3. **Context-window refresh** — regenerate the doc map / panel on a schedule. *(recurring)*
4. **Your own reading & annotation** — the continuous human practice the rest feeds on.

Tell me which of these to actually start, and I'll set them running.
