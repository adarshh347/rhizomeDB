/* RhizomeDB whole-book reader.
 *
 * Loads one book as its ordered passages (/api/book?id=…), renders a continuous
 * reading column with a table of contents, and lets you:
 *   · highlight any selection  (saved as an annotation on that passage's chunk id)
 *   · comment on a highlight or note a whole passage
 *   · discuss the passage in view with the AI (one rolling thread per book)
 *   · jump into the resonance engine seeded by the passage you're reading
 *
 * Annotations attach to the SAME chunk ids the rest of RhizomeDB uses, so a
 * highlight made here also marks that passage in explore results and saved
 * sessions. All persistence goes through the existing /api endpoints.
 */
const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const params = new URLSearchParams(location.search);
const BOOK_ID = params.get('id') || '';
const CHAT_TARGET = 'book:' + BOOK_ID;   // one discussion thread per book

let BOOK = null;                 // {title, author, paragraphs:[...], toc:[...]}
let annotations = [];            // every annotation in this book
let byTarget = {};               // chunk_id -> [annotations]
let activeId = null;             // chunk id of the passage currently in view

function toast(t){ const e=$('#toast'); e.textContent=t; e.style.display='block';
  clearTimeout(toast._t); toast._t=setTimeout(()=>e.style.display='none', 1700); }

