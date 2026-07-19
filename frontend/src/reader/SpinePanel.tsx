import { useEffect, useRef } from "react";
import { ArrowLeftRight } from "lucide-react";

import type { BookPayload, Paragraph } from "../api/types";
import { Tip } from "./Tip";

// The engineering layer made visible (R6): the book's chunks — the units the
// index and connection engine read — each with its id, character span and a
// preview. De-carded to quiet, hairline-separated rows. Clicking a row drives
// the native renderer to that passage; the ⇄ opens its connections.
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
  // inside the rail — nudging only the rail's own scrollTop, never the page.
  useEffect(() => {
    const li = activeRef.current;
    const rail = li?.closest(".rail") as HTMLElement | null;
    if (!li || !rail) return;
    const lr = li.getBoundingClientRect();
    const pr = rail.getBoundingClientRect();
    if (lr.top < pr.top + 8 || lr.bottom > pr.bottom - 8) {
      rail.scrollTop += lr.top - pr.top - rail.clientHeight * 0.3;
    }
  }, [activeId]);

  return (
    <aside className="rail spine-rail">
      <div className="rail-head">
        <span className="section-label">Spine · chunks</span>
        <span className="count">{book.paragraphs.length}</span>
      </div>
      <p className="rail-note">
        The passages the index reads. Click one to find it in the book.
      </p>
      <ul className="rail-list">
        {book.paragraphs.map((c) => (
          <li
            key={c.id}
            ref={c.id === activeId ? activeRef : undefined}
            className={`row row-split ${c.id === activeId ? "active" : ""}`}
          >
            <button className="row-main" onClick={() => onOpen(c)}>
              <span className="chunk-line">
                <span className="mono chunk-id">#{c.id.split("#")[1]}</span>
                {c.heading && <span className="chunk-heading">{c.heading}</span>}
                {c.page != null && <span className="mono chunk-page">p{c.page}</span>}
              </span>
              {c.spine_start != null && c.spine_end != null && (
                <span className="mono chunk-span">
                  chars {c.spine_start.toLocaleString()}–{c.spine_end.toLocaleString()}
                </span>
              )}
              <span className="chunk-preview">
                {c.text.slice(0, 140)}
                {c.text.length > 140 ? "…" : ""}
              </span>
            </button>
            <span className="row-action">
              <Tip label="Find rhizomatic connections">
                <button
                  className="btn-ghost icon"
                  onClick={() => onConnect(c)}
                  aria-label="Find connections to this passage"
                >
                  <ArrowLeftRight size={15} strokeWidth={1.75} aria-hidden />
                </button>
              </Tip>
            </span>
          </li>
        ))}
      </ul>
    </aside>
  );
}
