"""Embed chunks locally with fastembed (ONNX bge-base) and persist vectors.

Vectors are L2-normalized so cosine similarity is a plain dot product. Output
is index/embeddings.npy (float32, row i ↔ chunk i in chunks.jsonl).
"""
import numpy as np

from . import config, chunk as chunk_mod


_EMBEDDER = None


def _embedder():
    """Lazily build and cache the ONNX embedder (loading it is the slow part)."""
    global _EMBEDDER
    if _EMBEDDER is None:
        import os
        # The HF downloader times out on slow links by default; give it room.
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "180")
        from fastembed import TextEmbedding
        config.EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _EMBEDDER = TextEmbedding(model_name=config.EMBED_MODEL,
                                  cache_dir=str(config.EMBED_CACHE_DIR))
    return _EMBEDDER


def build_embeddings(batch: int = 64) -> np.ndarray:
    chunks = chunk_mod.load_chunks()
    if not chunks:
        raise SystemExit("No chunks found. Run the chunk step first.")
    texts = [c["text"] for c in chunks]
    print(f"Embedding {len(texts)} chunks with {config.EMBED_MODEL} ...")
    emb = _embedder()
    vecs = np.asarray(list(emb.embed(texts, batch_size=batch)), dtype=np.float32)
    # normalize
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms
    np.save(config.EMBEDDINGS_PATH, vecs)
    print(f"Saved {vecs.shape} -> {config.EMBEDDINGS_PATH}")
    return vecs


def embed_query(text: str) -> np.ndarray:
    """Embed a single free-text seed into the same normalized space."""
    emb = _embedder()
    v = np.asarray(next(iter(emb.embed([text]))), dtype=np.float32)
    n = np.linalg.norm(v)
    return v / (n or 1.0)
