"""Service layer for the panel + reader — the logic behind the HTTP boundary.

Everything here is pure(ish) domain logic extracted from the old stdlib
``serve.py`` so the FastAPI app (``rhizome/api.py``) can call it directly and
the transport is a thin shell. No FastAPI, no ``http.server`` imports live
here; a route is expected to be a one-liner over one of these functions.

Engines and stores are loaded once and cached (module globals), because the
embedding index is large and shared across every request.
"""
from __future__ import annotations

import inspect
import re as _re

import numpy as np

from . import (config, chunk as chunk_mod, embed as embed_mod,
               store as store_mod, llm, workspace, rhythm)
from .catalog import load_catalog


# ---- lazily-loaded, process-wide singletons ---------------------------------
_ENGINE = None
_READER_CHUNKS = None
_STORES: dict = {}
_EVAL_CACHE = None
_WORD_COUNTS: dict = {}

PLATEAU_CACHE_PATH = config.INDEX_DIR / "cache_plateau.json"


def reader_chunks():
    """Load passage text for the reader without requiring embeddings.

    Reading, browsing, and annotation only need chunks.jsonl.  Keeping this
    separate from Store means the library remains usable before (or without)
    the optional vector index being built.
    """
    global _READER_CHUNKS
    if _READER_CHUNKS is None:
        _READER_CHUNKS = chunk_mod.load_chunks()
    return _READER_CHUNKS


def get_engine():
    """Load the engine once (default Store + LLM client) and reuse it."""
    global _ENGINE
    if _ENGINE is None:
        from .engine import Engine
        _ENGINE = Engine()
    return _ENGINE


def get_store(model_key=config.DEFAULT_EMBED):
    """Cache one Store per embedding model (chunks are shared, vectors differ)."""
    if model_key not in _STORES:
        if model_key == config.DEFAULT_EMBED:
            _STORES[model_key] = get_engine().store
        else:
            _STORES[model_key] = store_mod.Store(model_key)
    return _STORES[model_key]


def index_ready() -> bool:
    return config.CHUNKS_PATH.exists() and config.EMBEDDINGS_PATH.exists()


def embeddings_status():
    """Each registered embedding model + whether its vectors are built."""
    out = []
    for key, spec in config.EMBED_MODELS.items():
        out.append({"key": key, "label": spec["label"], "dim": spec["dim"],
                    "ready": config.embeddings_path(key).exists(),
                    "default": key == config.DEFAULT_EMBED})
    return out


def run_eval(refresh=False):
    """In-domain embedding leaderboard (cached — it embeds the gold queries with
    every model, which takes a few seconds the first time)."""
    global _EVAL_CACHE
    if _EVAL_CACHE is None or refresh:
        from . import eval_embed
        _EVAL_CACHE = eval_embed.evaluate()
    return _EVAL_CACHE


def status_payload():
    cat = load_catalog()
    info = llm.provider_info()
    return {
        "index_ready": index_ready(),
        "n_chunks": sum(1 for _ in config.CHUNKS_PATH.open()) if index_ready() else 0,
        "books": [{"author": m.get("author"), "title": m.get("title")}
                  for m in cat.values()],
        "llm_enabled": info["enabled"],
        "provider": info["provider"],
        "providers": info.get("providers", []),
        "model": info["model"],
        "hint": info["hint"],
        "embed_model": config.EMBED_MODEL,
    }


