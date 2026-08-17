# Reader — Code Review (correctness)

- **Commit audited:** `f616bf8` (*Merge pull request #12 from adarshh347/reader-wide-marginalia*)
- **Date:** 2026-08-10
- **Effort level:** high
- **Scope:** `frontend/src/reader/`, `frontend/src/routes/Reader.tsx`, `rhizome/reader_service.py`, `rhizome/anchor.py` — 21 files. Freshly cloned repo with no diff, so the source was reviewed as a whole rather than as a change set.
- **Method:** four independent finder agents (three correctness angles + one cleanup angle) → 44 candidates → an independent verifier per distinct `(file, line)` location, 40 verifier agents, each asked to refute rather than confirm → 41 kept, 3 refuted → top 10 reported. Static review; nothing was executed. `tsc --noEmit` and `vite build` were run separately and are both clean, so none of these are type or build errors.

**23 additional lower-severity reuse/efficiency findings were verified but fell below the reporting cap.** A few of the more substantive ones are noted at the end.

---

## The shape of it

Nearly every serious finding lands in one subsystem: **the annotation-anchoring path**. That is not an accident of sampling — it is the part of the reader that has to reconcile three renderers' notions of "where is this text" against a single converted-Markdown spine, and the defects cluster at exactly the seams where those coordinate systems meet.

Four independent bugs conspire on the same user action — *highlight a passage and have it come back to the right place*:

1. the server's ambiguity guard is **inverted** (F1), so it never protects a real highlight;
2. the EPUB renderer sends a **malformed suffix** (F2) that both weakens scoring *and* trips F1's disabled guard;
3. the PDF renderer builds a **wrong quote entirely** for cross-page selections (F3);
4. when anchoring fails, the orphan path **throws away the coordinates** it already had (F5), and pinning later **widens the mark to a whole chunk** (F4).

F1 and F2 compound: F2 guarantees a degenerate suffix, and a non-empty suffix is precisely what switches off F1's guard. An EPUB highlight of a repeated phrase is therefore *more* likely to silently anchor to the wrong occurrence than a bare-quote lookup would be.

The remaining findings are availability: a scan with no bound (F6), an exception the SSE worker structurally cannot catch (F7), and three unhandled promise rejections that turn failures into silence (F8–F10).

---

## Confirmed findings

### F1 · `anchor.resolve` tie guard is inverted — `rhizome/anchor.py:91`

The guard reads:

```python
if len(ranked) > 1 and ranked[0][0] == ranked[1][0] and not (prefix or suffix):
    return None
```

The docstring one line above (`anchor.py:81`) promises: *"Tied/weak candidates return None: an orphan is safer than a wrong note."* But ANDing with `not (prefix or suffix)` means the guard can **only** fire when the caller supplies no context at all — and every renderer always sends 32 chars (`anchoring.ts:8`, `CONTEXT = 32`). For an actual reader highlight the guard is dead code.

When a quote repeats in identical surroundings — a running header, a refrain, a repeated epigraph, a table label — both occurrences score identically, and `sorted(..., reverse=True)` over `(score, start)` tuples breaks the tie on the **largest start**: the *last* occurrence in the book, not the one the reader selected. The stored `text_position` points somewhere else entirely; the highlight paints hundreds of pages away, `chunks_for` returns the wrong chunk, and the flash confidently announces "Anchored to «wrong chunk»".

The same inversion sits at `anchor.py:100` on the normalised path, where `max(ranked)` picks the largest start on a tie.

**Fix:** the guard should fire on a tie regardless of context — context is what's *supposed* to break the tie, so a tie that survives scoring is exactly the ambiguous case the docstring wants to reject. Drop the `and not (prefix or suffix)` clause.

### F2 · EPUB `context()` puts the quote's own tail in the suffix — `frontend/src/reader/EpubRenderer.tsx:248`

The walker sets `phase = "after"` at the startContainer, so **every text node strictly between start and end containers** is appended to `suffix`. For any selection spanning more than one text node — crossing a `<b>`/`<i>`/`<a>`, or a paragraph break, i.e. the common case for a multi-sentence highlight — `suffix` accumulates the *middle of the quote*. Worse, the `if (suffix.length > CONTEXT * 2) break;` on line 250 then exits **before** the endContainer's real trailing text is ever read.

So `suffix.slice(0, CONTEXT)` is 32 characters of the quote itself. Server-side `_context_score` scores it against the genuine following text, gets ~0, and halves the confidence — and because a non-empty suffix is present, it simultaneously disables F1's guard. The two defects point the same direction.

**Fix:** only accumulate into `suffix` once the walker has passed the *end* container, and don't break out of the walk before reading the endContainer's trailing text.

### F3 · PDF cross-page selection slices page N's text with page N+1's offsets — `frontend/src/reader/PdfRenderer.tsx:228`

`pageIndex`/`pageText` are derived from `range.startContainer` only (lines 211-216), but `b` comes from `off(range.endContainer, ...)` — an offset into the *next* page's text. `pageText.slice(a, b)` yields unrelated text from page 1, or, when the swap on line 227 fires because the second page's offset is smaller, a backwards range producing garbage or an empty quote.

If the slice is non-empty, the **wrong text** is saved as the highlight's quote and sent to `anchor.resolve` — so the mark anchors to a passage the reader never selected. The quads compound it (lines 231-239): rects from page 2 are normalised against page 1's `getBoundingClientRect()`, so the repainted `.pdf-hl` divs land far outside the visible text, often below the page box entirely.

**Fix:** detect that start and end resolve to different `.pdf-page` elements and either reject the selection or build a per-page quad set with per-page text slices.

### F4 · `pin_orphan` widens a failed match to the entire chunk — `rhizome/reader_service.py:692`

```python
idx = spine.find(quote, cs, ce)
exact = idx >= 0
start, end = (idx, idx + len(quote)) if exact else (cs, ce)
```

A quote is in the orphan queue *precisely because* `anchor.resolve` already failed exact, NFKD-normalised, **and** windowed-fuzzy matching across the whole spine. A plain `str.find` restricted to one chunk will essentially always miss too — any whitespace, hyphenation, or typographic difference defeats it, and `add_annotation` has already `.strip()`ed the quote. So the `else` branch is the *normal* path, not the exceptional one.

The result is `text_position = {spine_start: cs, spine_end: ce}`: the reader pins an orphan, the row leaves the queue, and `MdRenderer` paints straight from those offsets — highlighting the **entire ~240-word chunk** amber instead of the one sentence, with `Marginalia` anchoring the note to the chunk's first glyph. Line 695 also overwrites `text_quote` with empty prefix/suffix, so a later re-resolve has *less* context than before pinning.

**Fix:** use `anchor.resolve` (the normalise/fuzzy path used everywhere else) scoped to the chunk rather than a raw `str.find`, and on genuine failure keep the annotation orphaned rather than inventing a chunk-wide span. Preserve the original prefix/suffix either way.

### F5 · Orphan path discards the format-native locator — `rhizome/reader_service.py:627`

The `locator` parameter (declared line 606) is only ever passed to `selector_bundle` on the **resolved** path (line 634). The orphan branch stores just `selector.text_quote`.

So: a reader selects a sentence in the PDF view and clicks Highlight. The frontend sends `quote` + `locator {page, quads}` (`PdfRenderer.tsx:245`). The PDF text layer's extraction differs from the converted-MD spine, `anchor.resolve` returns None — and the exact coordinates the renderer had *already computed* are dropped on the floor. `PdfRenderer`'s paint loop skips the record (`if (!loc || loc.page == null || !loc.quads) continue`, line 143) and `jumpToAnnotation` finds no `.pdf-hl[data-aid]`.

The highlight the user just drew **vanishes the moment the list refreshes**, and can never be repainted or jumped to, because the quads are gone from storage. Same for an EPUB `{cfi}`. This is the most user-visible finding here: it is the one where the reader watches their own mark disappear.

**Fix:** persist `locator` on the orphan branch too. Spine resolution and format-native coordinates are independent — failing the former is no reason to discard the latter.

### F6 · Unbounded `SequenceMatcher` scan — `rhizome/anchor.py:113`

```python
words = list(re.finditer(r"\S+", norm_spine))
qwords = max(1, len(norm_quote.split()))
for width in range(max(1, qwords - 2), qwords + 3):
    for i in range(0, max(0, len(words) - width + 1)):
        ratio = SequenceMatcher(None, norm_quote, norm_spine[a:b]).ratio()
```

Five window widths × every word position in the whole spine, with no prefilter and no size, count, or time cap. PDF and EPUB quotes come from a text layer / iframe and rarely match the spine byte-for-byte, so both fast paths miss and control reaches here routinely. For a 100k-word book that's ~500,000 `ratio()` calls, each quadratic in quote length: `POST /api/v2/annotations` blocks for minutes, the frontend `await` never returns, the toolbar stays up, and the user sees neither a highlight nor an error.

Imports multiply it: `imports.import_markdown` calls `create_anchored_annotation` per quote, each re-reading the spine and re-running `_normalise_with_map` — which itself copies `text[pos + 1:]` on line 46 for **every hyphen**, i.e. O(n²) on the spine. A 200-quote sidecar import hangs the single-worker server indefinitely.

**Fix:** cheap prefilter before `SequenceMatcher` (rare-token index, or `quick_ratio()`/`real_quick_ratio()` as a gate), plus a hard cap on candidate windows and an overall time budget after which the quote is orphaned. Separately, the hyphen loop should use the already-compiled-but-**dead** `_HYPHEN_BREAK_RE` (`anchor.py:14`) instead of slicing the remaining string per character.

### F7 · `SystemExit` kills the SSE stream with zero events — `rhizome/reader_service.py:423`

Ingest grows `chunks.jsonl` without rebuilding embeddings and clears `_READER_CHUNKS` (`ingest.py:155`) so a new book is instantly readable — by design. But then `Store.__init__` hits `len(self.chunks) != len(self.vecs)` and raises **`SystemExit`** (`store.py:42`), a `BaseException`. The explore route's `index_ready()` guard passes (both files merely *exist*), and `api.py`'s `_sse` worker catches only `Exception` — so no `event: error` is ever emitted. The `finally` closes the queue and the response ends after the `: ok` comment.

The Connections panel spins, then reports the generic "Connection lost." from `es.onerror`, with **no hint that the index needs rebuilding** — for every passage of every book, until the process is restarted with rebuilt embeddings.

**Fix:** `Store` should raise a normal `Exception` (a library has no business calling `SystemExit`), and `_sse` should catch `BaseException` and emit a real `event: error` carrying the cause.

### F8 · `api.spine()` has no `.catch` — `frontend/src/reader/MdRenderer.tsx:46`

```js
useEffect(() => { setSpine(null); api.spine(bookId).then((s) => setSpine(s.text)); }, [bookId]);
```

If a book's chunks are in `chunks.jsonl` but its converted `.md` is missing or duplicated across two subdirectories, `anchor.spine_path` raises and `GET /books/{id}/spine` 404s (`api.py:141`). The promise rejects unhandled, `spine` stays `null` forever, and the component renders "Loading the text…" **indefinitely**.

Every sibling data path handles this — `Reader.tsx`'s book fetch, `PdfRenderer`, and `EpubRenderer` all render an explicit error state. The MD renderer is the lone exception, so the same book shows a clear "Couldn't render…" on its PDF and EPUB tabs and an eternal spinner on its Text tab.

**Fix:** add a `.catch` setting an error state, matching the sibling renderers.

### F9 · `pin`/`remove`/`dismiss` rejections are unhandled — `frontend/src/reader/useAnnotations.ts:36`

`orphan_candidates` (`reader_service.py:660`) ranks candidate chunks by word overlap **without checking they carry spine offsets**, but `pin_orphan` (line 684) returns `None` for any chunk whose `spine_start` is missing — and `chunk.py:_attach_spine_offsets` `continue`s whenever a chunk's first or last paragraph isn't found in the spine, so such chunks exist and *are offered to the user*. `api.py:325` turns that into a 404, `api.pinOrphan` throws, `useAnnotations.pin` awaits with no try/catch, and `Reader.tsx` wires `onPin={pin}` straight into the candidate button.

The reader clicks a suggested passage and **nothing happens**: no flash, no error, the orphan stays in the queue. The only trace is an unhandled rejection in the console. Same silent path for `onDelete`/`onDismiss`.

**Fix:** catch in the hook and surface via the existing flash mechanism. Separately, `orphan_candidates` should not offer chunks that `pin_orphan` will refuse.

### F10 · SSE error listener `JSON.parse`s the native error Event — `frontend/src/reader/useConnections.ts:65`

```js
const on = (name, fn) => es.addEventListener(name, (e) => fn(JSON.parse((e as MessageEvent).data)));
...
on("error", (d) => { ... });
```

`addEventListener("error")` on an EventSource fires for **both** server-sent `event: error` frames and the browser's own connection-failure Event, whose `data` is `undefined`. When the stream dies without an error frame — the F7 case, a proxy timeout during a long judge/synthesize stage, a dev-server restart — the handler throws `"undefined is not valid JSON"` before it can set the error text. Only the generic `es.onerror` fallback runs, so the panel shows "Connection lost." plus a stack trace instead of the real cause, and the `finished`/close bookkeeping in the named handler is skipped.

**Fix:** guard the parse — treat a missing `data` as a transport error and route it to the same state the `onerror` fallback sets.

---

## Refuted

Three candidates were raised by finders and **killed** by verification. Recorded so they aren't re-raised:

| File:line | Claim | Why refuted |
|---|---|---|
| `MdRenderer.tsx:113` | All three renderers assign `handleRef.current` during render instead of `useImperativeHandle` — a render-phase side effect reallocating two closures per render | Not a defect in practice for this usage |
| `PdfRenderer.tsx:146` | PDF highlights positioned in absolute px from `getBoundingClientRect` per annotation, though stored quads are already normalised 0..1 | The normalisation/denormalisation is intentional and correct |
| `EpubRenderer.tsx:70` | EPUB readiness falls back to a hard-coded 1200ms `setTimeout` guess instead of a real lifecycle signal | Not load-bearing as claimed |

---

## Below the cap

23 verified reuse/efficiency findings didn't make the top 10. The ones most worth a follow-up pass:

- **`chunks_for` re-reads the whole corpus per call** — `reader_service.py:633` omits the optional `chunks=` argument, so `anchor.py:126-130` falls back to a full corpus read on every annotation create.
- **`load_spine` runs a recursive glob per `resolve()`** — `anchor.py:86` → `spine_path` does `CONVERTED_DIR.rglob(...)` over the whole converted tree, then re-reads and re-strips frontmatter, on *every* call. (This same glob is the sink for **S2** in the security audit.)
- **`_normalise_with_map` is O(n²)** — `anchor.py:46` slices `text[pos + 1:]` per hyphen inside a per-character loop; the compiled `_HYPHEN_BREAK_RE` at line 14 is dead code.
- **`MdRenderer.tsx:136` drops exact offsets** — `selectionToAnchor` computes precise `start`/`end` (`anchoring.ts:57-64`) but only `quote`/`prefix`/`suffix`/`rect` are forwarded, forcing the server to re-derive by search what the client already knew exactly. Fixing this would sidestep **F1** entirely for the MD path.

That last one is worth emphasising: the client *has* the exact answer and throws it away, then the server guesses — and F1 is a bug in the guessing. Passing the offsets through would make the ambiguity question moot for Markdown highlights.

---

## Summary

| # | Location | Defect | Class |
|---|---|---|---|
| F1 | `anchor.py:91` | Tie guard inverted — never fires with context | wrong anchor |
| F2 | `EpubRenderer.tsx:248` | Suffix contains the quote's own tail | wrong anchor |
| F3 | `PdfRenderer.tsx:228` | Cross-page selection slices wrong page's text | wrong quote |
| F4 | `reader_service.py:692` | Pin widens failed match to whole chunk | wrong span |
| F5 | `reader_service.py:627` | Orphan path discards locator | mark vanishes |
| F6 | `anchor.py:113` | Unbounded `SequenceMatcher` scan | hangs |
| F7 | `reader_service.py:423` | `SystemExit` uncatchable by SSE worker | silent failure |
| F8 | `MdRenderer.tsx:46` | Spine fetch has no `.catch` | spins forever |
| F9 | `useAnnotations.ts:36` | CRUD rejections unhandled | silent no-op |
| F10 | `useConnections.ts:65` | Error listener parses native Event | wrong error |

**Suggested order.** F5 first — it is the one where the reader watches their own highlight disappear, and the fix is to stop discarding an argument the function already receives. Then F1 (one clause, and it restores documented behaviour), then F2/F3 (renderer selection payloads), then F4. F6–F10 are availability and can follow.

Worth noting for anyone fixing these: F1, F2, F4, F5, and the `MdRenderer.tsx:136` cleanup finding are all the same underlying story — **information that exists at one layer is dropped or re-derived at the next**. Fixing them piecemeal will work; fixing them as one pass over the anchoring contract would work better.
