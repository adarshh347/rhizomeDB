"""`marks` engine — retrieval over the reader's own highlights/notes."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines, workspace
from rhizome import embed as embed_mod
from rhizome.engines import Context, Seed
from rhizome.engines.marks import MarksEngine, mark_text

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-12)


def _ann(i, kind, target, quote="", note="", **extra):
    a = {"id": f"an_{i:03d}", "kind": kind, "target": target, "quote": quote,
         "note": note, "color": "amber", "created": "2026-08-10 00:00:00",
         "book_id": target.split("#")[0]}
    a.update(extra)
    return a


class MarksTests(unittest.TestCase):
    def setUp(self):
        self.chunks, self.vecs = make_corpus()
        self.ctx = Context.from_arrays(self.chunks, self.vecs)
        self.eng = engines.get("marks")
        self.seed = self.ctx.seed_from_chunk("alpha#0003")
        sv = self.seed.vec
        # an off-axis unit vector orthogonal to the seed, for controlled cosines
        rng = np.random.default_rng(3)
        r = rng.normal(size=len(sv)).astype(np.float32)
        r -= (r @ sv) * sv
        self.off = _unit(r)
        self.anns = [
            _ann(0, "note", "beta#0007", note="the flash and the region rhyme"),          # strong
            _ann(1, "highlight", "beta#0007", quote="repose in wonder"),                  # weaker, same chunk
            _ann(2, "highlight", "delta#0002", quote="the structure of the move"),        # mid
            _ann(3, "note", "gamma#0005", note="too far away"),                           # below floor
            _ann(4, "note", "alpha#0003", note="my own seed"),                            # seed chunk
            _ann(5, "note", "alpha#0009", note="same book as seed"),                      # same book
            _ann(6, "highlight", "nowhere#0000", quote="orphan-ish"),                     # unresolvable
            _ann(7, "note", "delta#0008", note="", quote=""),                             # empty text
            _ann(8, "note", "beta#0001", note="lost", orphaned=True),                     # orphaned
            _ann(9, "highlight", "legacy label", quote="via chunk_ids", chunk_ids=["gamma#0011"]),
            _ann(10, "highlight", "legacy label 2", quote="via passage_id", passage_id="delta#0010"),
        ]
        self.ctx._side["annotations"] = self.anns
        usable = [a for a in self.anns if mark_text(a) and not a.get("orphaned")]
        self.assertEqual(len(usable), 9)
        cos = {"an_000": 0.9, "an_001": 0.6, "an_002": 0.5, "an_003": 0.1, "an_004": 0.95,
               "an_005": 0.7, "an_006": 0.8, "an_009": 0.4, "an_010": 0.3}
        vecs = np.stack([_unit(cos[a["id"]] * sv + np.sqrt(1 - cos[a["id"]] ** 2) * self.off)
                         for a in usable])
        self.ctx._side["marks_vecs"] = {"ids": tuple(a["id"] for a in usable), "vecs": vecs}

    def _picks(self, **kw):
        return self.eng.candidates(self.seed, self.ctx, **kw)

    def test_ready_and_contract(self):
        self.assertEqual(self.eng.ready(self.ctx), (True, ""))
        picks = self._picks(k=3)
        self.assertLessEqual(len(picks), 3)
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), CONTRACT_KEYS - set(p))
            self.assertEqual(p["path"], "marks")
            self.assertEqual(p["corpus_size"], len(self.chunks))
            self.assertIsNotNone(p["rank"])
            for extra in ("annotation_id", "kind", "color", "quote", "note", "mark_similarity"):
                self.assertIn(extra, p)
            self.assertIsNot(p, self.ctx.chunks[self.ctx.index_of(p["id"])])

    def test_best_mark_per_chunk_sorted_desc_and_resolution(self):
        picks = self._picks(k=10)
        ids = [p["id"] for p in picks]
        # beta#0007 (0.9 note beats 0.6 highlight), alpha#0009 (0.7), delta#0002 (0.5),
        # gamma#0011 via chunk_ids (0.4), delta#0010 via passage_id (0.3)
        self.assertEqual(ids, ["beta#0007", "alpha#0009", "delta#0002", "gamma#0011", "delta#0010"])
        self.assertEqual(picks[0]["annotation_id"], "an_000")
        self.assertEqual(picks[0]["kind"], "note")
        self.assertTrue(picks[0]["why"].startswith("your note — “the flash"))
        self.assertTrue(picks[2]["why"].startswith("your highlight — “the structure"))
        self.assertAlmostEqual(picks[0]["mark_similarity"], 0.9, places=3)
        scores = [p["score"] for p in picks]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # excluded: seed chunk, unresolvable, empty, orphaned, below floor
        for bad in ("alpha#0003", "gamma#0005", "beta#0001", "delta#0008"):
            self.assertNotIn(bad, ids)

    def test_k_and_floor_and_same_book(self):
        self.assertEqual(len(self._picks(k=2)), 2)
        self.assertEqual([p["id"] for p in self._picks(k=10, min_sim=0.65)],
                         ["beta#0007", "alpha#0009"])
        self.assertEqual(self._picks(k=10, min_sim=0.99), [])
        ids = [p["id"] for p in self._picks(k=10, exclude_same_book=True)]
        self.assertNotIn("alpha#0009", ids)
        self.assertIn("beta#0007", ids)

    def test_deterministic(self):
        a = [p["id"] for p in self._picks(k=5)]
        b = [p["id"] for p in self._picks(k=5)]
        self.assertEqual(a, b)

    def test_theme_seed(self):
        # a theme seed with the same vector as the chunk seed: seed chunk no longer excluded
        theme = Seed(text="the open region", vec=self.seed.vec)
        ids = [p["id"] for p in self.eng.candidates(theme, self.ctx, k=10)]
        self.assertEqual(ids[0], "alpha#0003")
        self.assertIn("beta#0007", ids)
        # no vector → nothing
        self.assertEqual(self.eng.candidates(Seed(text="x", vec=None), self.ctx, k=5), [])

    def test_ready_false_when_no_marks(self):
        ctx = Context.from_arrays(self.chunks, self.vecs)
        ctx._side["annotations"] = []
        ok, why = self.eng.ready(ctx)
        self.assertFalse(ok)
        self.assertEqual(why, "no marks yet — highlight or note something first")
        ctx._side["annotations"] = [_ann(0, "note", "b#0", note="lost", orphaned=True)]
        self.assertFalse(self.eng.ready(ctx)[0])
        ctx._side["annotations"] = [_ann(0, "note", "nowhere#0000", note="unresolvable")]
        ctx._side["marks_vecs"] = {"ids": ("an_000",), "vecs": self.seed.vec[None, :]}
        ok, why = self.eng.ready(ctx)
        self.assertFalse(ok)
        self.assertIn("this corpus", why)
        self.assertEqual(self.eng.candidates(self.seed, ctx, k=5), [])

    def test_mark_vecs_rebuilt_when_ids_change(self):
        calls = []
        eng = MarksEngine()

        def fake_build(marks):
            calls.append(len(marks))
            return np.tile(self.seed.vec, (len(marks), 1))

        # monkeypatch the embed path by pre-seeding a stale cache and swapping embed_texts
        import rhizome.embed as embed_mod
        orig = embed_mod.embed_texts
        embed_mod.embed_texts = lambda texts, key, **kw: fake_build(texts)
        try:
            self.ctx._side["marks_vecs"] = {"ids": ("stale",), "vecs": np.zeros((1, 32), np.float32)}
            picks = eng.candidates(self.seed, self.ctx, k=10)
            self.assertEqual(calls, [9])
            self.assertTrue(picks)
            eng.candidates(self.seed, self.ctx, k=10)
            self.assertEqual(calls, [9], "cache reused when ids unchanged")
        finally:
            embed_mod.embed_texts = orig

    def test_annotations_reread_when_the_file_changes(self):
        """A1 — a highlight written *after* the engine first ran must show up on
        the next call. The side cache used to be built once per process, so a
        long-running server served the annotations as they stood at first use."""
        ctx = Context.from_arrays(self.chunks, self.vecs)   # nothing pre-injected
        eng = MarksEngine()
        sv = self.seed.vec
        rows = [_ann(0, "note", "beta#0007", note="the flash and the region rhyme")]

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "annotations.jsonl"

            def write():
                path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

            write()
            with patch.object(workspace, "ANNOT_PATH", path), \
                 patch.object(embed_mod, "embed_texts",
                              lambda texts, key, **kw: np.tile(sv, (len(texts), 1))):
                self.assertEqual(eng.ready(ctx), (True, ""))
                first = [p["id"] for p in eng.candidates(self.seed, ctx, k=10)]
                self.assertEqual(first, ["beta#0007"])

                rows.append(_ann(1, "highlight", "delta#0002", quote="the structure of the move"))
                write()

                second = [p["id"] for p in eng.candidates(self.seed, ctx, k=10)]
                self.assertEqual(second, ["beta#0007", "delta#0002"])
                # and the same file re-read costs nothing new
                self.assertEqual([p["id"] for p in eng.candidates(self.seed, ctx, k=10)], second)

    def test_no_marks_file_yet_then_one_appears(self):
        """A missing annotations file is a stable stamp — not-ready stays cheap,
        and the engine flips the moment the first mark is written."""
        ctx = Context.from_arrays(self.chunks, self.vecs)
        eng = MarksEngine()
        sv = self.seed.vec
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "annotations.jsonl"
            with patch.object(workspace, "ANNOT_PATH", path), \
                 patch.object(embed_mod, "embed_texts",
                              lambda texts, key, **kw: np.tile(sv, (len(texts), 1))):
                ok, why = eng.ready(ctx)
                self.assertFalse(ok)
                self.assertIn("no marks yet", why)
                path.write_text(json.dumps(
                    _ann(0, "note", "beta#0007", note="written while the server ran")) + "\n",
                    encoding="utf-8")
                self.assertEqual(eng.ready(ctx), (True, ""))
                self.assertEqual([p["id"] for p in eng.candidates(self.seed, ctx, k=10)],
                                 ["beta#0007"])

    def test_injected_side_value_is_never_overwritten(self):
        """The test seam the whole suite relies on: a raw value in ctx._side is
        honoured verbatim, whatever the file on disk says."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "annotations.jsonl"
            path.write_text(json.dumps(_ann(99, "note", "beta#0007", note="on disk")) + "\n",
                            encoding="utf-8")
            with patch.object(workspace, "ANNOT_PATH", path):
                self.assertEqual(self.eng._annotations(self.ctx), self.anns)
                self.assertIs(self.ctx._side["annotations"], self.anns)


if __name__ == "__main__":
    unittest.main()
