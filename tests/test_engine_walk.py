"""`walk` — the line of flight: sequential hops, one new book per hop."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}
# the fixture band is thin: skip_top=0 lets a walk actually get going
LOOSE = dict(skip_top=0, min_sim=0.0)


class WalkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx = Context.from_arrays(cls.chunks, cls.vecs)
        cls.eng = engines.get("walk")

    def test_registered_and_ready(self):
        self.assertIn("walk", engines.keys())
        self.assertEqual(self.eng.ready(self.ctx), (True, ""))
        ok, why = self.eng.ready(Context.from_arrays(self.chunks, None))
        self.assertFalse(ok); self.assertTrue(why)

    def test_contract_fields_and_extras(self):
        seed = self.ctx.seed_from_chunk("delta#0000")
        picks = self.eng.candidates(seed, self.ctx, k=8, **LOOSE)
        self.assertTrue(picks)
        self.assertLessEqual(len(picks), 8)
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), f"missing {CONTRACT_KEYS - set(p)}")
            self.assertEqual(p["path"], "walk")
            self.assertEqual(p["corpus_size"], len(self.chunks))
            self.assertIn("hop", p); self.assertIn("from_id", p); self.assertIn("hop_similarity", p)
            self.assertEqual(p["score"], p["hop_similarity"])
            self.assertIn(f"hop {p['hop']}", p["why"])
            self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])
        # similarity / rank are relative to the ORIGINAL seed
        sims = self.vecs @ seed.vec
        for p in picks:
            self.assertAlmostEqual(p["similarity"], float(sims[self.ctx.index_of(p["id"])]), places=3)

    def test_hops_are_sequential_and_chain(self):
        seed = self.ctx.seed_from_chunk("delta#0000")
        picks = self.eng.candidates(seed, self.ctx, k=8, **LOOSE)
        self.assertGreaterEqual(len(picks), 2)
        self.assertEqual([p["hop"] for p in picks], list(range(1, len(picks) + 1)))
        self.assertEqual(picks[0]["from_id"], seed.chunk_id)
        for prev, cur in zip(picks, picks[1:]):
            self.assertEqual(cur["from_id"], prev["id"])
            # hop_similarity is the cosine to the previous step
            a, b = self.ctx.index_of(prev["id"]), self.ctx.index_of(cur["id"])
            self.assertAlmostEqual(cur["hop_similarity"], float(self.vecs[a] @ self.vecs[b]), places=3)
        # hop 1: cosine to the seed itself
        self.assertAlmostEqual(picks[0]["hop_similarity"], picks[0]["similarity"], places=3)

    def test_no_book_repeats_and_stops_when_books_run_out(self):
        for cid in ("delta#0000", "gamma#0011", "alpha#0003"):
            seed = self.ctx.seed_from_chunk(cid)
            picks = self.eng.candidates(seed, self.ctx, k=10, **LOOSE)
            books = [p["book_id"] for p in picks]
            self.assertEqual(len(books), len(set(books)), "a book was revisited")
            self.assertNotIn(seed.book_id, books)
            self.assertLessEqual(len(picks), 3, "4 books → at most 3 hops from a chunk seed")
            self.assertNotIn(cid, [p["id"] for p in picks])

    def test_revisit_books_lets_the_walk_continue(self):
        seed = self.ctx.seed_from_chunk("delta#0000")
        strict = self.eng.candidates(seed, self.ctx, k=10, **LOOSE)
        loose = self.eng.candidates(seed, self.ctx, k=10, revisit_books=True, **LOOSE)
        self.assertEqual([p["id"] for p in loose[:len(strict)]], [p["id"] for p in strict])
        self.assertGreater(len(loose), len(strict))
        self.assertLessEqual(len(loose), 10)
        ids = [p["id"] for p in loose]
        self.assertEqual(len(ids), len(set(ids)), "a chunk was picked twice")
        # a revisit never steps back into the book it is standing in
        for prev, cur in zip(loose, loose[1:]):
            self.assertNotEqual(prev["book_id"], cur["book_id"])

    def test_returns_at_most_k(self):
        seed = self.ctx.seed_from_chunk("delta#0000")
        for k in (1, 2):
            picks = self.eng.candidates(seed, self.ctx, k=k, **LOOSE)
            self.assertEqual(len(picks), k)
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=0, **LOOSE), [])

    def test_empty_on_floors(self):
        seed = self.ctx.seed_from_chunk("delta#0000")
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5, min_sim=0.99), [])
        rng = np.random.default_rng(1)
        v = rng.normal(size=self.vecs.shape[1]).astype(np.float32)
        v -= self.vecs.T @ (self.vecs @ v) / len(self.vecs)
        v /= np.linalg.norm(v)
        self.assertEqual(self.eng.candidates(Seed(text="noise", vec=v), self.ctx, k=5, min_sim=0.99), [])
        # no vector at all (lexical-only theme seed) → nothing, no raise
        self.assertEqual(self.eng.candidates(Seed(text="only words"), self.ctx, k=5), [])

    def test_deterministic(self):
        seed = self.ctx.seed_from_chunk("gamma#0011")
        a = self.eng.candidates(seed, self.ctx, k=6, **LOOSE)
        b = self.eng.candidates(seed, self.ctx, k=6, **LOOSE)
        self.assertEqual(a, b)

    def test_theme_seed_starts_with_no_visited_books(self):
        seed = Seed(text="theme", vec=self.vecs[5])   # an alpha chunk's vector, no chunk_id
        picks = self.eng.candidates(seed, self.ctx, k=10, **LOOSE)
        self.assertTrue(picks)
        self.assertLessEqual(len(picks), 4, "4 books → at most 4 hops from a theme")
        self.assertIsNone(picks[0]["from_id"])
        self.assertEqual(picks[0]["hop"], 1)
        self.assertIn("theme", picks[0]["why"])
        books = [p["book_id"] for p in picks]
        self.assertEqual(len(books), len(set(books)))
        # a theme can land in any book, including alpha (no seed book to exclude)
        self.assertIn("alpha", books)
        for prev, cur in zip(picks, picks[1:]):
            self.assertEqual(cur["from_id"], prev["id"])


if __name__ == "__main__":
    unittest.main()
