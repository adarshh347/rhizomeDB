import { useState } from "react";
import { ArrowLeftRight, X } from "lucide-react";

import { api, type OrphanCandidate } from "../api/client";
import type { Annotation } from "../api/types";
import { Tip } from "./Tip";

// Notes & highlights, plus the orphan queue (R11): imported quotes that could
// not be anchored, shown with their source and a way to pin them to a passage
// (candidates suggested by word overlap) or dismiss them — nothing silently
// dropped. `origin` (R12) is surfaced as a quiet mono tag on imported marks.
// De-carded: each mark is a hairline-separated row with a coloured quote spine,
// not a boxed card.
export function NotesRail({
  items,
  onJump,
  onDelete,
  onPin,
  onDismiss,
  onConnect,
}: {
  items: Annotation[];
  onJump: (a: Annotation) => void;
  onDelete: (id: string) => void;
  onPin: (id: string, chunkId: string) => void;
  onDismiss: (id: string) => void;
  onConnect: (chunkId: string) => void;
}) {
  const marks = items.filter((a) => a.quote && !a.orphaned);
  const orphans = items.filter((a) => a.orphaned && a.quote);

  return (
    <aside className="rail notes-rail">
      <div className="rail-head">
        <span className="section-label">Notes &amp; highlights</span>
        <span className="count">{marks.length}</span>
      </div>
      {marks.length === 0 && (
        <p className="rail-note">
          Select any passage to highlight it — the mark resolves to the spine and
          appears here.
        </p>
      )}
      <ul className="rail-list">
        {marks.map((a) => {
          const approx = !!a.selector?.approximate;
          return (
            <li key={a.id} className="row">
              <button
                className="note-quote"
                style={{ borderColor: `var(--hl-${a.color || "amber"})` }}
                onClick={() => onJump(a)}
                title="Jump to this mark"
              >
                <span className="q">“{a.quote}”</span>
                {a.note && <span className="n">{a.note}</span>}
              </button>
              <div className="note-meta">
                {approx && (
                  <span className="mark-approx" title="Fuzzy-matched anchor">
                    approximate
                  </span>
                )}
                {a.origin && <span className="provenance">{a.origin}</span>}
                {a.primary_chunk_id && (
                  <Tip label="Connections to this passage">
                    <button
                      className="btn-ghost icon"
                      onClick={() => onConnect(a.primary_chunk_id!)}
                      aria-label="Connections to this passage"
                    >
                      <ArrowLeftRight size={14} strokeWidth={1.75} aria-hidden />
                    </button>
                  </Tip>
                )}
                <span className="spacer" />
                <span className="when">{(a.created || "").slice(0, 16)}</span>
                <Tip label="Delete">
                  <button
                    className="btn-ghost icon danger"
                    onClick={() => onDelete(a.id)}
                    aria-label="Delete this mark"
                  >
                    <X size={14} strokeWidth={2} aria-hidden />
                  </button>
                </Tip>
              </div>
            </li>
          );
        })}
      </ul>

      {orphans.length > 0 && (
        <div className="orphan-queue">
          <div className="rail-head">
            <span className="section-label">Orphan queue</span>
            <span className="count">{orphans.length}</span>
          </div>
          <p className="rail-note">
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
    <li className="row orphan-row">
      <div className="note-quote" style={{ borderColor: "var(--accent-soft)" }}>
        <span className="q">“{ann.quote}”</span>
        {ann.note && <span className="n">{ann.note}</span>}
      </div>
      <div className="note-meta">
        {ann.origin && <span className="provenance">{ann.origin}</span>}
        <span className="spacer" />
        <button className="btn-ghost" onClick={pick}>
          {loading ? "…" : candidates ? "hide" : "pin"}
        </button>
        <button className="btn-ghost" onClick={() => onDismiss(ann.id)}>
          dismiss
        </button>
      </div>
      {/* candidates: a genuine interactive picker — keeps a boxed container */}
      {candidates && (
        <ul className="candidate-list">
          {candidates.length === 0 && <li className="cand-empty">No candidates found.</li>}
          {candidates.map((c) => (
            <li key={c.chunk_id}>
              <button className="candidate" onClick={() => onPin(ann.id, c.chunk_id)}>
                <span className="cand-id mono">
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
