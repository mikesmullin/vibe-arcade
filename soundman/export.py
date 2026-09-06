#!/usr/bin/env python
"""export.py: desk automation JSON + approved keeper -> outbox MP3 + automation.yaml.

The MP3 is the RAW keeper transcoded — NO automation is baked in. The game
loads raw audio (WAV primary, MP3 fallback) and applies the automation LIVE at
runtime (two-layer ADSR per the SfxEngine contract in ../../AGENTS.md). Baking
would freeze one performance and defeat the whole runtime-automation design.

Deterministic: same keeper + same ffmpeg build -> same bytes. The yaml records
the exact command, ffmpeg version, and sha256 so any rerun is verifiable
(run twice and cmp).

    python3 export.py --settings '<__soundman.get() JSON>' [--force]

The take + layers come from the settings; `monitorDb` is the sound's playback
gain (applied live on the voice by daw.mjs, desk and game alike — recorded on
the card, never rendered into the audio). Refuses takes that are not in the outbox
`intake.yaml` game keys — the human approval gate, enforced in code.

Writes out/<id>/{<id>_vNN.mp3, automation.yaml}.
MP3 (libmp3lame, mono 48 kHz, 128k) is the universal browser format: it plays
in Chrome/Safari/Edge/Firefox/Opera with no plugins. WAV stays the lossless
keeper for decodeAudioData; Opus/Vorbis are skipped for Safari's partial support.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
MP3_KBPS = 128


def ffmpeg_version() -> str:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-version"], capture_output=True, text=True)
    return (r.stdout.splitlines() or ["ffmpeg ?"])[0]


def run(cmd: str, *args: str):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg {cmd} failed: {r.stderr[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", required=True, help="__soundman.get() JSON")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    s = json.loads(a.settings)
    aid = s["sound"]
    adir = HERE / "out" / aid
    card = yaml.safe_load(open(adir / "intake.yaml")) or {}
    approved = card.get("game_keys") or {}
    take = int(s.get("take", 1))
    keeper_name = "audition.wav" if take == 0 else f"{aid}_v{take:02d}.wav"
    if take != 0 and keeper_name not in approved.values():
        raise SystemExit(
            f"export.py: REFUSED — {keeper_name} is not an approved outbox keeper "
            f"(intake.yaml game keys: {sorted(approved.values())}). "
            f"Get human approval + promote.py first.")
    keeper = adir / keeper_name
    if not keeper.is_file():
        raise SystemExit(f"export.py: keeper missing: {keeper}")

    mp3 = adir / f"{keeper.stem}.mp3"
    auto_yaml = adir / "automation.yaml"
    if mp3.exists() and auto_yaml.exists() and not a.force:
        print(f"skip {aid} export (exists, --force to redo)")
        return

    run("transcode", "-i", str(keeper),
        "-codec:a", "libmp3lame", "-b:a", f"{MP3_KBPS}k",
        "-ar", "48000", "-ac", "1", str(mp3))
    run("verify-decode", "-i", str(mp3), "-f", "null", "-")
    sha = hashlib.sha256(mp3.read_bytes()).hexdigest()

    card_out = {
        "id": aid,
        "date": date.today().isoformat(),
        "take": take,
        "keeper": keeper_name,
        "keeper_mp3": mp3.name,
        "raw_note": "mp3 is the raw keeper transcoded — NO automation baked in; "
                    "the game applies layers live at runtime",
        "layers": s["layers"],
        "monitorDb": s.get("monitorDb"),
        "monitor_note": "playback gain — applied live on the voice by daw.mjs (desk == game); never rendered into audio",
        "render": {"mp3": f"libmp3lame {MP3_KBPS}k mono 48000Hz",
                   "ffmpeg": ffmpeg_version()},
        "files": {mp3.name: mp3.name},
        "sha256_mp3": sha,
        "copy_as": (f"cp soundman/out/{aid}/{keeper_name} assets/sfx/{aid}/{keeper_name}\n"
                    f"cp soundman/out/{aid}/{mp3.name} assets/sfx/{aid}/{mp3.name}\n"
                    f"cp soundman/out/{aid}/automation.yaml assets/sfx/{aid}/automation.yaml\n"),
        "command": "python3 export.py --settings '<get() JSON>'" + (" --force" if a.force else ""),
        "determinism": "same keeper + same ffmpeg build -> same bytes (sha256 above; rerun with --force and cmp)",
    }
    with open(auto_yaml, "w") as f:
        yaml.safe_dump(card_out, f, sort_keys=False)
    print(f"[{aid}] {keeper_name} (raw) -> {mp3.name} + {auto_yaml.name}")
    print(f"   sha256:{sha[:12]}…  layers: hit {s['layers']['hit']} / body {s['layers']['body']}")


if __name__ == "__main__":
    main()
