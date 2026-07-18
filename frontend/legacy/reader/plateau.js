/* RhizomeDB — the Plateau.
 *
 * A deep-study page for a single passage. From one chunk it shows: the passage
 * (with surrounding context), a CONSTELLATION (its core concepts as a draggable
 * force-graph of nodes + named edges), AI brainstorming angles, suggestive
 * follow-ups, a notes column, and a grounded discussion. Study data comes from
 * /api/plateau (one cached LLM call, heuristic fallback). Notes and chat reuse
 * the same /api endpoints as the reader, keyed to this passage.
 */
const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const params = new URLSearchParams(location.search);
const CHUNK_ID = params.get('chunk') || '';
const CHAT_TARGET = 'plateau:' + CHUNK_ID;

let DATA = null, annotations = [];

function toast(t){ const e=$('#toast'); e.textContent=t; e.style.display='block';
  clearTimeout(toast._t); toast._t=setTimeout(()=>e.style.display='none', 1700); }

// ---------------------------------------------------------------- theme
function applyTheme(t){ document.body.classList.toggle('dark', t==='dark');
  $('#themeBtn').textContent = t==='dark' ? '☀' : '☾'; if(C.ready) C.recolor(); }
$('#themeBtn').onclick = () => { const n = document.body.classList.contains('dark') ? 'light' : 'dark';
  localStorage.setItem('rhz_theme', n); applyTheme(n); };

// reading text size — shared --read-scale, persisted across reader pages
function applyScale(s){ s = Math.max(.8, Math.min(1.7, Math.round(s*100)/100));
  document.body.style.setProperty('--read-scale', s); localStorage.setItem('rhz_scale', s); }
$('#fontDown').onclick = () => applyScale((+localStorage.getItem('rhz_scale')||1) - .08);
$('#fontUp').onclick   = () => applyScale((+localStorage.getItem('rhz_scale')||1) + .08);

// ---------------------------------------------------------------- boot
async function boot(){
  applyTheme(localStorage.getItem('rhz_theme') || 'light');
  applyScale(+localStorage.getItem('rhz_scale') || 1);
  if(!CHUNK_ID){ $('#passageText').textContent = 'No passage chosen.'; return; }
  await load();
  await loadAnnotations();
  await loadChat();
}
async function load(refresh){
  let d;
  try{ d = await (await fetch('/api/plateau?chunk='+encodeURIComponent(CHUNK_ID)+(refresh?'&refresh=1':''))).json(); }
  catch(e){ $('#passageText').textContent = 'Could not reach the server.'; return; }
  if(d.error){ $('#passageText').textContent = d.error; return; }
  DATA = d;
  const c = d.chunk;
  document.title = 'Plateau · ' + (c.title || c.book_id);
  $('#byline').textContent = `${c.author||''}${c.page?(' · p.'+c.page):''}`;
  $('#bookLink').href = `/book?id=${encodeURIComponent(c.book_id)}#p-${encodeURIComponent(c.id)}`;
  $('#bookLink').textContent = c.title || 'Book';
  $('#passageSrc').textContent = `${c.author||'Unknown'}, ${c.title||c.book_id}`
    + (c.heading?` · ${c.heading}`:'') + ` · ${c.id}`
    + (c.character?` · ${c.character}`:'');
  $('#passageText').textContent = c.text;
  renderContext(d.context);
  const srcLabel = {llm:'AI study map', cache:'AI study map', heuristic:'keyword map',
    'heuristic-quota':'keyword map (AI quota reached)'}[d.source] || d.source;
  $('#srcTag').textContent = srcLabel;
  C.init(d.graph.concepts, d.graph.edges);
  renderAngles(d.angles);
  renderFollowups(d.follow_ups);
}
$('#rebuildBtn').onclick = async () => {
  $('#rebuildBtn').disabled = true; $('#rebuildBtn').textContent = '↻ Rebuilding…';
  await load(true);
  $('#rebuildBtn').disabled = false; $('#rebuildBtn').textContent = '↻ Rebuild';
  toast('Study map rebuilt');
};

