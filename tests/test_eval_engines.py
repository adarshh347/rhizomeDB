"""The constellatory eval harness (PRD §6c) on the fixture corpus."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import bridge_pairs, make_corpus  # noqa: E402

from rhizome import engines, eval_engines
from rhizome.engines import Context

REPORT_KEYS = {"built", "embed_key", "k", "n_seeds", "n_noise", "engines"}
ROW_KEYS = {"key", "label", "ready", "n_seeds", "mean_k", "empty_rate", "mean_rank_pct",
            "median_rank", "ild", "book_spread", "cross_book_rate", "noise_fp_rate",
            "ms_per_seed", "bridge_recall", "n_bridges"}


class _NothingEngine(engines.BaseEngine):
    key = "nothing"
    label = "Nothing"
    blurb = "always finds nothing"
    needs = ["vectors"]

    def candidates(self, seed, ctx, *, k=8, **_):
        return []


class EvalEnginesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx = Context.from_arrays(cls.chunks, cls.vecs)
        # theme seeds embed only when a model is available; the fixture uses
        # random 32-d vectors, so give the noise seeds deterministic vectors
        # instead of calling the embedding model.
        import numpy as np
        rng = np.random.default_rng(3)

        def fake_seed_from_text(text, *, embed=True):
            v = None
            if embed and cls.ctx.has_vectors:
                v = rng.normal(size=cls.vecs.shape[1]).astype(np.float32)
                v /= np.linalg.norm(v)
            return engines.Seed(text=text, vec=v, label=f'theme: "{text}"')

        cls._patch = mock.patch.object(Context, "seed_from_text", staticmethod(fake_seed_from_text))
        cls._patch.start()
        cls.report = eval_engines.build_report(cls.ctx, k=5, n_seeds=12, bridges=bridge_pairs())

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()

    def _rows(self):
        return {r["key"]: r for r in self.report["engines"]}

    def test_report_shape(self):
        r = self.report
        self.assertTrue(REPORT_KEYS <= set(r))
        self.assertEqual(r["k"], 5)
        self.assertEqual(r["n_seeds"], 12)
        self.assertEqual(r["n_noise"], len(eval_engines.NOISE_SEEDS))
        self.assertEqual([x["key"] for x in r["engines"]], engines.keys())
        for row in r["engines"]:
            self.assertTrue(ROW_KEYS <= set(row), f"{row['key']} missing {ROW_KEYS - set(row)}")
            self.assertIn("sample", row)
            if not row["ready"]:
                self.assertIn("reason", row)

    def test_seed_set_deterministic_and_spaced(self):
        a = eval_engines.seed_set(self.ctx, 12)
        b = eval_engines.seed_set(self.ctx, 12)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 12)
        self.assertEqual(a[0], self.chunks[0]["id"])
        self.assertEqual(len(set(c.split("#")[0] for c in a)), 4, "seeds span all books")

    def test_metric_ranges(self):
        for row in self.report["engines"]:
            if not row["ready"]:
                continue
            with self.subTest(engine=row["key"]):
                for rate in ("empty_rate", "book_spread", "cross_book_rate",
                             "noise_fp_rate", "bridge_recall"):
                    v = row[rate]
                    if v is not None:
                        self.assertGreaterEqual(v, 0.0); self.assertLessEqual(v, 1.0)
                if row["mean_rank_pct"] is not None:
                    self.assertGreaterEqual(row["mean_rank_pct"], 0.0)
                    self.assertLessEqual(row["mean_rank_pct"], 100.0)
                self.assertGreaterEqual(row["mean_k"], 0.0)
                self.assertLessEqual(row["mean_k"], 5.0)
                self.assertGreaterEqual(row["ms_per_seed"], 0.0)
                self.assertEqual(row["n_bridges"], len(bridge_pairs()))
                self.assertLessEqual(len(row["sample"]), eval_engines.SAMPLE_SEEDS)
                for s in row["sample"]:
                    self.assertLessEqual(len(s["picks"]), eval_engines.SAMPLE_PICKS)
                    for p in s["picks"]:
                        self.assertTrue({"chunk_id", "why", "rank", "similarity"} <= set(p))

    def test_plain_is_nearer_than_band(self):
        rows = self._rows()
        self.assertLess(rows["plain"]["mean_rank_pct"], rows["band"]["mean_rank_pct"])
        self.assertLess(rows["plain"]["median_rank"], rows["band"]["median_rank"])

    def test_band_is_strictly_cross_book(self):
        self.assertEqual(self._rows()["band"]["cross_book_rate"], 1.0)
        # plain includes the seed's own book neighbours
        self.assertLess(self._rows()["plain"]["cross_book_rate"], 1.0)

    def test_bridge_recall_present(self):
        rows = self._rows()
        # plain retrieves the fixture bridges (their vectors are pulled together)
        self.assertIsNotNone(rows["plain"]["bridge_recall"])
        self.assertGreater(rows["plain"]["bridge_recall"], 0.0)

    def test_no_bridges_gives_null_recall(self):
        rep = eval_engines.build_report(self.ctx, k=3, engine_keys=["plain"], n_seeds=4, bridges=[])
        row = rep["engines"][0]
        self.assertIsNone(row["bridge_recall"]); self.assertEqual(row["n_bridges"], 0)

    def test_empty_engine_is_safe(self):
        with mock.patch.dict(engines.registry(), {"nothing": _NothingEngine()}):
            rep = eval_engines.build_report(self.ctx, k=4, engine_keys=["nothing"], n_seeds=6,
                                            bridges=bridge_pairs())
        row = rep["engines"][0]
        self.assertTrue(row["ready"])
        self.assertEqual(row["mean_k"], 0.0)
        self.assertEqual(row["empty_rate"], 1.0)
        self.assertIsNone(row["mean_rank_pct"]); self.assertIsNone(row["median_rank"])
        self.assertIsNone(row["ild"]); self.assertIsNone(row["book_spread"])
        self.assertEqual(row["noise_fp_rate"], 0.0)
        self.assertEqual(row["bridge_recall"], 0.0)
        # and the table still renders
        self.assertIn("nothing", eval_engines.format_table(rep))

    def test_not_ready_engine_gets_a_row(self):
        ctx = Context.from_arrays(self.chunks, None)   # vectorless
        rep = eval_engines.build_report(ctx, k=4, engine_keys=["band"], n_seeds=6, bridges=[])
        row = rep["engines"][0]
        self.assertFalse(row["ready"]); self.assertTrue(row["reason"])
        self.assertIsNone(row["mean_k"])
        self.assertIn("not ready", eval_engines.format_table(rep))

    def test_vectorless_ctx_noise_seeds_do_not_crash(self):
        ctx = Context.from_arrays(self.chunks, None)
        rep = eval_engines.build_report(ctx, k=4, n_seeds=6, bridges=[])
        self.assertEqual(rep["n_noise"], len(eval_engines.NOISE_SEEDS))
        for row in rep["engines"]:
            if row["ready"] and "vectors" in engines.get(row["key"]).needs:
                self.assertIsNone(row["noise_fp_rate"])

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "eval_engines.json"
            with mock.patch.object(eval_engines, "REPORT_PATH", path):
                self.assertIsNone(eval_engines.load_report())
                out = eval_engines.save_report(self.report)
                self.assertEqual(out, path)
                self.assertEqual(eval_engines.load_report(), self.report)

    def test_merge_report_refreshes_subset_rows_only(self):
        fresh = eval_engines.build_report(self.ctx, k=5, engine_keys=["plain"], n_seeds=12,
                                          bridges=bridge_pairs())
        merged = eval_engines.merge_report(self.report, fresh)
        self.assertEqual([r["key"] for r in merged["engines"]], engines.keys())
        self.assertEqual(merged["built"], fresh["built"])
        self.assertEqual({r["key"]: r for r in merged["engines"]}["plain"], fresh["engines"][0])
        # incomparable (different k) → the fresh partial report stands alone
        other = eval_engines.build_report(self.ctx, k=2, engine_keys=["plain"], n_seeds=12,
                                          bridges=[])
        self.assertEqual(eval_engines.merge_report(self.report, other), other)
        self.assertEqual(eval_engines.merge_report(None, fresh), fresh)

    def test_format_table(self):
        txt = eval_engines.format_table(self.report)
        lines = txt.splitlines()
        self.assertIn("engine", lines[2])
        for row in self.report["engines"]:
            self.assertTrue(any(l.startswith(row["key"]) for l in lines), row["key"])
        # aligned: every ready row has the same width as the header
        header_w = len(lines[2])
        for l in lines[4:4 + len(self.report["engines"])]:
            if "not ready" not in l:
                self.assertEqual(len(l), header_w, l)


if __name__ == "__main__":
    unittest.main()
