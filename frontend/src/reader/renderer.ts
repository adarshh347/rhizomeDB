// The contract every renderer (MD / PDF / EPUB) satisfies so the reader shell,
// the selection toolbar, the notes rail and the resolve→create→paint flow are
// shared. A renderer's only format-specific jobs are: draw the book, turn a
// selection into an AnchorInput, and paint stored annotations back.
import type { Annotation, BookPayload } from "../api/types";

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

export interface RendererProps {
  bookId: string;
  book: BookPayload;
  annotations: Annotation[];
  onSelect: (anchor: AnchorInput | null) => void;
  // Renderers register a jump handler here so the rail can scroll to a mark.
  jumpRef: React.MutableRefObject<((ann: Annotation) => void) | null>;
}

export const HL_COLORS = ["amber", "rose", "sage", "sky", "violet"];
