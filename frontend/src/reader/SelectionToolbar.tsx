import type { Anchor } from "./anchoring";

const COLORS = ["amber", "rose", "sage", "sky", "violet"];

// The floating toolbar that appears over a live selection. Identical surface
// for every renderer (PRD §8) — for MD it's the only one; PDF/EPUB will mount
// the same component. Highlight applies immediately; Note opens a composer.
export function SelectionToolbar({
  anchor,
  color,
  onColor,
  onHighlight,
  onNote,
}: {
  anchor: Anchor;
  color: string;
  onColor: (c: string) => void;
  onHighlight: () => void;
  onNote: () => void;
}) {
  const top = anchor.rect.top + window.scrollY - 46;
  const left = anchor.rect.left + window.scrollX + anchor.rect.width / 2;
  return (
    <div
      className="sel-toolbar"
      style={{ top, left }}
      onMouseDown={(e) => e.preventDefault() /* keep the selection alive */}
    >
      <div className="swatches">
        {COLORS.map((c) => (
          <button
            key={c}
            className={`swatch ${c === color ? "on" : ""}`}
            style={{ background: `var(--hl-${c})` }}
            title={c}
            onClick={() => onColor(c)}
          />
        ))}
      </div>
      <button className="sel-btn" onClick={onHighlight}>
        Highlight
      </button>
      <button className="sel-btn" onClick={onNote}>
        Note…
      </button>
    </div>
  );
}
