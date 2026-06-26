# PRD — Research Writer + Relational Authoring Graph

> Paste into Claude Code. Turn the reader's own annotations/highlights into
> grounded, cited drafts — assembled either by a quick selection lens or on a
> non-sequential relational canvas whose edges become the argument's skeleton.
> A scaffold of *your* thinking, not a finished paper. Three voices, always cited.

## 1. Context
Annotations (highlight quote + your note) live in `workspace/annotations.jsonl`,
each linked to a chunk id (→ author/title/page metadata). There's a concept graph
(`edges.jsonl`) and the constellatory engine (`store.connections`, `llm`). This
feature is the OUTPUT end of the system: read → spark → relate → **write** → (read
the draft). It must stay grounded in the marks; it never invents beyond them.

## 2. Goal
Select a set of annotations (by lens or graph), optionally arrange them as a typed
relational map, and generate a grounded, cited draft at a chosen genre × scale,
section by section, with the three registers kept visibly distinct.

## 3. Non-goals
- Not a generic summariser or a one-shot essay button; not a "finished paper."
- Never asserts beyond the annotated passages; no uncited claims pass the check.
- Don't blur the three voices (source / your claims / model glue).

## 4. Requirements

**R1 — Selection lenses.** Build a "working set" of annotations from any of:
recency (**last 2 / 5 / 10** — the quick default), current **session**,
**concept** (all annotations touching a concept), **intensity** (chamatkara-marked),
a **graph component** (R2), a saved **collection**, or a **free-text prompt** that
retrieves relevant annotations (embed prompt → match annotation/passage vectors).
Each selected item carries: quote, note, source passage + citation metadata.

**R2 — Relational authoring graph (the canvas).** A page where nodes are
annotations / highlights / concepts (plus engine-suggested bridge nodes, R3) and
edges are **typed relations** drawn by the reader or proposed by the engine:
`grounds | contrasts | tension | unfolds-into | exemplifies | echoes`. Non-
sequential. Select a **connected component** → "Write from this." Persist as a
named collection (`workspace/collections/<id>.json`: nodes + typed edges + meta).

**R3 — Engine enrichment.** For the working set, run constellatory evocation to
surface cross-corpus connections the reader did NOT mark; present as optional
bridge-nodes ("the engine found these resonances — include?"). Included bridges
join the graph and the draft as clearly machine-originated.

**R4 — Structure from the graph.** Map edge types → rhetorical roles
(`grounds`→support, `contrasts`/`tension`→antithesis/objection, `unfolds-into`→
development, `exemplifies`→evidence, `echoes`→motif). Derive an **outline**: the
central node / longest path = thesis spine; branches = sections. If the selection
has no graph (recency lens), the LLM proposes an outline the user can reorder.

**R5 — Genre × scale.** Writer formats (genre): `apercu | essay | comparative |
dialectic | commentary | syllabus`. Scale from the window: note (~300w) / essay
(~800–1200w) / article (~2000w+). Genre + scale chosen by the user; default maps
last-2→apercu/note, last-5→essay, last-10→article.

**R6 — Drafting (outline-first, section-by-section, three voices).**
1. Generate the outline (R4); user approves/reorders.
2. Draft each section grounded ONLY in its assigned annotations + passages.
3. Keep three visibly-distinct registers: **source** (quoted highlight, cited
   `(Author, Work, p.N)`), **your claim** (from the note, attributed to the
   reader), **connective tissue** (model glue, lightly marked as such).
4. Assemble + a references section from chunk metadata. Markdown output.

**R7 — Faithfulness + rigor.** A grounding pass: every assertion must trace to a
highlight, a note, or a cited passage; flag/strip anything that can't. **Gap-
finder**: name claims in the notes lacking marked support, and surface passages
that bear on them. **Counter-reading** (optional): the strongest corpus-grounded
objection to the thesis.

**R8 — Revision as conversation.** Targeted edits on the existing draft ("make the
Abhinavagupta thread the spine", "cut §3", "sharpen the tension in §2") — section
regen, not full regen.

**R9 — Output lifecycle.** The draft is saved as an annotatable document (it
re-enters the reader: annotate it → those notes feed the next revision) and filed
in the archive collection. Export markdown (+ docx later).

## 5. Endpoints / storage
- `POST /api/writer/select` (lens → working set) ·
  `POST /api/writer/outline` (working set/graph → outline) ·
  `POST /api/writer/draft` (outline + sections → grounded draft) ·
  `POST /api/writer/revise` (draft + instruction → edited draft) ·
  `GET/POST /api/collections` (the authoring graphs).
- `workspace/collections/<id>.json`, `workspace/drafts/<id>.md`.

## 6. Faithfulness/voice contract (acceptance-critical)
- Every paragraph's claims trace to a quote/note/passage; uncited assertions are
  removed by the grounding pass.
- The three registers are distinguishable in the output (markup or styling).
- Citations resolve to real chunk metadata (author/work/page).

## 7. Acceptance criteria
- Selecting "last 5" (or a concept, or a graph component) yields a working set with
  quotes + notes + citations.
- Outline reflects the graph's edge-types when a graph is used.
- The draft cites passages, attributes notes to the reader, and flags model glue.
- Gap-finder names at least the unsupported note-claims for a test selection.
- A draft can be re-opened in the reader and annotated.

## 8. Sequencing
1. **MVP**: R1 (recency + concept lenses) → R5 (essay) → R6 (outline-first, three
   voices, citations) → R7 grounding pass. A cited essay from your last-5 marks.
2. R2 relational authoring graph + R4 structure-from-graph.
3. R3 engine enrichment + R7 counter-reading.
4. R8 revision-as-conversation, R9 lifecycle/export.

## 9. Open questions
- Voice: condition on the reader's own notes so the draft sounds like them?
- How to render the three voices (inline tags vs side-margin vs colour).
- Default genre/scale per lens; max annotations before the draft must be sectioned.
