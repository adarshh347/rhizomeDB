"""Chunk map generator — see the world of chunks, not just store it (PRD R5).

Projects every chunk (all built levels) into 2D with one shared PCA over the
embeddings (same bge-base space, so propositions sit near their parents), tags
each node with its character + colour, and links parent↔child + top semantic
neighbour. Emits:

    index/chunkmap.json   the graph data (nodes + edges + stats) for reuse
    chunkmap.html         a self-contained, dependency-free interactive map
                          (data inlined → opens offline; no CDN, no vendor JS)

Run:  python -m tools.chunkmap          (or: rhizome chunkmap)
"""
import json
import pathlib

import numpy as np

from rhizome import config

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_JSON = config.INDEX_DIR / "chunkmap.json"
OUT_HTML = ROOT / "chunkmap.html"

# character → colour (controlled vocab from config); 'untagged' falls back
CHAR_COLORS = {
    "definitional": "#7fb0a3", "argumentative": "#d98c5f", "exegetical": "#9b8cd9",
    "illustrative": "#d9c45f", "poetic": "#d97fb0", "citation": "#7f95d9",
    "transitional": "#8a93a3", "aporetic": "#d95f5f", "historical": "#5fa8d9",
    "polemical": "#d9745f", "untagged": "#5a6172",
}
LEVEL_SHAPE = {"parent": "square", "chunk": "circle", "proposition": "triangle"}


def _load_level(level):
    cpath = config.chunks_path(level)
    epath = config.level_emb_path(level)
    if not cpath.exists() or not epath.exists():
        return [], None
    recs = [json.loads(l) for l in cpath.open(encoding="utf-8")]
    vecs = np.load(epath)
    if len(recs) != len(vecs):
        return [], None
    return recs, vecs


def _pca2(mat):
    """2D PCA via economy SVD; returns (N,2) float."""
    c = mat - mat.mean(axis=0, keepdims=True)
    U, S, _ = np.linalg.svd(c, full_matrices=False)
    xy = U[:, :2] * S[:2]
    # normalize to a friendly range
    xy = xy - xy.min(axis=0)
    span = xy.max(axis=0)
    span[span == 0] = 1.0
    return (xy / span) * 1000.0


