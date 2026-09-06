# soundman — a prop factory for diner-game audio

This folder turns a **list of game sounds** into a **folder of WAV one-shots and
loops**, the same way `artman/` turns a list into sprites. You describe each sound
once in [`manifest.yaml`](manifest.yaml), run [`run.py`](run.py), and the keepers pop
out in [`out/`](out/). Spec: [`../tmp/SOUNDMAN.md`](../tmp/SOUNDMAN.md).

## What is here

| Path | What |
|---|---|
| [`manifest.yaml`](manifest.yaml) | The SOUND manifest (sound-owned): prompt per asset, seconds, loop flag, variation count, seeds, synth recipe. The code side keeps its own ledger at `../assets/manifest.yaml` — never edit that file from here. |
| [`run.py`](run.py) | The runner: renders each asset (synth backend today, ComfyUI backend when a model lands), posts in ffmpeg, writes keepers. |
| [`audition.py`](audition.py) | Cross-id mix for review: one keeper per `out/<id>/` concatenated with gaps into `scratch/audition_mix.wav` (the audio contact sheet; cf. art's `sheet.py`). |
| [`play.py`](play.py) | One-shot wav playback through local speakers, pure Python (ctypes into libpulse-simple, same pa_simple API the voice daemon uses). No player binary. |
| [`daw.html`](daw.html) | Shared sound-design desk (title `SoundMan Agent`): two-layer ADSR (HIT + BODY) with DAW knobs, live curve canvas, automation JSON + draft coder snippet. Served by the desk server `:8091`. |
| [`daw.mjs`](daw.mjs) | `SfxEngine` — the shared ES6 playback lib: raw keeper + live two-layer ADSR (the reference envelope; `export.py:layer_gain` is its numpy twin). `daw.html` imports it; the game imports its accepted copy `assets/daw.mjs` and the bank `assets/sfx.json`. Bump `VERSION` on change. |
| [`present.py`](present.py) | The ritual: voice TTS announce (`Sound's done: <id>`, blocking via daemon WAV + local playback) then one keeper via `play.py` (`--take N` picks, `--all` plays the mix). `present.py <id> [--take N] [--all] [--bg] [--voice NAME]`. |
| [`export.py`](export.py) | Desk JSON + approved keeper → raw-mirror `<id>_vNN.mp3` (NO automation baked — game applies layers live) + `automation.yaml` (settings, command, sha256). Refuses unapproved takes. Deterministic: same keeper + ffmpeg → same bytes. |
| [`promote.py`](promote.py) | Approval gate: copies HUMAN-APPROVED takes from a scratch render dir into `out/`, rebuilds audition/waveform/intake, updates INDEX + sounds.json. Nothing enters the outbox without named-take approval. |
| [`refs/`](refs/) | Source inputs (reference recordings, style notes) — NOT scratch. Empty until needed. |
| [`out/<id>/`](out/) | Final-final outbox, e.g. `out/sfx_patty_sizzle_loop/`: keeper WAVs plus siblings `intake.yaml` (handoff card) + `waveform.png` (proof picture) + `audition.wav` (keepers back-to-back). Pre-post renders and exact prompts live in `out/<id>/raw/` (git-ignored). |
| [`docs/`](docs/) | Review notes. Empty until needed. |
| [`scratch/`](scratch/) | ALL intermediate/temp output (git-ignored): prompt explores, level tests, cross-id mixes. Never referenced by the game or the handoff. |
| [`INDEX.yaml`](INDEX.yaml) | Index of finished outbox ids (files + game keys). |
| [`AGENTS.md`](AGENTS.md) | Guide for the sound assistant working in this folder (sandbox scope, GPU rules, outbox contract). |

## Why these models (from SOUNDMAN.md)

- **Daily driver: Stable Audio 3.0 Small SFX.** Built for effects, not songs. Open
  weights, licensed training data, Community License. Variable length to ~2 min. Runs
  on CPU; instant on a 5090. Day-0 ComfyUI support. Covers ~90% of the library:
  sizzle, slap, ding, coin, scrape, pops, lid, dispense.
- **Fallback: Stable Audio Open 1.0** (44.1 kHz stereo, ~47 s) when a 3.0 prompt is mushy.
- **Second opinion: Woosh (Sony) / TangoFlux** when Small SFX is too generic.
- **Sync-only: AudioX-Turbo / MMAudio** (video-to-audio) — only when a flip/animation
  clip must lock to picture, not for a one-shot library.
- **Beds: MOSS-SoundEffect** (Apache 2.0) for 10–30 s kitchen beds / diner room tone.
- Skip MusicGen / ACE-Step / Bark for SFX — wrong tool for `sfx_patty_sear_01.wav`.

**Status 2026-09-06: none of these are installed** (`diffusion_models/` holds only the
art klein + minimax video files, `checkpoints/` is empty, no audio custom nodes), so
the **synth backend is the production path**: procedural numpy recipes (filtered-noise
sizzle beds + Poisson crackle + transient thumps + sine pings) that render the same
manifest fields today. Diffusion re-renders later keep the same ids/keys — the game
never knows the backend changed.

## Backends

- `synth` (default, works now): numpy recipes in `run.py`, post in ffmpeg, peak
  normalize in numpy. Deterministic per seed; variations spread density/AM so the
  game can round-robin without machine-gun repetition.
- `comfy` (specified, not installed): will build the Stable Audio API graph in code
  and POST it to `/prompt` exactly like `artman/run.py` does for klein — no saved
  workflow JSON. `run.py --backend comfy` exits with install instructions until then.

## Post (same standard for both backends)

- high-pass ~80 Hz (UI; sizzle keeps 80 Hz too — rumble lives above it),
- fade last 8–15 ms on one-shots so they don't click (**loops skip the fade**; the
  crossfade splice is the click fix),
