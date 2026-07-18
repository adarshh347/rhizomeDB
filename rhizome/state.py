"""Live pipeline snapshot — the single source of truth for the panel.

Re-reads the index every call, so both the static panel (`tools/panel.py`) and
the running FastAPI backend (`rhizome/api.py`) reflect the current state: as you
annotate, rebuild, or explore, the next snapshot shows it.
"""
import datetime as dt
import os

from . import config, catalog as catalog_mod
from . import notes as notes_mod
from . import graph as graph_mod


def _chunk_count() -> int:
    try:
        with config.CHUNKS_PATH.open(encoding="utf-8") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


def _note_texts() -> dict:
    out = {}
    if config.NOTES_DIR.exists():
        for md in config.NOTES_DIR.rglob("*.md"):
            out[md.stem] = md.read_text(encoding="utf-8", errors="ignore")
    return out


def snapshot() -> dict:
    anns = notes_mod.load_annotations()
    edges = graph_mod.load_edges()
    cat = catalog_mod.load_catalog()
    notes_txt = _note_texts()
    all_note_text = " ".join(notes_txt.values()).lower()

    by_role, by_origin = {}, {}
    for a in anns:
        by_role[a["role"]] = by_role.get(a["role"], 0) + 1
    for e in edges:
        by_origin[e["origin"]] = by_origin.get(e["origin"], 0) + 1

    books = []
    for bid, m in cat.items():
        title = m.get("title") or bid
        read = (bid.lower() in all_note_text) or (title.lower() in all_note_text)
        books.append({"id": bid, "title": title,
                      "author": m.get("author") or "", "read": read})

    deck = [{"cat": "decide", "title": "Name the faculty",
             "body": "Pick the word for what this engine does — beyond 'retrieval'. "
                     "Front-runner: Pratibhā. Alternates: Spanda, Darśana / Heuretics, Topos.",
             "meta": "a parked decision — ROADMAP.md §H"}]
    for b in books:
        if not b["read"]:
            deck.append({"cat": "read", "title": f"Read & annotate: {b['title']}",
                         "body": f"{b['author']}. Read a section in the flow and annotate it; "
                                 f"or let the reader-agent take a first pass.",
                         "meta": f"book: {b['id']}"})
    for a in anns:
        if a["role"] == "seed" and a["text"]:
            deck.append({"cat": "explore", "title": "Evoke from this seed",
                         "body": a["text"][:300], "meta": f"note: {a['note_id']}",
                         "seed_note": a["note_id"]})
    for a in anns:
        if a["role"] == "task" and a["text"]:
            deck.append({"cat": "do", "title": "Action", "body": a["text"][:300],
                         "meta": f"from {a['note_id']}"})
    for a in anns:
        if a["role"] == "direction" and a["text"]:
            deck.append({"cat": "chase", "title": "Direction to chase",
                         "body": a["text"][:300], "meta": f"from {a['note_id']}"})

    gnodes, seen = [], set()
    for e in edges:
        for side in (e["source"], e["target"]):
            if side not in seen:
                seen.add(side)
                gnodes.append({"id": side, "label": side[:36]})
    gedges = [{"from": e["source"], "to": e["target"], "rel": e["relation"],
               "origin": e["origin"]} for e in edges]

    return {
        "status": {
            "books": len(books), "chunks": _chunk_count(),
            "notes": len(notes_txt), "annotations": len(anns),
            "edges": len(edges), "by_role": by_role, "by_origin": by_origin,
            "llm_key": any(os.environ.get(k) for k in
                           ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY")),
        },
        "books": books, "deck": deck, "gnodes": gnodes, "gedges": gedges,
        "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
