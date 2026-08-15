"""`structural` engine — persisted HyDE over a hand-built structural matrix."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed
from rhizome.engines import structural as mod

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}
EXTRA_KEYS = {"structural_similarity", "surface_similarity", "gap", "abstraction"}

A, B = "alpha#0001", "delta#0005"     # the planted structural pair (surface-far)
SAME_BOOK = "alpha#0006"              # structurally near A but in A's own book


def _unit(v):
    return v / (np.linalg.norm(v) + 1e-12)


def make_structural(chunks, vecs, seed=11):
    """A structural space that is mostly noise, with A~B (cross-book) and
    A~SAME_BOOK planted as near-identical moves."""
    rng = np.random.default_rng(seed)
    n, dim = vecs.shape
    idx = {c["id"]: i for i, c in enumerate(chunks)}
    svecs = np.asarray([_unit(rng.normal(size=dim)) for _ in range(n)], dtype=np.float32)
    move = _unit(rng.normal(size=dim))
    svecs[idx[A]] = _unit(0.85 * move + 0.55 * svecs[idx[A]])
    svecs[idx[B]] = _unit(0.85 * move + 0.55 * svecs[idx[B]])
    svecs[idx[SAME_BOOK]] = _unit(0.85 * move + 0.55 * svecs[idx[SAME_BOOK]])
    abstractions = [f"the move of chunk {c['id']}: " + "x" * 300 for c in chunks]
    return {"vecs": svecs, "abstractions": abstractions}


class StructuralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.side = make_structural(cls.chunks, cls.vecs)
        cls.eng = engines.get("structural")

    def ctx(self, with_side=True, vecs="yes"):
        ctx = Context.from_arrays(self.chunks, self.vecs if vecs == "yes" else None)
        if with_side:
            ctx._side["structural"] = self.side
        return ctx

    def test_registered(self):
        self.assertIn("structural", engines.keys())
        self.assertEqual(self.eng.needs, ["structural"])
        self.assertTrue(set(self.eng.params) >= {"min_struct", "dedup_struct", "exclude_same_book"})

    def test_ready_false_when_side_missing(self):
        ctx = self.ctx(with_side=False)
        ctx._side["structural"] = None       # loader result when files are absent
        ok, why = self.eng.ready(ctx)
        self.assertFalse(ok)
        self.assertIn("build-structural", why)
        self.assertEqual(self.eng.candidates(ctx.seed_from_chunk(A), ctx), [])

    def test_ready_true_with_side(self):
        self.assertEqual(self.eng.ready(self.ctx()), (True, ""))

    def test_surfaces_planted_pair_with_positive_gap(self):
        ctx = self.ctx()
        picks = self.eng.candidates(ctx.seed_from_chunk(A), ctx, k=5)
        self.assertTrue(picks)
        self.assertLessEqual(len(picks), 5)
        self.assertEqual(picks[0]["id"], B)
        top = picks[0]
        self.assertTrue(CONTRACT_KEYS <= set(top))
        self.assertTrue(EXTRA_KEYS <= set(top))
        self.assertGreater(top["structural_similarity"], 0.6)
        # surface-far: the fixture puts alpha and delta in different regions
        self.assertLess(top["surface_similarity"], 0.5)
        self.assertGreater(top["gap"], 0)
        self.assertAlmostEqual(top["gap"], round(top["structural_similarity"] - top["surface_similarity"], 4), places=3)
        self.assertEqual(top["surface_similarity"], top["similarity"])
        self.assertEqual(top["score"], top["structural_similarity"])
        self.assertEqual(top["path"], "structural")
        self.assertIn("same move", top["why"])
        self.assertIn("structural vs", top["why"])
        self.assertLessEqual(len(top["abstraction"]), mod.ABSTRACTION_CLIP)
        # sorted by structural similarity desc, all cross-book, floors respected
        ss = [p["structural_similarity"] for p in picks]
        self.assertEqual(ss, sorted(ss, reverse=True))
        for p in picks:
            self.assertGreaterEqual(p["structural_similarity"], mod.MIN_STRUCT)
            self.assertLess(p["structural_similarity"], mod.DEDUP_STRUCT)
            self.assertNotEqual(p["book_id"], "alpha")
        self.assertIsNotNone(top["rank"])
        self.assertEqual(top["corpus_size"], len(self.chunks))

    def test_seed_and_same_book_excluded(self):
        ctx = self.ctx()
        picks = self.eng.candidates(ctx.seed_from_chunk(A), ctx, k=50)
        ids = [p["id"] for p in picks]
        self.assertNotIn(A, ids)
        self.assertNotIn(SAME_BOOK, ids)
        # with exclusion off, the same-book near-move shows up
        picks = self.eng.candidates(ctx.seed_from_chunk(A), ctx, k=50, exclude_same_book=False)
        ids = [p["id"] for p in picks]
        self.assertNotIn(A, ids)
        self.assertIn(SAME_BOOK, ids)

    def test_respects_k_and_floor(self):
        ctx = self.ctx()
        picks = self.eng.candidates(ctx.seed_from_chunk(A), ctx, k=2)
        self.assertEqual(len(picks), 2)
        # a floor above every candidate → nothing, never padded
        self.assertEqual(self.eng.candidates(ctx.seed_from_chunk(A), ctx, k=5, min_struct=0.99), [])
        # a dedup ceiling below the planted pair drops it as a quotation
        picks = self.eng.candidates(ctx.seed_from_chunk(A), ctx, k=5, dedup_struct=0.5)
        self.assertNotIn(B, [p["id"] for p in picks])

    def test_deterministic(self):
        ctx = self.ctx()
        a = self.eng.candidates(ctx.seed_from_chunk(B), ctx, k=6)
        b = self.eng.candidates(ctx.seed_from_chunk(B), ctx, k=6)
        self.assertEqual(a, b)

    def test_theme_seed_without_client_falls_back_to_surface(self):
        ctx = self.ctx()
        # theme seed whose surface vector IS A's structural row → the fallback
        # queries the structural space with it: A itself is a quotation (≥ dedup),
        # its planted partners B and SAME_BOOK (no book to exclude) surface
        q = self.side["vecs"][ctx.index_of(A)]
        seed = Seed(text="the move", vec=q)
        picks = self.eng.candidates(seed, ctx, k=5)
        self.assertTrue(picks)
        ids = [p["id"] for p in picks]
        self.assertNotIn(A, ids); self.assertIn(B, ids); self.assertIn(SAME_BOOK, ids)
        for p in picks:
            self.assertIn(mod.THEME_FALLBACK_NOTE, p["why"])
        # no vector and no client → nothing
        self.assertEqual(self.eng.candidates(Seed(text="the move"), ctx, k=5), [])

    def test_theme_seed_with_client_abstracts_then_embeds(self):
        ctx = self.ctx()
        calls = {}

        class FakeClient:
            def complete(self, system, user, **kw):
                calls["user"] = user
                return "an abstraction"

        q = self.side["vecs"][ctx.index_of(A)]
        from rhizome import embed as embed_mod
        real = embed_mod.embed_query
        embed_mod.embed_query = lambda text, key: (calls.setdefault("abs", text), q)[1]
        try:
            picks = self.eng.candidates(Seed(text="the move"), ctx, k=3, client=FakeClient())
        finally:
            embed_mod.embed_query = real
        self.assertEqual(calls["abs"], "an abstraction")
        self.assertIn("the move", calls["user"])
        ids = [p["id"] for p in picks]
        self.assertNotIn(A, ids); self.assertIn(B, ids)
        self.assertNotIn(mod.THEME_FALLBACK_NOTE, picks[0]["why"])
        self.assertIsNone(picks[0]["similarity"])   # theme seed w/o surface vec

    def test_no_surface_vectors_still_works(self):
        ctx = self.ctx(vecs="no")
        picks = self.eng.candidates(Seed(text="x", chunk_id=A, book_id="alpha"), ctx, k=3)
        self.assertEqual(picks[0]["id"], B)
        self.assertIsNone(picks[0]["similarity"]); self.assertIsNone(picks[0]["gap"])
        self.assertIsNone(picks[0]["surface_similarity"])

    def test_structural_paths(self):
        npy, jsonl = mod.structural_paths("minilm")
        self.assertTrue(str(npy).endswith("structural_minilm.npy"))
        self.assertTrue(str(jsonl).endswith("structural_minilm.jsonl"))


if __name__ == "__main__":
    unittest.main()
