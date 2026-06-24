#!/usr/bin/env python3
"""Guided panel — a calm control surface for RhizomeDB.

Reads the current pipeline state (notes → annotations → graph, corpus, edges)
and bakes a single self-contained HTML page that:
  · shows the pipeline situation at a glance (a status strip),
  · walks you through what to do *one card at a time* (read this / explore this
    seed / do this action / chase this direction) — so dense docs don't have to
    be read all at once,
  · shows reading coverage per book and a small concept-graph.

Static + offline (data baked in). Re-run to refresh:  python3 tools/panel.py
"""
import datetime as dt
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # repo root on path

from rhizome import config, catalog as catalog_mod
from rhizome import notes as notes_mod
from rhizome import graph as graph_mod


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


def gather() -> dict:
    anns = notes_mod.load_annotations()
    edges = graph_mod.load_edges()
    cat = catalog_mod.load_catalog()
    notes_txt = _note_texts()
    all_note_text = " ".join(notes_txt.values()).lower()

    by_role = {}
    for a in anns:
        by_role[a["role"]] = by_role.get(a["role"], 0) + 1
    by_origin = {}
    for e in edges:
        by_origin[e["origin"]] = by_origin.get(e["origin"], 0) + 1

    # reading coverage: a book is "read" if a note references its title/stem
    books = []
    for bid, m in cat.items():
        title = (m.get("title") or bid)
        read = (bid.lower() in all_note_text) or (title.lower() in all_note_text)
        books.append({"id": bid, "title": title, "author": m.get("author") or "",
                      "read": read})

    # ---- the guided deck: one card at a time -----------------------------
    deck = []
    deck.append({"cat": "decide", "title": "Name the faculty",
                 "body": "Pick the word for what this engine does — beyond 'retrieval'. "
                         "Front-runner: Pratibhā. Alternates: Spanda, Darśana / Heuretics, Topos.",
                 "meta": "a parked decision — see ROADMAP.md §H"})
    for b in books:
        if not b["read"]:
            deck.append({"cat": "read", "title": f"Read & annotate: {b['title']}",
                         "body": f"{b['author']}. Read a section in the flow and annotate it in "
                                 f"the schema; or let the reader-agent take a first pass.",
                         "meta": f"book: {b['id']}"})
    for a in anns:
        if a["role"] == "seed" and a["text"]:
            deck.append({"cat": "explore", "title": "Evoke from this seed",
                         "body": a["text"][:300],
                         "meta": f"rhizome explore --note {a['note_id']}"})
    for a in anns:
        if a["role"] == "task" and a["text"]:
            deck.append({"cat": "do", "title": "Action",
                         "body": a["text"][:300], "meta": f"from {a['note_id']}"})
    for a in anns:
        if a["role"] == "direction" and a["text"]:
            deck.append({"cat": "chase", "title": "Direction to chase",
                         "body": a["text"][:300], "meta": f"from {a['note_id']}"})

    # ---- mini concept graph ---------------------------------------------
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
        "books": books, "deck": deck,
        "gnodes": gnodes, "gedges": gedges,
        "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>RhizomeDB — Panel</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
