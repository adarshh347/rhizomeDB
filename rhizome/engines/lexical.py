"""`lexical` — keyword retrieval (BM25). The SOLID / lookup end of the dial.

Pure-Python BM25 (Okapi; k1 = 1.5, b = 0.75) over lowercase ``\\w+`` tokens with
a small function-word stoplist. No vectors are needed: the engine is ready
whenever the context has chunks, so it also serves as the fallback retrieval
path when embeddings are not built.

The seed is turned into a term list by `query_terms()`:
  * chunk seed  → the passage's top-n *distinctive* terms by tf-idf within the
    corpus (idf from the BM25 document-frequency table) — the words that make
    this passage this passage, not the words every passage shares;
  * theme seed  → its own tokens (deduped, order kept).

The side index is built lazily via ``ctx.side("bm25", …)`` and exposed as
`bm25_index(ctx)` so other engines (`hybrid`, `fused`) can share it; tests may
pre-populate ``ctx._side["bm25"]`` with any object exposing ``.search`` and
``.terms``.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .. import config
from .base import BaseEngine, Context, Seed, finish

# --------------------------------------------------------------------------- #
# Knobs (module constants, exposed through `params`)                          #
# --------------------------------------------------------------------------- #
BM25_K1 = 1.5
BM25_B = 0.75
QUERY_TERMS = 12          # distinctive terms drawn from a chunk seed
EXCLUDE_SAME_BOOK = False  # lookup end: the seed's own book is fair game
MAX_WHY_TERMS = 6         # how many matched terms `why` lists

_TOKEN_RE = re.compile(r"\w+")

# ~60 English function words. Deliberately *not* including content-bearing
# words a philosophical corpus lives on ("being", "thing", "world").
STOP = frozenset("""
a an the and or but nor so yet if then than as of in on at to from by for with
without into onto upon over under between through about above below after before
is are was were be been am do does did have has had having not no it its this
that these those there here which who whom whose what when where why how i we you
he she they them us our your his her their my me him can could may might must
shall should will would also too very more most such each any all both either
""".split())


def tokenize(text: str) -> list[str]:
    """Lowercase ``\\w+`` tokens minus stopwords and bare digits/1-char tokens.
    Markdown emphasis underscores are stripped (``_energeia_`` → ``energeia``)
    so a term matches whether or not the source italicised it."""
    out = []
    for t in _TOKEN_RE.findall(text.lower()):
        t = t.strip("_")
        if t and t not in STOP and len(t) > 1 and not t.isdigit():
            out.append(t)
    return out


# --------------------------------------------------------------------------- #
# The BM25 side index                                                          #
# --------------------------------------------------------------------------- #
class BM25Index:
    """Okapi BM25 over a list of documents (chunk texts).

    ``search(terms, n)`` → ``[(doc_index, score), …]`` descending, only docs
    with score > 0. ``terms(text)`` → the tokeniser used at build time.
    """

    def __init__(self, texts: list[str], k1: float = BM25_K1, b: float = BM25_B):
        self.k1 = k1
        self.b = b
        self.n_docs = len(texts)
        self.doc_len: list[int] = []
        self.tf: list[Counter] = []
        self.df: Counter = Counter()
        # postings: term -> list of (doc_index, tf)
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, text in enumerate(texts):
            toks = tokenize(text)
            c = Counter(toks)
            self.tf.append(c)
            self.doc_len.append(len(toks))
            for term, f in c.items():
                self.df[term] += 1
                self.postings.setdefault(term, []).append((i, f))
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

    # -- vocabulary helpers ------------------------------------------------ #
    def terms(self, text: str) -> list[str]:
        return tokenize(text)

    def idf(self, term: str) -> float:
        """Robertson/Sparck-Jones idf with the +1 smoothing (never negative)."""
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def distinctive_terms(self, doc_index: int, n: int = QUERY_TERMS) -> list[str]:
        """Top-n terms of document `doc_index` by tf·idf (ties: alphabetical)."""
        c = self.tf[doc_index]
        scored = [(f * self.idf(t), t) for t, f in c.items()]
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [t for _, t in scored[:n]]

    def matched_terms(self, doc_index: int, terms: list[str]) -> list[str]:
        """Which of `terms` occur in document `doc_index` (query order, deduped)."""
        seen, out = set(), []
        c = self.tf[doc_index]
        for t in terms:
            if t in c and t not in seen:
                seen.add(t); out.append(t)
        return out

    # -- scoring ---------------------------------------------------------- #
    def score_all(self, terms: list[str]) -> dict[int, float]:
        """BM25 score of every document that matches at least one term."""
        scores: dict[int, float] = {}
        if not terms or not self.n_docs:
            return scores
        k1, b, avgdl = self.k1, self.b, self.avgdl or 1.0
        for term in dict.fromkeys(terms):   # each query term counts once
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf(term)
            for i, f in plist:
                denom = f + k1 * (1.0 - b + b * self.doc_len[i] / avgdl)
                scores[i] = scores.get(i, 0.0) + idf * (f * (k1 + 1.0)) / denom
        return scores

    def search(self, terms: list[str], n: int) -> list[tuple[int, float]]:
        scores = self.score_all(terms)
        ranked = sorted(((i, s) for i, s in scores.items() if s > 0.0),
                        key=lambda p: (-p[1], p[0]))
        return ranked[:n]


# --------------------------------------------------------------------------- #
# Module-level API other engines import                                        #
# --------------------------------------------------------------------------- #
def bm25_index(ctx: Context) -> BM25Index:
    """The context's BM25 side index (built once, cached on the context)."""
    return ctx.side("bm25", lambda: BM25Index([c.get("text", "") for c in ctx.chunks]))


