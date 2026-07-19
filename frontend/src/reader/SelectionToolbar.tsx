import { type AnchorInput, HL_COLORS } from "./renderer";

// The floating toolbar over a live selection — identical for every renderer
// (PRD §8). Positioned `fixed` from the selection's viewport rect, so it works
// the same over the MD surface, the PDF text layer, and the EPUB iframe.
export function SelectionToolbar({
  anchor,
  color,
  onColor,
  onHighlight,
  onNote,
}: {
  anchor: AnchorInput;
  color: string;
  onColor: (c: string) => void;
  onHighlight: () => void;
  onNote: () => void;
}) {
  const top = Math.max(8, anchor.rect.top - 46);
  const left = anchor.rect.left + anchor.rect.width / 2;
  return (
    <div
      className="sel-toolbar"
      style={{ position: "fixed", top, left }}
      onMouseDown={(e) => e.preventDefault() /* keep the selection alive */}
    >
      <div className="swatches">
        {HL_COLORS.map((c) => (
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
