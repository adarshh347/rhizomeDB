"""`plain` — nearest neighbours. Ordinary RAG, kept as the baseline.

Top-k by cosine, no exclusions, no diversification: the seed's own book, its
near-verbatim quotations, its immediate neighbours all count. This is exactly
what the constellatory engines throw away, so it is the contrast every other
engine is read against (see `rhizome/rag.py`, which this wraps).
"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, decorate, ranks_from, similarities


class PlainEngine(BaseEngine):
    key = "plain"
    label = "Nearest (plain RAG)"
    blurb = ("Top-k most-similar passages by cosine — no exclusions, no spread. "
             "Ordinary retrieval-augmented lookup; the baseline the constellatory "
             "engines are measured against.")
    needs = ["vectors"]
    noise_gate = False   # the baseline always answers — that is the point of it
    params = {
        "include_seed": {"type": "bool", "default": False,
                         "help": "keep the seed passage itself if it is a corpus chunk"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   include_seed: bool = False, **_) -> list[dict]:
        sims = similarities(seed, ctx)
        if sims is None:
            return []
        rank = ranks_from(sims)
        order = np.argsort(-sims, kind="stable")
        out = []
        for idx in order:
            idx = int(idx)
            if not include_seed and seed.chunk_id and ctx.chunks[idx]["id"] == seed.chunk_id:
                continue
            out.append(decorate(idx, ctx, path=self.key, sims=sims, rank=rank,
                                score=float(sims[idx]),
                                why=f"#{int(rank[idx]) + 1} nearest by surface similarity"))
            if len(out) >= k:
                break
        return out


ENGINE = PlainEngine()
