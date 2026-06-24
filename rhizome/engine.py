"""The connection engine: seed → candidates → judge → synthesize → wander."""
import numpy as np

from . import config, embed, llm, graph, usage
from .store import Store


class Engine:
    def __init__(self, seed_int: int | None = None):
        self.store = Store()
        self.rng = np.random.default_rng(seed_int)
        self.client = llm.get_client()

    # --- seed resolution -------------------------------------------------
    def resolve_seed(self, *, theme=None, chunk_id=None, random=False) -> dict:
        """Turn a request into a seed: {vec, text, book_id, author, label}."""
        if theme is not None:
            return {"vec": embed.embed_query(theme), "text": theme,
                    "book_id": None, "author": None, "label": f'theme: "{theme}"'}
        if chunk_id is not None:
            c = self.store.get(chunk_id)
            i = self.store.by_id[chunk_id]
        elif random:
            i = self.store.random_index(self.rng)
            c = self.store.chunks[i]
        else:
            raise ValueError("resolve_seed() needs theme=, chunk_id=, or random=True")
        label = f"{c['id']} ({c.get('author') or 'Unknown'}, {c.get('title') or c['book_id']})"
        return {"vec": self.store.vecs[i], "text": c["text"],
                "book_id": c["book_id"], "author": c.get("author"), "label": label}

    # --- one exploration step -------------------------------------------
    def explore(self, *, theme=None, chunk_id=None, random=False,
                structural=False, persist=True, k=config.N_CANDIDATES):
        s = self.resolve_seed(theme=theme, chunk_id=chunk_id, random=random)
        vec, seed_text, book_id, author, seed_label = (
            s["vec"], s["text"], s["book_id"], s["author"], s["label"])
        meter = usage.Meter(self.client)   # attribute tokens to each part of the run

        # Structural-HyDE: retrieve on the seed's underlying *move/structure*
        # rather than its surface words, so structurally-kindred passages that
        # share no vocabulary still come within reach (needs an LLM client).
        abstraction = None
        if structural and self.client is not None:
            abstraction = llm.abstract_seed(seed_text, self.client)
            meter.mark("structural seed")
            vec = embed.embed_query(abstraction)

        candidates = self.store.connections(
            vec, seed_book_id=book_id, seed_author=author, k=k)

        result = {
            "seed_label": seed_label,
            "seed_text": seed_text,
            "seed_book_id": book_id,
            "abstraction": abstraction,
            "candidates": candidates,
            "confirmed": [],
            "exploration": None,
            "mode": "geometry-only",
            "usage": meter.report(),
        }
        if not candidates or self.client is None:
            return result

        # judge — keep genuine, drop forced
        verdicts = llm.judge_connections(seed_text, candidates, self.client)
        meter.mark("judge")
        vmap = {v.candidate_index: v for v in verdicts}
        confirmed = []
        for i, c in enumerate(candidates):
            v = vmap.get(i)
            if v and v.connected and v.forced_risk != "high":
                merged = dict(c)
                merged.update(bridge_concept=v.bridge_concept,
                              articulation=v.articulation,
                              forced_risk=v.forced_risk,
                              confidence=v.confidence)
                confirmed.append(merged)
        confirmed.sort(key=lambda c: c["confidence"], reverse=True)
        result["confirmed"] = confirmed
        result["mode"] = "judged"

        if confirmed:
            if persist:
                graph.append_judged(seed_label, confirmed)   # accrete into the graph
            result["exploration"] = llm.synthesize(seed_text, confirmed, self.client)
            meter.mark("synthesize")
        result["usage"] = meter.report()
        return result

    # --- wander: follow a connection as the next seed -------------------
    def wander(self, steps=3, *, theme=None, chunk_id=None, random=True,
               structural=False, k=config.N_CANDIDATES):
        path = []
        cur = dict(theme=theme, chunk_id=chunk_id, random=random)
        for _ in range(steps):
            step = self.explore(k=k, structural=structural, **cur)
            path.append(step)
            # choose the next seed: the highest-confidence confirmed connection,
            # else the top geometric candidate — a line of flight through the rhizome.
            nxt = (step["confirmed"][0] if step["confirmed"]
                   else (step["candidates"][0] if step["candidates"] else None))
            if not nxt:
                break
            cur = dict(theme=None, chunk_id=nxt["id"], random=False)
        return path
