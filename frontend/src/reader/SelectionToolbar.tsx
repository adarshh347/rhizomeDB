import { flip, offset, shift, useFloating } from "@floating-ui/react";
import { useLayoutEffect, useMemo } from "react";

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
  const virtualReference = useMemo(
    () => ({ getBoundingClientRect: () => anchor.rect }),
    [anchor.rect],
  );
  const { refs, floatingStyles, placement } = useFloating({
    strategy: "fixed",
    placement: "top",
    middleware: [offset(8), flip({ padding: 8 }), shift({ padding: 8 })],
  });

  useLayoutEffect(() => {
    refs.setReference(virtualReference);
  }, [refs, virtualReference]);

  return (
    <div
      className="sel-toolbar"
      ref={refs.setFloating}
      style={floatingStyles}
      data-placement={placement}
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
