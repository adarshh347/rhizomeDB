#!/usr/bin/env python3
"""Doc-graph — the living context window.

Scans the project's markdown (notes, specs, plans, research) and emits a single
self-contained interactive HTML map: every document is a node, edges are the
references and shared concepts between them. Re-run any time to refresh — this
is meant to be regenerated as the corpus of plans grows, so the whole can be
grasped at a glance.

    python3 tools/docgraph.py                      # scan defaults -> docs_map.html
    python3 tools/docgraph.py --dir A --dir B --out map.html

No dependencies; embeds its data into the page (works offline). The graph
library (vis-network) loads from a CDN when you open the file.
"""
import argparse
import datetime as dt
import html
import json
import pathlib
import re

# Controlled vocabulary — the project's load-bearing concepts. Shared concepts
# between two docs become a (dashed) edge, so thematic kinship is visible.
CONCEPTS = [
    "constellatory", "evocation", "pratibha", "spanda", "darshana", "chamatkara",
    "aletheia", "unconcealment", "gelassenheit", "visranti", "rhizome", "rasa",
    "dhvani", "sphota", "structural", "hyde", "embedding", "chunking", "retrieval",
    "graph", "edge", "annotation", "schema", "judge", "bridge", "seed", "wander",
    "heidegger", "merleau-ponty", "deleuze", "abhinavagupta", "bhartrhari",
    "phenomenolog", "disclosure", "intra-corpus", "knowledge graph", "agentic",
]

KIND_COLOR = {
    "reading-note": "#C4533A",   # terracotta — the human/agent reading
    "spec":         "#6B8F71",   # sage — schemas / specs
    "research":     "#4F6D8C",   # slate — research briefs
    "theory":       "#B07D48",   # ochre — theory/vision notes
    "readme":       "#8A8A8A",   # grey — readmes
    "doc":          "#9A9A9A",
}
MDLINK = re.compile(r"\[[^\]]+\]\(([^)]+\.md)[^)]*\)")
WIKILINK = re.compile(r"\[\[([^\]]+?)\]\]")
HEADING = re.compile(r"^(#{1,4})\s+(.*\S)\s*$", re.M)


def infer_kind(path: pathlib.Path) -> str:
    name = path.name.lower()
    parent = path.parent.name.lower()
    if name in ("readme.md",):
        return "readme"
    if "schema" in name or "operating" in name:
        return "spec"
    if "research" in name:
        return "research"
    if parent == "notes":
        return "reading-note"
    if "notes_theory" in str(path).lower():
        return "theory"
    return "doc"


def first_summary(text: str) -> str:
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b:
            continue
        if b.startswith("#") or b.startswith("<!--") or b.startswith("---"):
            continue
        b = b.lstrip(">").strip()           # blockquote summaries count
        b = re.sub(r"[*`_#]", "", b)
        if len(b) > 30:
            return " ".join(b.split())[:280]
    return ""


def scan(dirs: list[pathlib.Path]) -> list[dict]:
    docs = []
    seen = set()
    for d in dirs:
        if not d.exists():
            continue
        for md in sorted(d.rglob("*.md")):
            sp = str(md)
            if "/converted/" in sp or "/.venv/" in sp or "/node_modules/" in sp:
                continue
            if sp in seen:
                continue
            seen.add(sp)
            text = md.read_text(encoding="utf-8", errors="ignore")
            tl = text.lower()
            hm = HEADING.search(text)
            title = hm.group(2) if hm else md.stem
            headings = [m.group(2) for m in HEADING.finditer(text)][:12]
            concepts = sorted({c for c in CONCEPTS if c in tl})
            links = set(re.findall(MDLINK, text)) | set(re.findall(WIKILINK, text))
            docs.append({
                "id": md.stem,
                "title": re.sub(r"[*`_]", "", title)[:80],
                "project": md.parent.parent.name if md.parent.name == "notes" else md.parent.name,
                "path": f"{md.parent.name}/{md.name}",
                "kind": infer_kind(md),
                "summary": first_summary(text),
                "headings": headings,
                "concepts": concepts,
                "links_raw": [str(x) for x in links],
                "size": len(text),
            })
    return docs


