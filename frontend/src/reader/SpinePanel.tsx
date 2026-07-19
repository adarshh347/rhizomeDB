import { useEffect, useRef } from "react";

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
  onConnect,
}: {
  book: BookPayload;
  activeId?: string | null;
  onOpen: (chunk: Paragraph) => void;
  onConnect: (chunk: Paragraph) => void;
}) {
  const activeRef = useRef<HTMLLIElement>(null);

  // Keep the active chunk (driven by the reader's scroll position) in view
  // inside the panel. Adjust only the panel's own scrollTop — never bubble up
  // to move the page, which would fight the reading you're tracking.
  useEffect(() => {
    const li = activeRef.current;
    const panel = li?.closest(".spine-panel") as HTMLElement | null;
    if (!li || !panel) return;
    const lr = li.getBoundingClientRect();
    const pr = panel.getBoundingClientRect();
    if (lr.top < pr.top + 8 || lr.bottom > pr.bottom - 8) {
      panel.scrollTop += lr.top - pr.top - panel.clientHeight * 0.3;
    }
  }, [activeId]);

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
          <li
            key={c.id}
            ref={c.id === activeId ? activeRef : undefined}
            className={`chunk-row ${c.id === activeId ? "active" : ""}`}
          >
            <button className="chunk-main" onClick={() => onOpen(c)}>
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
            <button
              className="chunk-connect"
              onClick={() => onConnect(c)}
              title="Find rhizomatic connections to this passage"
            >
              ⇄
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
