"""`walk` — a line of flight. The rhizome as a *path*, not a set.

A geometry-only wander: hop 1 is the top MMR pick of the resonance band around
the seed (`Store.connections`, restricted to books not yet visited); hop 2 is
the top pick of the band around *that* passage; and so on, up to `k` hops. The
seed's own book counts as visited from the start, so the walk keeps leaving —
each step is a new work, chosen for its resonance with the previous step rather
than with the origin. Every pick still reports `similarity`/`rank` against the
ORIGINAL seed (the disclosure axis every engine shares) and adds `hop`,
`from_id` and `hop_similarity` (cosine to the previous step). The list is in
hop order. When no unvisited book clears the band's floors the walk stops
early — it never pads.
"""
from __future__ import annotations

from .. import config
from .base import BaseEngine, Context, Seed, decorate, finish

POOL = 24               # how much of the band each hop looks at for an unvisited book
REVISIT_BOOKS = False   # when the unvisited books run out, stop (False) or allow a return (True)


class WalkEngine(BaseEngine):
    key = "walk"
    label = "Line of flight"
    blurb = ("A wander through the corpus: the band's best pick from the seed, then "
             "the best pick from that passage, then from the next — one new book per "
             "hop, never returning. k is the number of hops; the list is the path.")
    needs = ["vectors"]
    params = {
        "pool": {"type": "int", "default": POOL,
                 "help": "how many band picks each hop scans for the first unvisited book"},
        "revisit_books": {"type": "bool", "default": REVISIT_BOOKS,
                          "help": "when every book has been visited, allow a return instead of stopping"},
        "skip_top": {"type": "int", "default": config.SKIP_TOP,
                     "help": "per hop: how many of the most-similar (obvious) matches to drop"},
        "min_sim": {"type": "float", "default": config.MIN_SIM,
                    "help": "per hop: noise floor for the next step"},
        "mmr_lambda": {"type": "float", "default": config.MMR_LAMBDA,
                       "help": "per hop: < 0.5 favours diversity in the band the step is drawn from"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   pool: int = POOL, revisit_books: bool = REVISIT_BOOKS,
                   skip_top: int = config.SKIP_TOP, min_sim: float = config.MIN_SIM,
                   mmr_lambda: float = config.MMR_LAMBDA, **_) -> list[dict]:
        if seed.vec is None or not ctx.has_vectors or k <= 0:
            return []
        vecs = ctx.vecs
        visited_books: set[str] = {seed.book_id} if seed.book_id else set()
        picked_ids: set[str] = {seed.chunk_id} if seed.chunk_id else set()

        cur_vec, cur_book, cur_author, cur_id = seed.vec, seed.book_id, seed.author, seed.chunk_id
        picks: list[dict] = []
        for hop in range(1, k + 1):
            band = ctx.store.connections(
                cur_vec, seed_book_id=cur_book, seed_author=cur_author, k=pool,
                skip_top=skip_top, min_sim=min_sim, mmr_lambda=mmr_lambda)
            nxt = None
            for c in band:
                if c["id"] in picked_ids:
                    continue
                if c["book_id"] not in visited_books:
                    nxt = c
                    break
            if nxt is None and revisit_books:
                for c in band:
                    if c["id"] not in picked_ids and c["book_id"] != cur_book:
                        nxt = c
                        break
            if nxt is None:
                break  # the walk ends here rather than padding
            idx = ctx.index_of(nxt["id"])
            hop_sim = float(vecs[idx] @ cur_vec)
            if cur_id:
                cur_i = ctx.index_of(cur_id)
                prev_title = ctx.chunks[cur_i].get("title") if cur_i is not None else None
                prev_label = cur_author or prev_title or cur_book or cur_id
            else:
                prev_label = "the theme"
            picks.append(decorate(
                idx, ctx, path=self.key, score=hop_sim,
                why=f"hop {hop} from {prev_label} — sim {hop_sim:.2f} to the previous step",
                hop=hop, from_id=cur_id, hop_similarity=round(hop_sim, 4)))
            picked_ids.add(nxt["id"])
            visited_books.add(nxt["book_id"])
            cur_vec, cur_book, cur_author, cur_id = vecs[idx], nxt["book_id"], nxt.get("author"), nxt["id"]
        return finish(picks, seed, ctx)


ENGINE = WalkEngine()
