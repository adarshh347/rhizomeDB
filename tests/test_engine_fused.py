"""`fused` engine — the constellation: union of paths, RRF-merged with
provenance weights, re-ranked by relevance × surprise, set-spread."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed
from rhizome.engines import fused as fused_mod

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}
SEED = "delta#0000"      # a seed for which the fixture band is non-empty


def _band_only(ctx):
    """Silence every optional path: no concepts, no marks, no structural index."""
    ctx._side["concepts"] = None
    ctx._side["annotations"] = []
    ctx._side["structural"] = None
    return ctx


class FusedBandOnlyTests(unittest.TestCase):
    def setUp(self):
        self.chunks, self.vecs = make_corpus()
        self.ctx = _band_only(Context.from_arrays(self.chunks, self.vecs))
        self.eng = engines.get("fused")
        self.seed = self.ctx.seed_from_chunk(SEED)

    def test_ready_needs_vectors_only(self):
        self.assertEqual(self.eng.needs, ["vectors"])
        self.assertEqual(self.eng.ready(self.ctx), (True, ""))
        ctx = Context.from_arrays(self.chunks, None)
        ok, why = self.eng.ready(ctx)
        self.assertFalse(ok); self.assertTrue(why)
        self.assertEqual(self.eng.candidates(self.seed, ctx, k=5), [])

    def test_contract_and_k(self):
        picks = self.eng.candidates(self.seed, self.ctx, k=2)
        self.assertTrue(picks)
        self.assertLessEqual(len(picks), 2)
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), CONTRACT_KEYS - set(p))
            self.assertEqual(p["corpus_size"], len(self.chunks))
            self.assertTrue(p["path"].startswith("fused:"))
            self.assertIn("paths", p); self.assertIn("contributions", p)
            self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])
        self.assertNotIn(SEED, [p["id"] for p in picks])

    def test_band_only_is_a_reranked_subset_of_band(self):
        band = engines.get("band").candidates(self.seed, self.ctx, k=fused_mod.POOL_EACH)
        band_ids = {p["id"] for p in band}
        self.assertTrue(band_ids)
        picks = self.eng.candidates(self.seed, self.ctx, k=8)
        self.assertTrue(picks)
        self.assertTrue({p["id"] for p in picks} <= band_ids)
        for p in picks:
            self.assertEqual(p["paths"], ["band"])
            self.assertEqual(p["path"], "fused:band")
            self.assertEqual(set(p["contributions"]), {"band"})
            self.assertTrue(p["why"].startswith("band — "))
            self.assertIn("resonance band", p["why"])
            self.assertTrue(p["cross_book"])
        scores = [p["score"] for p in picks]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # relevance × surprise: the top band pick (rank 0 → 1/10) times its surprise
        top = picks[0]
        self.assertAlmostEqual(top["score"], top["relevance"] * top["surprise"], places=3)

    def test_empty_when_band_is_empty(self):
        seed = self.ctx.seed_from_chunk("alpha#0003")     # band finds nothing here
        self.assertEqual(engines.get("band").candidates(seed, self.ctx, k=12), [])
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5), [])

    def test_floor_drops_noise_even_when_a_path_found_it(self):
        picks = self.eng.candidates(self.seed, self.ctx, k=8, min_sim=0.9)
        self.assertEqual(picks, [])

    def test_deterministic(self):
        a = self.eng.candidates(self.seed, self.ctx, k=5)
        b = self.eng.candidates(self.seed, self.ctx, k=5)
        self.assertEqual([(p["id"], p["score"]) for p in a], [(p["id"], p["score"]) for p in b])

    def test_theme_seed_with_vector(self):
        seed = Seed(text="the structure of the move", vec=self.vecs[self.ctx.index_of(SEED)])
        picks = self.eng.candidates(seed, self.ctx, k=5)
        self.assertTrue(picks)
        for p in picks:
            self.assertFalse(p["cross_book"])          # no seed book → no cross-book bonus
            self.assertIsNotNone(p["similarity"])
            self.assertLess(p["similarity"], fused_mod.DEDUP_SIM)
            self.assertGreaterEqual(p["similarity"], fused_mod.MIN_SIM)

    def test_theme_seed_without_vector_is_empty(self):
        seed = Seed(text="repose and flash", vec=None)
        self.assertEqual(self.eng.candidates(seed, self.ctx, k=5), [])


class FusedMultiPathTests(unittest.TestCase):
    """Hand-injected concept + marks sides: two paths agreeing beat one."""

    def setUp(self):
        self.chunks, self.vecs = make_corpus()
        self.ctx = Context.from_arrays(self.chunks, self.vecs)
        self.ctx._side["structural"] = None
        self.eng = engines.get("fused")
        self.seed = self.ctx.seed_from_chunk(SEED)
        # band for delta#0000: gamma#0006 (0.214), beta#0010 (0.184), gamma#0009 (0.158)
        # concept side: seed shares "move" with beta#0010 (band pick), alpha#0009 (an
        # obvious top-8 hit the band skipped) and gamma#0010 (below the noise floor)
        self.ctx._side["concepts"] = {"chunk_concepts": {
            SEED: ["move", "figure"], "beta#0010": ["move"], "alpha#0009": ["move"],
            "gamma#0010": ["move"], "delta#0003": ["figure"],
        }}
        self.ctx._side["edges"] = []
        # marks side: one note on beta#0010, embedded exactly at the seed
        self.ctx._side["annotations"] = [{
            "id": "an_000", "kind": "note", "target": "beta#0010", "quote": "wonder",
            "note": "the move as a flash", "color": "amber", "book_id": "beta",
        }]
        self.ctx._side["marks_vecs"] = {"ids": ("an_000",),
                                        "vecs": self.seed.vec[None, :].astype(np.float32)}
        self.assertEqual(engines.get("concept").ready(self.ctx), (True, ""))
        self.assertEqual(engines.get("marks").ready(self.ctx), (True, ""))

    def test_multi_path_chunk_outranks_single_path(self):
        picks = self.eng.candidates(self.seed, self.ctx, k=8)
        by = {p["id"]: p for p in picks}
        self.assertIn("beta#0010", by); self.assertIn("gamma#0006", by)
        multi, single = by["beta#0010"], by["gamma#0006"]
        self.assertEqual(sorted(multi["paths"]), ["band", "concept", "marks"])
        self.assertEqual(single["paths"], ["band"])
        self.assertGreater(multi["score"], single["score"])
        self.assertLess(picks.index(multi), picks.index(single))
        # provenance: marks (1.5) outweighs concept (1.1) outweighs band (1.0)
        self.assertEqual(multi["paths"][0], "marks")
        self.assertEqual(multi["path"], "fused:marks+concept+band")
        self.assertTrue(multi["why"].startswith("marks + concept + band — your note"))
        self.assertAlmostEqual(multi["relevance"], sum(multi["contributions"].values()), places=4)
        # pass-through extras from the paths that found it
        self.assertEqual(multi["annotation_id"], "an_000")
        self.assertEqual(multi["note"], "the move as a flash")
        self.assertEqual(multi["concepts"], ["move"])
        self.assertNotIn("annotation_id", single)

    def test_union_reaches_past_the_band_and_respects_floors(self):
        picks = self.eng.candidates(self.seed, self.ctx, k=8)
        ids = [p["id"] for p in picks]
        self.assertIn("alpha#0009", ids)               # concept-only, skipped by band
        by = {p["id"]: p for p in picks}
        self.assertEqual(by["alpha#0009"]["paths"], ["concept"])
        self.assertTrue(by["alpha#0009"]["why"].startswith("concept — via concepts: move"))
        self.assertNotIn("gamma#0010", ids)            # concept found it, but sim < MIN_SIM
        self.assertNotIn(SEED, ids)
        self.assertNotIn("delta#0003", ids)            # same book, excluded by every path

    def test_k_and_spread_respected(self):
        for k in (1, 2, 3):
            picks = self.eng.candidates(self.seed, self.ctx, k=k)
            self.assertLessEqual(len(picks), k)
            self.assertTrue(picks)
        all_ = self.eng.candidates(self.seed, self.ctx, k=8)
        one = self.eng.candidates(self.seed, self.ctx, k=1)
        self.assertEqual(one[0]["id"], all_[0]["id"])   # the strongest survives the spread

    def test_deterministic_across_calls(self):
        a = self.eng.candidates(self.seed, self.ctx, k=4)
        b = self.eng.candidates(self.seed, self.ctx, k=4)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        self.assertEqual([p["contributions"] for p in a], [p["contributions"] for p in b])


if __name__ == "__main__":
    unittest.main()
