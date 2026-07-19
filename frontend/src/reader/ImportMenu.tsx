import { useRef, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Dialog from "@radix-ui/react-dialog";
import { ChevronDown } from "lucide-react";

import { api, ApiError, type ImportResult } from "../api/client";
import type { BookFormat } from "../api/types";

// Bring in annotations made elsewhere. Embedded PDF highlights when the book has
// a PDF; pasted Markdown/Obsidian notes for any book; a reader's exported
// sidecar (KOReader .lua, Calibre/generic JSON, CSV). All flow through the one
// resolver server-side, so results include how many anchored vs orphaned.
// Menu = Radix DropdownMenu; the markdown composer = Radix Dialog (focus trap,
// esc, scroll-lock, aria) skinned in paper/ink.
export function ImportMenu({
  bookId,
  formats,
  onImported,
}: {
  bookId: string;
  formats: BookFormat[];
  onImported: (r: ImportResult) => void;
}) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [auto, setAuto] = useState(false);
  const [busy, setBusy] = useState(false);
  const sidecarInput = useRef<HTMLInputElement>(null);
  const mdRef = useRef<HTMLTextAreaElement>(null);
  const hasPdf = formats.some((f) => f.format === "pdf" && f.available);

  async function run(fn: () => Promise<ImportResult>) {
    setBusy(true);
    try {
      onImported(await fn());
      setMarkdown(null);
      setText("");
      setAuto(false);
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
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button className="btn import-trigger">
            Import
            <ChevronDown size={14} strokeWidth={2} aria-hidden />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="rz-menu" align="end" sideOffset={6}>
            <DropdownMenu.Item
              className="rz-menu-item"
              disabled={!hasPdf}
              onSelect={() => run(() => api.importPdf(bookId))}
            >
              Embedded PDF highlights
            </DropdownMenu.Item>
            <DropdownMenu.Item
              className="rz-menu-item"
              onSelect={() => {
                setText("");
                setAuto(false);
                setMarkdown("");
              }}
            >
              Markdown / Obsidian notes…
            </DropdownMenu.Item>
            <DropdownMenu.Item
              className="rz-menu-item"
              // defer past the menu's focus-return so the file dialog opens cleanly
              onSelect={() => setTimeout(() => sidecarInput.current?.click(), 0)}
            >
              EPUB reader sidecar…
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      <input
        ref={sidecarInput}
        type="file"
        accept=".lua,.json,.csv,.txt"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = ""; // let the same file be picked again
          if (file) run(() => api.importSidecar(bookId, file));
        }}
      />

      <Dialog.Root
        open={markdown !== null}
        onOpenChange={(o) => {
          if (!o) setMarkdown(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="rz-overlay" />
          <Dialog.Content
            className="rz-dialog"
            aria-describedby={undefined}
            onOpenAutoFocus={(e) => {
              e.preventDefault();
              mdRef.current?.focus();
            }}
          >
            <Dialog.Title className="section-label">Import markdown notes</Dialog.Title>
            <p className="dialog-help">
              Paste notes — <code>==highlights==</code> and <code>&gt;</code>{" "}
              blockquotes (an optional line after a quote becomes its note).
            </p>
            <textarea
              ref={mdRef}
              className="field code"
              placeholder="==a highlighted phrase==&#10;&#10;> a quoted passage&#10;— my note on it"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <label className="md-auto">
              <input
                type="checkbox"
                checked={auto}
                onChange={(e) => setAuto(e.target.checked)}
              />
              Auto-detect the book (match the whole library)
            </label>
            <div className="composer-actions">
              <Dialog.Close asChild>
                <button className="btn">Cancel</button>
              </Dialog.Close>
              <button
                className="btn primary"
                disabled={busy || !text.trim()}
                onClick={() => run(() => api.importMarkdown(auto ? "" : bookId, text))}
              >
                {busy ? "Importing…" : auto ? "Detect & import" : "Import"}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
