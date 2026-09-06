/* daw.mjs — SfxEngine: raw keeper playback + runtime two-layer ADSR automation.
 *
 * One file, two consumers:
 *   - the sound desk (daw.html) imports ./daw.mjs to audition takes;
 *   - the game imports its accepted copy (assets/daw.mjs) to play them.
 * Both must produce the same performance from the same automation card, so the
 * envelope schedule below is THE reference: attack (linear to peak), hold,
 * decay (exponential to sustain), sustain (loop wraps keep it, never
 * retrigger), release on stop (setTargetAtTime toward 0, tau = release/3).
 * export.py:layer_gain is the numpy twin. Nothing is ever baked into audio.
 *
 * Automation card shape (automation.yaml → bank JSON):
 *   layers: { hit:  { peakDb, attackMs, holdMs, decayMs, sustainDb, releaseMs },
 *             body: { peakDb, attackMs, holdMs, decayMs, sustainDb, releaseMs } }
 * Sustain is a level; every other knob is a time. A card's monitorDb is the
 * sound's playback gain: the bank carries it as gainDb and play() applies it
 * live on the voice master (never rendered into audio), so the game is
 * exactly as loud as the desk was.
 */

export const VERSION = '1.1.0';
export const LAYER_KEYS = ['hit', 'body'];
export const db2g = db => Math.pow(10, db / 20);
const FLOOR = 1e-4;   // exponential ramps cannot reach 0; this is -80 dB

export const DEFAULT_LAYERS = {
  hit:  { peakDb: 0,  attackMs: 5,    holdMs: 500, decayMs: 500, sustainDb: -40, releaseMs: 120 },
  body: { peakDb: -3, attackMs: 3000, holdMs: 0,   decayMs: 200, sustainDb: -3,  releaseMs: 800 },
};

export function cloneLayers(layers = DEFAULT_LAYERS) {
  const out = {};
  for (const k of LAYER_KEYS) out[k] = Object.assign({}, DEFAULT_LAYERS[k], layers[k] || {});
  return out;
}

/** Numeric twin of the WebAudio schedule: [[t, gain], ...] for one layer. */
export function layerGains(L, tMax, N) {
  const A = L.attackMs / 1000, H = L.holdMs / 1000, D = L.decayMs / 1000;
  const peak = Math.max(db2g(L.peakDb), FLOOR), sus = Math.max(db2g(L.sustainDb), FLOOR);
  const out = [];
  for (let i = 0; i <= N; i++) {
    const t = tMax * i / N;
    let g;
    if (t < A) g = FLOOR + (peak - FLOOR) * (A ? t / A : 1);
    else if (t < A + H) g = peak;
    else if (t < A + H + D) {
      const u = D ? (t - A - H) / D : 1;
      g = peak * Math.pow(Math.max(sus / peak, FLOOR), u);   // exponential decay (or swell)
    } else g = sus;
    out.push([t, g]);
  }
  return out;
}

/** Sum of both layers over time (what the ear hears before master gain). */
export function envSum(layers, tMax, N) {
  const ls = LAYER_KEYS.map(k => layerGains(layers[k], tMax, N));
  return ls[0].map(([t, g], i) => [t, g + ls[1][i][1]]);
}

/** Schedule one layer's envelope on a gain AudioParam starting at time t. */
export function scheduleLayer(param, L, t) {
  const g = v => Math.max(db2g(v), FLOOR);
  const A = L.attackMs / 1000, H = L.holdMs / 1000, D = L.decayMs / 1000;
  param.cancelScheduledValues(t);
  param.setValueAtTime(FLOOR, t);
  param.linearRampToValueAtTime(g(L.peakDb), t + A);
  param.linearRampToValueAtTime(g(L.peakDb), t + A + H);
  param.exponentialRampToValueAtTime(g(L.sustainDb), t + A + H + D);
  param.setValueAtTime(g(L.sustainDb), t + A + H + D);   // sit in sustain (loop wraps stay here)
}

/**
 * One playing (or about-to-play) sound. Returned synchronously by
 * SfxEngine.play(); decoding happens in the background and `ready` resolves
 * once the source has started (false if it was stopped first or failed).
 */
export class Voice {
  constructor(engine, spec) {
    this.engine = engine; this.spec = spec; this.key = spec.key || spec.url;
    this.layers = cloneLayers(spec.layers);
    this.loop = !!spec.loop; this.gainDb = spec.gainDb ?? 0;
    this.src = null; this.master = null; this.gains = {}; this.t0 = 0;
    this.started = false; this.stopped = false;
    this.ready = null;
  }
  /** seconds since the envelope started (0 before start) */
  get time() { return this.started && !this.stopped ? this.engine.ctx.currentTime - this.t0 : 0; }
  get playing() { return this.started && !this.stopped; }

  _start(buf) {
    if (this.stopped) return false;
    const ctx = this.engine.ctx;
    const src = ctx.createBufferSource();
    src.buffer = buf; src.loop = this.loop;
    const master = ctx.createGain();
    master.gain.value = db2g(this.gainDb);
    master.connect(this.engine.destination);
    const t = ctx.currentTime + 0.02;
    for (const k of LAYER_KEYS) {
      const gn = ctx.createGain();
      src.connect(gn); gn.connect(master);
      scheduleLayer(gn.gain, this.layers[k], t);
      this.gains[k] = gn;
    }
    src.start(t);
    src.onended = () => { if (!this.stopped) { this.stopped = true; this.engine._forget(this); } };
    this.src = src; this.master = master; this.t0 = t; this.started = true;
    return true;
  }

