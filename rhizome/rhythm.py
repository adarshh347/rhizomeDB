"""Reading Rhythm — passive behavioural reading capture (Phase 0).

The involuntary complement to explicit annotation: log lightweight reading
behaviour, reconstruct the session timeline *with idle and hidden time stripped*,
derive per-passage attention features, and score evidence-bound hotspots with
robust statistics (no ML, numpy only).

Symptom, not verdict — every hotspot is bound to its evidence (slow pace,
re-reads, a lingering selection) and offered back as an invitation, never a claim
about the reader's mind. Local-only, opt-in; the client decides whether to send.

  workspace/behavior/<book>.jsonl   raw events (enter/exit/scroll/select/idle/…)
  workspace/behavior/labels.jsonl   confirm/dismiss labels (active-learning seed)

Scoring (R3): robust z-score of ms/word vs the reader's own baseline, with
Bayesian shrinkage so thin-evidence passages pull toward baseline (no cold-start
false positives). A hotspot needs >=2 corroborating signals — a single long
dwell is never enough.
"""
import json
import time

import numpy as np

from . import workspace

BEHAVIOR_DIR = workspace.WORKSPACE_DIR / "behavior"

# Evidence / scoring constants (relative, not absolute — see PRD non-goals).
MIN_ATTENTIVE_MS = 1500     # below this a passage has too little evidence to score
PRIOR_MS = 9000             # shrinkage prior strength: ~9s of reading to trust a pace
Z_SLOW = 1.0                # robust-z above which a passage reads "slow for you"
MIN_BASELINE_PASSAGES = 8   # fewer than this scored → low confidence, no baseline


def _now_ms() -> int:
    return int(time.time() * 1000)


def behavior_path(book: str):
    return BEHAVIOR_DIR / f"{workspace._safe(book)}.jsonl"


def labels_path():
    return BEHAVIOR_DIR / "labels.jsonl"


# --- capture -----------------------------------------------------------------
def append_events(book: str, session: str, events: list[dict]) -> int:
    """Append a batch of client events, stamping the session id. Returns count."""
    BEHAVIOR_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with behavior_path(book).open("a", encoding="utf-8") as f:
        for e in events:
            if not isinstance(e, dict) or "t" not in e or "type" not in e:
                continue
            e["session"] = session
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
            n += 1
    return n


def load_events(book: str) -> list[dict]:
    p = behavior_path(book)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def clear_book(book: str) -> bool:
    p = behavior_path(book)
    if p.exists():
        p.unlink()
        return True
    return False


def logged_summary(book: str) -> dict:
    """The 'what's logged' view (guardrail R7): counts only, no interpretation."""
    events = load_events(book)
    by_type, sessions = {}, set()
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        sessions.add(e.get("session", ""))
    return {"total": len(events), "by_type": by_type,
            "sessions": len([s for s in sessions if s]),
            "path": str(behavior_path(book).relative_to(workspace.config.ROOT))}


# --- sessionize (R2) ---------------------------------------------------------
def _dead_intervals(events: list[dict]) -> list[tuple]:
    """Spans to subtract from dwell: idle ('idle'→'active') and tab-hidden
    ('hidden'→'visible'). Unclosed spans are ignored (no end → not counted)."""
    spans = []
    for open_t, close_t in (("idle", "active"), ("hidden", "visible")):
        start = None
        for e in events:
            if e["type"] == open_t and start is None:
                start = e["t"]
            elif e["type"] == close_t and start is not None:
                if e["t"] > start:
                    spans.append((start, e["t"]))
                start = None
    return spans


def _dead_overlap(s: int, e: int, dead: list[tuple]) -> int:
    return sum(max(0, min(e, d1) - max(s, d0)) for d0, d1 in dead)


def _features(events: list[dict], word_counts: dict) -> dict:
    """Per-passage attention features for a set of events (one session or all).
    Walks 'enter' events as visit boundaries; attentive time = wall time minus
    overlapping idle/hidden spans."""
    events = sorted(events, key=lambda e: e["t"])
    dead = _dead_intervals(events)
    # visit boundaries: each 'enter' starts a visit that ends at the next 'enter'/'exit'
    marks = [e for e in events if e["type"] in ("enter", "exit")]
    visits = {}   # passage -> list of attentive ms per visit
    selected = {}  # passage -> bool (selected without it becoming a highlight)
    for i, e in enumerate(marks):
        if e["type"] != "enter":
            continue
        pid = e.get("passage")
        if not pid:
            continue
        end = marks[i + 1]["t"] if i + 1 < len(marks) else e["t"]
        att = max(0, (end - e["t"]) - _dead_overlap(e["t"], end, dead))
        visits.setdefault(pid, []).append(att)
    for e in events:
        if e["type"] == "select" and not e.get("highlighted"):
            selected[e.get("passage")] = True

    out = {}
    for pid, durs in visits.items():
        att = int(sum(durs))
        words = max(1, int(word_counts.get(pid, 0)) or 1)
        out[pid] = {
            "attentive_ms": att,
            "ms_per_word": att / words,
            "revisits": max(0, len(durs) - 1),
            "first_pass_ms_per_word": durs[0] / words if durs else 0.0,
            "max_dwell_ms": int(max(durs)) if durs else 0,
            "selected_not_highlighted": bool(selected.get(pid)),
            "words": words,
        }
    return out


