#!/usr/bin/env python
"""promote.py: move HUMAN-APPROVED takes from a scratch render dir into out/.

Nothing enters the outbox without explicit human approval (per-take).
Workflow: render to scratch -> human listens -> approve takes -> promote.

    python3 run.py --out scratch/sizzle_try2 sfx_patty_sizzle_loop   # render (scratch only)
    # ... human listens (present.py --out? no: ffplay scratch/.../audition.wav)
    python3 promote.py sfx_patty_sizzle_loop --from scratch/sizzle_try2 --takes 3 [--force]

Copies the approved keepers (+ their raw/ siblings if present) into
out/<id>/, then rebuilds audition.wav + waveform.png + intake.yaml and updates
INDEX.yaml + out/sounds.json. Metadata (seed, prompt, loop) comes from
manifest.yaml; per-take seeds follow run.py (seed + (take-1)*977).
"""
import argparse
import json
import shutil
import subprocess
import wave
from datetime import date
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


def write_wav(path: Path, x: np.ndarray, sr: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def waveform_png(audition: Path, png: Path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(audition),
           "-filter_complex", "showwavespic=s=1200x400:colors=0x33ccff",
           "-frames:v", "1", str(png)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"   warn: waveform render failed: {r.stderr[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id", help="outbox id, e.g. sfx_patty_sizzle_loop")
    ap.add_argument("--from", dest="src", required=True, help="scratch render dir holding <id>_vNN.wav")
    ap.add_argument("--takes", required=True, help="approved takes, e.g. '3' or '1,3'")
    ap.add_argument("--force", action="store_true", help="overwrite existing outbox files")
    a = ap.parse_args()

    m = yaml.safe_load(open(HERE / "manifest.yaml"))
    asset = next((x for x in m.get("assets", []) if x["id"] == a.id), None)
    if asset is None:
        raise SystemExit(f"promote.py: no asset '{a.id}' in manifest.yaml")
    takes = [int(t) for t in a.takes.split(",")]
    srcdir = HERE / a.src
    adir = HERE / "out" / a.id
    (adir / "raw").mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    seed0 = int(asset.get("seed", 0))
    sr = int(m.get("sample_rate", 48000))

    keepers = []
    for i in takes:
        name = f"{a.id}_v{i:02d}.wav"
        src = srcdir / name
        if not src.is_file():
            raise SystemExit(f"promote.py: approved take missing in {srcdir}: {name}")
        dst = adir / name
        if dst.exists() and not a.force:
            raise SystemExit(f"promote.py: {dst} exists (use --force to overwrite)")
        shutil.copy2(str(src), str(dst))
        for raw in (srcdir / "raw").glob(f"{a.id}_v{i:02d}*"):
            shutil.copy2(str(raw), str(adir / "raw" / raw.name))
        keepers.append(name)
        print(f"[{a.id}] promoted {name} (seed {seed0 + (i - 1) * 977})")

    gap = np.zeros(int(sr * 0.35), dtype=np.float32)
    parts = []
    for f in keepers:
        y, _ = read_wav(adir / f)
        parts += [y, gap]
    write_wav(adir / "audition.wav", np.concatenate(parts[:-1]), sr)
    waveform_png(adir / "audition.wav", adir / "waveform.png")

    game_keys = {f[:-4]: f for f in keepers}
    card = {
        "id": a.id,
        "date": today,
        "engine": m.get("engine", "synth"),
        "rendered": f"synth/{(asset.get('synth') or {}).get('recipe', 'sizzle')}",
        "sample_rate": sr,
        "loop": bool(asset.get("loop", False)),
        "game_keys": game_keys,
        "seed": seed0,
        "copy_as": "".join(f"cp soundman/out/{a.id}/{f} assets/sfx/{a.id}/{f}\n" for f in keepers),
        "assets_snippet": "".join(f"{f[:-4]}: A+'sfx/{a.id}/{f}',\n" for f in keepers),
        "listen_verify": (f"python3 present.py {a.id} (pre-accept, voice announce + playback); "
                          "post-accept playback check in cook2.html?debug (code side)"),
        "notes": f"prompt was: {asset.get('prompt', '')}",
        "approved": f"{today} (takes {a.takes} approved by human; promoted from {a.src}/)",
    }
    with open(adir / "intake.yaml", "w") as f:
        yaml.safe_dump(card, f, sort_keys=False)

    idx_path = HERE / "INDEX.yaml"
    idx = yaml.safe_load(open(idx_path)) or {}
    idx[a.id] = {"date": today, "files": keepers, "keys": list(game_keys),
                 "loop": bool(asset.get("loop", False)),
                 "backend": f"synth/{(asset.get('synth') or {}).get('recipe', 'sizzle')}"}
    with open(idx_path, "w") as f:
        f.write("# SOUNDMAN INDEX — finished outbox ids (sound-written). "
                "Code side: ls out/*/intake.yaml works just as well.\n")
        yaml.safe_dump(idx, f, sort_keys=True)

    sounds = {}
    for cp in sorted((HERE / "out").glob("*/intake.yaml")):
        c = yaml.safe_load(open(cp)) or {}
        if c.get("game_keys"):
            sounds[c.get("id", cp.parent.name)] = {
                "keepers": list(c["game_keys"].values()),
                "audition": "audition.wav", "loop": bool(c.get("loop", False))}
    (HERE / "out" / "sounds.json").write_text(json.dumps(sounds, indent=1, sort_keys=True) + "\n")
    print(f"   -> {adir.relative_to(HERE)}/ ({len(keepers)} keepers, audition, waveform, intake)")


if __name__ == "__main__":
    main()
