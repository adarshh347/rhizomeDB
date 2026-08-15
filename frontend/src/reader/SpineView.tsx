import { useMemo } from "react";

import { type Block, type HighlightSpan, type Segment, segmentsFor } from "./spine";

// Render the parsed spine. Every leaf span carries data-s so selection maps
// back to exact spine offsets; marked segments render as <mark> tinted by the
// annotation colour, with a dotted underline when the anchor was fuzzy
// ("approximate", per the honesty requirement in the PRD §8).
function renderSegment(seg: Segment, key: number) {
  const style = seg.mark
    ? { background: `var(--hl-${seg.mark.color})` }
    : undefined;
  const cls = [
    seg.mark ? "hl" : "",
    seg.mark?.approximate ? "approx" : "",
    seg.mark?.hasNote ? "has-note" : "",
    seg.mark?.startsHere ? "mark-start" : "",
    seg.mark?.endsHere ? "mark-end" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const Tag = seg.mark ? "mark" : "span";
  let inner: React.ReactNode = seg.text;
  if (seg.strong) inner = <strong>{inner}</strong>;
  if (seg.em) inner = <em>{inner}</em>;
  return (
    <Tag
      key={key}
      data-s={seg.start}
      className={cls || undefined}
      style={style}
      data-aid={seg.mark?.id}
      data-honesty={seg.mark?.startsHere && seg.mark.approximate ? "approximate" : undefined}
      title={seg.mark?.startsHere && seg.mark.note ? `Note: ${seg.mark.note}` : undefined}
    >
      {inner}
    </Tag>
  );
}

// A converter's figure-omission marker ("⇒ picture [W x H] intentionally
// omitted ⇐") is machine residue, not prose — it gets a quiet caption class.
// Only the paragraph's className changes; the runs (and their data-s offsets)
// render exactly as for any paragraph, so anchoring is untouched.
const FIGURE_RE = /^(?:⇒|==>)\s*picture\b.*intentionally omitted\s*(?:⇐|<==)$/;

function BlockView({
  block,
  highlights,
  nextStart,
}: {
  block: Block;
  highlights: HighlightSpan[];
  nextStart: number;
}) {
  if (block.kind === "page") {
    return (
      <div className="spine-page" data-s={block.start} aria-hidden>
        <span>page {block.page}</span>
      </div>
    );
  }
  const segs = segmentsFor(block.runs, highlights, nextStart);
  const children = segs.map(renderSegment);
  if (block.kind === "heading") {
    const H = `h${Math.min(block.level + 1, 6)}` as keyof React.JSX.IntrinsicElements;
    return <H className={`spine-h spine-h${block.level}`}>{children}</H>;
  }
  const text = block.runs.map((r) => r.text).join("").trim();
  const figure = FIGURE_RE.test(text);
  return <p className={`spine-p${figure ? " spine-figure" : ""}`}>{children}</p>;
}

export function SpineView({
  blocks,
  highlights,
}: {
  blocks: Block[];
  highlights: HighlightSpan[];
}) {
  // Re-segment only when the highlight set changes (not on every render).
  const painted = useMemo(() => {
    // spine offset of the first text of the next text-bearing block, so a mark
    // that continues into it does not close early (U7)
    const nexts: number[] = new Array(blocks.length).fill(Infinity);
    let next = Infinity;
    for (let i = blocks.length - 1; i >= 0; i--) {
      nexts[i] = next;
      const b = blocks[i];
      if (b.kind !== "page" && b.runs.length) next = b.runs[0].start;
    }
    return blocks.map((b, i) => (
      <BlockView key={i} block={b} highlights={highlights} nextStart={nexts[i]} />
    ));
  }, [blocks, highlights]);
  return <>{painted}</>;
}
