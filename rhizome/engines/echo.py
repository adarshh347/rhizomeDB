"""`echo` — echoes in this book. The intra-corpus constellation.

The default resonance band throws away the seed's own book on purpose (a
passage's own book is the *obvious* neighbourhood). This engine looks only
there — but far away: candidates are the same book's chunks at least `gap`
positions from the seed in the book's own reading order, minus near-verbatim
repeats (cos ≥ `dedup_sim`) and anything below the `min_sim` floor. The
survivors are MMR-spread so the picks fall across the book's sections instead
of piling up in one chapter. Every pick carries `distance` (chunks away, in
reading order) and `heading` (the chunk's own heading, when the ingest kept
one).

Needs a passage seed: a free-text theme has no home book, so it returns [] —
unless `book_id` is passed as a param, in which case the theme is echoed
inside that book (no positional gap applies).
"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, decorate, ranks_from, similarities

GAP = 12            # positions (in the book's own order) a pick must be from the seed
MIN_SIM = 0.30      # floor: below this the "echo" is noise
DEDUP_SIM = config.DEDUP_SIM   # ceiling: at/above this it is a repeat, not an echo
MMR_LAMBDA = 0.6    # > 0.5 leans towards closeness; diversity spreads across sections
POOL = 120          # size of the in-book band MMR draws from

SIDE_KEY = "book_order"


def build_book_order(chunks: list[dict]) -> dict:
    """Side index: {book_id: [chunk indexes in ctx.chunks order]} and
    {chunk index: position within its book}."""
    books: dict[str, list[int]] = {}
    for i, c in enumerate(chunks):
        books.setdefault(c["book_id"], []).append(i)
    pos = {i: p for idxs in books.values() for p, i in enumerate(idxs)}
    return {"books": books, "pos": pos}


class EchoEngine(BaseEngine):
    key = "echo"
    label = "Echoes in this book"
    blurb = ("Same book only — the constellation the default band excludes: passages "
             "from elsewhere in the seed's own book, at least a dozen chunks away, "
             "spread across its sections. Needs a passage seed (a free-text theme has "
             "no home book unless `book_id` is given).")
    needs = ["vectors"]
    params = {
        "gap": {"type": "int", "default": GAP,
                "help": "minimum distance from the seed, in chunks of the book's own order"},
        "min_sim": {"type": "float", "default": MIN_SIM, "help": "noise floor"},
        "dedup_sim": {"type": "float", "default": DEDUP_SIM,
                      "help": "at/above this a candidate is a repeat, not an echo"},
        "mmr_lambda": {"type": "float", "default": MMR_LAMBDA,
                       "help": "< 0.5 favours spread across sections over closeness"},
        "pool": {"type": "int", "default": POOL, "help": "size of the in-book band MMR draws from"},
        "book_id": {"type": "str", "default": None,
                    "help": "for a theme seed: the book to echo inside (chunk seeds use their own)"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   gap: int = GAP, min_sim: float = MIN_SIM, dedup_sim: float = DEDUP_SIM,
                   mmr_lambda: float = MMR_LAMBDA, pool: int = POOL,
                   book_id: str | None = None, **_) -> list[dict]:
        sims = similarities(seed, ctx)
        if sims is None or k <= 0:
            return []
        book = seed.book_id or book_id
        if not book:
            return []   # a theme has no home book — say so with silence
        side = ctx.side(SIDE_KEY, lambda: build_book_order(ctx.chunks))
        idxs = side["books"].get(book, [])
        if not idxs:
            return []
        seed_idx = ctx.index_of(seed.chunk_id) if seed.chunk_id else None
        seed_pos = side["pos"].get(seed_idx) if seed_idx is not None else None

        # 1) the in-book band: far from the seed, not a repeat, above the floor
        band: list[int] = []
        for i in sorted(idxs, key=lambda j: (-float(sims[j]), j)):
            if i == seed_idx:
                continue
            if seed_pos is not None and abs(side["pos"][i] - seed_pos) < gap:
                continue
            s = float(sims[i])
            if s >= dedup_sim:
                continue
            if s < min_sim:
                break
            band.append(i)
            if len(band) >= pool:
                break
        if not band:
            return []

        # 2) MMR over the band so picks fall across sections, not one chapter
        selected: list[int] = []
        cand = band[:]
        while cand and len(selected) < k:
            best_i, best_score = None, -1e9
            for i in cand:
                rel = float(sims[i])
                div = max(float(ctx.vecs[i] @ ctx.vecs[s]) for s in selected) if selected else 0.0
                score = mmr_lambda * rel - (1 - mmr_lambda) * div
                if score > best_score:
                    best_score, best_i = score, i
            selected.append(best_i)
            cand.remove(best_i)

        rank = ranks_from(sims)
        out = []
        for i in selected:
            c = ctx.chunks[i]
            heading = (c.get("heading") or "").strip() or None
            dist = abs(side["pos"][i] - seed_pos) if seed_pos is not None else None
            where = f" ({heading})" if heading else ""
            if dist is not None:
                why = f"same book, {dist} passages away{where} — sim {float(sims[i]):.2f}"
            else:
                why = f"echo inside {c.get('title') or book}{where} — sim {float(sims[i]):.2f}"
            out.append(decorate(i, ctx, path=self.key, why=why, score=float(sims[i]),
                                sims=sims, rank=rank, distance=dist, heading=heading))
        return out


ENGINE = EchoEngine()
