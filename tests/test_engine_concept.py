"""`concept` engine — personalised PageRank over the chunk–concept graph."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import concepts as concepts_mod, config, engines
from rhizome.engines import Context

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}


def concepts_fixture():
    """A hand-built concept map over the fixture corpus.

    releasement : alpha#0003, gamma#0005, beta#0007   (cross-book bridge)
    open region : alpha#0003, alpha#0004, delta#0002
    stillness   : beta#0007, beta#0008
    structure   : delta#0002, delta#0008, gamma#0005
    world       : pervasive — on many chunks (should carry little weight)
    """
    cc = {
        "alpha#0003": ["releasement", "open region", "world"],
        "alpha#0004": ["open region", "world"],
        "gamma#0005": ["releasement", "structure", "world"],
        "beta#0007": ["releasement", "stillness", "world"],
        "beta#0008": ["stillness", "world"],
        "delta#0002": ["open region", "structure", "world"],
        "delta#0008": ["structure", "world"],
        "delta#0009": ["world"],
        "gamma#0000": ["world"],
        "beta#0000": ["world"],
    }
    labels = sorted({l for ls in cc.values() for l in ls})
    return {"mode": "test", "concepts": [{"id": l, "label": l, "count": 0, "score": 0, "books": {}}
                                         for l in labels],
            "chunk_concepts": cc}


_DEFAULT = object()


def make_ctx(concepts=_DEFAULT, edges=None):
    chunks, vecs = make_corpus()
    ctx = Context.from_arrays(chunks, vecs)
    ctx._side["concepts"] = concepts_fixture() if concepts is _DEFAULT else concepts
    ctx._side["edges"] = [] if edges is None else edges
    return ctx


class ConceptEngineTests(unittest.TestCase):
    def setUp(self):
        self.eng = engines.get("concept")
        self.ctx = make_ctx()

    def test_registered_and_ready_with_side_data(self):
        self.assertEqual(self.eng.needs, ["concepts"])
        ok, why = self.eng.ready(self.ctx)
        self.assertTrue(ok, why)

    def test_not_ready_when_concepts_missing(self):
        for missing in (None, {}, {"chunk_concepts": {}}):
            ctx = make_ctx(concepts=missing)
            ok, why = self.eng.ready(ctx)
            self.assertFalse(ok)
            self.assertIn("concepts not built", why)
            self.assertEqual(self.eng.candidates(ctx.seed_from_chunk("alpha#0003"), ctx, k=5), [])

    def test_not_ready_when_concepts_cover_another_corpus(self):
        # concepts.json built for different chunk ids → no graph nodes → not ready, no picks
        foreign = {"chunk_concepts": {"other-book#0001": ["releasement"], "other-book#0002": ["world"]}}
        ctx = make_ctx(concepts=foreign)
        ok, why = self.eng.ready(ctx)
        self.assertFalse(ok)
        self.assertIn("do not cover this corpus", why)
        self.assertEqual(self.eng.candidates(ctx.seed_from_chunk("alpha#0003"), ctx, k=5), [])

    def test_contract_shape_and_k(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, self.ctx, k=2)
        self.assertLessEqual(len(picks), 2)
        self.assertTrue(picks)
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), CONTRACT_KEYS - set(p))
            self.assertEqual(p["path"], "concept")
            self.assertEqual(p["corpus_size"], len(self.ctx.chunks))
            self.assertIsNotNone(p["similarity"])   # finish() back-fills the surface axis
            self.assertIsNotNone(p["rank"])
            self.assertIn("concepts", p)
            self.assertIn("activation", p)
            self.assertGreater(p["activation"], 0)
            self.assertTrue(p["why"].startswith("via concepts:"))
            self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])

    def test_cross_book_reach_through_shared_concept(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, self.ctx, k=8)
        ids = [p["id"] for p in picks]
        # the two other books that name "releasement" are reached
        self.assertIn("gamma#0005", ids)
        self.assertIn("beta#0007", ids)
        # and delta#0002 through "open region"
        self.assertIn("delta#0002", ids)
        by_id = {p["id"]: p for p in picks}
        self.assertIn("releasement", by_id["gamma#0005"]["concepts"])
        self.assertIn("releasement", by_id["beta#0007"]["why"])
        # the specific concept ranks before the pervasive one
        self.assertEqual(by_id["gamma#0005"]["concepts"][-1], "world")
        # every pick shares at least one concept with the seed
        for p in picks:
            self.assertTrue(set(p["concepts"]) & {"releasement", "open region", "world"})
        # concept-only neighbours out-rank world-only ones
        world_only = [p["id"] for p in picks if p["concepts"] == ["world"]]
        if world_only:
            self.assertGreater(ids.index(world_only[0]), ids.index("gamma#0005"))

    def test_seed_and_same_book_excluded(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, self.ctx, k=20)
        ids = [p["id"] for p in picks]
        self.assertNotIn("alpha#0003", ids)
        self.assertFalse(any(i.startswith("alpha#") for i in ids))
        # same-book allowed when asked
        picks = self.eng.candidates(seed, self.ctx, k=20, exclude_same_book=False)
        ids = [p["id"] for p in picks]
        self.assertIn("alpha#0004", ids)
        self.assertNotIn("alpha#0003", ids)

    def test_no_concepts_on_seed_means_no_picks(self):
        seed = self.ctx.seed_from_chunk("alpha#0011")   # not in the concept map
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5), [])

    def test_floor_returns_empty(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5, min_activation=1.0), [])

    def test_theme_seed_matches_concept_label(self):
        seed = self.ctx.seed_from_text("releasement and calm", embed=False)
        picks = self.eng.candidates(seed, self.ctx, k=8)
        ids = [p["id"] for p in picks]
        self.assertEqual(set(ids), {"alpha#0003", "gamma#0005", "beta#0007"})
        for p in picks:
            self.assertEqual(p["concepts"], ["releasement"])
            self.assertIn("releasement", p["why"])
            self.assertIsNone(p["similarity"])   # no vector on this seed
        # nothing matches → []
        seed = self.ctx.seed_from_text("zebra quantum", embed=False)
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=8), [])

    def test_edges_add_bridge_nodes(self):
        edges = [{"source": "s", "target": "visranti / repose", "relation": "resonates",
                  "provenance": "alpha#0003", "origin": "authored"},
                 {"source": "s", "target": "visranti / repose", "relation": "resonates",
                  "provenance": "delta#0010", "origin": "judged"},
                 {"source": "s", "target": "elsewhere", "relation": "resonates",
                  "provenance": "not-a-chunk", "origin": "note"}]
        ctx = make_ctx(edges=edges)
        seed = ctx.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, ctx, k=20)
        by_id = {p["id"]: p for p in picks}
        self.assertIn("delta#0010", by_id)   # reachable only through the bridge node
        self.assertEqual(by_id["delta#0010"]["concepts"], ["edge:visranti / repose"])
        self.assertIn("(bridge)", by_id["delta#0010"]["why"])
        # switching edges off drops the bridge-only neighbour
        picks = self.eng.candidates(seed, ctx, k=20, use_edges=False)
        self.assertNotIn("delta#0010", [p["id"] for p in picks])

    def test_concepts_file_is_reread_when_it_appears(self):
        """A1 — `rhizome concepts` run against a live server must flip the engine
        from not-ready to ready. The loader's None result used to be cached for
        the process lifetime, so the engine stayed stuck at "not built"."""
        chunks, vecs = make_corpus()
        ctx = Context.from_arrays(chunks, vecs)     # nothing pre-injected
        with tempfile.TemporaryDirectory() as d:
            cpath, epath = Path(d) / "concepts.json", Path(d) / "edges.jsonl"
            with patch.object(concepts_mod, "CONCEPTS_PATH", cpath), \
                 patch.object(config, "EDGES_PATH", epath):
                ok, why = self.eng.ready(ctx)
                self.assertFalse(ok)
                self.assertIn("concepts not built", why)
                seed = ctx.seed_from_chunk("alpha#0003")
                self.assertEqual(self.eng.candidates(seed, ctx, k=5), [])

                cpath.write_text(json.dumps(concepts_fixture()), encoding="utf-8")

                ok, why = self.eng.ready(ctx)
                self.assertTrue(ok, why)
                ids = [p["id"] for p in self.eng.candidates(seed, ctx, k=8)]
                self.assertIn("gamma#0005", ids)
                self.assertIn("beta#0007", ids)

                # a rebuild with a different map is picked up too (graph included)
                narrowed = concepts_fixture()
                narrowed["chunk_concepts"] = {"alpha#0003": ["releasement"],
                                              "beta#0007": ["releasement"]}
                cpath.write_text(json.dumps(narrowed), encoding="utf-8")
                ids = [p["id"] for p in self.eng.candidates(seed, ctx, k=8)]
                self.assertEqual(ids, ["beta#0007"])

    def test_injected_concepts_side_is_never_overwritten(self):
        """The suite's test seam: a raw ctx._side value wins over any file."""
        with tempfile.TemporaryDirectory() as d:
            cpath = Path(d) / "concepts.json"
            cpath.write_text(json.dumps({"chunk_concepts": {"alpha#0003": ["from disk"]}}),
                             encoding="utf-8")
            with patch.object(concepts_mod, "CONCEPTS_PATH", cpath):
                from rhizome.engines.concept import concepts_side
                self.assertIs(concepts_side(self.ctx), self.ctx._side["concepts"])
                ctx = make_ctx(concepts=None)
                self.assertIsNone(concepts_side(ctx))

    def test_deterministic(self):
        seed = self.ctx.seed_from_chunk("beta#0007")
        a = self.eng.candidates(seed, self.ctx, k=6)
        b = self.eng.candidates(seed, self.ctx, k=6)
        self.assertEqual([(p["id"], p["score"]) for p in a], [(p["id"], p["score"]) for p in b])
        # and against a freshly-built context (no cached graph)
        c = self.eng.candidates(seed, make_ctx(), k=6)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in c])


if __name__ == "__main__":
    unittest.main()