:root{--bg:#F4F0E8;--ink:#2B2722;--panel:#FBF8F2;--line:#E5DCCB;--accent:#C4533A;--muted:#857A6B;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:-apple-system,BlinkMacSystemFont,Inter,"Segoe UI",sans-serif;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:26px 24px 60px}
h1{font-family:Georgia,serif;font-size:26px;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.strip{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:26px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px;min-width:92px}
.stat .n{font-size:22px;font-weight:600}.stat .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.cols{display:grid;grid-template-columns:1.15fr .85fr;gap:22px}
@media(max-width:840px){.cols{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px 22px 18px;min-height:210px;display:flex;flex-direction:column}
.cat{font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:8px}
.card h2{font-family:Georgia,serif;font-size:20px;margin:0 0 10px}
.card .body{font-size:14.5px;color:#433d35;flex:1}
.card .meta{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted);background:#F1EADD;border-radius:7px;padding:6px 9px;margin-top:12px;word-break:break-word}
.nav{display:flex;align-items:center;gap:12px;margin-top:14px}
.nav button{border:1px solid var(--line);background:#fff;border-radius:9px;padding:7px 16px;font-size:13px;cursor:pointer}
.nav button:hover{border-color:var(--accent);color:var(--accent)}
.count{font-size:12px;color:var(--muted)}
.section h3{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 10px}
.book{display:flex;align-items:center;gap:9px;font-size:13.5px;padding:5px 0;border-bottom:1px dashed var(--line)}
.pill{font-size:10px;border-radius:20px;padding:1px 8px}
.read{background:#DCE8DC;color:#3f6b46}.unread{background:#F0E2D8;color:#9a5a3c}
#net{height:300px;background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-top:8px}
.catcolors{}
</style></head><body><div class="wrap">
<h1>RhizomeDB · Panel</h1>
<div class="sub">your pipeline at a glance, and one next step at a time · refreshed __WHEN__</div>
<div class="strip" id="strip"></div>
<div class="cols">
  <div>
    <div class="card" id="card">
      <div class="cat" id="c-cat"></div><h2 id="c-title"></h2>
      <div class="body" id="c-body"></div><div class="meta" id="c-meta"></div>
      <div class="nav"><button onclick="step(-1)">‹ Prev</button>
        <button onclick="step(1)">Next ›</button><span class="count" id="c-count"></span></div>
    </div>
    <div class="section" style="margin-top:22px"><h3>Reading coverage</h3><div id="books"></div></div>
  </div>
  <div class="section"><h3>Concept graph</h3><div id="net"></div>
    <div class="sub" style="margin-top:8px">authored · note · judged bridges, accreting</div></div>
</div></div>
<script>
const D = __DATA__;
const CC = {decide:"#7a5ca8", read:"#C4533A", explore:"#4F6D8C", do:"#6B8F71", chase:"#B07D48"};
// status strip
const s=D.status, cells=[["books",s.books],["chunks",s.chunks],["notes",s.notes],
  ["annotations",s.annotations],["edges",s.edges]];
document.getElementById("strip").innerHTML = cells.map(([l,n])=>
  `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("")
  + `<div class="stat"><div class="n">${s.llm_key?"on":"off"}</div><div class="l">llm key</div></div>`;
// deck
let i=0; const deck=D.deck;
function render(){const c=deck[i];
  document.getElementById("c-cat").textContent=c.cat; document.getElementById("c-cat").style.color=CC[c.cat]||"#857A6B";
  document.getElementById("c-title").textContent=c.title;
  document.getElementById("c-body").textContent=c.body;
  document.getElementById("c-meta").textContent=c.meta||"";
  document.getElementById("c-count").textContent=`step ${i+1} of ${deck.length}`;}
function step(d){i=(i+d+deck.length)%deck.length;render();} render();
// books
document.getElementById("books").innerHTML = D.books.map(b=>
  `<div class="book"><span class="pill ${b.read?'read':'unread'}">${b.read?'reading':'to read'}</span>
   <span>${b.title}</span></div>`).join("");
// graph
new vis.Network(document.getElementById("net"),
  {nodes:new vis.DataSet(D.gnodes.map(n=>({id:n.id,label:n.label,shape:"dot",size:11,
     font:{size:11},color:{background:"#C4533A",border:"#fff"}}))),
   edges:new vis.DataSet(D.gedges.map(e=>({from:e.from,to:e.to,label:e.rel,
     font:{size:9,color:"#857A6B"},color:{color: e.origin==='judged'?'#4F6D8C':e.origin==='authored'?'#C4533A':'#cdbfa6'},
     arrows:"to",dashes:e.origin==='note'})))},
  {physics:{stabilization:{iterations:120}},interaction:{hover:true},nodes:{borderWidth:2}});
</script></body></html>"""


def main():
    here = pathlib.Path(__file__).resolve().parent.parent
    data = gather()
    page = PAGE.replace("__DATA__", json.dumps(data)).replace("__WHEN__", data["when"])
    out = here / "build" / "panel.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    s = data["status"]
    print(f"panel -> {out}")
    print(f"  {s['books']} books · {s['chunks']} chunks · {s['annotations']} annotations "
          f"· {s['edges']} edges · deck of {len(data['deck'])} cards")


if __name__ == "__main__":
    main()
