// Parse a book's spine (the canonical converted text) into rend: blocks →
// inline runs, each run carrying the SPINE character offset of its first
// character. Markdown markers (**bold**, _italic_, leading #) are dropped from
// the displayed text but never break the offset map: within a run the display
// text is a contiguous spine substring, so `spineOffset = run.start + i`. That
// invariant is what lets a DOM selection become an exact spine quote and lets a
// stored [spine_start, spine_end) paint back onto exactly the right glyphs.

export interface Run {
  start: number; // spine offset of run.text[0]
  text: string;
  em?: boolean;
  strong?: boolean;
}

export type Block =
  | { kind: "heading"; level: number; start: number; runs: Run[] }
  | { kind: "para"; start: number; runs: Run[] }
  | { kind: "page"; start: number; page: number };

const PAGE_RE = /^<!--\s*page\s+(\d+)\s*-->$/;
const HEADING_RE = /^(#{1,6})\s+(.*\S)\s*$/;

// Inline parse of the raw block substring [base, base+raw.length). Emits runs
// with markers stripped. `**` toggles strong (unambiguous). `_` toggles em only
// when it "flanks" a word (CommonMark-ish): an opener is followed by a
// non-space, a closer is preceded by a non-space — so stray underscores in the
// middle of tokens are left as literal text rather than mangling the run map.
function parseInline(raw: string, base: number): Run[] {
  const runs: Run[] = [];
  let buf = "";
  let bufStart = base;
  let em = false;
  let strong = false;
  let i = 0;

  const flush = () => {
    if (buf) runs.push({ start: bufStart, text: buf, em, strong });
    buf = "";
  };
  const isSpace = (c: string | undefined) => !c || /\s/.test(c);
  const isWord = (c: string | undefined) => !!c && !/\s/.test(c);

  while (i < raw.length) {
    const two = raw.slice(i, i + 2);
    if (two === "**") {
      flush();
      strong = !strong;
      i += 2;
      bufStart = base + i;
      continue;
    }
    if (raw[i] === "_") {
      const prev = raw[i - 1];
      const next = raw[i + 1];
      const canOpen = !em && isSpace(prev) && isWord(next);
      const canClose = em && isWord(prev) && (isSpace(next) || /[.,;:!?)"'’”]/.test(next ?? ""));
      if (canOpen || canClose) {
        flush();
        em = !em;
        i += 1;
        bufStart = base + i;
        continue;
      }
    }
    if (!buf) bufStart = base + i;
    buf += raw[i];
    i += 1;
  }
  flush();
  return runs;
}

export function parseSpine(spine: string): Block[] {
  const blocks: Block[] = [];
  // Split on blank lines while tracking the offset of each block's first char.
  const re = /\n[ \t]*\n/g;
  let idx = 0;
  let match: RegExpExecArray | null;
  const push = (raw: string, at: number) => {
    // trim leading/trailing whitespace but keep the offset of the first kept char
    const lead = raw.length - raw.trimStart().length;
    const body = raw.trim();
    if (!body) return;
    const start = at + lead;
    const pm = PAGE_RE.exec(body);
    if (pm && body.length < 40) {
      blocks.push({ kind: "page", start, page: parseInt(pm[1], 10) });
      return;
    }
    const hm = HEADING_RE.exec(body);
    if (hm && !body.includes("\n")) {
      const hashes = hm[1].length;
      const textStart = start + body.indexOf(hm[2]);
      blocks.push({ kind: "heading", level: hashes, start, runs: parseInline(hm[2], textStart) });
      return;
    }
    // paragraph — collapse internal newlines to spaces for reading, but the run
    // map still points at real spine offsets (a newline is one char, like a space).
    blocks.push({ kind: "para", start, runs: parseInline(body, start) });
  };

  while ((match = re.exec(spine)) !== null) {
    push(spine.slice(idx, match.index), idx);
    idx = match.index + match[0].length;
  }
  push(spine.slice(idx), idx);
  return blocks;
}

// A displayed segment: a run possibly sliced by highlight boundaries. `mark`,
// when set, means these glyphs fall inside a stored annotation's span.
export interface Segment {
  start: number;
  text: string;
  em?: boolean;
  strong?: boolean;
  mark?: { id: string; color: string; approximate: boolean };
}

export interface HighlightSpan {
  id: string;
  spine_start: number;
  spine_end: number;
  color: string;
  approximate: boolean;
}

// Split a block's runs at highlight boundaries so each returned segment is
// wholly inside or outside every highlight. Overlaps resolve to the first
// matching span (creation order); good enough until layered highlights land.
export function segmentsFor(runs: Run[], highlights: HighlightSpan[]): Segment[] {
  const out: Segment[] = [];
  for (const run of runs) {
    const runEnd = run.start + run.text.length;
    // boundaries within this run, from any highlight edge that falls inside it
    const cuts = new Set<number>([0, run.text.length]);
    for (const h of highlights) {
      for (const edge of [h.spine_start, h.spine_end]) {
        const local = edge - run.start;
        if (local > 0 && local < run.text.length) cuts.add(local);
      }
    }
    const sorted = [...cuts].sort((a, b) => a - b);
    for (let k = 0; k < sorted.length - 1; k++) {
      const a = sorted[k];
      const b = sorted[k + 1];
      const segStart = run.start + a;
      const mid = segStart + (b - a) / 2;
      const hit = highlights.find((h) => mid >= h.spine_start && mid < h.spine_end);
      out.push({
        start: segStart,
        text: run.text.slice(a, b),
        em: run.em,
        strong: run.strong,
        mark: hit
          ? { id: hit.id, color: hit.color, approximate: hit.approximate }
          : undefined,
      });
    }
    void runEnd;
  }
  return out;
}