# ---- workflow description (code pulled live from the real source) -----------
def workflow():
    stages = [
        {"key": "chunk", "title": "1 · Chunk",
         "blurb": "Each converted book is split into ~240-word passages that keep an "
                  "argument's flow intact, tagged with page + heading for citation. "
                  "A hygiene filter drops OCR junk, title pages, indexes and "
                  "bibliographies so only real prose is indexed.",
         "code": inspect.getsource(chunk_mod._is_boilerplate)},
        {"key": "embed", "title": "2 · Embed (local)",
         "blurb": "Passages become 768-dim vectors with a local ONNX model "
                  "(fastembed, bge-base) — no API key, no network. Vectors are "
                  "L2-normalized so cosine similarity is a plain dot product.",
         "code": inspect.getsource(embed_mod.build_embeddings)},
        {"key": "geometry", "title": "3 · Resonance geometry",
         "blurb": "The heart. NOT nearest-neighbour. It takes the seed, drops the "
                  "most-similar (obvious) matches, keeps a band of related-but-"
                  "distant passages, excludes the seed's own author, and MMR-"
                  "diversifies so picks span different books and ideas.",
         "code": inspect.getsource(store_mod.Store.connections)},
        {"key": "judge", "title": "4 · Judge (not-forced filter)",
         "blurb": "The configured LLM (Gemini, Groq, or Claude) reads each pairing "
                  "and decides whether a genuine resonance arises from the flow of "
                  "the theory, or whether it is forced (shared vocabulary, "
                  "manufactured reading). Forced links are dropped. This is the "
                  "prompt that does it:",
         "code": llm.JUDGE_SYSTEM},
        {"key": "synth", "title": "5 · Synthesize",
         "blurb": "Survivors are woven into a long cited 'exploration' that traces "
                  "the lines of flight between the passages — inspired by them, "
                  "citing each, an invitation to think across texts.",
         "code": llm.SYNTH_LONG_SYSTEM},
        {"key": "brainstorm", "title": "6 · Brainstorm (LLM + RAG)",
         "blurb": "One call over the picks builds three things grounded in the "
                  "corpus: a *line of interpretation* threading the passages, a "
                  "*comparison* putting them in tension, and five follow-up "
                  "questions — each opening a different line of flight.",
         "code": llm.BRAINSTORM_SYSTEM},
    ]
    return stages


# ---- passage reader ---------------------------------------------------------
def passage_with_context(chunk_id: str):
    """The full chunk plus its immediate neighbours in the same book, for the
    reader page. Returns None if the id is unknown."""
    chunks = reader_chunks()
    by_id = {c["id"]: i for i, c in enumerate(chunks)}
    i = by_id.get(chunk_id)
    if i is None:
        return None
    c = chunks[i]

    def brief(j):
        if j < 0 or j >= len(chunks):
            return None
        n = chunks[j]
        if n["book_id"] != c["book_id"]:
            return None
        return {"id": n["id"], "page": n.get("page"),
                "text": n["text"][:240] + ("…" if len(n["text"]) > 240 else "")}

    return {
        "id": c["id"], "book_id": c["book_id"], "author": c.get("author"),
        "title": c.get("title"), "heading": c.get("heading"), "page": c.get("page"),
        "text": c["text"],
        "prev": brief(i - 1), "next": brief(i + 1),
    }


# ---- whole-book reader ------------------------------------------------------
def _ann_counts_by_book():
    """How many annotations attach to each book (target == '<book_id>#<n>')."""
    counts = {}
    for a in workspace.list_annotations(None):
        t = a.get("target", "")
        bid = t.split("#", 1)[0] if "#" in t else None
        if bid:
            counts[bid] = counts.get(bid, 0) + 1
    return counts


def books_index():
    """Every book in the corpus with its reading-relevant stats, for the library
    landing page. Order: most chunks first (the meatier books up top)."""
    cat = load_catalog()
    per_book = {}
    for c in reader_chunks():
        b = c["book_id"]
        per_book[b] = per_book.get(b, 0) + 1
    anns = _ann_counts_by_book()
    out = []
    for bid, n in per_book.items():
        meta = cat.get(bid, {})
        out.append({"book_id": bid, "title": meta.get("title", bid),
                    "author": meta.get("author", "Unknown"),
                    "year": meta.get("year"), "n_chunks": n,
                    "n_annotations": anns.get(bid, 0)})
    out.sort(key=lambda b: b["n_chunks"], reverse=True)
    return {"books": out}


def book_payload(book_id: str):
    """A whole book as its ordered sequence of chunks, plus a heading-based table
    of contents. Returns None for an unknown book. The chunk ids are the SAME
    targets the annotation/chat APIs already use, so highlights attach per chunk
    and survive across the reader, the explore page, and saved sessions."""
    cat = load_catalog()
    chunks = [c for c in reader_chunks() if c["book_id"] == book_id]
    if not chunks:
        return None
    meta = cat.get(book_id, {})
    paras = []
    for c in chunks:
        h = (c.get("heading") or "").strip()
        paras.append({"id": c["id"], "heading": h or None, "page": c.get("page"),
                      "character": c.get("character"),
                      "character_desc": c.get("character_desc"),
                      "spine_start": c.get("spine_start"),
                      "spine_end": c.get("spine_end"),
                      "text": c["text"]})
    return {"book_id": book_id, "title": meta.get("title", book_id),
            "author": meta.get("author", "Unknown"), "year": meta.get("year"),
            "n_chunks": len(chunks), "toc": _build_toc(chunks), "paragraphs": paras}


