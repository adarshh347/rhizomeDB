"""The retrieval contract every mini-engine implements (PRD Phase 0).

An *engine* answers one question — "from this seed, what else in the corpus?" —
with one retrieval geometry. All engines share the same inputs (a `Seed`, a
`Context`) and return the same shape (a list of chunk-dict copies decorated with
the disclosure fields below), so the reader, the eval harness and the CLI can
treat them interchangeably and the reader can *feel* the difference between
plain RAG and constellatory retrieval by flipping a switch.

Every pick carries:

    similarity   cosine to the seed's surface vector (None if the seed has none)
    rank         position of the pick in the full descending-similarity sort
                 (0 = the single most-similar passage) — the proof that a pick
                 is a mid-band resonance and not an obvious top hit
    corpus_size  len(store) — so `rank` reads as "#412 of 4110"
    score        the engine's own ranking score (BM25, activation, fused …)
    path         the engine key that produced it (fused picks carry the union)
    why          one human sentence: what made this a pick

Contract rules:
  * never pad — return [] when nothing clears the engine's floors
    ("a machine that always finds a connection is lying", VISION.md);
  * never mutate `ctx.chunks` / `ctx.store.chunks` — always copy;
  * be deterministic for a given (seed, ctx, params).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from .. import config


# --------------------------------------------------------------------------- #
# Seed                                                                         #
# --------------------------------------------------------------------------- #
@dataclass
class Seed:
    """What the engine starts from.

    `vec` is the surface embedding (None when only text is known and no vector
    model is loaded — a lexical engine still works). `chunk_id`/`book_id` are
    None for a free-text (theme) seed.
    """
    text: str
    vec: np.ndarray | None = None
    chunk_id: str | None = None
    book_id: str | None = None
    author: str | None = None
    label: str = ""

    @property
    def is_chunk(self) -> bool:
        return self.chunk_id is not None


# --------------------------------------------------------------------------- #
# Context — the shared runtime every engine reads from                         #
# --------------------------------------------------------------------------- #
class _ArrayStore:
    """A `Store`-shaped object built from in-memory arrays (tests, ad-hoc
    corpora). Mirrors the attributes engines rely on: chunks, vecs, by_id,
    model_key, level, and `connections()` (delegated to the real algorithm)."""

    def __init__(self, chunks: list[dict], vecs: np.ndarray | None,
                 model_key: str = config.DEFAULT_EMBED, level: str = "chunk"):
        from ..store import Store
        self.chunks = list(chunks)
        self.vecs = vecs
        self.by_id = {c["id"]: i for i, c in enumerate(self.chunks)}
        self.model_key = model_key
        self.level = level
        # borrow the exact algorithm so parity holds for array-backed contexts
        self.connections = Store.connections.__get__(self, _ArrayStore)

    def __len__(self):
        return len(self.chunks)

    def get(self, chunk_id: str) -> dict:
        return self.chunks[self.by_id[chunk_id]]

    def random_index(self, rng: np.random.Generator) -> int:
        return int(rng.integers(0, len(self.chunks)))


@dataclass
class Context:
    """The shared retrieval runtime.

    `store` is the exact numpy scorer (`rhizome.store.Store` or an array-backed
    stand-in). Side indexes an engine may need (BM25, the concept graph, the
    reader's annotations, the structural matrix) are built lazily and cached on
    the context via `side(name, builder)` so a server process pays once.
    """
    store: Any
    embed_key: str = config.DEFAULT_EMBED
    # The willingness-to-find-nothing gate: an engine returns [] when the
    # seed's best match in the corpus sits below this cosine (see
    # `clears_noise_floor`). None = ungated (uncalibrated model, or an in-memory
    # test corpus). `from_store` sets it from config.noise_floor(embed_key).
    noise_floor: float | None = None
    _side: dict[str, Any] = field(default_factory=dict, repr=False)

    # -- construction -------------------------------------------------------
    @classmethod
    def from_store(cls, store, embed_key: str = config.DEFAULT_EMBED) -> "Context":
        return cls(store=store, embed_key=embed_key,
                   noise_floor=config.noise_floor(embed_key))

    @classmethod
    def from_arrays(cls, chunks: list[dict], vecs: np.ndarray | None,
                    embed_key: str = config.DEFAULT_EMBED) -> "Context":
        """Build a context from memory — the unit-test path. `vecs` must be
        L2-normalised rows aligned with `chunks` (or None for lexical-only)."""
        if vecs is not None:
            vecs = np.asarray(vecs, dtype=np.float32)
            if len(vecs) != len(chunks):
                raise ValueError("chunks and vecs are out of sync")
        return cls(store=_ArrayStore(chunks, vecs, embed_key), embed_key=embed_key)

    # -- convenience ---------------------------------------------------------
    @property
    def chunks(self) -> list[dict]:
        return self.store.chunks

    @property
    def vecs(self) -> np.ndarray | None:
        return getattr(self.store, "vecs", None)

    @property
    def has_vectors(self) -> bool:
        return self.vecs is not None and len(self.vecs) == len(self.chunks)

    def index_of(self, chunk_id: str) -> int | None:
        return self.store.by_id.get(chunk_id)

    def side(self, name: str, builder):
        """Lazily build + cache a side index (BM25, concept graph, …)."""
        if name not in self._side:
            self._side[name] = builder()
        return self._side[name]

    def drop_side(self, name: str) -> None:
        self._side.pop(name, None)

    # -- seeds -----------------------------------------------------------------
    def seed_from_chunk(self, chunk_id: str) -> Seed:
        i = self.store.by_id[chunk_id]
        c = self.chunks[i]
        vec = self.vecs[i] if self.has_vectors else None
        label = f"{c['id']} ({c.get('author') or 'Unknown'}, {c.get('title') or c['book_id']})"
        return Seed(text=c["text"], vec=vec, chunk_id=c["id"], book_id=c["book_id"],
                    author=c.get("author"), label=label)

    def seed_from_text(self, text: str, *, embed: bool = True) -> Seed:
        """A free-text (theme) seed. Embeds with the context's model unless
        `embed=False` (lexical-only use) or no vectors are loaded."""
        vec = None
        if embed and self.has_vectors:
            from .. import embed as embed_mod
            vec = embed_mod.embed_query(text, self.embed_key)
        return Seed(text=text, vec=vec, label=f'theme: "{text}"')


# --------------------------------------------------------------------------- #
# Engine protocol                                                              #
# --------------------------------------------------------------------------- #
@runtime_checkable
class Engine(Protocol):
    key: str          # short stable id, e.g. "band"
    label: str        # human label, e.g. "Resonance band"
    blurb: str        # one or two sentences: the geometry, in words
    needs: list[str]  # subset of {"vectors", "chunks", "concepts", "annotations", "structural", "llm"}
    params: dict      # {name: {"type": "int"|"float"|"bool", "default": …, "help": …}}

    def ready(self, ctx: Context) -> tuple[bool, str]:
        """(True, "") when the engine can run against this context, else
        (False, why-not) — the UI shows the reason instead of a dead option."""
        ...

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   **params) -> list[dict]:
        ...


# --------------------------------------------------------------------------- #
# Helpers shared by engines                                                    #
# --------------------------------------------------------------------------- #
def similarities(seed: Seed, ctx: Context) -> np.ndarray | None:
    """Cosine of every chunk to the seed's surface vector (or None)."""
    if seed.vec is None or not ctx.has_vectors:
        return None
    return ctx.vecs @ seed.vec


def best_match(seed: Seed, ctx: Context) -> float | None:
    """The seed's strongest cosine to any corpus chunk other than itself —
    the number the noise floor gate is applied to."""
    sims = similarities(seed, ctx)
    if sims is None or len(sims) == 0:
        return None
    if seed.chunk_id is not None:
        i = ctx.index_of(seed.chunk_id)
        if i is not None:
            sims = sims.copy()
            sims[i] = -np.inf
            if len(sims) == 1:
                return None
    return float(sims.max())


def clears_noise_floor(seed: Seed, ctx: Context) -> bool:
    """False when the corpus holds nothing that resonates with the seed above
    the context's calibrated floor — the engine should then return [] rather
    than eight confident-looking picks. Always True when the context is
    ungated or the seed has no vector (lexical engines gate on term matches)."""
    if ctx.noise_floor is None or seed.vec is None or not ctx.has_vectors:
        return True
    best = best_match(seed, ctx)
    return best is None or best >= ctx.noise_floor


def ranks_from(sims: np.ndarray) -> np.ndarray:
    """rank[i] = position of chunk i in the descending similarity sort."""
    order = np.argsort(-sims, kind="stable")
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order))
    return rank