// ---------------------------------------------------------------- load
async function boot(){
  if(!BOOK_ID){ $('#reading').innerHTML='<div class="empty">No book chosen — back to the <a href="/library">library</a>.</div>'; return; }
  let d;
  try{ d = await (await fetch('/api/book?id='+encodeURIComponent(BOOK_ID))).json(); }
  catch(e){ $('#reading').innerHTML='<div class="empty">Could not reach the server.</div>'; return; }
  if(d.error){ $('#reading').innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
  BOOK = d;
  document.title = 'Reader · ' + d.title;
  $('#title').textContent = d.title;
  $('#byline').textContent = (d.author||'') + (d.year?(' · '+d.year):'') + ' · ' + d.n_chunks + ' passages';
  await loadAnnotations();
  renderToc();
  renderBook();
  observeParagraphs();
  await loadChat();
}

// ---------------------------------------------------------------- table of contents
let tocAnchors = [];   // {el, idx}  — for active-section highlighting while scrolling
function renderToc(){
  const box = $('#toc');
  if(!BOOK.toc.length){ box.innerHTML='<div class="empty" style="padding:0 6px">No sections.</div>'; return; }
  const idxOf = {};
  BOOK.paragraphs.forEach((p, i) => { if(!(p.id in idxOf)) idxOf[p.id] = i; });
  box.innerHTML = BOOK.toc.map(t => {
    const isPage = /^Page\s/i.test(t.heading);
    const right = (t.page && !isPage) ? `p.${esc(''+t.page)}` : '';
    return `<a class="toc-row" href="#p-${esc(t.id)}" data-id="${esc(t.id)}">`
      + `<span class="lbl">${esc(t.heading)}</span>`
      + `${right?`<span class="pg">${right}</span>`:''}</a>`;
  }).join('');
  tocAnchors = [...box.querySelectorAll('a')].map(a => ({el:a, idx: idxOf[a.dataset.id] ?? 0}));
  box.querySelectorAll('a').forEach(a => a.onclick = e => {
    e.preventDefault();
    const el = document.getElementById('p-'+a.dataset.id);
    if(el) el.scrollIntoView({behavior:'smooth', block:'start'});
  });
}
function markActiveToc(activeIdx){
  if(!tocAnchors.length) return;
  let cur = tocAnchors[0];
  for(const t of tocAnchors){ if(t.idx <= activeIdx) cur = t; else break; }
  tocAnchors.forEach(t => t.el.classList.toggle('active', t === cur));
  cur.el.scrollIntoView({block:'nearest'});
}

// ---------------------------------------------------------------- reading column
function renderBook(){
  let html = '';
  let lastHeading = null, lastPage = null;
  for(const p of BOOK.paragraphs){
    if(p.heading && p.heading !== lastHeading){
      html += `<h2 class="sec-head" id="sec-${esc(p.id)}">${esc(p.heading)}</h2>`;
      lastHeading = p.heading;
    }
    if(p.page && p.page !== lastPage){
      html += `<div class="pagemark">— page ${esc(''+p.page)} —</div>`;
      lastPage = p.page;
    }
    const anns = byTarget[p.id] || [];
    const hasNote = anns.some(a => a.note || a.kind==='note');
    const title = p.character ? `${p.character}${p.character_desc?' — '+p.character_desc:''}` : '';
    html += `<div class="para${hasNote?' has-note':''}" id="p-${esc(p.id)}" data-id="${esc(p.id)}" title="${esc(title)}">`
          + `<span class="pin" data-id="${esc(p.id)}" title="Note this whole passage">✎</span>`
          + applyHighlights(p.text, anns)
          + `</div>`;
  }
  $('#reading').innerHTML = html;
  $('#reading').querySelectorAll('.pin').forEach(pin =>
    pin.onclick = () => notePassage(pin.dataset.id));
  $('#reading').querySelectorAll('mark').forEach(m =>
    m.onclick = () => { switchTab('notes'); flashAnn(m.dataset.aid); });
}

// Wrap each highlight quote (first un-wrapped occurrence) in <mark>.
function applyHighlights(text, anns){
  let html = esc(text);
  // only reader highlights live in the passage; AI quotes come from answers
  anns.filter(a => a.kind==='highlight' && a.quote && (a.source||'reader')!=='ai').forEach(a => {
    const q = esc(a.quote);
    const idx = html.indexOf(q);
    if(idx === -1) return;   // span was edited away / spans a tag boundary — skip
    const cls = a.note ? 'has-note' : '';
    const repl = `<mark class="${cls}" data-aid="${a.id}" title="${a.note?esc(a.note):'highlight'}">${q}</mark>`;
    html = html.slice(0, idx) + repl + html.slice(idx + q.length);
  });
  return html;
}

// ---------------------------------------------------------------- active passage tracking
let _io = null;
function observeParagraphs(){
  if(_io) _io.disconnect();
  const main = $('#main');
  const total = BOOK.paragraphs.length;
  const io = new IntersectionObserver(entries => {
    // the visible paragraph nearest the top becomes "active" (grounds chat + explore)
    let top = null, topY = Infinity;
    for(const e of entries){ if(e.isIntersecting){ const y=e.boundingClientRect.top; if(y<topY){topY=y; top=e.target;} } }
    if(top){
      activeId = top.dataset.id;
      onActivePassage(activeId);   // Reading Rhythm: log the passage change
      document.querySelectorAll('.para.active').forEach(p=>p.classList.remove('active'));
      top.classList.add('active');
      const idx = BOOK.paragraphs.findIndex(p => p.id === activeId);
      if(idx>=0){ const pct = Math.round((idx+1)/total*100);
        $('#prog').textContent = `${pct}% · ${idx+1}/${total}`;
        $('#progfill').style.width = pct + '%';
        markActiveToc(idx);
        const para = BOOK.paragraphs[idx];
        $('#chatground').innerHTML = 'Grounded in the passage in view'
          + (para.page?` <b>(p.${para.page})</b>`:'');
      }
    }
  }, {root: main, rootMargin: '-12% 0px -70% 0px', threshold: 0});
  $('#reading').querySelectorAll('.para').forEach(p => io.observe(p));
  _io = io;
}

// ---------------------------------------------------------------- annotations
async function loadAnnotations(){
  try{
    const r = await fetch('/api/book_annotations?book='+encodeURIComponent(BOOK_ID));
    annotations = (await r.json()).items || [];
  }catch(e){ annotations = []; }
  byTarget = {};
  for(const a of annotations){ (byTarget[a.target] = byTarget[a.target] || []).push(a); }
  renderAnnList();
  renderCompanion();
}

const isAi = a => (a.source||'reader') === 'ai';
function jumpToPassage(chunkId){
  const p = document.getElementById('p-'+chunkId);
  if(p){ p.scrollIntoView({behavior:'smooth', block:'center'});
    p.style.transition='background .2s'; const old=p.style.background;
    p.style.background='var(--field)'; setTimeout(()=>p.style.background=old, 900); }
}
function passageLabel(chunkId){
  const p = BOOK.paragraphs.find(x => x.id === chunkId);
  if(!p) return chunkId;
  return (p.heading ? p.heading + ' · ' : '') + (p.page ? 'p.'+p.page+' · ' : '') + chunkId;
}

// "Notes & highlights" — the reader's own marks (everything that isn't a companion note).
function renderAnnList(){
  const box = $('#annlist');
  const human = annotations.filter(a => !isAi(a));
  if(!human.length){ box.innerHTML='<div class="empty">No notes or highlights yet.</div>'; return; }
  box.innerHTML = human.map(a => `
    <div class="ann ${a.kind==='note'?'note-only':''}" id="ann-${a.id}" data-target="${esc(a.target)}">
      ${a.quote?`<div class="q">${esc(a.quote)}</div>`:''}
      ${a.note?`<div class="n">${esc(a.note)}</div>`:''}
      <div class="meta"><span>${a.kind==='highlight'?'highlight':'note'} · ${esc(a.created||'')}</span>
        <span class="acts">
          <a class="deep" href="/plateau?chunk=${encodeURIComponent(a.target)}" target="_blank" rel="noopener">Deepen ↗</a>
          <span class="disc" data-id="${a.id}">Discuss ↳</span>
          <span class="del" data-id="${a.id}">delete</span></span></div>
    </div>`).join('');
  box.querySelectorAll('.ann').forEach(el => el.onclick = e => {
    if(['del','disc','deep'].some(c => e.target.classList.contains(c))) return;
    jumpToPassage(el.dataset.target);
  });
  box.querySelectorAll('.del').forEach(d => d.onclick = ev => { ev.stopPropagation(); delAnnotation(d.dataset.id); });
  box.querySelectorAll('.disc').forEach(d => d.onclick = ev => {
    ev.stopPropagation();
    const a = annotations.find(x => x.id === d.dataset.id);
    if(a) openThread(a);
  });
}

// "From the companion" — highlights/notes the reader kept from AI answers (R4),
// grouped by the passage each grew from.
function renderCompanion(){
  const box = $('#companionlist'); if(!box) return;
  const ai = annotations.filter(isAi);
  $('#companionCount') && ($('#companionCount').textContent = ai.length ? ' · ' + ai.length : '');
  if(!ai.length){ box.innerHTML='<div class="empty">Nothing yet. Select text in a companion answer to keep it here.</div>'; return; }
  const groups = {};
  for(const a of ai){ const k = a.passage_id || a.target; (groups[k] = groups[k] || []).push(a); }
  box.innerHTML = Object.entries(groups).map(([pid, items]) => `
    <div class="cgroup">
      <div class="cgroup-head" data-jump="${esc(pid)}">${esc(passageLabel(pid))} <span class="jump">jump ↗</span></div>
      ${items.map(a => `
        <div class="ann companion" id="ann-${a.id}">
          ${a.quote?`<div class="q">${esc(a.quote)}</div>`:''}
          ${a.note?`<div class="n">${esc(a.note)}</div>`:''}
          <div class="meta"><span class="src-badge">companion</span>
            <span class="acts">
              <span class="disc" data-reopen="${a.id}">Reopen ↳</span>
              <span class="del" data-id="${a.id}">delete</span></span></div>
        </div>`).join('')}
    </div>`).join('');
  box.querySelectorAll('.cgroup-head').forEach(h => h.onclick = () => { switchTab('notes'); jumpToPassage(h.dataset.jump); });
  box.querySelectorAll('.del').forEach(d => d.onclick = ev => { ev.stopPropagation(); delAnnotation(d.dataset.id); });
  box.querySelectorAll('[data-reopen]').forEach(d => d.onclick = ev => { ev.stopPropagation();
    reopenThread(annotations.find(x => x.id === d.dataset.reopen)); });
}

// Reopen the conversation a companion note came from, wherever it lives.
function reopenThread(note){
  if(!note) return;
  const ct = note.chat_target || '';
  if(ct.startsWith('ann:')){
    const a = annotations.find(x => x.id === ct.slice(4));
    if(a){ openThread(a); return; }
  }
  if(ct.startsWith('plateau:')){
    window.open('/plateau?chunk='+encodeURIComponent(note.passage_id||note.target), '_blank', 'noopener'); return;
  }
  // book-level thread → the Discuss tab; flash the source message if present
  switchTab('chat');
  setTimeout(() => {
    if(!note.msg_id) return;
    const el = $('#msgs').querySelector(`[data-msg-id="${CSS.escape(note.msg_id)}"]`);
    if(el){ el.scrollIntoView({block:'center'});
      el.style.outline='1px solid var(--accent)'; setTimeout(()=>el.style.outline='', 1300); }
  }, 80);
}

function flashAnn(id){
  const el = document.getElementById('ann-'+id);
  if(el){ el.scrollIntoView({behavior:'smooth', block:'center'});
    el.style.outline='1px solid var(--accent)'; setTimeout(()=>el.style.outline='', 1200); }
}

// extra carries provenance for companion notes (source:'ai', msg_id, chat_target,
// passage_id); empty for ordinary reader marks (source defaults to 'reader').
async function saveAnnotation(target, kind, quote, note, extra={}){
  $('#seltool').style.display='none';
  const body = {target, kind, quote, note, source:'reader', ...extra};
  const r = await fetch('/api/annotations', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  if(!r.ok){ toast('Could not save'); return; }
  const d = await r.json();
  // Reading Rhythm: a selection that became a highlight is NOT a "selected-not-highlighted" signal
  if(body.source==='reader' && kind==='highlight') logEv('select', {passage:target, highlighted:true});
  toast(body.source==='ai' ? 'Saved to “From the companion”' : 'Saved');
  window.getSelection().removeAllRanges();
  await loadAnnotations(); renderBook(); reobserve();
  // a reader's commentary opens its own discussion; companion notes don't recurse
  if(note && d.annotation && body.source==='reader') openThread(d.annotation);
}
async function delAnnotation(id){
  await fetch('/api/annotations/delete', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})});
  await loadAnnotations(); renderBook(); reobserve();
}
function notePassage(id){
  openComposer({title:'Note on this passage', saveLabel:'Save note',
    onSave: note => saveAnnotation(id, 'note', '', note)});
}

