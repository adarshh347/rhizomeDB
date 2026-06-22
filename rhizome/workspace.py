"""Local, UI-driven workspace persistence: annotations, AI chats, and saved
pipeline sessions. Everything lives under ROOT/workspace/ as plain JSON so it is
inspectable, gitignorable, and independent of the CLI reading-notes loop in
notes.py (which parses human-authored Markdown markup — a different concern).

  workspace/annotations.jsonl   one record per highlight / comment / note
  workspace/chats/<target>.jsonl  one record per chat message, per target
  workspace/sessions/<id>.json  a whole captured pipeline run

A "target" is whatever a note attaches to: a chunk id ("being-and-truth#0042"),
or a synthetic key like "session:<id>" or "exploration:<id>".
"""
import hashlib
import json
import re
import time

from . import config

WORKSPACE_DIR = config.ROOT / "workspace"
ANNOT_PATH = WORKSPACE_DIR / "annotations.jsonl"
SESSIONS_DIR = WORKSPACE_DIR / "sessions"
CHATS_DIR = WORKSPACE_DIR / "chats"


def _ensure():
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    CHATS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _uid(prefix: str) -> str:
    # time-based + short hash; no Math.random needed, monotonic enough for a UI
    h = hashlib.sha1(f"{prefix}{time.time_ns()}".encode()).hexdigest()[:8]
    return f"{prefix}_{h}"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


# --- annotations -------------------------------------------------------------
def add_annotation(target: str, kind: str, *, quote: str = "", note: str = "",
                   color: str = "amber") -> dict:
    """kind: 'highlight' (a marked span, optional note) | 'note' (free comment)."""
    _ensure()
    rec = {"id": _uid("an"), "target": target, "kind": kind,
           "quote": quote.strip(), "note": note.strip(), "color": color,
           "created": _now()}
    with ANNOT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_annotations(target: str | None = None) -> list[dict]:
    if not ANNOT_PATH.exists():
        return []
    out = []
    with ANNOT_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if target is None or r.get("target") == target:
                out.append(r)
    return out


def delete_annotation(ann_id: str) -> bool:
    if not ANNOT_PATH.exists():
        return False
    rows = [json.loads(l) for l in ANNOT_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    kept = [r for r in rows if r.get("id") != ann_id]
    with ANNOT_PATH.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(kept) != len(rows)


# --- chats -------------------------------------------------------------------
def _chat_path(target: str):
    return CHATS_DIR / f"{_safe(target)}.jsonl"


def load_chat(target: str) -> list[dict]:
    p = _chat_path(target)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_chat(target: str, role: str, content: str) -> dict:
    _ensure()
    rec = {"role": role, "content": content, "created": _now()}
    with _chat_path(target).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# --- sessions ----------------------------------------------------------------
def save_session(payload: dict) -> dict:
    """Persist a whole captured pipeline run. Returns {id, title, when}."""
    _ensure()
    sid = payload.get("id") or _uid("ses")
    payload["id"] = sid
    payload.setdefault("when", _now())
    title = (payload.get("query") or payload.get("seed_label") or "session").strip()
    payload["title"] = title[:120]
    (SESSIONS_DIR / f"{sid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": sid, "title": payload["title"], "when": payload["when"]}


def list_sessions() -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []
    out = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"id": d.get("id", p.stem), "title": d.get("title", p.stem),
                    "query": d.get("query", ""), "when": d.get("when", ""),
                    "n_candidates": len(d.get("candidates", [])),
                    "has_exploration": bool(d.get("exploration"))})
    out.sort(key=lambda s: s.get("when", ""), reverse=True)
    return out


def get_session(sid: str) -> dict | None:
    p = SESSIONS_DIR / f"{_safe(sid)}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def delete_session(sid: str) -> bool:
    p = SESSIONS_DIR / f"{_safe(sid)}.json"
    if p.exists():
        p.unlink()
        return True
    return False
