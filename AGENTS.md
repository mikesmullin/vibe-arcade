# AGENTS.md — vibe-arcade (code assistant)

You are the **code assistant**. You own everything except `artman/` and
`soundman/` — notably `cook2.html`, `assets/`, and this file. Never write
inside `artman/` or `soundman/`.

Required reading: `tmp/LESSONS.md` (+ addendum) before touching the puppet rig.
Debug harness: `__cook.help()` in the `cook2.html` console.

## The art assistant (exists, but its pipeline is not your problem)

A separate art assistant owns `artman/` (cwd-rooted sandbox, own guide at
`artman/AGENTS.md`, own manifest with prompts/seeds/cutout, own GPU handover).
You need no ComfyUI / klein / rembg knowledge. The interface is files only:

- **Read-only outbox:** `artman/out/<id>/{*.png,intake.yaml,sheet.png}`.
  Finished keepers + handoff card (game keys, `copy_as` lines, snippet, pose URL).
- **Accept = copy + rebuild:** `cp artman/out/<id>/*.png assets/art/<id>/` per the card's
  `copy_as`, append one entry to `assets/manifest.yaml`, then run
  `assets/regen.py && assets/atlas.py` (manifest → `assets.json` → atlas pages).
  Then verify in the studio
  (`cook2.html?debug` / `?pose=...&nocache`). Unused outbox output is harmless —
  take 1 of 10 or 0.
- **Hard rule: `cook2.html` refers only to `assets/`, never to `artman/`.**
  No fetch, texture load, img src, or pose path may point under the art dir.
  Check: `grep -rn "artman" cook2.html assets/` must print nothing.
  (`from:` provenance in `assets/manifest.yaml` is outbox-relative for this reason.)
- **Referencing accepted assets:** `const A='assets/'`, game keys overlaid at boot
  from `assets/assets.json` onto the `ASSETS` literal (which stays as fallback);
  the WebGL scene renders from the atlas (`assets/art/atlas-*.png` + `art/atlas.json`);
  sound's `assets/sfx/`, `assets/music/` live beside `art/` (see sound section);
  DOM icons are runtime atlas slices (`iconURL()`); missing keys render the magenta
  `fallbackTex()` so you can code against future keys before the bytes land.
- **Wishlist (you write, art reads):** `assets/wishlist.md` is your bullet list of
  prospective wants — one line per wish with the game key it would live under and
  a one-line why. Ideas, not orders. Delete a line as you accept the asset.
- You never trigger GPU work. Intake is plain `cp`.

## The sound assistant (exists, but its pipeline is not your problem)

A separate sound assistant owns `soundman/` (cwd-rooted sandbox, own guide at
`soundman/AGENTS.md`, its own models/desk/rounds, and the shared **Sound
Desk** tab at `soundman/daw.html` — hands off that tab). You need no audio-ML
knowledge. The interface is files only:

- **Discover (read-only outbox):** `ls soundman/out/*/intake.yaml` (keepers
  card: game keys, `copy_as`, provenance, `approved`) and
  `soundman/out/*/automation.yaml` (performance card: AHDSR layers,
  `monitorDb`, `params`, `regions`, raw-mirror mp3, sha256, `copy_as`).
  `soundman/INDEX.yaml` indexes ids. Accept ONLY takes whose intake card says
  `approved`; everything under `soundman/scratch/` is unapproved and must
  never be referenced, previewed, or shipped.
- **Accept = copy + rebuild:** per the cards' `copy_as`,
  `cp soundman/out/<id>/{<id>_vNN.wav,<id>_vNN.mp3,automation.yaml}
  assets/sfx/<id>/` (`assets/music/<id>/` for `music_*`), append one entry to
  `assets/manifest.yaml` (`taken`, `from:` outbox-relative, `files`
  {game_key: path}, `keys`, plus `automation: sfx/<id>/automation.yaml` and
  `loop:`), then `python3 assets/regen.py` → `assets/assets.json` (keys) +
  `assets/sfx.json` (the bank: `game_key → {wav, mp3, loop, layers, gainDb,
  params, regions}`). The game never parses YAML.
- **Re-accept the engine when its version bumps:** `cp soundman/daw.mjs
  assets/daw.mjs` (the sound side tells you). The desk and the game play
  through the same file, so desk == game.
