"""Ingest an uploaded book so it reads exactly like a curated one.

Save the file under ``books/uploads/``, convert it to a spine (the same
pymupdf/pymupdf4llm path the corpus pipeline uses; MOBI via the ``mobi`` lib,
extracted to EPUB so it also renders natively), chunk it with spine offsets, and
append to the index. The book is browsable + readable the moment this returns;
it only joins the *vector* index later, when embeddings are (re)built — reading
needs chunks.jsonl, not embeddings.

Calibre's ``ebook-convert`` is the PRD's preferred MOBI path but is optional; we
degrade to the pure-Python ``mobi`` extractor when it isn't installed.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil

from . import catalog as catalog_mod, chunk as chunk_mod, config, sources

ALLOWED_EXT = {".pdf", ".epub", ".mobi"}


def _upload_dir() -> pathlib.Path:
    return config.ROOT / "books" / "uploads"


def _converted_upload_dir() -> pathlib.Path:
    return config.CONVERTED_DIR / "uploads"


def _slug(filename: str) -> str:
    stem = pathlib.Path(filename).stem
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return s or "book"


def _unique_book_id(slug: str) -> str:
    """A book id not already used by any converted spine."""
    existing = {p.stem for p in config.CONVERTED_DIR.rglob("*.md")}
    if slug not in existing:
        return slug
    i = 2
    while f"{slug}-{i}" in existing:
        i += 1
    return f"{slug}-{i}"


def _header(source_file: str, pages: int) -> str:
    return f"---\nsource_file: {source_file}\npages: {pages}\n---\n\n"


def _convert_pdf_epub(path: pathlib.Path) -> tuple[str, int]:
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(path)
    pages = doc.page_count
    doc.close()
    md = pymupdf4llm.to_markdown(str(path), show_progress=False)
    return md, pages


def _convert_mobi(path: pathlib.Path, dest_epub: pathlib.Path) -> tuple[str, int, str | None]:
    """Extract a MOBI. When it yields an EPUB, keep it (as ``dest_epub``) so the
    book renders natively; otherwise fall back to text-only (spine, no native)."""
    import mobi
    import pymupdf
    import pymupdf4llm

    tmpdir, extracted = mobi.extract(str(path))
    try:
        if pathlib.Path(extracted).suffix.lower() == ".epub":
            shutil.copyfile(extracted, dest_epub)
            doc = pymupdf.open(extracted)
            pages = doc.page_count
            doc.close()
            md = pymupdf4llm.to_markdown(extracted, show_progress=False)
            return md, pages, dest_epub.name
        doc = pymupdf.open(extracted)  # older MOBI → HTML; text-only spine
        parts = [doc[i].get_text("text") for i in range(doc.page_count)]
        pages = doc.page_count
        doc.close()
        return "\n\n".join(parts), pages, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _derive_title(book_id: str, md: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*$", md, re.MULTILINE)
    if m and 2 < len(m.group(1).strip()) < 90:
        return m.group(1).strip()
    return book_id.replace("-", " ").title()


def _append_chunks(book_id: str, rows: list[dict]) -> None:
    """Append this book's chunks to the index (replacing any prior rows for it)."""
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if config.CHUNKS_PATH.exists():
        with config.CHUNKS_PATH.open(encoding="utf-8") as f:
            existing = [json.loads(line) for line in f if line.strip()]
    kept = [c for c in existing if c.get("book_id") != book_id]
    with config.CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for c in kept + rows:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def ingest(filename: str, data: bytes) -> dict:
    """Convert + index an uploaded book. Returns its library summary.

    Raises ValueError for an unsupported/empty file; conversion errors bubble up.
    """
    ext = pathlib.Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"unsupported format {ext or '(none)'!r} — allowed: pdf, epub, mobi")
    if not data:
        raise ValueError("empty file")

    upload_dir = _upload_dir()
    converted_dir = _converted_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    converted_dir.mkdir(parents=True, exist_ok=True)

    book_id = _unique_book_id(_slug(filename))
    saved = upload_dir / f"{book_id}{ext}"
    saved.write_bytes(data)

    if ext == ".mobi":
        md, pages, epub_name = _convert_mobi(saved, upload_dir / f"{book_id}.epub")
        source_file = epub_name or saved.name
    else:
        md, pages = _convert_pdf_epub(saved)
        source_file = saved.name

    if not md.strip():
        saved.unlink(missing_ok=True)
        raise ValueError("no text could be extracted from this file")

    md_path = converted_dir / f"{book_id}.md"
    md_path.write_text(_header(source_file, pages) + md, encoding="utf-8")

    title = _derive_title(book_id, md)
    meta = {"author": "", "title": title, "year": None, "collection": "uploads"}
    cat = catalog_mod.load_catalog()
    cat[book_id] = meta
    catalog_mod.save_catalog(cat)

    rows = chunk_mod.chunk_book(md_path, book_id, meta)
    _append_chunks(book_id, rows)

    # Drop the reader's cached corpus so the new book appears without a restart.
    from . import reader_service
    reader_service._READER_CHUNKS = None
    reader_service._WORD_COUNTS.pop(book_id, None)

    return {"book_id": book_id, "title": title, "author": "",
            "n_chunks": len(rows), "formats": sources.formats_for(book_id)}
