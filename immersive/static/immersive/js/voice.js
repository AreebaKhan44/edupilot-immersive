// EduPilot voice engine - shared by the 3D viewer (teacher AND student) and the lesson page.
//  * Device voice (Web Speech API) when the browser has one.
//  * Server voice (/lessons/<id>/scenes/<n>/audio/ : gTTS online, Windows SAPI or espeak-ng offline) as the other engine.
//  * If the first engine is silent / fails, the other one is tried automatically (so the student always hears something).
//  * Long narrations are cut into sentence chunks (Chrome stops reading after ~15 s otherwise).
//  * Fixes for the classic "no sound" bugs: utterance garbage-collected before it ends, speak() right after cancel()
//    being dropped, synth stuck in "paused", and engines that never fire an event (watchdog timers).
//  * User choices (voice, speed, source) are remembered in localStorage.

const LANGS = { en: 'en-US', ur: 'ur-PK', hi: 'hi-IN' };
const KEY = 'edupilot.voice.v1';

function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } }
function save(o) { try { localStorage.setItem(KEY, JSON.stringify(o)); } catch { /* private mode */ } }

export function chunkText(text, max = 170) {
  const sentences = String(text || '').replace(/\s+/g, ' ').trim().split(/(?<=[.!?؟۔।])\s+/);
  const out = []; let cur = '';
  for (const s of sentences) {
    if (!s) continue;
    if ((cur + ' ' + s).trim().length <= max) cur = (cur + ' ' + s).trim();
    else {
      if (cur) out.push(cur);
      if (s.length <= max) cur = s;
      else { // very long sentence: cut on spaces
        cur = ''; let part = '';
        for (const w of s.split(' ')) { if ((part + ' ' + w).trim().length > max) { out.push(part); part = w; } else part = (part + ' ' + w).trim(); }
        cur = part;
      }
    }
  }
  if (cur) out.push(cur);
  return out;
}

export class Voice {
  constructor({ locale = 'en' } = {}) {
    this.locale = locale;
    this.lang = LANGS[locale] || 'en-US';
    this.synth = window.speechSynthesis || null;
    const p = load();
    this.rate = Number(p.rate) || 0.95;
    this.voiceURI = p.voiceURI || '';
    this.source = p.source || 'auto';          // auto | browser | server
    this.token = 0;                            // bumps on every speak()/cancel() so stale callbacks are ignored
    this.audio = null;
    this._utt = null;                          // keep a reference: Chrome garbage-collects running utterances and then never fires onend
    this._timers = new Set();
    this.speaking = false;
    this.paused = false;
    this.engine = '';                          // 'browser' | 'server' (engine that is playing now)
    this.status = '';
    this.onchange = null;                      // called when speaking/paused changes
    this.onstatus = null;                      // called with a short human message (what is playing / what went wrong)
    // some browsers need a "warm-up": getVoices() is empty until the first voiceschanged event
    if (this.synth) { try { this.synth.getVoices(); } catch { /* ignore */ } }
  }

  // ----- voices -----
  allVoices() { try { return this.synth ? this.synth.getVoices() : []; } catch { return []; } }
  voices() {
    const two = this.lang.slice(0, 2).toLowerCase();
    return this.allVoices().filter((v) => v.lang && v.lang.toLowerCase().replace('_', '-').startsWith(two));
  }
  hasBrowserVoice() { return this.voices().length > 0; }
  pickVoice() {
    const list = this.voices();
    return list.find((v) => v.voiceURI === this.voiceURI) || list.find((v) => v.lang.toLowerCase().replace('_', '-') === this.lang.toLowerCase()) || list.find((v) => v.localService) || list[0] || null;
  }
  onVoicesChanged(cb) { if (this.synth) this.synth.addEventListener?.('voiceschanged', cb); }

  // ----- settings -----
  setRate(r) { this.rate = Math.min(1.6, Math.max(0.6, Number(r) || 1)); if (this.audio) this.audio.playbackRate = this.rate; this._persist(); }
  setVoice(uri) { this.voiceURI = uri || ''; this._persist(); }
  setSource(s) { this.source = ['auto', 'browser', 'server'].includes(s) ? s : 'auto'; this._persist(); }
  _persist() { save({ rate: this.rate, voiceURI: this.voiceURI, source: this.source }); }
  _say(msg) { this.status = msg; this.onstatus?.(msg); }

  // order in which the engines are tried for this utterance (the second one is the automatic fall-back)
  enginesFor(audioUrl) {
    const b = !!this.synth, s = !!audioUrl;
    let order;
    if (this.source === 'server') order = ['server', 'browser'];
    else if (this.source === 'browser') order = ['browser', 'server'];
    else if (this.hasBrowserVoice() || (b && !this.allVoices().length && this.locale === 'en')) order = ['browser', 'server'];   // voice list not loaded yet: default device voice speaks English
    else order = ['server', 'browser'];
    return order.filter((e) => (e === 'browser' ? b : s));
  }

  // ----- playback -----
  _set(speaking, paused = false) { this.speaking = speaking; this.paused = paused; this.onchange?.(this); }
  _later(fn, ms) { const id = setTimeout(() => { this._timers.delete(id); fn(); }, ms); this._timers.add(id); return id; }
  _clear(id) { if (id) { clearTimeout(id); this._timers.delete(id); } }
  _clearAll() { this._timers.forEach((id) => clearTimeout(id)); this._timers.clear(); }

