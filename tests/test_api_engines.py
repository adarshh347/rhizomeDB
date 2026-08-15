"""The mini-engine routes of the FastAPI backend (Increment 3).

Everything runs against an in-memory `engines.Context` built from the fixture
corpus (no real index, no LLM): `reader_service.get_context` is patched to
return it, `index_ready` is forced True, and `get_engine` hands back a stub
whose `.client` is None so an explore run ends after candidates + note + done.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import config, engines, reader_service as rs  # noqa: E402
from rhizome import embed as embed_mod  # noqa: E402
from rhizome.engines import Context  # noqa: E402

ITEM_KEYS = {"index", "chunk_id", "author", "title", "page", "text", "similarity",
             "direct_dissimilarity", "structural_similarity", "rank", "corpus_size",
             "score", "path", "why"}


def _sse_events(text: str):
    """Parse an SSE body into [(event, data-dict)]."""
    out = []
    for block in text.split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev is not None:
            out.append((ev, data))
    return out


class ApiEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()

    def setUp(self):
        self.ctx = Context.from_arrays(self.chunks, self.vecs)
        stub = SimpleNamespace(client=None, store=self.ctx.store)
        # a theme seed embeds with the real model — replace it with a fixture-dim vector
        theme_vec = self.vecs[3].copy()
        self.patches = [
            patch.object(rs, "get_context", lambda embed_key=config.DEFAULT_EMBED: self.ctx),
            patch.object(rs, "index_ready", lambda: True),
            patch.object(rs, "get_engine", lambda: stub),
            patch.object(embed_mod, "embed_query", lambda text, model_key=None: theme_vec),
        ]
        for p in self.patches:
            p.start()
        from rhizome.api import app
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    # ---- /engines -----------------------------------------------------------
    def test_engines_lists_ready_engines_and_default(self):
        r = self.client.get("/api/v2/engines")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["default"], "band")
        cards = body["engines"]
        self.assertEqual([c["key"] for c in cards], engines.keys())
        ready = [c for c in cards if c["ready"]]
        self.assertGreaterEqual(len(ready), 2)
        for c in cards:
            for k in ("key", "label", "blurb", "needs", "params", "ready", "reason"):
                self.assertIn(k, c)

    def test_engines_status_survives_a_context_without_vectors(self):
        ctx = Context.from_arrays(self.chunks, None)
        with patch.object(rs, "get_context", lambda embed_key=config.DEFAULT_EMBED: ctx):
            body = self.client.get("/api/v2/engines").json()
        by_key = {c["key"]: c for c in body["engines"]}
        self.assertTrue(by_key["lexical"]["ready"])
        self.assertFalse(by_key["band"]["ready"])
        self.assertTrue(by_key["band"]["reason"])

    # ---- /connect -----------------------------------------------------------
    def test_connect_band_chunk_returns_items(self):
        r = self.client.get("/api/v2/connect", params={
            "engine": "band", "mode": "chunk", "value": "alpha#0009", "candidates": 4})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["engine"]["key"], "band")
        self.assertEqual(body["seed"]["chunk_id"], "alpha#0009")
        self.assertEqual(body["seed"]["book_id"], "alpha")
        self.assertEqual(body["params"]["k"], 4)
        self.assertIsInstance(body["ms"], float)
        self.assertLessEqual(len(body["items"]), 4)
        self.assertTrue(body["items"])
        for i, it in enumerate(body["items"]):
            self.assertTrue(ITEM_KEYS <= set(it), ITEM_KEYS - set(it))
            self.assertEqual(it["index"], i)
            self.assertEqual(it["path"], "band")
            self.assertTrue(it["why"])
            self.assertIsInstance(it["rank"], int)
            self.assertNotEqual(it["chunk_id"], "alpha#0009")
            self.assertNotEqual(it["title"], None)
        # identical to a direct Store.connections() call (parity through the API)
        seed = self.ctx.seed_from_chunk("alpha#0009")
        direct = self.ctx.store.connections(seed.vec, seed_book_id="alpha",
                                            seed_author=seed.author, k=4)
        self.assertEqual([it["chunk_id"] for it in body["items"]], [c["id"] for c in direct])

    def test_connect_plain(self):
        r = self.client.get("/api/v2/connect", params={
            "engine": "plain", "mode": "chunk", "value": "beta#0007", "candidates": 3})
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual([it["rank"] for it in items], [1, 2, 3])
        self.assertTrue(all(it["path"] == "plain" for it in items))

    def test_connect_theme_seed(self):
        r = self.client.get("/api/v2/connect", params={
            "engine": "plain", "mode": "theme", "value": "region releasement waiting"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIsNone(body["seed"]["chunk_id"])
        self.assertTrue(body["seed"]["label"].startswith("theme:"))
        self.assertTrue(body["items"])

    def test_connect_engine_params_via_query(self):
        r = self.client.get("/api/v2/connect", params={
            "engine": "band", "mode": "chunk", "value": "alpha#0003",
            "candidates": 3, "min_sim": 0.99})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["params"]["min_sim"], 0.99)
        self.assertTrue(body["note"])

    def test_connect_unknown_engine_is_400(self):
        r = self.client.get("/api/v2/connect", params={
            "engine": "nope", "mode": "chunk", "value": "alpha#0003"})
        self.assertEqual(r.status_code, 400)

    def test_connect_unknown_chunk_is_404(self):
        r = self.client.get("/api/v2/connect", params={
            "engine": "band", "mode": "chunk", "value": "zeta#9999"})
        self.assertEqual(r.status_code, 404)

    def test_connect_not_ready_engine_reports_note(self):
        ctx = Context.from_arrays(self.chunks, None)
        with patch.object(rs, "get_context", lambda embed_key=config.DEFAULT_EMBED: ctx):
            r = self.client.get("/api/v2/connect", params={
                "engine": "band", "mode": "chunk", "value": "alpha#0003"})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["items"], [])
            self.assertTrue(body["note"])
            # lexical works with chunks only
            r = self.client.get("/api/v2/connect", params={
                "engine": "lexical", "mode": "chunk", "value": "alpha#0003"})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["items"])

    # ---- /connect/compare -----------------------------------------------------
    def test_compare_returns_results_and_square_matrix(self):
        r = self.client.get("/api/v2/connect/compare", params={
            "mode": "chunk", "value": "alpha#0003", "candidates": 5})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["seed"]["chunk_id"], "alpha#0003")
        results = body["results"]
        self.assertGreaterEqual(len(results), 2)
        keys = [x["key"] for x in results]
        self.assertEqual(body["overlap"]["keys"], keys)
        m = body["overlap"]["matrix"]
        self.assertEqual(len(m), len(keys))
        for i, row in enumerate(m):
            self.assertEqual(len(row), len(keys))
            self.assertAlmostEqual(row[i], 1.0)
            for v in row:
                self.assertGreaterEqual(v, 0.0); self.assertLessEqual(v, 1.0)
        for x in results:
            self.assertIn("ms", x); self.assertIn("label", x)
            self.assertLessEqual(len(x["items"]), 5)

    def test_compare_subset_of_engines(self):
        r = self.client.get("/api/v2/connect/compare", params={
            "mode": "chunk", "value": "alpha#0003", "engines": "band,plain"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["overlap"]["keys"], ["band", "plain"])
        r = self.client.get("/api/v2/connect/compare", params={
            "mode": "chunk", "value": "alpha#0003", "engines": "band,nope"})
        self.assertEqual(r.status_code, 400)

    # ---- /explore -------------------------------------------------------------
    def test_explore_streams_engine_then_candidates(self):
        r = self.client.get("/api/v2/explore", params={
            "mode": "chunk", "value": "alpha#0009", "candidates": 4, "engine": "band"})
        self.assertEqual(r.status_code, 200)
        events = _sse_events(r.text)
        names = [e for e, _ in events]
        self.assertEqual(names[:3], ["seed", "engine", "candidates"])
        self.assertIn("note", names); self.assertEqual(names[-1], "done")
        seed = events[0][1]
        for k in ("label", "text", "author", "book_id", "embed_key", "embed_label", "chunk_id"):
            self.assertIn(k, seed)
        self.assertEqual(seed["chunk_id"], "alpha#0009")
        self.assertEqual(events[1][1]["key"], "band")
        cands = events[2][1]
        self.assertEqual(cands["params"]["engine"], "band")
        for k in ("total_chunks", "skip_top", "pool", "min_sim", "mmr_lambda",
                  "exclude_same_author", "k"):
            self.assertIn(k, cands["params"])
        self.assertIn("excluded_author", cands)
        self.assertTrue(cands["items"])
        for it in cands["items"]:
            self.assertTrue(ITEM_KEYS <= set(it), ITEM_KEYS - set(it))
            self.assertIsNone(it["structural_similarity"])

    def test_explore_other_engine_and_unknown_engine(self):
        r = self.client.get("/api/v2/explore", params={
            "mode": "chunk", "value": "alpha#0003", "engine": "plain"})
        events = _sse_events(r.text)
        self.assertEqual(events[1][1]["key"], "plain")
        self.assertTrue(all(it["path"] == "plain" for it in events[2][1]["items"]))
        r = self.client.get("/api/v2/explore", params={
            "mode": "chunk", "value": "alpha#0003", "engine": "nope"})
        self.assertEqual(r.status_code, 400)

    def test_explore_not_ready_engine_emits_note_then_done(self):
        ctx = Context.from_arrays(self.chunks, None)
        with patch.object(rs, "get_context", lambda embed_key=config.DEFAULT_EMBED: ctx):
            r = self.client.get("/api/v2/explore", params={
                "mode": "chunk", "value": "alpha#0003", "engine": "band"})
        names = [e for e, _ in _sse_events(r.text)]
        self.assertEqual(names, ["seed", "engine", "note", "done"])

    def test_item_keeps_an_engines_own_structural_axis(self):
        pick = dict(self.chunks[0], similarity=0.5, rank=3, corpus_size=48, score=0.7,
                    path="structural", why="w", structural_similarity=0.7,
                    abstraction="MOVE", terms=["a"])
        it = rs._item(0, pick)
        self.assertEqual(it["structural_similarity"], 0.7)
        self.assertEqual(it["abstraction"], "MOVE")
        self.assertEqual(it["terms"], ["a"])
        # the explore run's LLM axis wins when the caller supplies one
        self.assertEqual(rs._item(0, pick, 0.2)["structural_similarity"], 0.2)
        # unknown → null, never missing
        bare = rs._item(1, dict(self.chunks[1], path="x", why="y"))
        self.assertTrue(ITEM_KEYS <= set(bare))
        self.assertIsNone(bare["similarity"]); self.assertIsNone(bare["structural_similarity"])

    # ---- /engines/eval ----------------------------------------------------------
    def test_eval_report_404_when_absent(self):
        from rhizome import api as api_mod
        with patch.object(api_mod, "_load_eval_report", lambda: None):
            r = self.client.get("/api/v2/engines/eval")
        self.assertEqual(r.status_code, 404)
        self.assertIn("not built", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