def build():
    levels, recs_all, vecs_all = [], [], []
    for level in config.CHUNK_LEVELS:
        recs, vecs = _load_level(level)
        if not recs:
            continue
        levels.append(level)
        for r in recs:
            recs_all.append(r)
        vecs_all.append(vecs)
    if not recs_all:
        raise SystemExit("No levels built. Run `rhizome build --levels parent,chunk` first.")
    vecs = np.vstack(vecs_all)
    print(f"Projecting {len(recs_all)} nodes across levels {levels} ...")
    xy = _pca2(vecs)

    # per-level offset index ranges, for semantic-NN within a level
    nodes = []
    id_to_idx = {}
    for i, (r, (x, y)) in enumerate(zip(recs_all, xy)):
        char = (r.get("character") or "untagged")
        nodes.append({
            "id": r["id"], "l": r.get("level", "chunk"), "b": r["book_id"],
            "a": r.get("author") or "Unknown", "t": r.get("title") or r["book_id"],
            "c": char, "cd": r.get("character_desc", ""),
            "bl": r.get("context_blurb", ""),
            "w": len(r["text"].split()), "pg": r.get("page"),
            "x": round(float(x), 1), "y": round(float(y), 1),
            "p": r.get("parent_id"), "ch": r.get("child_ids") or [],
            "prev": " ".join(r["text"].split())[:200],
        })
        id_to_idx[r["id"]] = i

    # edges: parent↔child (solid) + top-1 semantic neighbour within level (dashed)
    edges = []
    for n in nodes:
        if n["p"] and n["p"] in id_to_idx:
            edges.append({"s": n["id"], "t": n["p"], "k": "pc"})
    # semantic neighbour per level (cosine top-1, excluding self)
    offset = 0
    for level, v in zip(levels, vecs_all):
        idxs = list(range(offset, offset + len(v)))
        offset += len(v)
        if len(v) < 2:
            continue
        sims = v @ v.T
        np.fill_diagonal(sims, -1)
        nn = sims.argmax(axis=1)            # j is LOCAL to this level's matrix
        for local, j in enumerate(nn):
            edges.append({"s": nodes[idxs[local]]["id"],
                          "t": nodes[idxs[int(j)]]["id"], "k": "sem"})

    # stats
    from collections import Counter
    per_level = Counter(n["l"] for n in nodes)
    per_char = Counter(n["c"] for n in nodes)
    per_book = Counter(n["b"] for n in nodes if n["l"] == "chunk")
    parents_per_book = Counter(n["b"] for n in nodes if n["l"] == "parent")
    density = {}
    for b in per_book:
        density[b] = {"chunks": per_book[b], "parents": parents_per_book.get(b, 0)}
    stats = {"per_level": dict(per_level), "per_character": dict(per_char),
             "per_book": dict(per_book), "density": density,
             "total_nodes": len(nodes), "levels": levels,
             "characterized": sum(1 for n in nodes if n["c"] != "untagged")}

    data = {"nodes": nodes, "edges": edges, "stats": stats,
            "char_colors": CHAR_COLORS, "level_shape": LEVEL_SHAPE}
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data), encoding="utf-8")
    print(f"Wrote {OUT_JSON}  ({len(nodes)} nodes, {len(edges)} edges)")
    OUT_HTML.write_text(_html(data), encoding="utf-8")
    print(f"Wrote {OUT_HTML}  (self-contained — opens offline)")
    print(f"  levels: {dict(per_level)}")
    print(f"  characters: {dict(per_char)}")
    return data


