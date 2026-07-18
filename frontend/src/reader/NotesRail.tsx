import type { Annotation } from "../api/types";

// The notes & highlights rail. Lists every mark on the book; orphans (quotes
// that could not be anchored) are shown with a marker rather than hidden, so
// re-anchoring or manual pinning stays possible later (PRD R11).
export function NotesRail({
  items,
  onJump,
  onDelete,
}: {
  items: Annotation[];
  onJump: (a: Annotation) => void;
  onDelete: (id: string) => void;
}) {
  const marks = items.filter((a) => a.quote);
  return (
    <aside className="notes-rail">
      <div className="rail-head">
        <h3>Notes &amp; highlights</h3>
        <span className="rail-count">{marks.length}</span>
      </div>
      {marks.length === 0 && (
        <p className="rail-empty">
          Select any passage to highlight it — the mark resolves to the spine and
          appears here.
        </p>
      )}
      <ul className="rail-list">
        {marks.map((a) => {
          const approx = !!a.selector?.approximate;
          return (
            <li key={a.id} className={`rail-item ${a.orphaned ? "orphan" : ""}`}>
              <button
                className="rail-quote"
                style={{ borderColor: `var(--hl-${a.color || "amber"})` }}
                onClick={() => onJump(a)}
                disabled={a.orphaned}
                title={a.orphaned ? "Unanchored — not on the page" : "Jump to this mark"}
              >
                <span className="q">“{a.quote}”</span>
                {a.note && <span className="n">{a.note}</span>}
              </button>
              <div className="rail-meta">
                {a.orphaned && <span className="tag orphan">orphan</span>}
                {approx && !a.orphaned && (
                  <span className="tag approx" title="Fuzzy-matched anchor">
                    approximate
                  </span>
                )}
                {a.origin && <span className="tag">{a.origin}</span>}
                <span className="when">{(a.created || "").slice(0, 16)}</span>
                <button className="rail-del" onClick={() => onDelete(a.id)} title="Delete">
                  ×
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
