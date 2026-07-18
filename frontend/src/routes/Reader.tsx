import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { BookPayload } from "../api/types";
import { type Anchor, selectionToAnchor } from "../reader/anchoring";
import { NotesRail } from "../reader/NotesRail";
import { SelectionToolbar } from "../reader/SelectionToolbar";
import { SpineView } from "../reader/SpineView";
import { parseSpine } from "../reader/spine";
import { useAnnotations } from "../reader/useAnnotations";
import "./reader.css";

interface Loaded {
  book: BookPayload;
  spine: string;
}

export function Reader() {
  const { bookId = "" } = useParams();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [color, setColor] = useState("amber");
  const [composing, setComposing] = useState<Anchor | null>(null);
  const [noteText, setNoteText] = useState("");
  const [spineView, setSpineView] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  const { items, highlights, create, remove } = useAnnotations(bookId);

  useEffect(() => {
    setData(null);
    setError(null);
    Promise.all([api.book(bookId), api.spine(bookId)])
      .then(([book, spine]) => setData({ book, spine: spine.text }))
      .catch((e: ApiError) => setError(e.message));
  }, [bookId]);

  const blocks = useMemo(
    () => (data ? parseSpine(data.spine) : []),
    [data],
  );

  // Which chunk (by spine overlap) a given offset belongs to — the reveal
  // behind the "spine view" toggle (PRD R6): the engineering layer under the
  // prose, made visible in the margin.
  const chunkAt = useCallback(
    (offset: number): string | null => {
      if (!data) return null;
      let best: { id: string; overlap: number } | null = null;
      for (const p of data.book.paragraphs) {
        if (p.spine_start == null || p.spine_end == null) continue;
        if (offset >= p.spine_start && offset < p.spine_end) {
          const dist = Math.min(offset - p.spine_start, p.spine_end - offset);
          if (!best || dist > best.overlap) best = { id: p.id, overlap: dist };
        }
      }
      return best?.id ?? null;
    },
    [data],
  );

  const onMouseUp = useCallback(() => {
    if (!data || !surfaceRef.current) return;
    // let the browser finalise the selection first
    setTimeout(() => {
      const a = surfaceRef.current
        ? selectionToAnchor(data.spine, surfaceRef.current)
        : null;
      setAnchor(a);
    }, 0);
  }, [data]);

  const clearSelection = () => {
    window.getSelection()?.removeAllRanges();
    setAnchor(null);
  };

  const showFlash = (msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 3200);
  };

  const doCreate = async (a: Anchor, note: string) => {
    try {
      const res = await create({
        book_id: bookId,
        quote: a.quote,
        prefix: a.prefix,
        suffix: a.suffix,
        kind: "highlight",
        note,
        color,
      });
      if (res.orphaned) {
        showFlash("Saved, but the quote could not be anchored — see the rail.");
      } else {
        const primary = res.chunks.find((c) => c.primary)?.chunk_id;
        const approx = res.annotation.selector?.approximate;
        showFlash(
          `Anchored to ${primary ?? "the spine"}${approx ? " (approximate)" : ""}.`,
        );
      }
    } catch (e) {
      showFlash(`Could not save: ${(e as ApiError).message}`);
    }
    clearSelection();
  };

  const onHighlight = () => {
    if (anchor) doCreate(anchor, "");
  };
  const onNote = () => {
    if (anchor) {
      setComposing(anchor);
      setNoteText("");
      setAnchor(null);
    }
  };
  const onComposeSave = () => {
    if (composing) {
      doCreate(composing, noteText.trim());
      setComposing(null);
    }
  };

  const jumpTo = (id: string) => {
    const el = surfaceRef.current?.querySelector(`[data-aid="${id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("pulse");
      setTimeout(() => el.classList.remove("pulse"), 1200);
    }
  };

  if (error)
    return (
      <div className="center-note">
        <p>Couldn’t open this book: {error}</p>
        <p>
          <Link to="/">← back to the library</Link>
        </p>
      </div>
    );
  if (!data) return <div className="center-note">Opening the book…</div>;

  return (
    <div className={`reader ${spineView ? "spine-on" : ""}`}>
      <div className="reader-bar">
        <div className="reader-title">
          <span className="rt-title">{data.book.title}</span>
          <span className="rt-author">{data.book.author}</span>
        </div>
        <span className="spacer" />
        <label className="spine-toggle">
          <input
            type="checkbox"
            checked={spineView}
            onChange={(e) => setSpineView(e.target.checked)}
          />
          Spine view
        </label>
      </div>

      <div className="reader-body">
        <article
          className="reading-surface"
          ref={surfaceRef}
          onMouseUp={onMouseUp}
        >
          {spineView ? (
            <SpineViewWithChunks blocks={blocks} highlights={highlights} chunkAt={chunkAt} />
          ) : (
            <SpineView blocks={blocks} highlights={highlights} />
          )}
        </article>

        <NotesRail
          items={items}
          onJump={(a) => jumpTo(a.id)}
          onDelete={remove}
        />
      </div>

      {anchor && (
        <SelectionToolbar
          anchor={anchor}
          color={color}
          onColor={setColor}
          onHighlight={onHighlight}
          onNote={onNote}
        />
      )}

      {flash && <div className="reader-flash">{flash}</div>}

      {composing && (
        <div className="composer-back" onClick={() => setComposing(null)}>
          <div className="composer" onClick={(e) => e.stopPropagation()}>
            <div className="composer-quote">“{composing.quote}”</div>
            <textarea
              autoFocus
              placeholder="Your note…"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onComposeSave();
                if (e.key === "Escape") setComposing(null);
              }}
            />
            <div className="composer-actions">
              <button className="btn" onClick={() => setComposing(null)}>
                Cancel
              </button>
              <button className="btn primary" onClick={onComposeSave}>
                Save note
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Spine-view variant: the same painted prose, but each paragraph gets a faint
// margin badge naming the chunk it belongs to — the dial between reading and
// engineering, turned toward the index.
function SpineViewWithChunks({
  blocks,
  highlights,
  chunkAt,
}: {
  blocks: ReturnType<typeof parseSpine>;
  highlights: Parameters<typeof SpineView>[0]["highlights"];
  chunkAt: (offset: number) => string | null;
}) {
  return (
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
  );
}