// ---------------------------------------------------------------- passage context
function renderContext(ctx){
  const parts = [];
  if(ctx.prev) parts.push(`<span class="clab">Before</span>${esc(ctx.prev.text)}`);
  if(ctx.next) parts.push(`<span class="clab">After</span>${esc(ctx.next.text)}`);
  $('#ctxBox').innerHTML = parts.join('') || '<span class="ci-empty">No adjacent passages.</span>';
}
$('#ctxToggle').onclick = () => {
  const open = $('#ctxBox').classList.toggle('open');
  $('#ctxToggle').textContent = open ? 'Hide context ↑' : 'Show surrounding context ↓';
};

// ---------------------------------------------------------------- angles + follow-ups
function renderAngles(angles){
  const box = $('#angles');
  if(!angles || !angles.length){ $('#anglePanel').style.display='none'; return; }
  $('#anglePanel').style.display='';
  box.innerHTML = angles.map(a =>
    `<div class="angle"><div class="at">${esc(a.title)}</div><div class="ax">${esc(a.thought)}</div></div>`).join('');
}
function renderFollowups(fups){
  const box = $('#fups');
  if(!fups || !fups.length){ $('#fupPanel').style.display='none'; return; }
  $('#fupPanel').style.display='';
  box.innerHTML = fups.map((q,i) =>
    `<button class="fup" data-q="${esc(q)}"><span class="fnum">${i+1}</span><span>${esc(q)}</span><span class="fgo">↳</span></button>`).join('');
  box.querySelectorAll('.fup').forEach(b => b.onclick = () => { switchTab('chat'); sendChat(b.dataset.q); });
}

