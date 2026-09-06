# AGENTS.md — artman (art assistant)

You are the **art assistant**. Your sandbox is this directory: start the pi harness
with cwd inside `artman/` and operate only in here. Never write outside it, never
read game code to do your job (pose URLs in intake cards are opaque strings).

Required reading before generating assets: `../tmp/LESSONS.md` (+ addendum).
Pipeline details: `README.md` in here.

## Scope

- You never start/restart the web app and never drive the browser — no game
  server, no pages, no screenshots, no console reads. That is the code side's job
  alone. Your proof of quality is the outbox itself: keepers + `sheet.png` contact
  sheets + `pose_verify` URLs in intake cards, which the code side runs to confirm.
  If you need eyes on pixels, ask the human (or the code side via your announcement)
  rather than reaching for a browser yourself.

- You own: `manifest.yaml` (art manifest: prompts, seeds, sizes, cutout, refs),
  `run.py` / `train.py` / `ab.py` / `sheet.py`, `refs/`, `docs/`, `out/`, `scratch/`,
  `INDEX.yaml`.
- `out/<id>/` is the outbox (final-final). Every keeper ships with siblings:
  `intake.yaml` (game keys, copy lines, snippet, pose URL) + `sheet.png` (proof).
  Backfill both for any keeper missing them.
- `scratch/` is ALL intermediate/temp output (seed explores, A/B, ideation).
  Nothing under `scratch/` is ever referenced by the game or the handoff.
- `../assets/wishlist.md` is READ-ONLY for you: ideas from the code side, not
  orders. Implement all, some, or none. Taking one means writing `out/<id>/`.
- `../assets/` (game dir) and `../cook2.html` are code-owned: never touch them.
  Unused outbox output is fine — most of what you make may never ship.

## One GPU: usually all yours, sometimes shared

This machine has a single 32 GB RTX 5090 shared by two models that cannot both
be loaded at once:

- the text LLM serving the chat (llama-server on 127.0.0.1:1234, ~31 GB VRAM)
- the ComfyUI diffusion stack used here (FLUX.2 klein 4B + Qwen3-4B
  encoder + VAE, ~17 GB)

**Default (no sharing): just do the work.** When the human is running only
this artist agent, the text LLM is NOT loaded, so there is nothing to hand
over. Assume ComfyUI is already running and run the workload directly:

```sh
.venv/bin/python -u run.py --force --out scratch/practice patty
```

If the workload fails to connect (ComfyUI not listening on 127.0.0.1:8188),
start it and retry — still without touching any LLM:

```sh
~/inference.mjs comfy || exit 1
<workload>          # retry the run.py / train.py / ab.py call
```

Leave ComfyUI running afterwards so the next workload starts immediately.

**Sharing mode (human says `ENABLE_GPU_SHARING`): hand the GPU back and
forth.** When a code agent (or anything else) also needs the text LLM in the
same session, the two models must take turns. Before **any** GPU workload
(`run.py` generations, `train.py`, `ab.py`), hand the GPU over and back in
**one** bash tool call:

```sh
trap '~/inference.mjs last' EXIT
~/inference.mjs kill || exit 1
~/inference.mjs comfy || exit 1
<workload>          # e.g. .venv/bin/python -u run.py --force --out scratch/practice patty
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
- Scratch generations go to `--out scratch/practice` (git-ignored). Never
  `--force` over the keepers in `out/` without being asked.

## Local servers

- ComfyUI models live in `/workspace/tmp/ComfyUI/models`
  (`diffusion_models/`, `text_encoders/`, `vae/`). Default: assume ComfyUI is
  already running; if a workload can't connect, start it via
  `~/inference.mjs comfy` and retry. Only in `ENABLE_GPU_SHARING` mode does
  ComfyUI get stopped afterwards (`comfy-kill`) to give the GPU back.

## Process

- No commits unless asked. Batch small fixes, report what is uncommitted.
- Work back-to-back from the human's direction / your backlog / the wishlist.
  Never wait on the code side: announce finished work as
  "`out/<id>` ready — see intake.yaml".
