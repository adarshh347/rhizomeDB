"""Chunk converted Markdown into passages with provenance metadata.

Splits on blank lines into paragraphs, then accumulates paragraphs into chunks
of ~CHUNK_TARGET_WORDS with a small overlap so an argument's flow isn't cut
mid-thought. Tracks the nearest Markdown heading and (for the scanned books
that carry `<!-- page N -->` markers) the page number, so connections can be
cited precisely later.
"""
import json
import re

from . import config, catalog

PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _wordcount(s: str) -> int:
    return len(s.split())


def _attach_spine_offsets(chunks: list[dict], spine: str) -> None:
    """Add character spans without changing chunk ids or text.

    Chunks overlap, so the next search starts just after the previous chunk's
    start (not its end).  Page markers may sit between paragraphs in the
    converted Markdown; the span deliberately covers those source characters.
    """
    cursor = 0
    for chunk in chunks:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", chunk["text"])
                      if p.strip()]
        if not paragraphs:
            continue
        start = spine.find(paragraphs[0], cursor)
        if start < 0:
            start = spine.find(paragraphs[0])
        if start < 0:
            continue
        end_start = spine.find(paragraphs[-1], start)
        if end_start < 0:
            continue
        chunk["spine_start"] = start
        chunk["spine_end"] = end_start + len(paragraphs[-1])
        cursor = start + 1


# --- chunk hygiene: drop front/back-matter & bibliographic apparatus --------
_FRONTMATTER_SIGNALS = (
    "no part of this book", "all rights reserved", "library of congress",
    "cataloging-in-publication", "manufactured in the united states",
    "printed in the united states", "university press", "isbn",
    "p. cm", "intentionally omitted", "this book is a publication",
    "permission in writing from the publisher",
)


def _prose_ratio(s: str) -> float:
    """Fraction of tokens that look like words (>=2 letters, no digits).
    Low for indexes, bibliographies, citation-only footnote runs, title pages."""
    toks = s.split()
    if not toks:
        return 0.0
    wordlike = sum(
        1 for w in toks
        if sum(ch.isalpha() for ch in w) >= 2 and not any(ch.isdigit() for ch in w)
    )
    return wordlike / len(toks)


def _is_boilerplate(text: str) -> bool:
    """Conservative filter for non-prose chunks. Real philosophical prose
    survives; copyright/title pages, catalog blocks, index/bibliography and
    citation-only footnote runs are dropped. Tuned on the Heidegger corpus."""
    tl = text.lower()
    hits = sum(sig in tl for sig in _FRONTMATTER_SIGNALS)
    if "intentionally omitted" in tl and len(text) < 600:
        return True
    if hits >= 2:
        return True
    pr = _prose_ratio(text)
    if hits >= 1 and pr < 0.65:
        return True
    if pr < 0.50:        # mostly numbers/dates/names -> apparatus, not argument
        return True
    return False


def _iter_blocks(text: str):
    """Yield (kind, payload) where kind is 'page', 'heading', or 'para'."""
    for raw in re.split(r"\n\s*\n", text):
        block = raw.strip()
        if not block:
            continue
        pm = PAGE_RE.search(block)
        if pm and len(block) < 40:        # a lone page marker
            yield ("page", int(pm.group(1)))
            continue
        # strip inline page markers from prose, but remember the page
        page_here = None
        if pm:
            page_here = int(pm.group(1))
            block = PAGE_RE.sub("", block).strip()
        hm = HEADING_RE.match(block)
        if hm and "\n" not in block:
            yield ("heading", hm.group(1))
            continue
        if page_here is not None:
            yield ("page", page_here)
        if block:
            yield ("para", block)


def chunk_book(md_path, book_id: str, meta: dict) -> list[dict]:
    text = _strip_frontmatter(md_path.read_text(encoding="utf-8"))
    chunks: list[dict] = []
    buf: list[str] = []
    buf_words = 0
    cur_page = None
    cur_heading = None
    start_page = None
    dropped = 0

    def flush():
        nonlocal buf, buf_words, start_page, dropped
        if buf_words >= config.CHUNK_MIN_WORDS:
            body = "\n\n".join(buf).strip()
            if _is_boilerplate(body):
                dropped += 1
            else:
                chunks.append({
                    "id": f"{book_id}#{len(chunks):04d}",
                    "book_id": book_id,
                    "author": meta.get("author", ""),
                    "title": meta.get("title", ""),
                    "heading": cur_heading,
                    "page": start_page,
                    "text": body,
                })
        # carry an overlap tail into the next chunk
        if buf and config.CHUNK_OVERLAP_WORDS:
            tail, tw = [], 0
            for para in reversed(buf):
                tail.insert(0, para)
                tw += _wordcount(para)
                if tw >= config.CHUNK_OVERLAP_WORDS:
                    break
            buf = tail
            buf_words = sum(_wordcount(p) for p in buf)
        else:
            buf, buf_words = [], 0
        start_page = cur_page

    for kind, payload in _iter_blocks(text):
        if kind == "page":
            cur_page = payload
            if start_page is None:
                start_page = payload
        elif kind == "heading":
            if buf_words >= config.CHUNK_TARGET_WORDS // 2:
                flush()
            cur_heading = payload
        else:  # para
            if start_page is None:
                start_page = cur_page
            buf.append(payload)
            buf_words += _wordcount(payload)
            if buf_words >= config.CHUNK_TARGET_WORDS:
                flush()
    # final
    if buf_words >= config.CHUNK_MIN_WORDS:
        body = "\n\n".join(buf).strip()
        if _is_boilerplate(body):
            dropped += 1
        else:
            chunks.append({
                "id": f"{book_id}#{len(chunks):04d}", "book_id": book_id,
                "author": meta.get("author", ""), "title": meta.get("title", ""),
                "heading": cur_heading, "page": start_page, "text": body,
            })
    _attach_spine_offsets(chunks, text)
    chunk_book.last_dropped = dropped
    return chunks


def build_chunks() -> list[dict]:
    cat = catalog.load_catalog()
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    all_chunks: list[dict] = []
    for md in sorted(config.CONVERTED_DIR.rglob("*.md")):
        book_id = md.stem
        meta = cat.get(book_id, {"author": "", "title": book_id})
        bc = chunk_book(md, book_id, meta)
        all_chunks.extend(bc)
        dropped = getattr(chunk_book, "last_dropped", 0)
        note = f"  (+{dropped} boilerplate dropped)" if dropped else ""
        print(f"  {book_id:42s} {len(bc):5d} chunks{note}")
    with config.CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Total: {len(all_chunks)} chunks -> {config.CHUNKS_PATH}")
    return all_chunks


def backfill_spine_offsets() -> dict:
    """Add/recompute R1 fields on an existing index without touching ids/order."""
    chunks = load_chunks()
    by_book: dict[str, list[dict]] = {}
    for record in chunks:
        by_book.setdefault(record["book_id"], []).append(record)
    updated = missing = 0
    for book_id, records in by_book.items():
        paths = list(config.CONVERTED_DIR.rglob(f"{book_id}.md"))
        if len(paths) != 1:
            missing += len(records)
            continue
        spine = _strip_frontmatter(paths[0].read_text(encoding="utf-8"))
        before = sum("spine_start" in r for r in records)
        _attach_spine_offsets(records, spine)
        updated += sum("spine_start" in r for r in records) - before
        missing += sum("spine_start" not in r for r in records)
    with config.CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for record in chunks:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"total": len(chunks), "updated": updated, "missing": missing}


def load_chunks() -> list[dict]:
    with config.CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]