def _build_toc(chunks):
    """A navigable contents rail for any book. Books differ: some tag every chunk
    with a section heading, some carry only page numbers, the dictionary has
    neither — so fall back heading → page-stride → passage-stride, and always
    return something clickable."""
    have_head = sum(1 for c in chunks if (c.get("heading") or "").strip())
    have_page = sum(1 for c in chunks if c.get("page") is not None)
    toc, last = [], None
    if have_head >= 3:
        for c in chunks:
            h = (c.get("heading") or "").strip()
            if h and h != last:
                toc.append({"heading": h, "id": c["id"], "page": c.get("page")})
                last = h
        if len(toc) <= 300:
            return toc
        # too granular (heading ~= per chunk): thin to ~120 evenly-spaced marks
        step = max(1, len(toc) // 120)
        return toc[::step]
    if have_page >= 3:
        for c in chunks:
            p = c.get("page")
            if p is not None and p != last and (last is None or p - last >= 5):
                toc.append({"heading": f"Page {p}", "id": c["id"], "page": p})
                last = p
        return toc
    # no structure at all — milestone every ~25 passages
    return [{"heading": f"Passage {i+1}", "id": c["id"], "page": None}
            for i, c in enumerate(chunks) if i % 25 == 0]


def book_word_counts(book_id: str) -> dict:
    """Per-passage word counts for a book (cached) — needed to normalise dwell
    into ms/word so long passages aren't mistaken for slow reading."""
    if book_id not in _WORD_COUNTS:
        _WORD_COUNTS[book_id] = {c["id"]: len(c["text"].split())
                                 for c in reader_chunks() if c["book_id"] == book_id}
    return _WORD_COUNTS[book_id]


def book_annotations(book_id: str):
    """All annotations across every chunk of one book, for the reader's notes
    rail (kept separate from the per-target annotations the panel posts to)."""
    items = [a for a in workspace.list_annotations(None)
             if a.get("target", "").split("#", 1)[0] == book_id]
    items.sort(key=lambda a: (a.get("target", ""), a.get("created", "")))
    return {"items": items}


# ---- Plateau: a deep-study page for a single passage ------------------------
def _heuristic_graph(text: str):
    """A concept graph without an LLM: salient phrases as nodes, sentence
    co-occurrence as edges. The fallback so the Plateau is always populated."""
    from collections import Counter
    from . import concepts as C
    grams = Counter(C._candidates(C._tokens(text)))
    ranked = [g for g, _ in grams.most_common(40)]
    picked = []
    for g in sorted(ranked, key=lambda g: (-(" " in g), -grams[g])):  # prefer multiword, frequent
        if all(g not in p and p not in g for p in picked):
            picked.append(g)
        if len(picked) >= 8:
            break
    concepts = [{"label": g, "gloss": ""} for g in picked]
    idx = {g: i for i, g in enumerate(picked)}
    pair = Counter()
    for s in _re.split(r"(?<=[.!?])\s+", text):
        sl = s.lower()
        present = [g for g in picked if g in sl]
        for a in range(len(present)):
            for b in range(a + 1, len(present)):
                pair[tuple(sorted((idx[present[a]], idx[present[b]])))] += 1
    edges = [{"a": a, "b": b, "relation": "co-occurs"} for (a, b), _ in pair.most_common(12)]
    return {"concepts": concepts, "edges": edges, "follow_ups": [], "angles": []}


def plateau_payload(chunk_id: str, refresh: bool = False):
    """Everything the Plateau page needs for one passage: the passage + nearby
    context, and an LLM study map (concept constellation + follow-ups + angles),
    cached by content hash so re-opening a passage costs no tokens."""
    eng = get_engine()
    store = eng.store
    i = store.by_id.get(chunk_id)
    if i is None:
        return None
    c = store.chunks[i]

    def neighbour(j):
        if 0 <= j < len(store.chunks) and store.chunks[j]["book_id"] == c["book_id"]:
            n = store.chunks[j]
            return {"id": n["id"], "page": n.get("page"), "text": n["text"]}
        return None

    from . import enrich
    cache = enrich._load_cache(PLATEAU_CACHE_PATH)
    h = enrich._hash(c["text"])
    study, source = cache.get(h), "cache"
    if study is None or refresh:
        if eng.client is not None:
            try:
                study = llm.study_passage(c["text"], eng.client)
                source = "llm"
                cache[h] = study
                enrich._save_cache(PLATEAU_CACHE_PATH, cache)
            except Exception as e:
                study = _heuristic_graph(c["text"])
                source = "heuristic" if not llm._is_rate_limit(e) else "heuristic-quota"
        else:
            study, source = _heuristic_graph(c["text"]), "heuristic"
    return {
        "chunk": {"id": c["id"], "book_id": c["book_id"], "author": c.get("author"),
                  "title": c.get("title"), "heading": c.get("heading"),
                  "page": c.get("page"), "character": c.get("character"),
                  "character_desc": c.get("character_desc"), "text": c["text"]},
        "context": {"prev": neighbour(i - 1), "next": neighbour(i + 1)},
        "graph": {"concepts": study.get("concepts", []), "edges": study.get("edges", [])},
        "follow_ups": study.get("follow_ups", []),
        "angles": study.get("angles", []),
        "source": source,
    }


# ---- the live exploration run (SSE emits are provided by the caller) --------
def _emit_tokens(emit, eng, stage):
    """Stream this stage's token usage + the running cumulative total."""
    c = eng.client
    if c is None:
        return
    lu = getattr(c, "last_usage", None) or {}
    tu = getattr(c, "total_usage", None) or {}
    emit("tokens", {
        "stage": stage,
        "provider": lu.get("provider") or getattr(c, "provider", None),
        "prompt": lu.get("prompt", 0), "completion": lu.get("completion", 0),
        "total": lu.get("total", 0),
        "cumulative": tu.get("total", 0),
        "failover": lu.get("failover") or [],
    })


def _resolve_seed(store, embed_key, *, theme=None, chunk_id=None, random=False):
    """Seed → {vec, text, book_id, author, label}, using a chosen model's store."""
    if theme is not None:
        return {"vec": embed_mod.embed_query(theme, embed_key), "text": theme,
                "book_id": None, "author": None, "label": f'theme: "{theme}"'}
    if chunk_id is not None:
        i = store.by_id[chunk_id]
    elif random:
        i = int(np.random.default_rng().integers(0, len(store.chunks)))
    else:
        raise ValueError("need theme=, chunk_id=, or random=True")
    c = store.chunks[i]
    label = f"{c['id']} ({c.get('author') or 'Unknown'}, {c.get('title') or c['book_id']})"
    return {"vec": store.vecs[i], "text": c["text"], "book_id": c["book_id"],
            "author": c.get("author"), "label": label}


def _struct_axis(eng, store, embed_key, seed_text, candidates):
    """Structural-similarity axis per candidate, in the chosen model's space.

    Retrieval ran on the *surface* query vector (direct similarity). Here we ask
    the LLM to name the seed's underlying *structure* (the move beneath its
    words), embed that with the SAME model, and measure each candidate against
    it. High structurally + low directly is the rhizomatic ideal: same shape of
    thought, different vocabulary. Returns ({index: struct_sim}, abstraction).
    """
    if eng.client is None:
        return {}, None
    try:
        abstraction = llm.abstract_seed(seed_text, eng.client)
        avec = embed_mod.embed_query(abstraction, embed_key)
    except Exception:
        return {}, None
    out = {}
    for i, c in enumerate(candidates):
        j = store.by_id.get(c["id"])
        if j is not None:
            out[i] = round(float(avec @ store.vecs[j]), 4)
    return out, abstraction


def run_explore(emit, *, theme=None, chunk_id=None, random=False,
                k=config.N_CANDIDATES, embed_key=config.DEFAULT_EMBED):
    """Drive one exploration, pushing SSE events through ``emit(event, data)``."""
    eng = get_engine()
    if embed_key not in config.EMBED_MODELS or not config.embeddings_path(embed_key).exists():
        embed_key = config.DEFAULT_EMBED
    store = get_store(embed_key)
    seed = _resolve_seed(store, embed_key, theme=theme, chunk_id=chunk_id, random=random)
    is_question = theme is not None   # a typed query → long answer + follow-ups
    emit("seed", {"label": seed["label"], "text": seed["text"],
                  "author": seed["author"], "book_id": seed["book_id"],
                  "embed_key": embed_key,
                  "embed_label": config.EMBED_MODELS[embed_key]["label"]})

    candidates = store.connections(
        seed["vec"], seed_book_id=seed["book_id"], seed_author=seed["author"], k=k)

    # Structural axis (one cheap LLM call) — lets the UI contrast structural
    # similarity against direct dissimilarity for every retrieved passage.
    struct, abstraction = _struct_axis(eng, store, embed_key, seed["text"], candidates)

    def _direct(c):
        return c.get("similarity") or 0.0

    emit("candidates", {
        "params": {"total_chunks": len(store), "skip_top": config.SKIP_TOP,
                   "pool": config.POOL, "min_sim": config.MIN_SIM,
                   "mmr_lambda": config.MMR_LAMBDA,
                   "exclude_same_author": config.EXCLUDE_SAME_AUTHOR},
        "excluded_author": seed["author"],
        "items": [{"index": i, "author": c.get("author") or "Unknown",
                   "title": c.get("title") or c["book_id"], "page": c.get("page"),
                   "chunk_id": c.get("id"),
                   "similarity": _direct(c),
                   "direct_dissimilarity": round(1.0 - _direct(c), 4),
                   "structural_similarity": struct.get(i),
                   "rank": c.get("rank"), "corpus_size": c.get("corpus_size"),
                   "text": c["text"]}
                  for i, c in enumerate(candidates)],
    })
    if abstraction:
        emit("abstraction", {"text": abstraction})
        _emit_tokens(emit, eng, "abstract (structural reading)")

    if not candidates:
        emit("note", {"text": "No candidates in the resonance band for this seed."})
        emit("done", {}); return
    if eng.client is None:
        emit("note", {"text": "Geometry-only mode — set GROQ_API_KEY (or GEMINI/"
                              "ANTHROPIC) to enable judging, synthesis & follow-ups."})
        emit("done", {}); return

    emit("stage", {"name": "judge", "status": "running"})
    try:
        verdicts = llm.judge_connections(seed["text"], candidates, eng.client)
    except Exception as e:
        if llm._is_rate_limit(e):
            emit("note", {"text": "LLM daily token quota reached on all configured "
                                  "providers — showing the retrieval geometry only. "
                                  "Judging, synthesis & follow-ups will work again once "
                                  "a provider's quota resets (or add another key)."})
        else:
            emit("note", {"text": f"Judging failed ({type(e).__name__}) — geometry only."})
        emit("done", {}); return
    vmap = {v.candidate_index: v for v in verdicts}
    confirmed = []
    vout = []
    for i, c in enumerate(candidates):
        v = vmap.get(i)
        if v is None:
            continue
        genuine = bool(v.connected and v.forced_risk != "high")
        vout.append({"index": i, "connected": v.connected, "genuine": genuine,
                     "forced_risk": v.forced_risk, "bridge_concept": v.bridge_concept,
                     "articulation": v.articulation,
                     "relation_to_query": v.relation_to_query,
                     "unique_shade": v.unique_shade, "confidence": v.confidence})
        if genuine:
            m = dict(c); m.update(bridge_concept=v.bridge_concept,
                                  articulation=v.articulation,
                                  relation_to_query=v.relation_to_query,
                                  unique_shade=v.unique_shade,
                                  forced_risk=v.forced_risk, confidence=v.confidence)
            confirmed.append(m)
    confirmed.sort(key=lambda c: c["confidence"], reverse=True)
    emit("verdicts", {"items": vout, "n_confirmed": len(confirmed)})
    _emit_tokens(emit, eng, "judge + justify")

    # The brainstorm + synthesis layers work on the picks. Prefer confirmed
    # connections; fall back to the raw resonance band so the run is still useful
    # even when the judge rejects everything.
    grounding = confirmed if confirmed else candidates

    if confirmed:
        emit("stage", {"name": "synthesize", "status": "running"})
        try:
            text = llm.synthesize(seed["text"], confirmed, eng.client, long=is_question)
            emit("exploration", {"text": text})
            _emit_tokens(emit, eng, "synthesize (long answer)")
        except Exception as e:
            msg = ("LLM quota reached — judging done, but synthesis & brainstorm "
                   "skipped. Try again after a provider resets.") if llm._is_rate_limit(e) \
                  else f"Synthesis failed: {type(e).__name__}."
            emit("note", {"text": msg}); emit("done", {}); return
    else:
        emit("note", {"text": "Every candidate read as forced — synthesizing from the "
                              "resonance band instead."})

    # Brainstorm: one call → line of interpretations + comparison + follow-ups.
    try:
        emit("stage", {"name": "brainstorm", "status": "running"})
        bs = llm.brainstorm(seed["text"], grounding, eng.client)
        _emit_tokens(emit, eng, "brainstorm (interpretation + comparison + follow-ups)")
        emit("brainstorm", {
            "interpretations": [{"passage": it.passage, "reading": it.reading}
                                for it in bs.interpretations],
            "comparisons": [{"between": cp.between, "contrast": cp.contrast}
                            for cp in bs.comparisons],
        })
        if bs.follow_ups:
            emit("followups", {"items": bs.follow_ups})
    except Exception as e:
        msg = ("Brainstorm skipped — LLM quota reached (the answer above stands)."
               if llm._is_rate_limit(e) else f"Brainstorm layer skipped: {type(e).__name__}.")
        emit("note", {"text": msg})
    emit("done", {})


def compare_models(*, mode="theme", value="", k=config.N_CANDIDATES, models=""):
    """Run the SAME query through several embedding models (geometry only, no
    LLM) so the UI can show how retrieval diverges by model."""
    value = (value or "").strip()
    keys = [m for m in (models or "").split(",") if m] or [
        s["key"] for s in embeddings_status() if s["ready"]]
    keys = [m for m in keys if config.embeddings_path(m).exists()]
    if mode == "theme" and not value:
        return {"error": "compare needs a theme value"}

    results = []
    for key in keys:
        try:
            store = get_store(key)
            seed = _resolve_seed(
                store, key,
                theme=value if mode == "theme" else None,
                chunk_id=value if mode == "chunk" else None,
                random=(mode == "random"))
            cands = store.connections(
                seed["vec"], seed_book_id=seed["book_id"],
                seed_author=seed["author"], k=k)
            results.append({
                "key": key, "label": config.EMBED_MODELS[key]["label"],
                "dim": config.EMBED_MODELS[key]["dim"],
                "items": [{"chunk_id": c["id"], "author": c.get("author") or "Unknown",
                           "title": c.get("title") or c["book_id"], "page": c.get("page"),
                           "rank": c.get("rank"), "similarity": c.get("similarity"),
                           "text": c["text"][:240] + ("…" if len(c["text"]) > 240 else "")}
                          for c in cands],
            })
        except Exception as e:
            results.append({"key": key, "label": key, "error": f"{type(e).__name__}: {e}"})
    return {"mode": mode, "value": value, "k": k, "results": results}


def chat_turn(target: str, message: str, context: str = "", source_label: str = ""):
    """Append the user message, run the LLM, append + return the reply.

    Returns a dict with an ``error`` key (and ``status``) when the message is
    empty or no provider is configured, so the route can pick the HTTP code.
    """
    message = (message or "").strip()
    if not message:
        return {"error": "empty message", "status": 400}
    eng = get_engine()
    if eng.client is None:
        return {"error": "LLM not configured (set a provider key).", "status": 503}
    history = workspace.load_chat(target)
    workspace.append_chat(target, "user", message)
    reply = llm.chat(context, history, message, eng.client, source_label=source_label)
    rec = workspace.append_chat(target, "assistant", reply)
    usage = dict(getattr(eng.client, "last_usage", {}) or {})
    return {"reply": reply, "msg_id": rec["msg_id"], "usage": usage,
            "cumulative": getattr(eng.client, "total_usage", {}).get("total", 0)}


def confirm_candidate(book: str, passage_id: str, action: str, evidence: str = ""):
    """Keep/Dismiss a candidate spark (R6b). Keep creates a real annotation
    (source:'spark') the reader can build on, plus a positive label; Dismiss
    records a negative label. Both feed the future personal model (R5)."""
    if not passage_id or action not in ("keep", "dismiss"):
        return {"error": "passage_id and action (keep|dismiss) required", "status": 400}
    annotation = None
    if action == "keep":
        annotation = workspace.add_annotation(
            passage_id, "note", note=f"Reading rhythm drew you here — {evidence}",
            source="spark", passage_id=passage_id)
    rhythm.add_label(book, passage_id, 1 if action == "keep" else 0, evidence)
    return {"ok": True, "annotation": annotation}
