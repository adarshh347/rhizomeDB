#!/usr/bin/env python3
"""Generate small, self-consistent sample PDF + EPUB books for renderer testing.

The real corpus files live in R2 (books/ is gitignored), so a fresh checkout has
no native file to render. This builds a couple of genuine ones from existing
spine text and runs them through the *real* conversion + chunking pipeline, so
the PDF.js / epub.js renderers and the whole anchoring loop can be exercised
end-to-end without the corpus:

    .venv/bin/python scripts/make_sample_books.py

Writes books/samples/*.{pdf,epub}, data/converted/samples/*.md (the spines), and
appends their chunks to index/chunks.jsonl. Idempotent — re-running replaces the
samples. Everything it writes is gitignored or regenerable; nothing to commit.
"""
import json
import pathlib
import zipfile

import pymupdf
import pymupdf4llm

from rhizome import config, chunk as chunk_mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOKS = ROOT / "books" / "samples"
CONVERTED = config.CONVERTED_DIR / "samples"

# Embed a real TrueType font in the sample PDF. The base-14 "helv" is NOT
# embedded, which makes PDF.js stall waiting on standard-font data; an embedded
# font renders reliably and better mirrors how real books ship.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
]
FONT_FILE = next((f for f in _FONT_CANDIDATES if pathlib.Path(f).exists()), None)
FONT_NAME = "F0"

# Two short public-domain-ish passages (Heidegger, "What Is Called Thinking?"
# lecture cadence) — enough prose to select, highlight and re-anchor against.
PASSAGES = {
    "sample-what-calls-for-thinking": [
        "What is called thinking?",
        "We come to know what it means to think when we ourselves try to think. "
        "If the attempt is to be successful, we must be ready to learn thinking. "
        "As soon as we allow ourselves to become involved in such learning, we "
        "have admitted that we are not yet capable of thinking.",
        "Yet man is called the being who can think, and rightly so. Man is the "
        "rational animal. Reason, ratio, unfolds in thinking. Being the rational "
        "animal, man must be capable of thinking if he really wants to.",
        "Still, it may be that man wants to think, but cannot. Perhaps he wants "
        "too much when he wants to think, and so can do too little. Man can think "
        "in the sense that he possesses the possibility to do so. This possibility "
        "alone, however, is no guarantee to us that we are capable of thinking.",
        "We are capable of doing only what we are inclined to do. And again, we "
        "truly incline toward something only when it in turn inclines toward us, "
        "toward our essential being, by appealing to our essential being as what "
        "holds us there. To hold means originally to tend, keep, take care.",
        "What must be thought about, turns away from man. It withdraws from him. "
        "But how can we have the least knowledge of something that withdraws from "
        "the beginning, how can we even give it a name? Whatever withdraws, "
        "refuses arrival. But withdrawing is not nothing.",
    ],
    "sample-the-thing-gathers": [
        "The thing things.",
        "In thinging, the thing stays the united four, earth and sky, divinities "
        "and mortals, in the simple onefold of their self-unified fourfold. The "
        "thing gathers. Gathering, it lets the fourfold of world abide in a single "
        "presence, in the thing that is present.",
        "The jug is a thing insofar as it things. The presence of something "
        "present such as the jug comes into its own, appropriatively manifests and "
        "determines itself, only from the thinging of the thing. Nearness "
        "preserves farness. Preserving farness, nearness presences nearness in "
        "nearing that farness.",
        "Bringing near in this way, nearness conceals its own self and remains, in "
        "its own way, nearest of all. The thing is not in the sense of the "
        "represented object, nor merely at hand. The thing things world.",
    ],
}


def make_pdf(path: pathlib.Path, title: str, paragraphs: list[str]) -> None:
    """A clean text PDF with a real, selectable text layer (no images)."""
    doc = pymupdf.open()
    width, height = pymupdf.paper_size("letter")
    margin = 72
    rect = pymupdf.Rect(margin, margin, width - margin, height - margin)
    body = f"{title}\n\n" + "\n\n".join(paragraphs)
    # insert_textbox returns <0 when the text overflows the box; add pages until
    # it all fits.
    font_kw = {"fontfile": FONT_FILE, "fontname": FONT_NAME} if FONT_FILE else {"fontname": "helv"}
    remaining = body
    while remaining:
        page = doc.new_page(width=width, height=height)
        rc = page.insert_textbox(rect, remaining, fontsize=12,
                                 align=pymupdf.TEXT_ALIGN_LEFT, **font_kw)
        if rc >= 0:
            break
        # rc is the count of characters that did NOT fit; re-flow the rest.
        placed = _fit_chars(page, rect, remaining)
        remaining = remaining[placed:].lstrip()
    doc.save(path)
    doc.close()