- peak-normalize to −1 dB, then in-game gain per bus (code side).

## Usage

```sh
cd /workspace/vibe-arcade/soundman
python3 run.py                                # everything in manifest.yaml
python3 run.py sfx_patty_sizzle_loop          # just this id
python3 run.py --force sfx_patty_sizzle_loop  # regenerate
python3 run.py --out scratch/practice sfx_ui_coin   # explore, never referenced
python3 run.py --seed-offset 7 sfx_patty_burn       # quick re-roll
python3 audition.py                           # cross-id mix -> scratch/audition_mix.wav
python3 present.py sfx_patty_sizzle_loop        # TTS announce (blocking) + first keeper (1x)
python3 present.py sfx_patty_sizzle_loop --bg   # TTS blocks, sfx detached in background
python3 play.py out/sfx_patty_sizzle_loop/sfx_patty_sizzle_loop_v01.wav
```

Needs: system `python3` (numpy + pyyaml), `ffmpeg` (post + waveforms), and
libpulse (playback — present wherever PulseAudio runs). No venv, no GPU, no
player binary.

## Manifest fields

- Top level: `project`, `out`, `engine` (target diffusion engine), `sample_rate`
  (48000), `channels` (1, mono one-shots/loops), `post` (highpass Hz, fade ms,
  peak dB, loop crossfade s), `backend` (`synth` | `comfy`).
- Per asset: `id`, `prompt` (sound-report style: "close mic, no music, no room,
  0.5 s" — the audio twin of "isolated, transparent background"), `seconds`,
  `loop` (default false), `variations` (games hate identical sizzles — render
  several), `seed`, `synth: {recipe: sizzle|drop|burn|coin}`.

Outputs: `out/<id>/<id>_vNN.wav` (posted, peak-normalized keepers),
`out/<id>/raw/` (pre-post render + exact prompt/seed txt), plus
`out/<id>/intake.yaml` + `waveform.png` (wavespic of the audition) +
`audition.wav` (keepers concatenated with 0.35 s gaps).

## Handoff to the game (code side pulls, sound never pushes)

The game serves `../assets/`, never `out/`. When the code assistant wants a keeper
it copies the WAVs into `../assets/sfx/<id>/`, logs the accept in
`../assets/manifest.yaml` and regens the asset map. Unused outbox output is fine —
most of what gets made may never ship. Wishes from the code side arrive via
`../assets/wishlist.md` (read-only for sound: `sfx_*` / `music_*` lines are ideas,
not orders). Game keys are the asset ids (variations round-robin under one key).

## Lessons so far

- Generate one-shots and short loops, never a mixed kitchen bed: `sfx_patty_sear`,
  `sfx_grill_idle`, `sfx_diner_bed` layer in-engine (same rule as art: no "patty
  cooking in a busy diner" single file).
- Variation count matters more than single-file perfection — prompt specificity and
  variation count are the bottleneck, not the 5090.
- Loops must be seamless at the splice: render long, equal-power crossfade the tail
  into the head, and skip the one-shot end fade.

## Not done yet

- No diffusion model installed — synth timbre is placeholder-grade next to SA3.
- No `assets/sfx/` accept path on the code side yet (manifest entry shape +
  map regen + WebAudio wiring against the current tiny synth in `cook2.html`).
- Loudness standard is peak-only; move to LUFS-per-bus when the game has a mixer.
