"""`hybrid` — dense + keyword, fused by reciprocal rank (RRF).

The lookup-end hybrid: take the dense top-N by cosine to the seed vector and
the BM25 top-N for the seed's distinctive terms (from the sibling `lexical`
module), then fuse the two rankings with reciprocal-rank fusion —
``score = Σ 1 / (rrf_k + rank)`` over the lists a chunk appears in. A passage
that both geometries agree on rises above one that only one of them saw; a
passage seen by one geometry alone still surfaces, tagged "dense only" /
"keyword only". No band exclusions by default (`exclude_same_book=False`) —
this is the ordinary-RAG side of the dial, kept honest by the disclosure
fields (`rank`, `dense_rank`, `lexical_rank`).

Extras on every pick: ``dense_rank`` (1-based position in the dense list, or
None), ``lexical_rank`` (1-based position in the BM25 list, or None) and
``matched_terms`` (which of the seed's query terms occur in the pick).
"""
from __future__ import annotations

import re

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, decorate, finish, ranks_from, similarities

RRF_K = 60            # the RRF smoothing constant (Cormack et al. 2009)
POOL = 50             # top-N taken from each list before fusion
QUERY_TERMS = 12      # how many distinctive seed terms feed BM25
WHY_TERMS = 3         # how many matched terms the `why` sentence names

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def _lexical_ranked(seed: Seed, ctx: Context, n: int) -> tuple[list[tuple[int, float]], list[str]]:
    """BM25 hits [(idx, score)] + the query terms used. Imported lazily so
    engine discovery never depends on the sibling module; returns ([], [])
    when it is unavailable or the seed yields no terms."""
    try:
        from .lexical import bm25_index, query_terms
    except ImportError:
        return [], []
    terms = list(query_terms(seed, ctx, n=QUERY_TERMS))
    if not terms:
        return [], terms
    hits = bm25_index(ctx).search(terms, n)
    return [(int(i), float(s)) for i, s in hits], terms


def _matched(text: str, terms: list[str]) -> list[str]:
    toks = set(_TOKEN.findall(text.lower()))
    return [t for t in terms if t.lower() in toks]


class HybridEngine(BaseEngine):
    key = "hybrid"
    label = "Dense + keyword (RRF)"
    blurb = ("Reciprocal-rank fusion of the dense top-N (cosine) and the BM25 top-N "
             "(the seed's distinctive terms). Passages both geometries agree on rise; "
             "either alone still surfaces. The lookup end of the dial.")
    needs = ["vectors", "chunks"]
    params = {
        "rrf_k": {"type": "int", "default": RRF_K,
                  "help": "RRF smoothing constant; larger flattens the rank curve"},
        "pool": {"type": "int", "default": POOL,
                 "help": "how many top hits each list (dense, keyword) contributes"},
        "exclude_same_book": {"type": "bool", "default": False,
                              "help": "drop passages from the seed's own book"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   rrf_k: int = RRF_K, pool: int = POOL,
                   exclude_same_book: bool = False, **_) -> list[dict]:
        if k <= 0 or pool <= 0:
            return []
        chunks = ctx.chunks
        seed_idx = ctx.index_of(seed.chunk_id) if seed.chunk_id else None

        def eligible(idx: int) -> bool:
            if idx == seed_idx:
                return False
            if exclude_same_book and seed.book_id and chunks[idx]["book_id"] == seed.book_id:
                return False
            return True

        # (a) dense list
        sims = similarities(seed, ctx)
        rank = ranks_from(sims) if sims is not None else None
        dense: list[int] = []
        if sims is not None:
            for idx in np.argsort(-sims, kind="stable"):
                idx = int(idx)
                if eligible(idx):
                    dense.append(idx)
                    if len(dense) >= pool:
                        break

        # (b) keyword list (over-fetch a little so exclusions do not starve it)
        hits, terms = _lexical_ranked(seed, ctx, pool + (2 if seed_idx is None else 3))
        lexical: list[int] = []
        for idx, _score in hits:
            if 0 <= idx < len(chunks) and eligible(idx) and idx not in lexical:
                lexical.append(idx)
                if len(lexical) >= pool:
                    break

        if not dense and not lexical:
            return []

        # (c) fuse
        d_rank = {idx: r + 1 for r, idx in enumerate(dense)}
        l_rank = {idx: r + 1 for r, idx in enumerate(lexical)}
        fused: dict[int, float] = {}
        for idx, r in d_rank.items():
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + r)
        for idx, r in l_rank.items():
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + r)
        order = sorted(fused, key=lambda i: (-fused[i], d_rank.get(i, 10**9),
                                             l_rank.get(i, 10**9), i))

        picks = []
        for idx in order[:k]:
            dr, lr = d_rank.get(idx), l_rank.get(idx)
            matched = _matched(chunks[idx]["text"], terms) if lr is not None else []
            if dr is not None and lr is not None:
                why = f"dense #{dr} + keyword #{lr}"
            elif dr is not None:
                why = f"dense only #{dr}"
            else:
                why = f"keyword only #{lr}"
            if matched:
                why += f" ({', '.join(matched[:WHY_TERMS])})"
            p = decorate(idx, ctx, path=self.key, why=why, score=fused[idx],
                         sims=sims, rank=rank, dense_rank=dr, lexical_rank=lr,
                         matched_terms=matched)
            p["score"] = round(fused[idx], 6)   # RRF scores are ~1/60; 4 dp would tie them
            picks.append(p)
        return finish(picks, seed, ctx)


ENGINE = HybridEngine()
