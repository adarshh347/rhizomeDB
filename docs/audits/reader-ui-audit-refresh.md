# Reader — UI/Design Audit Refresh

*Re-run of the `docs/reader-ui-audit.md` pass against the current tree, to record what landed, what regressed, and what is still outstanding.*

- **Commit audited:** `f616bf8` (*Merge pull request #12 from adarshh347/reader-wide-marginalia*)
- **Date:** 2026-08-10
- **Method:** **static source review only.** The original audit (PART A) rested on live browser probes against `localhost:5173` + backend `127.0.0.1:8010` with a real 13-book corpus. This refresh did **not** run the app, so every claim below is derived from source. Findings that need a rendered page to confirm are marked **[needs live check]**.
- **Scope:** `frontend/src/styles/{tokens,fonts,global,primitives}.css`, `frontend/src/routes/{reader,library}.css`, `frontend/src/routes/Reader.tsx`, `frontend/src/reader/*`, `frontend/public/fonts/`, `frontend/package.json` + `package-lock.json`.

---

## 1. Verdict against the original audit

The redesign substantially landed. Every Increment 1–6 gate has a visible implementation in source, and the post-checkpoint marginalia enhancement is present and correctly gated. The remaining debt is concentrated in **`library.css` and `global.css`**, which were never brought onto the type/space scales the rest of the system now uses.

| Original finding (PART A) | Status |
|---|---|
| A2 — **Fonts never load** (`document.fonts.size === 0`) | **Fixed.** `styles/fonts.css` declares five `@font-face` rules against locally-served WOFF2 in `public/fonts/` (Fraunces variable roman; Inter 400/400i/500/600; JetBrains Mono 400), all `font-display: swap`, all `url("/fonts/…")` — no CDN. SIL OFL licenses committed at `public/fonts/licenses/`. **[needs live check]** that `document.fonts.size > 0` and computed families resolve. |
| A2 — **No type scale** (~21 hard-coded sizes) | **Mostly fixed.** `--text-xs…--text-2xl` ramp exists in `tokens.css:27-33`. Adoption is uneven — see finding **U1**. |
| A2 — **No spacing scale** | **Mostly fixed.** `--space-1…--space-8` at `tokens.css:44-51`, with `--space` kept as a back-compat alias. Adoption uneven — see **U1**. |
| A2 — **Dark theme maintained twice** (drift risk) | **Fixed, and better than proposed.** Every colour is declared once via `light-dark()` on `:root`; the toggle flips `color-scheme` via `[data-theme]` (`tokens.css:99-104`). The duplicated dark block is gone entirely rather than merely deduped. |
| A2 — **Magic numbers** (`3.1rem`, `calc(--rail-w + 3rem)`, `calc(--measure + 8rem)`) | **Partially fixed.** `--header-h: 3.1rem` was tokenized (`tokens.css:59`) and the ad-hoc connections-panel width is gone (one rail now). But `calc(var(--measure) + 8rem)` still appears raw ×3, and a **new** magic number `6.2rem` was introduced — see **U2**. |
| A3 — **Box overload** (~20+ bordered surfaces, nested 3 deep) | **Fixed.** 11 `border: Npx solid/dashed` declarations remain across all four stylesheets, and each surviving container carries an inline comment justifying it (format switch = "mutually exclusive interactive choices"; dropzone = "genuine interactive containment"; `.candidate` = "a genuine interactive choice, not passive list content"; PDF page; overlays). This satisfies the Increment 2 gate as written. |
| A3 — **No `:focus-visible` anywhere** | **Fixed.** One global ring at `global.css:54-58` driven by `--ring-width/--ring-offset/--ring-color`. One caveat — see **U4**. |
| A3 — Notes rail / spine / connections as boxed cards | **Fixed.** De-carded to hairline `list-row` primitives in `primitives.css`; `.book-card` is now `border-bottom: 1px solid var(--rule-hair)` on a transparent ground. |
| A3 — **PDF theme break** (stark `#fff` in cream surround) | **Fixed as specified.** `.pdf-surface` is `--paper-sunken`, `.pdf-pages` centres with gap, `.pdf-page` gets `--shadow-2` + `1px var(--rule)` edge, and the canvas keeps `background: #fff` with the comment *"the document's own page — never re-tinted"* — matching Increment 6's "no canvas recolor/tint/filter" constraint. |
| A3 — Figure-omission markers raw in the reading plane | **Fixed.** `.spine-p.spine-figure` renders as a quiet centred mono caption, `user-select: none`. |
| A3 — `resonance 77%` is text, not a meter | **Fixed.** Resonance meter primitive exists and is Tooltip-labelled (`ConnectionsPanel.tsx:89,98`). |
| A3 — Library grid *"only survives via `minmax(15rem,1fr)`, no real breakpoints"* | **Not fixed.** Still `repeat(auto-fill, minmax(15rem, 1fr))` with zero `@media` rules in `library.css`. See **U3**. |

### Increment gates (PART D)

| Increment | Gate | Status |
|---|---|---|
| 1 · Foundation | fonts loaded, no CDN; tokens applied | **Met in source** (live font check outstanding) |
| 2 · Primitives | Radix Dialog/Popover/DropdownMenu/Tooltip + Lucide; every remaining box has a recorded reason | **Met.** Note the *Popover* slot was filled by **DropdownMenu** (`ImportMenu.tsx:55`) rather than Popover — a reasonable substitution for a menu, and `@radix-ui/react-popover` is correctly absent from `package.json` rather than installed-and-unused. |
| 3 · Reading + annotations | `[data-s]`, selection, scroll-sync, highlight painting preserved | **Met in source.** `mark.hl` painting, `.approx` dotted underline + `≈` marker, and the `《》` note marker are all `::before/::after` on the mark — they add no elements and so cannot perturb `data-s` runs. |
| 4 · Rail unification | Radix Tabs **with `forceMount`**; SSE not destroyed on switch | **Met, and belt-and-braces.** All three `Tabs.Content` carry `forceMount` (`ReaderRail.tsx:53,64,73`) with explicit `[data-state="inactive"] { display: none }` (`primitives.css:291`) so inactive panels leave the a11y tree. Independently, `useConnections` is hoisted to `Reader.tsx:46` — SSE state lives *above* the rail, so it survives rail unmount regardless of Tabs behaviour. `forceMount` still earns its place for panel scroll position and SpinePanel active-row tracking. |
| 5 · Responsive | rail→drawer, toolbar→bottom-bar, modals→sheets, no overflow | **Met in source.** Radix Dialog drawer at `Reader.tsx:295-325`, Floating UI `flip`/`shift`/`offset` on the selection toolbar (`SelectionToolbar.tsx:1,26`), `.rz-dialog` → bottom sheet under `max-width: 900px`. Two caveats: **U2** and **U5**. |
| 6 · States & polish | loading/empty/error/disabled/focus sweep; PDF framing; motion; dark | **Met in source.** `.state-loading/.state-error/.state-empty` in `global.css`; two `prefers-reduced-motion` blocks (`global.css:177`, `reader.css:620`, plus `primitives.css:647`); PDF framing as above. One inconsistency — **U4**. |

**Post-checkpoint marginalia** is correctly gated: `Marginalia.tsx:5` and `reader.css:190` both use `min-width: 1500px`, `.marginalia { display: none }` is the default, and the whole gutter treatment lives inside the media query. The JS and CSS breakpoints match — the class of bug where they drift is not present here.

---

## 2. Outstanding findings

Ranked by how much they cost the design system. None is a correctness bug; that is the code review's remit.

### U1 — The type and spacing scales are only two-thirds adopted

`library.css` and `global.css` never migrated. Measured across the four stylesheets:

| File | `font-size` decls | off-scale (not `var(--text-*)`) | raw spacing literals (not `var(--space-*)`) |
|---|---|---|---|
| `styles/primitives.css` | 33 | **1** | **0** |
| `routes/reader.css` | 24 | 3 | 4 |
| `styles/global.css` | 7 | **6** | 5 |
| `routes/library.css` | 7 | **7** | 11 |

Concretely: `library.css` still carries `2.4rem`, `1.2rem`, `0.92rem`, `0.9rem`, `0.85rem`, `0.78rem`, `0.62rem` — seven sizes, none of which is a ramp step, several within 0.02rem of a neighbour, which is precisely the A2 complaint. `global.css` adds `1.05rem`, `0.85rem` (×2), `1rem`, and two `em`-relative sizes. Spacing shows the same split: `.library { padding: 2.5rem 1.5rem 4rem }`, `.dropzone { margin: 1.75rem 0 0; padding: 1.5rem 1.75rem }`, `.book-stats { margin-top: 0.9rem; gap: 0.75rem }`.

`primitives.css` — the file the redesign actually authored — is essentially perfect (0 raw spacing, 1 off-scale `0.9em`, which is legitimately relative). The debt is entirely in the two files that predate the pass and were only partially touched.

**Effect:** B5's *"one type ramp"* principle does not hold across the app. The Library is visibly a different typographic system from the Reader, which is the surface a first-time user meets first.

**Fix:** map the 13 off-scale sizes onto the nearest ramp step and the 20 raw spacing literals onto `--space-*`. This is mechanical and low-risk — the values already cluster near ramp steps (`0.92rem`→`--text-ui`, `0.85rem`→`--text-sm`, `0.78rem`/`0.62rem`→`--text-xs`, `1.2rem`→`--text-lg`, `2.4rem`→`--text-2xl` or a new `--text-3xl` if the Library title genuinely wants to be larger than a page title).

### U2 — `calc(100vh - 6.2rem)` is a new magic number, and it is wrong at narrow widths

`reader.css:98` (`.pdf-surface`) and `reader.css:152` (`.epub-surface`) both hard-code:

```css
height: calc(100vh - 6.2rem);
```

Two problems.

1. **It re-introduces exactly what A2 flagged.** `6.2rem` is `--header-h` (3.1rem) doubled — topbar + reader-bar — but written as a literal, so the relationship is invisible and the two will drift the moment either bar's padding changes. `--header-h` was tokenized specifically to stop this.

2. **It is incorrect below 900px.** The `max-width: 900px` block sets `.reader-bar { flex-wrap: wrap }` and promotes `.mobile-rail-triggers` to `order: 3; width: 100%` — a full extra row inside the reader bar. The reader bar is therefore materially taller than 3.1rem at narrow widths, but the PDF and EPUB surfaces still subtract a fixed `6.2rem`. The scroll box is taller than the space available, so the bottom of the PDF/EPUB surface is pushed below the viewport fold and the page gains a second, outer scrollbar. Increment 5's gate was *"no horizontal overflow at narrow"* — this is vertical, so it passed the gate as written while still being a layout defect. **[needs live check]** to confirm the doubled scrollbar visually.

The comment above the declaration explains *why* an explicit height exists (*"percentage-height chains resolve too late for the renderers that measure on mount"*), which is a real constraint — the fix is not to remove the explicit height but to make it correct.

**Fix:** introduce `--reader-bar-h` alongside `--header-h`, redefine it inside the `max-width: 900px` block to the wrapped height, and write `height: calc(100vh - var(--header-h) - var(--reader-bar-h))`. Alternatively measure the bar with a `ResizeObserver` and publish it as a custom property — heavier, but immune to the bar growing for any other reason.

### U3 — The Library grid still has no breakpoints

A3 flagged that the grid *"only survives via `minmax(15rem,1fr)`"*. Unchanged: `library.css:60` is still `repeat(auto-fill, minmax(15rem, 1fr))`, and `library.css` contains **zero** `@media` rules. At ~320–360px the 15rem minimum plus `.library`'s `1.5rem` side padding leaves the cards essentially edge-to-edge, and `.book-title { margin-right: 2.5rem }` (reserving room for the absolutely-positioned `.book-fmt` badge) eats a large fraction of a narrow card's width.

The Reader was made responsive; the Library was not. **[needs live check]** for the exact width at which it becomes uncomfortable.

**Fix:** drop the track minimum and tighten `.library` padding under a `max-width: 600px` breakpoint, consistent with the one already in `primitives.css:656`.

### U4 — Two small inconsistencies in the disabled/focus systems

**(a) `pointer-events: none` on disabled buttons contradicts the stated disabled state.** `global.css:128-132`:

```css
.btn:disabled,
.btn-ghost:disabled {
  opacity: 0.42;
  pointer-events: none;
}
```

B6 defines disabled as *"reduced opacity + `not-allowed`"*, and `global.css:47-50` duly sets `cursor: not-allowed` on `button:disabled`. But `pointer-events: none` means the cursor never resolves over the element — the `not-allowed` affordance is dead code for `.btn`/`.btn-ghost`. The two places that *do* show the intended cursor (`.format-switch .fmt:disabled` at `reader.css:88`, `.mobile-rail-triggers .btn-ghost:disabled` at `reader.css:571`) each re-declare `opacity` + `cursor` locally, which is the duplication the primitives pass set out to remove.

It is also a latent a11y trap: a disabled trigger inside `<Tip>` can never fire its Radix Tooltip, because the trigger receives no pointer events. No current call site does this (`Tip` is used at `ConnectionsPanel.tsx:39,89,98`, `NotesRail.tsx:78,90`, `SpinePanel.tsx:73`, `App.tsx:27` — none disabled), so this is a trap for the next change, not a live bug.

**Fix:** drop `pointer-events: none` and let `cursor: not-allowed` do its job; `disabled` already blocks activation on real `<button>`s.

**(b) The global focus ring forces `border-radius: 4px` onto round controls.** `global.css:54-58` sets `border-radius: 4px` on `:focus-visible`. An outline otherwise follows the element's own radius, so this actively *overrides* it. B5 asks for *"one focus ring"*, which the token achieves; the radius override is the part that doesn't generalise.

> **Corrected after the live run.** I originally cited `.theme-toggle` as a victim of this. It isn't — see **U7**, where its `border-radius: 50%` turns out to be overridden to 5px by `.btn-ghost` and it never renders round in the first place. The remaining genuinely-circular control is `.sel-toolbar .swatch` (`reader.css:410`, specificity `0,2,0`, carries no `.btn-ghost` class), which does get a squarish ring.

**Fix:** remove the `border-radius` from the `:focus-visible` rule. Modern outlines already follow the element radius.

### U5 — The narrow selection bar wins by `!important` ×3

`reader.css:593-599` overrides Floating UI's inline positioning:

```css
.sel-toolbar {
  position: fixed !important;
  inset: auto var(--space-3) var(--space-3) var(--space-3) !important;
  transform: none !important;
}
```

This works — inline styles need `!important` to beat — and the intent (bottom action bar on narrow, per B3) is right. But it is the only `!important` in the reader stylesheet, it is invisible to anyone reading `SelectionToolbar.tsx`, and Floating UI keeps computing a placement that is then discarded, so `placement`-derived styling would silently disagree with where the bar actually sits.

**Fix:** branch in the component — skip `useFloating`'s `floatingStyles` when the existing `isNarrow` media match is true (`Reader.tsx:35` already tracks exactly this breakpoint and could pass it down) — and let the CSS be a plain rule.

### U7 — The closing marginal bracket lands mid-quote on any multi-segment highlight — *found live*

`reader.css:350-363` hangs **both** brackets off the same class:

```css
mark.hl.has-note.mark-start::before { content: "《"; }
mark.hl.has-note.mark-start::after  { content: "》"; }
```

But `SpineView.tsx:17` only ever emits `mark-start` (`seg.mark?.startsHere ? "mark-start" : ""`) — there is **no `mark-end` class anywhere in the codebase**. A highlight is split into one `<mark>` per spine run, so any selection crossing an italic, bold, or link run becomes multiple segments and the closing `》` renders at the end of the **first** segment.

Observed live on *Being and Truth*, a 6-segment highlight:

```
《With this do we now know the 》fundamental question of philosophy? No— but we know
the direction and way by which we are to come into the asking
```

The quotation visually closes five words in, and the remaining five segments sit outside the brackets that are supposed to contain them. Confirmed by inspecting the computed pseudo-elements: segment 1 has `before: "《", after: "》"`; segments 2-6 have `none` for both.

`mark.hl.approx.mark-start::after` (the `≈` uncertainty marker, `reader.css:366`) has the identical structure and the same defect.

This is not cosmetic nitpicking — B2 makes these marks Plane-2 "the reader's marks", and a bracket that closes in the wrong place misreports *which text the note is attached to*. Multi-run selections are the common case in this corpus, where emphasis is heavy.

**Fix:** emit a `mark-end` class on the last segment (`SpineView` already knows the run boundaries — it computes `startsHere`) and move the `::after` rules onto `mark.hl.has-note.mark-end`.

### U8 — `.theme-toggle`'s circular radius is dead code — *found live*

`global.css:104` declares `.theme-toggle { border-radius: 50% }`, but the element carries `class="btn-ghost icon theme-toggle"` and `.btn-ghost { border-radius: var(--radius-sm) }` lives in `primitives.css`, which `main.tsx:8` imports *after* `global.css:7`. Both selectors are specificity `0,1,0`, so source order decides and `.btn-ghost` wins: the toggle computes to **5px**, not 50%, and renders as a rounded square.

This is a side-effect of the Increment 2 primitives extraction — the primitive was introduced without removing the older per-element rule it now silently overrides. Worth a sweep for the same pattern elsewhere: any `global.css` rule at single-class specificity that a `primitives.css` class also sets is now dead.

**Fix:** decide whether the toggle is round (raise specificity or move the rule into `primitives.css` after `.btn-ghost`) or isn't (delete the dead declaration).

### U9 — Raw Markdown syntax leaks into the notes rail — *found live*

The reading surface renders `_fundamental question of philosophy?_` as italics, but the stored quote is the raw spine slice, so the Notes rail row displays the underscores literally:

> "With this do we now know the _fundamental question of philosophy?_ No— but we know the _direction and way_ by which we are to _come into the asking_"

Plane 2 is meant to be the reader's own marks; showing converter syntax there breaks the "the book remains a book" premise the audit opens with. The quote must stay raw in storage (anchoring depends on exact spine offsets), so this is a *display* fix in `NotesRail`/`Marginalia` only — strip or render inline emphasis at render time, leaving `selector.text_quote` untouched.

### U6 — `format("woff2-variations")` is the legacy form

`fonts.css:19` declares the Fraunces variable face as `format("woff2-variations")`. Current browsers accept it, and the CSS Fonts 4 replacement is `format("woff2") tech(variations)`. Not urgent; worth a note so it doesn't become a mystery later. **[needs live check]** — if Fraunces renders at a fixed weight rather than responding to `font-weight`, this is the first thing to check.

---

## 3. Live verification

The app was subsequently built and run — API on `127.0.0.1:8010`, Vite on `5174`, against the repo's 8-book Heidegger corpus (4110 chunks, 0 missing spine offsets) with 6 seeded annotations on *Being and Truth*. Chrome 147, `innerWidth` 1378, `devicePixelRatio` 1.

**Closed — the Increment 1 gate holds.**

```
document.fonts.size === 6
  Fraunces 100 900 normal   loaded
  Inter 400 normal          loaded
  Inter 400 italic          loaded
  Inter 500 normal          unloaded   ← declared, simply unused on this route
  Inter 600 normal          loaded
  JetBrains Mono 400 normal loaded
h1 computed family: Fraunces, "Iowan Old Style", … → document.fonts.check() true
body computed family: Inter, -apple-system, …
```

The original audit's headline finding — *"Fonts never load. `document.fonts.size === 0` … the intended typographic identity does not currently render"* — is **genuinely fixed**. Fraunces is loaded *and* computed on headings; the reading plane is serif, the chrome is Inter.

**Closed — dark-theme dedupe works.** Flipping `data-theme` resolves every token through `light-dark()` off `color-scheme`, with no duplicated block:

| `data-theme` | `color-scheme` | `--paper` | `--ink` |
|---|---|---|---|
| *(absent — auto)* | `light dark` | `rgb(23,21,15)` | `rgb(236,229,212)` |
| `light` | `light` | `rgb(250,246,238)` | `rgb(38,34,28)` |
| `dark` | `dark` | `rgb(23,21,15)` | `rgb(236,229,212)` |

Values match the tokens exactly. `light-dark()` is supported in the target browser; the no-fallback risk noted below remains a deliberate-decision item, not an observed failure.

**U2 confirmed, and worse than stated.** Measured at desktop width:

| Quantity | Actual | Assumed by CSS |
|---|---|---|
| `.topbar` height | **52.19px** | `--header-h` = 3.1rem = 49.6px |
| `.topbar` + `.reader-bar` | **102.77px** | `6.2rem` = 99.2px |

The hardcoded `6.2rem` is already wrong by ~3.6px *at desktop*, before any narrow-width wrapping — so the magic number doesn't merely risk drifting, it has already drifted from the layout it describes.

**Closed — the ≥1500px marginalia enhancement works.** At `innerWidth` 1920 the gate fires and the gutter lays out cleanly:

```
matchMedia('(min-width: 1500px)').matches  true
.marginalia computed display                block
.margin-note count                          6
overlapping pairs (measured rects)          0      ← collision avoidance holds
.md-reader-plane grid-template-columns      176px 784.094px 48px
horizontal overflow                         false
```

The 176px gutter is the declared `11rem`, and margin notes render with a colour spine plus a leader rule to their mark — no card, no elevation, as B4 specifies. This is the post-checkpoint enhancement's figs 08–09 reproduced independently.

**Still open — narrow-viewport findings (U2's narrow half, U3).** `resize_window` reported success but `innerWidth` would not go *below* 1378, and later settled at 1920; I could never drive it under the 900px breakpoint. So the narrow reflow, the rail→drawer transition, and the Library grid at small widths remain unobserved — the same class of limitation the original audit recorded from the other direction (*"innerWidth fixed at 1745 … couldn't force a narrow viewport"*). Also unobservable here: `.pdf-surface`/`.epub-surface` never mount, because the corpus ships converted Markdown only — the PDF/EPUB source files are gitignored, so both formats show disabled in the format switch. **U2's narrow-overflow claim therefore remains reasoned-from-source, not observed** — only its desktop half (the drifted magic number) is measured.

**Three new findings the static pass missed** — U7 (closing bracket lands mid-quote), U8 (`.theme-toggle` circular radius is dead code), U9 (raw Markdown in the notes rail). All three are visible the moment a real highlight is painted, which is precisely why they survived a source-only review.

### Environment note — the documented setup produces a broken venv

`README.md:43` says `python3 -m venv .venv`. On stock macOS, `python3` is the Command Line Tools 3.9.6, and `rhizome/cli.py` cannot import there:

```
File "rhizome/usage.py", line 70, in Meter
    def mark(self, label: str) -> dict | None:
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

PEP 604 `X | None` is evaluated at class-definition time, and `usage.py` has no `from __future__ import annotations`. The project therefore requires **Python ≥ 3.10**, but nothing declares it — no `pyproject.toml`, no `requires-python`, no marker in `requirements.txt`, no note in the README. Rebuilding on 3.12.13 works. Worth either declaring the floor or adding the `__future__` import.

## 4. What I did verify by running

`npm ci` from the committed lockfile, then:

- **`npx tsc --noEmit` — clean**, exit 0, no output. The Increment gate *"`tsc --noEmit` + build clean after every one"* holds at `f616bf8`.
- **`npx vite build` — clean**, 1999 modules, built in 2.43s. Output: `index.js` 1,077.92 kB (334.10 kB gzip), `pdf.worker.min.js` 1,326.00 kB, `index.css` 28.54 kB (6.28 kB gzip). Rollup emits its >500 kB chunk warning; PART C recorded that code-splitting the renderers *"was tried and reverted — PDF text-layer instability"*, so this is a known accepted cost, not a regression.
- **Fonts ship and there is no CDN.** All six WOFF2 files plus the `licenses/` directory are copied into `dist/fonts/`, and grepping the built CSS for `http(s)://` returns **zero** external references. That confirms the "no CDN, self-hosted" half of the Increment 1 gate from the build artifact; only the runtime half (`document.fonts.size > 0`, computed family, CLS) still needs a live page.
