import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { Annotation } from "../api/types";

const WIDE_QUERY = "(min-width: 1500px)";
const GAP = 12;

function useWideMarginalia() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_QUERY).matches);

  useEffect(() => {
    const query = window.matchMedia(WIDE_QUERY);
    const update = () => setWide(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return wide;
}

// Markdown-only progressive marginalia. Notes are positioned from the first
// painted segment for their annotation; their own measured heights determine
// collision stacking. Nothing here changes the book DOM or its data-s runs.
export function Marginalia({
  annotations,
  surface,
  plane,
  activeId,
  onActivate,
}: {
  annotations: Annotation[];
  surface: React.RefObject<HTMLElement>;
  plane: React.RefObject<HTMLElement>;
  activeId: string | null;
  onActivate: (annotation: Annotation) => void;
}) {
  const wide = useWideMarginalia();
  const layerRef = useRef<HTMLElement>(null);
  const noteRefs = useRef(new Map<string, HTMLElement>());
  const [tops, setTops] = useState<Record<string, number>>({});
  const marks = useMemo(
    () =>
      annotations.filter(
        (annotation) =>
          !annotation.orphaned &&
          !!annotation.quote &&
          !!annotation.selector?.text_position,
      ).sort(
        (a, b) =>
          (a.selector?.text_position?.spine_start ?? 0) -
          (b.selector?.text_position?.spine_start ?? 0),
      ),
    [annotations],
  );

  useLayoutEffect(() => {
    if (!wide || !surface.current || !plane.current) return;

    let disposed = false;
    const layout = () => {
      if (disposed) return;
      const planeTop = plane.current!.getBoundingClientRect().top;
      const desired = marks
        .map((annotation) => {
          const anchor = surface.current!.querySelector<HTMLElement>(
            `[data-aid="${CSS.escape(annotation.id)}"]`,
          );
          if (!anchor) return null;
          return {
            annotation,
            top: anchor.getBoundingClientRect().top - planeTop,
            height: noteRefs.current.get(annotation.id)?.offsetHeight ?? 72,
          };
        })
        .filter((item): item is NonNullable<typeof item> => !!item)
        .sort((a, b) => a.top - b.top);

      let bottom = 0;
      const next: Record<string, number> = {};
      for (const item of desired) {
        const top = Math.max(item.top, bottom + (bottom ? GAP : 0));
        next[item.annotation.id] = top;
        bottom = top + item.height;
      }
      setTops(next);
    };

    layout();
    const observer = new ResizeObserver(layout);
    observer.observe(surface.current);
    if (layerRef.current) observer.observe(layerRef.current);
    noteRefs.current.forEach((note) => observer.observe(note));
    document.fonts.ready.then(layout);
    window.addEventListener("resize", layout);
    return () => {
      disposed = true;
      observer.disconnect();
      window.removeEventListener("resize", layout);
    };
  }, [wide, marks, plane, surface]);

  if (!wide || marks.length === 0) return null;

  return (
    <aside className="marginalia" ref={layerRef} aria-label="Notes in the margin">
      {marks.map((annotation) => {
        const long = (annotation.note?.length ?? 0) > 150;
        return (
          <article
            key={annotation.id}
            ref={(node) => {
              if (node) noteRefs.current.set(annotation.id, node);
              else noteRefs.current.delete(annotation.id);
            }}
            className={`margin-note ${activeId === annotation.id ? "active" : ""}`}
            style={{
              top: tops[annotation.id] ?? 0,
              borderColor: `var(--hl-${annotation.color || "amber"})`,
            }}
            data-aid={annotation.id}
          >
            <button className="margin-quote" onClick={() => onActivate(annotation)}>
              “{annotation.quote}”
            </button>
            {annotation.note &&
              (long ? (
                <details className="margin-long-note">
                  <summary>{annotation.note.slice(0, 112)}…</summary>
                  <p>{annotation.note}</p>
                </details>
              ) : (
                <p className="margin-note-text">{annotation.note}</p>
              ))}
            <div className="margin-meta">
              {annotation.selector?.approximate && <span className="mark-approx">≈</span>}
              {annotation.origin && <span className="provenance">{annotation.origin}</span>}
            </div>
          </article>
        );
      })}
    </aside>
  );
}