def decorate(idx: int, ctx: Context, *, path: str, why: str, score: float | None = None,
             sims: np.ndarray | None = None, rank: np.ndarray | None = None,
             **extras) -> dict:
    """Copy chunk `idx` and attach the disclosure fields. Pass `sims`/`rank`
    (from `similarities`/`ranks_from`) so every engine reports the same
    surface-similarity axis and corpus rank, whatever it ranked by."""
    c = dict(ctx.chunks[idx])
    c["similarity"] = round(float(sims[idx]), 4) if sims is not None else None
    c["rank"] = int(rank[idx]) if rank is not None else None
    c["corpus_size"] = len(ctx.chunks)
    c["score"] = round(float(score), 4) if score is not None else c["similarity"]
    c["path"] = path
    c["why"] = why
    c.update(extras)
    return c


def finish(picks: list[dict], seed: Seed, ctx: Context) -> list[dict]:
    """Back-fill `similarity`/`rank`/`corpus_size` on picks an engine produced
    without the surface axis (lexical, concept, marks …) so the disclosure
    columns are populated wherever a surface vector exists."""
    sims = similarities(seed, ctx)
    if sims is None:
        for p in picks:
            p.setdefault("similarity", None); p.setdefault("rank", None)
            p["corpus_size"] = len(ctx.chunks)
        return picks
    rank = ranks_from(sims)
    for p in picks:
        i = ctx.index_of(p["id"])
        if i is None:
            continue
        p["similarity"] = round(float(sims[i]), 4)
        p["rank"] = int(rank[i])
        p["corpus_size"] = len(ctx.chunks)
    return picks


