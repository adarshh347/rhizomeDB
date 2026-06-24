"""RhizomeDB panel server — dynamic, dependency-free (Python stdlib only).

Run it and leave it on; it re-reads the pipeline every request, and the React
page polls a few times a minute, so the panel stays live as you annotate,
rebuild, or explore:

    python3 -m rhizome.server            # -> http://127.0.0.1:8765
    python3 -m rhizome.server --port 9000

Endpoints:
    GET  /                 the React panel (single page, CDN React, no build step)
    GET  /api/state        the live snapshot (status, deck, books, graph)
    POST /api/rebuild      re-parse notes + rebuild the graph
    POST /api/explore      run one exploration {theme|chunk|random, structural}
    GET  /ask              baseline-RAG question -> answer page
    POST /api/ask          plain RAG: top-k retrieve -> long grounded answer + sources + follow-ups

`/api/explore` degrades gracefully: random/chunk seeds work with no extra deps;
free-text/structural need fastembed (+ an LLM key for judging) — without them it
returns the geometry-only band or a clear message.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, state as state_mod, notes as notes_mod, graph as graph_mod

_ENGINE = None
_ENGINE_LOCK = threading.Lock()
VENDOR_DIR = config.ROOT / "frontend" / "vendor"   # local React/Babel/vis (no CDN)


def _engine():
    """Lazily construct the engine once (loads the index)."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from .engine import Engine
            _ENGINE = Engine()
        return _ENGINE


def run_explore(body: dict) -> dict:
    try:
        eng = _engine()
        step = eng.explore(
            theme=body.get("theme") or None,
            chunk_id=body.get("chunk") or None,
            random=bool(body.get("random")),
            structural=bool(body.get("structural")),
        )
        # trim payload for the wire
        def slim(c):
            return {"author": c.get("author"), "title": c.get("title"),
                    "book_id": c.get("book_id"), "similarity": c.get("similarity"),
                    "bridge_concept": c.get("bridge_concept"),
                    "articulation": c.get("articulation"),
                    "text": (c.get("text") or "")[:400]}
        from . import usage
        usage.record_report(step.get("usage"))   # accrue into today's free-tier ledger
        return {
            "mode": step["mode"], "seed_label": step["seed_label"],
            "abstraction": step.get("abstraction"),
            "candidates": [slim(c) for c in step["candidates"]],
            "confirmed": [slim(c) for c in step["confirmed"]],
            "exploration": step["exploration"],
            "usage": step.get("usage"),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}",
                "hint": "free-text/structural seeds need fastembed installed "
                        "(+ an LLM key for judging). Try a random seed to test geometry."}


def run_ask(body: dict) -> dict:
    """Baseline RAG: top-k retrieve -> long grounded answer + sources + follow-ups."""
    try:
        eng = _engine()
        if eng.client is None:
            return {"error": "No LLM key set.",
                    "hint": "set ANTHROPIC_API_KEY / GEMINI_API_KEY / GROQ_API_KEY to get answers."}
        from . import rag
        q = (body.get("question") or "").strip()
        if not q:
            return {"error": "empty question"}
        k = max(3, min(12, int(body.get("k") or 6)))
        res = rag.answer(q, eng.store, eng.client, k=k)
        fol = rag.followups(q, res["sources"], eng.client)

        def slim(c):
            return {"author": c.get("author"), "title": c.get("title"),
                    "book_id": c.get("book_id"), "page": c.get("page"),
                    "similarity": c.get("similarity"), "text": (c.get("text") or "")[:700]}
        return {"answer": res["answer"], "sources": [slim(c) for c in res["sources"]],
                "followups": fol,
                "basis": "top-k cosine similarity to the question embedding "
                         "(pure nearest-neighbour — no diversification, no exclusions)"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}",
                "hint": "normal RAG needs fastembed (to embed the question) + an LLM key (to answer)."}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, SPA, "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._send(200, json.dumps(state_mod.snapshot()))
        elif self.path == "/ask" or self.path.startswith("/ask?"):
            self._send(200, ASK_SPA, "text/html; charset=utf-8")
        elif self.path.startswith("/vendor/"):
            self._serve_vendor(self.path)
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def _serve_vendor(self, path):
        name = path.split("/")[-1].split("?")[0]   # basename only (no traversal)
        f = VENDOR_DIR / name
        if name.endswith(".js") and f.is_file():
            self._send(200, f.read_bytes(), "text/javascript; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "vendor not found"}))

    def do_POST(self):
        if self.path == "/api/rebuild":
            notes_mod.build_annotations()
            graph_mod.build_edges()
            self._send(200, json.dumps(state_mod.snapshot()))
        elif self.path == "/api/explore":
            self._send(200, json.dumps(run_explore(self._json_body())))
        elif self.path == "/api/ask":
            self._send(200, json.dumps(run_ask(self._json_body())))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *_):
        pass  # quiet


