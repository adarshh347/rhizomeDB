import { useEffect, useRef, useState } from "react";
import ePub, { type Rendition } from "epubjs";

import type { Annotation } from "../api/types";
import type { AnchorInput, RendererProps } from "./renderer";

const CONTEXT = 32;

// Concrete highlight fills (the SVG overlay epub.js draws lives in the book
// iframe, where our CSS custom properties don't reach). Kept close to the
// tokens' light values; opacity carries the tint in either theme.
const FILL: Record<string, string> = {
  amber: "#f4d98b",
  rose: "#f2b8b0",
  sage: "#bcd6ac",
  sky: "#a9cbe0",
  violet: "#cabce0",
};

// EPUB renderer: reflowable chapters via epub.js. A selection yields
// quote/prefix/suffix (for the one resolver) plus a native {cfi} locator;
// stored highlights paint through Rendition.annotations at their CFI. The book
// iframe is themed from the app's paper/ink tokens so it reads as one surface.
export function EpubRenderer({ bookId, annotations, onSelect, handleRef }: RendererProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendRef = useRef<Rendition | null>(null);
  const paintedRef = useRef<Set<string>>(new Set());
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const [ready, setReady] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const host = hostRef.current;
    if (!host) return;
    host.innerHTML = "";
    setStatus("loading");

    // Open from bytes, not the URL: the /file endpoint has no `.epub`
    // extension, so epub.js would otherwise treat it as an *unpacked* directory
    // and silently render nothing. `openAs: "binary"` reads the zip archive.
    fetch(`/api/v2/books/${encodeURIComponent(bookId)}/file`)
      .then((r) => r.arrayBuffer())
      .then((buf) => {
        if (cancelled) return;
        const book = ePub(buf as ArrayBuffer, { openAs: "binary" });
        const rendition = book.renderTo(host, {
          width: "100%",
          height: "100%",
          flow: "scrolled-doc",
          spread: "none",
        });
        rendRef.current = rendition;
        setupTheme(rendition);
        const markReady = () => {
          if (!cancelled) {
            setStatus("ready");
            setReady((v) => v + 1);
          }
        };
        // Readiness comes from the `rendered` event, not display()'s promise
        // (which can stay pending with a binary/scrolled-doc source). A timeout
        // fallback covers the case where the event is missed on remount.
        rendition.on("rendered", markReady);
        rendition.on("selected", (cfiRange: string, contents: any) => {
          const found = readSelection(cfiRange, contents);
          if (found) onSelect(found);
        });
        rendition.display().catch(fail);
        setTimeout(() => {
          if (!cancelled && host.querySelector("iframe")) markReady();
        }, 1200);
      })
      .catch(fail);

    function fail(e: unknown) {
      if (!cancelled) {
        setStatus("error");
        setMessage(e instanceof Error ? e.message : String(e));
      }
    }

    // Theme the book iframe from the live app tokens (keeps light/dark in sync).
    function setupTheme(r: Rendition) {
      const css = getComputedStyle(document.documentElement);
      const tok = (n: string) => css.getPropertyValue(n).trim();
      r.themes.register("rhizome", {
        body: {
          background: tok("--paper"),
          color: tok("--ink"),
          // the book reads in the reading serif, same as the MD surface
          "font-family": tok("--font-reading"),
          "line-height": "1.7",
          padding: "1rem 1.5rem",
        },
        p: { "margin-bottom": "1.1rem" },
        "h1, h2, h3": { "font-family": tok("--font-display"), color: tok("--ink") },
        "::selection": { background: tok("--accent-wash") },
      });
      r.themes.select("rhizome");
    }

    return () => {
      cancelled = true;
      rendRef.current?.destroy();
      rendRef.current = null;
      paintedRef.current.clear();
    };
    // onSelect is stable enough; re-running on bookId is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  // Paint stored highlights that carry a CFI locator; diff against what's drawn.
  useEffect(() => {
    const rendition = rendRef.current;
    if (!rendition || status !== "ready") return;
    const want = new Map<string, Annotation>();
    for (const a of annotations) {
      const cfi = (a.selector?.locator as { cfi?: string } | undefined)?.cfi;
      if (cfi) want.set(cfi, a);
    }
    // remove stale
    for (const cfi of paintedRef.current) {
      if (!want.has(cfi)) {
        try {
          rendition.annotations.remove(cfi, "highlight");
        } catch {
          /* already gone */
        }
        paintedRef.current.delete(cfi);
      }
    }
    // add new
    for (const [cfi, a] of want) {
      if (paintedRef.current.has(cfi)) continue;
      try {
        rendition.annotations.highlight(
          cfi,
          { id: a.id },
          () => handleRef.current?.jumpToAnnotation(a),
          "",
          {
            fill: FILL[a.color] || FILL.amber,
            "fill-opacity": "0.4",
            ...(a.selector?.approximate ? { "stroke-dasharray": "2", stroke: "#b98a2e" } : {}),
          },
        );
        paintedRef.current.add(cfi);
      } catch {
        /* CFI not in a rendered section yet */
      }
    }
  }, [annotations, status, ready]);

  handleRef.current = {
    jumpToAnnotation: (a: Annotation) => {
      const cfi = (a.selector?.locator as { cfi?: string } | undefined)?.cfi;
      if (cfi) rendRef.current?.display(cfi);
    },
    // Locate a chunk by searching the rendered book for its opening text.
    locateChunk: (chunk) => {
      const needle = chunk.text.slice(0, 40).replace(/\s+/g, " ").trim();
      const host = hostRef.current;
      if (!needle || !host) return;
      for (const iframe of host.querySelectorAll("iframe")) {
        const doc = iframe.contentDocument;
        if (!doc) continue;
        const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
        let node: Node | null;
        while ((node = walker.nextNode())) {
          if ((node.textContent ?? "").replace(/\s+/g, " ").includes(needle)) {
            (node.parentElement as HTMLElement | null)?.scrollIntoView({
              block: "center",
            });
            return;
          }
        }
      }
    },
  };

  if (status === "error")
    return (
      <div className="center-note state-error" role="alert">
        <p>Couldn’t render the EPUB: {message}</p>
      </div>
    );

  return (
    <div className="epub-surface">
      {status === "loading" && (
        <div className="center-note state-loading" role="status">
          <span className="spinner" aria-hidden /> Opening the EPUB…
        </div>
      )}
      <div className="epub-host" ref={hostRef} />
    </div>
  );
}

