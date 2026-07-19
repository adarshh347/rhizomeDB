"""Import annotations made elsewhere so they take on the same life as native
ones — every importer is ~a parser feeding the one quote resolver.

  * R8 — embedded PDF annotations: read /Annots (Highlight/Underline/StrikeOut/
    Squiggly), lift the covered text + popup note, resolve against the spine, and
    store with origin='import-pdf'. Idempotent per annotation (content hash), so
    re-importing updates rather than duplicates. The PDF's own quads are kept
    (normalized) so the mark repaints exactly where the reader drew it.
  * R9 — Markdown / Obsidian: parse ==highlights== and blockquotes (+ an optional
    note line) into quotes, resolve, store with origin='import-md'.
  * R10 — EPUB reader sidecars: best-effort adapters for the files other readers
    leave beside a book — KOReader's metadata.*.lua, Calibre's exported
    highlights JSON, or a generic quote+note JSON/CSV. Each is just a parser
    yielding (quote, note) pairs; they resolve like any other, origin
    'import-epub'.

Whatever the source, an unresolvable quote becomes an orphan (never dropped),
ready for the queue (R11).
"""
from __future__ import annotations

import hashlib
import json
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


# --- EPUB reader sidecars (R10) ----------------------------------------------
# Every reader stores highlights its own way, but we only ever need (quote,
# note) — the resolver does the rest. These adapters are deliberately lenient:
# a field we don't recognise is skipped, a quote that won't resolve orphans.
_QUOTE_KEYS = ("quote", "text", "highlight", "highlighted_text", "highlightedText",
               "selected_text", "selectedText", "content", "body")
_NOTE_KEYS = ("note", "notes", "comment", "annotation", "remark")


def _clean(s: str) -> str:
    return " ".join(str(s).split())


def _pick(d: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return _clean(v)
    return ""


def _json_entries(data) -> list:
    """The list of highlight records inside a JSON sidecar, however it's shaped:
    a bare array, or a dict holding one under a familiar key (Calibre's
    'highlights', KOReader's 'annotations', …), or a dict keyed by id."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("highlights", "annotations", "bookmarks", "items", "entries", "notes"):
            v = data.get(key)
            if isinstance(v, list):
                return v
        vals = list(data.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return vals
    return []


def parse_json_sidecar(raw: str) -> list[tuple[str, str]]:
    """Generic + Calibre JSON: pull (quote, note) from each record by key
    aliases. Plain strings are treated as note-less quotes."""
    pairs: list[tuple[str, str]] = []
    for e in _json_entries(json.loads(raw)):
        if isinstance(e, str):
            q = _clean(e)
            if q:
                pairs.append((q, ""))
        elif isinstance(e, dict):
            q = _pick(e, _QUOTE_KEYS)
            if q:
                pairs.append((q, _pick(e, _NOTE_KEYS)))
    return pairs


_LUA_STR = r'"((?:[^"\\]|\\.)*)"'
_LUA_FIELD = re.compile(r'\["(text|note)"\]\s*=\s*' + _LUA_STR, re.DOTALL)
_LUA_TABLE = re.compile(r'\["(annotations|highlights|bookmarks)"\]\s*=\s*\{')


def _lua_unescape(s: str) -> str:
    return (s.replace('\\"', '"').replace("\\n", "\n")
             .replace("\\t", "\t").replace("\\\\", "\\"))


def parse_koreader_lua(text: str) -> list[tuple[str, str]]:
    """KOReader metadata.*.lua: within the highlight table, each ["text"] opens a
    record (the highlighted passage) and a following ["note"] is its annotation.
    Scoping to the table keeps top-level metadata (title, etc.) from posing as a
    quote."""
    m = _LUA_TABLE.search(text)
    region = text[m.end():] if m else text
    pairs: list[tuple[str, str]] = []
    quote: str | None = None
    note = ""

    def flush():
        nonlocal quote, note
        if quote:
            q = _clean(_lua_unescape(quote))
            if q:
                pairs.append((q, _clean(_lua_unescape(note))))
        quote, note = None, ""

    for f in _LUA_FIELD.finditer(region):
        if f.group(1) == "text":
            flush()
            quote = f.group(2)
        else:  # note
            note = f.group(2)
    flush()
    return pairs


def parse_csv_sidecar(raw: str) -> list[tuple[str, str]]:
    """CSV export: quote + note columns picked by header name, else the first
    two columns."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    qi = next((i for i, h in enumerate(header) if h in _QUOTE_KEYS), None)
    ni = next((i for i, h in enumerate(header) if h in _NOTE_KEYS), None)
    body = rows[1:] if qi is not None else rows
    if qi is None:  # headerless: assume quote, note
        qi, ni = 0, (1 if len(header) > 1 else None)
    pairs: list[tuple[str, str]] = []
    for r in body:
        if qi >= len(r):
            continue
        q = _clean(r[qi])
        if q:
            note = _clean(r[ni]) if ni is not None and ni < len(r) else ""
            pairs.append((q, note))
    return pairs


def parse_sidecar(filename: str, raw: bytes) -> tuple[list[tuple[str, str]], str]:
    """Sniff a sidecar's format from its name/contents and parse it. Returns the
    (quote, note) pairs and a short format label."""
    text = raw.decode("utf-8", "replace")
    name = (filename or "").lower()
    if name.endswith(".lua") or _LUA_TABLE.search(text):
        return parse_koreader_lua(text), "koreader"
    head = text.lstrip()[:1]
    if name.endswith(".json") or head in "[{":
        try:
            return parse_json_sidecar(text), "json"
        except (ValueError, TypeError):
            pass
    if name.endswith(".csv") or ("," in text):
        return parse_csv_sidecar(text), "csv"
    # last resort: try the structured parsers anyway
    try:
        return parse_json_sidecar(text), "json"
    except (ValueError, TypeError):
        return parse_csv_sidecar(text), "csv"


def import_epub_sidecar(book_id: str, filename: str, raw: bytes) -> dict:
    """Import a reader sidecar's highlights against one book. Idempotent per
    (quote, note); unresolved quotes orphan (R11)."""
    pairs, fmt = parse_sidecar(filename, raw)
    imported = orphaned = duplicate = 0
    items = []
    for quote, note in pairs:
        res = rs.create_anchored_annotation(
            book_id, quote, note=note, source="import", origin="import-epub",
            content_hash=_hash(book_id, -2, quote, note))
        if res.get("existing"):
            duplicate += 1
        elif res["orphaned"]:
            orphaned += 1
        else:
            imported += 1
        items.append(res["annotation"])
    return {"origin": "import-epub", "format": fmt, "imported": imported,
            "orphaned": orphaned, "duplicate": duplicate, "total": len(items),
            "items": items}
