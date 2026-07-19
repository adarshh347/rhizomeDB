import { Link } from "react-router-dom";
import { ArrowRight, X } from "lucide-react";

import type { ConnectionsState } from "./useConnections";
import { Tip } from "./Tip";

const STATUS_LABEL: Record<string, string> = {
  geometry: "finding the resonance band…",
  judging: "judging genuine vs forced…",
  synthesizing: "weaving a reading…",
  done: "",
  error: "",
};

// The reader talking to the connection engine (the point of RhizomeDB): from the
// passage you're reading, the rhizomatic band of related-but-distant passages
// *across other books*, streamed live. Geometry alone is useful without a key;
// with an LLM the genuine-vs-forced verdict and a synthesized reading follow.
// Every connection links back into the book via the R6 ?chunk= deep link.
// De-carded to quiet rows; similarity reads as a small meter, not just a number.
export function ConnectionsPanel({
  chunkId,
  fromLabel,
  onClose,
  state,
}: {
  chunkId: string;
  fromLabel: string;
  onClose: () => void;
  state: ConnectionsState;
}) {
  const { seed, candidates, verdicts, exploration, notes, status, error } = state;

  return (
    <section className="rail-panel connections-rail" aria-label="Connections">
      <div className="rail-head">
        <span className="section-label">Connections</span>
        <span className="spacer" />
        <Tip label="Close">
          <button className="btn-ghost icon" onClick={onClose} aria-label="Close connections">
            <X size={15} strokeWidth={2} aria-hidden />
          </button>
        </Tip>
      </div>
      <p className="conn-from">
        from <span className="mono chunk-id">#{chunkId.split("#")[1]}</span> {fromLabel}
      </p>

      {status !== "done" && status !== "error" && (
        <div className="conn-status">
          <span className="spinner" /> {STATUS_LABEL[status]}
        </div>
      )}
      {error && <div className="inline-error">{error}</div>}

      {exploration && (
        <div className="conn-synthesis">
          <span className="section-label">A reading</span>
          <p>{exploration}</p>
        </div>
      )}

      <ul className="rail-list">
        {candidates.map((c) => {
          const book = c.chunk_id.split("#")[0];
          const v = verdicts[c.index];
          const sim = Math.round(c.similarity * 100);
          const struct =
            c.structural_similarity != null
              ? Math.round(c.structural_similarity * 100)
              : null;
          return (
            <li key={c.chunk_id} className={`row ${v && !v.genuine ? "forced" : ""}`}>
              <div className="conn-title-line">
                <span className="conn-author">{c.author}</span>
                <span className="conn-book">{c.title}</span>
                {c.page != null && <span className="mono conn-page">p{c.page}</span>}
              </div>
              <div className="conn-text">
                {c.text.slice(0, 240)}
                {c.text.length > 240 ? "…" : ""}
              </div>
              {v?.genuine && v.bridge_concept && (
                <div className="conn-bridge">
                  <span className="badge-genuine">genuine</span> {v.bridge_concept}
                </div>
              )}
              <div className="conn-foot">
                <Tip label="resonance — surface similarity">
                  <span className="meter">
                    <span className="meter-track">
                      <span className="meter-fill" style={{ width: `${sim}%` }} />
                    </span>
                    {sim}%
                  </span>
                </Tip>
                {struct != null && (
                  <Tip label="structural — same shape of thought, different words">
                    <span className="meter structural">
                      <span className="meter-track">
                        <span className="meter-fill" style={{ width: `${struct}%` }} />
                      </span>
                      {struct}%
                    </span>
                  </Tip>
                )}
                <Link
                  className="conn-open"
                  to={`/read/${encodeURIComponent(book)}?chunk=${encodeURIComponent(c.chunk_id)}`}
                >
                  open in book <ArrowRight size={13} strokeWidth={2} aria-hidden />
                </Link>
              </div>
            </li>
          );
        })}
      </ul>

      {status === "done" && candidates.length === 0 && (
        <p className="rail-note">No resonant passages in the band for this one.</p>
      )}
      {notes.length > 0 && (
        <div className="conn-notes">
          {notes.map((n, i) => (
            <p key={i}>{n}</p>
          ))}
        </div>
      )}
      {seed?.embed_label && <p className="conn-embed">via {seed.embed_label}</p>}
    </section>
  );
}
