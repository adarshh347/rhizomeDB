import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { BookPayload } from "../api/types";
import type { ImportResult } from "../api/client";
import { EpubRenderer } from "../reader/EpubRenderer";
import { ImportMenu } from "../reader/ImportMenu";
import { MdRenderer } from "../reader/MdRenderer";
import { NotesRail } from "../reader/NotesRail";
import { PdfRenderer } from "../reader/PdfRenderer";
import { SelectionToolbar } from "../reader/SelectionToolbar";
import type { AnchorInput } from "../reader/renderer";
import { useAnnotations } from "../reader/useAnnotations";
import "./reader.css";

const FORMAT_LABEL: Record<string, string> = { pdf: "PDF", epub: "EPUB", md: "Text" };

export function Reader() {
  const { bookId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [book, setBook] = useState<BookPayload | null>(null);
  const [format, setFormat] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<AnchorInput | null>(null);
  const [color, setColor] = useState("amber");
  const [composing, setComposing] = useState<AnchorInput | null>(null);
  const [noteText, setNoteText] = useState("");
  const [spineView, setSpineView] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const jumpRef = useRef<((a: import("../api/types").Annotation) => void) | null>(null);

  const { items, create, remove, pin, dismiss, reload } = useAnnotations(bookId);

  const onImported = (r: ImportResult & { error?: string }) => {
    reload();
    if (r.total < 0) {
      showFlash(`Import failed${r.error ? `: ${r.error}` : ""}.`);
    } else {
      const dup = r.duplicate ? `, ${r.duplicate} already present` : "";
      showFlash(`Imported ${r.imported} anchored, ${r.orphaned} orphaned${dup}.`);
    }
  };

  useEffect(() => {
    setBook(null);
    setError(null);
    api
      .book(bookId)
      .then((b) => {
        setBook(b);
        const wanted = params.get("format");
        const avail: string[] = b.formats.filter((f) => f.available).map((f) => f.format);
        setFormat(wanted && avail.includes(wanted) ? wanted : b.default_format);
      })
      .catch((e: ApiError) => setError(e.message));
  }, [bookId]);

  const pickFormat = (f: string) => {
    setFormat(f);
    setAnchor(null);
    const next = new URLSearchParams(params);
    next.set("format", f);
    setParams(next, { replace: true });
  };

  const showFlash = (msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 3200);
  };

  const doCreate = async (a: AnchorInput, note: string) => {
    try {
      const res = await create({
        book_id: bookId,
        quote: a.quote,
        prefix: a.prefix,
        suffix: a.suffix,
        kind: "highlight",
        note,
        color,
        locator: a.locator,
      });
      if (res.orphaned) {
        showFlash("Saved, but the quote could not be anchored — see the rail.");
      } else {
        const primary = res.chunks.find((c) => c.primary)?.chunk_id;
        const approx = res.annotation.selector?.approximate;
        showFlash(`Anchored to ${primary ?? "the spine"}${approx ? " (approximate)" : ""}.`);
      }
    } catch (e) {
      showFlash(`Could not save: ${(e as ApiError).message}`);
    }
    window.getSelection()?.removeAllRanges();
    setAnchor(null);
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
  if (!book) return <div className="center-note">Opening the book…</div>;

  const rendererProps = {
    bookId,
    book,
    annotations: items,
    onSelect: setAnchor,
    jumpRef,
  };

  return (
    <div className={`reader ${spineView ? "spine-on" : ""}`}>
      <div className="reader-bar">
        <div className="reader-title">
          <span className="rt-title">{book.title}</span>
          <span className="rt-author">{book.author}</span>
        </div>
        <span className="spacer" />
        {book.formats.length > 1 && (
          <div className="format-switch">
            {book.formats.map((f) => (
              <button
                key={f.format}
                className={`fmt ${f.format === format ? "on" : ""}`}
                disabled={!f.available}
                title={f.available ? "" : "Source file not present locally (lives in R2)"}
                onClick={() => f.available && pickFormat(f.format)}
              >
                {FORMAT_LABEL[f.format] ?? f.format}
              </button>
            ))}
          </div>
        )}
        {format === "md" && (
          <label className="spine-toggle">
            <input
              type="checkbox"
              checked={spineView}
              onChange={(e) => setSpineView(e.target.checked)}
            />
            Spine view
          </label>
        )}
        <ImportMenu bookId={bookId} formats={book.formats} onImported={onImported} />
      </div>

      <div className="reader-body">
        <div className="renderer-slot">
          {format === "pdf" && <PdfRenderer {...rendererProps} />}
          {format === "epub" && <EpubRenderer {...rendererProps} />}
          {format === "md" && <MdRenderer {...rendererProps} spineView={spineView} />}
        </div>

        <NotesRail
          items={items}
          onJump={(a) => jumpRef.current?.(a)}
          onDelete={remove}
          onPin={pin}
          onDismiss={dismiss}
        />
      </div>

      {anchor && (
        <SelectionToolbar
          anchor={anchor}
          color={color}
          onColor={setColor}
          onHighlight={() => doCreate(anchor, "")}
          onNote={() => {
            setComposing(anchor);
            setNoteText("");
            setAnchor(null);
          }}
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
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  doCreate(composing, noteText.trim());
                  setComposing(null);
                }
                if (e.key === "Escape") setComposing(null);
              }}
            />
            <div className="composer-actions">
              <button className="btn" onClick={() => setComposing(null)}>
                Cancel
              </button>
              <button
                className="btn primary"
                onClick={() => {
                  doCreate(composing, noteText.trim());
                  setComposing(null);
                }}
              >
                Save note
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
