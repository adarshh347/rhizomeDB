"""`band` — the resonance band. Today's constellatory geometry, plus the gate.

A thin wrapper over `Store.connections()`: drop near-duplicates (≥ dedup
ceiling), skip the `skip_top` most-similar (the obvious), stop below the
`min_sim` floor, exclude the seed's own book, then MMR-diversify.

**Parity, and its one qualification.** The *geometry* is byte-identical to a
direct `Store.connections()` call — this engine is the parity oracle
(`tests/test_engines.py::ParityTests`, on the fixture and on the real index).
But, like every constellatory engine, it is *also* subject to the context's
noise floor: `BaseEngine.__init_subclass__` wraps `candidates()` in
`base.clears_noise_floor(seed, ctx)` (`rhizome/engines/base.py`; the floor
itself is `config.NOISE_FLOOR`, read by `Context.from_store`). So on a gated
context a seed whose best match in the corpus sits below the floor gets `[]`
here where `Store.connections()` would still have returned k picks. That is
deliberate — the willingness to find nothing (VISION.md; PRD §6c) — not a
parity break: above the floor the two are identical, below it the gate is the
only difference (`tests/test_explore_path.py::BandGateParityTests` proves both
halves). Free-text *theme* seeds are what actually gate; passage seeds
essentially never do (measured: min best cross-book cosine ≥ 0.73 vs a 0.50
floor). `Context.from_arrays` (the unit-test path) is ungated, which is why the
fixture parity test cannot see the gate at all.
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