// ---------------------------------------------------------------- comment composer
const MODAL = {back:$('#modalBack'), title:$('#modalTitle'), quote:$('#modalQuote'),
               text:$('#modalText'), save:$('#modalSave'), onSave:null};
function openComposer({title, quote='', initial='', saveLabel='Save', onSave}){
  MODAL.title.textContent = title;
  if(quote){ MODAL.quote.textContent = '“' + quote + '”'; MODAL.quote.style.display='block'; }
  else MODAL.quote.style.display='none';
  MODAL.text.value = initial;
  MODAL.save.textContent = saveLabel;
  MODAL.onSave = onSave;
  MODAL.back.classList.add('open');
  setTimeout(() => MODAL.text.focus(), 40);
}
function closeComposer(){ MODAL.back.classList.remove('open'); MODAL.onSave = null; }
function submitComposer(){
  const t = MODAL.text.value.trim();
  const cb = MODAL.onSave;
  closeComposer();
  if(t && cb) cb(t);
}
$('#modalSave').onclick = submitComposer;
$('#modalCancel').onclick = closeComposer;
$('#modalClose').onclick = closeComposer;
MODAL.back.addEventListener('mousedown', e => { if(e.target === MODAL.back) closeComposer(); });
MODAL.text.addEventListener('keydown', e => {
  if(e.key === 'Escape'){ e.preventDefault(); closeComposer(); }
  if(e.key === 'Enter' && (e.metaKey || e.ctrlKey)){ e.preventDefault(); submitComposer(); }
});