// ---------------------------------------------------------------- CONSTELLATION (force graph)
const C = (() => {
  const canvas = $('#constCanvas'), ctx = canvas.getContext('2d');
  let nodes = [], edges = [], W = 0, H = 0, sel = null, hover = null, drag = null;
  let moved = false, raf = null, col = {}, ready = false;
  let loom = false, weaves = [], pair = [], onPair = null;   // Loom: identities + woven threads
  const nodeByLabel = lbl => nodes.find(n => n.label === lbl);

  function recolor(){
    const s = getComputedStyle(document.body);
    const g = k => s.getPropertyValue(k).trim();
    col = {accent:g('--accent'), ink:g('--ink'), ink2:g('--ink2'), line:g('--line2'),
           panel:g('--panel'), dim:g('--dim'), bg:g('--bg2'), accInk:g('--bg')};
    if(ready) draw();
  }
  function resize(){
    const dpr = window.devicePixelRatio || 1;
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W*dpr; canvas.height = H*dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function init(concepts, e){
    recolor(); resize();
    const n = concepts.length;
    const R = Math.min(W,H) * 0.30;
    nodes = concepts.map((c,i) => {
      ctx.font = '600 14px Georgia, serif';
      const tw = ctx.measureText(c.label).width;
      return {label:c.label, gloss:c.gloss, handle:String.fromCharCode(65 + (i % 26)),
              hw:tw/2+15, hh:15,
              x: W/2 + Math.cos(i/n*2*Math.PI)*R + (i%2?6:-6),
              y: H/2 + Math.sin(i/n*2*Math.PI)*R + (i%3?4:-4), vx:0, vy:0, deg:1};
    });
    edges = (e||[]).map(x => ({a:x.a, b:x.b, relation:x.relation||''}));
    edges.forEach(x => { if(nodes[x.a]) nodes[x.a].deg++; if(nodes[x.b]) nodes[x.b].deg++; });
    sel = hover = drag = null; pair = []; showInfo(null); ready = true; run();
  }
  function step(){
    const REP = 2400, SPRING = 0.02, GRAV = 0.018, DAMP = 0.85, L = Math.min(W,H)*0.32;
    for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++){
      const a=nodes[i], b=nodes[j]; let dx=a.x-b.x, dy=a.y-b.y; let d2=dx*dx+dy*dy||1;
      const d=Math.sqrt(d2), f=REP/d2; const ux=dx/d, uy=dy/d;
      a.vx+=ux*f; a.vy+=uy*f; b.vx-=ux*f; b.vy-=uy*f;
    }
    for(const e of edges){ const a=nodes[e.a], b=nodes[e.b]; if(!a||!b) continue;
      let dx=b.x-a.x, dy=b.y-a.y; const d=Math.sqrt(dx*dx+dy*dy)||1; const f=(d-L)*SPRING;
      const ux=dx/d, uy=dy/d; a.vx+=ux*f; a.vy+=uy*f; b.vx-=ux*f; b.vy-=uy*f;
    }
    let energy=0;
    for(const nd of nodes){
      if(nd===drag) continue;
      nd.vx += (W/2-nd.x)*GRAV; nd.vy += (H/2-nd.y)*GRAV;
      nd.vx*=DAMP; nd.vy*=DAMP; nd.x+=nd.vx; nd.y+=nd.vy;
      nd.x = Math.max(nd.hw+6, Math.min(W-nd.hw-6, nd.x));
      nd.y = Math.max(nd.hh+6, Math.min(H-nd.hh-6, nd.y));
      energy += nd.vx*nd.vx + nd.vy*nd.vy;
    }
    return energy;
  }
  function run(){ cancelAnimationFrame(raf); const loop=()=>{ const e=step(); draw();
    if(e>0.05 || drag) raf=requestAnimationFrame(loop); }; raf=requestAnimationFrame(loop); }
  function pill(n, fill, stroke, textCol){
    const x=n.x-n.hw, y=n.y-n.hh, w=n.hw*2, h=n.hh*2, r=h/2;
    ctx.beginPath();
    ctx.moveTo(x+r,y); ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
    ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath();
    ctx.fillStyle=fill; ctx.fill(); ctx.lineWidth=1.5; ctx.strokeStyle=stroke; ctx.stroke();
    ctx.fillStyle=textCol; ctx.font='600 14px Georgia, serif';
    ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(n.label, n.x, n.y+0.5);
  }
  function draw(){
    ctx.clearRect(0,0,W,H);
    for(const e of edges){ const a=nodes[e.a], b=nodes[e.b]; if(!a||!b) continue;
      const on = sel && (a===sel || b===sel);
      ctx.strokeStyle = on ? col.accent : col.line; ctx.lineWidth = on ? 2 : 1;
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
      if(on && e.relation){ ctx.fillStyle=col.dim; ctx.font='11px ui-sans-serif,sans-serif';
        ctx.textAlign='center'; ctx.textBaseline='middle';
        ctx.fillText(e.relation, (a.x+b.x)/2, (a.y+b.y)/2 - 7); }
    }
    // woven threads (Loom): dashed, in the secondary accent, labelled
    if(loom){
      ctx.strokeStyle = col.accent2; ctx.fillStyle = col.accent2;
      ctx.lineWidth = 2; ctx.setLineDash([5,4]);
      for(const w of weaves){ const a=nodeByLabel(w.a), b=nodeByLabel(w.b); if(!a||!b) continue;
        ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
        if(w.note){ ctx.font='11px ui-sans-serif,sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
          ctx.fillText(w.note.slice(0,28), (a.x+b.x)/2, (a.y+b.y)/2 - 7); } }
      ctx.setLineDash([]);
    }
    for(const n of nodes){
      const picked = pair.includes(n);
      if(n===sel || picked) pill(n, col.accent, picked?col.accent2:col.accent, col.accInk);
      else if(n===hover) pill(n, col.panel, col.accent, col.ink);
      else pill(n, col.panel, col.line, col.ink2);
      if(loom){   // identity badge so every component can be named in speech/text
        ctx.fillStyle = col.accent2; ctx.beginPath();
        ctx.arc(n.x - n.hw, n.y - n.hh, 9, 0, 2*Math.PI); ctx.fill();
        ctx.fillStyle = col.accInk; ctx.font = '700 10px ui-sans-serif,sans-serif';
        ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(n.handle, n.x - n.hw, n.y - n.hh + 0.5);
      }
    }
  }
  function at(px,py){ for(let i=nodes.length-1;i>=0;i--){ const n=nodes[i];
    if(Math.abs(px-n.x)<=n.hw && Math.abs(py-n.y)<=n.hh) return n; } return null; }
  function pos(ev){ const r=canvas.getBoundingClientRect(); return {x:ev.clientX-r.left, y:ev.clientY-r.top}; }
  function showInfo(n){
    const box = $('#constInfo');
    if(!n){ box.innerHTML='<span class="ci-empty">Click a concept to see how this passage uses it.</span>'; return; }
    box.innerHTML = `<div class="ci-label">${esc(n.label)}</div>`
      + (n.gloss?`<div class="ci-gloss">${esc(n.gloss)}</div>`:'')
      + `<div class="ci-act"><button class="btn ghost" id="discConcept">Discuss this concept ↳</button></div>`;
    $('#discConcept').onclick = () => { switchTab('chat');
      sendChat(`How does this passage use the concept of “${n.label}”?` + (n.gloss?` (${n.gloss})`:'')); };
  }
  canvas.addEventListener('mousedown', ev => { const p=pos(ev); const n=at(p.x,p.y);
    if(n){ drag=n; moved=false; n.vx=n.vy=0; } });
  canvas.addEventListener('mousemove', ev => { const p=pos(ev);
    if(drag){ drag.x=p.x; drag.y=p.y; drag.vx=drag.vy=0; moved=true; run(); }
    else { const h=at(p.x,p.y); if(h!==hover){ hover=h; canvas.style.cursor=h?'pointer':'grab'; draw(); } } });
  window.addEventListener('mouseup', ev => { if(!drag) return;
    if(!moved){
      sel = (sel===drag?null:drag); showInfo(sel);
      if(loom){   // clicking concepts in Loom builds the pair to relate
        const i = pair.indexOf(drag);
        if(i >= 0) pair.splice(i, 1);
        else { pair.push(drag); if(pair.length > 2) pair.shift(); }
        if(pair.length === 2 && onPair) onPair(pair[0].label, pair[1].label);
      }
    }
    drag=null; draw();
  });
  window.addEventListener('resize', () => { if(ready){ resize(); run(); } });

  return {init, recolor, get ready(){return ready;},
    setLoom(on){ loom = on; pair = []; if(ready) draw(); },
    setWeaves(list){ weaves = list || []; if(ready) draw(); },
    setOnPair(fn){ onPair = fn; },
    clearPair(){ pair = []; if(ready) draw(); },
    labels(){ return nodes.map(n => ({label:n.label, handle:n.handle, gloss:n.gloss})); }};
})();

