#!/usr/bin/env python
"""audition.py: cross-id mix for review (the audio contact sheet; cf. art's sheet.py).

    python3 audition.py   # one keeper per out/<id>/ -> scratch/audition_mix.wav
"""
import wave
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
SR = 48000


def read_mono(path: Path):
    with wave.open(str(path), "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def main():
    ids = sorted(p.parent.name for p in HERE.glob("out/*/intake.yaml"))
    if not ids:
        raise SystemExit("nothing in out/ yet — run.py first")
    (HERE / "scratch").mkdir(exist_ok=True)
    gap = np.zeros(int(SR * 0.5), dtype=np.float32)
    parts, playlist = [], []
    for aid in ids:
        card = yaml.safe_load(open(HERE / "out" / aid / "intake.yaml"))
        files = list((card.get("game_keys") or {}).values())
        if not files:
            print(f"skip {aid}: no game_keys in intake.yaml");
            continue
        src = HERE / "out" / aid / files[0]
        y, sr = read_mono(src)
        if sr != SR:
            print(f"skip {aid}: {sr} Hz != {SR} Hz (kept the mix at one rate)");
            continue
        parts += [y, gap]
        playlist.append((aid, files[0], len(y) / sr))
    mix = HERE / "scratch" / "audition_mix.wav"
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype(np.int16)
    with wave.open(str(mix), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"-> {mix.relative_to(HERE)} ({sum(d for _, _, d in playlist):.1f}s of keepers)")
    for aid, f, d in playlist:
        print(f"   {aid:28s} {f}  {d:.2f}s")


if __name__ == "__main__":
    main()
