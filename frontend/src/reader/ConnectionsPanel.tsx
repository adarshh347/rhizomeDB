import { Link } from "react-router-dom";

import { useConnections } from "./useConnections";

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
export function ConnectionsPanel({
  chunkId,
  fromLabel,
  onClose,
}: {
  chunkId: string;
  fromLabel: string;
  onClose: () => void;
}) {
  const { seed, candidates, verdicts, exploration, notes, status, error } =
    useConnections(chunkId);

  return (
    <aside className="connections-panel">
      <div className="rail-head">
        <h3>Connections</h3>
        <button className="rail-link" onClick={onClose}>
          close
        </button>
      </div>
      <p className="conn-from">
        from <span className="chunk-id">#{chunkId.split("#")[1]}</span> {fromLabel}
      </p>

      {status !== "done" && status !== "error" && (
        <div className="conn-status">
          <span className="spinner" /> {STATUS_LABEL[status]}
        </div>
      )}
      {error && <div className="upload-error">{error}</div>}

      {exploration && (
        <div className="conn-synthesis">
          <h4>A reading</h4>
          <p>{exploration}</p>
        </div>
      )}

      <ul className="conn-list">
        {candidates.map((c) => {
          const book = c.chunk_id.split("#")[0];
          const v = verdicts[c.index];
          return (
            <li key={c.chunk_id} className={`conn-item ${v && !v.genuine ? "forced" : ""}`}>
              <div className="conn-meta">
                <span className="conn-author">{c.author}</span>
                <span className="conn-title">{c.title}</span>
                {c.page != null && <span className="conn-page">p{c.page}</span>}
              </div>
              <div className="conn-text">
                {c.text.slice(0, 240)}
                {c.text.length > 240 ? "…" : ""}
              </div>
              {v?.genuine && v.bridge_concept && (
                <div className="conn-bridge">
                  <span className="tag genuine">genuine</span> {v.bridge_concept}
                </div>
              )}
              <div className="conn-foot">
                <span className="conn-sim" title="resonance (surface similarity)">
                  resonance {Math.round(c.similarity * 100)}%
                </span>
                {c.structural_similarity != null && (
                  <span
                    className="conn-struct"
                    title="structural similarity — same shape of thought, different words"
                  >
                    structural {Math.round(c.structural_similarity * 100)}%
                  </span>
                )}
                <Link className="conn-open" to={`/read/${encodeURIComponent(book)}?chunk=${encodeURIComponent(c.chunk_id)}`}>
                  open in book →
                </Link>
              </div>
            </li>
          );
        })}
      </ul>

      {status === "done" && candidates.length === 0 && (
        <p className="rail-empty">No resonant passages in the band for this one.</p>
      )}
      {notes.length > 0 && (
        <div className="conn-notes">
          {notes.map((n, i) => (
            <p key={i}>{n}</p>
          ))}
        </div>
      )}
      {seed?.embed_label && (
        <p className="conn-embed">via {seed.embed_label}</p>
      )}
    </aside>
  );
}
