"""`echo` — same-book, far-from-the-seed retrieval."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus, PER_BOOK  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed
from rhizome.engines.echo import build_book_order

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}


class EchoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx = Context.from_arrays(cls.chunks, cls.vecs)
        cls.eng = engines.get("echo")
        cls.pos = build_book_order(cls.chunks)["pos"]

    def _picks(self, cid="alpha#0003", **kw):
        seed = self.ctx.seed_from_chunk(cid)
        kw.setdefault("gap", 3)
        kw.setdefault("min_sim", 0.0)
        return seed, self.eng.candidates(seed, self.ctx, **kw)

    def test_registered_and_ready(self):
        self.assertIn("echo", engines.keys())
        self.assertEqual(self.eng.ready(self.ctx), (True, ""))
        ok, why = self.eng.ready(Context.from_arrays(self.chunks, None))
        self.assertFalse(ok); self.assertTrue(why)

    def test_contract_fields_and_extras(self):
        seed, picks = self._picks(k=4)
        self.assertTrue(picks)
        self.assertLessEqual(len(picks), 4)
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), CONTRACT_KEYS - set(p))
            self.assertEqual(p["path"], "echo")
            self.assertIsInstance(p["distance"], int)
            self.assertEqual(p["heading"], self.ctx.chunks[self.ctx.index_of(p["id"])]["heading"])
            self.assertIn("passages away", p["why"])
            self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])

    def test_same_book_only_seed_excluded_and_gap_respected(self):
        for cid in ("alpha#0003", "beta#0007", "delta#0000", "gamma#0011"):
            seed, picks = self._picks(cid, k=8, gap=4)
            seed_pos = self.pos[self.ctx.index_of(cid)]
            self.assertTrue(picks, cid)
            for p in picks:
                self.assertEqual(p["book_id"], seed.book_id)
                self.assertNotEqual(p["id"], cid)
                d = abs(self.pos[self.ctx.index_of(p["id"])] - seed_pos)
                self.assertGreaterEqual(d, 4)
                self.assertEqual(p["distance"], d)

    def test_default_gap_wider_than_a_short_book_gives_nothing(self):
        # PER_BOOK chunks per fixture book: with gap >= PER_BOOK nothing survives — no padding
        seed = self.ctx.seed_from_chunk("alpha#0003")
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5, gap=PER_BOOK, min_sim=0.0), [])

    def test_k_respected(self):
        for k in (1, 2, 3):
            _, picks = self._picks(k=k, gap=1)
            self.assertEqual(len(picks), k)

    def test_min_sim_floor_empties(self):
        _, picks = self._picks(k=5, min_sim=0.999)
        self.assertEqual(picks, [])

    def test_dedup_ceiling_drops_repeats(self):
        # make a near-verbatim repeat of alpha#0003 far away in the same book
        chunks = [dict(c) for c in self.chunks]
        vecs = self.vecs.copy()
        i, j = self.ctx.index_of("alpha#0003"), self.ctx.index_of("alpha#0011")
        vecs[j] = vecs[i]
        ctx = Context.from_arrays(chunks, vecs)
        seed = ctx.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, ctx, k=8, gap=3, min_sim=0.0)
        self.assertNotIn("alpha#0011", [p["id"] for p in picks])
        picks = self.eng.candidates(seed, ctx, k=8, gap=3, min_sim=0.0, dedup_sim=1.01)
        self.assertIn("alpha#0011", [p["id"] for p in picks])

    def test_deterministic(self):
        _, a = self._picks(k=5)
        _, b = self._picks(k=5)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])

    def test_theme_seed_is_empty_unless_book_given(self):
        seed = Seed(text="theme", vec=self.vecs[self.ctx.index_of("beta#0002")])
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5, min_sim=0.0), [])
        picks = self.eng.candidates(seed, self.ctx, k=5, min_sim=0.0, book_id="beta")
        self.assertTrue(picks)
        for p in picks:
            self.assertEqual(p["book_id"], "beta")
            self.assertIsNone(p["distance"])
            self.assertIn("echo inside", p["why"])
        # a theme with no vector at all is empty too
        self.assertEqual(self.eng.candidates(Seed(text="x"), self.ctx, k=5, book_id="beta"), [])

    def test_side_index_can_be_prepopulated(self):
        ctx = Context.from_arrays(self.chunks, self.vecs)
        ctx._side["book_order"] = build_book_order(self.chunks)
        seed = ctx.seed_from_chunk("gamma#0005")
        self.assertTrue(self.eng.candidates(seed, ctx, k=3, gap=2, min_sim=0.0))

    def test_mmr_spreads_across_sections(self):
        # with lambda 0 (pure diversity) picks should touch more than one heading
        _, picks = self._picks("delta#0000", k=4, gap=1, mmr_lambda=0.0)
        self.assertGreater(len({p["heading"] for p in picks}), 1)


if __name__ == "__main__":
    unittest.main()
