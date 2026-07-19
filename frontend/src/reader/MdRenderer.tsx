import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { Annotation } from "../api/types";
import { selectionToAnchor } from "./anchoring";
import { type HighlightSpan, parseSpine } from "./spine";
import { SpineView } from "./SpineView";
import type { RendererProps } from "./renderer";

// MD renderer: the book drawn off its spine with an exact offset map. Selection
// maps to a literal spine substring (quote/prefix/suffix sliced by offset);
// stored highlights paint by their spine position. The "spine view" reveals the
// chunk each passage belongs to — the engineering layer under the prose (R6).
export function MdRenderer({
  bookId,
  book,
  annotations,
  onSelect,
  jumpRef,
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

  jumpRef.current = (a: Annotation) => {
    const el = surfaceRef.current?.querySelector(`[data-aid="${a.id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("pulse");
      setTimeout(() => el.classList.remove("pulse"), 1200);
    }
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

  if (!spine) return <div className="center-note">Loading the text…</div>;

  return (
    <article className="reading-surface" ref={surfaceRef} onMouseUp={onMouseUp}>
      {spineView ? (
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
      ) : (
        <SpineView blocks={blocks} highlights={highlights} />
      )}
    </article>
  );
}
