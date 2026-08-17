"""`concept` — the concept graph as a retrieval path (PRD Phase 3).

Geometry: a bipartite graph chunks ↔ concept nodes built from
`index/concepts.json` (`chunk_concepts`), optionally extended with attributed
bridges from `index/edges.jsonl` (an edge whose provenance is a corpus chunk
becomes an `edge:<target>` node hanging off that chunk, weighted by origin so
a human note outweighs a judged bridge). Edge weight is idf-style
1/log(2 + count) so pervasive concepts carry less mass than specific ones.

Retrieval is personalised PageRank by numpy power iteration from the seed:
a chunk seed personalises on its own node; a theme seed personalises on the
concept nodes whose label tokens overlap the theme. Chunks are ranked by the
PPR mass that lands on them, must share at least one concept with the seed
(so `why` can name it), and never come from the seed's own book by default.
Cross-book reach through a shared idea is the whole point: two passages with
zero surface similarity land next to each other because they name the same
concept — the surface `similarity`/`rank` disclosure shows exactly how far
apart they were in vector space.
"""
from __future__ import annotations

import re

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, decorate, file_stamp, finish

# --- knobs (exposed via `params`) --------------------------------------------
ALPHA = 0.15            # teleport probability (restart to the personalisation vector)
ITERS = 30              # power-iteration steps
MIN_ACTIVATION = 1e-6   # floor: chunks below this much PPR mass are not picks
USE_EDGES = True        # fold index/edges.jsonl bridges into the graph
EDGE_ORIGIN_WEIGHT = {"note": 1.5, "authored": 1.5, "judged": 1.0}
WHY_CONCEPTS = 3        # how many shared concepts the `why` sentence names

_TOKEN_RE = re.compile(r"[a-z][a-z'\-]{2,}")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


# --- side-index loaders (overridable in tests via ctx._side[...]) -----------
def load_concepts_side():
    """`concepts.json` as a dict, or None when it is not built."""
    try:
        from .. import concepts as concepts_mod
        return concepts_mod.load_concepts()
    except (SystemExit, FileNotFoundError, OSError, ValueError):
        return None


def load_edges_side() -> list[dict]:
    """`edges.jsonl` rows, or [] when the file is missing."""
    try:
        from .. import graph as graph_mod
        return graph_mod.load_edges()
    except (SystemExit, FileNotFoundError, OSError, ValueError):
        return []


def _concepts_ok(data) -> bool:
    return bool(data) and bool(data.get("chunk_concepts"))


def _concepts_stamp():
    """Freshness token for `index/concepts.json` — so a `rhizome concepts` run
    against a live server flips the engine from not-ready to ready."""
    from .. import concepts as concepts_mod
    return file_stamp(concepts_mod.CONCEPTS_PATH)


def _edges_stamp():
    return file_stamp(config.EDGES_PATH)


def concepts_side(ctx: Context):
    """`concepts.json`, re-read when the file on disk has changed."""
    return ctx.side_fresh("concepts", _concepts_stamp(), load_concepts_side)


def edges_side(ctx: Context) -> list[dict]:
    """`edges.jsonl` rows, re-read when the file on disk has changed."""
    return ctx.side_fresh("edges", _edges_stamp(), load_edges_side)


