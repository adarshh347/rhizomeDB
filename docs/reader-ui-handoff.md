# Reader UI redesign — handoff (continue from Increment 3)

**Read this first. You are picking up a multi-increment UI pass mid-flight.** The
prior agent completed Increments 1–2 (committed) and left Increment 3 partially
edited but **unverified and uncommitted**. This file is your full context; there
is no prior conversation to rely on.

Delete this file before the final PR — the durable record is
`docs/reader-ui-audit.md`.

---

## 1. Orientation

**RhizomeDB** is a personal reading-and-research instrument. Books are converted
to a canonical "spine" (markdown), chunked, embedded, and every highlight/note
resolves to an exact spine offset → chunk → annotation → connections graph.

- **Backend**: Python FastAPI, `rhizome/` (`api.py` `/api/v2`, `reader_service.py`,
  `anchor.py` the quote resolver, `imports.py`, `store.py` connections engine).
- **Frontend**: Vite + React 18 + TS in `frontend/`. Routes: `/` Library,
  `/read/:bookId` Reader. Three renderers (PDF.js / epub.js / Markdown) behind one
  contract.
- Read `docs/reader-ui-audit.md` for the full audit + design spec (PART A audit,
  PART B design direction, PART C OSS boundary, PART D increments). **It is the
  authority on intent.** Screenshots in `docs/assets/reader-ui-audit/`.

Guiding identity: **"The book remains a book, while its computational spine
remains available beneath it."** A serious reading instrument — not a SaaS
dashboard, not a deck of cards.

---

## 2. Current state

Branch **`reader-ui-redesign`** (pushed to `origin`; **no PR yet, by instruction**).

```
5e9f52a  Increment 2 — Primitives: de-card + borrowed a11y mechanics
262c632  Increment 1 — Foundation: fonts, token scales, theme dedupe
5f89ec8  docs: Reader v2 UI audit + design direction
c619f45  (main) — everything before the UI pass
```

**Increment 1 (done, committed).** Vendored WOFF2 (Fraunces variable / Inter
400·500·600·400-italic / JetBrains Mono 400) in `frontend/public/fonts/` with SIL
OFL licenses + `README.md` attribution; `src/styles/fonts.css` `@font-face` with
`font-display: swap`; `index.html` preloads the 2 first-paint faces. Added type
scale (`--text-*`, `--leading-*`, `--weight-*`), 4px spacing scale
(`--space-1..8`), `--rule-hair`, `--ring-*`, `--radius-lg`, `--header-h`. Dark
theme deduped: every colour is one `light-dark()` value; `[data-theme]` only
flips `color-scheme`. Removed dead `api.resolve` / `ResolveResult` / `TocEntry`.

**Increment 2 (done, committed).** Borrowed mechanics: Radix **Dialog** (note
composer in `Reader.tsx` + markdown-import composer in `ImportMenu.tsx`),
**DropdownMenu** (import menu), **Tooltip** (`src/reader/Tip.tsx`, one Provider in
`App.tsx`); **lucide-react** icons. Invented meaning in
`src/styles/primitives.css`: de-carded `.row` list rows, one `.rail` shell (was
3×), `.section-label`, `.meta-row`, `.provenance`, `.meter` (resonance as a bar),
`.field`, `.btn-ghost`, one `:focus-visible` ring, Radix skins (`.rz-*`).
`reader.css` shed the notes/spine/connections card blocks, composer, and import
popover. `.spinner` moved to shared primitives.

**Bundle after Inc 2**: JS 1,065.97 kB (gz 331.88); CSS 22.63 kB (gz 5.13).

### 2a. IN-FLIGHT: Increment 3, uncommitted and UNVERIFIED

Four files are modified on disk. **They build clean but were never checked in a
browser.** Verify (or revert) before doing anything else.

| File | Change |
|---|---|
| `src/styles/tokens.css` | added `--font-reading` (Fraunces stack) — the book's own reading face, distinct from `--font-body` Inter (UI) |
| `src/routes/reader.css` | `.reading-surface` now uses `--font-reading` + `hyphens:auto`; `.spine-p` gets `text-wrap:pretty`; new `.spine-p.spine-figure` quiet mono caption; `.spine-h` gets `text-wrap:balance` |
| `src/reader/SpineView.tsx` | `BlockView` detects the converter's `⇒ picture […] intentionally omitted ⇐` marker and adds `spine-figure` to the paragraph's className — **className only; runs and `data-s` render unchanged** |
| `src/reader/EpubRenderer.tsx` | epub iframe theme `font-family` → `--font-reading` (visual only, one line in `setupTheme`) |

`git diff` to see them. If you dislike the direction, `git checkout --` those
four files and redo Increment 3 your way — but keep the intent (§5, Inc 3).

