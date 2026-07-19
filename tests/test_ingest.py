"""Uploading a book: convert → chunk → index → readable, in a temp corpus."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pymupdf

from rhizome import config, ingest, reader_service as rs


def _make_pdf() -> bytes:
    doc = pymupdf.open()
    body = ("On Thinking\n\n" + " ".join(
        "We come to know what it means to think when we ourselves try to think."
        for _ in range(12)))
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 540, 720), body, fontsize=11, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(config, "ROOT", root),
            patch.object(config, "CONVERTED_DIR", root / "converted"),
            patch.object(config, "INDEX_DIR", root / "index"),
            patch.object(config, "CHUNKS_PATH", root / "index" / "chunks.jsonl"),
            patch.object(config, "CATALOG_PATH", root / "catalog.json"),
            patch.object(config, "CHUNK_MIN_WORDS", 5),
            patch.object(config, "CHUNK_TARGET_WORDS", 40),
            patch.object(config, "CHUNK_OVERLAP_WORDS", 0),
        ]
        for p in self.patches:
            p.start()
        (root / "converted").mkdir()
        rs._READER_CHUNKS = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        rs._READER_CHUNKS = None
        self.tmp.cleanup()

    def test_rejects_unsupported_format(self):
        with self.assertRaises(ValueError):
            ingest.ingest("notes.txt", b"hello")

    def test_pdf_upload_becomes_a_readable_book(self):
        result = ingest.ingest("On Thinking!.pdf", _make_pdf())
        self.assertEqual(result["book_id"], "on-thinking")
        self.assertGreaterEqual(result["n_chunks"], 1)

        # spine written, file saved, format advertised + available
        self.assertTrue((config.CONVERTED_DIR / "uploads" / "on-thinking.md").exists())
        self.assertTrue((config.ROOT / "books" / "uploads" / "on-thinking.pdf").exists())
        fmts = {f["format"]: f["available"] for f in result["formats"]}
        self.assertTrue(fmts.get("pdf"))

        # it shows up in the library + opens (chunks + catalog entry)
        books = {b["book_id"] for b in rs.books_index()["books"]}
        self.assertIn("on-thinking", books)
        self.assertIsNotNone(rs.book_payload("on-thinking"))

    def test_duplicate_upload_gets_a_distinct_id(self):
        a = ingest.ingest("On Thinking.pdf", _make_pdf())
        b = ingest.ingest("On Thinking.pdf", _make_pdf())
        self.assertEqual(a["book_id"], "on-thinking")
        self.assertEqual(b["book_id"], "on-thinking-2")


if __name__ == "__main__":
    unittest.main()