// ---------------------------------------------------------------- tabs
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.pane===name));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id==='pane-'+name));
  if(name==='chat') setTimeout(()=>$('#chatin').focus(), 30);
}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.pane));

// ---------------------------------------------------------------- notes
async function loadAnnotations(){
  try{ annotations = (await (await fetch('/api/annotations?target='+encodeURIComponent(CHUNK_ID))).json()).items || []; }
  catch(e){ annotations = []; }
  renderAnnList();
  renderLoomThreads();
}
// Reading notes and companion notes sit parallel for THIS passage, split into
// two labelled sub-groups and distinguished by source (R4).
function annCard(a){
  const companion = (a.source||'reader') === 'ai';
  return `<div class="ann ${a.kind==='note'?'note-only':''} ${companion?'companion':''}" id="ann-${a.id}">
      ${a.quote?`<div class="q">${esc(a.quote)}</div>`:''}
      ${a.note?`<div class="n">${esc(a.note)}</div>`:''}
      <div class="meta"><span>${companion?'<span class="src-badge">companion</span>':(a.kind==='highlight'?'highlight':'note')+' · '+esc(a.created||'')}</span>
        <span class="del" data-id="${a.id}">delete</span></div>
    </div>`;
}
function renderAnnList(){
  const box = $('#annlist');
  const reader = annotations.filter(a => !['ai','loom'].includes(a.source||'reader'));
  const companion = annotations.filter(a => (a.source||'reader') === 'ai');
  if(!reader.length && !companion.length){ box.innerHTML='<div class="empty">No notes yet.</div>'; return; }
  let html = '';
  if(reader.length){ html += `<div class="subhead reader"><span class="dot"></span>Your notes</div>`
    + reader.map(annCard).join(''); }
  if(companion.length){ html += `<div class="subhead"><span class="dot"></span>From the companion</div>`
    + companion.map(annCard).join(''); }
  box.innerHTML = html;
  box.querySelectorAll('.del').forEach(d => d.onclick = () => delAnnotation(d.dataset.id));
}
async function saveNote(text){
  await fetch('/api/annotations', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({target:CHUNK_ID, kind:'note', note:text, source:'plateau'})});
  toast('Note saved'); await loadAnnotations();
}
async function delAnnotation(id){
  await fetch('/api/annotations/delete', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})});
  await loadAnnotations();
}
$('#noteSave').onclick = () => { const t=$('#noteIn').value.trim(); if(!t) return; $('#noteIn').value=''; saveNote(t); };
$('#noteIn').addEventListener('keydown', e => { if(e.key==='Enter' && (e.metaKey||e.ctrlKey)) $('#noteSave').click(); });

