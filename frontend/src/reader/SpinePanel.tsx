import type { BookPayload, Paragraph } from "../api/types";

// The engineering layer made visible (R6): the book's chunks — the units the
// index and the connection engine actually read — each with its id, character
// span on the spine, and a preview. Clicking one drives the native renderer to
// that passage. The other direction (chunk → book) is the ?chunk= deep link the
// reader honours on open, so any chunk id anywhere becomes a location.
export function SpinePanel({
  book,
  activeId,
  onOpen,
}: {
  book: BookPayload;
  activeId?: string | null;
  onOpen: (chunk: Paragraph) => void;
}) {
  return (
    <aside className="spine-panel">
      <div className="rail-head">
        <h3>Spine · chunks</h3>
        <span className="rail-count">{book.paragraphs.length}</span>
      </div>
      <p className="rail-empty">
        The passages the index reads. Click one to find it in the book.
      </p>
      <ul className="chunk-list">
        {book.paragraphs.map((c) => (
          <li key={c.id}>
            <button
              className={`chunk-row ${c.id === activeId ? "active" : ""}`}
              onClick={() => onOpen(c)}
            >
              <span className="chunk-hd">
                <span className="chunk-id">#{c.id.split("#")[1]}</span>
                {c.heading && <span className="chunk-heading">{c.heading}</span>}
                {c.page != null && <span className="chunk-page">p{c.page}</span>}
              </span>
              {c.spine_start != null && c.spine_end != null && (
                <span className="chunk-span">
                  chars {c.spine_start.toLocaleString()}–{c.spine_end.toLocaleString()}
                </span>
              )}
              <span className="chunk-preview">
                {c.text.slice(0, 140)}
                {c.text.length > 140 ? "…" : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
