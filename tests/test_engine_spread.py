"""`spread` — the resonance band chosen by set-level diversity (DPP / facility)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed
from rhizome.engines import spread as spread_mod

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}
# the fixture corpus is small: loosen the band so there is a set to choose from
BAND = dict(skip_top=2, min_sim=0.05)


def _unit(v):
    return v / np.linalg.norm(v)


def _clustered_matrix(seed=3):
    """Two tight clusters (5 + 5) and one outlier; returns (S, labels, sims).
    Cluster centres share cos≈0.3, the outlier cos≈0.1 with each; `sims` is a
    seed-similarity per item (clusters 0.30, outlier 0.20)."""
    rng = np.random.default_rng(seed)
    e = np.eye(16)
    a = e[0]
    b = _unit(0.3 * e[0] + np.sqrt(1 - 0.09) * e[1])
    out = _unit(0.1 * e[0] + 0.1 * e[1] + e[2])
    vecs, labels, sims = [], [], []
    for c, lab in ((a, "A"), (b, "B")):
        for _ in range(5):
            vecs.append(_unit(c + 0.08 * rng.normal(size=16))); labels.append(lab); sims.append(0.30)
    vecs.append(out); labels.append("O"); sims.append(0.20)
    V = np.asarray(vecs)
    return V @ V.T, labels, np.asarray(sims)


class SpreadEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx = Context.from_arrays(cls.chunks, cls.vecs)
        cls.eng = engines.get("spread")

    def _band_ids(self, seed, **kw):
        return {c["id"] for c in self.eng.band(seed, self.ctx, **{**BAND, **kw})}

    def test_registered_and_ready(self):
        self.assertIn("spread", engines.keys())
        self.assertEqual(self.eng.ready(self.ctx), (True, ""))
        ctx_novec = Context.from_arrays(self.chunks, None)
        ok, why = self.eng.ready(ctx_novec)
        self.assertFalse(ok); self.assertTrue(why)

    def test_returns_at_most_k_with_contract_fields(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        for method in ("dpp", "facility"):
            picks = self.eng.candidates(seed, self.ctx, k=5, select=method, **BAND)
            self.assertTrue(0 < len(picks) <= 5)
            for p in picks:
                self.assertTrue(CONTRACT_KEYS <= set(p), CONTRACT_KEYS - set(p))
                self.assertEqual(p["path"], "spread")
                self.assertEqual(p["select"], method)
                self.assertIsInstance(p["covers"], int)
                self.assertGreaterEqual(p["covers"], 0)
                self.assertGreaterEqual(p["band_size"], len(picks))
                self.assertIn("set-spread pick", p["why"])
                self.assertNotEqual(p["id"], "alpha#0003")
                self.assertNotEqual(p["book_id"], "alpha")   # same-book exclusion kept
            # picks are copies, not the store's dicts
            for p in picks:
                self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])

    def test_picks_are_a_subset_of_the_band(self):
        seed = self.ctx.seed_from_chunk("beta#0007")
        band = self._band_ids(seed)
        for method in ("dpp", "facility"):
            picks = self.eng.candidates(seed, self.ctx, k=6, select=method, **BAND)
            self.assertTrue({p["id"] for p in picks} <= band)
            self.assertEqual(len({p["id"] for p in picks}), len(picks))   # no repeats

    def test_k_equal_band_size_returns_the_whole_band(self):
        seed = self.ctx.seed_from_chunk("delta#0000")
        band = self._band_ids(seed)
        self.assertGreater(len(band), 1)
        for method in ("dpp", "facility"):
            picks = self.eng.candidates(seed, self.ctx, k=len(band), select=method, **BAND)
            self.assertEqual({p["id"] for p in picks}, band)
        # covers sums to band_size - k when everything is selected
        picks = self.eng.candidates(seed, self.ctx, k=len(band), **BAND)
        self.assertEqual(sum(p["covers"] for p in picks), 0)

    def test_covers_partition_the_band(self):
        seed = self.ctx.seed_from_chunk("gamma#0011")
        band = self._band_ids(seed)
        picks = self.eng.candidates(seed, self.ctx, k=4, **BAND)
        self.assertEqual(sum(p["covers"] for p in picks), len(band) - len(picks))

    def test_empty_on_floors(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5, skip_top=2, min_sim=0.999), [])
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5, skip_top=10_000, min_sim=0.05), [])
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=0, **BAND), [])
        # a seed with no vector cannot enter the band
        self.assertEqual(self.eng.candidates(Seed(text="no vec"), self.ctx, k=5, **BAND), [])

    def test_deterministic(self):
        seed = self.ctx.seed_from_chunk("beta#0002")
        for method in ("dpp", "facility"):
            a = self.eng.candidates(seed, self.ctx, k=6, select=method, **BAND)
            b = self.eng.candidates(seed, self.ctx, k=6, select=method, **BAND)
            self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
            self.assertEqual([p["score"] for p in a], [p["score"] for p in b])

    def test_theme_seed_has_no_book_exclusion(self):
        # a theme seed built from a chunk's vector but with no chunk_id / book_id
        base = self.ctx.seed_from_chunk("alpha#0003")
        theme = Seed(text="theme", vec=base.vec)
        picks = self.eng.candidates(theme, self.ctx, k=6, **BAND)
        self.assertTrue(0 < len(picks) <= 6)
        band = self._band_ids(theme)
        self.assertTrue({p["id"] for p in picks} <= band)
        # without a book_id nothing is excluded → the seed's own book may appear
        self.assertTrue(any(c.startswith("alpha#") for c in band))
        for p in picks:
            self.assertEqual(p["corpus_size"], len(self.chunks))
            self.assertIsNotNone(p["similarity"])

    def test_bad_select_raises(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")
        with self.assertRaises(ValueError):
            self.eng.candidates(seed, self.ctx, k=3, select="mmr", **BAND)

    def test_never_mutates_store_chunks(self):
        before = [dict(c) for c in self.ctx.chunks]
        seed = self.ctx.seed_from_chunk("delta#0004")
        self.eng.candidates(seed, self.ctx, k=5, **BAND)
        self.assertEqual(before, self.ctx.chunks)


class SelectDiverseTests(unittest.TestCase):
    """The set selectors on a hand-built matrix: two tight clusters + an outlier."""

    def test_spreads_across_clusters(self):
        S, labels, sims = _clustered_matrix()
        # dpp with the engine's quality (q = exp(alpha * sim)): the clusters are
        # more resonant than the outlier, so k=2 takes one from each cluster and
        # k=3 adds the outlier rather than a second member of a cluster.
        # facility ignores quality: coverage alone gives the same shape.
        for method, q in (("dpp", np.exp(3.0 * sims)), ("facility", None), ("facility", sims)):
            two = spread_mod.select_diverse(S, q, 2, method)
            self.assertEqual(len(two), 2)
            self.assertEqual({labels[i] for i in two}, {"A", "B"},
                             f"{method}: k=2 should take one from each cluster")
            three = spread_mod.select_diverse(S, q, 3, method)
            self.assertEqual(len(three), 3)
            self.assertEqual({labels[i] for i in three}, {"A", "B", "O"},
                             f"{method}: k=3 should add the outlier, not a 2nd cluster member")
            self.assertEqual(three[:2], two, "greedy: prefix-stable")
        # a pure-diversity dpp (unit quality) still never doubles up a cluster at k=3
        three = spread_mod.select_diverse(S, None, 3, "dpp")
        self.assertEqual({labels[i] for i in three}, {"A", "B", "O"})

    def test_quality_breaks_ties_within_a_cluster(self):
        S, labels, sims = _clustered_matrix()
        q = np.ones(len(labels)); q[3] = 4.0          # a much better item in cluster A
        picks = spread_mod.select_diverse(S, q, 1, "dpp")
        self.assertEqual(picks, [3])

    def test_returns_at_most_n_and_deterministic(self):
        S, labels, sims = _clustered_matrix()
        for method in ("dpp", "facility"):
            a = spread_mod.select_diverse(S, None, 50, method)
            b = spread_mod.select_diverse(S, None, 50, method)
            self.assertEqual(a, b)
            self.assertLessEqual(len(a), len(labels))
            self.assertEqual(len(set(a)), len(a))
        self.assertEqual(spread_mod.select_diverse(np.zeros((0, 0)), None, 3, "dpp"), [])

    def test_dpp_drops_exact_duplicates(self):
        v = _unit(np.array([1.0, 2.0, 3.0]))
        w = _unit(np.array([-3.0, 1.0, 0.0]))
        V = np.stack([v, v, w])
        S = V @ V.T
        picks = spread_mod.select_diverse(S, None, 3, "dpp")
        self.assertEqual(len(picks), 2)          # the duplicate adds no volume
        self.assertEqual({0, 2}, set(picks))

    def test_facility_gain_is_coverage(self):
        S, _, _ = _clustered_matrix()
        picks, gains = spread_mod.select_with_gains(S, None, 3, "facility")
        # first gain = the column sum (coverage from nothing); gains are non-increasing
        self.assertAlmostEqual(gains[0], float(np.maximum(S[:, picks[0]], 0).sum()))
        self.assertTrue(all(g1 >= g2 - 1e-9 for g1, g2 in zip(gains, gains[1:])))


if __name__ == "__main__":
    unittest.main()
