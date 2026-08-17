"""`hybrid` — dense + keyword RRF fusion, on the fixture corpus.

The keyword half comes from the sibling `lexical` module. Tests of the fusion
arithmetic stub `hybrid._lexical_ranked` so they hold regardless of BM25's
exact scores; the end-to-end tests skip when `lexical` is not importable.
"""
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed
from rhizome.engines import hybrid

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why", "dense_rank", "lexical_rank"}


def _lexical_available() -> bool:
    try:
        from rhizome.engines import lexical  # noqa: F401
        return True
    except ImportError:
        return False


class HybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx = Context.from_arrays(cls.chunks, cls.vecs)
        cls.eng = engines.get("hybrid")

    # -- helpers --------------------------------------------------------------
    def _stub(self, idxs, terms=("region", "releasement")):
        """Make the keyword list exactly `idxs` (in that order)."""
        hits = [(i, float(len(idxs) - n)) for n, i in enumerate(idxs)]
        return mock.patch.object(hybrid, "_lexical_ranked", lambda seed, ctx, n: (hits[:n], list(terms)))

    def _dense_order(self, seed):
        sims = self.vecs @ seed.vec
        return [int(i) for i in np.argsort(-sims, kind="stable")
                if self.chunks[int(i)]["id"] != seed.chunk_id]

    # -- registry / contract ---------------------------------------------------
    def test_registered_and_ready(self):
        self.assertIn("hybrid", engines.keys())
        self.assertEqual(self.eng.needs, ["vectors", "chunks"])
        ok, _ = self.eng.ready(self.ctx)
        self.assertTrue(ok)
        ok, why = self.eng.ready(Context.from_arrays(self.chunks, None))
        self.assertFalse(ok); self.assertTrue(why)
        for name in ("rrf_k", "pool", "exclude_same_book"):
            self.assertIn(name, self.eng.params)

    def test_k_and_contract_fields(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        with self._stub([5, 6, 7]):
            picks = self.eng.candidates(seed, self.ctx, k=4)
        self.assertEqual(len(picks), 4)
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), f"missing {CONTRACT_KEYS - set(p)}")
            self.assertEqual(p["path"], "hybrid")
            self.assertEqual(p["corpus_size"], len(self.chunks))
            self.assertIsNotNone(p["similarity"]); self.assertIsNotNone(p["rank"])
            self.assertTrue(p["why"])
            self.assertIsNot(p, self.chunks[self.ctx.index_of(p["id"])])
        self.assertNotIn("alpha#0003", [p["id"] for p in picks])
        scores = [p["score"] for p in picks]
        self.assertEqual(scores, sorted(scores, reverse=True))

    # -- fusion arithmetic -------------------------------------------------------
    def test_chunk_in_both_lists_outranks_single_list_at_equal_rank(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        dense = self._dense_order(seed)
        both, dense_only = dense[2], dense[0]   # both: dense #3 + keyword #3 ; other: dense #1 only
        # keyword list: two strangers, then `both` at #3, then more strangers
        others = [i for i in range(len(self.chunks)) if i not in dense[:12]
                  and self.chunks[i]["id"] != seed.chunk_id]
        kw = [others[0], others[1], both] + others[2:6]
        with self._stub(kw):
            picks = self.eng.candidates(seed, self.ctx, k=8, pool=10)
        ids = [p["id"] for p in picks]
        self.assertEqual(ids[0], self.chunks[both]["id"])
        top = picks[0]
        self.assertEqual((top["dense_rank"], top["lexical_rank"]), (3, 3))
        self.assertTrue(top["why"].startswith("dense #3 + keyword #3"))
        # the equal-rank single-list chunks share a score below the fused one,
        # and dense #1 (in one list only) sits below the both-lists chunk
        d1 = next(p for p in picks if p["id"] == self.chunks[dense_only]["id"])
        self.assertEqual((d1["dense_rank"], d1["lexical_rank"]), (1, None))
        self.assertLess(d1["score"], top["score"])
        self.assertTrue(d1["why"].startswith("dense only #1"))
        k1 = next(p for p in picks if p["id"] == self.chunks[others[0]]["id"])
        self.assertEqual((k1["dense_rank"], k1["lexical_rank"]), (None, 1))
        self.assertTrue(k1["why"].startswith("keyword only #1"))
        self.assertAlmostEqual(k1["score"], d1["score"], places=6)
        # rrf arithmetic: 1/(60+3)*2 vs 1/(60+1)
        self.assertAlmostEqual(top["score"], 2 / 63, places=6)
        self.assertAlmostEqual(d1["score"], 1 / 61, places=6)

    def test_rrf_k_param_changes_scores(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        with self._stub([]):
            a = self.eng.candidates(seed, self.ctx, k=1, rrf_k=60)
            b = self.eng.candidates(seed, self.ctx, k=1, rrf_k=10)
        self.assertAlmostEqual(a[0]["score"], 1 / 61, places=6)
        self.assertAlmostEqual(b[0]["score"], 1 / 11, places=6)

    def test_why_names_matched_terms(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        i = self.ctx.index_of("alpha#0005")
        with self._stub([i], terms=("alpha", "alphatoken5", "zzz")):
            picks = self.eng.candidates(seed, self.ctx, k=50, pool=50)
        p = next(p for p in picks if p["id"] == "alpha#0005")
        self.assertIn("alphatoken5", p["why"])
        self.assertNotIn("zzz", p["why"])
        self.assertEqual(p["matched_terms"], ["alphatoken5"])

    def test_pool_bounds_each_list(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        with self._stub([]):
            picks = self.eng.candidates(seed, self.ctx, k=50, pool=5)
        self.assertEqual(len(picks), 5)
        self.assertEqual([p["dense_rank"] for p in picks], [1, 2, 3, 4, 5])

    def test_exclude_same_book(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        same = [self.ctx.index_of("alpha#0001"), self.ctx.index_of("beta#0002")]
        with self._stub(same):
            picks = self.eng.candidates(seed, self.ctx, k=50, exclude_same_book=True)
        self.assertTrue(picks)
        self.assertTrue(all(p["book_id"] != "alpha" for p in picks))
        beta = next(p for p in picks if p["id"] == "beta#0002")
        self.assertEqual(beta["lexical_rank"], 1, "ranks are among eligible chunks")

    def test_empty_when_both_lists_empty(self):
        seed = Seed(text="")            # no vector, and the keyword side yields nothing
        with self._stub([]):
            self.assertEqual(self.eng.candidates(seed, self.ctx, k=5), [])
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=0), [])

    def test_keyword_only_when_seed_has_no_vector(self):
        seed = Seed(text="region releasement")
        with self._stub([1, 2, 3]):
            picks = self.eng.candidates(seed, self.ctx, k=5)
        self.assertEqual([p["id"] for p in picks], [self.chunks[i]["id"] for i in (1, 2, 3)])
        for p in picks:
            self.assertIsNone(p["dense_rank"]); self.assertIsNone(p["similarity"])
            self.assertIn("keyword only", p["why"])

    def test_deterministic(self):
        seed = self.ctx.seed_from_chunk("beta#0007")
        with self._stub([3, 9, 30]):
            a = self.eng.candidates(seed, self.ctx, k=6)
            b = self.eng.candidates(seed, self.ctx, k=6)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        self.assertEqual([p["score"] for p in a], [p["score"] for p in b])

    def test_never_mutates_context(self):
        seed = self.ctx.seed_from_chunk("beta#0007")
        before = [dict(c) for c in self.chunks]
        with self._stub([3, 9]):
            self.eng.candidates(seed, self.ctx, k=6)
        self.assertEqual(before, self.chunks)

    # -- end to end with the real lexical module -----------------------------------
    @unittest.skipUnless(_lexical_available(), "rhizome.engines.lexical not importable yet")
    def test_theme_seed_with_real_lexical(self):
        seed = Seed(text="region releasement alphatoken5", vec=self.vecs[self.ctx.index_of("alpha#0005")])
        picks = self.eng.candidates(seed, self.ctx, k=6)
        self.assertTrue(picks); self.assertLessEqual(len(picks), 6)
        self.assertIn("alpha#0005", [p["id"] for p in picks])
        self.assertTrue(any(p["lexical_rank"] is not None for p in picks))

    @unittest.skipUnless(_lexical_available(), "rhizome.engines.lexical not importable yet")
    def test_chunk_seed_with_real_lexical_gets_both_lists(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, self.ctx, k=8)
        self.assertTrue(picks)
        self.assertNotIn("alpha#0003", [p["id"] for p in picks])
        self.assertTrue(any(p["lexical_rank"] is not None for p in picks))
        self.assertTrue(any(p["dense_rank"] is not None for p in picks))


if __name__ == "__main__":
    unittest.main()
