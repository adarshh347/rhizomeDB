// Mirrors the shapes rhizome/api.py returns. Kept intentionally small — only
// what the reader consumes — and additive, matching the backend convention that
// selector positions/locators are caches while the quote is authoritative.

export interface BookSummary {
  book_id: string;
  title: string;
  author: string;
  year: number | null;
  n_chunks: number;
  n_annotations: number;
}

export interface TocEntry {
  heading: string;
  id: string;
  page: number | null;
}

export interface Paragraph {
  id: string; // chunk id — the annotation target/join key
  heading: string | null;
  page: number | null;
  character: string | null;
  character_desc: string | null;
  spine_start: number | null;
  spine_end: number | null;
  text: string;
}

export interface BookPayload {
  book_id: string;
  title: string;
  author: string;
  year: number | null;
  n_chunks: number;
  toc: TocEntry[];
  paragraphs: Paragraph[];
}

export interface SpinePayload {
  book_id: string;
  length: number;
  text: string;
}

export interface TextQuoteSelector {
  quote: string;
  prefix: string;
  suffix: string;
}
export interface TextPositionSelector {
  spine_start: number;
  spine_end: number;
}
export interface SelectorBundle {
  text_quote: TextQuoteSelector;
  text_position?: TextPositionSelector;
  locator?: Record<string, unknown>;
  approximate?: boolean;
  confidence?: number;
}

export interface ChunkHit {
  chunk_id: string;
  overlap: number;
  primary: boolean;
}

export interface ResolveResult {
  resolved: boolean;
  orphaned: boolean;
  selector?: SelectorBundle;
  chunks?: ChunkHit[];
}

export interface Annotation {
  id: string;
  target: string;
  kind: "highlight" | "note";
  quote: string;
  note: string;
  color: string;
  source: string;
  created: string;
  book_id?: string;
  origin?: string;
  orphaned?: boolean;
  selector?: SelectorBundle;
  chunk_ids?: string[];
  primary_chunk_id?: string;
}

export interface CreateAnnotationBody {
  book_id: string;
  quote: string;
  prefix?: string;
  suffix?: string;
  kind?: "highlight" | "note";
  note?: string;
  color?: string;
  source?: string;
  origin?: string;
  locator?: Record<string, unknown>;
}

export interface CreateAnnotationResult {
  annotation: Annotation;
  chunks: ChunkHit[];
  orphaned: boolean;
}
