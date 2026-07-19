import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rhizome import anchor, chunk, config


class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.converted = root / "converted"
        self.converted.mkdir()
        self.spine = "Alpha prefix. A durable phrase lives here. Omega suffix."
        (self.converted / "book.md").write_text(self.spine, encoding="utf-8")
        self.patch = patch.object(config, "CONVERTED_DIR", self.converted)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_exact_resolution_and_chunk_overlap(self):
        found = anchor.resolve("durable phrase", "Alpha prefix. A ",
                               " lives here", book_id="book")
        self.assertIsNotNone(found)
        self.assertTrue(found.exact)
        chunks = [
            {"id": "book#0000", "book_id": "book", "spine_start": 0, "spine_end": 30},
            {"id": "book#0001", "book_id": "book", "spine_start": 20, "spine_end": 58},
        ]
        hits = anchor.chunks_for(found.spine_start, found.spine_end,
                                 book_id="book", chunks=chunks)
        self.assertEqual(hits[0]["chunk_id"], "book#0000")
        self.assertTrue(hits[0]["primary"])

    def test_normalises_hyphenation_and_ligatures(self):
        (self.converted / "book.md").write_text(
            "The signi-\n ficance of the o\ufb03ce remains.", encoding="utf-8")
        found = anchor.resolve("significance of the office", book_id="book")
        self.assertIsNotNone(found)
        self.assertFalse(found.exact)

    def test_ambiguous_quote_without_context_is_orphan(self):
        (self.converted / "book.md").write_text("same words / same words", encoding="utf-8")
        self.assertIsNone(anchor.resolve("same words", book_id="book"))


class ChunkOffsetTests(unittest.TestCase):
    def test_offsets_are_additive_and_point_into_spine(self):
        with TemporaryDirectory() as td, patch.object(config, "CHUNK_MIN_WORDS", 2), \
                patch.object(config, "CHUNK_TARGET_WORDS", 4), \
                patch.object(config, "CHUNK_OVERLAP_WORDS", 0):
            path = Path(td) / "sample.md"
            path.write_text("First paragraph has words.\n\nSecond paragraph has words.",
                            encoding="utf-8")
            rows = chunk.chunk_book(path, "sample", {})
            spine = path.read_text(encoding="utf-8")
            self.assertTrue(rows)
            for row in rows:
                self.assertIn("spine_start", row)
                self.assertIn(row["text"].split("\n\n")[0],
                              spine[row["spine_start"]:row["spine_end"]])


if __name__ == "__main__":
    unittest.main()
