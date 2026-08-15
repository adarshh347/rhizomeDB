// Mirrors the shapes rhizome/api.py returns. Kept intentionally small — only
// what the reader consumes — and additive, matching the backend convention that
// selector positions/locators are caches while the quote is authoritative.

export interface BookFormat {
  format: "pdf" | "epub" | "md";
  native: boolean;
  available: boolean;
  source_file: string | null;
}

export interface BookSummary {
  book_id: string;
  title: string;
  author: string;
  year: number | null;
  n_chunks: number;
  n_annotations: number;
  formats: BookFormat[];
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
  paragraphs: Paragraph[];
  formats: BookFormat[];
  default_format: string;
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

// --- connection engine (SSE /explore) --------------------------------------
export interface ExploreSeed {
  label: string;
  text: string;
  author: string | null;
  book_id: string | null;
  chunk_id?: string | null;
  embed_key?: string;
  embed_label: string;
}

// One pick from any retrieval engine — the ITEM shape shared by /connect,
// /connect/compare and the SSE 'candidates' event. The first block is always
// present; the extras appear only when the engine that produced the pick has
// something to disclose (a walk's hop, a mark's note, shared concepts…).
export interface ConnectItem {
  index: number;
  chunk_id: string;
  author: string;
  title: string;
  page: number | null;
  text: string;
  similarity: number | null;
  direct_dissimilarity: number | null;
  structural_similarity: number | null;
  rank: number | null;
  corpus_size: number;
  score: number | null;
  path: string;
  why: string;
  // engine-specific extras
  hop?: number;
  from_id?: string;
  hop_similarity?: number;
  annotation_id?: string;
  note?: string;
  quote?: string;
  kind?: string;
  color?: string;
  concepts?: string[];
  activation?: number;
  gap?: number;
  abstraction?: string;
  dense_rank?: number;
  lexical_rank?: number;
  distance?: number;
  heading?: string;
  covers?: number;
  paths?: string[];
  contributions?: Record<string, number>;
}

// The SSE stream's candidates are ITEMs; the old name stays for callers.
export type ExploreCandidate = ConnectItem;

export interface EngineParam {
  type: string;
  default: unknown;
  help: string;
}

export interface EngineCard {
  key: string;
  label: string;
  blurb: string;
  needs: string[];
  params: Record<string, EngineParam>;
  ready: boolean;
  reason: string;
}

export interface EngineRef {
  key: string;
  label: string;
  blurb: string;
}

export interface ConnectResponse {
  engine: EngineRef;
  seed: ExploreSeed;
  items: ConnectItem[];
  params: Record<string, unknown>;
  ms: number;
  note: string | null;
}

export interface CompareResult {
  key: string;
  label: string;
  items: ConnectItem[];
  ms: number;
  error?: string;
}

export interface CompareResponse {
  seed: ExploreSeed;
  results: CompareResult[];
  overlap: { keys: string[]; matrix: number[][] };
}

export interface EngineEvalRow {
  key: string;
  label: string;
  ready: boolean;
  n_seeds: number;
  mean_k: number;
  empty_rate: number;
  mean_rank_pct: number;
  median_rank: number;
  ild: number;
  book_spread: number;
  cross_book_rate: number;
  noise_fp_rate: number;
  ms_per_seed: number;
  bridge_recall: number | null;
  n_bridges: number;
}

export interface EngineEvalReport {
  built: string;
  embed_key: string;
  k: number;
  n_seeds: number;
  n_noise: number;
  engines: EngineEvalRow[];
}

export interface ExploreVerdict {
  index: number;
  connected: boolean;
  genuine: boolean;
  forced_risk: string;
  bridge_concept: string;
  articulation: string;
  confidence: number;
}
