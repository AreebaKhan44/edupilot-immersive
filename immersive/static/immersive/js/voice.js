// EduPilot voice engine - shared by the 3D viewer and the lesson page.
//  * Browser voice (Web Speech API) when the device has a voice for the lesson language.
//  * Otherwise (typically Urdu / Hindi on desktop) the server-generated audio of the scene (gTTS / espeak).
//  * Long narrations are split into sentence chunks (Chrome stops reading after ~15 s otherwise).
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
    this.speaking = false;
    this.paused = false;
    this.onchange = null;                      // called when speaking/paused changes
  }

  // ----- voices -----
  allVoices() { return this.synth ? this.synth.getVoices() : []; }
  voices() {
    const two = this.lang.slice(0, 2).toLowerCase();
    const all = this.allVoices();
    const mine = all.filter((v) => v.lang && v.lang.toLowerCase().startsWith(two));
    return mine.length ? mine : [];
  }
  hasBrowserVoice() { return this.voices().length > 0; }
  pickVoice() {
    const list = this.voices();
    return list.find((v) => v.voiceURI === this.voiceURI) || list.find((v) => v.lang.toLowerCase() === this.lang.toLowerCase()) || list[0] || null;
  }
  onVoicesChanged(cb) { if (this.synth) this.synth.addEventListener?.('voiceschanged', cb); }

  // ----- settings -----
  setRate(r) { this.rate = Math.min(1.6, Math.max(0.6, Number(r) || 1)); if (this.audio) this.audio.playbackRate = this.rate; this._persist(); }
  setVoice(uri) { this.voiceURI = uri || ''; this._persist(); }
  setSource(s) { this.source = ['auto', 'browser', 'server'].includes(s) ? s : 'auto'; this._persist(); }
  _persist() { save({ rate: this.rate, voiceURI: this.voiceURI, source: this.source }); }

  // which engine will be used for this utterance
  engineFor(audioUrl) {
    if (this.source === 'server' && audioUrl) return 'server';
    if (this.source === 'browser' && this.synth) return 'browser';
    if (this.hasBrowserVoice()) return 'browser';
    if (audioUrl) return 'server';
    return this.synth ? 'browser' : 'none';
  }

  // ----- playback -----
  _set(speaking, paused = false) { this.speaking = speaking; this.paused = paused; this.onchange?.(this); }

  /** speak(text, {audioUrl, onend, onfail}) - onend after normal finish, onfail if nothing could be played. */
  speak(text, { audioUrl = '', onend = null, onfail = null } = {}) {
    this.cancel(false);
    const token = this.token;
    text = String(text || '').trim();
    if (!text) { onend?.(); return; }
    const finish = (failed) => { if (token !== this.token) return; this._set(false); failed ? onfail?.() : onend?.(); };
    const engine = this.engineFor(audioUrl);
    this._set(true);
    if (engine === 'server') return this._playAudio(audioUrl, token, finish, text);
    if (engine === 'browser') return this._playBrowser(text, token, finish);
    finish(true);
  }

  _playBrowser(text, token, finish) {
    const parts = chunkText(text); let i = 0;
    const next = () => {
      if (token !== this.token) return;
      if (i >= parts.length) return finish(false);
      const u = new SpeechSynthesisUtterance(parts[i++]);
      u.lang = this.lang; u.rate = this.rate;
      const v = this.pickVoice(); if (v) { try { u.voice = v; } catch { /* keep the default voice */ } }
      u.onend = next;
      u.onerror = (e) => { if (token !== this.token || e.error === 'canceled' || e.error === 'interrupted') return; finish(true); };
      this.synth.speak(u);
    };
    this.synth.cancel(); next();
  }

  _playAudio(url, token, finish, textForFallback) {
    const a = new Audio(url); a.playbackRate = this.rate; this.audio = a;
    a.onended = () => finish(false);
    a.onerror = () => { // server could not make audio (no gTTS / espeak): try the browser voice instead
      if (token !== this.token) return;
      if (this.synth && this.source !== 'server') { this.audio = null; this._playBrowser(textForFallback, token, finish); } else finish(true);
    };
    a.play().catch((e) => { if (token !== this.token) return; if (e && e.name === 'NotAllowedError') finish(true); else a.onerror(); });
  }

  pause() { if (!this.speaking || this.paused) return; this.audio ? this.audio.pause() : this.synth?.pause(); this._set(true, true); }
  resume() { if (!this.paused) return; this.audio ? this.audio.play() : this.synth?.resume(); this._set(true, false); }
  togglePause() { this.paused ? this.resume() : this.pause(); }
  cancel(notify = true) {
    this.token++;
    if (this.audio) { this.audio.onended = this.audio.onerror = null; this.audio.pause(); this.audio = null; }
    this.synth?.cancel();
    if (notify) this._set(false); else { this.speaking = false; this.paused = false; }
  }
}