// re-attach the IntersectionObserver after a re-render (highlights changed the DOM)
function reobserve(){ observeParagraphs(); }

// ---------------------------------------------------------------- selection toolbar
let pending = null;   // {target, quote}
$('#reading').addEventListener('mouseup', () => {
  const sel = window.getSelection();
  const txt = (sel ? sel.toString() : '').trim();
  const tool = $('#seltool');
  if(txt.length < 3){ tool.style.display='none'; return; }
  // which passage does the selection start in?
  let node = sel.anchorNode;
  while(node && !(node.classList && node.classList.contains('para'))) node = node.parentElement;
  if(!node){ tool.style.display='none'; return; }
  pending = {target: node.dataset.id, quote: txt};
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  tool.style.display='flex';
  tool.style.top = (window.scrollY + rect.top - tool.offsetHeight - 8) + 'px';
  tool.style.left = (window.scrollX + rect.left) + 'px';
});
document.addEventListener('mousedown', e => {
  if(!$('#seltool').contains(e.target) && e.target.tagName!=='MARK') $('#seltool').style.display='none';
});

// R2 — the same toolbar fires inside an assistant bubble, capturing provenance so
// the highlight is saved as a companion note linked to the passage discussed.
function wireAiSelection(container, passageIdFn){
  if(!container) return;
  container.addEventListener('mouseup', () => {
    const sel = window.getSelection();
    const txt = (sel ? sel.toString() : '').trim();
    if(txt.length < 3) return;
    let node = sel.anchorNode;
    while(node && !(node.classList && node.classList.contains('msg'))) node = node.parentElement;
    if(!node || !node.classList.contains('assistant')) return;
    const passageId = passageIdFn();
    if(!passageId){ toast('No passage in view to link this to'); return; }
    pending = {target: passageId, quote: txt,
               extra: {source:'ai', msg_id: node.dataset.msgId || '',
                       chat_target: node.dataset.target || '', passage_id: passageId}};
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const tool = $('#seltool');
    tool.style.display = 'flex';
    tool.style.top = (window.scrollY + rect.top - tool.offsetHeight - 8) + 'px';
    tool.style.left = (window.scrollX + rect.left) + 'px';
  });
}
wireAiSelection($('#msgs'), () => activeId);
wireAiSelection($('#threadMsgs'), () => THREAD.passageId);

