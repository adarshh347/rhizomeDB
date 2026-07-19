import { useEffect } from "react";

// The book→spine half of the R6 dial. As the reader scrolls, report which chunk
// sits at the top of the reading area so the spine panel can highlight where you
// are (locateChunk is the other direction: spine→book).
//
// Two deliberate choices keep this cheap and format-agnostic:
//  - a single `elementFromPoint` probe at a trigger line just under the reader
//    bar, so the cost is O(1) per frame no matter how long the book is; and
//  - a capture-phase scroll listener on window, so it fires whether the scroll
//    lives on the window (MD) or inside a renderer's own overflow container
//    (PDF/EPUB) — scroll events don't bubble, but they do run capture-first.
//
// `probe` returns the current chunk id (or null when the line lands in a gap);
// updates are coalesced to one animation frame and only forwarded on change.
export function useScrollSpy(
  enabled: boolean,
  probe: () => string | null,
  onChunk: (id: string | null) => void,
) {
  useEffect(() => {
    if (!enabled) return;
    let raf = 0;
    let last: string | null | undefined;
    const run = () => {
      raf = 0;
      const id = probe();
      if (id !== last) {
        last = id;
        onChunk(id);
      }
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(run);
    };
    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    schedule(); // settle an initial value once content is up
    return () => {
      window.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [enabled, probe, onChunk]);
}