# --- the graph -----------------------------------------------------------------
class ConceptGraph:
    """Bipartite chunk ↔ node adjacency as a dense (n_chunks × n_nodes) weight
    matrix. Nodes are concept labels plus optional `edge:<target>` bridge nodes.
    Small enough (≈4k × ≈200) that dense numpy is the simplest correct thing."""

    def __init__(self, chunks: list[dict], concepts: dict, edges: list[dict] | None,
                 use_edges: bool = True):
        by_id = {c["id"]: i for i, c in enumerate(chunks)}
        n = len(chunks)
        chunk_concepts = (concepts or {}).get("chunk_concepts") or {}

        # column nodes, in a deterministic order (first-seen over the chunk order)
        node_index: dict[str, int] = {}
        entries: list[tuple[int, int, float]] = []   # (chunk_idx, node_idx, raw weight)
        for i, c in enumerate(chunks):
            for label in chunk_concepts.get(c["id"], []) or []:
                label = str(label).strip()
                if not label:
                    continue
                j = node_index.setdefault(label, len(node_index))
                entries.append((i, j, 1.0))
        if use_edges:
            for e in edges or []:
                prov = e.get("provenance")
                i = by_id.get(prov) if isinstance(prov, str) else None
                if i is None:
                    continue
                target = str(e.get("target") or "").strip()
                if not target:
                    continue
                w = EDGE_ORIGIN_WEIGHT.get(str(e.get("origin") or ""), 1.0)
                j = node_index.setdefault(f"edge:{target}", len(node_index))
                entries.append((i, j, w))

        m = len(node_index)
        self.n, self.m = n, m
        self.labels = [None] * m
        for label, j in node_index.items():
            self.labels[j] = label
        self.node_index = node_index
        W = np.zeros((n, m), dtype=np.float64)
        for i, j, w in entries:
            W[i, j] = max(W[i, j], w)
        # degree = how many chunks carry the node; pervasive → lighter edges
        self.count = (W > 0).sum(axis=0).astype(np.int64) if m else np.zeros(0, dtype=np.int64)
        idf = 1.0 / np.log(2.0 + self.count) if m else np.zeros(0)
        self.W = W * idf[None, :]
        # row/col-stochastic transitions (dangling rows/cols stay zero)
        rs = self.W.sum(axis=1); cs = self.W.sum(axis=0)
        self.P_cn = np.divide(self.W, rs[:, None], out=np.zeros_like(self.W), where=rs[:, None] > 0)
        self.P_nc = np.divide(self.W, cs[None, :], out=np.zeros_like(self.W), where=cs[None, :] > 0)
        self.chunk_dangling = rs <= 0
        self.node_dangling = cs <= 0
        # per-chunk node sets, for the "shared concept" requirement + `why`
        self.chunk_nodes = [set(np.nonzero(W[i])[0].tolist()) for i in range(n)] if m else [set() for _ in range(n)]

    def ppr(self, e_chunks: np.ndarray, e_nodes: np.ndarray, *, alpha: float = ALPHA,
            iters: int = ITERS) -> tuple[np.ndarray, np.ndarray]:
        """Personalised PageRank on the bipartite graph. `e_chunks`/`e_nodes`
        together form the teleport vector (they are normalised here)."""
        e_c = e_chunks.astype(np.float64); e_n = e_nodes.astype(np.float64)
        tot = e_c.sum() + e_n.sum()
        if tot <= 0:
            return np.zeros(self.n), np.zeros(self.m)
        e_c /= tot; e_n /= tot
        p_c, p_n = e_c.copy(), e_n.copy()
        for _ in range(iters):
            # dangling mass (nodes with no edges) restarts at the teleport vector
            lost = float(p_c[self.chunk_dangling].sum() + p_n[self.node_dangling].sum())
            new_n = p_c @ self.P_cn                  # chunk → node
            new_c = self.P_nc @ p_n                  # node → chunk
            p_c = alpha * e_c + (1 - alpha) * (new_c + lost * e_c)
            p_n = alpha * e_n + (1 - alpha) * (new_n + lost * e_n)
        return p_c, p_n

    def match_theme(self, text: str) -> list[int]:
        """Node indices whose label tokens overlap the theme's tokens."""
        toks = _tokens(text)
        if not toks:
            return []
        out = []
        for j, label in enumerate(self.labels):
            lab = label[5:] if label.startswith("edge:") else label
            if _tokens(lab) & toks:
                out.append(j)
        return out


def _graph_builder(ctx: Context, use_edges: bool):
    def build():
        concepts = concepts_side(ctx)
        edges = edges_side(ctx) if use_edges else []
        return ConceptGraph(ctx.chunks, concepts, edges, use_edges=use_edges)
    return build


