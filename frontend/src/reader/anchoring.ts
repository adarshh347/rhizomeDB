// Turn a live DOM selection into an exact spine anchor. Every displayed leaf
// carries data-s (the spine offset of its first glyph) and holds a single text
// node, so a (textNode, offset) endpoint maps to `+dataset.s + offset`. The
// quote/prefix/suffix are then sliced straight from the spine string — never
// from selection.toString() — so what we send the resolver is a literal spine
// substring and the exact-match path always wins.

const CONTEXT = 32; // chars of prefix/suffix — enough to disambiguate repeats

export interface Anchor {
  quote: string;
  prefix: string;
  suffix: string;
  start: number;
  end: number;
  rect: DOMRect;
}

function pointToSpine(node: Node, offset: number, root: HTMLElement): number | null {
  if (!root.contains(node)) return null;
  if (node.nodeType === Node.TEXT_NODE) {
    const host = node.parentElement?.closest<HTMLElement>("[data-s]");
    if (host && host.dataset.s) return parseInt(host.dataset.s, 10) + offset;
    return null;
  }
  // Element endpoint: descend to the child at `offset` (or the last one).
  const el = node as HTMLElement;
  const child = el.childNodes[Math.min(offset, el.childNodes.length - 1)];
  if (child) {
    const host = (child.nodeType === Node.TEXT_NODE ? child.parentElement : (child as HTMLElement))
      ?.closest?.<HTMLElement>("[data-s]");
    if (host && host.dataset.s) {
      const base = parseInt(host.dataset.s, 10);
      // offset==childCount means "after the last glyph" of that host
      return offset >= el.childNodes.length ? base + (host.textContent?.length ?? 0) : base;
    }
  }
  const self = el.closest<HTMLElement>("[data-s]");
  if (self && self.dataset.s) return parseInt(self.dataset.s, 10);
  return null;
}

export function selectionToAnchor(spine: string, root: HTMLElement): Anchor | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);

  let a = pointToSpine(range.startContainer, range.startOffset, root);
  let b = pointToSpine(range.endContainer, range.endOffset, root);
  if (a === null || b === null) return null;
  if (a > b) [a, b] = [b, a];
  if (b - a < 1) return null;

  const quote = spine.slice(a, b);
  if (!quote.trim()) return null;

  return {
    quote,
    prefix: spine.slice(Math.max(0, a - CONTEXT), a),
    suffix: spine.slice(b, b + CONTEXT),
    start: a,
    end: b,
    rect: range.getBoundingClientRect(),
  };
}