---

## 3. Binding constraints from the user (do not violate)

These were given explicitly. They override your defaults.

1. **De-card aggressively, but boxes are not banned.** A container is justified
   when it communicates real containment, transient elevation, or interaction:
   popovers, selection toolbar, modals, orphan-resolution candidates, destructive
   confirmation, mobile drawer/sheet. **For every remaining bordered/elevated
   container, record the semantic reason** (do this in a CSS comment, as
   `primitives.css` already does).
2. **Marginalia is approved but gated.** Do NOT build wide-screen margin
   annotations until fonts/scales, primitives, reading typography, rail
   architecture, and responsive shell are all complete and verified. Then treat it
   as a separate gated enhancement, Markdown-renderer first. Must handle
   collision, stacking, long notes, intermediate widths, and rail sync. **Do not
   claim PDF/EPUB parity without fixtures** (none exist locally).
3. **Fonts**: checked-in local WOFF2 only (done). Ship only used weights. Licenses
   committed beside assets. Verify computed families, `document.fonts`, offline
   loading, no network/CDN requests, payload, layout shift.
4. **PDF fidelity is sacred.** Never tint, filter, or recolor the PDF canvas to
   match the cream theme. Improve only the *surrounding* shell: canvas colour,
   edge, restrained shadow, spacing, centering, fit-width. EPUB and Markdown may
   adopt the paper theme directly; PDF content stays faithful to the document.
5. **Unified rail (Increment 4)**: shared shell + Notes/Spine/Connections modes,
   but preserve distinct state and behaviour. Notes = persistent reader material.
   Spine keeps active-chunk scroll tracking. Connections retains originating
   passage, SSE status/stages, results, error state, cancellation, return
   behaviour. **Switching modes must not cancel, duplicate, or restart the SSE
   request.** `forceMount` is permitted but **SSE survival must not depend only on
   DOM mounting** — check whether connections state can be owned *above* the tab
   view. Hidden panels must not be keyboard-reachable or exposed to screen readers
   as active content, and must not run scroll/probe work. Spine active-row
   behaviour must survive returning to the tab. **Do not force the three modes
   into identical internal layouts just to look consistent.** Monospace is for
   ids, offsets, scores, provenance, machine metadata — *not* automatically for
   full passage prose.
6. **Icons**: Lucide where it improves consistency/accessibility, but do not
   mechanically erase product-specific symbols. The **⇄ Connections mark was a
   deliberate decision**: preserved as meaning via Lucide `ArrowLeftRight`
   (bidirectional book⇄spine), now consistent and `aria-label`led. Keep it.
7. **Seeded annotations**: five exist for visual QA (ids below). Keep them during
   the branch, **clear them before final delivery**. Do NOT bolt a
   `seed_dev_annotations.py` into an unrelated commit as cleanup. Only add a
   fixture if it has durable visual-test value — and then as its own
   development-infrastructure commit with a documented `--clear` path and
   unmistakable dev provenance.
8. **No second primitive system, no styled component kit.** Radix only (never
   React Aria). No Tailwind/shadcn/emotion/styled-components. Headless behaviour
   may be borrowed; the paper/ink visual language stays ours.
9. **Process**: implement incrementally; verify TypeScript/build after every
   increment; visually inspect every changed surface at desktop and narrow widths;
   compare before/after; **commit each verified increment separately**; **do not
   open a PR until the complete UI pass is verified.**

**Architectural rule: borrow mechanics, invent meaning.** Commodity mechanics
(focus trap, keyboard nav, ARIA, collision-aware popovers, sheets, resizable
separators, markdown ASTs, virtualization) → delegate. RhizomeDB owns: passage ↔
spine ↔ chunk identity; annotation and re-anchoring; book ⇄ spine movement;
marginalia semantics; uncertainty/provenance; connections and SSE stages;
seeds/edges/graph circulation; the visual relationship between book, marks, and
machine.

---

## 4. OSS boundary (decided — do not relitigate)

| Library | Decision |
|---|---|
| Radix Dialog / DropdownMenu / Tooltip | **Adopted, installed, in use** |
| Radix **Tabs** | **Adopt in Inc 4** for the rail header, guarded per §3.5. Not yet installed. |
| Radix **Popover** | Approved but **not installed** — no genuine use surfaced; install only when a real Popover case appears |
| **@floating-ui/react** | **Adopt in Inc 5** for selection-toolbar positioning. Not yet installed. |
| **lucide-react** | Adopted, in use |
| react-resizable-panels | **Deferred** (reading is measure-capped; low value) |
| TanStack Virtual | **Deferred** — only if profiling proves a Spine-panel bottleneck, and then rewire active-row tracking to `scrollToIndex`. **Never virtualize the book DOM** (breaks `[data-s]`, selection, scroll-sync, highlight painting). |
| unified/remark | **Rejected for this pass.** Markdown import parsing lives in the Python backend; `parseSpine` carries anchoring-critical offsets. Do not combine parser migration with visual redesign. |
| React Aria, Tailwind/shadcn | **Rejected** |

