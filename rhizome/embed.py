"""Embed chunks locally with fastembed (ONNX bge-base) and persist vectors.

Vectors are L2-normalized so cosine similarity is a plain dot product. Output
is index/embeddings.npy (float32, row i ↔ chunk i in chunks.jsonl).
"""
import numpy as np

from . import config, chunk as chunk_mod


_EMBEDDERS = {}   # model_key -> TextEmbedding (loading is the slow part; cache them)


def _model_name(model_key: str) -> str:
    spec = config.EMBED_MODELS.get(model_key)
    if not spec:
        raise SystemExit(f"Unknown embedding model '{model_key}'. "
                         f"Known: {', '.join(config.EMBED_MODELS)}")
    return spec["name"]


def _preload_cuda():
    """Make the GPU reachable when onnxruntime-gpu is installed.

    The CUDA/cuDNN shared libraries ship as pip wheels under
    `site-packages/nvidia/*/lib`, which are not on the loader path — so ORT's
    CUDA provider fails to dlopen `libcublasLt.so.12` and silently falls back to
    CPU. `onnxruntime.preload_dlls()` (ORT ≥1.21) loads them into the process
    first. No-op on the CPU-only `onnxruntime` build (no such function) and
    harmless when there's no GPU, so it's always safe to call."""
    try:
        import onnxruntime as ort
        preload = getattr(ort, "preload_dlls", None)
        if callable(preload):
            preload()
    except Exception:
        pass


def active_providers(emb) -> list[str]:
    """The ONNX execution providers a built embedder is actually running on
    (e.g. ['CUDAExecutionProvider', 'CPUExecutionProvider']). Defensive: the
    session lives a couple of attributes deep and the layout shifts between
    fastembed versions, so we probe and shrug off anything unexpected."""
    for obj in (getattr(emb, "model", None), emb):
        session = getattr(getattr(obj, "model", None), "model", None)
        get = getattr(session, "get_providers", None)
        if callable(get):
            try:
                return list(get())
            except Exception:
                pass
    return []


def _embedder(model_key: str = config.DEFAULT_EMBED):
    """Lazily build and cache the ONNX embedder for a given model key.

    Device selection is fastembed's default `Device.AUTO`: it uses the GPU
    (CUDAExecutionProvider) when onnxruntime-gpu is installed and CUDA is
    available, and falls back to CPU otherwise. We deliberately do *not* pass an
    explicit providers list — that would raise on CPU-only machines instead of
    degrading — and instead log which provider actually won."""
    if model_key not in _EMBEDDERS:
        import os
        # The HF downloader times out on slow links by default; give it room.
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "180")
        _preload_cuda()
        from fastembed import TextEmbedding
        config.EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        emb = TextEmbedding(
            model_name=_model_name(model_key), cache_dir=str(config.EMBED_CACHE_DIR))
        provs = active_providers(emb)
        if provs:
            device = "GPU" if any("CUDA" in p for p in provs) else "CPU"
            print(f"  embedder '{model_key}' on {device} — providers: {', '.join(provs)}")
        _EMBEDDERS[model_key] = emb
    return _EMBEDDERS[model_key]


def build_embeddings(model_key: str = config.DEFAULT_EMBED, batch: int = 64) -> np.ndarray:
    chunks = chunk_mod.load_chunks()
    if not chunks:
        raise SystemExit("No chunks found. Run the chunk step first.")
    texts = [c["text"] for c in chunks]
    print(f"Embedding {len(texts)} chunks with {_model_name(model_key)} ({model_key}) ...")
    emb = _embedder(model_key)
    vecs = np.asarray(list(emb.embed(texts, batch_size=batch)), dtype=np.float32)
    # normalize so cosine similarity is a plain dot product
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms
    out = config.embeddings_path(model_key)
    np.save(out, vecs)
    print(f"Saved {vecs.shape} -> {out}")
    return vecs


def embed_texts(texts: list[str], model_key: str = config.DEFAULT_EMBED,
                batch: int = 64) -> np.ndarray:
    """Embed an arbitrary list of texts → normalized (N, dim) matrix. Used to
    build any level's vectors (parent, proposition, …) with the default model."""
    emb = _embedder(model_key)
    vecs = np.asarray(list(emb.embed(texts, batch_size=batch)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def embed_query(text: str, model_key: str = config.DEFAULT_EMBED) -> np.ndarray:
    """Embed a single free-text query into the same normalized space as the
    chosen model's corpus vectors. Asymmetric models (BGE, Arctic) get their
    query-side instruction prefix; the corpus passages were embedded without one
    (that asymmetry is how these models are trained to be used)."""
    prefix = config.EMBED_MODELS.get(model_key, {}).get("query_prefix", "")
    emb = _embedder(model_key)
    v = np.asarray(next(iter(emb.embed([prefix + text]))), dtype=np.float32)
    n = np.linalg.norm(v)
    return v / (n or 1.0)