// ---------------------------------------------------------------- annotate AI answers
const MODAL = {back:$('#modalBack'), title:$('#modalTitle'), quote:$('#modalQuote'),
               text:$('#modalText'), save:$('#modalSave'), onSave:null};
function openComposer({title, quote='', saveLabel='Save', onSave}){
  MODAL.title.textContent = title;
  if(quote){ MODAL.quote.textContent = '“'+quote+'”'; MODAL.quote.style.display='block'; }
  else MODAL.quote.style.display='none';
  MODAL.text.value=''; MODAL.save.textContent=saveLabel; MODAL.onSave=onSave;
  MODAL.back.classList.add('open'); setTimeout(()=>MODAL.text.focus(), 40);
}
function closeComposer(){ MODAL.back.classList.remove('open'); MODAL.onSave=null; }
function submitComposer(){ const t=MODAL.text.value.trim(); const cb=MODAL.onSave; closeComposer(); if(t&&cb) cb(t); }
$('#modalSave').onclick = submitComposer;
$('#modalCancel').onclick = closeComposer;
$('#modalClose').onclick = closeComposer;
MODAL.back.addEventListener('mousedown', e => { if(e.target===MODAL.back) closeComposer(); });
MODAL.text.addEventListener('keydown', e => {
  if(e.key==='Escape'){ e.preventDefault(); closeComposer(); }
  if(e.key==='Enter' && (e.metaKey||e.ctrlKey)){ e.preventDefault(); submitComposer(); } });

let pending = null;
$('#msgs').addEventListener('mouseup', () => {
  const sel = window.getSelection(); const txt = (sel?sel.toString():'').trim();
  if(txt.length < 3) return;
  let node = sel.anchorNode;
  while(node && !(node.classList && node.classList.contains('msg'))) node = node.parentElement;
  if(!node || !node.classList.contains('assistant')) return;
  pending = {quote: txt, msg_id: node.dataset.msgId || ''};
  const rect = sel.getRangeAt(0).getBoundingClientRect(); const tool = $('#seltool');
  tool.style.display='flex';
  tool.style.top = (window.scrollY+rect.top-tool.offsetHeight-8)+'px';
  tool.style.left = (window.scrollX+rect.left)+'px';
});
document.addEventListener('mousedown', e => { if(!$('#seltool').contains(e.target)) $('#seltool').style.display='none'; });
async function saveCompanion(quote, note){
  $('#seltool').style.display='none';
  await fetch('/api/annotations', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({target:CHUNK_ID, kind:'highlight', quote, note, source:'ai',
      passage_id:CHUNK_ID, msg_id:(pending&&pending.msg_id)||'', chat_target:CHAT_TARGET})});
  toast('Saved to companion notes'); window.getSelection().removeAllRanges();
  await loadAnnotations(); switchTab('notes');
}
$('#hl').onclick = () => pending && saveCompanion(pending.quote, '');
$('#hlc').onclick = () => { if(!pending) return; const {quote} = pending; $('#seltool').style.display='none';
  openComposer({title:'Note on the companion', quote, saveLabel:'Save note',
    onSave: note => saveCompanion(quote, note)}); };