def query_terms(seed: Seed, ctx: Context, n: int = QUERY_TERMS) -> list[str]:
    """Terms that stand for the seed.

    Chunk seed → its top-n distinctive terms (tf·idf against the corpus).
    Theme seed → all of its tokens, deduped, order kept.
    """
    idx = bm25_index(ctx)
    if seed.is_chunk:
        i = ctx.index_of(seed.chunk_id)
        if i is not None and hasattr(idx, "distinctive_terms"):
            return idx.distinctive_terms(i, n)
        if i is not None:   # a foreign side object: fall back to plain tf
            c = Counter(idx.terms(ctx.chunks[i].get("text", "")))
            return [t for t, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
    return list(dict.fromkeys(idx.terms(seed.text or "")))


# --------------------------------------------------------------------------- #
# The engine                                                                   #
# --------------------------------------------------------------------------- #
class LexicalEngine(BaseEngine):
    key = "lexical"
    label = "Keyword (BM25)"
    blurb = ("Classic keyword retrieval: the passage's most distinctive words, "
             "scored by BM25 against every chunk. Needs no embeddings. The lookup "
             "end of the dial — and the 'obvious' the resonance band throws away, "
             "made visible.")
    needs = ["chunks"]
    params = {
        "exclude_same_book": {"type": "bool", "default": EXCLUDE_SAME_BOOK,
                              "help": "drop hits from the seed's own book"},
        "n_terms": {"type": "int", "default": QUERY_TERMS,
                    "help": "distinctive terms drawn from a chunk seed (theme seeds use all their words)"},
    }

    def ready(self, ctx: Context) -> tuple[bool, str]:
        if not ctx.chunks:
            return False, "no chunks loaded (run: python -m rhizome.cli ingest)"
        return True, ""

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   exclude_same_book: bool = EXCLUDE_SAME_BOOK,
                   n_terms: int = QUERY_TERMS, **_) -> list[dict]:
        if not ctx.chunks or k <= 0:
            return []
        idx = bm25_index(ctx)
        terms = query_terms(seed, ctx, n=n_terms)
        if not terms:
            return []
        seed_i = ctx.index_of(seed.chunk_id) if seed.chunk_id else None
        # exclusions may skip many hits (a whole book): rank everything that
        # matches, then filter — the match set is small and the sort is cheap
        hits = idx.search(terms, n=len(ctx.chunks))
        if not hits:
            return []
        picks = []
        for i, score in hits:
            if i == seed_i:
                continue
            c = ctx.chunks[i]
            if exclude_same_book and seed.book_id and c.get("book_id") == seed.book_id:
                continue
            present = set(idx.terms(c.get("text", "")))
            matched = [t for t in dict.fromkeys(terms) if t in present]
            shown = ", ".join(matched[:MAX_WHY_TERMS])
            more = f" (+{len(matched) - MAX_WHY_TERMS} more)" if len(matched) > MAX_WHY_TERMS else ""
            p = dict(c)
            p["similarity"] = None
            p["rank"] = None
            p["corpus_size"] = len(ctx.chunks)
            p["score"] = round(float(score), 4)
            p["path"] = self.key
            p["why"] = f"keyword match: {shown}{more}"
            p["terms"] = matched
            picks.append(p)
            if len(picks) >= k:
                break
        return finish(picks, seed, ctx)


ENGINE = LexicalEngine()
