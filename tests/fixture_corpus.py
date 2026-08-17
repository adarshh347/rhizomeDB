"""A small deterministic in-memory corpus for engine tests.

Four "books" by three authors, ~12 chunks each, with vectors drawn so that each
book has a topical centre (so same-book chunks are near each other), plus a
handful of deliberate cross-book "bridges" (chunk pairs whose vectors are
pulled together across books). Text is generated from small vocabularies so a
lexical engine has something real to match on.

    from fixture_corpus import make_corpus
    chunks, vecs = make_corpus()
    ctx = Context.from_arrays(chunks, vecs)
"""
from __future__ import annotations

import numpy as np

BOOKS = [
    ("alpha", "Ada Alpha", "The Open Region"),
    ("beta", "Bruno Beta", "Repose and Flash"),
    ("gamma", "Ada Alpha", "Letting Be"),
    ("delta", "Dora Delta", "Structure of the Move"),
]

# per-book vocabularies (a shared core so lexical overlap exists across books)
CORE = ["thinking", "being", "question", "opening", "world", "word", "time"]
VOCAB = {
    "alpha": CORE + ["region", "releasement", "waiting", "gathering", "presence", "clearing"],
    "beta":  CORE + ["repose", "flash", "wonder", "rasa", "stillness", "delight"],
    "gamma": CORE + ["letting", "dwelling", "calm", "path", "field", "gelassenheit"],
    "delta": CORE + ["structure", "move", "form", "shape", "figure", "abstraction"],
}

DIM = 32
PER_BOOK = 12
# (book_a, i, book_b, j): chunk i of book_a resonates with chunk j of book_b
BRIDGES = [("alpha", 3, "beta", 7), ("gamma", 5, "delta", 2), ("alpha", 9, "delta", 8)]


def _unit(v):
    return v / (np.linalg.norm(v) + 1e-12)


def make_corpus(seed: int = 7, per_book: int = PER_BOOK, dim: int = DIM):
    rng = np.random.default_rng(seed)
    centres = {b: rng.normal(size=dim) for b, _, _ in BOOKS}
    chunks, vecs = [], []
    for bid, author, title in BOOKS:
        vocab = VOCAB[bid]
        for i in range(per_book):
            words = list(rng.choice(vocab, size=28, replace=True))
            # a distinctive token per chunk so exact lexical hits are possible
            words.append(f"{bid}token{i}")
            text = " ".join(words) + "."
            chunks.append({
                "id": f"{bid}#{i:04d}", "book_id": bid, "author": author, "title": title,
                "page": i + 1, "heading": f"Section {i // 4}", "text": text,
                "spine_start": i * 200, "spine_end": i * 200 + len(text),
            })
            v = 0.7 * centres[bid] + rng.normal(size=dim)
            vecs.append(v)
    vecs = np.asarray(vecs, dtype=np.float32)
    idx = {c["id"]: n for n, c in enumerate(chunks)}
    for ba, i, bb, j in BRIDGES:
        a, b = idx[f"{ba}#{i:04d}"], idx[f"{bb}#{j:04d}"]
        shared = rng.normal(size=dim)
        vecs[a] = 0.35 * vecs[a] + 1.2 * shared
        vecs[b] = 0.35 * vecs[b] + 1.2 * shared
    vecs = np.asarray([_unit(v) for v in vecs], dtype=np.float32)
    return chunks, vecs


def bridge_pairs():
    return [(f"{a}#{i:04d}", f"{b}#{j:04d}") for a, i, b, j in BRIDGES]
