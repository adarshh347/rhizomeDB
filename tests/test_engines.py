"""The engine contract + the parity gate (PRD Phase 0).

Every registered engine is run against the in-memory fixture corpus and checked
for the shared contract (shape, disclosure fields, no padding, determinism).
The `band` engine is additionally proven byte-identical to a direct
`Store.connections()` call — on the fixture always, and on the real index when
one is built (skipped otherwise).
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import config, engines
from rhizome.engines import Context, Seed

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx = Context.from_arrays(cls.chunks, cls.vecs)

    def test_registry_lists_the_reference_engines(self):
        keys = engines.keys()
        for k in ("plain", "band"):
            self.assertIn(k, keys)
        self.assertEqual(keys[0], "band", "band is the default and listed first")

    def test_every_engine_honours_the_contract(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        for eng in engines.all_engines():
            ok, why = eng.ready(self.ctx)
            if not ok:
                continue  # engines that need side data absent from the fixture
            with self.subTest(engine=eng.key):
                picks = eng.candidates(seed, self.ctx, k=5)
                self.assertLessEqual(len(picks), 5)
                for p in picks:
                    self.assertTrue(CONTRACT_KEYS <= set(p), f"missing {CONTRACT_KEYS - set(p)}")
                    self.assertEqual(p["corpus_size"], len(self.chunks))
                    self.assertIsInstance(p["why"], str)
                    self.assertTrue(p["why"])
                    self.assertIn(eng.key, p["path"])
                    if p["rank"] is not None:
                        self.assertGreaterEqual(p["rank"], 0)
                # deterministic
                again = eng.candidates(seed, self.ctx, k=5)
                self.assertEqual([p["id"] for p in picks], [p["id"] for p in again])
                # copies, never the store's own dicts
                for p in picks:
                    self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])

    def test_engines_never_pad_past_the_floor(self):
        # a seed orthogonal to everything: below MIN_SIM for all → band is empty
        rng = np.random.default_rng(1)
        v = rng.normal(size=self.vecs.shape[1]).astype(np.float32)
        v -= self.vecs.T @ (self.vecs @ v) / len(self.vecs)   # push away from the corpus
        v /= np.linalg.norm(v)
        seed = Seed(text="noise", vec=v)
        picks = engines.get("band").candidates(seed, self.ctx, k=5, min_sim=0.99)
        self.assertEqual(picks, [])

    def test_describe_all_reports_readiness(self):
        cards = engines.describe_all(self.ctx)
        self.assertEqual(len(cards), len(engines.keys()))
        for c in cards:
            self.assertIn("ready", c); self.assertIn("reason", c); self.assertIn("blurb", c)
            self.assertTrue(c["label"])


class ParityTests(unittest.TestCase):
    """`band` must reproduce `Store.connections()` exactly (Phase 0 gate)."""

    def _strip(self, picks):
        return [{k: v for k, v in p.items() if k not in ("score", "path", "why")}
                for p in picks]

    def test_band_matches_store_on_fixture(self):
        chunks, vecs = make_corpus()
        ctx = Context.from_arrays(chunks, vecs)
        band = engines.get("band")
        for cid in ("alpha#0003", "beta#0007", "delta#0000", "gamma#0011"):
            seed = ctx.seed_from_chunk(cid)
            direct = ctx.store.connections(seed.vec, seed_book_id=seed.book_id,
                                           seed_author=seed.author, k=6)
            via = band.candidates(seed, ctx, k=6)
            self.assertEqual(self._strip(via), direct)

    def test_band_matches_store_on_real_index(self):
        if not (config.CHUNKS_PATH.exists() and config.EMBEDDINGS_PATH.exists()):
            self.skipTest("real index not built")
        from rhizome.store import Store
        store = Store()
        ctx = Context.from_store(store)
        band = engines.get("band")
        n = len(store)
        for i in range(0, n, max(1, n // 30)):
            cid = store.chunks[i]["id"]
            seed = ctx.seed_from_chunk(cid)
            direct = store.connections(seed.vec, seed_book_id=seed.book_id,
                                       seed_author=seed.author)
            via = band.candidates(seed, ctx)
            self.assertEqual(self._strip(via), direct, f"parity broke on {cid}")


class NoiseFloorTests(unittest.TestCase):
    """The willingness to find nothing: a gated context returns [] from every
    gated engine when the seed's best match sits below the floor; plain never
    gates; an ungated context (tests, uncalibrated models) is unaffected."""

    def setUp(self):
        self.chunks, self.vecs = make_corpus()
        self.ctx = Context.from_arrays(self.chunks, self.vecs)
        rng = np.random.default_rng(3)
        v = rng.normal(size=self.vecs.shape[1]).astype(np.float32)
        v -= self.vecs.T @ (self.vecs @ v) / len(self.vecs)
        self.noise = Seed(text="word salad", vec=v / np.linalg.norm(v))
        self.best = float((self.vecs @ self.noise.vec).max())

    def test_ungated_context_is_unaffected(self):
        self.assertIsNone(self.ctx.noise_floor)
        picks = engines.get("band").candidates(self.noise, self.ctx, k=4, min_sim=-1.0)
        self.assertTrue(picks)

    def test_gated_context_returns_nothing_from_gated_engines(self):
        self.ctx.noise_floor = self.best + 0.05
        for eng in engines.all_engines():
            if not eng.ready(self.ctx)[0] or not getattr(eng, "noise_gate", False):
                continue
            with self.subTest(engine=eng.key):
                self.assertEqual(eng.candidates(self.noise, self.ctx, k=4), [])
        # plain is the baseline that always answers
        self.assertTrue(engines.get("plain").candidates(self.noise, self.ctx, k=4))

    def test_gate_opens_when_the_seed_resonates(self):
        self.ctx.noise_floor = self.best - 0.05
        picks = engines.get("band").candidates(self.noise, self.ctx, k=4, min_sim=-1.0)
        self.assertTrue(picks)
        from rhizome.engines.base import best_match
        band = engines.get("band")
        self.ctx.noise_floor = None
        seed = next(s for s in (self.ctx.seed_from_chunk(c["id"]) for c in self.chunks)
                    if band.candidates(s, self.ctx, k=4))
        self.ctx.noise_floor = best_match(seed, self.ctx) - 0.01
        self.assertTrue(band.candidates(seed, self.ctx, k=4))

    def test_from_store_reads_the_calibration(self):
        from rhizome.engines.base import _ArrayStore
        ctx = Context.from_store(_ArrayStore(self.chunks, self.vecs), "bge-base")
        self.assertEqual(ctx.noise_floor, config.noise_floor("bge-base"))
        self.assertIsNotNone(ctx.noise_floor)


class PlainTests(unittest.TestCase):
    def test_plain_is_nearest_and_includes_same_book(self):
        chunks, vecs = make_corpus()
        ctx = Context.from_arrays(chunks, vecs)
        seed = ctx.seed_from_chunk("alpha#0003")
        picks = engines.get("plain").candidates(seed, ctx, k=5)
        self.assertEqual(len(picks), 5)
        sims = [p["similarity"] for p in picks]
        self.assertEqual(sims, sorted(sims, reverse=True))
        self.assertNotIn("alpha#0003", [p["id"] for p in picks])
        # nearest, ranks are the top of the sort (0 is the seed itself, excluded)
        self.assertEqual([p["rank"] for p in picks], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
