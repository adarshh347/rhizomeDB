"""Which native formats a book can be *rendered* in, and where the file is.

The spine (converted Markdown) is always renderable — it is the substrate the
whole anchoring layer resolves against. A book can *additionally* be rendered
in its original format (PDF via PDF.js, EPUB via epub.js) when the source file
is present under ``books/``. We learn the original format from the provenance
header the conversion step writes into every spine (``source_file:``), so a
book advertises "pdf" even before its (gitignored, R2-backed) file is fetched —
the UI can then say the format exists but needs the file.

MOBI is treated as EPUB for rendering: per the PRD it is converted to EPUB
first, so a rendered MOBI book is served whatever EPUB the conversion produced.
"""
from __future__ import annotations

import re

from . import config

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SOURCE_RE = re.compile(r"^source_file:\s*(.+?)\s*$", re.MULTILINE)

# original extension -> the renderer that draws it natively
_RENDERER_FOR_EXT = {".pdf": "pdf", ".epub": "epub", ".mobi": "epub"}
_MEDIA_TYPE = {"pdf": "application/pdf", "epub": "application/epub+zip"}


def _spine_path(book_id: str):
    matches = list(config.CONVERTED_DIR.rglob(f"{book_id}.md"))
    return matches[0] if len(matches) == 1 else None


def _source_filename(book_id: str) -> str | None:
    """The original filename recorded in the spine's provenance header."""
    path = _spine_path(book_id)
    if path is None:
        return None
    fm = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not fm:
        return None
    m = _SOURCE_RE.search(fm.group(1))
    return m.group(1).strip() if m else None


def _books_root():
    return config.ROOT / "books"


def _locate_file(source_file: str):
    """Find the real source file under books/ (any collection subdir)."""
    root = _books_root()
    if not root.exists():
        return None
    exact = list(root.rglob(source_file))
    if exact:
        return exact[0]
    return None


def source_info(book_id: str) -> dict:
    """{source_file, renderer, native_available, path} for one book.

    ``renderer`` is the native renderer id (pdf|epub) or None if the original
    format is unknown/unsupported. ``native_available`` is True only when the
    file is actually present to serve.
    """
    source_file = _source_filename(book_id)
    if not source_file:
        return {"source_file": None, "renderer": None,
                "native_available": False, "path": None}
    ext = "." + source_file.rsplit(".", 1)[-1].lower() if "." in source_file else ""
    renderer = _RENDERER_FOR_EXT.get(ext)
    path = _locate_file(source_file) if renderer else None
    return {"source_file": source_file, "renderer": renderer,
            "native_available": path is not None, "path": path}


def formats_for(book_id: str) -> list[dict]:
    """The renderable formats for a book, most-native first.

    ``md`` is always present (it renders off the spine). The native format is
    marked ``available`` only when its file can be served; otherwise the UI can
    still list it and explain the file needs fetching.
    """
    info = source_info(book_id)
    formats = []
    if info["renderer"]:
        formats.append({"format": info["renderer"], "native": True,
                        "available": info["native_available"],
                        "source_file": info["source_file"]})
    formats.append({"format": "md", "native": False, "available": True,
                    "source_file": info["source_file"]})
    return formats


def default_format(book_id: str) -> str:
    """Open natively when the file is here, otherwise fall back to the spine."""
    for f in formats_for(book_id):
        if f["available"]:
            return f["format"]
    return "md"


def media_type_for(renderer: str) -> str | None:
    return _MEDIA_TYPE.get(renderer)
