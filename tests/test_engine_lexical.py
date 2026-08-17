"""`lexical` (BM25) engine tests — on the fixture corpus, with and without vectors."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import engines
from rhizome.engines import Context, Seed
from rhizome.engines import lexical

CONTRACT_KEYS = {"id", "book_id", "text", "similarity", "rank", "corpus_size",
                 "score", "path", "why"}


class LexicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks, cls.vecs = make_corpus()
        cls.ctx_novec = Context.from_arrays(cls.chunks, None)
        cls.ctx_vec = Context.from_arrays(cls.chunks, cls.vecs)
        cls.eng = engines.get("lexical")

    # -- readiness ---------------------------------------------------------- #
    def test_registered_and_ready_without_vectors(self):
        self.assertIn("lexical", engines.keys())
        self.assertEqual(self.eng.needs, ["chunks"])
        self.assertEqual(self.eng.ready(self.ctx_novec), (True, ""))
        ok, why = self.eng.ready(Context.from_arrays([], None))
        self.assertFalse(ok); self.assertTrue(why)

    # -- theme seeds -------------------------------------------------------- #
    def test_theme_distinctive_token_hits_its_chunk_first(self):
        seed = Seed(text="alphatoken3")
        picks = self.eng.candidates(seed, self.ctx_novec, k=5)
        self.assertEqual(len(picks), 1)          # only one chunk carries the token
        self.assertEqual(picks[0]["id"], "alpha#0003")
        self.assertIn("alphatoken3", picks[0]["why"])
        self.assertEqual(picks[0]["terms"], ["alphatoken3"])
        self.assertIsNone(picks[0]["similarity"]); self.assertIsNone(picks[0]["rank"])
        self.assertEqual(picks[0]["corpus_size"], len(self.chunks))

    def test_theme_multiword_ranks_by_bm25_and_respects_k(self):
        seed = Seed(text="the releasement of the region and its waiting")
        picks = self.eng.candidates(seed, self.ctx_novec, k=4)
        self.assertLessEqual(len(picks), 4)
        self.assertTrue(picks)
        scores = [p["score"] for p in picks]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for p in picks:
            self.assertTrue(CONTRACT_KEYS <= set(p), CONTRACT_KEYS - set(p))
            self.assertEqual(p["path"], "lexical")
            self.assertTrue(p["why"].startswith("keyword match: "))
            self.assertEqual(p["book_id"], "alpha")   # only alpha uses those words
            for t in p["terms"]:
                self.assertIn(t, p["text"].lower())

    def test_theme_stopwords_only_or_no_match_is_empty(self):
        self.assertEqual(self.eng.candidates(Seed(text="the and of"), self.ctx_novec, k=5), [])
        self.assertEqual(self.eng.candidates(Seed(text="zzzunknownword qqq"), self.ctx_novec, k=5), [])
        self.assertEqual(self.eng.candidates(Seed(text=""), self.ctx_novec, k=5), [])

    # -- chunk seeds -------------------------------------------------------- #
    def test_chunk_seed_excludes_itself_and_uses_distinctive_terms(self):
        seed = self.ctx_novec.seed_from_chunk("beta#0007")
        terms = lexical.query_terms(seed, self.ctx_novec)
        self.assertLessEqual(len(terms), lexical.QUERY_TERMS)
        self.assertIn("betatoken7", terms)          # unique token → high idf → kept
        self.assertNotIn("the", terms)
        picks = self.eng.candidates(seed, self.ctx_novec, k=6)
        self.assertLessEqual(len(picks), 6)
        self.assertTrue(picks)
        self.assertNotIn("beta#0007", [p["id"] for p in picks])
        # default is the lookup end: same-book hits are allowed (and dominate here)
        self.assertIn("beta", {p["book_id"] for p in picks})

    def test_exclude_same_book_param(self):
        seed = self.ctx_novec.seed_from_chunk("beta#0007")
        picks = self.eng.candidates(seed, self.ctx_novec, k=6, exclude_same_book=True)
        self.assertNotIn("beta", {p["book_id"] for p in picks})
        for p in picks:
            self.assertGreater(p["score"], 0)

    def test_similarity_and_rank_populate_when_vectors_exist(self):
        seed = self.ctx_vec.seed_from_chunk("alpha#0003")
        picks = self.eng.candidates(seed, self.ctx_vec, k=5)
        self.assertTrue(picks)
        for p in picks:
            self.assertIsInstance(p["similarity"], float)
            self.assertIsInstance(p["rank"], int)
            self.assertGreaterEqual(p["rank"], 1)     # 0 is the seed itself
            self.assertEqual(p["corpus_size"], len(self.chunks))
            self.assertNotEqual(p["score"], p["similarity"])   # score is BM25, not cosine

    # -- determinism / hygiene --------------------------------------------- #
    def test_deterministic_and_never_mutates_store(self):
        seed = self.ctx_novec.seed_from_chunk("gamma#0005")
        a = self.eng.candidates(seed, self.ctx_novec, k=5)
        b = self.eng.candidates(seed, self.ctx_novec, k=5)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        for p in a:
            self.assertIsNot(p, self.ctx_novec.chunks[self.ctx_novec.index_of(p["id"])])
        self.assertNotIn("why", self.ctx_novec.chunks[0])

    # -- side index API ------------------------------------------------------ #
    def test_side_index_is_cached_and_overridable(self):
        ctx = Context.from_arrays(self.chunks, None)
        idx = lexical.bm25_index(ctx)
        self.assertIs(idx, lexical.bm25_index(ctx))
        self.assertIs(idx, ctx._side["bm25"])
        self.assertEqual(idx.terms("The Region of releasement, 2024!"), ["region", "releasement"])
        hits = idx.search(["deltatoken2"], 3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(self.chunks[hits[0][0]]["id"], "delta#0002")

        class Fake:
            def terms(self, text): return ["x"]
            def search(self, terms, n): return [(0, 1.0)]
        ctx2 = Context.from_arrays(self.chunks, None)
        ctx2._side["bm25"] = Fake()
        self.assertIs(lexical.bm25_index(ctx2), ctx2._side["bm25"])
        picks = self.eng.candidates(Seed(text="anything"), ctx2, k=3)
        self.assertEqual([p["id"] for p in picks], [self.chunks[0]["id"]])

    def test_query_terms_theme_dedupes_and_keeps_order(self):
        seed = Seed(text="Waiting, the region; waiting again for the Region")
        self.assertEqual(lexical.query_terms(seed, self.ctx_novec), ["waiting", "region", "again"])


if __name__ == "__main__":
    unittest.main()
