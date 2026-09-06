#!/usr/bin/env python
"""present.py: announce an outbox id via voice TTS (blocking), then play it.

    python3 present.py sfx_patty_sizzle_loop            # TTS + first keeper (1x)
    python3 present.py sfx_patty_sizzle_loop --take 2   # TTS + keeper v02 only
    python3 present.py sfx_patty_sizzle_loop --all      # TTS + full audition mix
    python3 present.py sfx_patty_sizzle_loop --file sfx_patty_sizzle_loop_perf.wav  # TTS + export
    python3 present.py sfx_patty_sizzle_loop --voice aru  # different voice preset
    python3 present.py sfx_patty_sizzle_loop --bg       # TTS blocks, sfx detached

The ritual: the human hears who (the voice) + which (the id, spoken) BEFORE
the sound, so feedback lands on the right asset. TTS always runs in the
foreground so ordering is guaranteed; --bg detaches only the sfx playback.
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
VOICE = Path("/workspace/voice/zig-out/bin/voice")


def announce(text: str, voice: str):
    """Speak blocking: download the utterance WAV from the voice daemon
    (preloaded models, fast) and play it locally — paplay returns only when
    playback finishes, so the sfx never overlaps the announcement. Falls back
    to the bare voice client if the daemon HTTP API is unreachable."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:3124/speak",
            data=json.dumps({"text": text, "voice": voice,
                             "mode": "download"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        if blob[:4] != b"RIFF":
            raise ValueError(f"unexpected speak response ({len(blob)} bytes)")
        ap = HERE / "scratch" / "announce.wav"
        ap.write_bytes(blob)
        print(f"say: {text}")
        r = subprocess.run([sys.executable, str(HERE / "play.py"), str(ap)])
        if r.returncode != 0:
            sys.exit(r.returncode)
        return
    except Exception as e:
        print(f"announce via daemon HTTP failed ({e}); voice-client fallback")
    if not VOICE.is_file():
        sys.exit(f"present.py: voice CLI missing: {VOICE}")
    r = subprocess.run([str(VOICE), voice, text])
    if r.returncode != 0:
        sys.exit(f"present.py: voice TTS failed (exit {r.returncode}) — sfx not played")


def spoken(aid: str) -> str:
    name = aid
    for prefix in ("sfx_", "music_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id", help="outbox id, e.g. sfx_patty_sizzle_loop")
    ap.add_argument("--take", type=int, default=1,
                    help="which keeper to play (1-based, default 1)")
    ap.add_argument("--all", action="store_true",
                    help="play the full audition mix instead of one keeper")
    ap.add_argument("--file", default=None,
                    help="play a specific file under out/<id>/ (e.g. exports)")
    ap.add_argument("--voice", default="alan",
                    help="voice preset for the announcement (default alan)")
    ap.add_argument("--bg", action="store_true",
                    help="detach sfx playback in background (TTS still blocks)")
    a = ap.parse_args()

    card_path = HERE / "out" / a.id / "intake.yaml"
    if not card_path.is_file():
        sys.exit(f"present.py: no outbox card: {card_path}")
    card = yaml.safe_load(open(card_path)) or {}
    files = list((card.get("game_keys") or {}).values())
    if a.file:
        wav = HERE / "out" / a.id / a.file
    elif a.all:
        wav = HERE / "out" / a.id / "audition.wav"
    else:
        if not 1 <= a.take <= len(files):
            sys.exit(f"present.py: --take {a.take} out of range (1..{len(files)})")
        wav = HERE / "out" / a.id / files[a.take - 1]
    if not wav.is_file():
        sys.exit(f"present.py: nothing to play: {wav}")

    text = f"Sound's done: {spoken(a.id)}"
    announce(text, a.voice)

    cmd = [sys.executable, str(HERE / "play.py"), str(wav)]
    if a.bg:
        log = open(HERE / "scratch" / "present.log", "ab")
        p = subprocess.Popen(cmd, start_new_session=True,
                             stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT)
        print(f"playing {wav.name} in background (pid {p.pid})")
    else:
        print(f"play: {wav.name}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            sys.exit(r.returncode)


if __name__ == "__main__":
    main()
