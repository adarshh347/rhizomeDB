"""In-memory index + the constellatory geometry.

The whole point lives in `connections()`: instead of returning the nearest
neighbours (the obvious, near-duplicate matches), it returns the "resonance
band" — passages that are related-but-distant — then MMR-diversifies so the
picks span different books and ideas.

The band sits between two cuts: drop the `skip_top` most-similar (too obvious)
*and* anything at/above `dedup_sim` (a verbatim quotation of the seed — a
commentary quoting its source is not a discovered connection). By default it
excludes only the seed's own *book*, not its author, so relational surprise can
be found *within* a single corpus (intra-corpus constellation), which is the
deeper aim — cross-author was only ever a proxy for distance.
"""
import json

import numpy as np

from . import config, chunk as chunk_mod


class Store:
    def __init__(self, model_key: str = config.DEFAULT_EMBED,
                 level: str = config.DEFAULT_LEVEL):
        self.model_key = model_key
        self.level = level
        cpath = config.chunks_path(level)
        if level == "chunk":
            self.chunks = chunk_mod.load_chunks()
        else:
            if not cpath.exists():
                raise SystemExit(f"Level '{level}' not built ({cpath}). "
                                 f"Run: python -m rhizome.cli build --levels {level}")
            with cpath.open(encoding="utf-8") as f:
                self.chunks = [json.loads(ln) for ln in f]
        path = config.level_emb_path(level, model_key)
        if not path.exists():
            raise SystemExit(f"Embeddings for level '{level}'/'{model_key}' not built "
                             f"({path}). Run: python -m rhizome.cli embed --model {model_key}"
                             + ("" if level == "chunk" else f" / build --levels {level}"))
        self.vecs = np.load(path)  # (N, dim), normalized
        if len(self.chunks) != len(self.vecs):
            raise SystemExit(f"{cpath.name} and {path.name} are out of sync — rebuild.")
        self.by_id = {c["id"]: i for i, c in enumerate(self.chunks)}

    def __len__(self):
        return len(self.chunks)

    def get(self, chunk_id: str) -> dict:
        return self.chunks[self.by_id[chunk_id]]

    def random_index(self, rng: np.random.Generator) -> int:
        return int(rng.integers(0, len(self.chunks)))

    def connections(
        self,
        seed_vec: np.ndarray,
        *,
        seed_book_id: str | None = None,
        seed_author: str | None = None,
        skip_top: int = config.SKIP_TOP,
        pool: int = config.POOL,
        k: int = config.N_CANDIDATES,
        mmr_lambda: float = config.MMR_LAMBDA,
        min_sim: float = config.MIN_SIM,
        dedup_sim: float = config.DEDUP_SIM,
        exclude_same_book: bool = config.EXCLUDE_SAME_BOOK,
        exclude_same_author: bool = config.EXCLUDE_SAME_AUTHOR,
    ) -> list[dict]:
        sims = self.vecs @ seed_vec  # cosine, since all normalized
        order = np.argsort(-sims)
        # rank[i] = position of chunk i in the full descending-similarity sort
        # (0 = the single most-similar passage). Lets callers show *where in the
        # corpus* a pick came from — proof it is a mid-band resonance, not an
        # obvious top hit.
        rank = np.empty(len(order), dtype=np.int64)
        rank[order] = np.arange(len(order))

        # 1) Build the candidate band: drop near-duplicates (verbatim quotation of
        #    the seed) and the obvious top matches; keep the related-but-distant.
        band: list[int] = []
        skipped = 0
        for idx in order:
            c = self.chunks[idx]
            if sims[idx] >= dedup_sim:
                continue  # near-duplicate / the seed quoting itself, not a connection
            if exclude_same_book and seed_book_id and c["book_id"] == seed_book_id:
                continue
            if exclude_same_author and seed_author and c["author"] and c["author"] == seed_author:
                continue
            if sims[idx] < min_sim:
                break
            if skipped < skip_top:
                skipped += 1
                continue
            band.append(int(idx))
            if len(band) >= pool:
                break
        if not band:
            return []

        # 2) MMR: pick k that are each resonant with the seed but diverse from
        #    one another — spreads picks across books and conceptual angles.
        selected: list[int] = []
        cand = band[:]
        while cand and len(selected) < k:
            best_i, best_score = None, -1e9
            for idx in cand:
                rel = float(sims[idx])
                if selected:
                    div = max(float(self.vecs[idx] @ self.vecs[s]) for s in selected)
                else:
                    div = 0.0
                score = mmr_lambda * rel - (1 - mmr_lambda) * div
                if score > best_score:
                    best_score, best_i = score, idx
            selected.append(best_i)
            cand.remove(best_i)

        out = []
        for idx in selected:
            c = dict(self.chunks[idx])
            c["similarity"] = round(float(sims[idx]), 4)
            c["rank"] = int(rank[idx])           # where in the corpus it sat
            c["corpus_size"] = len(self.chunks)
            out.append(c)
        return out