$('#hl').onclick = () => pending && saveAnnotation(pending.target, 'highlight', pending.quote, '', pending.extra || {});
$('#hlc').onclick = () => {
  if(!pending) return;
  const {target, quote, extra} = pending;
  const ai = extra && extra.source === 'ai';
  $('#seltool').style.display = 'none';
  openComposer({title: ai ? 'Note on the companion' : 'Highlight + comment', quote, saveLabel:'Save comment',
    onSave: note => saveAnnotation(target, 'highlight', quote, note, extra || {})});
};

// ---------------------------------------------------------------- tabs
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.pane===name));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id==='pane-'+name));
  if(name === 'rhythm' && rhythmEnabled()) refreshRhythm();
}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.pane));

// ---------------------------------------------------------------- chat (grounded in the passage in view)
// Assistant bubbles carry msg_id + chat target so a reader can annotate them.
function renderMsg(m, target){
  const who = m.role==='user' ? 'You' : 'Companion';
  const prov = (m.role==='assistant' && m.msg_id)
    ? ` data-msg-id="${esc(m.msg_id)}" data-target="${esc(target||'')}"` : '';
  return `<div class="msg ${m.role}"${prov}><div class="who">${who}</div>${esc(m.content)}</div>`;
}
async function loadChat(){
  try{
    const r = await fetch('/api/chat?target='+encodeURIComponent(CHAT_TARGET));
    const msgs = (await r.json()).messages || [];
    const box = $('#msgs');
    box.innerHTML = msgs.length ? msgs.map(m => renderMsg(m, CHAT_TARGET)).join('') : '';
    box.scrollTop = box.scrollHeight;
  }catch(e){}
}
function activeContext(){
  const idx = BOOK.paragraphs.findIndex(p => p.id === activeId);
  if(idx < 0) return {text:'', label:''};
  // the passage in view plus a neighbour each side, so the AI has a little run-up
  const lo = Math.max(0, idx-1), hi = Math.min(BOOK.paragraphs.length, idx+2);
  const text = BOOK.paragraphs.slice(lo, hi).map(p => p.text).join('\n\n');
  const p = BOOK.paragraphs[idx];
  return {text, label: `${BOOK.author}, ${BOOK.title}${p.page?(', p.'+p.page):''}`};
}
$('#send').onclick = sendChat;
$('#chatin').addEventListener('keydown', e => { if(e.key==='Enter' && (e.metaKey||e.ctrlKey)) sendChat(); });
async function sendChat(){
  const inp = $('#chatin'); const msg = inp.value.trim(); if(!msg) return;
  const {text, label} = activeContext();
  inp.value=''; $('#send').disabled=true; $('#chathint').textContent='thinking…';
  const box = $('#msgs');
  box.innerHTML += renderMsg({role:'user', content:msg}); box.scrollTop = box.scrollHeight;
  try{
    const r = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({target:CHAT_TARGET, message:msg, context:text, source_label:label})});
    const d = await r.json();
    if(d.error){ $('#chathint').textContent = d.error; }
    else{ box.innerHTML += renderMsg({role:'assistant', content:d.reply, msg_id:d.msg_id}, CHAT_TARGET);
      $('#chathint').textContent = d.usage ? `${d.usage.provider||''} · ${d.usage.total||0} tokens (run total ${d.cumulative||0})` : ''; }
    box.scrollTop = box.scrollHeight;
  }catch(e){ $('#chathint').textContent='request failed'; }
  $('#send').disabled=false;
}