def build_edges(docs: list[dict]) -> list[dict]:
    by_stem = {d["id"]: d for d in docs}
    edges, pairseen = [], set()

    # 1) explicit references: a doc that names another doc's filename/stem/title
    for d in docs:
        body_refs = set()
        for raw in d["links_raw"]:
            stem = pathlib.PurePath(raw).stem
            if stem in by_stem and stem != d["id"]:
                body_refs.add(stem)
        for other in docs:
            if other["id"] == d["id"]:
                continue
            if other["id"] in body_refs:
                continue
            # bare mention of another doc's filename anywhere in this doc
            # (handled by links_raw already for md links; here catch stem mentions)
        for ref in body_refs:
            key = tuple(sorted((d["id"], ref)))
            if key in pairseen:
                continue
            pairseen.add(key)
            edges.append({"from": d["id"], "to": ref, "kind": "reference"})

    # 2) shared-concept kinship (dashed) when 2+ concepts overlap and no explicit link
    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            key = tuple(sorted((a["id"], b["id"])))
            if key in pairseen:
                continue
            shared = set(a["concepts"]) & set(b["concepts"])
            if len(shared) >= 2:
                pairseen.add(key)
                edges.append({"from": a["id"], "to": b["id"], "kind": "kin",
                              "shared": sorted(shared)})
    return edges


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>RhizomeDB — Context Window</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  :root{--bg:#F4F0E8;--ink:#2B2722;--panel:#FBF8F2;--line:#E0D8C8;--accent:#C4533A;}
  *{box-sizing:border-box} html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
  #wrap{display:flex;height:100vh}
  #net{flex:1;height:100%}
  #side{width:340px;border-left:1px solid var(--line);background:var(--panel);padding:18px 20px;overflow:auto}
  h1{font-size:15px;letter-spacing:.04em;text-transform:uppercase;margin:0 0 2px;color:var(--accent)}
  .sub{font-size:12px;color:#80776a;margin-bottom:14px}
  #q{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;margin-bottom:12px;font-size:13px}
  .legend{font-size:11.5px;color:#6c6358;line-height:1.9;margin-bottom:10px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
  #detail{border-top:1px solid var(--line);padding-top:14px;margin-top:6px}
  #detail h2{font-size:16px;margin:0 0 4px;font-family:Georgia,serif}
  #detail .path{font-size:11px;color:#9a9081;margin-bottom:10px;font-family:ui-monospace,monospace}
  #detail .sum{font-size:13px;line-height:1.55;color:#4a443c}
  #detail .tags{margin-top:12px}
  .tag{display:inline-block;font-size:10.5px;background:#EBE4D6;color:#6c6358;border-radius:20px;padding:2px 9px;margin:0 4px 5px 0}
  .hd{font-size:11px;color:#80776a;text-transform:uppercase;letter-spacing:.05em;margin:14px 0 5px}
  .hl{font-size:12.5px;color:#4a443c;line-height:1.5;padding-left:10px;border-left:2px solid var(--line);margin:3px 0}
  .empty{color:#a89e90;font-size:13px;font-style:italic}
</style></head><body><div id="wrap">
  <div id="net"></div>
  <div id="side">
    <h1>Context Window</h1>
    <div class="sub">__N__ documents · __E__ links · generated __WHEN__</div>
    <input id="q" placeholder="filter documents…">
    <div class="legend" id="legend"></div>
    <div id="detail"><div class="empty">Click a node to read its summary, headings and concepts. Drag to rearrange. Scroll to zoom.</div></div>
  </div></div>
<script>
const DOCS = __DOCS__, EDGES = __EDGES__, COLORS = __COLORS__;
const nodes = new vis.DataSet(DOCS.map(d=>({
  id:d.id, label:d.title, shape:"dot",
  size: 10 + Math.min(26, Math.sqrt(d.size)/10),
  color:{background:COLORS[d.kind]||"#999", border:"#fff"},
  font:{size:13, color:"#2B2722", face:"Inter"}, _d:d
})));
const edges = new vis.DataSet(EDGES.map(e=>({
  from:e.from, to:e.to,
  dashes: e.kind==="kin",
  color:{color: e.kind==="reference"?"#C4533A":"#cdbfa6", opacity: e.kind==="reference"?0.7:0.5},
  width: e.kind==="reference"?2:1, _e:e
})));
const net = new vis.Network(document.getElementById("net"), {nodes,edges}, {
  physics:{barnesHut:{gravitationalConstant:-4500, springLength:140, springConstant:0.03}, stabilization:{iterations:220}},
  interaction:{hover:true, tooltipDelay:120}, nodes:{borderWidth:2}
});
const KINDS={}; DOCS.forEach(d=>KINDS[d.kind]=1);
document.getElementById("legend").innerHTML =
  Object.keys(KINDS).map(k=>`<span><span class="dot" style="background:${COLORS[k]}"></span>${k}</span>`).join("&nbsp;&nbsp;")
  + `<br><span style="color:#C4533A">━</span> references &nbsp; <span style="color:#cdbfa6">┄</span> shared concepts`;
function show(d){
  const hs = d.headings.length? `<div class="hd">Sections</div>`+d.headings.map(h=>`<div class="hl">${h}</div>`).join(""):"";
  const cs = d.concepts.length? `<div class="tags">`+d.concepts.map(c=>`<span class="tag">${c}</span>`).join("")+`</div>`:"";
  document.getElementById("detail").innerHTML =
    `<h2>${d.title}</h2><div class="path">${d.path}</div>`+
    (d.summary?`<div class="sum">${d.summary}</div>`:"")+ cs + hs;
}
net.on("click", p=>{ if(p.nodes.length){ show(nodes.get(p.nodes[0])._d); }});
document.getElementById("q").addEventListener("input", e=>{
  const t=e.target.value.toLowerCase();
  nodes.update(DOCS.map(d=>({id:d.id, hidden: t && !(d.title+" "+d.concepts.join(" ")+" "+d.path).toLowerCase().includes(t)})));
});
</script></body></html>"""


def main():
    here = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", default=None, help="directory to scan (repeatable)")
    ap.add_argument("--out", default=str(here / "docs_map.html"))
    args = ap.parse_args()

    if args.dir:
        dirs = [pathlib.Path(d).expanduser() for d in args.dir]
    else:
        dirs = [here, pathlib.Path.home() / "Documents/projects/semant/Semant/notes_theory"]
    dirs = [d for d in dirs if d.exists()]

    docs = scan(dirs)
    edges = build_edges(docs)
    page = (PAGE
            .replace("__DOCS__", json.dumps(docs))
            .replace("__EDGES__", json.dumps(edges))
            .replace("__COLORS__", json.dumps(KIND_COLOR))
            .replace("__N__", str(len(docs)))
            .replace("__E__", str(len(edges)))
            .replace("__WHEN__", dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    out = pathlib.Path(args.out)
    out.write_text(page, encoding="utf-8")
    print(f"{len(docs)} docs, {len(edges)} edges -> {out}")
    for d in docs:
        print(f"  [{d['kind']:12s}] {d['path']:48s} {len(d['concepts'])} concepts")


if __name__ == "__main__":
    main()