SPA = r"""<!doctype html><html><head><meta charset="utf-8"><title>RhizomeDB · Panel</title>
<script src="/vendor/react.production.min.js"></script>
<script src="/vendor/react-dom.production.min.js"></script>
<script src="/vendor/babel.min.js"></script>
<script src="/vendor/vis-network.min.js"></script>
<style>
:root{--bg:#F4F0E8;--ink:#2B2722;--panel:#FBF8F2;--line:#E5DCCB;--accent:#C4533A;--muted:#857A6B;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:-apple-system,BlinkMacSystemFont,Inter,"Segoe UI",sans-serif;line-height:1.5}
.wrap{max-width:1120px;margin:0 auto;padding:24px 22px 70px}
h1{font-family:Georgia,serif;font-size:25px;margin:0 0 2px}
.sub{color:var(--muted);font-size:12.5px;margin-bottom:18px}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#6B8F71;margin-right:6px;animation:p 2s infinite}
@keyframes p{50%{opacity:.3}}
.strip{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:22px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:9px 13px;min-width:84px}
.stat .n{font-size:21px;font-weight:600}.stat .l{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.cols{display:grid;grid-template-columns:1.1fr .9fr;gap:20px}@media(max-width:880px){.cols{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}
.cat{font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:7px}
.card h2{font-family:Georgia,serif;font-size:19px;margin:0 0 9px}.card .body{font-size:14px;color:#433d35;min-height:70px}
.meta{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted);background:#F1EADD;border-radius:7px;padding:6px 9px;margin-top:11px;word-break:break-word}
.nav{display:flex;align-items:center;gap:10px;margin-top:13px}
button{border:1px solid var(--line);background:#fff;border-radius:9px;padding:7px 15px;font-size:13px;cursor:pointer}
button:hover{border-color:var(--accent);color:var(--accent)}button:disabled{opacity:.5;cursor:default}
.count{font-size:12px;color:var(--muted)}
h3{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 9px}
.book{display:flex;gap:8px;align-items:center;font-size:13px;padding:4px 0;border-bottom:1px dashed var(--line)}
.pill{font-size:10px;border-radius:20px;padding:1px 8px}.read{background:#DCE8DC;color:#3f6b46}.unread{background:#F0E2D8;color:#9a5a3c}
#net{height:260px;background:var(--panel);border:1px solid var(--line);border-radius:13px}
textarea{width:100%;border:1px solid var(--line);border-radius:9px;padding:8px;font:inherit;font-size:13px;resize:vertical}
.res{font-size:13px;margin-top:10px}.res .c{border-left:2px solid var(--line);padding:4px 0 4px 10px;margin:7px 0}
.expl{background:#F1EADD;border-radius:10px;padding:12px;font-size:13.5px;line-height:1.6;white-space:pre-wrap;margin-top:10px}
.usage{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--muted);margin-top:10px}
.usage b{color:var(--ink)}.upart{display:inline-block;background:#EBE4D6;border-radius:12px;padding:1px 8px;margin:4px 6px 0 0}
.sec{margin-top:20px}
</style></head><body><div id="root"></div>
<script type="text/babel" data-presets="react">
const {useState,useEffect,useRef} = React;
const CC={decide:"#7a5ca8",read:"#C4533A",explore:"#4F6D8C",do:"#6B8F71",chase:"#B07D48"};
const api=(p,o)=>fetch(p,o).then(r=>r.json());

function Strip({s}){const cells=[["books",s.books],["chunks",s.chunks],["notes",s.notes],
  ["annotations",s.annotations],["edges",s.edges],["llm key",s.llm_key?"on":"off"]];
  return <div className="strip">{cells.map(([l,n])=>
    <div className="stat" key={l}><div className="n">{n}</div><div className="l">{l}</div></div>)}</div>;}

function Deck({deck}){const [i,setI]=useState(0); if(!deck.length)return null;
  const c=deck[Math.min(i,deck.length-1)];
  return <div className="card"><div className="cat" style={{color:CC[c.cat]}}>{c.cat}</div>
    <h2>{c.title}</h2><div className="body">{c.body}</div>{c.meta&&<div className="meta">{c.meta}</div>}
    <div className="nav"><button onClick={()=>setI((i-1+deck.length)%deck.length)}>‹ Prev</button>
    <button onClick={()=>setI((i+1)%deck.length)}>Next ›</button>
    <span className="count">step {Math.min(i,deck.length-1)+1} of {deck.length}</span></div></div>;}

function Books({books}){return <div className="sec"><h3>Reading coverage</h3>
  {books.map(b=><div className="book" key={b.id}>
    <span className={"pill "+(b.read?"read":"unread")}>{b.read?"reading":"to read"}</span>
    <span>{b.title}</span></div>)}</div>;}

function Graph({nodes,edges}){const ref=useRef();
  useEffect(()=>{if(!ref.current)return;
    new vis.Network(ref.current,{nodes:new vis.DataSet(nodes.map(n=>({id:n.id,label:n.label,
      shape:"dot",size:11,font:{size:11},color:{background:"#C4533A",border:"#fff"}}))),
      edges:new vis.DataSet(edges.map(e=>({from:e.from,to:e.to,label:e.rel,arrows:"to",
        font:{size:9,color:"#857A6B"},dashes:e.origin==="note",
        color:{color:e.origin==="judged"?"#4F6D8C":e.origin==="authored"?"#C4533A":"#cdbfa6"}})))},
      {physics:{stabilization:{iterations:120}},nodes:{borderWidth:2}});},[nodes,edges]);
  return <div className="sec"><h3>Concept graph (live)</h3><div id="net" ref={ref}></div></div>;}

function Explore({onChange}){const [t,setT]=useState(""),[st,setSt]=useState(false),
  [run,setRun]=useState(false),[res,setRes]=useState(null);
  const go=async(rand)=>{setRun(true);setRes(null);
    const r=await api("/api/explore",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(rand?{random:true}:{theme:t,structural:st})});
    setRes(r);setRun(false);onChange&&onChange();};
  return <div className="card sec"><h3>Work & test — run an evocation</h3>
    <textarea rows={2} placeholder="a theme or a line of thought to seed from…" value={t}
      onChange={e=>setT(e.target.value)}/>
    <div className="nav"><button disabled={run||!t} onClick={()=>go(false)}>Evoke</button>
      <button disabled={run} onClick={()=>go(true)}>Surprise me</button>
      <label style={{fontSize:12}}><input type="checkbox" checked={st}
        onChange={e=>setSt(e.target.checked)}/> structural</label>
      {run&&<span className="count">running…</span>}</div>
    {res&&res.error&&<div className="meta">{res.error}<br/>{res.hint}</div>}
    {res&&!res.error&&<div className="res">
      {res.abstraction&&<div className="meta">structural seed → {res.abstraction}</div>}
      {(res.confirmed.length?res.confirmed:res.candidates).map((c,k)=>
        <div className="c" key={k}><b>{c.author}</b> — {c.title}{c.bridge_concept?` · ${c.bridge_concept}`:""}
        <br/><span style={{color:"#5a5249"}}>{c.articulation||c.text}</span></div>)}
      {res.exploration&&<div className="expl">{res.exploration}</div>}
      {res.usage&&res.usage.total_tokens>0&&<div className="usage">
        <b>tokens</b> {res.usage.total_tokens.toLocaleString()}
        {res.usage.is_gemini?` · ${res.usage.pct_day.toFixed(2)}% of the free-tier day · ${res.usage.requests} req`:` · ${res.usage.requests} req`}
        {res.usage.parts.map((p,k)=><span key={k} className="upart">{p.label} {p.tokens.toLocaleString()}{res.usage.is_gemini?` (${p.pct_day.toFixed(2)}%)`:""}</span>)}
      </div>}</div>}</div>;}

function App(){const [d,setD]=useState(null);
  const load=()=>api("/api/state").then(setD);
  useEffect(()=>{load();const id=setInterval(load,8000);return()=>clearInterval(id);},[]);
  if(!d)return <div className="wrap">loading…</div>;
  return <div className="wrap"><h1>RhizomeDB · Panel</h1>
    <div className="sub"><span className="live"></span>live · refreshed {d.when} · one step at a time
      &nbsp;·&nbsp;<a href="/ask" style={{color:"#C4533A"}}>ask (baseline RAG) →</a></div>
    <Strip s={d.status}/>
    <div className="cols"><div><Deck deck={d.deck}/><Books books={d.books}/></div>
      <div><Graph nodes={d.gnodes} edges={d.gedges}/><Explore onChange={load}/></div></div></div>;}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
</script></body></html>"""