// ---------------------------------------------------------------- per-comment thread
// Each commentary gets its own AI conversation (target "ann:<id>"), grounded in
// the paragraph it sits on plus the note itself, so the discussion stays on that
// passage and persists between visits.
const THREAD = {target:'', context:'', label:'', comment:'', passageId:''};
function openThread(ann){
  const para = BOOK.paragraphs.find(p => p.id === ann.target);
  const ptext = para ? para.text : '';
  const quote = ann.quote || '', comment = ann.note || '';
  THREAD.target = 'ann:' + ann.id;
  THREAD.passageId = ann.target;   // the chunk this discussion is about (for AI annotations)
  THREAD.comment = comment;
  THREAD.context = `Passage under discussion:\n${ptext}`
    + (quote ? `\n\nThe reader highlighted: "${quote}"` : '')
    + (comment ? `\n\nThe reader's note: ${comment}` : '');
  THREAD.label = `${BOOK.author}, ${BOOK.title}` + (para && para.page ? `, p.${para.page}` : '');
  $('#threadSrc').textContent = THREAD.label;
  $('#threadDeepen').href = '/plateau?chunk=' + encodeURIComponent(ann.target);
  $('#threadNote').innerHTML = (quote ? `<div class="tq">${esc(quote)}</div>` : '')
    + (comment ? `<div class="tn"><span class="lbl">Your note</span>${esc(comment)}</div>` : '');
  const hasNote = !!(quote || comment);
  $('#threadNoteToggle').style.display = hasNote ? 'flex' : 'none';
  $('#threadNotePreview').textContent = comment || quote || '';
  setNoteFolded(false);   // start open; folds itself once the conversation begins
  $('#threadIn').value = '';
  loadThread();
  $('#threadBack').classList.add('open');
  setTimeout(() => $('#threadIn').focus(), 60);
}
function closeThread(){ $('#threadBack').classList.remove('open'); }
// fold the quote+note so the conversation gets the height (off/on, LeetCode-style)
function setNoteFolded(folded){
  $('#thread').classList.toggle('note-folded', folded);
  $('#threadNoteCaret').textContent = folded ? '▸' : '▾';
  $('#threadNoteLabel').textContent = folded ? 'Show note' : 'Hide note';
}
$('#threadNoteToggle').onclick = () =>
  setNoteFolded(!$('#thread').classList.contains('note-folded'));
async function loadThread(){
  const box = $('#threadMsgs');
  let msgs = [];
  try{ msgs = (await (await fetch('/api/chat?target='+encodeURIComponent(THREAD.target))).json()).messages || []; }
  catch(e){}
  if(msgs.length){ box.innerHTML = msgs.map(m => renderMsg(m, THREAD.target)).join(''); setNoteFolded(true); }
  else{
    box.innerHTML = `<div class="empty">Ask anything about this passage — your note is the
      starting point, and the AI keeps it and the paragraph in view as it answers.</div>`
      + (THREAD.comment ? `<button class="btn ghost kick" id="threadKick">Have the AI respond to your note</button>` : '');
    const k = $('#threadKick');
    if(k) k.onclick = () => sendThread(THREAD.comment);
  }
  box.scrollTop = box.scrollHeight;
}
async function sendThread(text){
  const inp = $('#threadIn');
  const msg = (text != null ? text : inp.value).trim();
  if(!msg) return;
  if(text == null) inp.value = '';
  $('#threadSend').disabled = true; $('#threadHint').textContent = 'thinking…';
  const box = $('#threadMsgs');
  if(box.querySelector('.empty')) box.innerHTML = '';
  box.innerHTML += renderMsg({role:'user', content:msg}); box.scrollTop = box.scrollHeight;
  try{
    const d = await (await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({target:THREAD.target, message:msg, context:THREAD.context, source_label:THREAD.label})})).json();
    if(d.error){ $('#threadHint').textContent = d.error; }
    else{ box.innerHTML += renderMsg({role:'assistant', content:d.reply, msg_id:d.msg_id}, THREAD.target); setNoteFolded(true);
      $('#threadHint').textContent = d.usage ? `${d.usage.provider||''} · ${d.usage.total||0} tokens` : ''; }
    box.scrollTop = box.scrollHeight;
  }catch(e){ $('#threadHint').textContent = 'request failed'; }
  $('#threadSend').disabled = false;
}
$('#threadSend').onclick = () => sendThread();
$('#threadClose').onclick = closeThread;
$('#threadBack').addEventListener('mousedown', e => { if(e.target === $('#threadBack')) closeThread(); });
$('#threadIn').addEventListener('keydown', e => {
  if(e.key === 'Escape'){ e.preventDefault(); closeThread(); }
  if(e.key === 'Enter' && (e.metaKey || e.ctrlKey)){ e.preventDefault(); sendThread(); }
});