# --- scoring (R3) ------------------------------------------------------------
def _baseline(feats: dict):
    """Robust baseline (median + MAD) of ms/word over passages with real
    evidence. Returns (median, mad, n_evidence)."""
    xs = [f["ms_per_word"] for f in feats.values() if f["attentive_ms"] >= MIN_ATTENTIVE_MS]
    if len(xs) < 3:
        return None, None, len(xs)
    a = np.array(xs, dtype=float)
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med))) or (float(a.std()) or 1.0)
    return med, mad, len(xs)


def _score(feats: dict, med: float, mad: float) -> dict:
    """Annotate each passage with a shrinkage-corrected robust z and its signals."""
    scored = {}
    for pid, f in feats.items():
        att = f["attentive_ms"]
        # Bayesian shrinkage: thin evidence pulls the pace toward baseline.
        w = att / (att + PRIOR_MS)
        eff = w * f["ms_per_word"] + (1 - w) * med
        z = 0.6745 * (eff - med) / mad if mad else 0.0
        slow = z >= Z_SLOW and att >= MIN_ATTENTIVE_MS
        revisited = f["revisits"] >= 1
        selected = f["selected_not_highlighted"]
        signals = []
        if slow:
            signals.append(("slow", f"{eff/med:.1f}× your usual pace"))
        if revisited:
            signals.append(("revisited", f"returned {f['revisits']+1}×"))
        if selected:
            signals.append(("selected", "selected a line without highlighting"))
        scored[pid] = {**f, "speed_z": round(z, 2),
                       "signals": [s[0] for s in signals],
                       "evidence": "; ".join(s[1] for s in signals),
                       "hotspot": len(signals) >= 2}   # >=2 corroborating signals
    return scored


def compute(book: str, word_counts: dict) -> dict:
    """Full-history rhythm for a book: per-passage features + scores + baseline,
    for the heatmap (R6a) and self-portrait (R6d)."""
    feats = _features(load_events(book), word_counts)
    med, mad, n = _baseline(feats)
    have_baseline = n >= MIN_BASELINE_PASSAGES and med is not None
    passages = _score(feats, med, mad) if med is not None else \
        {pid: {**f, "speed_z": 0.0, "signals": [], "evidence": "", "hotspot": False}
         for pid, f in feats.items()}
    return {"book": book, "have_baseline": have_baseline,
            "baseline": {"median_ms_per_word": med, "mad": mad, "n_evidence": n},
            "passages": passages}


def _latest_session(book: str) -> str | None:
    sessions = [e.get("session") for e in load_events(book) if e.get("session")]
    return max(sessions) if sessions else None


def candidates(book: str, word_counts: dict, session: str | None = None) -> dict:
    """End-of-session candidate sparks (R6b): hotspots from one session, scored
    against the reader's whole-history baseline, minus anything already labelled."""
    session = session or _latest_session(book)
    all_events = load_events(book)
    base_feats = _features(all_events, word_counts)
    med, mad, n = _baseline(base_feats)
    if med is None or not session:
        return {"session": session, "have_baseline": False, "candidates": []}
    sess_feats = _features([e for e in all_events if e.get("session") == session], word_counts)
    scored = _score(sess_feats, med, mad)
    labelled = {l["passage_id"] for l in load_labels(book)}
    cands = [{"passage_id": pid, "evidence": s["evidence"], "signals": s["signals"],
              "speed_z": s["speed_z"], "revisits": s["revisits"],
              "attentive_ms": s["attentive_ms"]}
             for pid, s in scored.items() if s["hotspot"] and pid not in labelled]
    cands.sort(key=lambda c: c["speed_z"], reverse=True)
    return {"session": session, "have_baseline": n >= MIN_BASELINE_PASSAGES, "candidates": cands}


# --- labels (R6b → R5 active learning) ---------------------------------------
def add_label(book: str, passage_id: str, label: int, evidence: str = "") -> dict:
    BEHAVIOR_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"book": book, "passage_id": passage_id, "label": int(label),
           "evidence": evidence, "created": _now_ms()}
    with labels_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_labels(book: str | None = None) -> list[dict]:
    p = labels_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                r = json.loads(line)
                if book is None or r.get("book") == book:
                    out.append(r)
            except Exception:
                pass
    return out
