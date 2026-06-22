"""Plain (baseline) RAG — the deliberate opposite of constellatory evocation.

Where the engine *avoids* the obvious nearest neighbours (skip-top, near-dup
drop, same-book exclusion, MMR), ordinary RAG *wants* them: embed the question,
take the top-k most-similar passages by cosine, answer grounded in exactly those.

We expose the retrieved paragraphs and their similarity scores, so the *basis* of
every answer is visible — which is the point of having this baseline: you can see
what pure nearest-neighbour retrieval fetches, judge how lexically-vs-structurally
similar those passages are, and feel the contrast with what constellatory
retrieval does instead.
"""
import re

import numpy as np

from . import embed


ANSWER_SYSTEM = """\
You answer a question about philosophy using ONLY the supplied passages. Write a
thorough, genuinely long answer — multiple full paragraphs — that synthesises
what the passages say, develops the idea carefully, and stays faithful to them.
Cite the passages inline by number, like [2] or [3][5], wherever you draw on
them. If the passages do not actually address part of the question, say so plainly
rather than inventing — note what is missing. Do not pad; be long because you are
thorough, not because you repeat yourself. No headers or bullet lists — flowing
prose."""

FOLLOWUP_SYSTEM = """\
You are given a question and the passages used to answer it. Propose follow-up
questions that go deeper, sideways, or into tension — each genuinely pursuable in
a philosophy corpus, each opening a distinct new angle (not rephrasings of the
original). Return ONLY the questions, one per line, no numbering, no preamble."""


def retrieve(store, qvec: np.ndarray, k: int = 6) -> list[dict]:
    """Top-k nearest passages by cosine — no exclusions, no diversification.
    The plain baseline; this is what 'normal RAG' fetches."""
    sims = store.vecs @ qvec
    order = np.argsort(-sims)[:k]
    out = []
    for idx in order:
        c = dict(store.chunks[int(idx)])
        c["similarity"] = round(float(sims[int(idx)]), 4)
        out.append(c)
    return out


def _context(sources: list[dict]) -> str:
    return "\n\n".join(
        f"[{i + 1}] {c.get('author') or 'Unknown'}, {c.get('title') or c['book_id']}"
        + (f", p.{c['page']}" if c.get('page') else "") + f"\n{c['text']}"
        for i, c in enumerate(sources)
    )


def answer(question: str, store, client, k: int = 6,
           expand_to_parents: bool = False) -> dict:
    """Embed the question, retrieve top-k from `store` (which is bound to a level
    on the SOLID→LIQUID dial), answer grounded in those passages. With
    expand_to_parents, do small-to-big: match the precise units but hand the LLM
    their larger PARENT passages (the dial's core mechanism)."""
    qvec = embed.embed_query(question)
    matched = retrieve(store, qvec, k)
    sources = matched
    if expand_to_parents and getattr(store, "level", "chunk") != "parent":
        from . import chunking
        parents = chunking.parents_of(matched)
        if parents:
            sources = parents
    user = (f"QUESTION:\n{question}\n\nPASSAGES:\n{_context(sources)}\n\n"
            f"Write a thorough, long answer grounded in the passages, citing [n].")
    text = client.complete(ANSWER_SYSTEM, user, max_tokens=3000,
                           temperature=0.5, json_mode=False)
    return {"answer": text.strip(), "sources": sources, "matched": matched}


def followups(question: str, sources: list[dict], client, n: int = 5) -> list[str]:
    """LLM + the retrieved context → n follow-up questions."""
    user = (f"QUESTION:\n{question}\n\nPASSAGES:\n{_context(sources)}\n\n"
            f"Give {n} follow-up questions, one per line.")
    raw = client.complete(FOLLOWUP_SYSTEM, user, max_tokens=400,
                          temperature=0.85, json_mode=False)
    qs = [re.sub(r"^[\s\d\.\)\-•*]+", "", ln).strip() for ln in raw.splitlines() if ln.strip()]
    return [q for q in qs if len(q) > 8][:n]