// ---------------------------------------------------------------- explore this passage
$('#exploreBtn').onclick = () => {
  if(!activeId){ toast('Scroll to a passage first'); return; }
  window.open('/?mode=chunk&value='+encodeURIComponent(activeId), '_blank', 'noopener');
};

// ---------------------------------------------------------------- light / dark
function applyTheme(t){
  document.body.classList.toggle('dark', t === 'dark');
  $('#themeBtn').textContent = t === 'dark' ? '☀' : '☾';
  $('#themeBtn').title = t === 'dark' ? 'Switch to light' : 'Switch to dark';
}
$('#themeBtn').onclick = () => {
  const next = document.body.classList.contains('dark') ? 'light' : 'dark';
  localStorage.setItem('rhz_theme', next); applyTheme(next);
};
applyTheme(localStorage.getItem('rhz_theme') || 'light');

// ---------------------------------------------------------------- reading text size
// One control scales every reading surface (passage, answers, plateau) via the
// --read-scale CSS var; persisted and shared across reader pages.
function applyScale(s){ s = Math.max(.8, Math.min(1.7, Math.round(s*100)/100));
  document.body.style.setProperty('--read-scale', s); localStorage.setItem('rhz_scale', s); }
$('#fontDown').onclick = () => applyScale((+localStorage.getItem('rhz_scale')||1) - .08);
$('#fontUp').onclick   = () => applyScale((+localStorage.getItem('rhz_scale')||1) + .08);
applyScale(+localStorage.getItem('rhz_scale') || 1);

// ---------------------------------------------------------------- collapse rails
// The toggle reads "active" while its rail is shown.
function applyCollapse(cls, btn, on){
  document.body.classList.toggle(cls, on);
  btn.classList.toggle('active', !on);   // active == rail visible
}
function wireCollapse(btnSel, cls, key){
  const btn = $(btnSel);
  applyCollapse(cls, btn, localStorage.getItem(key) === '1');
  btn.onclick = () => {
    const on = !document.body.classList.contains(cls);
    localStorage.setItem(key, on ? '1' : '0');
    applyCollapse(cls, btn, on);
  };
}
wireCollapse('#tocToggle', 'toc-collapsed', 'rhz_toc_collapsed');
wireCollapse('#railToggle', 'rail-collapsed', 'rhz_rail_collapsed');

// ---------------------------------------------------------------- resizable panels
// Drag a gutter to widen the contents or notes rail; reading takes the rest.
const shell = $('#shell');
const LIMITS = {toc:[160,560], rail:[240,720]};
function setWidth(side, px){
  const [lo, hi] = LIMITS[side];
  px = Math.max(lo, Math.min(hi, Math.round(px)));
  shell.style.setProperty(side === 'toc' ? '--toc-w' : '--rail-w', px + 'px');
  localStorage.setItem('rhz_' + side + '_w', px);
}
// restore saved widths
['toc','rail'].forEach(side => {
  const v = +localStorage.getItem('rhz_' + side + '_w');
  if(v) shell.style.setProperty(side === 'toc' ? '--toc-w' : '--rail-w', v + 'px');
});
let drag = null;
document.querySelectorAll('.gutter').forEach(g => g.addEventListener('mousedown', e => {
  e.preventDefault();
  drag = {side: g.dataset.resize, g};
  g.classList.add('drag'); document.body.classList.add('resizing');
}));
window.addEventListener('mousemove', e => {
  if(!drag) return;
  const r = shell.getBoundingClientRect();
  setWidth(drag.side, drag.side === 'toc' ? e.clientX - r.left : r.right - e.clientX);
});
window.addEventListener('mouseup', () => {
  if(!drag) return;
  drag.g.classList.remove('drag'); document.body.classList.remove('resizing'); drag = null;
});
// double-click a gutter to reset that rail to its default width
document.querySelectorAll('.gutter').forEach(g => g.addEventListener('dblclick', () => {
  const side = g.dataset.resize;
  localStorage.removeItem('rhz_' + side + '_w');
  shell.style.removeProperty(side === 'toc' ? '--toc-w' : '--rail-w');
}));

boot();
