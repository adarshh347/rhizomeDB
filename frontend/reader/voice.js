/* RhizomeDB — Loom voice (dictation).
 *
 * Speak into any field. A small mic button transcribes speech to text via the
 * browser's Web Speech API — zero dependencies, no API key, on localhost/HTTPS.
 * Buttons opt in declaratively:  <button class="micbtn" data-target="#someInput">🎙</button>
 * and are auto-wired on load; dynamically-added buttons can call Voice.attach.
 * Where the browser has no SpeechRecognition, mic buttons quietly hide.
 */
window.Voice = (function(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const supported = !!SR;

  function attach(btn, getTarget){
    if(!btn || btn._voiceWired) return;
    btn._voiceWired = true;
    if(!supported){ btn.style.display = 'none'; return; }
    btn.title = btn.title || 'Dictate — speak to transcribe';
    let rec = null, listening = false;

    btn.addEventListener('click', () => {
      if(listening){ rec && rec.stop(); return; }
      const target = typeof getTarget === 'function' ? getTarget() : getTarget;
      if(!target) return;
      rec = new SR();
      rec.lang = navigator.language || 'en-US';
      rec.interimResults = true;
      rec.continuous = true;
      const base = target.value ? target.value.replace(/\s+$/, '') + ' ' : '';
      let finalText = '';
      rec.onresult = e => {
        let interim = '';
        for(let i = e.resultIndex; i < e.results.length; i++){
          const r = e.results[i];
          if(r.isFinal) finalText += r[0].transcript;
          else interim += r[0].transcript;
        }
        target.value = base + finalText + interim;
        target.dispatchEvent(new Event('input'));
        target.scrollTop = target.scrollHeight;
      };
      rec.onend = () => { listening = false; btn.classList.remove('listening');
        target.value = (base + finalText).trim(); target.focus(); };
      rec.onerror = ev => { listening = false; btn.classList.remove('listening');
        if(ev.error === 'not-allowed') btn.title = 'Microphone permission denied'; };
      try{ rec.start(); listening = true; btn.classList.add('listening'); }
      catch(e){ listening = false; }
    });
  }

  function scan(root){
    (root || document).querySelectorAll('.micbtn[data-target]').forEach(
      btn => attach(btn, () => document.querySelector(btn.dataset.target)));
  }

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => scan());
  else scan();

  return {attach, scan, supported};
})();
