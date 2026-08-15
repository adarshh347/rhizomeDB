"""`spread` — the resonance band, chosen by set-level diversity (PRD Phase 5).

Same band as `band` (dedup ceiling · skip-top · min-sim floor · same-book
exclusion · pool cap), but instead of pairwise MMR the k picks are chosen as a
*set*: either the greedy MAP of a determinantal point process (kernel
``L = q qᵀ ⊙ S`` — S the cosine matrix among band members, q_i = exp(α · sim
to seed), so quality pulls toward the seed while the determinant pushes the
set apart), or greedy facility-location (each pick maximises how much of the
whole band is now "covered" by its nearest selected passage). Both are
MMR-free: a pick is chosen for what it adds to the set, not for how far it
sits from the last pick.

`select_diverse(sim_matrix, quality, k, method)` is exposed at module level
so the fused engine can reuse the same selector on its own candidate pool.
"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed

SELECT_METHODS = ("dpp", "facility")
DEFAULT_SELECT = "dpp"
DEFAULT_ALPHA = 3.0        # quality sharpness: q_i = exp(alpha * sim_i)
_EPS = 1e-10               # DPP: below this residual an item is linearly dependent


# --------------------------------------------------------------------------- #
# Set selectors                                                                #
# --------------------------------------------------------------------------- #
def _dpp_greedy(S: np.ndarray, quality: np.ndarray, k: int) -> tuple[list[int], list[float]]:
    """Fast greedy MAP for a DPP (Chen, Zhang & Zhou 2018): incremental
    Cholesky, O(n·k) per step. Returns (indices, marginal log-det gains)."""
    n = S.shape[0]
    q = np.asarray(quality, dtype=np.float64)
    L = (q[:, None] * S) * q[None, :]           # q qᵀ ⊙ S
    k = min(k, n)
    cis = np.zeros((k, n), dtype=np.float64)     # rows of the Cholesky factor
    di2s = np.diag(L).copy()                     # residual (conditional) variances
    picks: list[int] = []
    gains: list[float] = []
    while len(picks) < k:
        j = int(np.argmax(di2s))                 # first max wins → deterministic
        d2 = float(di2s[j])
        if not np.isfinite(d2) or d2 <= _EPS:
            break                                # nothing independent is left
        picks.append(j)
        gains.append(float(np.log(d2)))
        m = len(picks) - 1
        if len(picks) == k:
            break
        ci = cis[:m, j]
        eis = (L[j, :] - ci @ cis[:m, :]) / np.sqrt(d2)
        cis[m, :] = eis
        di2s = di2s - eis * eis
        di2s[picks] = -np.inf
    return picks, gains


def _facility_greedy(S: np.ndarray, k: int) -> tuple[list[int], list[float]]:
    """Greedy facility-location: maximise Σ_j max_{s∈picks} S[j, s] over the
    whole band. Returns (indices, marginal coverage gains)."""
    n = S.shape[0]
    k = min(k, n)
    best = np.zeros(n, dtype=np.float64)          # coverage each j enjoys so far
    picks: list[int] = []
    gains: list[float] = []
    avail = np.ones(n, dtype=bool)
    while len(picks) < k:
        gain = np.maximum(S - best[:, None], 0.0).sum(axis=0)   # gain of adding each column
        gain[~avail] = -np.inf
        j = int(np.argmax(gain))
        if not np.isfinite(gain[j]):
            break
        picks.append(j)
        gains.append(float(gain[j]))
        best = np.maximum(best, S[:, j])
        avail[j] = False
    return picks, gains


def select_with_gains(sim_matrix: np.ndarray, quality: np.ndarray | None, k: int,
                      method: str = DEFAULT_SELECT) -> tuple[list[int], list[float]]:
    """Choose ≤k indices of `sim_matrix` (square, cosine among candidates) as a
    diverse set. Returns (indices in selection order, marginal gains)."""
    S = np.asarray(sim_matrix, dtype=np.float64)
    n = S.shape[0]
    if n == 0 or k <= 0:
        return [], []
    if method == "facility":
        return _facility_greedy(S, k)
    if method == "dpp":
        q = np.ones(n) if quality is None else np.asarray(quality, dtype=np.float64)
        return _dpp_greedy(S, q, k)
    raise ValueError(f"unknown select method {method!r}; use one of {SELECT_METHODS}")


def select_diverse(sim_matrix: np.ndarray, quality: np.ndarray | None, k: int,
                   method: str = DEFAULT_SELECT) -> list[int]:
    """Indices (into `sim_matrix`) of a set-diverse selection of size ≤ k."""
    return select_with_gains(sim_matrix, quality, k, method)[0]


def coverage_counts(S: np.ndarray, picks: list[int]) -> list[int]:
    """For each pick: how many *other* items in S have it as their nearest
    selected item (ties → the earlier pick)."""
    if not picks:
        return []
    sub = S[:, picks]                                   # n × |picks|
    nearest = np.argmax(sub, axis=1)                    # first max wins
    counts = [0] * len(picks)
    for j, p in enumerate(nearest):
        if j == picks[p]:
            continue
        counts[int(p)] += 1
    return counts


# --------------------------------------------------------------------------- #
# Engine                                                                       #
# --------------------------------------------------------------------------- #
class SpreadEngine(BaseEngine):
    key = "spread"
    label = "Resonance band · set-spread"
    blurb = ("The same resonance band as `band`, but the picks are chosen as a set — "
             "greedy DPP (quality × determinant) or facility-location coverage — so "
             "together they span the whole band instead of each merely differing "
             "from the last one (no MMR).")
    needs = ["vectors"]
    params = {
        "select": {"type": "str", "default": DEFAULT_SELECT,
                   "help": "set selector: 'dpp' (quality-weighted determinant) or "
                           "'facility' (coverage of the whole band)"},
        "alpha": {"type": "float", "default": DEFAULT_ALPHA,
                  "help": "dpp quality sharpness: q = exp(alpha * similarity); 0 = pure diversity"},
        "skip_top": {"type": "int", "default": config.SKIP_TOP,
                     "help": "how many of the most-similar (obvious) matches to drop"},
        "pool": {"type": "int", "default": config.POOL, "help": "size of the band the set is drawn from"},
        "min_sim": {"type": "float", "default": config.MIN_SIM, "help": "noise floor"},
        "dedup_sim": {"type": "float", "default": config.DEDUP_SIM,
                      "help": "at/above this a candidate is a quotation, not a connection"},
        "exclude_same_book": {"type": "bool", "default": config.EXCLUDE_SAME_BOOK,
                              "help": "never connect a passage to its own book"},
        "exclude_same_author": {"type": "bool", "default": config.EXCLUDE_SAME_AUTHOR,
                                "help": "force strictly cross-author connections"},
    }

    _BAND_KEYS = ("skip_top", "pool", "min_sim", "dedup_sim",
                  "exclude_same_book", "exclude_same_author")

    def band(self, seed: Seed, ctx: Context, **params) -> list[dict]:
        """The full resonance band (every member, MMR-ordered by the store)."""
        if seed.vec is None or not ctx.has_vectors:
            return []
        kwargs = {name: params[name] for name in self._BAND_KEYS if name in params}
        pool = int(kwargs.get("pool", config.POOL))
        return ctx.store.connections(seed.vec, seed_book_id=seed.book_id,
                                     seed_author=seed.author, k=pool, **kwargs)

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   select: str = DEFAULT_SELECT, alpha: float = DEFAULT_ALPHA,
                   **params) -> list[dict]:
        if select not in SELECT_METHODS:
            raise ValueError(f"select must be one of {SELECT_METHODS}, got {select!r}")
        band = self.band(seed, ctx, **params)
        if not band or k <= 0:
            return []
        idxs = [ctx.index_of(c["id"]) for c in band]
        V = ctx.vecs[idxs]
        S = (V @ V.T).astype(np.float64)
        sims = np.asarray([c["similarity"] for c in band], dtype=np.float64)
        quality = np.exp(float(alpha) * sims)
        picks, gains = select_with_gains(S, quality, k, select)
        covers = coverage_counts(S, picks)
        out = []
        n_sel = len(picks)
        for pos, (j, gain, cov) in enumerate(zip(picks, gains, covers), start=1):
            c = dict(band[j])
            c["score"] = round(gain, 4)
            c["path"] = self.key
            c["select"] = select
            c["covers"] = int(cov)
            c["band_size"] = len(band)
            c["why"] = (f"set-spread pick {pos}/{n_sel} ({select}) — covers {cov} of "
                        f"{len(band)} band passages, sim {c['similarity']:.2f}, "
                        f"#{c['rank'] + 1} of {c['corpus_size']} by similarity")
            out.append(c)
        return out


ENGINE = SpreadEngine()
