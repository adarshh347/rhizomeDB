#!/usr/bin/env python3
"""Tiny zero-dependency web frontend for RhizomeDB.

Explains the pipeline, shows the real source of each stage, and streams each
exploration run live (Server-Sent Events): seed → resonance geometry → judging
→ synthesis. Run:

    .venv/bin/python serve.py          # then open http://localhost:8000

The judging + synthesis stages light up only if ANTHROPIC_API_KEY is set;
otherwise the run stops after the retrieval geometry (still fully usable).
"""
import inspect
import json
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from rhizome import config, chunk as chunk_mod, embed as embed_mod, store as store_mod, llm
from rhizome.catalog import load_catalog

ROOT = pathlib.Path(__file__).resolve().parent
INDEX_HTML = ROOT / "frontend" / "index.html"

_ENGINE = None


def get_engine():
    """Load the engine once (Store + LLM client) and reuse it."""
    global _ENGINE
    if _ENGINE is None:
        from rhizome.engine import Engine
        _ENGINE = Engine()
    return _ENGINE


def index_ready() -> bool:
    return config.CHUNKS_PATH.exists() and config.EMBEDDINGS_PATH.exists()


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


# ---- the live run -----------------------------------------------------------
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


def _struct_axis(eng, seed_text, candidates):
    """Compute the structural-similarity axis for each candidate.

    Retrieval ran on the *surface* query vector (direct similarity). Here we ask
    the LLM to name the seed's underlying *structure* (the move beneath its
    words), embed that, and measure each candidate against it. A passage that
    scores high structurally but low directly is the rhizomatic ideal: same
    shape of thought, different vocabulary. Returns {index: struct_sim} or {}.
    """
    if eng.client is None:
        return {}, None
    try:
        abstraction = llm.abstract_seed(seed_text, eng.client)
        avec = embed_mod.embed_query(abstraction)
    except Exception:
        return {}, None
    out = {}
    for i, c in enumerate(candidates):
        j = eng.store.by_id.get(c["id"])
        if j is not None:
            out[i] = round(float(avec @ eng.store.vecs[j]), 4)
    return out, abstraction


def run_explore(emit, *, theme=None, chunk_id=None, random=False, k=config.N_CANDIDATES):
    eng = get_engine()
    seed = eng.resolve_seed(theme=theme, chunk_id=chunk_id, random=random)
    is_question = theme is not None   # a typed query → long answer + follow-ups
    emit("seed", {"label": seed["label"], "text": seed["text"],
                  "author": seed["author"], "book_id": seed["book_id"]})

    candidates = eng.store.connections(
        seed["vec"], seed_book_id=seed["book_id"], seed_author=seed["author"], k=k)

    # Structural axis (one cheap LLM call) — lets the UI contrast structural
    # similarity against direct dissimilarity for every retrieved passage.
    struct, abstraction = _struct_axis(eng, seed["text"], candidates)

    def _direct(c):
        return c.get("similarity") or 0.0

    emit("candidates", {
        "params": {"total_chunks": len(eng.store), "skip_top": config.SKIP_TOP,
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
    verdicts = llm.judge_connections(seed["text"], candidates, eng.client)
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
        text = llm.synthesize(seed["text"], confirmed, eng.client, long=is_question)
        emit("exploration", {"text": text})
        _emit_tokens(emit, eng, "synthesize (long answer)")
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
        emit("note", {"text": f"Brainstorm layer skipped: {type(e).__name__}: {e}"})
    emit("done", {})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quieter console
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text, code=200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")   # never serve a stale page
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._html(INDEX_HTML.read_text(encoding="utf-8"))
        if path == "/api/status":
            cat = load_catalog()
            info = llm.provider_info()
            return self._json({
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
            })
        if path == "/api/workflow":
            return self._json({"stages": workflow()})
        if path == "/api/explore":
            return self._sse_explore(parse_qs(urlparse(self.path).query))
        return self._json({"error": "not found"}, 404)

    def _sse_explore(self, q):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")     # defeat any proxy buffering
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        # Open the stream immediately so the browser flips EventSource to OPEN
        # and stops buffering — a comment line is ignored by the SSE parser.
        self.wfile.write(b": ok\n\n")
        self.wfile.flush()

        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        try:
            if not index_ready():
                emit("error", {"text": "Index not built. Run: python -m rhizome.cli build"})
                return
            mode = (q.get("mode") or ["random"])[0]
            k = int((q.get("candidates") or [config.N_CANDIDATES])[0])
            value = (q.get("value") or [""])[0].strip()
            kwargs = {"k": k}
            if mode == "theme" and value:
                kwargs["theme"] = value
            elif mode == "chunk" and value:
                kwargs["chunk_id"] = value
            else:
                kwargs["random"] = True
            run_explore(emit, **kwargs)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                emit("error", {"text": f"{type(e).__name__}: {e}"})
            except Exception:
                pass


def main(port=8000):
    print(f"RhizomeDB frontend  →  http://localhost:{port}")
    print("  (Ctrl-C to stop)")
    if not index_ready():
        print("  NOTE: index not built yet — run `python -m rhizome.cli build` first.")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
