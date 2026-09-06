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
`soundman/AGENTS.md`, own manifest with prompts/seeds/synth recipes, own desk
at `soundman/daw.html` titled SoundMan Agent — hands off that tab too). You
need no audio-ML knowledge. The interface is files only:

- **Discover (read-only outbox):** `ls soundman/out/*/intake.yaml` (keepers
  cards: game keys, `copy_as`, seed, `approved`) + `*/automation.yaml`
  (performance cards: ADSR knob settings, take, raw-mirror mp3, sha256,
  `copy_as`). `soundman/INDEX.yaml` + `out/sounds.json` index them.
  Accept ONLY takes with `intake.yaml:approved` — the human gates every
  take; unapproved variations live in `soundman/scratch/` and must never be
  referenced, previewed, or shipped.
- **Accept = copy + rebuild:** `cp soundman/out/<id>/{keeper wavs + mp3,
  automation.yaml} assets/sfx/<id>/` (or `assets/music/<id>/` for `music_*`
  ids) per the cards' `copy_as`, append one entry to `assets/manifest.yaml`
  (same shape as art: taken date, `from:` outbox source, files
  {game_key: path}, keys — plus `automation: sfx/<id>/automation.yaml` and
  `loop:` for sounds), then regen the maps (`assets/regen.py` writes audio
  keys into `assets.json` and the automation bank into `assets/sfx.json`).
  First accepted sound: `sfx_patty_sizzle_loop` v03 (2026-09-05), looped by
  the `Grill` unbroken while ≥1 pan holds an item (cooking, cooked, burnt);
  `Grill.take` (tap-select or drag start) of the last item cuts it at once
  (`Loops.stop(..., {immediate:true})`), a failed drop reattaches and
  `update()` restarts it from the top. Game keys for takes live under
  one sound id; unused outbox output is harmless — take 1 of N or 0.
- **Hard rule: `cook2.html` refers only to `assets/`, never to `soundman/`.**
  No fetch, audio load, `<audio src>`, or automation path may point under the
  sound dir. Check: `grep -rn "soundman" cook2.html assets/
  --exclude=automation.yaml` must print nothing. (`from:` provenance in
  `assets/manifest.yaml` is outbox-relative for this reason; the accepted
  `automation.yaml` cards are copied verbatim and carry outbox `copy_as`
  lines, which is why they are excluded — the game reads `sfx.json`, never
  the card.)
- **Play RAW keepers with RUNTIME automation — nothing baked, ever.** The game
  decodes keeper WAVs (primary) or their raw MP3 mirrors (48 kHz mono,
  universal fallback) and shapes them live
  with the two-layer ADSR (hit + body) from the accepted `automation.yaml`.
  No outbox file has automation baked in — that is the design, not an
  omission. `monitorDb` on the card is the sound's playback gain: `regen.py`
  carries it into `sfx.json` as `gainDb` and the engine applies it live on the
  voice, so gameplay is exactly as loud as the desk (the engine is routed
  straight to `ctx.destination`, bypassing the synth's .8 master for that
  reason). Never render it into audio.
- **Playback lib (sound-written, you accept a copy): `assets/daw.mjs`.** The
  sound side owns `soundman/daw.mjs` (`SfxEngine`, `Voice`, `layerGains`,
  `VERSION`) and its desk plays through the very same file, so desk == game.
  Accept = `cp soundman/daw.mjs assets/daw.mjs` whenever `VERSION` bumps.
  `cook2.html` imports `./assets/daw.mjs`; `Sfx` (engine) shares the game's
  AudioContext + master gain (`Audio.ensure` → `Sfx.setContext`), loads the
  bank `assets/sfx.json` at boot, and `Loops.set(name, key, wanted)` runs a
  looping keeper while a station wants it (`frame()` sweeps loops nobody
  re-wanted for 250 ms — pause/end/menu/dispose/mute all stop with the
  release tail). Debug: `__cook.sfx` (engine, `.bank`, `.voices`) and
  `__cook.loops.v`. Semantics per layer: `setValueAtTime(1e-4)` → linear ramp
  to peak over attack → hold → exponential ramp to sustain over decay → sit
  (loop wraps keep sustain, never retrigger); stop = cancel +
  `setTargetAtTime(0, tau=release/3)`, source stops after the slowest tail.
  Missing keys = console warn + `null` voice (audio's `fallbackTex()`).
  `assets/regen.py` builds `assets/sfx.json` (`game_key → {wav, mp3, loop,
  layers}`) from every manifest entry carrying `automation:` — the game never
  parses YAML. Game keys for sounds live in the `SND` map in `cook2.html`.
- **Wishlist (shared file):** `assets/wishlist.md` `sfx_*` / `music_*` lines
  are yours to write, sound's to read (ideas, not orders). Delete a line as
  you accept the asset.
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
