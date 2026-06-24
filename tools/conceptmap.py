"""Concept map generator — the CONTENT lens (the study instrument).

Where the chunk map shows *that* chunks cluster, this shows *what the corpus is
about*: concepts laid out by co-occurrence (ideas that travel together sit near),
sized by how widely they're used, coloured by which text owns them. Click a
concept to see its SITES across the corpus — every passage that works with it,
and (when characterized) what kind of move each site makes. That is the study
question: "where does this idea live, and what does each site do with it?"

A first lens, deliberately falsifiable: mark concepts alive/dead as you explore
(saved in-browser, exportable) so we learn whether this view earns its keep —
and dismiss or mutate it if it doesn't.

    index/conceptmap.json   graph data (concept nodes + co-occurrence edges)
    conceptmap.html         self-contained, dependency-free interactive map

Run:  python -m tools.conceptmap        (or: rhizome conceptmap)
"""
import json
import pathlib
from collections import Counter, defaultdict

import numpy as np

from rhizome import config, concepts as concepts_mod, chunking

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_JSON = config.INDEX_DIR / "conceptmap.json"
OUT_HTML = ROOT / "conceptmap.html"

# A calm, distinguishable palette assigned to books (dominant-book colouring).
PALETTE = ["#7fb0a3", "#d98c5f", "#9b8cd9", "#d9c45f", "#d97fb0",
           "#7f95d9", "#5fa8d9", "#d9745f", "#8fbf7f", "#c98fbf"]

MAX_SITES = 40          # sites listed per concept (keeps the file lean)
SNIPPET = 240


def _pca2(mat):
    c = mat - mat.mean(axis=0, keepdims=True)
    U, S, _ = np.linalg.svd(c, full_matrices=False)
    xy = U[:, :2] * S[:2]
    xy = xy - xy.min(axis=0)
    span = xy.max(axis=0)
    span[span == 0] = 1.0
    return (xy / span) * 1000.0


def build():
    cdata = concepts_mod.load_concepts()
    concept_list = cdata["concepts"]
    chunk_concepts = cdata["chunk_concepts"]
    if not concept_list:
        raise SystemExit("No concepts. Run: rhizome concepts")

    ids = [c["id"] for c in concept_list]
    idx = {cid: i for i, cid in enumerate(ids)}
    C = len(ids)

    # Co-occurrence over the chunk assignments (ideas that travel together).
    cooc = np.zeros((C, C), dtype=np.float32)
    for labels in chunk_concepts.values():
        present = [idx[l] for l in labels if l in idx]
        for a in range(len(present)):
            for b in range(a + 1, len(present)):
                i, j = present[a], present[b]
                cooc[i, j] += 1
                cooc[j, i] += 1

    xy = _pca2(cooc) if C > 2 else np.zeros((C, 2))

    books = sorted({b for c in concept_list for b in c["books"]})
    book_color = {b: PALETTE[i % len(PALETTE)] for i, b in enumerate(books)}

    nodes = []
    for c, (x, y) in zip(concept_list, xy):
        dom = max(c["books"].items(), key=lambda kv: kv[1])[0] if c["books"] else ""
        nodes.append({"id": c["id"], "label": c["label"], "n": c["count"],
                      "dom": dom, "books": c["books"],
                      "x": round(float(x), 1), "y": round(float(y), 1)})

    # Edges: each concept's strongest co-occurrence partners (deduped).
    edges = []
    seen = set()
    for i in range(C):
        order = np.argsort(cooc[i])[::-1]
        kept = 0
        for j in order:
            j = int(j)
            if j == i or cooc[i, j] < 2:
                continue
            key = (min(i, j), max(i, j))
            if key not in seen:
                seen.add(key)
                edges.append({"s": ids[i], "t": ids[j], "w": int(cooc[i, j])})
            kept += 1
            if kept >= 4:
                break

    # Sites: every concept -> the passages that work with it, for the panel.
    chunks = {c["id"]: c for c in chunking.load_level("chunk")}
    by_concept = defaultdict(list)
    for chunk_id, labels in chunk_concepts.items():
        ch = chunks.get(chunk_id)
        if not ch:
            continue
        for l in labels:
            if l in idx and len(by_concept[l]) < MAX_SITES:
                by_concept[l].append({
                    "id": chunk_id, "b": ch["book_id"],
                    "ch": ch.get("character", ""), "cd": ch.get("character_desc", ""),
                    "prev": " ".join(ch["text"].split())[:SNIPPET]})
    sites = {k: v for k, v in by_concept.items()}

    stats = {"concepts": C, "edges": len(edges), "mode": cdata.get("mode", "?"),
             "books": len(books), "chunks_tagged": len(chunk_concepts)}
    data = {"nodes": nodes, "edges": edges, "sites": sites,
            "book_color": book_color, "stats": stats}

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data), encoding="utf-8")
    print(f"Wrote {OUT_JSON}  ({C} concepts, {len(edges)} edges, mode={cdata.get('mode')})")
    OUT_HTML.write_text(_html(data), encoding="utf-8")
    print(f"Wrote {OUT_HTML}  (self-contained — opens offline)")
    return data