  /** Live gain on the playing voice (monitor / bus level), in dB. */
  setGain(db) {
    this.gainDb = db;
    if (this.master) {
      const now = this.engine.ctx.currentTime;
      this.master.gain.cancelScheduledValues(now);
      this.master.gain.setTargetAtTime(db2g(db), now, 0.02);
    }
  }

  /** Release: each layer decays toward 0 with tau = release/3; source stops after the slowest tail. */
  stop({ immediate = false } = {}) {
    if (this.stopped) return;
    this.stopped = true;
    this.engine._forget(this);
    if (!this.src) return;   // never started (still decoding) — _start() will see `stopped`
    try {
      const ctx = this.engine.ctx, now = ctx.currentTime;
      let maxR = 0.1;
      for (const k of LAYER_KEYS) {
        const R = immediate ? 0.02 : (this.layers[k].releaseMs || 100) / 1000;
        maxR = Math.max(maxR, R);
        const gn = this.gains[k];
        if (gn) { gn.gain.cancelScheduledValues(now); gn.gain.setTargetAtTime(0, now, Math.max(R / 3, 0.01)); }
      }
      this.src.onended = null;
      this.src.stop(now + maxR + 0.25);
    } catch (e) { /* already stopped */ }
  }
}

/**
 * SfxEngine — plays raw keepers with live automation.
 *
 *   const sfx = new SfxEngine({ base: 'assets/' });
 *   await sfx.loadBank('assets/sfx.json');       // {key: {wav, mp3, loop, layers}}
 *   sfx.setContext(ctx, masterNode);             // share the game's AudioContext (optional)
 *   const v = sfx.play('sfx_patty_sizzle_loop_v03', { loop: true });
 *   v.stop();                                    // release tails play out
 *
 * play() also accepts an explicit spec {url, mp3, loop, layers, gainDb} (the
 * desk does this). Unknown keys warn and return null so callers can code
 * against future keys before the bytes land.
 */
export class SfxEngine {
  constructor({ ctx = null, destination = null, base = '', bank = {} } = {}) {
    this.ctx = ctx; this.destination = destination || (ctx && ctx.destination);
    this.base = base; this.bank = Object.assign({}, bank);
    this.buffers = {}; this.voices = new Set();
  }

  /** Lazily create an AudioContext (call from a user gesture) and resume it. */
  ensure() {
    if (!this.ctx) {
      const AC = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC(); this.destination = this.ctx.destination;
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }
  /** Use an existing context (and optional destination node, e.g. a master gain). */
  setContext(ctx, destination) {
    this.ctx = ctx; this.destination = destination || ctx.destination;
    this.buffers = {};   // decoded buffers belong to a context
  }

  register(key, entry) { this.bank[key] = entry; }
  async loadBank(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('loadBank ' + url + ': ' + r.status);
    const j = await r.json();
    Object.assign(this.bank, j);
    return j;
  }

  /** Fetch + decode (cached). Falls back to `alt` (the mp3 mirror) if the primary fails. */
  async decode(url, alt) {
    if (this.buffers[url]) return this.buffers[url];
    const tryOne = async u => {
      const r = await fetch(u);
      if (!r.ok) throw new Error('fetch ' + u + ': ' + r.status);
      return this.ctx.decodeAudioData(await r.arrayBuffer());
    };
    let buf;
    try { buf = await tryOne(url); }
    catch (e) { if (!alt) throw e; console.warn('[SfxEngine] ' + e.message + ' — trying ' + alt); buf = await tryOne(alt); }
    this.buffers[url] = buf;
    return buf;
  }

  resolve(keyOrSpec) {
    if (typeof keyOrSpec !== 'string') return keyOrSpec;
    const e = this.bank[keyOrSpec];
    if (!e) return null;
    return { key: keyOrSpec, url: this.base + (e.wav || e.url), mp3: e.mp3 ? this.base + e.mp3 : null, loop: !!e.loop, layers: e.layers, gainDb: e.gainDb ?? 0 };
  }

  /** Start a sound; returns a Voice right away (null for an unknown key / no context). */
  play(keyOrSpec, opts = {}) {
    const spec = this.resolve(keyOrSpec);
    if (!spec) { console.warn('[SfxEngine] unknown sound key: ' + keyOrSpec); return null; }
    if (!this.ctx) { console.warn('[SfxEngine] no AudioContext yet (call ensure() from a user gesture)'); return null; }
    const v = new Voice(this, Object.assign({}, spec, opts));
    this.voices.add(v);
    v.ready = this.decode(spec.url, spec.mp3).then(buf => v._start(buf)).catch(e => { console.warn('[SfxEngine] ' + e.message); v.stop(); return false; });
    return v;
  }

  stopAll(opts) { for (const v of Array.from(this.voices)) v.stop(opts); }
  _forget(v) { this.voices.delete(v); }
}

export default SfxEngine;
