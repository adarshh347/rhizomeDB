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
    >
      {inner}
    </Tag>
  );
}

function BlockView({ block, highlights }: { block: Block; highlights: HighlightSpan[] }) {
  if (block.kind === "page") {
    return (
      <div className="spine-page" data-s={block.start} aria-hidden>
        <span>page {block.page}</span>
      </div>
    );
  }
  const segs = segmentsFor(block.runs, highlights);
  const children = segs.map(renderSegment);
  if (block.kind === "heading") {
    const H = `h${Math.min(block.level + 1, 6)}` as keyof React.JSX.IntrinsicElements;
    return <H className={`spine-h spine-h${block.level}`}>{children}</H>;
  }
  return <p className="spine-p">{children}</p>;
}

export function SpineView({
  blocks,
  highlights,
}: {
  blocks: Block[];
  highlights: HighlightSpan[];
}) {
  // Re-segment only when the highlight set changes (not on every render).
  const painted = useMemo(
    () => blocks.map((b, i) => <BlockView key={i} block={b} highlights={highlights} />),
    [blocks, highlights],
  );
  return <>{painted}</>;
}
