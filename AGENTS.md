# AGENTS.md — vibe-arcade (code assistant)

You are the **code assistant**. You own everything except `assetgen/` — notably
`cook2.html`, `assets/`, and this file. Never write inside `assetgen/`.

Required reading: `tmp/LESSONS.md` (+ addendum) before touching the puppet rig.
Debug harness: `__cook.help()` in the `cook2.html` console.

## The art assistant (exists, but its pipeline is not your problem)

A separate art assistant owns `assetgen/` (cwd-rooted sandbox, own guide at
`assetgen/AGENTS.md`, own manifest with prompts/seeds/cutout, own GPU handover).
You need no ComfyUI / klein / rembg knowledge. The interface is files only:

- **Read-only outbox:** `assetgen/out/<id>/{*.png,intake.yaml,sheet.png}`.
  Finished keepers + handoff card (game keys, `copy_as` lines, snippet, pose URL).
- **Accept = copy + rebuild:** `cp assetgen/out/<id>/*.png assets/art/<id>/` per the card's
  `copy_as`, append one entry to `assets/manifest.yaml`, then run
  `assets/regen.py && assets/atlas.py` (manifest → `assets.json` → atlas pages).
  Then verify in the studio
  (`cook2.html?debug` / `?pose=...&nocache`). Unused outbox output is harmless —
  take 1 of 10 or 0.
- **Hard rule: `cook2.html` refers only to `assets/`, never to `assetgen/`.**
  No fetch, texture load, img src, or pose path may point under the art dir.
  Check: `grep -rn "assetgen" cook2.html assets/` must print nothing.
  (`from:` provenance in `assets/manifest.yaml` is outbox-relative for this reason.)
- **Referencing accepted assets:** `const A='assets/'`, game keys overlaid at boot
  from `assets/assets.json` onto the `ASSETS` literal (which stays as fallback);
  the WebGL scene renders from the atlas (`assets/art/atlas-*.png` + `art/atlas.json`),
  (room beside them for future `assets/sfx/`, `assets/music/`),
  DOM icons are runtime atlas slices (`iconURL()`); missing keys render the magenta
  `fallbackTex()` so you can code against future keys before the bytes land.
- **Wishlist (you write, art reads):** `assets/wishlist.md` is your bullet list of
  prospective wants — one line per wish with the game key it would live under and
  a one-line why. Ideas, not orders. Delete a line as you accept the asset.
- You never trigger GPU work. Intake is plain `cp`.

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