Installed versions (all permissive): `@radix-ui/react-dialog@1.1.19`,
`@radix-ui/react-dropdown-menu@2.1.20`, `@radix-ui/react-tooltip@1.2.12` (MIT);
`lucide-react@1.25.0` (ISC). Before installing anything new: record exact version
+ licence, and confirm no second primitive system entered the graph.

Known pre-existing audit warning: `@xmldom/xmldom` (transitive via **epubjs**).
Out of scope — do **not** `npm audit fix --force` (it breaks epubjs).

---

## 5. Remaining increments

### Increment 3 — Reading typography + annotation presence (IN FLIGHT)
Make the reading plane read as a book. The four uncommitted edits above are a
partial start (reading serif, hyphenation, figure-marker demotion). Still to
consider: annotation presence in the text (highlight weight/《mark》 treatment),
the `approximate` dotted-underline honesty marker, note affordance, and the
`.spine-annotated` two-layer view's typography.
**Gate**: create-highlight still anchors; `[data-s]` intact; scroll-sync intact;
build clean; desktop + narrow visual check.

### Increment 4 — Rail unification (structural; user approved to proceed)
One rail shell + Notes/Spine/Connections modes via Radix **Tabs**, honouring
every requirement in §3.5. Install `@radix-ui/react-tabs` first.
**Gate**: SpinePanel active-row auto-scroll survives tab return; ConnectionsPanel
SSE not cancelled/duplicated/restarted across mode switches; hidden panels not
keyboard-reachable nor SR-exposed nor running scroll/probe work; NotesRail CRUD +
orphan pin/dismiss intact.

### Increment 5 — Responsive shell + selection toolbar
Rail → drawer/sheet (Radix Dialog) below ~900px; reading full-width; selection
toolbar → bottom action-bar on narrow; modals → sheets; remove fixed-width
overflow. Install `@floating-ui/react` and give the selection toolbar
collision-aware placement (`flip`/`shift`) — today it is naive `fixed` math in
`SelectionToolbar.tsx` (`top = rect.top − 46`) that overlaps the selection near
the viewport top and overflows at horizontal edges, across MD/PDF/EPUB.
**Gate**: no horizontal overflow at narrow; toolbar stays on-screen and over the
selection at top/right edges and inside a scrolled PDF page; behaviour parity.

### Increment 6 — States & polish
Consistent loading / empty / error / disabled / hover / focus across every
surface; **PDF page framing per §3.4 (shell only, never the canvas)**; motion
(honour `prefers-reduced-motion`); dark-mode pass; keyboard map.

### Then (separately gated): wide-screen marginalia — see §3.2.

---

## 6. Inviolable contracts

Do not change these without explicit justification to the user.

- **Anchoring** — `src/reader/renderer.ts` `AnchorInput {quote, prefix, suffix,
  locator, rect}`. Per-format: `anchoring.ts selectionToAnchor` (MD, requires
  `[data-s]` spine-offset spans emitted by `SpineView`), `PdfRenderer.readSelection`
  (`{page, quads}`), `EpubRenderer.readSelection` (`{cfi}`). `rect` positions the
  toolbar.
- **`[data-s]`** — every leaf span in `SpineView` carries its spine offset. The
  MD selection→quote map and the scroll-spy probe both depend on it. Change
  clothing, never the run structure.
- **Chunk mapping** — `MdRenderer.chunkAt`, `RendererHandle.locateChunk` per
  format, and the `?chunk=` deep-link retry effect in `Reader.tsx`.
- **SSE** — `src/reader/useConnections.ts` EventSource lifecycle; the `finished`
  guard prevents auto-reconnect after the server closes. Events: `seed,
  candidates, stage, verdicts, exploration, note, error, done`.
- **Scroll-sync** — `src/reader/useScrollSpy.ts` (capture-phase scroll +
  rAF-coalesced `elementFromPoint` probe) + `MdRenderer.probeChunk` +
  `Reader.onVisibleChunk`. **`MdRenderer`'s `annotated` tree must stay
  `useMemo`'d** — without it the spine-annotated view rebuilds O(blocks × chunks)
  every scroll frame and freezes the tab (this was a real bug, already fixed).
