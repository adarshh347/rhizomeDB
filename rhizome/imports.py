"""Import annotations made elsewhere so they take on the same life as native
ones — every importer is ~a parser feeding the one quote resolver.

  * R8 — embedded PDF annotations: read /Annots (Highlight/Underline/StrikeOut/
    Squiggly), lift the covered text + popup note, resolve against the spine, and
    store with origin='import-pdf'. Idempotent per annotation (content hash), so
    re-importing updates rather than duplicates. The PDF's own quads are kept
    (normalized) so the mark repaints exactly where the reader drew it.
  * R9 — Markdown / Obsidian: parse ==highlights== and blockquotes (+ an optional
    note line) into quotes, resolve, store with origin='import-md'.

Whatever the source, an unresolvable quote becomes an orphan (never dropped),
ready for the queue (R11).
"""
from __future__ import annotations

import hashlib
import re

from . import reader_service as rs, sources

_TEXT_MARKUP = {"Highlight", "Underline", "StrikeOut", "Squiggly"}

# our highlight palette in RGB (0..1), for mapping a PDF annot's colour
_PALETTE = {
    "amber": (0.957, 0.851, 0.545),
    "rose": (0.949, 0.722, 0.690),
    "sage": (0.737, 0.839, 0.675),
    "sky": (0.663, 0.796, 0.878),
    "violet": (0.792, 0.737, 0.878),
}


def _hash(book_id: str, page_no: int, quote: str, note: str) -> str:
    return hashlib.sha1(f"{book_id}|{page_no}|{quote}|{note}".encode()).hexdigest()[:16]


def _map_color(annot) -> str:
    colors = annot.colors or {}
    rgb = colors.get("stroke") or colors.get("fill")
    if not rgb or len(rgb) < 3:
        return "amber"
    r, g, b = rgb[:3]
    return min(_PALETTE, key=lambda k: sum((c - v) ** 2 for c, v in zip(_PALETTE[k], (r, g, b))))


def _quads(annot):
    import pymupdf

    v = annot.vertices or []
    out = []
    for i in range(0, len(v), 4):
        pts = v[i:i + 4]
        if len(pts) == 4:
            out.append(pymupdf.Quad(*pts))
    return out


def _text_in_quads(page, quads) -> str:
    """The words whose centre falls inside the highlight quads, in reading order
    — tighter than get_textbox(), which greedily grabs neighbouring lines."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, wordno)
    picked = []
    for q in quads:
        r = q.rect
        for x0, y0, x1, y1, w, *_ in words:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 1 <= cy <= r.y1 + 1:
                picked.append((round(y0, 1), x0, w))
    picked.sort()
    return " ".join(w for _, _, w in picked)


def _normalized_quads(page, quads) -> list[dict]:
    pw, ph = page.rect.width, page.rect.height
    if not pw or not ph:
        return []
    return [{"x": q.rect.x0 / pw, "y": q.rect.y0 / ph,
             "w": q.rect.width / pw, "h": q.rect.height / ph} for q in quads]


def import_pdf_annotations(book_id: str) -> dict:
    """Import the embedded annotations from a book's PDF. Idempotent."""
    import pymupdf

    info = sources.source_info(book_id)
    if info["renderer"] != "pdf" or not info["native_available"]:
        raise FileNotFoundError(f"no PDF file available for {book_id!r}")

    doc = pymupdf.open(info["path"])
    imported = orphaned = duplicate = 0
    items = []
    try:
        for pno in range(doc.page_count):
            page = doc[pno]
            for annot in page.annots() or []:
                if annot.type[1] not in _TEXT_MARKUP:
                    continue
                quads = _quads(annot)
                quote = _text_in_quads(page, quads).strip()
                if not quote:
                    continue
                note = (annot.info.get("content") or "").strip()
                locator = {"page": pno, "quads": _normalized_quads(page, quads)}
                res = rs.create_anchored_annotation(
                    book_id, quote, note=note, color=_map_color(annot),
                    source="import", origin="import-pdf", locator=locator,
                    content_hash=_hash(book_id, pno, quote, note))
                if res.get("existing"):
                    duplicate += 1
                elif res["orphaned"]:
                    orphaned += 1
                else:
                    imported += 1
                items.append(res["annotation"])
    finally:
        doc.close()
    return {"origin": "import-pdf", "imported": imported, "orphaned": orphaned,
            "duplicate": duplicate, "total": len(items), "items": items}


# --- Markdown / Obsidian -----------------------------------------------------
_HIGHLIGHT_RE = re.compile(r"==(.+?)==", re.DOTALL)


def parse_markdown_quotes(text: str) -> list[tuple[str, str]]:
    """(quote, note) pairs from ==highlights== and `>` blockquotes.

    A blockquote's quote is the joined `>` lines; a single non-blank, non-quote
    line immediately after it is taken as the note.
    """
    pairs: list[tuple[str, str]] = []
    for m in _HIGHLIGHT_RE.finditer(text):
        q = " ".join(m.group(1).split())
        if q:
            pairs.append((q, ""))

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith(">"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                block.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            quote = " ".join(" ".join(block).split())
            note = ""
            if i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", ">")):
                note = lines[i].strip().lstrip("—-").strip()
                i += 1
            if quote:
                pairs.append((quote, note))
        else:
            i += 1
    return pairs


def import_markdown(book_id: str, text: str) -> dict:
    """Import quotes parsed from markdown notes against one book. Idempotent."""
    imported = orphaned = duplicate = 0
    items = []
    for quote, note in parse_markdown_quotes(text):
        res = rs.create_anchored_annotation(
            book_id, quote, note=note, source="import", origin="import-md",
            content_hash=_hash(book_id, -1, quote, note))
        if res.get("existing"):
            duplicate += 1
        elif res["orphaned"]:
            orphaned += 1
        else:
            imported += 1
        items.append(res["annotation"])
    return {"origin": "import-md", "imported": imported, "orphaned": orphaned,
            "duplicate": duplicate, "total": len(items), "items": items}
