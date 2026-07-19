"""FastAPI boundary for Rhizome Reader v2 (default http://127.0.0.1:8010).

This is the one backend. It exposes:

  * the reader-v2 anchoring spine — quote resolution, selector bundles, and
    orphan-safe annotation creation against a book's canonical text;
  * the whole-book reader data (library, book payloads, per-book annotations,
    the raw spine for native rendering);
  * the exploration/panel surface (SSE explore stream, embedding compare,
    workflow source-view, sessions, chat, reading-rhythm behaviour).

Everything above the transport lives in ``rhizome.reader_service`` and
``rhizome.anchor``; the routes here are thin. In production the built React
frontend (``frontend/dist``) is served from ``/``; in dev the Vite server owns
the UI and proxies ``/api`` here.
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (anchor, config, imports, ingest, reader_service as rs, rhythm,
               sources, workspace)

MAX_UPLOAD_BYTES = 120 * 1024 * 1024  # 120 MB — comfortably fits a large scanned PDF


# --------------------------------------------------------------------------- #
# request models                                                              #
# --------------------------------------------------------------------------- #
class ResolveRequest(BaseModel):
    book_id: str
    quote: str = Field(min_length=1)
    prefix: str = ""
    suffix: str = ""


class AnnotationCreate(BaseModel):
    # Reader highlight against a book spine (book_id + quote), OR a legacy
    # passage/companion note (target/passage_id, no spine anchoring). Both
    # paths are supported so the panel and the native reader share one store.
    kind: str = "highlight"
    quote: str = ""
    note: str = ""
    color: str = "amber"
    source: str = "reader"
    origin: str = ""
    book_id: str = ""
    prefix: str = ""
    suffix: str = ""
    target: str = ""
    passage_id: str = ""
    msg_id: str = ""
    chat_target: str = ""
    locator: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    target: str
    message: str
    context: str = ""
    source_label: str = ""


class BehaviorRequest(BaseModel):
    book: str
    session: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    book: str = ""
    passage_id: str
    action: str
    evidence: str = ""


class MarkdownImport(BaseModel):
    book_id: str
    text: str = Field(min_length=1)


class PinRequest(BaseModel):
    chunk_id: str


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #
app = FastAPI(title="Rhizome Reader API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174", "http://localhost:5174",
                   "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

V2 = "/api/v2"


# ---- health + status --------------------------------------------------------
@app.get(f"{V2}/health")
def health():
    return {"status": "ok", "service": "rhizome-reader", "version": 2}


@app.get(f"{V2}/status")
def status():
    return rs.status_payload()


# ---- library + whole-book reader -------------------------------------------
@app.get(f"{V2}/books")
def books():
    return rs.books_index()


@app.get(f"{V2}/books/{{book_id}}")
def book(book_id: str):
    data = rs.book_payload(book_id)
    if data is None:
        raise HTTPException(404, f"unknown book id: {book_id!r}")
    return data


@app.get(f"{V2}/books/{{book_id}}/spine")
def book_spine(book_id: str):
    """The canonical converted text as one addressable character sequence — the
    substrate every selector resolves against and the MD renderer paints on."""
    try:
        text = anchor.load_spine(book_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"book_id": book_id, "length": len(text), "text": text}


@app.get(f"{V2}/books/{{book_id}}/annotations")
def book_annotations(book_id: str):
    return rs.book_annotations(book_id)


@app.get(f"{V2}/books/{{book_id}}/formats")
def book_formats(book_id: str):
    return {"book_id": book_id, "formats": sources.formats_for(book_id),
            "default": sources.default_format(book_id)}


@app.post(f"{V2}/books/upload", status_code=201)
async def upload_book(file: UploadFile = File(...)):
    """Accept a PDF/EPUB/MOBI, convert + index it, and return its library
    summary. The book is readable natively the moment this responds; it joins
    the vector index later when embeddings are rebuilt."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (max 120 MB)")
    try:
        return ingest.ingest(file.filename or "book", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # conversion failure — surface, don't 500 silently
        raise HTTPException(500, f"conversion failed: {type(exc).__name__}: {exc}") from exc


@app.get(f"{V2}/books/{{book_id}}/file")
def book_file(book_id: str):
    """Stream a book's original file (PDF/EPUB) for native rendering. 404 when
    the source file isn't present locally (it lives in R2, gitignored)."""
    from fastapi.responses import FileResponse

    info = sources.source_info(book_id)
    if not info["renderer"] or not info["native_available"]:
        raise HTTPException(404, f"no native source file available for {book_id!r}")
    media = sources.media_type_for(info["renderer"]) or "application/octet-stream"
    return FileResponse(info["path"], media_type=media,
                        filename=f"{book_id}.{info['renderer']}")


@app.get(f"{V2}/passage")
def passage(id: str = Query(...)):
    data = rs.passage_with_context(id)
    if data is None:
        raise HTTPException(404, "unknown chunk id")
    return data


@app.get(f"{V2}/plateau/{{chunk_id}}")
def plateau(chunk_id: str, refresh: bool = False):
    data = rs.plateau_payload(chunk_id, refresh=refresh)
    if data is None:
        raise HTTPException(404, "unknown chunk id")
    return data


# ---- anchoring --------------------------------------------------------------
@app.post(f"{V2}/anchors/resolve")
def resolve_anchor(body: ResolveRequest):
    try:
        result = anchor.resolve(body.quote, body.prefix, body.suffix,
                                book_id=body.book_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if result is None:
        return {"resolved": False, "orphaned": True}
    hits = anchor.chunks_for(result.spine_start, result.spine_end,
                             book_id=body.book_id)
    return {"resolved": True, "orphaned": False,
            "selector": anchor.selector_bundle(body.quote, body.prefix,
                                                body.suffix, result),
            "chunks": hits}


# ---- annotations ------------------------------------------------------------
@app.get(f"{V2}/annotations")
def annotations(book_id: str | None = None, origin: str | None = None,
                orphaned: bool | None = None, target: str | None = None,
                source: str | None = None, passage_id: str | None = None):
    rows = workspace.list_annotations(target, source=source, passage_id=passage_id)
    if book_id is not None:
        rows = [r for r in rows if r.get("book_id") == book_id
                or r.get("target", "").split("#", 1)[0] == book_id]
    if origin is not None:
        rows = [r for r in rows if r.get("origin") == origin]
    if orphaned is not None:
        rows = [r for r in rows if bool(r.get("orphaned")) is orphaned]
    return {"items": rows}


@app.post(f"{V2}/annotations", status_code=201)
def create_annotation(body: AnnotationCreate):
    # Path A — a reader highlight against a book spine: anchor it. An
    # unresolvable quote is stored as an orphan (never dropped), not rejected.
    if body.book_id and body.quote:
        try:
            return rs.create_anchored_annotation(
                body.book_id, body.quote, prefix=body.prefix, suffix=body.suffix,
                kind=body.kind, note=body.note, color=body.color,
                source=body.source, origin=body.origin, locator=body.locator)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    # Path B — a legacy passage / companion note (no spine anchoring). AI
    # annotations carry a passage_id; default the target to it so companion
    # notes group with the passage they grew from.
    target = body.target or body.passage_id
    rec = workspace.add_annotation(
        target, body.kind or "note", quote=body.quote, note=body.note,
        color=body.color, source=body.source, passage_id=body.passage_id,
        msg_id=body.msg_id, chat_target=body.chat_target, origin=body.origin)
    return {"annotation": rec, "chunks": [], "orphaned": False}


@app.delete(f"{V2}/annotations/{{ann_id}}")
def delete_annotation(ann_id: str):
    return {"ok": workspace.delete_annotation(ann_id)}


@app.get(f"{V2}/companion-notes")
def companion_notes(passage_id: str | None = None):
    return {"items": workspace.list_companion_notes(passage_id)}


# ---- imports (R8/R9) + orphan queue (R11) ----------------------------------
@app.post(f"{V2}/books/{{book_id}}/import/pdf")
def import_pdf(book_id: str):
    try:
        return imports.import_pdf_annotations(book_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post(f"{V2}/import/markdown")
def import_markdown(body: MarkdownImport):
    try:
        return imports.import_markdown(body.book_id, body.text)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post(f"{V2}/import/sidecar")
async def import_sidecar(book_id: str = Form(...), file: UploadFile = File(...)):
    """Import an EPUB reader's sidecar (KOReader .lua, Calibre/generic JSON, or
    CSV) against a book (R10). Format is sniffed from the file."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (max 120 MB)")
    try:
        return imports.import_epub_sidecar(book_id, file.filename or "sidecar", data)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, f"could not parse sidecar: {exc}") from exc


@app.get(f"{V2}/orphans")
def orphans(book_id: str | None = None):
    rows = [r for r in workspace.list_annotations() if r.get("orphaned")]
    if book_id is not None:
        rows = [r for r in rows if (r.get("book_id")
                or r.get("target", "").split("#", 1)[0]) == book_id]
    return {"items": rows}


@app.get(f"{V2}/orphans/{{ann_id}}/candidates")
def orphan_candidates(ann_id: str):
    return {"candidates": rs.orphan_candidates(ann_id)}


@app.post(f"{V2}/orphans/{{ann_id}}/pin")
def pin_orphan(ann_id: str, body: PinRequest):
    rec = rs.pin_orphan(ann_id, body.chunk_id)
    if rec is None:
        raise HTTPException(404, "orphan or chunk not found")
    return {"annotation": rec}


@app.post(f"{V2}/orphans/{{ann_id}}/dismiss")
def dismiss_orphan(ann_id: str):
    return {"ok": workspace.delete_annotation(ann_id)}


# ---- chat -------------------------------------------------------------------
@app.get(f"{V2}/chat")
def get_chat(target: str = ""):
    return {"messages": workspace.load_chat(target)}


@app.post(f"{V2}/chat")
def post_chat(body: ChatRequest):
    result = rs.chat_turn(body.target, body.message, body.context, body.source_label)
    if "error" in result:
        raise HTTPException(result.get("status", 400), result["error"])
    return result


# ---- sessions ---------------------------------------------------------------
@app.get(f"{V2}/sessions")
def sessions():
    return {"items": workspace.list_sessions()}


@app.get(f"{V2}/sessions/{{sid}}")
def get_session(sid: str):
    s = workspace.get_session(sid)
    if s is None:
        raise HTTPException(404, "not found")
    return s


@app.post(f"{V2}/sessions")
def save_session(payload: dict[str, Any]):
    return {"ok": True, **workspace.save_session(payload)}


@app.delete(f"{V2}/sessions/{{sid}}")
def delete_session(sid: str):
    return {"ok": workspace.delete_session(sid)}


# ---- reading rhythm / behaviour --------------------------------------------
@app.get(f"{V2}/rhythm")
def rhythm_view(book: str = ""):
    if not book:
        raise HTTPException(400, "book required")
    return rhythm.compute(book, rs.book_word_counts(book))


@app.get(f"{V2}/candidates")
def candidates(book: str = "", session: str | None = None):
    if not book:
        raise HTTPException(400, "book required")
    return rhythm.candidates(book, rs.book_word_counts(book), session)


@app.post(f"{V2}/candidates/confirm")
def candidates_confirm(body: ConfirmRequest):
    result = rs.confirm_candidate(body.book, body.passage_id, body.action, body.evidence)
    if "error" in result:
        raise HTTPException(result.get("status", 400), result["error"])
    return result


@app.get(f"{V2}/behavior/logged")
def behavior_logged(book: str = ""):
    if not book:
        raise HTTPException(400, "book required")
    return rhythm.logged_summary(book)


@app.post(f"{V2}/behavior")
def behavior_append(body: BehaviorRequest):
    n = rhythm.append_events(body.book, body.session, body.events or [])
    return {"ok": True, "stored": n}


@app.post(f"{V2}/behavior/clear")
def behavior_clear(book: str = Query(...)):
    return {"ok": rhythm.clear_book(book)}


# ---- panel: workflow / embeddings / eval / compare -------------------------
@app.get(f"{V2}/workflow")
def workflow():
    return {"stages": rs.workflow()}


@app.get(f"{V2}/embeddings")
def embeddings():
    return {"models": rs.embeddings_status()}


@app.get(f"{V2}/eval")
def eval_leaderboard(refresh: bool = False):
    return rs.run_eval(refresh=refresh)


@app.get(f"{V2}/compare")
def compare(mode: str = "theme", value: str = "",
            candidates: int = config.N_CANDIDATES, models: str = ""):
    return rs.compare_models(mode=mode, value=value, k=candidates, models=models)


# ---- the live exploration stream (SSE) -------------------------------------
def _sse(run) -> StreamingResponse:
    """Bridge the push-based ``run(emit)`` driver to an SSE response.

    ``run_explore`` blocks (retrieval + LLM calls) and emits progressively, so
    it runs on a worker thread feeding a queue the generator drains — the
    browser sees each stage the moment it happens.
    """
    q: queue.Queue = queue.Queue()

    def emit(event: str, data: dict):
        q.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")

    def worker():
        try:
            run(emit)
        except Exception as exc:  # surface, don't hang the stream
            q.put(f"event: error\ndata: {json.dumps({'text': f'{type(exc).__name__}: {exc}'})}\n\n")
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        yield ": ok\n\n"  # flip EventSource to OPEN immediately
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get(f"{V2}/explore")
def explore(mode: str = "random", value: str = "",
            candidates: int = config.N_CANDIDATES, embed: str = config.DEFAULT_EMBED):
    if not rs.index_ready():
        def not_ready(emit):
            emit("error", {"text": "Index not built. Run: python -m rhizome.cli build"})
        return _sse(not_ready)
    value = (value or "").strip()
    kwargs: dict[str, Any] = {"k": candidates, "embed_key": embed}
    if mode == "theme" and value:
        kwargs["theme"] = value
    elif mode == "chunk" and value:
        kwargs["chunk_id"] = value
    else:
        kwargs["random"] = True
    return _sse(lambda emit: rs.run_explore(emit, **kwargs))


# --------------------------------------------------------------------------- #
# static frontend (production build) — mounted last so it never shadows /api  #
# --------------------------------------------------------------------------- #
def mount_frontend(app: FastAPI) -> None:
    dist = config.ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        return  # dev mode: Vite serves the UI and proxies /api here

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    from fastapi.responses import HTMLResponse, FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # Serve a real file when one exists (favicon, vendored libs); otherwise
        # hand back index.html so client-side routing owns the path. index.html
        # is read per request (not cached at startup) so a frontend rebuild is
        # picked up without restarting the server.
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
            return FileResponse(candidate)
        return HTMLResponse((dist / "index.html").read_text(encoding="utf-8"))


mount_frontend(app)


def main():
    import uvicorn
    uvicorn.run("rhizome.api:app", host="127.0.0.1", port=8010, reload=True)


if __name__ == "__main__":
    main()
