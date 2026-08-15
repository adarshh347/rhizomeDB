"""`structural` — persisted HyDE (PRD Phase 2). Retrieval on the *move*, not
the words.

A build step (`build_structural`) asks the LLM, once per chunk, to name the
underlying structure of the passage (`rhizome.llm.abstract_seed`) and embeds
those abstractions into a SECOND matrix aligned row-for-row with the surface
one:

    index/structural_<embed_key>.npy     float32, L2-normalised, one row per chunk
    index/structural_<embed_key>.jsonl   {"id", "abstraction"} per chunk, same order

At query time no LLM is needed for a chunk seed: the seed's own stored
structural row is the query, and candidates are ranked by cosine in the
structural space. The disclosure is the *gap* — structural similarity minus
surface similarity — the "same move, different words" signal that plain
nearest-neighbour retrieval cannot see.

Theme (free-text) seeds have no stored row. If an LLM `client` is passed the
theme is abstracted and embedded live; otherwise the engine falls back to the
seed's surface vector projected into the structural space (see
`THEME_FALLBACK_NOTE`) — a weaker but LLM-free query.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, decorate, ranks_from, similarities

# --- knobs (module constants; exposed through `params`) -----------------------
MIN_STRUCT = 0.20        # floor: below this structural similarity is noise
DEDUP_STRUCT = 0.97      # ceiling: at/above this the candidate is a quotation
EXCLUDE_SAME_BOOK = True
ABSTRACTION_CLIP = 200   # chars of the stored abstraction carried on a pick
WHY_CLIP = 90            # chars of the abstraction quoted in `why`

THEME_FALLBACK_NOTE = ("theme seed without an LLM client: queried the structural "
                       "space with the seed's surface vector (no abstraction)")


def cache_path():
    """`index/cache_structural.json` — read at call time so INDEX_DIR redirects hold."""
    return config.INDEX_DIR / "cache_structural.json"


def structural_paths(embed_key: str = config.DEFAULT_EMBED):
    """(vectors .npy, abstractions .jsonl) for one embedding model."""
    return (config.INDEX_DIR / f"structural_{embed_key}.npy",
            config.INDEX_DIR / f"structural_{embed_key}.jsonl")


# --------------------------------------------------------------------------- #
# Loading                                                                      #
# --------------------------------------------------------------------------- #
def load_structural(ctx: Context) -> dict | None:
    """Read the structural matrix + abstractions for `ctx.embed_key`, aligned to
    `ctx.chunks` by id. None when the files are missing or unusable."""
    npy, jsonl = structural_paths(ctx.embed_key)
    if not (npy.exists() and jsonl.exists()):
        return None
    try:
        vecs = np.load(npy, mmap_mode="r")
        rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return None
    if len(rows) != len(vecs):
        return None
    by_id = {r["id"]: i for i, r in enumerate(rows)}
    n = len(ctx.chunks)
    dim = vecs.shape[1] if vecs.ndim == 2 else 0
    if dim == 0:
        return None
    # re-align to the live chunk order; chunks without a row get a zero vector
    out = np.zeros((n, dim), dtype=np.float32)
    abstractions: list[str | None] = [None] * n
    hit = 0
    for i, c in enumerate(ctx.chunks):
        j = by_id.get(c["id"])
        if j is None:
            continue
        out[i] = vecs[j]
        abstractions[i] = rows[j].get("abstraction")
        hit += 1
    if hit == 0:
        return None
    return {"vecs": out, "abstractions": abstractions}


def _clip(s: str | None, n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Engine                                                                       #
# --------------------------------------------------------------------------- #
class StructuralEngine(BaseEngine):
    key = "structural"
    label = "Structural (persisted HyDE)"
    blurb = ("Each passage's underlying *move* was named by the LLM at build time and "
             "embedded into a second vector space; a passage seeds retrieval with its "
             "own stored abstraction, so what comes back shares the form of the thought "
             "even when the words differ. No LLM at query time.")
    needs = ["structural"]
    params = {
        "min_struct": {"type": "float", "default": MIN_STRUCT,
                       "help": "floor on structural (abstraction-space) similarity"},
        "dedup_struct": {"type": "float", "default": DEDUP_STRUCT,
                         "help": "at/above this structural similarity the candidate is a quotation"},
        "exclude_same_book": {"type": "bool", "default": EXCLUDE_SAME_BOOK,
                              "help": "never connect a passage to its own book"},
    }

    # -- readiness ---------------------------------------------------------------
    def _side(self, ctx: Context):
        return ctx.side("structural", lambda: load_structural(ctx))

    def ready(self, ctx: Context) -> tuple[bool, str]:
        if self._side(ctx) is None:
            return False, ("structural index not built (run: python -m rhizome.cli "
                           "build-structural — needs an LLM key)")
        return True, ""

    # -- query vector ------------------------------------------------------------
    def _query_vec(self, seed: Seed, ctx: Context, side: dict, client) -> tuple[np.ndarray | None, str | None]:
        """(query vector in structural space, note-or-None)."""
        svecs = side["vecs"]
        if seed.is_chunk:
            i = ctx.index_of(seed.chunk_id)
            if i is not None and float(np.linalg.norm(svecs[i])) > 0:
                return np.asarray(svecs[i], dtype=np.float32), None
            # a chunk with no structural row (partial build) — fall through to surface
        if client is not None and seed.text:
            from .. import embed as embed_mod, llm
            abstraction = llm.abstract_seed(seed.text, client)
            return embed_mod.embed_query(abstraction, ctx.embed_key), None
        if seed.vec is not None and svecs.shape[1] == len(seed.vec):
            return np.asarray(seed.vec, dtype=np.float32), THEME_FALLBACK_NOTE
        return None, None

    # -- candidates --------------------------------------------------------------
    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   min_struct: float = MIN_STRUCT, dedup_struct: float = DEDUP_STRUCT,
                   exclude_same_book: bool = EXCLUDE_SAME_BOOK, client=None,
                   **_) -> list[dict]:
        side = self._side(ctx)
        if side is None:
            return []
        q, note = self._query_vec(seed, ctx, side, client)
        if q is None:
            return []
        svecs = side["vecs"]
        ssims = svecs @ q
        surface = similarities(seed, ctx)             # may be None (no vectors)
        rank = ranks_from(surface) if surface is not None else None
        order = np.argsort(-ssims, kind="stable")
        out = []
        for idx in order:
            idx = int(idx)
            s = float(ssims[idx])
            if s < min_struct:
                break                                  # sorted desc: nothing further clears
            if s >= dedup_struct:
                continue
            c = ctx.chunks[idx]
            if seed.chunk_id and c["id"] == seed.chunk_id:
                continue
            if exclude_same_book and seed.book_id and c["book_id"] == seed.book_id:
                continue
            surf = float(surface[idx]) if surface is not None else None
            gap = round(s - surf, 4) if surf is not None else None
            abstraction = side["abstractions"][idx]
            quote = _clip(abstraction, WHY_CLIP)
            if surf is not None:
                why = f"same move ({s:.2f} structural vs {surf:.2f} surface)"
            else:
                why = f"same move ({s:.2f} structural)"
            if quote:
                why += f": “{quote}”"
            if note:
                why += f" — {note}"
            out.append(decorate(idx, ctx, path=self.key, why=why, score=s,
                                sims=surface, rank=rank,
                                structural_similarity=round(s, 4),
                                surface_similarity=round(surf, 4) if surf is not None else None,
                                gap=gap,
                                abstraction=_clip(abstraction, ABSTRACTION_CLIP) or None))
            if len(out) >= k:
                break
        return out


ENGINE = StructuralEngine()


# --------------------------------------------------------------------------- #
# Build step                                                                   #
# --------------------------------------------------------------------------- #
def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_cache(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(path, cache):
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def build_structural(embed_key: str = config.DEFAULT_EMBED, *, client=None, books=None,
                     sample=None, batch=None) -> dict:
    """Abstract every chunk's move with the LLM (cached by content hash in
    `index/cache_structural.json`), embed the abstractions with `embed_key`, and
    write `structural_<embed_key>.npy` + `.jsonl` aligned with `chunks.jsonl`.

    `books` restricts abstraction to those book_ids and `sample` to the first N
    (both keep the cache warm for a later full build; chunks outside the scope
    whose abstraction is not cached get a zero row and a null abstraction).
    `batch` is the embedding batch size (default 64). Every `batch` LLM calls the
    cache is flushed so an interrupted run resumes for free.
    """
    from .. import chunk as chunk_mod, embed as embed_mod, llm

    chunks = chunk_mod.load_chunks()
    if client is None:
        client = llm.get_client()
    cache_file = cache_path()
    cache = _load_cache(cache_file)
    scope = [c for c in chunks if not books or c["book_id"] in books]
    if sample:
        scope = scope[:sample]
    todo = [c for c in scope if _hash(c["text"]) not in cache]
    if todo and client is None:
        raise RuntimeError("build_structural needs an LLM client: set an LLM API key "
                           "(see rhizome/llm.py) or pass client=…")
    flush_every = int(batch or 64)
    abstracted = 0
    for c in todo:
        text = llm.abstract_seed(c["text"], client)
        cache[_hash(c["text"])] = text
        abstracted += 1
        if abstracted % flush_every == 0:
            _save_cache(cache_file, cache)
    if abstracted:
        _save_cache(cache_file, cache)

    abstractions = [cache.get(_hash(c["text"])) for c in chunks]
    have = [i for i, a in enumerate(abstractions) if a]
    npy, jsonl = structural_paths(embed_key)
    dim = config.EMBED_MODELS.get(embed_key, {}).get("dim", config.EMBED_DIM)
    vecs = np.zeros((len(chunks), dim), dtype=np.float32)
    if have:
        emb = embed_mod.embed_texts([abstractions[i] for i in have], embed_key,
                                    batch=int(batch or 64))
        vecs = np.zeros((len(chunks), emb.shape[1]), dtype=np.float32)
        vecs[have] = emb
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(npy, vecs)
    with jsonl.open("w", encoding="utf-8") as f:
        for c, a in zip(chunks, abstractions):
            f.write(json.dumps({"id": c["id"], "abstraction": a}, ensure_ascii=False) + "\n")
    return {"n": len(chunks), "cached": len(scope) - len(todo), "abstracted": abstracted,
            "path": str(npy)}
