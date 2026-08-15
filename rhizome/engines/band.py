"""`band` — the resonance band. Today's constellatory engine, unchanged.

A thin wrapper over `Store.connections()`: drop near-duplicates (≥ dedup
ceiling), skip the `skip_top` most-similar (the obvious), stop below the
`min_sim` floor, exclude the seed's own book, then MMR-diversify. This engine is
the **parity oracle** — `tests/test_engines.py` asserts its picks are identical
to a direct `Store.connections()` call, so refactors elsewhere can never drift
the reference geometry.
"""
from __future__ import annotations

from .. import config
from .base import BaseEngine, Context, Seed


class BandEngine(BaseEngine):
    key = "band"
    label = "Resonance band"
    blurb = ("Not nearest-neighbour: drop verbatim near-duplicates, skip the most "
             "obvious matches, keep the related-but-distant band across other books, "
             "then MMR-spread the picks over different works and ideas.")
    needs = ["vectors"]
    params = {
        "skip_top": {"type": "int", "default": config.SKIP_TOP,
                     "help": "how many of the most-similar (obvious) matches to drop"},
        "pool": {"type": "int", "default": config.POOL, "help": "size of the band MMR draws from"},
        "mmr_lambda": {"type": "float", "default": config.MMR_LAMBDA,
                       "help": "< 0.5 favours diversity over closeness"},
        "min_sim": {"type": "float", "default": config.MIN_SIM, "help": "noise floor"},
        "dedup_sim": {"type": "float", "default": config.DEDUP_SIM,
                      "help": "at/above this a candidate is a quotation, not a connection"},
        "exclude_same_book": {"type": "bool", "default": config.EXCLUDE_SAME_BOOK,
                              "help": "never connect a passage to its own book"},
        "exclude_same_author": {"type": "bool", "default": config.EXCLUDE_SAME_AUTHOR,
                                "help": "force strictly cross-author connections"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   **params) -> list[dict]:
        if seed.vec is None or not ctx.has_vectors:
            return []
        kwargs = {name: params[name] for name in self.params if name in params}
        picks = ctx.store.connections(seed.vec, seed_book_id=seed.book_id,
                                      seed_author=seed.author, k=k, **kwargs)
        for p in picks:
            p["score"] = p["similarity"]
            p["path"] = self.key
            p["why"] = (f"in the resonance band — #{p['rank'] + 1} of {p['corpus_size']} "
                        f"by similarity, past the obvious top matches, from another book")
        return picks


ENGINE = BandEngine()