function readSelection(cfiRange: string, contents: any): AnchorInput | null {
  const win = contents.window as Window;
  const sel = win.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  const quote = sel.toString().trim();
  if (!quote) return null;

  const doc = contents.document as Document;
  const { prefix, suffix } = context(doc, range);

  // viewport rect = selection rect inside the iframe + the iframe's own offset
  const iframe = doc.defaultView?.frameElement as HTMLElement | null;
  const local = range.getBoundingClientRect();
  const base = iframe?.getBoundingClientRect();
  const rect = new DOMRect(
    local.left + (base?.left ?? 0),
    local.top + (base?.top ?? 0),
    local.width,
    local.height,
  );

  return { quote, prefix, suffix, locator: { cfi: cfiRange }, rect };
}

// Collect up to CONTEXT chars of text on each side of the selection by walking
// the iframe document's text nodes — enough to disambiguate a repeated quote.
function context(doc: Document, range: Range): { prefix: string; suffix: string } {
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  let prefix = "";
  let suffix = "";
  let phase: "before" | "after" = "before";
  let node: Node | null;
  while ((node = walker.nextNode())) {
    if (node === range.startContainer) {
      prefix += (node.textContent ?? "").slice(0, range.startOffset);
      phase = "after";
      if (node === range.endContainer) {
        suffix += (node.textContent ?? "").slice(range.endOffset);
      }
      continue;
    }
    if (node === range.endContainer) {
      suffix += (node.textContent ?? "").slice(range.endOffset);
      phase = "after";
      continue;
    }
    if (phase === "before") prefix += node.textContent ?? "";
    else suffix += node.textContent ?? "";
    if (suffix.length > CONTEXT * 2) break;
  }
  return { prefix: prefix.slice(-CONTEXT), suffix: suffix.slice(0, CONTEXT) };
}
