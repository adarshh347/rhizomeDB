"""`fused` — the constellation. PRD §4: fuse the paths, then re-rank.

Every other engine is one retrieval geometry. This one asks each of the
*constellatory* paths that is ready — the resonance band (always), the concept
graph, the reader's own marks, the structural index — for a small pool, then
merges by chunk:

    relevance(c) = Σ_paths  w_path / (10 + rank_of_c_in_that_path)     (RRF)
    surprise(c)  = 1 + 0.5·(1 − similarity) + 0.25·[other book]
    score(c)     = relevance × surprise

Provenance weights order the evidence human > structural > concept > dense
(`marks` 1.5 · `structural` 1.2 · `concept` 1.1 · `band` 1.0), so a passage
two paths agree on outranks a passage only one path found, and a passage the
reader once marked outranks one only the vectors like. Quotations
(similarity ≥ `DEDUP_SIM`) and noise (< `MIN_SIM`) are dropped whatever found
them. Finally the top 3k are set-spread with `spread.select_diverse` (facility
location over their score-weighted cosine matrix; the single strongest pick is
always kept) and k survive, in score order.

Sibling engines are imported lazily and each is optional: a missing module or
an unready path degrades to whatever remains — at minimum the band. Empty
union → `[]` (never pad).

Extra fields on every pick: `paths` (contributing path keys, strongest first),
`contributions` ({path: contrib}), `relevance`, `surprise`, and pass-through
extras from the path that found it (`note`, `quote`, `annotation_id`,
`kind`, `color`, `concepts`, `structural_similarity`, `abstraction`, `gap`, `hop`).
`path` = "fused:band+concept".
"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import (BaseEngine, Context, Seed, decorate, pairwise_cosine, ranks_from,
                   similarities)

POOL_EACH = 12                       # picks asked of each path
SPREAD_FACTOR = 3                    # set-spread the top SPREAD_FACTOR·k
RRF_K = 10                           # contrib = w / (RRF_K + rank)
MIN_SIM = config.MIN_SIM             # 0.15 — noise floor
DEDUP_SIM = config.DEDUP_SIM         # 0.97 — quotation ceiling
DISSIM_BONUS = 0.5                   # surprise term for surface distance
CROSS_BOOK_BONUS = 0.25              # surprise term for another book
PATH_WEIGHTS = {"marks": 1.5, "structural": 1.2, "concept": 1.1, "band": 1.0}
PATH_ORDER = ("band", "concept", "marks", "structural")   # deterministic union order
PASS_THROUGH = ("note", "quote", "annotation_id", "kind", "color", "concepts",
                "structural_similarity", "abstraction", "gap", "hop")
SPREAD_METHOD = "facility"


def _load_paths():
    """Sibling engines by key — each import is optional so a half-built
    package still yields a band-only constellation."""
    found = {}
    for name in PATH_ORDER:
        try:
            mod = __import__(f"{__package__}.{name}", fromlist=["ENGINE"])
        except ImportError:
            continue
        eng = getattr(mod, "ENGINE", None)
        if eng is not None:
            found[name] = eng
    return found


def _select_diverse():
    try:
        from . import spread as _spread
        return _spread.select_diverse
    except ImportError:
        return None


class FusedEngine(BaseEngine):
    key = "fused"
    label = "Constellation (fused)"
    blurb = ("The union of every constellatory path that is ready — resonance band, "
             "concept graph, your marks, the structural index — merged by reciprocal "
             "rank with human > structural > concept > dense provenance weights, "
             "re-ranked by relevance × surprise (surface distance, other book), then "
             "set-spread. Empty when no path finds anything.")
    needs = ["vectors"]
    params = {
        "pool_each": {"type": "int", "default": POOL_EACH,
                      "help": "how many picks to ask of each contributing path"},
        "min_sim": {"type": "float", "default": MIN_SIM,
                    "help": "drop picks below this surface similarity (noise)"},
        "dedup_sim": {"type": "float", "default": DEDUP_SIM,
                      "help": "drop picks at/above this surface similarity (quotations)"},
        "spread_factor": {"type": "int", "default": SPREAD_FACTOR,
                          "help": "set-spread the top spread_factor × k before taking k"},
    }

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   pool_each: int = POOL_EACH, min_sim: float = MIN_SIM,
                   dedup_sim: float = DEDUP_SIM, spread_factor: int = SPREAD_FACTOR,
                   **_) -> list[dict]:
        if k <= 0 or not ctx.has_vectors:
            return []
        paths = _load_paths()
        pool_each = max(int(pool_each), 1)

        # -- 1. union: ask each ready path for a pool -------------------------
        found: dict[str, dict] = {}          # chunk id -> {"contrib": {path: c}, "picks": {path: pick}}
        for name in PATH_ORDER:
            eng = paths.get(name)
            if eng is None:
                continue
            ok, _why = eng.ready(ctx)
            if not ok:
                continue
            picks = eng.candidates(seed, ctx, k=pool_each)
            w = PATH_WEIGHTS.get(name, 1.0)
            for r, p in enumerate(picks):
                cid = p.get("id")
                if cid is None or ctx.index_of(cid) is None:
                    continue
                if seed.chunk_id and cid == seed.chunk_id:
                    continue
                slot = found.setdefault(cid, {"contrib": {}, "picks": {}})
                if name in slot["contrib"]:
                    continue                # a path lists a chunk once
                slot["contrib"][name] = w / (RRF_K + r)
                slot["picks"][name] = p
        if not found:
            return []

        # -- 2. re-rank: relevance × surprise, floors ------------------------
        sims = similarities(seed, ctx)
        rank = ranks_from(sims) if sims is not None else None
        scored = []
        for cid, slot in found.items():
            idx = ctx.index_of(cid)
            sim = float(sims[idx]) if sims is not None else None
            if sim is not None and (sim >= dedup_sim or sim < min_sim):
                continue
            c = ctx.chunks[idx]
            cross = 1.0 if (seed.book_id and c.get("book_id") != seed.book_id) else 0.0
            relevance = sum(slot["contrib"].values())
            surprise = 1.0 + CROSS_BOOK_BONUS * cross
            if sim is not None:
                surprise += DISSIM_BONUS * (1.0 - sim)
            scored.append((relevance * surprise, cid, idx, relevance, surprise, cross, slot))
        if not scored:
            return []
        scored.sort(key=lambda t: (-t[0], t[1]))

        # -- 3. set-spread the top spread_factor·k, keep k ------------------
        top = scored[: max(int(spread_factor), 1) * k]
        chosen = top
        select = _select_diverse()
        if select is not None and len(top) > k:
            # the strongest resonance is always kept; the rest are chosen as a
            # set — facility-location over the cosine matrix, each column
            # weighted by its fused score so coverage by a strong pick counts more
            rest = top[1:]
            idxs = [t[2] for t in rest]
            S = pairwise_cosine(ctx, idxs).astype(np.float64)
            quality = np.asarray([t[0] for t in rest], dtype=np.float64)
            qw = quality / (quality.max() or 1.0)
            sel = select(S * qw[None, :], quality, k - 1, SPREAD_METHOD) if k > 1 else []
            keep = sorted(set(int(j) for j in sel))
            chosen = [top[0]] + [rest[j] for j in keep]
        chosen = sorted(chosen, key=lambda t: (-t[0], t[1]))[:k]

        # -- 4. decorate --------------------------------------------------------
        out = []
        for score, cid, idx, relevance, surprise, cross, slot in chosen:
            contrib = slot["contrib"]
            path_keys = sorted(contrib, key=lambda p: (-contrib[p], p))
            strongest = slot["picks"][path_keys[0]]
            base_why = str(strongest.get("why") or "").strip()
            why = " + ".join(path_keys) + (f" — {base_why}" if base_why else "")
            extras = {}
            for p in path_keys:               # strongest path wins a key collision
                for key in PASS_THROUGH:
                    if key in slot["picks"][p] and key not in extras:
                        extras[key] = slot["picks"][p][key]
            out.append(decorate(
                idx, ctx, path="fused:" + "+".join(path_keys), why=why, score=score,
                sims=sims, rank=rank,
                paths=path_keys,
                contributions={p: round(float(v), 5) for p, v in contrib.items()},
                relevance=round(float(relevance), 5), surprise=round(float(surprise), 4),
                cross_book=bool(cross), **extras))
        return out


ENGINE = FusedEngine()
