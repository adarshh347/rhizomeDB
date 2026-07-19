"""End-to-end tests for the consolidated FastAPI backend.

Everything runs against a throwaway corpus (one book, three chunks with real
spine offsets) and a throwaway workspace, so the suite never touches the user's
index or annotations. Covers the milestone-1 anchoring loop: resolve a quote →
create a highlight → it lands in the book's notes rail with a selector bundle →
delete it.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from rhizome import config, workspace, reader_service as rs


SPINE = (
    "# On Dwelling\n\n"
    "The first paragraph establishes a durable phrase that lives here plainly.\n\n"
    "A second paragraph turns the argument, extending the thought further along.\n\n"
    "The third paragraph closes with a distinct and final cadence of its own.\n"
)


def _chunks(book_id: str, spine: str) -> list[dict]:
    """Three chunks whose spine offsets point at the three paragraphs."""
    paras = [p for p in spine.split("\n\n") if p.strip() and not p.startswith("#")]
    rows = []
    for i, p in enumerate(paras):
        p = p.strip()
        start = spine.find(p)
        rows.append({"id": f"{book_id}#{i:04d}", "book_id": book_id,
                     "author": "Test Author", "title": "Test Book",
                     "heading": "On Dwelling", "page": i + 1,
                     "spine_start": start, "spine_end": start + len(p),
                     "text": p})
    return rows


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        converted = root / "converted"
        (converted / "sub").mkdir(parents=True)
        (converted / "sub" / "book.md").write_text(SPINE, encoding="utf-8")
        chunks_path = root / "chunks.jsonl"
        with chunks_path.open("w", encoding="utf-8") as f:
            for c in _chunks("book", SPINE):
                f.write(json.dumps(c) + "\n")
        ws = root / "workspace"

        self.patches = [
            patch.object(config, "CONVERTED_DIR", converted),
            patch.object(config, "CHUNKS_PATH", chunks_path),
            patch.object(workspace, "WORKSPACE_DIR", ws),
            patch.object(workspace, "ANNOT_PATH", ws / "annotations.jsonl"),
            patch.object(workspace, "SESSIONS_DIR", ws / "sessions"),
            patch.object(workspace, "CHATS_DIR", ws / "chats"),
        ]
        for p in self.patches:
            p.start()
        rs._READER_CHUNKS = None  # drop cached corpus from any prior test
        rs._WORD_COUNTS = {}

        from rhizome.api import app
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        rs._READER_CHUNKS = None
        self.tmp.cleanup()

    def test_library_and_book_carry_spine_offsets(self):
        books = self.client.get("/api/v2/books").json()["books"]
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["book_id"], "book")
        book = self.client.get("/api/v2/books/book").json()
        self.assertEqual(book["n_chunks"], 3)
        self.assertIsNotNone(book["paragraphs"][0]["spine_start"])

    def test_spine_endpoint_matches_offsets(self):
        spine = self.client.get("/api/v2/books/book/spine").json()
        book = self.client.get("/api/v2/books/book").json()
        p0 = book["paragraphs"][0]
        self.assertEqual(spine["text"][p0["spine_start"]:p0["spine_end"]], p0["text"])

    def test_resolve_maps_quote_to_chunk(self):
        r = self.client.post("/api/v2/anchors/resolve",
                             json={"book_id": "book", "quote": "durable phrase"}).json()
        self.assertTrue(r["resolved"])
        self.assertEqual(r["chunks"][0]["chunk_id"], "book#0000")
        self.assertTrue(r["chunks"][0]["primary"])

    def test_create_highlight_anchors_and_appears_in_rail(self):
        created = self.client.post("/api/v2/annotations", json={
            "book_id": "book", "quote": "extending the thought further",
            "note": "a mark", "kind": "highlight"}).json()
        self.assertFalse(created["orphaned"])
        rec = created["annotation"]
        self.assertEqual(rec["primary_chunk_id"], "book#0001")
        self.assertIn("text_position", rec["selector"])
        self.assertIn("text_quote", rec["selector"])

        rail = self.client.get("/api/v2/books/book/annotations").json()["items"]
        self.assertEqual([r["id"] for r in rail], [rec["id"]])

        deleted = self.client.delete(f"/api/v2/annotations/{rec['id']}").json()
        self.assertTrue(deleted["ok"])
        self.assertEqual(self.client.get("/api/v2/books/book/annotations").json()["items"], [])

    def test_unresolvable_highlight_is_stored_as_orphan(self):
        created = self.client.post("/api/v2/annotations", json={
            "book_id": "book", "quote": "a phrase that is nowhere in this book at all"}).json()
        self.assertTrue(created["orphaned"])
        self.assertTrue(created["annotation"]["orphaned"])
        orphans = self.client.get("/api/v2/annotations?orphaned=true").json()["items"]
        self.assertEqual(len(orphans), 1)


if __name__ == "__main__":
    unittest.main()
