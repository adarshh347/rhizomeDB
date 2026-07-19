"""Source-format detection: read the original format from a spine's provenance
header and whether the real file is present to render natively."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rhizome import config, sources


def _spine(text_dir: Path, book_id: str, source_file: str):
    (text_dir / f"{book_id}.md").write_text(
        f"---\nsource_file: {source_file}\npages: 3\n---\n\nBody text here.\n",
        encoding="utf-8",
    )


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.converted = self.root / "converted"
        self.converted.mkdir()
        self.books = self.root / "books"
        self.books.mkdir()
        self.patches = [
            patch.object(config, "CONVERTED_DIR", self.converted),
            patch.object(config, "ROOT", self.root),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_pdf_detected_but_unavailable_without_file(self):
        _spine(self.converted, "b", "Some Book.pdf")
        info = sources.source_info("b")
        self.assertEqual(info["renderer"], "pdf")
        self.assertFalse(info["native_available"])
        formats = [f["format"] for f in sources.formats_for("b")]
        self.assertEqual(formats, ["pdf", "md"])
        self.assertEqual(sources.default_format("b"), "md")

    def test_pdf_available_when_file_present(self):
        _spine(self.converted, "b", "Some Book.pdf")
        (self.books / "Some Book.pdf").write_bytes(b"%PDF-1.4 stub")
        info = sources.source_info("b")
        self.assertTrue(info["native_available"])
        self.assertEqual(info["path"].name, "Some Book.pdf")
        self.assertEqual(sources.default_format("b"), "pdf")

    def test_mobi_renders_as_epub(self):
        _spine(self.converted, "d", "Dict.mobi")
        self.assertEqual(sources.source_info("d")["renderer"], "epub")

    def test_unknown_source_is_md_only(self):
        _spine(self.converted, "x", "notes.txt")
        self.assertIsNone(sources.source_info("x")["renderer"])
        self.assertEqual([f["format"] for f in sources.formats_for("x")], ["md"])


if __name__ == "__main__":
    unittest.main()