// ---------------------------------------------------------------- discuss
function renderMsg(m){
  const prov = (m.role==='assistant' && m.msg_id) ? ` data-msg-id="${esc(m.msg_id)}" data-target="${esc(CHAT_TARGET)}"` : '';
  return `<div class="msg ${m.role}"${prov}><div class="who">${m.role==='user'?'You':'Companion'}</div>${esc(m.content)}</div>`;
}
async function loadChat(){
  try{ const msgs = (await (await fetch('/api/chat?target='+encodeURIComponent(CHAT_TARGET))).json()).messages || [];
    const box=$('#msgs'); if(msgs.length) box.innerHTML=msgs.map(renderMsg).join(''); box.scrollTop=box.scrollHeight; }
  catch(e){}
}
async function sendChat(text){
  const inp = $('#chatin'); const msg = (text != null ? text : inp.value).trim(); if(!msg || !DATA) return;
  if(text == null) inp.value = '';
  $('#send').disabled=true; $('#chathint').textContent='thinking…';
  const box=$('#msgs'); if(box.querySelector('.empty')) box.innerHTML='';
  box.innerHTML += renderMsg({role:'user', content:msg}); box.scrollTop=box.scrollHeight;
  const label = `${DATA.chunk.author||''}, ${DATA.chunk.title||DATA.chunk.book_id}${DATA.chunk.page?(', p.'+DATA.chunk.page):''}`;
  try{
    const d = await (await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({target:CHAT_TARGET, message:msg, context:DATA.chunk.text, source_label:label})})).json();
    if(d.error){ $('#chathint').textContent = d.error; }
    else { box.innerHTML += renderMsg({role:'assistant', content:d.reply, msg_id:d.msg_id});
      $('#chathint').textContent = d.usage ? `${d.usage.provider||''} · ${d.usage.total||0} tokens` : ''; }
    box.scrollTop=box.scrollHeight;
  }catch(e){ $('#chathint').textContent='request failed'; }
  $('#send').disabled=false;
}
$('#send').onclick = () => sendChat();
$('#chatin').addEventListener('keydown', e => { if(e.key==='Enter' && (e.metaKey||e.ctrlKey)) sendChat(); });

// ---------------------------------------------------------------- LOOM (advanced mode)
// Each concept becomes a named component (handle A,B,C…). You pick two on the map
// (or reference them by name), then speak or type the thread that binds them —
// "A grounds C", "these are the same move", "regroup under B". Threads are drawn
// on the constellation and saved with the passage (source:'loom'), parallel to
// reader/companion notes so a later graph pass can treat them as woven-by-hand.
let LOOM_ON = false, loomPair = null;
const LOOM_CHAT = 'loom:' + CHUNK_ID;
const PAIR_SEP = ' ⇄ ';

$('#loomBtn').onclick = () => {
  LOOM_ON = !LOOM_ON;
  $('#loomBtn').classList.toggle('active', LOOM_ON);
  $('#loomPanel').style.display = LOOM_ON ? '' : 'none';
  $('#constSub').textContent = LOOM_ON
    ? 'Loom is on — every concept is lettered. Click two to relate them, then speak or type the thread.'
    : "The passage's core concepts as a living map — drag a node, click one to read its role and take it into the discussion.";
  C.setLoom(LOOM_ON);
  if(LOOM_ON){ renderLoomChips(); renderLoomThreads(); $('#loomPanel').scrollIntoView({behavior:'smooth', block:'nearest'}); }
};

