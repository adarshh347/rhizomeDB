#!/usr/bin/env python3
"""Convert source books (PDF/EPUB/MOBI) into Markdown for the RAG pipeline.

Output: converted/<collection>/<clean-name>.md
Each file gets a small provenance header (source filename + page count).
"""
import os
import sys
import shutil
import subprocess
import tempfile
import pathlib

import pymupdf4llm
import pymupdf

# If pymupdf4llm yields fewer than this many chars per page, the PDF is almost
# certainly a scanned book whose body pages are images with an invisible OCR
# text layer underneath. pymupdf4llm drops that layer; pdftotext recovers it.
MIN_CHARS_PER_PAGE = 200

SRC_ROOT = pathlib.Path("books")
OUT_ROOT = pathlib.Path("converted")

# Map messy source filenames -> clean output slugs.
CLEAN_NAMES = {
    "What-Is-Called-Thinking-heidegger.pdf": "what-is-called-thinking",
    "Heidegger+Nietzsche+1+and+2.pdf": "heidegger-nietzsche-1-and-2",
    "heidegger-and-a-metaphysics-of-feeling-angst-and-the-finitude-of-being-9781472546623-9780826498755-9781441101525_compress.pdf": "metaphysics-of-feeling-angst-and-finitude",
    "HEIDEGGER AND THE DESTRUCTION OF ARISTOTLE _ on how to read -- Sean D_ Kirkland -- Studies in Phenomenology and Existential Philosophy, 1, 2023 -- isbn13 9780810146181 -- dc27bcab796c200ddaae9e610b3cb80a -- Anna’s Archive.pdf": "heidegger-and-the-destruction-of-aristotle",
    "Heidegger on Poetic Thinking -- Charles Bambach -- Elements in the Philosophy of Martin Heidegger, 2024 -- Cambridge University Press -- isbn13 9781009570558 -- c785d9f1bcd45c6c0f2a56f54ff40290 -- Anna’s Archive.pdf": "heidegger-on-poetic-thinking",
    "The Cambridge Companion to Heidegger.epub": "cambridge-companion-to-heidegger",
    "Being and Truth (Studies in Continental Thought) -- Martin Heidegger [Heidegger, Martin] -- 2010 -- Indiana University Press -- 78827c2432269c97224dbbc4be711722 -- Anna’s Archive.epub": "being-and-truth",
    "The Heidegger dictionary by Heidegger, Martin Heidegger, -- Unknown -- 2021 -- 216fdc48c90fa1788c3e2ef44f57ac58 -- Anna’s Archive.mobi": "heidegger-dictionary",
}


def header(src_name: str, pages: int) -> str:
    return (
        "---\n"
        f"source_file: {src_name}\n"
        f"pages: {pages}\n"
        "---\n\n"
    )


def pdftotext_layer(path: pathlib.Path, pages: int) -> str:
    """Extract the OCR/text layer with poppler, keeping page-break markers."""
    raw = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    # pdftotext separates pages with form-feed (\f); turn into readable markers.
    out = []
    for i, page in enumerate(raw.split("\f"), start=1):
        page = page.strip()
        if page:
            out.append(f"\n\n<!-- page {i} -->\n\n{page}")
    return header(path.name, pages) + "".join(out)


def convert_with_pymupdf(path: pathlib.Path) -> str:
    """Works for PDF and EPUB (anything pymupdf can open)."""
    doc = pymupdf.open(path)
    n = doc.page_count
    doc.close()
    md = pymupdf4llm.to_markdown(str(path), show_progress=False)
    # Scanned-PDF detection: too little text => fall back to the OCR layer.
    if path.suffix.lower() == ".pdf" and n and len(md) / n < MIN_CHARS_PER_PAGE:
        fallback = pdftotext_layer(path, n)
        if len(fallback) > len(md):
            print(f"     (scanned PDF detected -> pdftotext fallback)")
            return fallback
    return header(path.name, n) + md


def convert_mobi(path: pathlib.Path) -> str:
    import mobi
    tmpdir, extracted = mobi.extract(str(path))
    try:
        ext = pathlib.Path(extracted).suffix.lower()
        if ext == ".epub":
            doc = pymupdf.open(extracted)
            n = doc.page_count
            doc.close()
            md = pymupdf4llm.to_markdown(extracted, show_progress=False)
            return header(path.name, n) + md
        # Fallback: HTML output -> strip to text via pymupdf
        doc = pymupdf.open(extracted)
        parts = [doc[i].get_text("text") for i in range(doc.page_count)]
        n = doc.page_count
        doc.close()
        return header(path.name, n) + "\n\n".join(parts)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    filters = sys.argv[1:]  # optional substrings to limit which files to (re)convert
    sources = sorted(p for p in SRC_ROOT.rglob("*")
                     if p.suffix.lower() in {".pdf", ".epub", ".mobi"}
                     and (not filters or any(f in p.name for f in filters)))
    print(f"Found {len(sources)} source files\n")
    for src in sources:
        rel_dir = src.parent.relative_to(SRC_ROOT)
        out_dir = OUT_ROOT / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = CLEAN_NAMES.get(src.name, src.stem)
        out_path = out_dir / f"{slug}.md"
        try:
            if src.suffix.lower() == ".mobi":
                text = convert_mobi(src)
            else:
                text = convert_with_pymupdf(src)
            out_path.write_text(text, encoding="utf-8")
            kb = out_path.stat().st_size // 1024
            print(f"OK   {src.name[:50]:50s} -> {out_path}  ({kb} KB)")
        except Exception as e:
            print(f"FAIL {src.name[:50]:50s} : {e!r}")


if __name__ == "__main__":
    main()
