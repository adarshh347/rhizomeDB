# PRD — Native-format reading + the anchoring spine ("Rhizome Reader v2")

> Paste into Claude Code. Make the reader render books in their traditional
> formats (PDF / EPUB / MD; MOBI via conversion) while every selection, highlight
> and note still resolves to the data-engineering layer (chunks → annotations →
> seeds → edges → graph). Plus: import annotations made elsewhere (embedded PDF
> annots, markdown/Obsidian notes, EPUB reader sidecars). Build on OSS renderers;
> spend the effort on the anchoring/innovation layer, not on reinventing basics.

## 1. Context

Today the reader renders *chunks* (`frontend/reader/book.html` walks
`chunks.jsonl`). Great for data engineering — every visible unit IS an index
unit — but it reads badly as a book, and nobody will migrate from their real
reader to it. The corpus pipeline already extracts canonical text per book
(`scripts/convert_books.py` → `data/converted/*.md`, via pymupdf), chunks it,
and anchors notes **by quote, not page/id** (decided convention, ROADMAP B).
That convention is the W3C Web Annotation model's TextQuoteSelector — meaning
the architecture we need is standard, not exotic.

## 2. Goal

Best of both: the *rendering* is native and beautiful; the *meaning* lives in
the spine. One anchoring backend, two renderers (PDF + EPUB, built in
parallel), MD kept as the third trivial renderer, MOBI auto-converted to EPUB.
All annotation features work identically in every renderer, and external
annotations can be imported and take on the same life as native ones.

## 3. Non-goals

- No change to chunking, retrieval, or the engine. The spine feeds them as-is.
- Don't build a PDF or EPUB renderer from scratch — vendor OSS (see §5).
- Don't attempt pixel-perfect import of every third-party format on day one;
  quote-based anchoring + an orphan queue covers the long tail.

## 4. The core architecture — the spine

**Spine** = the canonical extracted text of a book (what `converted/*.md`
already is), treated as an addressable character sequence.

- **R1 — Chunk offsets.** At build time, every chunk records
  `spine_start`/`spine_end` (char offsets into its book's spine). Extend
  `rhizome/chunk.py` + the jsonl records; backward-compatible (fields are
  additive). This is the join key of the whole feature.
- **R2 — Anchor model.** Every annotation stores a W3C-style selector bundle:
  `{quote, prefix, suffix}` (TextQuoteSelector — the durable, portable
  anchor), `{spine_start, spine_end}` (TextPositionSelector — the fast one),
  and a *format-native locator* for view restoration: PDF `{page, quads}`,
  EPUB `{cfi}`, MD `{heading, para}`. Quote is authoritative; positions and
  locators are caches that can be re-derived.
- **R3 — The resolver.** One backend service (`rhizome/anchor.py`):
  - `resolve(quote, prefix, suffix, book_id) -> (spine_start, spine_end)` via
    exact match, then fuzzy match (normalised whitespace/hyphenation/ligatures,
    then edit-distance windowed search — the Hypothesis re-anchoring strategy).
  - `chunks_for(span) -> [chunk_ids]` (overlap against R1 offsets; a selection
    may straddle chunks — store all, primary = max overlap).
  - `locate(span, format) -> locator` for painting highlights back into a view.
  - Must be able to return **nothing** (unresolvable → orphan, never guess).
- **R4 — Extraction alignment.** The spine for each format must come from the
  *same file that is rendered*: PDF spine via pymupdf text extraction (already
  the pipeline); EPUB spine by extracting the EPUB's XHTML spine documents in
  order (extend `convert_books.py`); MOBI → `ebook-convert` (Calibre CLI) →
  EPUB → same path. If a book exists as both PDF and EPUB, each format gets
  its own spine↔render mapping but they share one chunk index via fuzzy
  cross-alignment (later; open question §10).

## 5. Renderers (vendor OSS, local like `frontend/vendor/` — no CDN)

- **PDF — PDF.js** (Mozilla). Canvas pages + its **text layer** gives selectable
  text with coordinates; selection → quote+context → R3. Highlights painted as
  absolutely-positioned quads over the text layer.
- **EPUB — epub.js** (futurepress). Reflowable chapters, CFI locators,
  `Rendition.annotations` API for painting highlights; themes hook for our
  tokens. (If epub.js limits bite later, Readium's ts-toolkit is the upgrade
  path — same architecture, heavier.)
- **MD — existing renderer**, upgraded to read from the spine with offsets so
  it shares the exact same annotation path.
- **Anchoring/selection UI — reuse the existing toolbar**; for fuzzy text
  anchoring take the approach (not necessarily the dependency) of
  `dom-anchor-text-quote` / Apache Annotator.
- **Conversion — Calibre `ebook-convert`** as an optional system dependency for
  MOBI (and fallback EPUB→text). Detect; degrade gracefully.

## 6. Reader features (parity + the point)

- **R5 — Feature parity across renderers.** Selection → highlight/comment,
  notes rail, Discuss drawer, companion notes (PRD-ai-annotations), schema
  tags (`SCHEMA.md` vocabulary offered in the annotation editor), rhythm
  capture hooks (PRD-behavioral-reading R1 events emit `chunk_id` via R3's
  span→chunk map — the IntersectionObserver equivalent per renderer).
- **R6 — The two-layer view toggle.** A "spine view" control: from any native
  page, reveal the underlying chunks/propositions of what's on screen (ids,
  characters, connections); from any chunk anywhere in the app, "open in
  book" jumps to the native rendering at that span. The dial between reading
  and engineering, made visible.
