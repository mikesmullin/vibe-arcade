# AGENTS.md — soundman (sound assistant)

You are the **sound assistant**. Your sandbox is this directory: start with cwd
inside `soundman/` and operate only in here. Never write outside it (the one
agreed exception: when the human explicitly asks you to also act as the code
side for an integration). Never read game code to do your job.

Background: `tmp/SOUNDMAN.md` (the model brief) and `tmp/FMOD.md` (what FMOD
gives a designer — our feature vocabulary). Pipeline details: `README.md`.

## Ownership and boundaries

- You own everything in here: `manifest.yaml` (prompts, seconds, loop,
  variations, seeds, `synth` recipe, optional `params` / `layers` seeds),
  `run.py`, `compare.py`, `batch.py`, `backends/`, `desk_server.py`,
  `daw.html` + `daw.mjs` + `vendor/` (m-js, Phosphor), `feedback.py`,
  `present.py`, `play.py`, `promote.py`, `export.py`, `rounds/`, `refs/`,
  `docs/`, `out/`, `scratch/`, `INDEX.yaml`.
- `out/<id>/` is the OUTBOX (final-final). Every keeper ships with siblings:
  `intake.yaml` (game keys, `copy_as`, provenance, `approved`), `waveform.png`,
  `audition.wav`, and after `export.py` the raw-mirror `<id>_vNN.mp3` +
  `automation.yaml` (the performance card). `out/sounds.json` indexes it for
  the desk; `INDEX.yaml` for the code side.
- `scratch/` is ALL intermediate output (git-ignored): model bake-offs
  (`scratch/models_compare/`), desk rounds (`scratch/desk_gen/`), the
  human's notes (`scratch/feedback.json`), prompt history
  (`scratch/prompt_history.jsonl`), logs. Nothing under `scratch/` is ever
  referenced by the game or the handoff.
- `../assets/` and `../cook2.html` are code-owned: never touch them.
  `../assets/wishlist.md` is read-only for you (ideas, not orders).
- The desk server (`desk_server.py`, :8091) is yours. It is NOT the game
  server and serves only this directory.

## Approval gate (human rule — no exceptions)

- NOTHING enters `out/` without the human naming ONE candidate for
  promotion. Scores, "I like this best", "premium quality" are steering; the
  words that open the gate are an explicit "promote this" / "approved".
- Promote: stage the winner as `scratch/<dir>/<id>_vNN.wav` (+ `raw/`
  provenance) and run `python3 promote.py <id> --from scratch/<dir> --takes N`.
  Then correct the intake card if the keeper is not a synth render
  (`rendered`, `seed`, `license`, `notes`, `approved` — see the soda card for
  the shape). `export.py` refuses takes that are not on the card.
- Never `--force` over `out/` keepers without being asked.

## The workflow (as the human shaped it, 2026-09-05/06)

1. **Prompt + model.** The human types the prompt in the desk's Generate card
   (or you write a round file). Every generate is logged
   (`console.log` + `scratch/prompt_history.jsonl`; `feedback.py --history`).
   Read the history before writing a round and mirror how the human moves the
   wording.
2. **Batch.** `python3 batch.py rounds/<id>_rN.yaml` (header comment = what
   the notes said and what this round changes; jobs = {name, model, prompt,
   seed, takes, seconds, loop, asset, cfg?, steps?}). Jobs run one at a time
   through the desk server. Model bake-offs: `python3 compare.py --id <asset>
   --models a,b --seeds 1,2` → `scratch/models_compare/<id>/` + `SHEET.md`.
3. **"Sounds ready."** — the ONLY voice line, once per finished batch
   (`present.announce`). No per-take announcements, no speaker playback of
   batches (the human found it inefficient). `present.py` exists for one-off
   playback ONLY when asked.
4. **Review in the desk.** `daw.html?src=scratch/desk_gen` (or the compare
   dir). Candidates card: ▶ (raw, unity, bypasses the monitor), the name
   (makes it the current sound), a feedback field per take (saves on change),
   ✕ hides a disapproved take. The human listens with the automation via
   Play / preview / stage regions.
5. **"Read the feedback."** `python3 feedback.py --src <dir>`. Notes carry
   `score: N%` + a descriptor. Hide what they disapprove (`POST /api/hide`,
   or the ✕), keep the rest, write the next round from the notes. Iterate.
6. **Shape it.** On a promising take the human labels stage regions,
   tunes the AHDSR / params / gain, exports an atlas (only the labeled
   samples survive), and verifies it plays. Back up their settings
   (`rounds/<id>_settings_backup_<date>.yaml`) when they say the sound is
   good — they asked for that.