def _html(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    return _TEMPLATE.replace("/*__DATA__*/", payload)


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RhizomeDB · Chunk map</title>
<style>
:root{--bg:#0e1014;--panel:#171a21;--panel2:#1e222b;--line:#2a2f3a;--ink:#e7e9ee;--dim:#9aa3b2;--accent:#d98c5f}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;overflow:hidden}
#wrap{display:flex;height:100vh}
#side{width:300px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--line);padding:14px 16px;overflow:auto}
#side h1{font-family:Georgia,serif;font-size:20px;margin:0 0 2px}
#side .sub{color:var(--dim);font-size:12px;margin-bottom:12px}
.lens{display:flex;gap:6px;margin:0 0 12px}
.lens a{flex:1;text-align:center;font-size:12px;padding:5px 0;border:1px solid var(--line);border-radius:6px;color:var(--dim);text-decoration:none}
.lens a.on{background:var(--panel2);color:var(--ink);border-color:var(--accent)}
.sec{margin:14px 0 6px;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--dim)}
.f{display:flex;align-items:center;gap:7px;font-size:13px;padding:2px 0;cursor:pointer}
.f input{accent-color:var(--accent)}
.dot{width:11px;height:11px;border-radius:50%;flex-shrink:0}
.statline{font-size:12px;color:var(--dim)}
.statline b{color:var(--ink)}
#main{flex:1;position:relative}
canvas{display:block;background:radial-gradient(circle at 50% 40%, #12151c, #0c0e12)}
#tip{position:absolute;top:10px;right:10px;width:330px;max-height:92vh;overflow:auto;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:none}
#tip .who{font-weight:600}#tip .src{color:var(--dim);font-size:12px}
#tip .chartag{display:inline-block;font-size:11px;padding:2px 9px;border-radius:999px;margin:8px 0;color:#13161b;font-weight:600}
#tip .tx{font-family:Georgia,serif;font-size:13.5px;color:#cdd6e4;margin-top:6px}
#tip .blurb{font-style:italic;color:var(--dim);font-size:12.5px;margin-top:6px}
#tip a{color:var(--accent)}
#tip .lk{font-size:12px;color:var(--dim);margin-top:8px}
#hint{position:absolute;left:10px;bottom:10px;color:var(--dim);font-size:11.5px}
button.mini{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:12px}
</style></head><body>
<div id="wrap">
  <div id="side">
    <h1>Chunk map</h1>
    <div class="sub">the world of chunks — PCA of the corpus, coloured by character</div>
    <div class="lens"><a href="conceptmap.html">concept</a><a href="chunkmap.html" class="on">similarity</a></div>
    <div id="stats"></div>
    <div class="sec">Levels</div><div id="flevels"></div>
    <div class="sec">Character</div><div id="fchars"></div>
    <div class="sec">Books</div><div id="fbooks"></div>
    <div style="margin-top:12px"><button class="mini" id="reset">reset view</button></div>
  </div>
  <div id="main">
    <canvas id="cv"></canvas>
    <div id="tip"></div>
    <div id="hint">scroll = zoom · drag = pan · click a node for detail</div>
  </div>
</div>
<script>
const DATA=/*__DATA__*/;
const N=DATA.nodes, E=DATA.edges, CC=DATA.char_colors;
const idIdx={}; N.forEach((n,i)=>idIdx[n.id]=i);
const books=[...new Set(N.map(n=>n.b))].sort();
const levels=DATA.stats.levels;
const chars=[...new Set(N.map(n=>n.c))];
const show={level:{}, char:{}, book:{}};
levels.forEach(l=>show.level[l]=true); chars.forEach(c=>show.char[c]=true); books.forEach(b=>show.book[b]=true);

const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
let W,H,view={s:0.55,ox:0,oy:0}, sel=null;
function resize(){ W=cv.width=cv.clientWidth*devicePixelRatio; H=cv.height=cv.clientHeight*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0); draw(); }
function fit(){ view={s:0.55, ox:cv.clientWidth/2-500*0.55, oy:cv.clientHeight/2-500*0.55}; }
const X=n=>n.x*view.s+view.ox, Y=n=>n.y*view.s+view.oy;
function vis(n){ return show.level[n.l] && show.char[n.c] && show.book[n.b]; }
function rad(n){ return Math.max(1.6, Math.sqrt(n.w)/6*view.s + (n.l==='parent'?1.5:0)); }

function draw(){
  ctx.clearRect(0,0,cv.clientWidth,cv.clientHeight);
  // edges only for the selected node (keeps it legible)
  if(sel){
    const s=N[idIdx[sel]];
    E.forEach(e=>{ if(e.s!==sel && e.t!==sel) return;
      const a=N[idIdx[e.s]], b=N[idIdx[e.t]]; if(!a||!b) return;
      ctx.beginPath(); ctx.moveTo(X(a),Y(a)); ctx.lineTo(X(b),Y(b));
      ctx.strokeStyle=e.k==='pc'?'rgba(127,176,163,.8)':'rgba(217,140,95,.5)';
      ctx.setLineDash(e.k==='pc'?[]:[4,3]); ctx.lineWidth=e.k==='pc'?1.6:1; ctx.stroke(); });
    ctx.setLineDash([]);
  }
  for(const n of N){ if(!vis(n)) continue;
    const x=X(n),y=Y(n),r=rad(n);
    ctx.fillStyle=CC[n.c]||CC.untagged; ctx.globalAlpha=sel&&sel!==n.id?.5:.9;
    ctx.beginPath();
    if(n.l==='parent'){ ctx.rect(x-r,y-r,r*2,r*2); }
    else if(n.l==='proposition'){ ctx.moveTo(x,y-r);ctx.lineTo(x+r,y+r);ctx.lineTo(x-r,y+r);ctx.closePath(); }
    else { ctx.arc(x,y,r,0,7); }
    ctx.fill();
  }
  ctx.globalAlpha=1;
  if(sel){ const s=N[idIdx[sel]],x=X(s),y=Y(s); ctx.strokeStyle='#fff';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.arc(x,y,rad(s)+3,0,7);ctx.stroke(); }
}

function nearest(mx,my){ let best=null,bd=14*14;
  for(const n of N){ if(!vis(n))continue; const dx=X(n)-mx,dy=Y(n)-my,d=dx*dx+dy*dy;
    if(d<bd){bd=d;best=n;} } return best; }
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function showTip(n){ sel=n?n.id:null; const t=document.getElementById('tip');
  if(!n){t.style.display='none';draw();return;}
  const col=CC[n.c]||CC.untagged;
  const kids=n.ch.length?`<div class="lk">▾ ${n.ch.length} child unit(s)</div>`:'';
  const par=n.p?`<div class="lk">▴ parent: ${esc(n.p)}</div>`:'';
  t.innerHTML=`<div class="who">${esc(n.a)}</div><div class="src">${esc(n.t)}${n.pg?(' · p.'+n.pg):''} · ${esc(n.l)} · ${n.w}w · ${esc(n.id)}</div>`
    +`<span class="chartag" style="background:${col}">${esc(n.c)}</span>`
    +(n.cd?`<div class="src">${esc(n.cd)}</div>`:'')
    +(n.bl?`<div class="blurb">${esc(n.bl)}</div>`:'')
    +`<div class="tx">${esc(n.prev)}…</div>${par}${kids}`
    +(n.l==='chunk'?`<div class="lk"><a href="/reader?id=${encodeURIComponent(n.id)}" target="_blank">open &amp; annotate ↗</a> <span class="src">(needs the server)</span></div>`:'');
  t.style.display='block'; draw(); }

// interaction
let drag=null;
cv.onmousedown=e=>drag={x:e.clientX,y:e.clientY,ox:view.ox,oy:view.oy,moved:false};
cv.onmousemove=e=>{ if(!drag)return; const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
  if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true; view.ox=drag.ox+dx;view.oy=drag.oy+dy;draw(); };
window.onmouseup=e=>{ if(drag&&!drag.moved){ const r=cv.getBoundingClientRect();
  showTip(nearest(e.clientX-r.left,e.clientY-r.top)); } drag=null; };
cv.onwheel=e=>{ e.preventDefault(); const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=e.deltaY<0?1.1:1/1.1, ns=Math.max(.1,Math.min(8,view.s*f));
  view.ox=mx-(mx-view.ox)*(ns/view.s); view.oy=my-(my-view.oy)*(ns/view.s); view.s=ns; draw(); };
document.getElementById('reset').onclick=()=>{fit();draw();};

// sidebar
function chk(container,items,group,labelFn){
  document.getElementById(container).innerHTML=items.map(it=>{
    const c=labelFn(it); return `<label class="f"><input type="checkbox" data-g="${group}" data-v="${esc(it)}" checked>${c}</label>`;
  }).join('');
}
chk('flevels',levels,'level',l=>`${esc(l)} <span class="src">(${DATA.stats.per_level[l]||0})</span>`);
chk('fchars',chars,'char',c=>`<span class="dot" style="background:${CC[c]||CC.untagged}"></span>${esc(c)} <span class="src">(${DATA.stats.per_character[c]||0})</span>`);
chk('fbooks',books,'book',b=>`${esc(b.replace(/-/g,' ').slice(0,28))} <span class="src">(${DATA.stats.per_book[b]||0})</span>`);
document.querySelectorAll('#side input[type=checkbox]').forEach(cb=>cb.onchange=()=>{
  show[cb.dataset.g][cb.dataset.v]=cb.checked; draw(); });

const st=DATA.stats;
document.getElementById('stats').innerHTML=
  `<div class="statline"><b>${st.total_nodes}</b> nodes · <b>${st.characterized}</b> characterized</div>`
  +`<div class="statline">${levels.map(l=>`${l}: <b>${st.per_level[l]||0}</b>`).join(' · ')}</div>`;

addEventListener('resize',resize); fit(); resize();
</script></body></html>
"""


if __name__ == "__main__":
    build()
