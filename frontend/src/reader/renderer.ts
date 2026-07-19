// The contract every renderer (MD / PDF / EPUB) satisfies so the reader shell,
// the selection toolbar, the notes rail and the resolve→create→paint flow are
// shared. A renderer's only format-specific jobs are: draw the book, turn a
// selection into an AnchorInput, and paint stored annotations back.
import type { Annotation, BookPayload, Paragraph } from "../api/types";

// What a selection yields, ready for /anchors resolution. `quote/prefix/suffix`
// go to the one resolver (quote is authoritative); `locator` is the format's
// own coordinates for fast view restoration (PDF {page, quads} · EPUB {cfi}).
// `rect` is viewport-relative, for placing the floating toolbar.
export interface AnchorInput {
  quote: string;
  prefix: string;
  suffix: string;
  locator?: Record<string, unknown>;
  rect: DOMRect;
}

// The imperative handle a renderer registers so the shell can drive it: jump to
// a stored mark, or locate a chunk in the native view (the reading⇄engineering
// dial of R6 — "open in book" lands here for every format).
export interface RendererHandle {
  jumpToAnnotation: (ann: Annotation) => void;
  locateChunk: (chunk: Paragraph) => void;
}

export interface RendererProps {
  bookId: string;
  book: BookPayload;
  annotations: Annotation[];
  onSelect: (anchor: AnchorInput | null) => void;
  handleRef: React.MutableRefObject<RendererHandle | null>;
  // The book→spine half of the R6 dial: a renderer calls this as the reader
  // scrolls, naming the chunk now at the top of the reading area, so the spine
  // panel can highlight where you are. Optional — a renderer that can't cheaply
  // map its viewport to a chunk simply never calls it.
  onVisibleChunk?: (chunkId: string | null) => void;
}

export const HL_COLORS = ["amber", "rose", "sage", "sky", "violet"];