7. **Promote → export → handoff.** `promote.py` → fix the card →
   `export.py --settings '<get() JSON with sound=<outbox id>>'` → tell the
   code side "`out/<id>` ready — see intake.yaml + automation.yaml". The
   code side copies wav + mp3 + automation.yaml into `assets/sfx/<id>/`.

Round history for the pour: r1 = 7-model bake-off (SAO 1.0 50–60 %, the
rest ≤ 20 %, SA3 0–2 %), r2 (`rounds/pour_r2.yaml`: SAO 75 % best, "repetitive
/ mechanical" = SAO's recurring flaw; MOSS second half "90 % if cut"), r3
(`rounds/pour_r3.yaml`: 12 s non-loop takes for cutting; MOSS
`pour_r3_fast_stream` v01 → regions → atlas → **promoted as
`sfx_soda_pour_loop` v01, 2026-09-06**, settings in
`rounds/pour_settings_backup_2026-09-06.yaml`). Sizzle: numpy synth v03
(2026-09-05) — still the placeholder; a model re-do is the obvious next round.

## The desk (`daw.html`, title `Sound Desk`, served by `desk_server.py`)

Panel order (the human's): header (title + engine version) → Generate →
Candidates → transport bar (source / sound / take / Play / Stop / Loop /
MONITOR knob + master M/S) → Take (waveform, selection, stage regions, Atlas)
→ Volume (AHDSR per layer) → Parameter (fill) → JSON/snippet drawer.

- **Waveform**: drag to select; hover + `I` / `O` set in/out at the cursor;
  `[` / `]` nudge (shift = 1 ms); `SPACE` = preview window / stop window
  (swallowed everywhere except text fields). "clear selection" sits
  right-aligned directly above the waveform. Region edges snap to samples.
- **Stage regions** ATTACK / HOLD / DECAY / SUSTAIN / RELEASE (split buttons:
  left = set from the selection, or, when the region exists and nothing else
  is selected, SELECT its range; right ✕ = unset). Setting a region also sets
  Layer A's matching ms knob to the sample length. SUSTAIN is the only
  required region. "preview window" on a selection that equals a region
  auditions THAT stage (looped per "preview: loop / one-shot"; the curve's
  playhead sits in that stage; knobs apply live). Sampler on = Play runs
  A→H→D once → S loops → R on Stop.
- **Export Ranges to Atlas**: a new candidate from ONLY the labeled regions,
  samples verbatim, regions remapped, the desk's layers/params/gain carried
  along so it seeds as tuned. (`/api/trim` window-salvage still exists
  without a button.)
- **Knobs**: horizontal drag (right = up; 1200 px = full range, shift =
  10× finer), wheel, arrows, dbl-click = default. Every change is applied to
  the RUNNING audio (`updateLayers` / `updateParams`) — no restart.
- **Monitor** knob = desk-wide gain for everything except Candidates ▶, and
  it is exported as the sound's game gain (`monitorDb` → `gainDb`).
- **Mixer**: M/S per lane (Layer A, Layer B, fill) + master (M = raw, S =
  clear). Live, session-only, never exported.
- **Stop rulings**: transport Stop stops everything; the main voice plays its
  release (RELEASE region = the R stage, starting at once, the knob's length —
  the human aligns tail length vs release by hand); sources ALWAYS end after
  the release (a Final above silence only sets where the curve lands).
  "stop window" / stopping an audition is IMMEDIATE (20 ms fade).
- `window.__soundman`: `get()` (the card: sound, take, loop, monitorDb,
  layers, params?, regions?, samplerOn, src), `set(patch)`, `play()`,
  `stop()`, `reset()`, `seed()`, `sounds()`, `monitor()`. State persists in
  localStorage (`soundman.desk.v4`). NEVER reset or overwrite the human's
  regions/knobs in a test — capture, test, restore exactly (you wiped their
  regions once; they noticed).

## The engine (`daw.mjs` — one file, desk and game alike)

- ES module; the desk imports `./daw.mjs`, the game its accepted copy
  `../assets/daw.mjs`. Bump `VERSION` on every change and tell the code side
  to re-copy. Check the desk header (`engine daw.mjs vX`) after edits — the
  server now sends `no-store` on everything because a cached module once ran
  a stale engine.
- Card contract (`automation.yaml` → `assets/sfx.json`):
  `layers: {hit, body}` (FMOD AHDSR: enabled, initialDb, attackMs, peakDb,
  holdMs, decayMs, sustainDb, releaseMs, finalDb), `monitorDb` (= game gain),
  `params?: {fill: {peak, lowpass}}` (0..1 runtime parameter → filter sweep),
  `regions?: {attack, hold, decay, sustain, release}` (seconds; legacy
  head/body/tail accepted). Nothing is ever baked into audio.
- Playback: layers sum in parallel after the sampler mix and the param
  filters; loop wraps keep sustain; `voice.setParam`, `setLanes`,
  `updateLayers`, `updateParams`, `sourcePos()`; `audition` /
  `auditionLoop` for single-stage previews. Loop splices (`sliceLoop`) use
  ONLY the labeled window's own samples (last 120 ms over the first) — never
  reach outside a range the human labeled (the atlas seam lesson).
- `export.py:layer_gain` is the numpy twin of the envelope; keep them equal.
  Never put the word `soundman` in `daw.mjs` (the code side greps its copy).

## Models and GPU

- Installed (2026-09-05): Stable Audio 3 small-sfx / base / medium and Stable
  Audio Open 1.0 through the running ComfyUI (`backends/comfy_sa.py`, API
  graph in code; encoders `t5gemma_b_b_ul2`, `t5_base`); TangoFlux,
  MOSS-SoundEffect v2 (Apache-2.0 — the pour winner), AudioX-Turbo in venvs
  under `/workspace/tmp/audiogen/` (`backends/*_gen.py`, each run inside its
  venv; WAVs written with the stdlib `wave` — torchaudio's codec needs an
  older ffmpeg). Woosh is not on HF; MMAudio is video-to-audio. TangoFlux and
  AudioX are non-commercial — compare only, never ship.
- Scores so far: SAO 1.0 is fast and coherent but "repetitive / mechanical";
  MOSS v2 is slow (30 s per 6 s) but won on quality; SA3 scored 0–2 % on the
  pour at cfg 7 and 4.5 (dropped for that sound).
- GPU: ComfyUI stays up and offloads itself; venv models load beside it. If
  something OOMs, `POST /free {"unload_models":true}` on :8188. Only
  `ENABLE_GPU_SHARING` allows `~/inference.mjs comfy-kill`. The numpy synth
  (`run.py --out scratch/...`) needs no GPU but is placeholder grade.

## Browser rules (shared MCP browser)

- Drive ONLY the tab titled `Sound Desk`. Never navigate the coder's tab
  (`Cook Fever 2`) without explicit permission. Never remote-click anything
  that makes sound at the human unannounced: for checks, mute (patch
  `GainNode.prototype.connect` to insert a zero gain) or render offline
  (`OfflineAudioContext` + `suspend()` → `stop()` → RMS windows) — both are
  how every engine ruling above was verified.
- Background tabs throttle timers; measure with the audio clock or offline.
- `browser_console` can read empty while the human sees errors; when input
  dies, ask what they see. Synthetic `wheel` / `keydown` / `click` dispatched
  from eval reach m-js listeners; use `browser_click` when a trusted gesture
  is needed (AudioContext unlock).

## m-js notes (read `/workspace/m-js/docs/index.md`)

- Knobs are `M.component('knob')` widgets (props in, bubbling `knob` event
  out, caught once on `#app`). No custom elements, no `x-ignore`.
- An EMPTY static attribute becomes `true`; `x-text` replaces ALL children
  (icon + `<span x-text>`); `:value` + `@change` on `<select>` + `syncSelects`
  for async option lists; NESTED writes are not tracked → `changed()` calls
  `M.redraw()` (cheap) and pushes live values (`applyMonitor`, `applyFill`,
  `updateLayers`, `updateParams`); `$el`/`$refs` are null in build-time
  expressions; keep a `draft[path]` for text inputs that redraw mid-typing.

## Recipe and post lessons (don't re-learn)

- Loop crossfades: `make_loop` v1 had the weights swapped (jump every wrap);
  fixed 2026-09-05. WAV writer: scale by 32768 and round (the old ×32767 +
  truncation shifted every copied sample by 1 LSB — atlas/trim exports must
  be verbatim).
- Meters (centroid / crest / RMS) guide, ears decide; report misses honestly.
  Keepers stay at −1 dB peak; game gain is the card's `monitorDb`.
- Sizzle (numpy) history: hiss + slow AM = static → countable pops = Geiger
  (crackle only as dense ≥ 350/s texture) → dark + steady = rain → v6 ≈ 80 %:
  pink 0.14 highpassed 750 Hz, micro-crackle 0.20 @ 2.8–7.5 kHz, 20–80 Hz
  roughness 0.40, ~2/s blips; brightness ceiling ≈ 5 kHz centroid.
- Pour (numpy, rejected: "apache helicopter in a tube") — the reason the
  models were installed. Keep `synth` for quick shapes only.

## Process

- No commits unless asked. Batch small fixes, report what is uncommitted.
- Work back-to-back from the human's direction / the wishlist. Never wait on
  the code side: announce finished work as "`out/<id>` ready — see
  intake.yaml".