ASK_SPA = r"""<!doctype html><html><head><meta charset="utf-8"><title>RhizomeDB · Ask</title>
<script src="/vendor/react.production.min.js"></script>
<script src="/vendor/react-dom.production.min.js"></script>
<script src="/vendor/babel.min.js"></script>
<style>
:root{--bg:#F4F0E8;--ink:#2B2722;--panel:#FBF8F2;--line:#E5DCCB;--accent:#C4533A;--muted:#857A6B;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:-apple-system,BlinkMacSystemFont,Inter,"Segoe UI",sans-serif;line-height:1.55}
.wrap{max-width:820px;margin:0 auto;padding:26px 22px 70px}
h1{font-family:Georgia,serif;font-size:25px;margin:0 0 2px}
.tag{font-size:11px;background:#EBE4D6;color:#6c6358;border-radius:20px;padding:2px 9px;vertical-align:middle}
.sub{color:var(--muted);font-size:12.5px;margin-bottom:16px}a{color:var(--accent)}
textarea{width:100%;border:1px solid var(--line);border-radius:10px;padding:10px;font:inherit;font-size:14px;resize:vertical}
.nav{display:flex;align-items:center;gap:12px;margin-top:10px}
button{border:1px solid var(--line);background:#fff;border-radius:9px;padding:8px 18px;font-size:13px;cursor:pointer}
button:hover{border-color:var(--accent);color:var(--accent)}button:disabled{opacity:.5}
label{font-size:12px;color:var(--muted)}input[type=number]{border:1px solid var(--line);border-radius:6px;padding:3px 5px}
.count{font-size:12px;color:var(--muted)}
.answer{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:18px;font-size:15px;line-height:1.7;white-space:pre-wrap}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:24px 0 9px}
.basis{text-transform:none;letter-spacing:0;font-weight:400;font-family:ui-monospace,monospace;font-size:11px}
.chip{display:inline-block;background:#fff;border:1px solid var(--line);border-radius:20px;padding:6px 12px;margin:0 7px 8px 0;font-size:13px;cursor:pointer}
.chip:hover{border-color:var(--accent);color:var(--accent)}
.src{border:1px solid var(--line);background:var(--panel);border-radius:11px;padding:12px 14px;margin-bottom:10px}
.srch{font-size:13px;margin-bottom:6px}.sim{float:right;font-family:ui-monospace,monospace;font-size:12px;color:var(--accent)}
.bar{height:5px;background:#EBE4D6;border-radius:4px;overflow:hidden;margin-bottom:8px}
.bar>div{height:100%;background:var(--accent)}
.txt{font-size:13px;color:#4a443c;max-height:150px;overflow:auto}
.meta{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted);background:#F1EADD;border-radius:8px;padding:10px;margin-top:14px}
</style></head><body><div id="root"></div>
<script type="text/babel" data-presets="react">
const {useState}=React;
const api=(p,o)=>fetch(p,o).then(r=>r.json());
function App(){
  const [q,setQ]=useState("what is dwelling"),[k,setK]=useState(6),
        [run,setRun]=useState(false),[r,setR]=useState(null);
  const ask=async(question)=>{const qq=(question||q).trim(); if(!qq)return; setQ(qq);
    setRun(true);setR(null);
    const res=await api("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question:qq,k})}); setR(res); setRun(false);
    window.scrollTo({top:0});};
  return <div className="wrap">
    <h1>RhizomeDB · Ask <span className="tag">baseline RAG</span></h1>
    <div className="sub">Plain top-k retrieval — deliberately the <i>opposite</i> of constellatory.
      The answer is grounded only in the nearest passages, shown below with their cosine scores.
      &nbsp;<a href="/">→ panel</a></div>
    <textarea rows={2} value={q} onChange={e=>setQ(e.target.value)} placeholder="ask the corpus…"/>
    <div className="nav"><button disabled={run||!q} onClick={()=>ask()}>Ask</button>
      <label>passages <input type="number" min="3" max="12" value={k}
        onChange={e=>setK(+e.target.value)} style={{width:50}}/></label>
      {run&&<span className="count">retrieving + answering…</span>}</div>
    {r&&r.error&&<div className="meta">{r.error}<br/>{r.hint}</div>}
    {r&&!r.error&&<div>
      <div className="answer">{r.answer}</div>
      {r.followups&&r.followups.length>0&&<div><h3>Follow-up questions</h3>
        {r.followups.map((f,i)=><span className="chip" key={i} onClick={()=>ask(f)}>{f}</span>)}</div>}
      <h3>Source paragraphs · <span className="basis">{r.basis}</span></h3>
      {r.sources.map((s,i)=><div className="src" key={i}>
        <div className="srch"><b>[{i+1}]</b> {s.author} — {s.title}{s.page?(", p."+s.page):""}
          <span className="sim">cos {s.similarity}</span></div>
        <div className="bar"><div style={{width:(Math.max(0,Math.min(1,s.similarity))*100)+"%"}}></div></div>
        <div className="txt">{s.text}</div></div>)}
    </div>}
  </div>;}
ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
</script></body></html>"""


def serve(port=8765):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"RhizomeDB panel  →  http://127.0.0.1:{port}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    serve(ap.parse_args().port)