  /** speak(text, {audioUrl, onend, onfail}) - onend after a normal finish, onfail if NO engine could play it. */
  speak(text, { audioUrl = '', onend = null, onfail = null } = {}) {
    this.cancel(false);
    const token = this.token;
    text = String(text || '').trim();
    if (!text) { onend?.(); return; }
    const engines = this.enginesFor(audioUrl);
    this._set(true);
    this._say('⏳ Starting voice…');
    const alive = () => token === this.token;
    const finish = (failed) => { if (!alive()) return; this._set(false); this.engine = ''; failed ? onfail?.() : onend?.(); };
    let k = 0, lastReason = '';
    const attempt = () => {
      if (!alive()) return;
      if (k >= engines.length) { this._say('⚠️ ' + (lastReason || 'No voice could play on this device.')); return finish(true); }
      const eng = engines[k++]; this.engine = eng;
      const done = (ok, reason) => {
        if (!alive()) return;
        if (ok) { this._say(''); return finish(false); }
        lastReason = reason || lastReason; attempt();                       // try the other engine
      };
      if (eng === 'server') this._playAudio(audioUrl, token, done);
      else this._playBrowser(text, token, done);
    };
    // Chrome drops a speak() that comes in the same tick as cancel(): give it a moment
    this._later(attempt, 90);
  }

  _playBrowser(text, token, done) {
    const synth = this.synth; if (!synth) return done(false, 'This browser has no speech synthesis.');
    const parts = chunkText(text); let i = 0, started = false, ended = false;
    const alive = () => token === this.token && !ended;
    const startWatch = this._later(() => { if (!alive() || started) return; ended = true; try { synth.cancel(); } catch { /* ignore */ } done(false, 'The device voice did not start (no sound from the browser).'); }, 4000);
    try { synth.cancel(); synth.resume(); } catch { /* ignore */ }
    const next = () => {
      if (!alive()) return;
      if (i >= parts.length) { ended = true; this._clear(startWatch); this._utt = null; return done(true); }
      const part = parts[i++];
      const u = new SpeechSynthesisUtterance(part);
      this._utt = u;
      u.lang = this.lang; u.rate = this.rate; u.volume = 1;
      const v = this.pickVoice(); if (v) { try { u.voice = v; u.lang = v.lang || this.lang; } catch { /* keep the default voice */ } }
      let moved = false; const go = () => { if (moved) return; moved = true; this._clear(chunkWatch); next(); };
      const chunkWatch = this._later(go, Math.max(9000, part.length * 140 / Math.max(0.6, this.rate)) + 4000);   // engine never reported the end of this chunk
      u.onstart = () => { started = true; this._clear(startWatch); this._say('🔊 Playing (device voice)'); };
      u.onend = () => { started = true; this._clear(startWatch); go(); };
      u.onerror = (e) => {
        if (!alive() || e.error === 'canceled' || e.error === 'interrupted') return;
        ended = true; this._clear(startWatch); this._clear(chunkWatch);
        done(false, e.error === 'not-allowed' ? 'The browser blocked the sound – click anywhere on the page, then press Repeat.' : 'The device voice failed (' + (e.error || 'error') + ').');
      };
      try { synth.speak(u); } catch { ended = true; this._clear(startWatch); done(false, 'The device voice could not start.'); }
    };
    this._later(next, 60);
  }

  _playAudio(url, token, done) {
    if (!url) return done(false, 'No server voice for this scene.');
    const a = new Audio(); a.preload = 'auto'; a.playbackRate = this.rate; this.audio = a;
    let settled = false;
    const finish = (ok, reason) => { if (settled) return; settled = true; this._clear(watch); a.onended = a.onerror = a.onplaying = null; if (this.audio === a) this.audio = null; if (!ok) { try { a.pause(); } catch { /* ignore */ } } done(ok, reason); };
    // the server may need some seconds to create the audio the first time (gTTS / SAPI), so the watchdog is generous
    const watch = this._later(() => finish(false, 'The server voice took too long.'), 25000);
    this._say('⏳ Preparing server voice…');
    a.onplaying = () => { this._clear(watch); this._say('🔊 Playing (server voice)'); };
    a.onended = () => finish(true);
    a.onerror = () => finish(false, 'Server voice is not available (install gTTS with internet, or use the device voice).');
    a.src = url;
    const p = a.play();
    if (p && p.catch) p.catch((e) => { if (e && e.name === 'AbortError') return; finish(false, e && e.name === 'NotAllowedError' ? 'The browser blocked the sound – click anywhere on the page, then press Repeat.' : 'Server voice could not play.'); });
  }

  pause() { if (!this.speaking || this.paused) return; if (this.audio) this.audio.pause(); else this.synth?.pause(); this._set(true, true); }
  resume() { if (!this.paused) return; if (this.audio) this.audio.play().catch(() => {}); else this.synth?.resume(); this._set(true, false); }
  togglePause() { this.paused ? this.resume() : this.pause(); }
  cancel(notify = true) {
    this.token++;
    this._clearAll();
    if (this.audio) { this.audio.onended = this.audio.onerror = this.audio.onplaying = null; try { this.audio.pause(); } catch { /* ignore */ } this.audio = null; }
    this._utt = null;
    try { this.synth?.cancel(); } catch { /* ignore */ }
    if (notify) { this._set(false); this._say(''); } else { this.speaking = false; this.paused = false; }
  }
}
