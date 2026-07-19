import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";

import { api, ApiError } from "../api/client";
import type { BookPayload, Paragraph } from "../api/types";
import type { ImportResult } from "../api/client";
import { EpubRenderer } from "../reader/EpubRenderer";
import { ImportMenu } from "../reader/ImportMenu";
import { MdRenderer } from "../reader/MdRenderer";
import { PdfRenderer } from "../reader/PdfRenderer";
import { ReaderRail, type RailMode } from "../reader/ReaderRail";
import { SelectionToolbar } from "../reader/SelectionToolbar";
import type { AnchorInput, RendererHandle } from "../reader/renderer";
import { useAnnotations } from "../reader/useAnnotations";
import { useConnections } from "../reader/useConnections";
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
  const [railMode, setRailMode] = useState<RailMode>("notes");
  const [connectionReturnMode, setConnectionReturnMode] = useState<RailMode>("notes");
  const [railOpen, setRailOpen] = useState(false);
  const [isNarrow, setIsNarrow] = useState(() => window.matchMedia("(max-width: 900px)").matches);
  const [connChunk, setConnChunk] = useState<string | null>(null);
  const [activeChunk, setActiveChunk] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const handleRef = useRef<RendererHandle | null>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  const { items, create, remove, pin, dismiss, reload } = useAnnotations(bookId);
  // The stream belongs to the Reader, above the tab panels. Mode switches only
  // change what is visible; they never mount, cancel, duplicate, or restart SSE.
  const connectionState = useConnections(connChunk);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const update = () => setIsNarrow(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  const showRail = (mode: RailMode) => {
    setRailMode(mode);
    if (isNarrow) setRailOpen(true);
  };

  const openConnections = (chunkId: string) => {
    if (railMode !== "connections") setConnectionReturnMode(railMode);
    setConnChunk(chunkId);
    setRailMode("connections");
    if (isNarrow) setRailOpen(true);
  };

  const closeConnections = () => {
    setRailMode(connectionReturnMode === "connections" ? "notes" : connectionReturnMode);
    setConnChunk(null);
    if (isNarrow) setRailOpen(false);
  };

  const openChunk = (chunk: Paragraph) => {
    setActiveChunk(chunk.id);
    handleRef.current?.locateChunk(chunk);
  };

  // book→spine: the renderer reports the chunk at the reading position as you
  // scroll. Ignore null probes (a gap between blocks) so the highlight holds
  // steady rather than flickering off. Stable identity — the spy effect depends
  // on it.
  const onVisibleChunk = useCallback((id: string | null) => {
    if (id) setActiveChunk(id);
  }, []);

  // "Open in book" (R6, engineering → reading): ?chunk=<id> scrolls to that
  // chunk once the renderer has loaded its content.
  useEffect(() => {
    const chunkId = params.get("chunk");
    if (!book || !chunkId) return;
    const chunk = book.paragraphs.find((p) => p.id === chunkId);
    if (!chunk) return;
    setActiveChunk(chunkId);
    let tries = 0;
    const timer = setInterval(() => {
      handleRef.current?.locateChunk(chunk);
      if (++tries >= 6) clearInterval(timer);
    }, 500);
    return () => clearInterval(timer);
  }, [book, format, params]);

  const onImported = (r: ImportResult & { error?: string }) => {
    reload();
    if (r.total < 0) {
      showFlash(`Import failed${r.error ? `: ${r.error}` : ""}.`);
    } else if (r.detected === null) {
      // auto-detect found no matching book (detected is null only on that path)
      showFlash("Couldn’t match those quotes to any book in the library.");
    } else {
      const dup = r.duplicate ? `, ${r.duplicate} already present` : "";
      // auto-detect resolved to a book — say which (its marks live over there)
      const where =
        r.detected && r.detected !== bookId && r.detected_title
          ? `Matched “${r.detected_title}” — `
          : "";
      showFlash(`${where}imported ${r.imported} anchored, ${r.orphaned} orphaned${dup}.`);
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
      <div className="center-note state-error" role="alert">
        <p>Couldn’t open this book: {error}</p>
        <p>
          <Link to="/">← back to the library</Link>
        </p>
      </div>
    );
  if (!book)
    return (
      <div className="center-note state-loading" role="status">
        <span className="spinner" aria-hidden /> Opening the book…
      </div>
    );

  const rendererProps = {
    bookId,
    book,
    annotations: items,
    onSelect: setAnchor,
    handleRef,
    onVisibleChunk,
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
        <label className="spine-toggle" title="Reveal the chunks under the text (R6)">
          <input
            type="checkbox"
            checked={spineView}
            onChange={(e) => {
              const checked = e.target.checked;
              setSpineView(checked);
              if (checked) setRailMode("spine");
              else if (railMode === "spine") setRailMode("notes");
            }}
          />
          Spine
        </label>
        <ImportMenu bookId={bookId} formats={book.formats} onImported={onImported} />
        <div className="mobile-rail-triggers" aria-label="Open reader context">
          <button className="btn-ghost" onClick={() => showRail("notes")}>Notes</button>
          <button className="btn-ghost" onClick={() => showRail("spine")}>Spine</button>
          <button
            className="btn-ghost"
            disabled={!connChunk}
            onClick={() => showRail("connections")}
          >
            Connections
          </button>
        </div>
      </div>

      <div className="reader-body">
        <div className="renderer-slot">
          {format === "pdf" && <PdfRenderer {...rendererProps} />}
          {format === "epub" && <EpubRenderer {...rendererProps} />}
          {format === "md" && (
            <MdRenderer
              {...rendererProps}
              spineView={spineView}
              trackSpine={railMode === "spine"}
            />
          )}
        </div>

        {!isNarrow && (
          <ReaderRail
            mode={railMode}
            onMode={setRailMode}
            book={book}
            items={items}
            activeChunk={activeChunk}
            connectionChunk={connChunk}
            connectionState={connectionState}
            onJump={(a) => handleRef.current?.jumpToAnnotation(a)}
            onDelete={remove}
            onPin={pin}
            onDismiss={dismiss}
            onOpenChunk={openChunk}
            onConnect={openConnections}
            onCloseConnections={closeConnections}
          />
        )}
      </div>

      {isNarrow && (
        <Dialog.Root open={railOpen} onOpenChange={setRailOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="rz-overlay rail-drawer-overlay" />
            <Dialog.Content className="rail-drawer" aria-describedby={undefined}>
              <Dialog.Title className="sr-only">Reader context</Dialog.Title>
              <ReaderRail
                mode={railMode}
                onMode={setRailMode}
                book={book}
                items={items}
                activeChunk={activeChunk}
                connectionChunk={connChunk}
                connectionState={connectionState}
                onJump={(a) => handleRef.current?.jumpToAnnotation(a)}
                onDelete={remove}
                onPin={pin}
                onDismiss={dismiss}
                onOpenChunk={openChunk}
                onConnect={openConnections}
                onCloseConnections={closeConnections}
              />
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}

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

      <Dialog.Root
        open={!!composing}
        onOpenChange={(o) => {
          if (!o) setComposing(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="rz-overlay" />
          <Dialog.Content
            className="rz-dialog dialog-note"
            aria-describedby={undefined}
            onOpenAutoFocus={(e) => {
              e.preventDefault();
              noteRef.current?.focus();
            }}
          >
            <Dialog.Title className="section-label">New note</Dialog.Title>
            {composing && (
              <>
                <blockquote className="quote-block">“{composing.quote}”</blockquote>
                <textarea
                  ref={noteRef}
                  className="field"
                  placeholder="Your note…"
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  onKeyDown={(e) => {
                    // ⌘/Ctrl+Enter saves; Esc is handled by the dialog itself.
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      doCreate(composing, noteText.trim());
                      setComposing(null);
                    }
                  }}
                />
                <div className="composer-actions">
                  <Dialog.Close asChild>
                    <button className="btn">Cancel</button>
                  </Dialog.Close>
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
              </>
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
