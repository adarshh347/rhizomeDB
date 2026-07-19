"""Importing annotations made elsewhere: embedded PDF highlights + markdown."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pymupdf

from rhizome import chunk as chunk_mod, config, imports, reader_service as rs, workspace

BODY = (
    "Poetically man dwells upon this earth. Dwelling is the manner in which "
    "mortals are upon the earth. To build is in itself already to dwell. The "
    "nature of building is letting dwell, and thinking too belongs to dwelling."
)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        converted = root / "converted"
        converted.mkdir()
        books = root / "books"
        books.mkdir()
        ws = root / "workspace"

        # spine (what the resolver matches against)
        (converted / "annotated.md").write_text(
            "---\nsource_file: annotated.pdf\npages: 1\n---\n\n" + BODY + "\n",
            encoding="utf-8")

        # PDF with a highlight over a phrase + a popup note
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(56, 56, 540, 760), BODY, fontsize=13)
        rect = page.search_for("man dwells upon this earth")[0]
        annot = page.add_highlight_annot(rect)
        annot.set_info(content="key phrase")
        annot.update()
        doc.save(books / "annotated.pdf")
        doc.close()

        # chunk index for the book
        chunks_path = root / "index" / "chunks.jsonl"
        chunks_path.parent.mkdir()
        self.patches = [
            patch.object(config, "ROOT", root),
            patch.object(config, "CONVERTED_DIR", converted),
            patch.object(config, "INDEX_DIR", root / "index"),
            patch.object(config, "CHUNKS_PATH", chunks_path),
            patch.object(config, "CHUNK_MIN_WORDS", 5),
            patch.object(config, "CHUNK_TARGET_WORDS", 60),
            patch.object(config, "CHUNK_OVERLAP_WORDS", 0),
            patch.object(workspace, "WORKSPACE_DIR", ws),
            patch.object(workspace, "ANNOT_PATH", ws / "annotations.jsonl"),
            patch.object(workspace, "SESSIONS_DIR", ws / "sessions"),
            patch.object(workspace, "CHATS_DIR", ws / "chats"),
        ]
        for p in self.patches:
            p.start()
        rows = chunk_mod.chunk_book(converted / "annotated.md", "annotated", {})
        with chunks_path.open("w", encoding="utf-8") as f:
            for c in rows:
                f.write(json.dumps(c) + "\n")
        rs._READER_CHUNKS = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        rs._READER_CHUNKS = None
        self.tmp.cleanup()

    def test_pdf_import_anchors_with_provenance_and_locator(self):
        result = imports.import_pdf_annotations("annotated")
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["orphaned"], 0)
        ann = result["items"][0]
        self.assertIn("man dwells upon this earth", ann["quote"])
        self.assertEqual(ann["origin"], "import-pdf")
        self.assertEqual(ann["note"], "key phrase")
        self.assertIn("text_position", ann["selector"])
        self.assertEqual(ann["selector"]["locator"]["page"], 0)
        self.assertTrue(ann["selector"]["locator"]["quads"])

    def test_pdf_import_is_idempotent(self):
        imports.import_pdf_annotations("annotated")
        again = imports.import_pdf_annotations("annotated")
        self.assertEqual(again["duplicate"], 1)
        self.assertEqual(again["imported"], 0)
        rows = workspace.list_annotations()
        self.assertEqual(len([r for r in rows if r.get("origin") == "import-pdf"]), 1)

    def test_markdown_import_resolved_and_orphan(self):
        md = (
            "==Dwelling is the manner in which mortals are upon the earth==\n\n"
            "> The nature of building is letting dwell\n"
            "— a note on building\n\n"
            "==a phrase that is nowhere in this book==\n"
        )
        result = imports.import_markdown("annotated", md)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["orphaned"], 1)
        orphans = [r for r in workspace.list_annotations() if r.get("orphaned")]
        self.assertEqual(len(orphans), 1)
        noted = [i for i in result["items"] if i.get("note")]
        self.assertTrue(any("building" in n["note"] for n in noted))


if __name__ == "__main__":
    unittest.main()
