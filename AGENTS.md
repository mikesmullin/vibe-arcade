# AGENTS.md — vibe-arcade

Notes for agentic collaborators working in this repo. Required reading before
touching assets or the puppet rig: `tmp/LESSONS.md` (+ addendum). Pipeline
details: `assetgen/README.md`. Debug harness: `__cook.help()` in the
`cook2.html` console.

## One GPU: hand it back and forth

This machine has a single 32 GB RTX 5090 shared by two models that cannot both
be loaded at once:

- the text LLM serving this chat (llama-server on 127.0.0.1:1234, ~31 GB VRAM)
- the ComfyUI diffusion stack used by `assetgen/` (FLUX.2 klein 4B + Qwen3-4B
  encoder + VAE, ~17 GB)

Before **any** GPU workload (`assetgen/run.py` generations, `train.py`,
`ab.py`), hand the GPU over and back in **one** bash tool call:

```sh
trap '~/inference.mjs last' EXIT
~/inference.mjs kill || exit 1
~/inference.mjs comfy || exit 1
<assetgen workload>          # e.g. .venv/bin/python -u run.py --force --out out_practice patty
rc=$?
~/inference.mjs comfy-kill
exit $rc
```

Why one tool call: killing the text LLM mid-turn is safe because the shell
outlives it; the EXIT trap guarantees `last` relaunches the LLM even if the
workload fails. `last` blocks until /health is 200, so the session is usable
as soon as the call returns.

Subcommands of `~/inference.mjs` (config: `~/.config/inference/config.yaml`):

| cmd | does |
|---|---|
| `kill` | stop the tracked llama-server; blocks until the process is gone (SIGTERM → 10 s → SIGKILL → hard error if still alive) |
| `comfy [args...]` | launch ComfyUI in the background (log `~/.cache/inference/comfy.log`, tracked in `comfy.lock`); passthrough args are appended, a passthrough `--listen`/`--port` overrides the defaults; blocks until `/system_stats` is 200; refuses to double-launch; warns if the GPU is >75% full (LLM still loaded?) |
| `comfy-kill` | stop the tracked ComfyUI; blocks until the process is gone |
| `last` | relaunch the last LLM profile; blocks until /health is 200 |

Gotchas learned the hard way (2026-09-05):

- Probe `/system_stats`, never `/system`: ComfyUI 0.30.0 has no `/system`
  route (404), so a `/system` health check waits forever on a healthy server.
- Never gate on a VRAM level: other processes may hold gigabytes, making any
  "wait until free" target unreachable. Process death is the completion
  signal — the driver reclaims VRAM on exit.
- `pgrep -f "ComfyUI/main"` false-negatives: the real argv is
  `.../ComfyUI/.venv/bin/python main.py`, which lacks that literal substring
  (and the pattern self-matches the searcher's own shell). Prefer the lock pid
  (`~/.cache/inference/comfy.lock`) or the port probe.
- Scratch generations go to `--out out_practice` (git-ignored). Never
  `--force` over the keepers in `assetgen/out/` without being asked.

## Local servers

- Game: `npm start` → :8080 (`server.mjs`, PID guard in `server.lock`). If the
  port is squatted, use `python -m http.server 8090` instead.
- ComfyUI is never autostarted; models live in `/workspace/tmp/ComfyUI/models`
  (`diffusion_models/`, `text_encoders/`, `vae/`). Start it only via
  `~/inference.mjs comfy` (after `kill`), stop it via `comfy-kill`.

## Process

- No commits unless asked. Batch small fixes, verify each in the studio
  (`cook2.html?debug` / `?pose=...`), report what is uncommitted.
- When the user reports a visual bug, isolate the object in the poser first,
  then decide asset problem (regenerate/re-cut) vs rig problem (layering,
  placement, clipping). Most character bugs so far were rig problems.