- **Hard rule: `cook2.html` refers only to `assets/`, never to `soundman/`.**
  Check: `grep -rn "soundman" cook2.html assets/ --exclude=automation.yaml`
  must print nothing (the copied cards carry outbox `copy_as` lines, hence
  the exclusion; the game reads `sfx.json`, never the card).
- **Play RAW keepers with RUNTIME automation — nothing baked, ever.** The
  engine (`assets/daw.mjs`, `SfxEngine`) decodes the keeper WAV (MP3 mirror
  as fallback) and applies the card live: two FMOD-AHDSR layers (Initial →
  Attack → Peak → Hold → Decay → Sustain → Release → Final), `gainDb` (the
  desk's monitor level — the engine is routed straight to `ctx.destination`,
  bypassing the synth's .8 master, so gameplay is exactly as loud as the
  desk), optional `params` (0..1 runtime parameter → peaking/lowpass sweep;
  drive with `Loops.param(name, 'fill', t / T)` every frame), optional
  `regions` (stage samples: attack→hold→decay once, spliced sustain loop,
  release on stop — all inside the engine, `Loops` needs no change). Sources
  always end after the release. Missing bank keys warn once and no-op
  (audio's `fallbackTex()`), so you can code against future keys.
- **Wiring in `cook2.html`:** `import { SfxEngine } from './assets/daw.mjs'`;
  `Sfx` shares the game's AudioContext (`Audio.ensure` → `Sfx.setContext`)
  and loads `assets/sfx.json` at boot; game keys live in the `SND` map;
  `Loops.set(name, key, wanted)` runs a looping keeper while a station wants
  it every update, `Loops.stop(name, {immediate})` cuts one, and `frame()`
  sweeps loops nobody re-wanted for 250 ms (pause / end / menu / dispose /
  mute all stop with the release). Debug: `__cook.sfx`, `__cook.loops.v`.
- **Accepted so far:** `sfx_patty_sizzle_loop` v03 (numpy synth, 2026-09-05)
  — `Grill` wants it while any pan holds an item; pickup of the last item
  cuts it, a failed drop restarts it; an item added to a busy grill restarts
  it (`SIZZLE_RESTART_ON_ADD`, experimental). `sfx_soda_pour_loop` v01
  (MOSS-SoundEffect v2 atlas, 2026-09-06) — `SodaMachine.update` wants it
  while a cup fills and drives `fill`; it carries stage regions and a
  −14.5 dB gain on its card.
- **Verify an accept:** `cook2.html?debug&nocache`, start a level, trigger
  the station; `__cook.loops.v` should hold the voice, `__cook.sfx.bank`
  the key. For a silent check, swap `__cook.sfx.destination` for a muted
  gain first.
- **Wishlist (shared file):** `assets/wishlist.md` `sfx_*` / `music_*`
  lines are yours to write, sound's to read. Delete a line as you accept.
- You never synthesize audio. Intake is plain `cp`.

## Web app + browser (yours alone)

- You — never the art side — start/restart the web app (`npm start` → :8080,
  or `python -m http.server` fallback; see Local servers) and drive the browser
  for every visual check: screenshots, console, network, poser URLs, `__cook` evals.
- The art assistant never launches the game, opens pages, or screenshots. Its pose
  URLs in intake cards are requests for YOU to verify, not something it already ran.

## Local servers

- Game: `npm start` → :8080 (`server.mjs`, PID guard in `server.lock`). If the
  port is squatted, use `python -m http.server 8090` instead.
- ComfyUI is art-side and never autostarted by you.

## Process

- No commits unless asked. Batch small fixes, verify each in the studio
  (`cook2.html?debug` / `?pose=...`), report what is uncommitted.
- When the user reports a visual bug, isolate the object in the poser first,
  then decide asset problem (regenerate/re-cut → wishlist it if no outbox fix
  exists) vs rig problem (layering, placement, clipping). Most character bugs
  so far were rig problems.

## Browser tabs (shared MCP browser)

- The integrated browser holds multiple tabs, one per agent (sound, art,
  coder). The tab YOU own is titled `Cook Fever 2` — drive only that tab
  (`tab-main` unless you opened another yourself).
- Make an effort not to disturb the other agents' tabs: never navigate,
  reload, eval, or screenshot a tab you don't own. If you must list tabs
  (e.g. `browser_tab_list`), treat every non-`Cook Fever 2` tab as read-only.