- **R7 — Library.** `library.html` lists books with available formats; upload/
  drop a PDF/EPUB/MOBI → conversion + spine + chunk build runs (reuse
  `cli build` per book); progress surfaced. A new book is readable natively
  immediately and joins the index when the build finishes.

## 7. Imports (external annotations take on the native life)

- **R8 — Embedded PDF annotations.** pymupdf reads `/Annots` (Highlight,
  Underline, Squiggly, popup notes): quads → extract quoted text from the page
  → R3 resolve → annotation records with `origin:'import-pdf'`. Idempotent
  (content-hash per annot); re-import updates, never duplicates.
- **R9 — Markdown / Obsidian.** Point at a folder/file: parse quotes
  (blockquotes, `==highlight==`, "quote" + comment patterns) and our own
  schema tags if present; each quote → R3 resolve against the chosen book (or
  auto-detect book by best corpus match). `origin:'import-md'`.
- **R10 — EPUB reader sidecars.** Best-effort adapters where files are
  available (KOReader `.sdr` metadata, Calibre bookmarks, generic
  quote+note CSV/JSON). All flow through the same quote resolver —
  an importer is ~a parser, nothing more. `origin:'import-epub'`.
- **R11 — Orphan queue.** Unresolved imports land in a visible queue with
  their quote + source; user pins them manually (search suggests candidate
  passages via existing retrieval) or dismisses. Nothing silently dropped.
- **R12 — Provenance.** `origin` field on every imported annotation
  (parallel to `source:'ai'` in PRD-ai-annotations); rails can filter by
  origin; imported `correlate`-like notes join the graph with attribution.

## 8. UI (the elegance requirement)

Adopt the Drishtikone tokens (semant `design-system/tokens.css` — paper/ink,
Fraunces display + Inter, light/dark) as the reader's stylesheet base (Front 6
S1). Reading surface: generous measure (~65ch reflow / fit-width PDF), margin
annotations on wide viewports, rails collapse to drawers on narrow. Selection
toolbar identical everywhere. Aletheia patterns where they fit: uncertainty
rendered honestly (fuzzy-matched anchors get a subtle "approximate" marker),
question-phrased prompts. No new framework — keep the vendored-React/static
approach; PDF.js and epub.js are vendored libs, not build-system commitments.

## 9. Acceptance criteria

- Open the same book as PDF and as EPUB; make a highlight in each; both
  resolve to the correct chunk(s); both appear in the notes rail and in
  `workspace/annotations.jsonl` with full selector bundles.
- `explore --note` works seamlessly on an annotation created in the PDF view.
- Kill and rebuild the index → all annotations re-anchor by quote (positions
  are caches, proven re-derivable).
- Import a PDF with embedded highlights → they appear as annotations with
  `origin:'import-pdf'`, painted in the native view at the right spans.
- Import a folder of markdown notes → resolved ones anchor; unresolved ones
  appear in the orphan queue; pinning one from the queue anchors it.
- A MOBI drop converts, renders as EPUB, and is annotatable.
- Rhythm capture (when built) receives correct `chunk_id`s from both renderers.

## 10. Sequencing

1. **The spine**: R1 offsets + R2 model + R3 resolver + migrate existing
   annotations (they already carry quotes) — prove re-anchoring first.
2. **EPUB + PDF renderers in parallel** against the one resolver (R5), MD
   unified onto the same path. R6 toggle once both paint highlights.
3. **R7 library/upload**, MOBI conversion.
4. **Imports**: R8 (embedded PDF — highest value, zero user formatting) →
   R9 (markdown) → R11 orphan queue → R10 sidecars.
5. **UI polish pass** with the token system (can start alongside 2).

## 11. Open questions

- Same book in two formats: cross-align spines to one shared chunk index now,
  or keep per-format indexes and align later? (Default: later.)
- PDF two-column/scanned books: pymupdf reading order can scramble the spine —
  per-book extraction QA flag? OCR path for scans (out of scope v1)?
- Highlight colors/kinds: map schema tags to colors in the native views?
- epub.js vs Readium: revisit only if epub.js pagination/CFI precision fails
  on real books.