- **Renderer handle** — `handleRef.current = {jumpToAnnotation, locateChunk}`.
- **Annotation CRUD** — `src/reader/useAnnotations.ts` (optimistic
  create/remove/pin/dismiss/reload) → `src/api/client.ts`.
- **Highlight painting** — MD `<mark>` via `SpineView.segmentsFor`; PDF `.pdf-hl`
  divs from `{page, quads}`; EPUB `Rendition.annotations` at CFI (uses a hardcoded
  `FILL` hex map because CSS tokens don't reach the iframe).

---

## 7. Environment & verification playbook

**Run it**
```bash
# backend (repo root)
.venv/bin/python -m uvicorn rhizome.api:app --host 127.0.0.1 --port 8010 --log-level warning
# frontend
cd frontend && npm run dev -- --port 5173
```
Vite proxies `/api` → 8010. Corpus: 13 books; the real multi-chunk ones are
Markdown (`being-and-truth` 602 chunks, `heidegger-on-poetic-thinking` 246,
`nietzsche-volumes-i-ii` ~1034). PDF/EPUB books present are **single-chunk
samples** — insufficient for scroll-sync/marginalia fixtures.

**Verify**
```bash
cd frontend && npm run build     # = tsc -b && vite build. THIS is the gate.
```
`npm run typecheck` (`tsc -b --noEmit`) emits a spurious TS6310 project-references
error — ignore it; `npm run build` is authoritative. No frontend tests exist.

**Hard-won gotchas**
- **Browser automation viewport is locked** (~1745 CSS px) and window resize is
  ignored → `@media (max-width: 900px)` cannot fire naturally. To check narrow
  visually, temporarily inject a constrained container + the media-query rules,
  screenshot, then remove. Flag such checks as *simulated*.
- **`requestAnimationFrame` is paused** in the automation tab
  (`visibilityState: "hidden"`). Any rAF-driven code (the scroll-spy!) will look
  broken, and `await requestAnimationFrame(...)` in a test hangs until a 45s
  timeout that *looks* like a page freeze but isn't. To verify rAF code,
  temporarily swap rAF → `setTimeout`, test, revert.
- **Screenshots can time out** on very tall pages (the spine-annotated view is
  ~60k px). Prefer `read_page` / DOM queries / JS probes; use a smaller book
  (`heidegger-on-poetic-thinking`) for spine-view checks.
- Radix triggers need **real pointer events** — a synthetic `element.click()` will
  not open a DropdownMenu. Click via the automation tool, not JS.
- The `anchor.resolve` quote resolver returns `None` (→ orphan) for a quote
  appearing **more than once** with tied context. `being-and-truth` repeats
  headings in its TOC and body, so heading-like test quotes always orphan. Pick a
  quote with `spine.count(q) == 1` to test successful anchoring.

**Functional smoke test (proves the contracts survived)**
Select text in the reading surface → toolbar appears → click Highlight → expect a
flash like `Anchored to being-and-truth#0001`, a `<mark>` painted in the text, and
a new row in the notes rail. Then delete the test annotation (see §8).

---

## 8. Housekeeping obligations

- **Seeded annotations** (visual QA only, on `being-and-truth`):
  `an_688d419f, an_cf415e9f, an_99d0039e, an_30b25037, an_aa281688`.
  Keep during the branch; **clear before final delivery**:
  ```bash
  cd /home/adarsh-yadav/Documents/projects/rhizomedb
  PYTHONPATH=. .venv/bin/python -c "
  from rhizome import workspace
  for i in ['an_688d419f','an_cf415e9f','an_99d0039e','an_30b25037','an_aa281688']:
      workspace.delete_annotation(i)
  print('cleared')"
  ```
  If you create annotations while testing, delete them too — the workspace should
  end with none of this pass's test data.
- **Never commit**: `frontend/dist/`, `frontend/node_modules/`, `frontend/public/pdfjs/`
  (all gitignored), `rhizome_vault/` (untracked, not ours — leave alone),
  `index/` runtime data.
- **Delete `docs/reader-ui-handoff.md`** (this file) before the final PR.
- **Commits**: one per verified increment, descriptive body explaining *why*.
  Use your own attribution trailer, not the previous agent's.
- **No PR until the whole UI pass is verified**, then open it against `main`
  (repo `github.com/adarshh347/rhizomeDB`; push over HTTPS — SSH is broken here).

---

## 9. What the user values

They read carefully and push back on hand-waving. They want: honest reporting of
what was and wasn't verified; limitations named rather than glossed (e.g. "narrow
width is simulated, not a true viewport"); semantic reasons recorded for design
choices; no unused dependencies shipped; and no scope creep past the agreed gate.
When something can't be verified in this environment, say so plainly and explain
what would verify it.
