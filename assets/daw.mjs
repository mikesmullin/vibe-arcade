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
 * Automation card shape (automation.yaml → bank JSON) — FMOD's AHDSR modulator,
 * one per layer (v1.3: Initial / Final levels + `enabled`, all optional):
 *   layers: { hit:  { enabled, initialDb, attackMs, peakDb, holdMs, decayMs, sustainDb, releaseMs, finalDb },
 *             body: { …same… } }
 * Initial → (attack) → Peak → (hold) → (decay) → Sustain … (release) → Final.
 * Levels: initial/peak/sustain/final (dB, -80 = silence); times: attack/hold/
 * decay/release (ms). A layer with enabled:false is not built. Layers sum
 * (parallel gains on one source) — FMOD's "two tracks, one AHDSR each". A card's monitorDb is the
 * sound's playback gain: the bank carries it as gainDb and play() applies it
 * live on the voice master (never rendered into audio), so the game is
 * exactly as loud as the desk was.
 *
 * SAMPLER REGIONS (v1.7 — one sample per envelope stage; FMOD's multi-instrument idea):
 *   regions: { attack: [a, b], hold: [a, b], decay: [a, b], sustain: [a, b], release: [a, b] }
 * (seconds into the keeper; legacy head/body/tail cards map to attack/sustain/release).
 * play(): attack → hold → decay play once each in order (30 ms crossfades at the joins,
 * missing stages skipped) → SUSTAIN, a seamless loop built from its window (equal-power
 * splice like run.py's make_loop), held until stop() → RELEASE plays once while the loop
 * fades and the envelope's R runs. Only `sustain` is required. Without `regions` the
 * whole keeper plays as before. The AHDSR layers and the param filters sit AFTER the
 * sampler mix, so envelope and samples vary together; the desk syncs each stage knob's
 * ms to its region length when the region is set, so they line up by default.
 *
 * AUDITION (desk use): spec.audition = one region name plays ONLY that region through its
 * envelope stage — attack: Initial→Peak over attackMs; hold: flat at Peak; decay: Peak→
 * Sustain over decayMs; sustain: looped at Sustain until stop(); release: Sustain→Final
 * over releaseMs from t0. spec.auditionLoop = true loops ANY stage region (spliced) and
 * re-triggers its stage curve every pass. Params/lanes apply.
 *
 * LIVE KNOBS (v1.8): voice.updateLayers(layers) / voice.updateParams(params) re-schedule the
 * playing envelope (from its current phase) and re-tune the filters without a restart —
 * the desk calls them on every knob change so tweaks are heard on the running loop.
 *
 * Runtime PARAMETERS (FMOD-style, v1.2): a card may carry
 *   params: { fill: { peak:    { fromHz, toHz, q, gainDb },   // resonance that rises
 *                     lowpass: { fromHz, toHz } } }           // brightness that closes
 * Each param is a 0..1 value the game sets every frame (voice.setParam('fill', t/T));
 * the engine maps it log-linearly onto the filter frequencies in the voice chain
 * src -> [peak] -> [lowpass] -> layer gains. Nothing about the parameter is in
 * the audio file: the keeper is pitch-neutral, the cue is live.
 */

export const VERSION = '1.8.2';
export const LAYER_KEYS = ['hit', 'body'];
export const db2g = db => Math.pow(10, db / 20);
const FLOOR = 1e-4;   // exponential ramps cannot reach 0; this is -80 dB

export const SILENCE_DB = -80;   // = FLOOR
export const DEFAULT_LAYERS = {
  hit:  { enabled: true,  initialDb: SILENCE_DB, attackMs: 5,    peakDb: 0,  holdMs: 500, decayMs: 500, sustainDb: -40, releaseMs: 120, finalDb: SILENCE_DB },
  body: { enabled: false, initialDb: SILENCE_DB, attackMs: 3000, peakDb: -3, holdMs: 0,   decayMs: 200, sustainDb: -3,  releaseMs: 800, finalDb: SILENCE_DB },
};
export const layerOn = L => !L || L.enabled !== false;
export const REGION_KEYS = ['attack', 'hold', 'decay', 'sustain', 'release'];
const LEGACY_REGION = { head: 'attack', body: 'sustain', tail: 'release' };
/** Card regions → the five stage names (legacy head/body/tail accepted); null unless a sustain window exists. */
export function normRegions(r) {
  if (!r) return null;
  const o = {};
  for (const k in r) { const nk = LEGACY_REGION[k] || k; if (REGION_KEYS.includes(nk) && r[k] && r[k].length === 2) o[nk] = [+r[k][0], +r[k][1]]; }
  return o.sustain ? o : null;
}
export const activeLayers = layers => LAYER_KEYS.filter(k => layers[k] && layerOn(layers[k]));

/** log-linear map of a 0..1 parameter onto [from, to] (Hz feel linear in pitch). */
export function paramMap(from, to, v) {
  v = Math.min(1, Math.max(0, +v || 0));
  return from * Math.pow(to / from, v);
}

export function cloneLayers(layers = DEFAULT_LAYERS) {
  const out = {};
  for (const k of LAYER_KEYS) {
    const src = layers[k];
    out[k] = Object.assign({}, DEFAULT_LAYERS[k], src || {});
    if (src && src.enabled === undefined) out[k].enabled = true;   // legacy cards (no flag): every listed layer plays
  }
  return out;
}

/** Numeric twin of the WebAudio schedule: [[t, gain], ...] for one layer. */
export function layerGains(L, tMax, N) {
  const A = L.attackMs / 1000, H = L.holdMs / 1000, D = L.decayMs / 1000;
  const init = Math.max(db2g(L.initialDb ?? SILENCE_DB), FLOOR);
  const peak = Math.max(db2g(L.peakDb), FLOOR), sus = Math.max(db2g(L.sustainDb), FLOOR);
  const out = [];
  if (!layerOn(L)) { for (let i = 0; i <= N; i++) out.push([tMax * i / N, FLOOR]); return out; }
  for (let i = 0; i <= N; i++) {
    const t = tMax * i / N;
    let g;
    if (t < A) g = init + (peak - init) * (A ? t / A : 1);
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

/** Envelope value (gain) of one layer at time t since start — numeric twin of the schedule. */
export function layerGainAt(L, t) {
  if (!layerOn(L)) return FLOOR;
  const A = L.attackMs / 1000, H = L.holdMs / 1000, D = L.decayMs / 1000;
  const init = Math.max(db2g(L.initialDb ?? SILENCE_DB), FLOOR);
  const peak = Math.max(db2g(L.peakDb), FLOOR), sus = Math.max(db2g(L.sustainDb), FLOOR);
  if (t < A) return init + (peak - init) * (A ? t / A : 1);
  if (t < A + H) return peak;
  if (t < A + H + D) return peak * Math.pow(Math.max(sus / peak, FLOOR), D ? (t - A - H) / D : 1);
  return sus;
}

/** Re-schedule the REMAINDER of a layer's envelope from `elapsed` seconds in (lane un-mute mid-play). */
export function scheduleLayerFrom(param, L, now, elapsed) {
  const g = v => Math.max(db2g(v), FLOOR);
  const A = L.attackMs / 1000, H = L.holdMs / 1000, D = L.decayMs / 1000;
  param.cancelScheduledValues(now);
  param.setValueAtTime(Math.max(layerGainAt(L, elapsed), FLOOR), now);
  if (elapsed < A) param.linearRampToValueAtTime(g(L.peakDb), now + (A - elapsed));
  if (elapsed < A + H) param.linearRampToValueAtTime(g(L.peakDb), now + (A + H - elapsed));
  if (elapsed < A + H + D) param.exponentialRampToValueAtTime(g(L.sustainDb), now + (A + H + D - elapsed));
  param.setValueAtTime(g(L.sustainDb), now + Math.max(0, A + H + D - elapsed));
}

/** Cut [a, b] seconds of `buf` into a seamless loop buffer using ONLY the window's own samples:
 *  the window's last `xf` seconds are equal-power crossfaded over its first `xf` seconds, so the
 *  loop is N − X long and its wrap is the blend (v1.8.2 — the old version blended the samples
 *  AFTER the window into the head, which is a hard cut when the window sits in an atlas). */
export function sliceLoop(ctx, buf, a, b, xf = 0.12) {
  const sr = buf.sampleRate, i0 = Math.max(0, Math.round(a * sr)), i1 = Math.min(buf.length, Math.round(b * sr));
  const N = Math.max(2, i1 - i0), X = Math.max(0, Math.min(Math.floor(xf * sr), Math.floor(N / 4)));
  const M = N - X;
  const out = ctx.createBuffer(buf.numberOfChannels, M, sr);
  for (let ch = 0; ch < buf.numberOfChannels; ch++) {
    const src = buf.getChannelData(ch), dst = out.getChannelData(ch);
    dst.set(src.subarray(i0, i0 + M));
    for (let i = 0; i < X; i++) {   // head = the window's own tail fading into its real head
      const t = (i / X) * Math.PI / 2, ci = Math.cos(t), si = Math.sin(t);
      dst[i] = src[i0 + M + i] * ci * ci + dst[i] * si * si;
    }
  }
  return out;
}

/** Gain of one envelope STAGE at phase u (seconds into the stage) — the audition's numeric twin. */
export function stageValueAt(L, stage, u) {
  const g = v => Math.max(db2g(v), FLOOR);
  const init = g(L.initialDb ?? SILENCE_DB), peak = g(L.peakDb), sus = g(L.sustainDb), fin = Math.max(db2g(L.finalDb ?? SILENCE_DB), 0);
  if (stage === 'attack') { const A = L.attackMs / 1000; return u >= A ? peak : init + (peak - init) * (A ? u / A : 1); }
  if (stage === 'hold') return peak;
  if (stage === 'decay') { const D = L.decayMs / 1000; return u >= D ? sus : peak * Math.pow(Math.max(sus / peak, FLOOR), D ? u / D : 1); }
  if (stage === 'sustain') return sus;
  const tau = Math.max((L.releaseMs || 100) / 1000 / 3, 0.01);
  return fin + (sus - fin) * Math.exp(-u / tau);
}

/** Schedule one envelope STAGE on a gain AudioParam from time t, starting at phase u. */
export function scheduleStage(param, L, stage, t, u = 0) {
  const g = v => Math.max(db2g(v), FLOOR);
  const peak = g(L.peakDb), sus = g(L.sustainDb), fin = Math.max(db2g(L.finalDb ?? SILENCE_DB), 0);
  param.setValueAtTime(Math.max(stageValueAt(L, stage, u), FLOOR), t);
  if (stage === 'attack') { const A = L.attackMs / 1000; if (u < A) param.linearRampToValueAtTime(peak, t + (A - u)); }
  else if (stage === 'decay') { const D = L.decayMs / 1000; if (u < D) { param.exponentialRampToValueAtTime(sus, t + (D - u)); param.setValueAtTime(sus, t + (D - u)); } }
  else if (stage === 'release') param.setTargetAtTime(fin, t, Math.max((L.releaseMs || 100) / 1000 / 3, 0.01));
}

/** Schedule one layer's envelope on a gain AudioParam starting at time t. */
export function scheduleLayer(param, L, t) {
  const g = v => Math.max(db2g(v), FLOOR);
  const A = L.attackMs / 1000, H = L.holdMs / 1000, D = L.decayMs / 1000;
  param.cancelScheduledValues(t);
  param.setValueAtTime(g(L.initialDb ?? SILENCE_DB), t);
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
    this.params = spec.params || null; this.paramVals = {}; this.filters = {};
    this.regions = normRegions(spec.regions);   // sampler mode when a sustain window exists
    const audR = spec.regions ? (Object.assign({}, spec.regions, normRegions(Object.assign({ sustain: [0, 0.01] }, spec.regions)) || {})) : {};
    const aud = LEGACY_REGION[spec.audition] || spec.audition;
    this.audition = aud && REGION_KEYS.includes(aud) && audR[aud] ? aud : null;   // single-region audition (desk)
    this.auditionRegion = this.audition ? audR[aud] : null;
    this.auditionLoop = !!(this.audition && (spec.auditionLoop || this.audition === 'sustain'));
    this.sampler = null;   // {S, gains, mix, headLen, bodyLen, bodyStart, tailLen, xf, buf}
    // lanes: per automation lane, active (true) or bypassed (false = raw through that stage).
    // Keys: each layer name + each param name. Missing = active.
    this.lanes = Object.assign({}, spec.lanes || {});
    for (const k in (this.params || {})) this.paramVals[k] = spec.paramInit && spec.paramInit[k] != null ? spec.paramInit[k] : 0;
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
    const master = ctx.createGain();
    master.gain.value = db2g(this.gainDb);
    master.connect(this.engine.destination);
    const t = ctx.currentTime + 0.02;
    // source: whole keeper, or the sampler (head once -> body loop -> tail on stop)
    let src, chain;
    if (this.audition) {
      const r = this.auditionRegion, len = Math.max(0.005, r[1] - r[0]);
      src = ctx.createBufferSource();
      if (this.auditionLoop) { src.buffer = sliceLoop(ctx, buf, r[0], r[1], this.spec.loopXfade ?? 0.12); src.loop = true; src.start(t); }
      else { src.buffer = buf; src.start(t, r[0], len); }
      this.sampler = { S: { [this.audition]: src }, gains: {}, mix: null, stages: [], susStart: t, susLen: len, relLen: 0, xf: 0.03, buf, auditionLen: this.auditionLoop ? src.buffer.duration : len };
      chain = src;
    } else if (this.regions) {
      const R = this.regions, xf = 0.03, mix = ctx.createGain();
      const len = r => Math.max(0, r[1] - r[0]);
      const S = {}, gains = {}, stages = [];
      let tCur = t, prev = null;
      for (const k of ['attack', 'hold', 'decay']) {   // one-shots, in order, crossfaded at the joins
        if (!R[k] || len(R[k]) <= 0.005) continue;
        const L = len(R[k]), at = prev ? tCur - xf : tCur;
        const sN = ctx.createBufferSource(); sN.buffer = buf;
        const g = ctx.createGain(); sN.connect(g); g.connect(mix);
        if (prev) { g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(1, at + xf); }
        g.gain.setValueAtTime(1, Math.max(at, at + L - xf)); g.gain.linearRampToValueAtTime(0, at + L);
        sN.start(at, R[k][0], L);
        S[k] = sN; gains[k] = g; stages.push({ k, at, len: L }); prev = k; tCur = at + L;
      }
      const susAt = prev ? tCur - xf : tCur;
      const susBuf = sliceLoop(ctx, buf, R.sustain[0], R.sustain[1], this.spec.loopXfade ?? 0.12);
      S.sustain = ctx.createBufferSource(); S.sustain.buffer = susBuf; S.sustain.loop = this.loop;
      gains.sustain = ctx.createGain(); S.sustain.connect(gains.sustain); gains.sustain.connect(mix);
      if (prev) { gains.sustain.gain.setValueAtTime(0, susAt); gains.sustain.gain.linearRampToValueAtTime(1, susAt + xf); }
      S.sustain.start(susAt);
      this.sampler = { S, gains, mix, stages, susStart: susAt, susLen: susBuf.duration, relLen: R.release ? len(R.release) : 0, xf, buf };
      src = S.sustain; chain = mix;
    } else {
      src = ctx.createBufferSource();
      src.buffer = buf; src.loop = this.loop;
      chain = src;
    }
    // parameter filter chain (only built when the card has params)
    for (const name in (this.params || {})) {
      const P = this.params[name], v = this.paramVals[name] || 0;
      if (P.peak) {
        const f = ctx.createBiquadFilter(); f.type = 'peaking';
        f.frequency.value = paramMap(P.peak.fromHz, P.peak.toHz, v); f.Q.value = P.peak.q ?? 5; f.gain.value = P.peak.gainDb ?? 8;
        chain.connect(f); chain = f; this.filters[name + '.peak'] = f;
      }
      if (P.lowpass) {
        const f = ctx.createBiquadFilter(); f.type = 'lowpass';
        f.frequency.value = paramMap(P.lowpass.fromHz, P.lowpass.toHz, v); f.Q.value = P.lowpass.q ?? 0.7;
        chain.connect(f); chain = f; this.filters[name + '.lowpass'] = f;
      }
    }
    for (const k of activeLayers(this.layers)) {
      const gn = ctx.createGain();
      chain.connect(gn); gn.connect(master);
      this.gains[k] = gn;
      if (!this.audition) scheduleLayer(gn.gain, this.layers[k], t);
    }
    if (this.audition) { this._scheduleAudition(t, 0); if (this.audition === 'release') this.releaseAt = t; }
    if (!this.regions && !this.audition) src.start(t);
    if (Object.values(this.lanes).some(v => v === false)) { this.src = src; this.t0 = t; this.started = true; this.setLanes(this.lanes); }
    src.onended = () => { if (!this.stopped) { this.stopped = true; this.engine._forget(this); } };
    this.src = src; this.master = master; this.t0 = t; this.started = true;
    return true;
  }

  /** Audition: (re)schedule the stage curve on every layer from `now`, starting at phase u; looped
   *  auditions re-trigger the curve at every pass for the next ~2 minutes (a later update re-plans). */
  _scheduleAudition(now, u) {
    const len = this.sampler.auditionLen, passes = this.auditionLoop ? Math.min(600, Math.ceil(120 / Math.max(len, 0.05))) : 1;
    for (const k of Object.keys(this.gains)) {
      const p = this.gains[k].gain, L = this.layers[k];
      p.cancelScheduledValues(now);
      scheduleStage(p, L, this.audition, now, u);
      for (let n = 1; n < passes; n++) scheduleStage(p, L, this.audition, now + n * len - u, 0);
    }
  }

  /** Live: new layer knobs → re-schedule the running envelope from its current phase (no restart). */
  updateLayers(layers) {
    this.layers = cloneLayers(layers);
    if (!this.src) return;
    const ctx = this.engine.ctx, now = ctx.currentTime + 0.005;
    if (this.audition) {
      const len = this.sampler.auditionLen, t = Math.max(0, now - this.t0);
      this._scheduleAudition(now, this.auditionLoop ? t % Math.max(len, 1e-3) : Math.min(t, len));
      return;
    }
    for (const k of Object.keys(this.gains)) {
      const p = this.gains[k].gain, L = this.layers[k];
      if (this.lanes[k] === false) continue;
      p.cancelScheduledValues(now);
      if (this.stopped) { const cur = Math.max(stageValueAt(L, 'release', Math.max(0, now - (this.releaseAt ?? now))), FLOOR); p.setValueAtTime(cur, now); p.setTargetAtTime(Math.max(db2g(L.finalDb ?? SILENCE_DB), 0), now, Math.max((L.releaseMs || 100) / 1000 / 3, 0.01)); }
      else scheduleLayerFrom(p, L, now, Math.max(0, now - this.t0));
    }
  }

  /** Live: new filter settings → re-tune the parameter filters at the current param values. */
  updateParams(params) {
    this.params = params || null;
    if (!this.src || !this.params) return;
    const ctx = this.engine.ctx, now = ctx.currentTime, tau = 0.02;
    for (const name in this.params) {
      const P = this.params[name], v = this.paramVals[name] || 0, on = this.lanes[name] !== false;
      const pk = this.filters[name + '.peak'], lp = this.filters[name + '.lowpass'];
      if (pk && P.peak) { pk.frequency.cancelScheduledValues(now); pk.frequency.setTargetAtTime(paramMap(P.peak.fromHz, P.peak.toHz, v), now, tau); pk.Q.setTargetAtTime(P.peak.q ?? 5, now, tau); pk.gain.setTargetAtTime(on ? (P.peak.gainDb ?? 8) : 0, now, tau); }
      if (lp && P.lowpass) { lp.frequency.cancelScheduledValues(now); lp.frequency.setTargetAtTime(on ? paramMap(P.lowpass.fromHz, P.lowpass.toHz, v) : 20000, now, tau); }
    }
  }

  /** Where in the SOURCE FILE the voice is right now (seconds), for a waveform playhead. */
  sourcePos() {
    if (!this.started) return 0;
    const t = this.time, R = this.regions, sm = this.sampler;
    if (this.audition) { const r = this.auditionRegion, len = sm.auditionLen; return r[0] + (this.auditionLoop ? t % Math.max(len, 1e-3) : Math.min(t, len)); }
    if (!R || !sm) return this.src && this.src.buffer && this.loop ? t % this.src.buffer.duration : t;
    const now = this.engine.ctx.currentTime;
    if (sm.relAt !== undefined) { const u = now - sm.relAt; return u < sm.relLen ? R.release[0] + u : R.release[1]; }
    for (const st of sm.stages) if (now < st.at + st.len) return R[st.k][0] + Math.max(0, now - st.at);
    const u = Math.max(0, now - sm.susStart);
    return R.sustain[0] + (this.loop ? u % Math.max(sm.susLen, 1e-3) : Math.min(u, sm.susLen));
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

  /** Set a 0..1 runtime parameter (e.g. 'fill'); safe before start (applied at _start). */
  setParam(name, v, tau = 0.05) {
    if (!this.params || !this.params[name]) return false;
    v = Math.min(1, Math.max(0, +v || 0));
    this.paramVals[name] = v;
    const P = this.params[name], ctx = this.engine.ctx, now = ctx ? ctx.currentTime : 0;
    const pk = this.filters[name + '.peak'], lp = this.filters[name + '.lowpass'];
    if (pk) { pk.frequency.cancelScheduledValues(now); pk.frequency.setTargetAtTime(paramMap(P.peak.fromHz, P.peak.toHz, v), now, tau); }
    if (lp && this.lanes[name] !== false) { lp.frequency.cancelScheduledValues(now); lp.frequency.setTargetAtTime(paramMap(P.lowpass.fromHz, P.lowpass.toHz, v), now, tau); }
    return true;
  }
  getParam(name) { return this.paramVals[name] ?? null; }
  laneActive(name) { return this.lanes[name] !== false; }

  /** Live mute/solo resolution from the mixer: {laneName: active}. A bypassed AHDSR layer
   *  becomes flat unity gain (raw) — unless every layer is bypassed, then only the first
   *  passes so raw is heard exactly once; a bypassed param lane flattens its filters.
   *  Un-bypassing re-schedules the remainder of the envelope from where it would be. */
  setLanes(active) {
    Object.assign(this.lanes, active);
    if (!this.src) return;
    const ctx = this.engine.ctx, now = ctx.currentTime, tau = 0.02, elapsed = now - this.t0;
    const keys = Object.keys(this.gains), allOff = keys.length && keys.every(k => this.lanes[k] === false);
    keys.forEach((k, i) => {
      const gn = this.gains[k].gain;
      if (this.lanes[k] === false) { gn.cancelScheduledValues(now); gn.setTargetAtTime(allOff && i > 0 ? FLOOR : 1, now, tau); }
      else scheduleLayerFrom(gn, this.layers[k], now + tau, Math.max(0, elapsed + tau));
    });
    for (const name in (this.params || {})) {
      const P = this.params[name], on = this.lanes[name] !== false, v = this.paramVals[name] || 0;
      const pk = this.filters[name + '.peak'], lp = this.filters[name + '.lowpass'];
      if (pk) { pk.gain.cancelScheduledValues(now); pk.gain.setTargetAtTime(on ? (P.peak.gainDb ?? 8) : 0, now, tau);
                pk.frequency.cancelScheduledValues(now); pk.frequency.setTargetAtTime(paramMap(P.peak.fromHz, P.peak.toHz, v), now, tau); }
      if (lp) { lp.frequency.cancelScheduledValues(now); lp.frequency.setTargetAtTime(on ? paramMap(P.lowpass.fromHz, P.lowpass.toHz, v) : 20000, now, tau); }
    }
  }

  /** Release. Layers ease toward their Final level with tau = release/3 starting NOW. Sampler: a
   *  TAIL region plays once from now (30 ms crossfade from the body) under that release — the tail
   *  is the release stage, so the human aligns tail length and the release knob by hand; without
   *  a tail the body keeps looping through the release. Sources always stop after the slowest end;
   *  a Final above silence only sets the level the release curve lands on before the cut. */
  stop({ immediate = false } = {}) {
    if (this.stopped) return;
    this.stopped = true;
    this.engine._forget(this);
    if (!this.src) return;   // never started (still decoding) — _start() will see `stopped`
    try {
      const ctx = this.engine.ctx, now = ctx.currentTime;
      const keys = Object.keys(this.gains);
      const Rmax = immediate ? 0.02 : Math.max(0.1, ...keys.map(k => (this.layers[k].releaseMs || 100) / 1000));
      let relAt = now, endAt = now + Rmax + 0.25;
      const sm = this.sampler;
      if (sm && this.audition) {   // audition: body = normal release, head/tail = already time-limited, just fade
        endAt = now + Rmax + 0.25;
      } else if (sm) {
        const R = this.regions;
        for (const st of sm.stages) { const g = sm.gains[st.k].gain; g.cancelScheduledValues(now); g.setTargetAtTime(0, now, sm.xf / 3); }   // any one-shot still sounding fades
        if (R.release && sm.relLen > 0.005 && !immediate) {
          const rel = ctx.createBufferSource(); rel.buffer = sm.buf;
          const g = ctx.createGain(); rel.connect(g); g.connect(sm.mix);
          g.gain.setValueAtTime(0, now); g.gain.linearRampToValueAtTime(1, now + sm.xf);
          rel.start(now, R.release[0], sm.relLen);
          sm.S.release = rel; sm.relAt = now;
          sm.gains.sustain.gain.cancelScheduledValues(now); sm.gains.sustain.gain.setTargetAtTime(0, now, sm.xf / 3);
          relAt = now;                                            // the release region IS the R stage: starts now, the knob's length
          endAt = Math.max(endAt, now + sm.relLen + 0.05);
        } else {                                                // no release sample: the sustain loop plays on through R, then fades
          sm.gains.sustain.gain.cancelScheduledValues(now + Rmax);
          sm.gains.sustain.gain.setTargetAtTime(0, now + Rmax, immediate ? 0.005 : sm.xf / 3);
          endAt = now + Rmax + sm.xf + 0.25;
        }
      }
      for (const k of keys) {
        const L = this.layers[k];
        const R = immediate ? 0.02 : (L.releaseMs || 100) / 1000;
        const fin = immediate ? 0 : Math.max(db2g(L.finalDb ?? SILENCE_DB), 0);
        const gn = this.gains[k].gain;
        gn.cancelScheduledValues(relAt);
        if (relAt > now) gn.setValueAtTime(Math.max(db2g(L.sustainDb), FLOOR), relAt);   // hold sustain until the release starts
        gn.setTargetAtTime(fin, relAt, Math.max(R / 3, 0.01));
      }
      this.releaseAt = relAt;
      this.src.onended = null;
      // sources ALWAYS end after the release (+ release region): a Final above silence only sets
      // where the release curve lands before the cut — Stop must stop (human's ruling 2026-09-06)
      if (sm) { for (const k in sm.S) { try { sm.S[k].stop(endAt); } catch (e) {} } }
      else this.src.stop(endAt);
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
 * play() also accepts an explicit spec {url, mp3, loop, layers, gainDb, params, lanes, regions} (the
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
    return { key: keyOrSpec, url: this.base + (e.wav || e.url), mp3: e.mp3 ? this.base + e.mp3 : null, loop: !!e.loop, layers: e.layers, gainDb: e.gainDb ?? 0, params: e.params || null, regions: e.regions || null };
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