C.setOnPair((a, b) => {   // two concepts picked on the map → stage a thread
  loomPair = {a, b};
  const el = $('#loomPair');
  el.style.display = 'flex';
  el.innerHTML = `<span><b>${esc(a)}</b>${PAIR_SEP}<b>${esc(b)}</b></span><span class="clr" id="loomClr">clear ✕</span>`;
  $('#loomClr').onclick = clearPair;
  $('#loomIn').focus();
});
function clearPair(){ loomPair = null; $('#loomPair').style.display = 'none'; C.clearPair(); }

function renderLoomChips(){
  const box = $('#loomChips');
  box.innerHTML = C.labels().map(c =>
    `<span class="loom-chip" data-label="${esc(c.label)}"><span class="h">${esc(c.handle)}</span>${esc(c.label)}</span>`).join('');
  box.querySelectorAll('.loom-chip').forEach(ch => ch.onclick = () => {
    const t = $('#loomIn'); t.value = (t.value ? t.value.replace(/\s+$/,'') + ' ' : '') + ch.dataset.label + ' ';
    t.focus();
  });
}

const loomNotes = () => annotations.filter(a => (a.source||'') === 'loom');
function parseWeave(a){   // relations store "LabelA ⇄ LabelB" in quote; free notes have no quote
  if(a.quote && a.quote.includes(PAIR_SEP)){ const [x,y] = a.quote.split(PAIR_SEP);
    return {a:x.trim(), b:y.trim(), note:a.note||''}; }
  return null;
}
function renderLoomThreads(){
  if(C.ready){ C.setWeaves(loomNotes().map(parseWeave).filter(Boolean)); }
  const box = $('#loomList'); if(!box) return;
  const items = loomNotes();
  if(!items.length){ box.innerHTML = '<div class="empty">No threads yet.</div>'; return; }
  box.innerHTML = items.map(a => {
    const w = parseWeave(a);
    return `<div class="loom-thread"><span class="del" data-id="${a.id}">delete</span>
      ${w ? `<div class="rel">${esc(w.a)}${PAIR_SEP}${esc(w.b)}</div>` : '<div class="rel">observation</div>'}
      <div class="tx">${esc(a.note||'')}</div></div>`;
  }).join('');
  box.querySelectorAll('.del').forEach(d => d.onclick = () => delAnnotation(d.dataset.id));
}

async function saveWeave(text){
  const quote = loomPair ? `${loomPair.a}${PAIR_SEP}${loomPair.b}` : '';
  await fetch('/api/annotations', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({target:CHUNK_ID, kind:'note', quote, note:text, source:'loom', passage_id:CHUNK_ID})});
  $('#loomIn').value = ''; clearPair(); toast('Thread woven');
  await loadAnnotations();
}
$('#loomSave').onclick = () => { const t = $('#loomIn').value.trim();
  if(!t){ toast('Say or type the thread first'); return; } saveWeave(t); };
$('#loomIn').addEventListener('keydown', e => { if(e.key==='Enter' && (e.metaKey||e.ctrlKey)) $('#loomSave').click(); });

// Ask the AI to propose a reorganisation, given the concepts + your woven threads.
$('#loomReorg').onclick = async () => {
  if(!DATA) return;
  const concepts = C.labels().map(c => `${c.handle}. ${c.label}${c.gloss?` — ${c.gloss}`:''}`).join('\n');
  const threads = loomNotes().map(a => { const w = parseWeave(a);
    return w ? `${w.a}${PAIR_SEP}${w.b}: ${a.note}` : `· ${a.note}`; }).join('\n') || '(none yet)';
  const msg = `Here are the concepts of this passage:\n${concepts}\n\nMy woven threads:\n${threads}\n\n`
    + `Propose a reorganisation: cluster these concepts into a few groups, name each group, `
    + `note the key relations (including any I missed), and end with one sentence on the through-line. Be concise.`;
  const box = $('#loomSuggest'); box.style.display = 'block'; box.textContent = 'Thinking…';
  try{
    const d = await (await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({target:LOOM_CHAT, message:msg, context:DATA.chunk.text,
        source_label:`${DATA.chunk.title||''} (Loom)`})})).json();
    box.textContent = d.error ? d.error : d.reply;
  }catch(e){ box.textContent = 'Request failed.'; }
};

boot();
