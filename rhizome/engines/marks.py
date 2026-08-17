"""`marks` — my marks. Retrieval over the reader's own highlights and notes.

The human half of the loop feeding retrieval: every annotation the reader has
made (`workspace.list_annotations()`) is embedded as *quote + note*, and the
seed is scored against those mark vectors by cosine. A mark that resonates is
returned as the chunk it sits on, with the note as the `why` — so a passage can
recall "what I once wrote in another book" rather than what the corpus happens
to say nearby. Cross-book by nature; the seed chunk itself is never a pick.

Side indexes (built lazily on the Context, overridable by tests):
    annotations   the raw annotation list, cached against the (mtime, size) of
                  `workspace.ANNOT_PATH` — a highlight written after the engine
                  first ran is picked up on the next call, not after a restart.
    marks_vecs    {"ids": tuple(annotation ids), "vecs": (N, dim)} — rebuilt when
                  the id tuple no longer matches the annotation list, so a new
                  highlight is picked up by a long-running server.
"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseEngine, Context, Seed, file_stamp, finish

MIN_SIM = 0.25            # floor: cosine(seed, mark) below this is not a resonance
EXCLUDE_SAME_BOOK = False  # marks in the seed's own book are allowed by default
QUOTE_CLIP = 200
WHY_CLIP = 80


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def mark_text(a: dict) -> str:
    return ((a.get("quote") or "") + " " + (a.get("note") or "")).strip()


def usable_marks(annotations: list[dict]) -> list[dict]:
    """Marks with text that are not orphaned (order preserved)."""
    return [a for a in annotations if mark_text(a) and not a.get("orphaned")]


def resolve_chunk(a: dict, ctx: Context) -> int | None:
    """chunk_ids[0..] present in ctx → target (if a chunk id) → passage_id."""
    for cid in a.get("chunk_ids") or []:
        i = ctx.index_of(cid)
        if i is not None:
            return i
    for key in ("target", "passage_id"):
        cid = a.get(key)
        if cid:
            i = ctx.index_of(cid)
            if i is not None:
                return i
    return None


class MarksEngine(BaseEngine):
    key = "marks"
    label = "My marks"
    blurb = ("Your own highlights and notes, embedded, scored by cosine from the seed. "
             "A pick is the passage one of your marks sits on; the why is the mark itself — "
             "what you once wrote, recalled from another book.")
    needs = ["vectors", "annotations"]
    params = {
        "min_sim": {"type": "float", "default": MIN_SIM,
                    "help": "floor on cosine(seed, mark) — below it a mark is not a resonance"},
        "exclude_same_book": {"type": "bool", "default": EXCLUDE_SAME_BOOK,
                              "help": "skip marks that sit in the seed's own book"},
    }

    # -- side data -----------------------------------------------------------
    def _annotations(self, ctx: Context) -> list[dict]:
        from .. import workspace
        return ctx.side_fresh("annotations", file_stamp(workspace.ANNOT_PATH),
                              workspace.list_annotations)

    def _marks(self, ctx: Context) -> list[dict]:
        return usable_marks(self._annotations(ctx))

    def _mark_vecs(self, ctx: Context, marks: list[dict]) -> np.ndarray:
        ids = tuple(a["id"] for a in marks)
        cur = ctx._side.get("marks_vecs")
        if cur is None or tuple(cur.get("ids", ())) != ids:
            def build():
                from .. import embed as embed_mod
                vecs = embed_mod.embed_texts([mark_text(a) for a in marks], ctx.embed_key)
                return {"ids": ids, "vecs": np.asarray(vecs, dtype=np.float32)}
            ctx.drop_side("marks_vecs")
            cur = ctx.side("marks_vecs", build)
        return cur["vecs"]

    # -- contract ------------------------------------------------------------
    def ready(self, ctx: Context) -> tuple[bool, str]:
        ok, why = super().ready(ctx)
        if not ok:
            return ok, why
        try:
            marks = self._marks(ctx)
        except Exception as e:  # workspace unreadable etc.
            return False, f"annotations unavailable ({e})"
        if not marks:
            return False, "no marks yet — highlight or note something first"
        if not any(resolve_chunk(a, ctx) is not None for a in marks):
            return False, "none of your marks sit on a passage in this corpus"
        return True, ""

    def candidates(self, seed: Seed, ctx: Context, *, k: int = config.N_CANDIDATES,
                   min_sim: float = MIN_SIM, exclude_same_book: bool = EXCLUDE_SAME_BOOK,
                   **_) -> list[dict]:
        if seed.vec is None or not ctx.has_vectors:
            return []
        marks = self._marks(ctx)
        if not marks or not any(resolve_chunk(a, ctx) is not None for a in marks):
            return []
        vecs = self._mark_vecs(ctx, marks)
        qv = np.asarray(seed.vec, dtype=np.float32)
        if vecs.ndim != 2 or len(vecs) != len(marks) or vecs.shape[1] != qv.shape[0]:
            return []
        sims = vecs @ qv

        best: dict[int, tuple[float, int]] = {}   # chunk idx -> (sim, mark position)
        for j, a in enumerate(marks):
            s = float(sims[j])
            if s < min_sim:
                continue
            idx = resolve_chunk(a, ctx)
            if idx is None:
                continue
            c = ctx.chunks[idx]
            if seed.chunk_id and c["id"] == seed.chunk_id:
                continue
            if exclude_same_book and seed.book_id and c.get("book_id") == seed.book_id:
                continue
            prev = best.get(idx)
            if prev is None or s > prev[0]:
                best[idx] = (s, j)

        order = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))[:k]
        picks = []
        for idx, (s, j) in order:
            a = marks[j]
            kind = a.get("kind") or "highlight"
            note, quote = (a.get("note") or "").strip(), (a.get("quote") or "").strip()
            if kind == "note" and note:
                why = f"your note — “{_clip(note, WHY_CLIP)}”"
            elif quote:
                why = f"your highlight — “{_clip(quote, WHY_CLIP)}”"
            else:
                why = f"your {kind} — “{_clip(note or quote, WHY_CLIP)}”"
            p = dict(ctx.chunks[idx])
            p.update({
                "score": round(s, 4), "path": self.key, "why": why,
                "annotation_id": a.get("id"), "kind": kind, "color": a.get("color"),
                "quote": _clip(quote, QUOTE_CLIP), "note": note,
                "mark_similarity": round(s, 4),
            })
            picks.append(p)
        return finish(picks, seed, ctx)


ENGINE = MarksEngine()