def pairwise_cosine(ctx: Context, idxs: list[int]) -> np.ndarray:
    v = ctx.vecs[idxs]
    return v @ v.T


def intra_list_diversity(ctx: Context, picks: list[dict]) -> float | None:
    """Mean pairwise (1 - cosine) across the picks — the set-spread proxy."""
    idxs = [ctx.index_of(p["id"]) for p in picks]
    idxs = [i for i in idxs if i is not None]
    if len(idxs) < 2 or not ctx.has_vectors:
        return None
    m = pairwise_cosine(ctx, idxs)
    n = len(idxs)
    off = (m.sum() - np.trace(m)) / (n * (n - 1))
    return round(float(1.0 - off), 4)


class BaseEngine:
    """Optional convenience base: sensible `params`, a `ready()` that checks
    `needs`, and `describe()` for the API. Subclasses set the class attributes
    and implement `candidates()`."""
    key = "base"
    label = "Base"
    blurb = ""
    needs: list[str] = ["vectors"]
    params: dict = {}
    # The willingness-to-find-nothing gate (see `clears_noise_floor`). Every
    # subclass's `candidates()` is wrapped so a seed that resonates with
    # nothing returns [] before the engine's own geometry runs. Set False on
    # engines that must always answer (plain nearest-neighbour — the baseline)
    # or that gate on something other than cosine (lexical: term matches).
    noise_gate = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        inner = cls.__dict__.get("candidates")
        if inner is None or getattr(inner, "_noise_gated", False):
            return

        @functools.wraps(inner)
        def gated(self, seed, ctx, *, k=config.N_CANDIDATES, **params):
            if self.noise_gate and not clears_noise_floor(seed, ctx):
                return []
            return inner(self, seed, ctx, k=k, **params)

        gated._noise_gated = True
        gated.__wrapped__ = inner
        cls.candidates = gated

    def ready(self, ctx: Context) -> tuple[bool, str]:
        if "vectors" in self.needs and not ctx.has_vectors:
            return False, "embeddings not built (run: python -m rhizome.cli embed)"
        return True, ""

    def describe(self, ctx: Context | None = None) -> dict:
        ok, why = (True, "") if ctx is None else self.ready(ctx)
        return {"key": self.key, "label": self.label, "blurb": self.blurb,
                "needs": list(self.needs), "params": dict(self.params),
                "ready": ok, "reason": why}

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   **params) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError
