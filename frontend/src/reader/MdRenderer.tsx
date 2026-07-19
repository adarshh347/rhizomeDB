import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { Annotation } from "../api/types";
import { selectionToAnchor } from "./anchoring";
import { type HighlightSpan, parseSpine } from "./spine";
import { SpineView } from "./SpineView";
import type { RendererProps } from "./renderer";
import { useScrollSpy } from "./useScrollSpy";

// Where the scroll-spy takes its reading: a line just below the reader bar,
// down the centre of the text column. The extra probes ride past inter-block
// margins (which return no offset-bearing span) to the next line of prose.
const BAR = 56;
const PROBE_LINES = [40, 84, 128];
const NOOP = () => {};

// MD renderer: the book drawn off its spine with an exact offset map. Selection
// maps to a literal spine substring (quote/prefix/suffix sliced by offset);
// stored highlights paint by their spine position. The "spine view" reveals the
// chunk each passage belongs to — the engineering layer under the prose (R6).
export function MdRenderer({
  bookId,
  book,
  annotations,
  onSelect,
  handleRef,
  onVisibleChunk,
  spineView = false,
}: RendererProps & { spineView?: boolean }) {
  const [spine, setSpine] = useState<string | null>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSpine(null);
    api.spine(bookId).then((s) => setSpine(s.text));
  }, [bookId]);

  const blocks = useMemo(() => (spine ? parseSpine(spine) : []), [spine]);

  const highlights: HighlightSpan[] = useMemo(() => {
    const spans: HighlightSpan[] = [];
    for (const a of annotations) {
      const pos = a.selector?.text_position;
      if (a.orphaned || !pos) continue;
      spans.push({
        id: a.id,
        spine_start: pos.spine_start,
        spine_end: pos.spine_end,
        color: a.color || "amber",
        approximate: !!a.selector?.approximate,
      });
    }
    return spans;
  }, [annotations]);

  const chunkAt = useCallback(
    (offset: number): string | null => {
      let best: { id: string; d: number } | null = null;
      for (const p of book.paragraphs) {
        if (p.spine_start == null || p.spine_end == null) continue;
        if (offset >= p.spine_start && offset < p.spine_end) {
          const d = Math.min(offset - p.spine_start, p.spine_end - offset);
          if (!best || d > best.d) best = { id: p.id, d };
        }
      }
      return best?.id ?? null;
    },
    [book],
  );

  // Which chunk is at the top of the reading area right now: probe a trigger
  // line (with a few fallbacks past margins), read the nearest span's spine
  // offset, and resolve it to a chunk. O(1) — no walking the whole book.
  const probeChunk = useCallback((): string | null => {
    const surface = surfaceRef.current;
    if (!surface) return null;
    const box = surface.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const base = Math.max(box.top, BAR);
    for (const gap of PROBE_LINES) {
      const el = document.elementFromPoint(x, base + gap) as HTMLElement | null;
      if (!el || !surface.contains(el)) continue;
      const span =
        (el.closest("[data-s]") as HTMLElement | null) ??
        (el.querySelector?.("[data-s]") as HTMLElement | null);
      if (span?.dataset.s != null) return chunkAt(Number(span.dataset.s));
    }
    return null;
  }, [chunkAt]);

  // Track only while the spine panel is showing — that's the only place the
  // active chunk is visible, so there's no reason to probe during plain reading.
  useScrollSpy(spineView && !!onVisibleChunk, probeChunk, onVisibleChunk ?? NOOP);

  const pulse = (el: Element, behavior: ScrollBehavior = "smooth") => {
    el.scrollIntoView({ behavior, block: "center" });
    el.classList.add("pulse");
    setTimeout(() => el.classList.remove("pulse"), 1200);
  };

  handleRef.current = {
    jumpToAnnotation: (a: Annotation) => {
      const el = surfaceRef.current?.querySelector(`[data-aid="${a.id}"]`);
      if (el) pulse(el);
    },
    // Locate a chunk by its spine offset: the span whose offset starts it.
    locateChunk: (chunk) => {
      if (chunk.spine_start == null || !surfaceRef.current) return;
      let best: HTMLElement | null = null;
      surfaceRef.current.querySelectorAll<HTMLElement>("[data-s]").forEach((s) => {
        const v = Number(s.dataset.s);
        if (v <= chunk.spine_start! && (!best || v > Number(best.dataset.s))) best = s;
      });
      if (best) pulse(best, "auto");
    },
  };

  const onMouseUp = useCallback(() => {
    if (!spine || !surfaceRef.current) return;
    setTimeout(() => {
      const found = surfaceRef.current
        ? selectionToAnchor(spine, surfaceRef.current)
        : null;
      onSelect(found ? { quote: found.quote, prefix: found.prefix, suffix: found.suffix, rect: found.rect } : null);
    }, 0);
  }, [spine, onSelect]);

  // The spine-annotated tree is expensive to build (a chunkAt() scan per block)
  // and depends only on the text + highlights — never on the reading position.
  // Memoize it so the scroll-spy's per-frame setActiveChunk (which re-renders
  // this component) doesn't rebuild the whole book each frame and freeze the tab.
  const annotated = useMemo(
    () => (
      <div className="spine-annotated">
        {blocks.map((b, i) => {
          const id = b.kind !== "page" ? chunkAt(b.start) : null;
          return (
            <div className="spine-row" key={i}>
              {id && <span className="chunk-badge">{id.split("#")[1]}</span>}
              <div className="spine-cell">
                <SpineView blocks={[b]} highlights={highlights} />
              </div>
            </div>
          );
        })}
      </div>
    ),
    [blocks, highlights, chunkAt],
  );

  if (!spine) return <div className="center-note">Loading the text…</div>;

  return (
    <article className="reading-surface" ref={surfaceRef} onMouseUp={onMouseUp}>
      {spineView ? annotated : <SpineView blocks={blocks} highlights={highlights} />}
    </article>
  );
}