class ConceptEngine(BaseEngine):
    key = "concept"
    label = "Concept graph"
    blurb = ("Walks the chunk–concept graph instead of vector space: personalised "
             "PageRank from the seed over shared concepts (and human/judged bridges), "
             "so passages from other books that name the same idea surface even "
             "when their surface similarity is low. `why` names the shared concepts.")
    needs = ["concepts"]
    params = {
        "exclude_same_book": {"type": "bool", "default": True,
                              "help": "never connect a passage to its own book"},
        "alpha": {"type": "float", "default": ALPHA,
                  "help": "teleport probability (higher = stays closer to the seed)"},
        "iters": {"type": "int", "default": ITERS, "help": "power-iteration steps"},
        "min_activation": {"type": "float", "default": MIN_ACTIVATION,
                           "help": "floor on PPR mass; below it a chunk is not a pick"},
        "use_edges": {"type": "bool", "default": USE_EDGES,
                      "help": "fold index/edges.jsonl bridges into the graph"},
    }

    # -- readiness ---------------------------------------------------------------
    def ready(self, ctx: Context) -> tuple[bool, str]:
        data = concepts_side(ctx)
        if not _concepts_ok(data):
            return False, "concepts not built (run: python -m rhizome.cli concepts)"
        cc = data["chunk_concepts"]
        if not any(c["id"] in cc for c in ctx.chunks):
            # built for another corpus / chunking — the graph would have no nodes
            return False, ("concepts do not cover this corpus — rebuild them "
                           "(run: python -m rhizome.cli concepts)")
        return True, ""

    def graph(self, ctx: Context, use_edges: bool = USE_EDGES) -> ConceptGraph:
        name = "concept_graph" if use_edges else "concept_graph_noedges"
        # the graph is derived from both files, so it goes stale with either
        stamp = (_concepts_stamp(), _edges_stamp() if use_edges else None)
        return ctx.side_fresh(name, stamp, _graph_builder(ctx, use_edges))

    # -- retrieval ---------------------------------------------------------------
    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   exclude_same_book: bool = True, alpha: float = ALPHA, iters: int = ITERS,
                   min_activation: float = MIN_ACTIVATION, use_edges: bool = USE_EDGES,
                   **_) -> list[dict]:
        ok, _why = self.ready(ctx)
        if not ok or k <= 0:
            return []
        g = self.graph(ctx, use_edges=bool(use_edges))
        if g.m == 0:
            return []

        e_c = np.zeros(g.n); e_n = np.zeros(g.m)
        seed_idx = ctx.index_of(seed.chunk_id) if seed.chunk_id else None
        if seed_idx is not None:
            seed_nodes = g.chunk_nodes[seed_idx]
            if not seed_nodes:
                return []          # the seed names no concept: nothing to walk from
            e_c[seed_idx] = 1.0
            how = "chunk"
        else:
            matched = g.match_theme(seed.text)
            if not matched:
                return []
            e_n[matched] = 1.0
            seed_nodes = set(matched)
            how = "theme"

        p_c, _p_n = g.ppr(e_c, e_n, alpha=float(alpha), iters=int(iters))
        seed_book = seed.book_id
        if seed_book is None and seed_idx is not None:
            seed_book = ctx.chunks[seed_idx].get("book_id")

        order = np.argsort(-p_c, kind="stable")
        out = []
        for idx in order:
            idx = int(idx)
            act = float(p_c[idx])
            if act < min_activation:
                break
            if idx == seed_idx:
                continue
            c = ctx.chunks[idx]
            if exclude_same_book and seed_book is not None and c.get("book_id") == seed_book:
                continue
            shared = seed_nodes & g.chunk_nodes[idx]
            if not shared:
                continue
            # most specific first (rarest concept), then by label for determinism
            shared_sorted = sorted(shared, key=lambda j: (int(g.count[j]), g.labels[j]))
            labels = [g.labels[j] for j in shared_sorted]
            named = ", ".join(_pretty(l) for l in labels[:WHY_CONCEPTS])
            why = f"via concepts: {named}" if how == "chunk" else f"theme matches concepts: {named}"
            pick = decorate(idx, ctx, path=self.key, why=why, score=act,
                            concepts=labels, activation=act)
            pick["score"] = round(act, 6)   # PPR mass is small; keep more digits
            out.append(pick)
            if len(out) >= k:
                break
        return finish(out, seed, ctx)


def _pretty(label: str) -> str:
    return label[5:] + " (bridge)" if label.startswith("edge:") else label


ENGINE = ConceptEngine()
