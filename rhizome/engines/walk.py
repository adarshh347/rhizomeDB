"""`walk` — a line of flight. The rhizome as a *path*, not a set.

A geometry-only wander: hop 1 is the strongest band connection from the seed
into a book not yet visited (dedup ceiling, skip the obvious, noise floor —
the band's own rules, with visited books excluded before the cut); hop 2 is
the same step from *that* passage; and so on, up to `k` hops. The
seed's own book counts as visited from the start, so the walk keeps leaving —
each step is a new work, chosen for its resonance with the previous step rather
than with the origin. Every pick still reports `similarity`/`rank` against the
ORIGINAL seed (the disclosure axis every engine shares) and adds `hop`,
`from_id` and `hop_similarity` (cosine to the previous step). The list is in
hop order. When no unvisited book clears the band's floors the walk stops
early — it never pads.
"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, decorate, finish

REVISIT_BOOKS = False   # when the unvisited books run out, stop (False) or allow a return (True)


class WalkEngine(BaseEngine):
    key = "walk"
    label = "Line of flight"
    blurb = ("A wander through the corpus: the band's best pick from the seed, then "
             "the best pick from that passage, then from the next — one new book per "
             "hop, never returning. k is the number of hops; the list is the path.")
    needs = ["vectors"]
    params = {
        "revisit_books": {"type": "bool", "default": REVISIT_BOOKS,
                          "help": "when every book has been visited, allow a return instead of stopping"},
        "skip_top": {"type": "int", "default": config.SKIP_TOP,
                     "help": "per hop: how many of the most-similar (obvious) matches to drop"},
        "min_sim": {"type": "float", "default": config.MIN_SIM,
                    "help": "per hop: noise floor for the next step"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   revisit_books: bool = REVISIT_BOOKS,
                   skip_top: int = config.SKIP_TOP, min_sim: float = config.MIN_SIM,
                   **_) -> list[dict]:
        if seed.vec is None or not ctx.has_vectors or k <= 0:
            return []
        vecs = ctx.vecs
        visited_books: set[str] = {seed.book_id} if seed.book_id else set()
        picked_ids: set[str] = {seed.chunk_id} if seed.chunk_id else set()

        cur_vec, cur_book, cur_author, cur_id = seed.vec, seed.book_id, seed.author, seed.chunk_id
        picks: list[dict] = []
        for hop in range(1, k + 1):
            # The band around the current step, built the way Store.connections
            # builds it (dedup ceiling, skip the obvious, noise floor) but with
            # every visited book excluded *before* the cut — so a step whose
            # nearest neighbours all sit in an already-visited work can still
            # leave for a new one. The first survivor is the strongest
            # connection into an unvisited book; MMR's first pick is that same
            # top-relevance item, so this equals "top MMR pick, unvisited books".
            sims = vecs @ cur_vec
            order = np.argsort(-sims, kind="stable")
            nxt_idx, skipped, fallback = None, 0, None
            for j in order:
                j = int(j)
                c = ctx.chunks[j]
                if sims[j] < min_sim:
                    break
                if sims[j] >= config.DEDUP_SIM or c["id"] in picked_ids:
                    continue
                if c["book_id"] == cur_book:
                    continue
                if c["book_id"] in visited_books:
                    if revisit_books and fallback is None and skipped >= skip_top:
                        fallback = j
                    continue
                if skipped < skip_top:
                    skipped += 1
                    continue
                nxt_idx = j
                break
            if nxt_idx is None and revisit_books:
                nxt_idx = fallback
            if nxt_idx is None:
                break  # the walk ends here rather than padding
            idx = nxt_idx
            nxt = ctx.chunks[idx]
            hop_sim = float(sims[idx])
            if cur_id:
                cur_i = ctx.index_of(cur_id)
                prev_title = ctx.chunks[cur_i].get("title") if cur_i is not None else None
                prev_label = prev_title or cur_author or cur_book or cur_id
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
