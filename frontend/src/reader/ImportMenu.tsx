import { useRef, useState } from "react";

import { api, ApiError, type ImportResult } from "../api/client";
import type { BookFormat } from "../api/types";

// Bring in annotations made elsewhere. Embedded PDF highlights when the book has
// a PDF; pasted Markdown/Obsidian notes for any book; a reader's exported
// sidecar (KOReader .lua, Calibre/generic JSON, CSV). All flow through the one
// resolver server-side, so results include how many anchored vs orphaned.
export function ImportMenu({
  bookId,
  formats,
  onImported,
}: {
  bookId: string;
  formats: BookFormat[];
  onImported: (r: ImportResult) => void;
}) {
  const [open, setOpen] = useState(false);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const sidecarInput = useRef<HTMLInputElement>(null);
  const hasPdf = formats.some((f) => f.format === "pdf" && f.available);

  async function run(fn: () => Promise<ImportResult>) {
    setBusy(true);
    try {
      onImported(await fn());
      setOpen(false);
      setMarkdown(null);
      setText("");
    } catch (e) {
      onImported({
        origin: "error",
        imported: 0,
        orphaned: 0,
        duplicate: 0,
        total: -1,
        ...({ error: (e as ApiError).message } as object),
      } as ImportResult & { error: string });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="import-menu">
      <button className="btn" onClick={() => setOpen((o) => !o)}>
        Import ▾
      </button>
      {open && (
        <div className="import-pop" onMouseLeave={() => setOpen(false)}>
          <button
            className="import-opt"
            disabled={!hasPdf}
            title={hasPdf ? "" : "This book has no PDF to read annotations from"}
            onClick={() => run(() => api.importPdf(bookId))}
          >
            Embedded PDF highlights
          </button>
          <button
            className="import-opt"
            onClick={() => {
              setMarkdown("");
              setOpen(false);
            }}
          >
            Markdown / Obsidian notes…
          </button>
          <button
            className="import-opt"
            title="KOReader .lua, Calibre/generic JSON, or CSV"
            onClick={() => sidecarInput.current?.click()}
          >
            EPUB reader sidecar…
          </button>
        </div>
      )}

      <input
        ref={sidecarInput}
        type="file"
        accept=".lua,.json,.csv,.txt"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = ""; // let the same file be picked again
          if (file) {
            setOpen(false);
            run(() => api.importSidecar(bookId, file));
          }
        }}
      />

      {markdown !== null && (
        <div className="composer-back" onClick={() => setMarkdown(null)}>
          <div className="composer" onClick={(e) => e.stopPropagation()}>
            <div className="composer-head">
              Paste notes — <code>==highlights==</code> and <code>&gt;</code>{" "}
              blockquotes (an optional line after a quote becomes its note).
            </div>
            <textarea
              autoFocus
              className="md-import"
              placeholder="==a highlighted phrase==&#10;&#10;> a quoted passage&#10;— my note on it"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="composer-actions">
              <button className="btn" onClick={() => setMarkdown(null)}>
                Cancel
              </button>
              <button
                className="btn primary"
                disabled={busy || !text.trim()}
                onClick={() => run(() => api.importMarkdown(bookId, text))}
              >
                {busy ? "Importing…" : "Import"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
