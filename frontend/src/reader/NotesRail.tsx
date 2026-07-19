import { useState } from "react";

import { api, type OrphanCandidate } from "../api/client";
import type { Annotation } from "../api/types";

// Notes & highlights, plus the orphan queue (R11): imported quotes that could
// not be anchored are shown with their source and a way to pin them to a
// passage (candidates suggested by word overlap) or dismiss them — nothing is
// silently dropped. `origin` (R12) is surfaced as a tag on every imported mark.
export function NotesRail({
  items,
  onJump,
  onDelete,
  onPin,
  onDismiss,
}: {
  items: Annotation[];
  onJump: (a: Annotation) => void;
  onDelete: (id: string) => void;
  onPin: (id: string, chunkId: string) => void;
  onDismiss: (id: string) => void;
}) {
  const marks = items.filter((a) => a.quote && !a.orphaned);
  const orphans = items.filter((a) => a.orphaned && a.quote);

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
            <li key={a.id} className="rail-item">
              <button
                className="rail-quote"
                style={{ borderColor: `var(--hl-${a.color || "amber"})` }}
                onClick={() => onJump(a)}
                title="Jump to this mark"
              >
                <span className="q">“{a.quote}”</span>
                {a.note && <span className="n">{a.note}</span>}
              </button>
              <div className="rail-meta">
                {approx && (
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

      {orphans.length > 0 && (
        <div className="orphan-queue">
          <div className="rail-head">
            <h3>Orphan queue</h3>
            <span className="rail-count">{orphans.length}</span>
          </div>
          <p className="rail-empty">
            Imported quotes that couldn’t be anchored. Pin one to a passage, or
            dismiss it.
          </p>
          <ul className="rail-list">
            {orphans.map((a) => (
              <OrphanRow key={a.id} ann={a} onPin={onPin} onDismiss={onDismiss} />
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

function OrphanRow({
  ann,
  onPin,
  onDismiss,
}: {
  ann: Annotation;
  onPin: (id: string, chunkId: string) => void;
  onDismiss: (id: string) => void;
}) {
  const [candidates, setCandidates] = useState<OrphanCandidate[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function pick() {
    if (candidates) {
      setCandidates(null);
      return;
    }
    setLoading(true);
    try {
      setCandidates(await api.orphanCandidates(ann.id));
    } finally {
      setLoading(false);
    }
  }

  return (
    <li className="rail-item orphan">
      <div className="rail-quote" style={{ borderColor: "var(--accent-soft)" }}>
        <span className="q">“{ann.quote}”</span>
        {ann.note && <span className="n">{ann.note}</span>}
      </div>
      <div className="rail-meta">
        {ann.origin && <span className="tag orphan">{ann.origin}</span>}
        <button className="rail-link" onClick={pick}>
          {loading ? "…" : candidates ? "hide" : "pin"}
        </button>
        <button className="rail-link" onClick={() => onDismiss(ann.id)}>
          dismiss
        </button>
      </div>
      {candidates && (
        <ul className="candidate-list">
          {candidates.length === 0 && <li className="cand-empty">No candidates found.</li>}
          {candidates.map((c) => (
            <li key={c.chunk_id}>
              <button className="candidate" onClick={() => onPin(ann.id, c.chunk_id)}>
                <span className="cand-id">
                  {c.chunk_id.split("#")[1]}
                  {c.heading ? ` · ${c.heading}` : c.page ? ` · p${c.page}` : ""}
                  <span className="cand-score">{Math.round(c.score * 100)}%</span>
                </span>
                <span className="cand-snip">{c.snippet}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