def _html(data: dict) -> str:
    return _TEMPLATE.replace("/*__DATA__*/", json.dumps(data, separators=(",", ":")))


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RhizomeDB · Concept map</title>
<style>
:root{--bg:#0e1014;--panel:#171a21;--panel2:#1e222b;--line:#2a2f3a;--ink:#e7e9ee;--dim:#9aa3b2;--accent:#d98c5f;--alive:#6fcf97;--dead:#7a818f}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;overflow:hidden}
#wrap{display:flex;height:100vh}
#side{width:300px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--line);padding:14px 16px;overflow:auto}
#side h1{font-family:Georgia,serif;font-size:20px;margin:0 0 2px}
#side .sub{color:var(--dim);font-size:12px;margin-bottom:10px}
.lens{display:flex;gap:6px;margin:0 0 12px}
.lens a{flex:1;text-align:center;font-size:12px;padding:5px 0;border:1px solid var(--line);border-radius:6px;color:var(--dim);text-decoration:none}
.lens a.on{background:var(--panel2);color:var(--ink);border-color:var(--accent)}
.sec{margin:14px 0 6px;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--dim)}
.statline{font-size:12px;color:var(--dim)}.statline b{color:var(--ink)}
#q{width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:6px 8px;font-size:13px}
#clist{margin-top:8px}
.ci{display:flex;justify-content:space-between;gap:6px;padding:3px 6px;border-radius:5px;cursor:pointer;font-size:13px}
.ci:hover{background:var(--panel2)}.ci .n{color:var(--dim);font-size:11px}
.ci.alive{box-shadow:inset 3px 0 0 var(--alive)}.ci.dead{opacity:.45;box-shadow:inset 3px 0 0 var(--dead)}
.f{display:flex;align-items:center;gap:7px;font-size:12.5px;padding:1px 0;cursor:pointer}
.dot{width:11px;height:11px;border-radius:50%;flex-shrink:0}
#main{flex:1;position:relative}
canvas{display:block;background:radial-gradient(circle at 50% 40%, #12151c, #0c0e12)}
#tip{position:absolute;top:10px;right:10px;width:360px;max-height:94vh;overflow:auto;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:none}
#tip h2{font-family:Georgia,serif;margin:0 0 2px;font-size:19px}
#tip .meta{color:var(--dim);font-size:12px}
.marks{display:flex;gap:8px;margin:10px 0}
.marks button{flex:1;background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;cursor:pointer;font-size:12px}
.marks button.alive.on{background:var(--alive);color:#0e1014;border-color:var(--alive)}
.marks button.dead.on{background:var(--dead);color:#0e1014;border-color:var(--dead)}
.bar{display:flex;height:7px;border-radius:4px;overflow:hidden;margin:8px 0}
.site{border-top:1px solid var(--line);padding:8px 0}
.site .s{color:var(--dim);font-size:11px}
.site .chartag{display:inline-block;font-size:10px;padding:1px 7px;border-radius:999px;background:var(--panel2);color:var(--dim);margin-left:4px}
.site .tx{font-family:Georgia,serif;font-size:13px;color:#cdd6e4;margin-top:3px}
.site a{color:var(--accent);font-size:11px;text-decoration:none}
#hint{position:absolute;left:10px;bottom:10px;color:var(--dim);font-size:11.5px}
button.mini{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:12px}
</style></head><body>
<div id="wrap">
  <div id="side">
    <h1>Concept map</h1>
    <div class="sub">what the corpus is about — concepts by co-occurrence, coloured by text</div>
    <div class="lens"><a href="conceptmap.html" class="on">concept</a><a href="chunkmap.html">similarity</a></div>
    <div id="stats"></div>
    <div class="sec">Find a concept</div>
    <input id="q" placeholder="filter concepts…" autocomplete="off">
    <div id="clist"></div>
    <div class="sec">Texts</div><div id="fbooks"></div>
    <div style="margin-top:12px;display:flex;gap:6px">
      <button class="mini" id="reset">reset view</button>
      <button class="mini" id="exp">export marks</button>
    </div>
  </div>
  <div id="main">
    <canvas id="cv"></canvas>
    <div id="tip"></div>
    <div id="hint">scroll = zoom · drag = pan · click a concept · mark it alive/dead as you explore</div>
  </div>
</div>
<script>
const DATA=/*__DATA__*/;
const N=DATA.nodes, E=DATA.edges, S=DATA.sites, BC=DATA.book_color;
const idIdx={}; N.forEach((n,i)=>idIdx[n.id]=i);
const books=Object.keys(BC).sort();
const showBook={}; books.forEach(b=>showBook[b]=true);
const MARK_KEY='rhizome.concept.marks';
let marks=JSON.parse(localStorage.getItem(MARK_KEY)||'{}');
function saveMarks(){localStorage.setItem(MARK_KEY,JSON.stringify(marks));}

const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
let W,H,view={s:0.55,ox:0,oy:0}, sel=null, hover=null;
function resize(){ W=cv.width=cv.clientWidth*devicePixelRatio; H=cv.height=cv.clientHeight*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0); draw(); }
function fit(){ view={s:0.5, ox:cv.clientWidth/2-500*0.5, oy:cv.clientHeight/2-500*0.5}; }
const X=n=>n.x*view.s+view.ox, Y=n=>n.y*view.s+view.oy;
function vis(n){ return showBook[n.dom]!==false; }
function rad(n){ return Math.max(3, Math.sqrt(n.n)*1.7*Math.min(1.4,view.s)+1); }
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

function draw(){
  ctx.clearRect(0,0,cv.clientWidth,cv.clientHeight);
  if(sel){ E.forEach(e=>{ if(e.s!==sel && e.t!==sel) return;
      const a=N[idIdx[e.s]], b=N[idIdx[e.t]]; if(!a||!b||!vis(a)||!vis(b)) return;
      ctx.beginPath(); ctx.moveTo(X(a),Y(a)); ctx.lineTo(X(b),Y(b));
      ctx.strokeStyle='rgba(217,140,95,.45)'; ctx.lineWidth=Math.min(4,Math.sqrt(e.w)); ctx.stroke(); }); }
  for(const n of N){ if(!vis(n)) continue;
    const x=X(n),y=Y(n),r=rad(n);
    ctx.globalAlpha = sel&&sel!==n.id ? .45 : .92;
    ctx.fillStyle = marks[n.id]==='dead' ? '#3a3f4a' : (BC[n.dom]||'#888');
    ctx.beginPath(); ctx.arc(x,y,r,0,7); ctx.fill();
    if(marks[n.id]==='alive'){ ctx.globalAlpha=1; ctx.strokeStyle='#6fcf97'; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(x,y,r+2.5,0,7); ctx.stroke(); }
    if(view.s>0.7 || n.n>=18 || n.id===hover){ ctx.globalAlpha=1; ctx.fillStyle='#cdd6e4';
      ctx.font=(n.id===hover?'600 ':'')+(11)+'px ui-sans-serif'; ctx.fillText(n.label,x+r+3,y+3); }
  }
  ctx.globalAlpha=1;
  if(sel){ const s=N[idIdx[sel]]; if(s&&vis(s)){ ctx.strokeStyle='#fff';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.arc(X(s),Y(s),rad(s)+4,0,7);ctx.stroke(); } }
}
function nearest(mx,my){ let best=null,bd=18*18;
  for(const n of N){ if(!vis(n))continue; const dx=X(n)-mx,dy=Y(n)-my,d=dx*dx+dy*dy;
    if(d<bd){bd=d;best=n;} } return best; }

function bookBar(bks){ const tot=Object.values(bks).reduce((a,b)=>a+b,0)||1;
  return '<div class="bar">'+Object.entries(bks).sort((a,b)=>b[1]-a[1]).map(([b,c])=>
    `<span title="${esc(b)}: ${c}" style="width:${c/tot*100}%;background:${BC[b]||'#888'}"></span>`).join('')+'</div>'; }

function showConcept(id){ sel=id; const n=N[idIdx[id]], t=document.getElementById('tip');
  if(!n){t.style.display='none';draw();return;}
  const m=marks[id]||'';
  const sites=(S[id]||[]).map(s=>
    `<div class="site"><div class="s">${esc(s.b.replace(/-/g,' '))}`
    +(s.ch?`<span class="chartag">${esc(s.ch)}${s.cd?' · '+esc(s.cd):''}</span>`:'')+`</div>`
    +`<div class="tx">${esc(s.prev)}…</div>`
    +`<a href="/reader?id=${encodeURIComponent(s.id)}" target="_blank">open &amp; annotate ↗</a></div>`).join('');
  t.innerHTML=`<h2>${esc(n.label)}</h2>`
    +`<div class="meta">in <b>${n.n}</b> passages · ${Object.keys(n.books).length} text(s)</div>`
    +bookBar(n.books)
    +`<div class="marks"><button class="alive${m==='alive'?' on':''}" data-m="alive">alive ✦</button>`
    +`<button class="dead${m==='dead'?' on':''}" data-m="dead">dead ✕</button></div>`
    +`<div class="sec">Sites — what each does with it</div>${sites||'<div class="meta">no sites listed</div>'}`;
  t.querySelectorAll('.marks button').forEach(b=>b.onclick=()=>{
    const v=b.dataset.m; if(marks[id]===v) delete marks[id]; else marks[id]=v;
    saveMarks(); showConcept(id); renderList(); });
  t.style.display='block'; draw();
}

// interaction
let drag=null;
cv.onmousedown=e=>drag={x:e.clientX,y:e.clientY,ox:view.ox,oy:view.oy,moved:false};
cv.onmousemove=e=>{ const r=cv.getBoundingClientRect();
  if(drag){ const dx=e.clientX-drag.x,dy=e.clientY-drag.y; if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;
    view.ox=drag.ox+dx;view.oy=drag.oy+dy;draw(); return; }
  const n=nearest(e.clientX-r.left,e.clientY-r.top); const h=n?n.id:null;
  if(h!==hover){hover=h; cv.style.cursor=h?'pointer':'default'; draw();} };
window.onmouseup=e=>{ if(drag&&!drag.moved){ const r=cv.getBoundingClientRect();
  const n=nearest(e.clientX-r.left,e.clientY-r.top); if(n)showConcept(n.id); else {sel=null;document.getElementById('tip').style.display='none';draw();} } drag=null; };
cv.onwheel=e=>{ e.preventDefault(); const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=e.deltaY<0?1.1:1/1.1, ns=Math.max(.1,Math.min(8,view.s*f));
  view.ox=mx-(mx-view.ox)*(ns/view.s); view.oy=my-(my-view.oy)*(ns/view.s); view.s=ns; draw(); };
document.getElementById('reset').onclick=()=>{fit();draw();};
document.getElementById('exp').onclick=()=>{ const blob=new Blob([JSON.stringify(marks,null,2)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='concept-marks.json'; a.click(); };

// concept list (ranked, searchable, reflects marks)
function renderList(){ const q=(document.getElementById('q').value||'').toLowerCase();
  const items=N.filter(n=>!q||n.label.includes(q)).sort((a,b)=>b.n-a.n).slice(0,120);
  document.getElementById('clist').innerHTML=items.map(n=>
    `<div class="ci ${marks[n.id]||''}" data-id="${esc(n.id)}"><span>${esc(n.label)}</span><span class="n">${n.n}</span></div>`).join('');
  document.querySelectorAll('.ci').forEach(el=>el.onclick=()=>{ const n=N[idIdx[el.dataset.id]];
    view.s=1.2; view.ox=cv.clientWidth/2-n.x*view.s; view.oy=cv.clientHeight/2-n.y*view.s; showConcept(el.dataset.id); }); }
document.getElementById('q').oninput=renderList;

// book filter
document.getElementById('fbooks').innerHTML=books.map(b=>
  `<label class="f"><input type="checkbox" data-b="${esc(b)}" checked><span class="dot" style="background:${BC[b]}"></span>${esc(b.replace(/-/g,' ').slice(0,26))}</label>`).join('');
document.querySelectorAll('#fbooks input').forEach(cb=>cb.onchange=()=>{showBook[cb.dataset.b]=cb.checked;draw();});

const st=DATA.stats;
document.getElementById('stats').innerHTML=
  `<div class="statline"><b>${st.concepts}</b> concepts · <b>${st.chunks_tagged}</b> passages · mode <b>${st.mode}</b></div>`;

renderList(); addEventListener('resize',resize); fit(); resize();
</script></body></html>
"""


if __name__ == "__main__":
    build()