def _fit_chars(page, rect, text: str) -> int:
    """How many leading chars of `text` fit in rect (binary search on length)."""
    font_kw = {"fontfile": FONT_FILE, "fontname": FONT_NAME} if FONT_FILE else {"fontname": "helv"}
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        tmp = pymupdf.open()
        p = tmp.new_page(width=page.rect.width, height=page.rect.height)
        rc = p.insert_textbox(rect, text[:mid], fontsize=12, **font_kw)
        tmp.close()
        if rc >= 0:
            lo = mid
        else:
            hi = mid - 1
    return lo


def make_epub(path: pathlib.Path, book_id: str, title: str,
              paragraphs: list[str]) -> None:
    """A minimal but valid EPUB 3: one XHTML chapter, spine + nav."""
    paras = "\n".join(f"<p>{_esc(p)}</p>" for p in paragraphs)
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">\n'
        f"<head><title>{_esc(title)}</title></head>\n"
        f"<body><h1>{_esc(title)}</h1>\n{paras}\n</body></html>"
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>nav</title></head>'
        '<body><nav epub:type="toc"><ol>'
        f'<li><a href="chapter.xhtml">{_esc(title)}</a></li>'
        "</ol></nav></body></html>"
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="bookid">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="bookid">urn:uuid:{book_id}</dc:identifier>\n'
        f"<dc:title>{_esc(title)}</dc:title>\n"
        "<dc:language>en</dc:language>\n</metadata>\n"
        '<manifest>\n'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>\n'
        '<item id="chapter" href="chapter.xhtml" '
        'media-type="application/xhtml+xml"/>\n'
        "</manifest>\n"
        '<spine><itemref idref="chapter"/></spine>\n</package>'
    )
    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n</container>'
    )
    with zipfile.ZipFile(path, "w") as z:
        # mimetype must be first and stored (uncompressed) per the spec.
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/chapter.xhtml", chapter)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def convert_and_chunk(book_id: str, src: pathlib.Path) -> list[dict]:
    CONVERTED.mkdir(parents=True, exist_ok=True)
    md = pymupdf4llm.to_markdown(str(src), show_progress=False)
    doc = pymupdf.open(src)
    header = f"---\nsource_file: {src.name}\npages: {doc.page_count}\n---\n\n"
    doc.close()
    md_path = CONVERTED / f"{book_id}.md"
    md_path.write_text(header + md, encoding="utf-8")
    meta = {"author": "Martin Heidegger (sample)", "title": book_id.replace("-", " ").title()}
    return chunk_mod.chunk_book(md_path, book_id, meta)


def main():
    BOOKS.mkdir(parents=True, exist_ok=True)
    formats = {"sample-what-calls-for-thinking": "pdf",
               "sample-the-thing-gathers": "epub"}
    new_chunks: list[dict] = []
    for book_id, paras in PASSAGES.items():
        title = book_id.replace("-", " ").title()
        fmt = formats[book_id]
        src = BOOKS / f"{book_id}.{fmt}"
        if fmt == "pdf":
            make_pdf(src, title, paras)
        else:
            make_epub(src, book_id, title, paras)
        rows = convert_and_chunk(book_id, src)
        new_chunks.extend(rows)
        print(f"  {book_id:36s} {fmt:4s} -> {src.relative_to(ROOT)}  ({len(rows)} chunks)")

    # Rewrite chunks.jsonl: existing rows minus any prior sample rows, plus new.
    sample_ids = set(PASSAGES)
    kept = [c for c in chunk_mod.load_chunks() if c["book_id"] not in sample_ids] \
        if config.CHUNKS_PATH.exists() else []
    with config.CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for c in kept + new_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Appended {len(new_chunks)} sample chunks -> {config.CHUNKS_PATH}")


if __name__ == "__main__":
    main()
