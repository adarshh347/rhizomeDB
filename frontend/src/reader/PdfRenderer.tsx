import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
// Vite bundles the worker locally (no CDN), satisfying the PRD's vendor rule.
import PdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?worker";

import type { Annotation } from "../api/types";
import type { AnchorInput, RendererProps } from "./renderer";

pdfjsLib.GlobalWorkerOptions.workerPort = new PdfWorker();

const SCALE = 1.5;
const CONTEXT = 32;

interface PageInfo {
  el: HTMLDivElement;
  text: string; // concatenated page text (the offset map's substrate)
}

// PDF renderer: PDF.js canvas pages + a selectable text layer whose spans carry
// their offset into the page text. A selection becomes quote/prefix/suffix (for
// the one resolver) plus a native locator {page, quads} (normalised 0..1 of the
// page box, so highlights survive re-render) painted as absolute divs.
export function PdfRenderer({ bookId, annotations, onSelect, handleRef }: RendererProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<PageInfo[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const [version, setVersion] = useState(0); // bumps when pages finish rendering

  // ---- load + render every page once -------------------------------------
  useEffect(() => {
    let cancelled = false;
    const host = hostRef.current;
    if (!host) return;
    host.innerHTML = "";
    pagesRef.current = [];
    setStatus("loading");

    (async () => {
      try {
        const doc = await pdfjsLib.getDocument({
          url: `/api/v2/books/${encodeURIComponent(bookId)}/file`,
          // Standard-font + cmap data, served locally (no CDN). Base-14 fonts
          // (Helvetica/Times/…) and non-Latin encodings need these; without
          // them page.render() can stall on a font that never arrives.
          cMapUrl: "/pdfjs/cmaps/",
          cMapPacked: true,
          standardFontDataUrl: "/pdfjs/standard_fonts/",
        }).promise;
        for (let n = 1; n <= doc.numPages; n++) {
          if (cancelled) return;
          const page = await doc.getPage(n);
          const natural = page.getViewport({ scale: 1 });
          // Fit the whole native page inside the available reading width. The
          // canvas and text layer are rendered at the same scale, preserving
          // PDF colour fidelity, selection geometry, and locator quads.
          const available = Math.max(320, host.clientWidth - 32);
          const renderScale = Math.min(SCALE, available / natural.width);
          const viewport = page.getViewport({ scale: renderScale });

          const pageEl = document.createElement("div");
          pageEl.className = "pdf-page";
          pageEl.dataset.page = String(n - 1);
          pageEl.style.width = `${viewport.width}px`;
          pageEl.style.height = `${viewport.height}px`;

          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          const ctx = canvas.getContext("2d")!;
          pageEl.appendChild(canvas);

          const textDiv = document.createElement("div");
          textDiv.className = "pdf-textlayer";
          textDiv.style.setProperty("--scale-factor", String(renderScale));
          pageEl.appendChild(textDiv);
          host.appendChild(pageEl);

          // The selectable text layer is what anchoring needs, so render it
          // first. The canvas is purely visual — paint it in the background so
          // a slow raster never blocks reading or selection.
          const textContent = await page.getTextContent();
          const textLayer = new pdfjsLib.TextLayer({
            textContentSource: textContent,
            container: textDiv,
            viewport,
          });
          await textLayer.render();
          page.render({ canvasContext: ctx, viewport }).promise.catch(() => {});

          // Build the offset map: walk the rendered spans in order, stamping
          // each with its start offset into the page's concatenated text.
          let pageText = "";
          textDiv.querySelectorAll<HTMLElement>("span").forEach((span) => {
            if (span.classList.contains("endOfContent")) return;
            const t = span.textContent ?? "";
            if (!t) return;
            span.dataset.off = String(pageText.length);
            pageText += t;
            // TextLayer usually appends a trailing space per item via the
            // element's own text; if not, approximate word separation.
            if (!/\s$/.test(t)) pageText += " ";
          });
          pagesRef.current.push({ el: pageEl, text: pageText });
        }
        if (!cancelled) {
          setStatus("ready");
          setVersion((v) => v + 1);
        }
      } catch (e) {
        if (!cancelled) {
          setStatus("error");
          setMessage(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bookId]);

  // ---- selection -> AnchorInput ------------------------------------------
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const onUp = () => {
      setTimeout(() => onSelect(readSelection(host, pagesRef.current)), 0);
    };
    host.addEventListener("mouseup", onUp);
    return () => host.removeEventListener("mouseup", onUp);
  }, [onSelect]);

  // ---- paint stored highlights (locator {page, quads}) -------------------
  useEffect(() => {
    for (const { el } of pagesRef.current) {
      el.querySelectorAll(".pdf-hl").forEach((n) => n.remove());
    }
    for (const a of annotations) {
      const loc = a.selector?.locator as
        | { page?: number; quads?: { x: number; y: number; w: number; h: number }[] }
        | undefined;
      if (!loc || loc.page == null || !loc.quads) continue;
      const page = pagesRef.current[loc.page];
      if (!page) continue;
      const { width, height } = page.el.getBoundingClientRect();
      for (const q of loc.quads) {
        const div = document.createElement("div");
        div.className = "pdf-hl";
        div.dataset.aid = a.id;
        div.style.left = `${q.x * width}px`;
        div.style.top = `${q.y * height}px`;
        div.style.width = `${q.w * width}px`;
        div.style.height = `${q.h * height}px`;
        div.style.background = `var(--hl-${a.color || "amber"})`;
        if (a.selector?.approximate) div.classList.add("approx");
        page.el.appendChild(div);
      }
    }
  }, [annotations, version]);

  const pulse = (el: Element, behavior: ScrollBehavior = "smooth") => {
    el.scrollIntoView({ behavior, block: "center" });
    el.classList.add("pulse");
    setTimeout(() => el.classList.remove("pulse"), 1200);
  };

  handleRef.current = {
    jumpToAnnotation: (a: Annotation) => {
      const el = hostRef.current?.querySelector(`.pdf-hl[data-aid="${a.id}"]`);
      if (el) pulse(el);
    },
    // Locate a chunk by finding its opening text in a page's text layer.
    locateChunk: (chunk) => {
      const needle = chunk.text.slice(0, 40).replace(/\s+/g, " ").trim();
      if (!needle) return;
      for (const page of pagesRef.current) {
        if (page.text.replace(/\s+/g, " ").includes(needle)) {
          pulse(page.el, "auto");
          return;
        }
      }
    },
  };

  if (status === "error")
    return (
      <div className="center-note state-error" role="alert">
        <p>Couldn’t render the PDF: {message}</p>
      </div>
    );

  return (
    <div className="pdf-surface">
      {status === "loading" && (
        <div className="center-note state-loading" role="status">
          <span className="spinner" aria-hidden /> Rendering the PDF…
        </div>
      )}
      <div className="pdf-pages" ref={hostRef} />
    </div>
  );
}

function readSelection(host: HTMLElement, pages: PageInfo[]): AnchorInput | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!host.contains(range.commonAncestorContainer)) return null;

  const pageEl = (range.startContainer.parentElement as HTMLElement)?.closest<HTMLElement>(
    ".pdf-page",
  );
  if (!pageEl || pageEl.dataset.page == null) return null;
  const pageIndex = parseInt(pageEl.dataset.page, 10);
  const pageText = pages[pageIndex]?.text ?? "";

  const off = (node: Node, o: number): number | null => {
    const span = (node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement))
      ?.closest<HTMLElement>("[data-off]");
    if (!span || span.dataset.off == null) return null;
    return parseInt(span.dataset.off, 10) + (node.nodeType === Node.TEXT_NODE ? o : 0);
  };
  let a = off(range.startContainer, range.startOffset);
  let b = off(range.endContainer, range.endOffset);
  if (a === null || b === null) return null;
  if (a > b) [a, b] = [b, a];
  const quote = pageText.slice(a, b).trim();
  if (!quote) return null;

  const box = pageEl.getBoundingClientRect();
  const quads = [...range.getClientRects()]
    .filter((r) => r.width > 0 && r.height > 0)
    .map((r) => ({
      x: (r.left - box.left) / box.width,
      y: (r.top - box.top) / box.height,
      w: r.width / box.width,
      h: r.height / box.height,
    }));

  return {
    quote,
    prefix: pageText.slice(Math.max(0, a - CONTEXT), a),
    suffix: pageText.slice(b, b + CONTEXT),
    locator: { page: pageIndex, quads },
    rect: range.getBoundingClientRect(),
  };
}
