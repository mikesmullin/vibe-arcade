#!/usr/bin/env python
"""soundman: manifest.yaml -> wav one-shots and loops.

    python3 run.py                                # everything in manifest.yaml
    python3 run.py sfx_patty_sizzle_loop          # only this asset id
    python3 run.py --force ...                    # regenerate even if keepers exist
    python3 run.py --out scratch/practice ...     # explore (never referenced)
    python3 run.py --backend comfy ...            # diffusion path (needs model install)

Backends: synth (numpy recipes + ffmpeg post, works today) | comfy (Stable Audio
via the ComfyUI API — specified in README.md, exits with instructions until a
model is installed).
"""
import argparse
import json
import subprocess
import sys
import tempfile
import wave
from datetime import date
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent


class _Literal(str):
    """str subclass that dumps as a YAML literal (|) block: paste-ready cards."""


def _literal_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")

yaml.add_representer(_Literal, _literal_representer, Dumper=yaml.SafeDumper)


# ------------------------------------------------------------------ wav io
def write_wav(path: Path, x: np.ndarray, sr: int):
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise SystemExit(f"unsupported sample width {sw} in {path}")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def wav_dur(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


# ------------------------------------------------------------ synth engine
def _norm_rms(x: np.ndarray) -> np.ndarray:
    r = float(np.sqrt(np.mean(x ** 2)))
    return x / (r or 1.0)


def band_noise(rng: np.random.Generator, n: int, sr: int,
               f_lo: float, f_hi: float, edge: float = 400.0) -> np.ndarray:
    """White noise through a smooth frequency mask (FFT brickwall with
    smoothstep edges). Vectorized; no scipy needed."""
    w = rng.standard_normal(n).astype(np.float32)
    F = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    m = np.clip((freqs - f_lo) / edge, 0, 1) * np.clip((f_hi - freqs) / edge, 0, 1)
    m = (m * m * (3 - 2 * m)).astype(np.float32)
    return np.fft.irfft(F * m, n).astype(np.float32)


def crackle(rng: np.random.Generator, n: int, sr: int, density: float,
            amp: float, decay_ms: float = 6.0) -> np.ndarray:
    """Poisson impulse train through an exponential-decay kernel: grease pops."""
    cnt = max(1, int(n / sr * density))
    pops = np.zeros(n, dtype=np.float32)
    idx = rng.integers(0, n, cnt)
    a = rng.exponential(amp, cnt).astype(np.float32) * rng.choice(
        np.array([-1.0, 1.0], dtype=np.float32), cnt)
    np.add.at(pops, idx, a)
    k = max(2, int(sr * decay_ms / 1000))
    kernel = np.exp(-np.arange(k, dtype=np.float32) / (k / 4.0))
    kernel /= kernel.sum()
    return np.convolve(pops, kernel, mode="same").astype(np.float32)


def _bandpass(x: np.ndarray, sr: int, f_lo: float, f_hi: float,
              edge_lo: float = 500.0, edge_hi: float = 800.0) -> np.ndarray:
    """FFT brickwall with smoothstep edges (no scipy needed)."""
    n = len(x)
    F = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    m = np.clip((freqs - f_lo) / edge_lo, 0, 1) * np.clip((f_hi - freqs) / edge_hi, 0, 1)
    m = (m * m * (3 - 2 * m)).astype(np.float32)
    return np.fft.irfft(F * m, n).astype(np.float32)


def _pink(rng: np.random.Generator, n: int) -> np.ndarray:
    """Pink (1/f) noise via the Paul Kellet filter: much less harsh than white
    as a frying base — energy falls with frequency instead of screaming."""
    w = rng.standard_normal(n).astype(np.float64)
    b = np.zeros(7)
    y = np.empty(n)
    for i in range(n):
        x = w[i]
        b[0] = 0.99886 * b[0] + x * 0.0555179
        b[1] = 0.99332 * b[1] + x * 0.0750759
        b[2] = 0.96900 * b[2] + x * 0.1538520
        b[3] = 0.86650 * b[3] + x * 0.3104856
        b[4] = 0.55000 * b[4] + x * 0.5329522
        b[5] = -0.7616 * b[5] - x * 0.0168980
        y[i] = (b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + x * 0.5362) * 0.11
        b[6] = x * 0.115926
    return y.astype(np.float32)


def _sizzle_bed(rng: np.random.Generator, n: int, sr: int, harsh: float) -> np.ndarray:
    """v6: drier, not brighter. v5 hit ~80% but still rainy, and the centroid
    (~4.9 kHz) is already at the harshness ceiling — so the wash thins again
    (0.17 -> 0.14, highpassed from 750 Hz) while the micro-crackle HOLDS at
    0.20, and fry definition comes from deeper roughness (0.32 -> 0.40) carved
    into the wash itself instead of more top end."""
    base = _bandpass(_pink(rng, n), sr, 750, 6500, edge_lo=300.0, edge_hi=3000.0)
    base = _norm_rms(base) * 0.14
    rough_src = band_noise(rng, n, sr, 20, 80, edge=20.0)
    rough_src /= np.max(np.abs(rough_src)) + 1e-6
    rough = 1.0 + (0.40 + 0.15 * harsh) * rough_src
    t = np.arange(n) / sr
    life = 1.0 + 0.08 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 6.28))
    x = base * rough.astype(np.float32) * life.astype(np.float32)
    micro = _norm_rms(_bandpass(crackle(rng, n, sr, 350.0, 1.0, decay_ms=2.0),
                                sr, 2800, 7500)) * (0.20 + 0.08 * harsh)
    x = x + micro
    blips = _norm_rms(_bandpass(crackle(rng, n, sr, 2.0, 1.0, decay_ms=12.0),
                                 sr, 800, 4000)) * 0.10
    x = x + blips
    if harsh > 0:
        x = np.tanh(x * (1.0 + 0.8 * harsh)) * 0.85
    return x.astype(np.float32)


def render_sizzle(rng, sr, seconds, harsh=0.0, slap=False) -> np.ndarray:
    n = int(sr * seconds)
    x = _sizzle_bed(rng, n, sr, harsh)
    if slap:
        t = np.arange(min(n, int(sr * 0.12))) / sr
        f = 130.0 - (75.0 * t / 0.12)  # meat-slap pitch drop 130 -> 55 Hz
        phase = 2 * np.pi * np.cumsum(f) / sr
        thump = np.sin(phase) * np.exp(-t * 28.0) * 0.9
        x[:len(thump)] += thump.astype(np.float32)
        ck = min(n, int(sr * 0.004))
        x[:ck] += (rng.standard_normal(ck).astype(np.float32)
                   * np.exp(-np.arange(ck) / (ck / 3.0)) * 0.4)
        ramp = min(n, int(sr * 0.15))
        x[:ramp] *= np.linspace(0.0, 1.0, ramp).astype(np.float32)
    return x


def render_coin(rng, sr, seconds) -> np.ndarray:
    n = int(sr * seconds)
    t = np.arange(n) / sr
    f1 = float(rng.uniform(0.99, 1.01)) * 2093.0
    f2 = float(rng.uniform(0.99, 1.01)) * 2637.0
    y = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 16.0) * 0.50
    dt = np.clip(t - 0.05, 0, None)
    y += np.sin(2 * np.pi * f2 * t) * np.exp(-dt * 14.0) * (dt > 0) * 0.35
    y += 0.08 * np.sin(2 * np.pi * 3 * f1 * t) * np.exp(-t * 30.0)
    ck = min(n, int(sr * 0.002))
    y[:ck] += rng.standard_normal(ck).astype(np.float32) * 0.15
    return y.astype(np.float32)


RECIPES = {
    "sizzle": lambda rng, sr, s: render_sizzle(rng, sr, s),
    "drop": lambda rng, sr, s: render_sizzle(rng, sr, s, slap=True),
    "burn": lambda rng, sr, s: render_sizzle(rng, sr, s, harsh=1.0),
    "coin": render_coin,
}


def make_loop(x: np.ndarray, sr: int, seconds: float, xfade: float) -> np.ndarray:
    """Equal-power crossfade of the tail into the head: seamless splice."""
    N, X = int(sr * seconds), int(sr * xfade)
    assert len(x) >= N + X, "loop render too short for crossfade"
    y = x[:N].copy()
    t = np.linspace(0, np.pi / 2, X).astype(np.float32)
    y[:X] = y[:X] * np.cos(t) ** 2 + x[N:N + X] * np.sin(t) ** 2
    return y


# --------------------------------------------------------------- ffmpeg post
def ffmpeg_post(raw: Path, post: Path, sr: int, highpass: int, fade_ms: float, loop: bool):
    af = [f"highpass=f={highpass}"]
    if not loop and fade_ms > 0:
        dur = wav_dur(raw)
        st = max(0.0, dur - fade_ms / 1000.0)
        af.append(f"afade=t=out:st={st:.3f}:d={fade_ms / 1000.0:.3f}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", ",".join(af),
           "-ar", str(sr), "-ac", "1", str(post)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg post failed on {raw.name}: {r.stderr[:500]}")


def peak_normalize(x: np.ndarray, peak_db: float) -> np.ndarray:
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        return x
    return (x * (10.0 ** (peak_db / 20.0) / peak)).astype(np.float32)


def waveform_png(audition: Path, png: Path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(audition),
           "-filter_complex", "showwavespic=s=1200x400:colors=0x33ccff",
           "-frames:v", "1", str(png)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"   warn: waveform render failed: {r.stderr[:200]}")


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--manifest", default=HERE / "manifest.yaml")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", help="override output dir (e.g. scratch/practice)")
    ap.add_argument("--backend", choices=["synth", "comfy"],
                    help="override manifest backend for this run")
    ap.add_argument("--seed-offset", type=int, default=0, help="add to every seed")
    a = ap.parse_args()

    m = yaml.safe_load(open(a.manifest))
    sr = m.get("sample_rate", 48000)
    post = m.get("post", {})
    hp, fade_ms = post.get("highpass", 80), post.get("fade_out_ms", 12)
    peak_db, xfade = post.get("peak_db", -1.0), post.get("loop_xfade", 0.5)
    out_root = HERE / (a.out or m.get("out", "out"))
    today = date.today().isoformat()

    assets = [x for x in m.get("assets", []) if not a.ids or x["id"] in a.ids]
    if not assets:
        sys.exit("no matching assets")

    backend = a.backend or m.get("backend", "synth")
    if backend == "comfy":
        sys.exit(
            "comfy backend: no audio diffusion model installed yet.\n"
            "To enable: install a Stable Audio custom node + weights "
            "(SOUNDMAN.md: Stable Audio 3.0 Small SFX) into /workspace/tmp/ComfyUI "
            "(models/diffusion_models/ + custom_nodes/), start ComfyUI, then re-run "
            "with --backend comfy. Until then the production path is the synth backend "
            "(default): procedural recipes rendering this same manifest."
        )

    for asset in assets:
        aid = asset["id"]
        secs = float(asset.get("seconds", 1.0))
        loop = bool(asset.get("loop", False))
        vars_ = int(asset.get("variations", 1))
        seed0 = int(asset.get("seed", 0)) + a.seed_offset
        recipe = (asset.get("synth") or {}).get("recipe", "sizzle")
        if recipe not in RECIPES:
            sys.exit(f"{aid}: unknown synth recipe '{recipe}' (want one of {sorted(RECIPES)})")
        prompt = asset.get("prompt", "")

        adir = out_root / aid
        (adir / "raw").mkdir(parents=True, exist_ok=True)
        keepers = [adir / f"{aid}_v{i:02d}.wav" for i in range(1, vars_ + 1)]
        if all(p.exists() for p in keepers) and not a.force:
            print(f"skip {aid} ({vars_} keepers exist)")
            continue

        # render long when looping so the tail can fold into the head
        render_secs = secs + (xfade if loop else 0.0)
        for i, final in enumerate(keepers, 1):
            seed = seed0 + (i - 1) * 977
            rng = np.random.default_rng(seed)
            x = RECIPES[recipe](rng, sr, render_secs)
            if loop:
                x = make_loop(x, sr, secs, xfade)
            raw_path = adir / "raw" / f"{aid}_v{i:02d}_raw.wav"
            write_wav(raw_path, x, sr)
            (adir / "raw" / f"{aid}_v{i:02d}.txt").write_text(
                f"{prompt}\nbackend=synth recipe={recipe} seed={seed} "
                f"seconds={secs}{' loop' if loop else ''}\n")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                post_tmp = Path(tf.name)
            try:
                ffmpeg_post(raw_path, post_tmp, sr, hp, fade_ms, loop)
                y, syr = read_wav(post_tmp)
                assert syr == sr, f"post resample mismatch {syr} != {sr}"
                write_wav(final, peak_normalize(y, peak_db), sr)
            finally:
                post_tmp.unlink(missing_ok=True)
            print(f"[{aid}] {final.name}  seed={seed}  {wav_dur(final):.2f}s")

        # audition mix: keepers back-to-back with 0.35 s gaps (the audio sheet)
        gap = np.zeros(int(sr * 0.35), dtype=np.float32)
        parts = []
        for f in keepers:
            y, _ = read_wav(f)
            parts += [y, gap]
        audition = adir / "audition.wav"
        write_wav(audition, np.concatenate(parts), sr)
        waveform_png(audition, adir / "waveform.png")

        game_keys = {f.name[:-4]: f.name for f in keepers}
        card = {
            "id": aid,
            "date": today,
            "engine": m.get("engine", "synth"),
            "rendered": f"synth/{recipe}",
            "sample_rate": sr,
            "loop": loop,
            "game_keys": game_keys,
            "seed": seed0,
            "copy_as": _Literal("\n".join(
                f"cp soundman/out/{aid}/{f.name} assets/sfx/{aid}/{f.name}"
                for f in keepers) + "\n"),
            "assets_snippet": _Literal("\n".join(
                f"{f.name[:-4]}: A+'sfx/{aid}/{f.name}'," for f in keepers) + "\n"),
            "listen_verify": (
                f"python3 present.py {aid} (pre-accept, voice announce + playback); "
                "post-accept playback check in cook2.html?debug (code side)"),
            "notes": ("variations round-robin under one game key so repeats don't "
                        f"machine-gun; prompt was: {prompt}"),
        }
        with open(adir / "intake.yaml", "w") as f:
            yaml.safe_dump(card, f, sort_keys=False)

        idx_path = out_root / "INDEX.yaml" if (out_root / "INDEX.yaml").exists() \
            else HERE / "INDEX.yaml"
        idx = yaml.safe_load(open(idx_path)) or {} if idx_path.exists() else {}
        idx[aid] = {"date": today, "files": [f.name for f in keepers],
                    "keys": list(game_keys), "loop": loop,
                    "backend": f"synth/{recipe}"}
        with open(idx_path, "w") as f:
            f.write("# SOUNDMAN INDEX — finished outbox ids (sound-written). "
                    "Code side: ls out/*/intake.yaml works just as well.\n")
            yaml.safe_dump(idx, f, sort_keys=True)
        print(f"   -> {adir.relative_to(HERE)}/ ({vars_} keepers, audition.wav, "
              f"waveform.png, intake.yaml)")

    if out_root == HERE / "out":
        sounds = {}
        for card_path in sorted((HERE / "out").glob("*/intake.yaml")):
            c = yaml.safe_load(open(card_path)) or {}
            if c.get("game_keys"):
                sounds[c.get("id", card_path.parent.name)] = {
                    "keepers": list(c["game_keys"].values()),
                    "audition": "audition.wav",
                    "loop": bool(c.get("loop", False))}
        (HERE / "out" / "sounds.json").write_text(
            json.dumps(sounds, indent=1, sort_keys=True) + "\n")

    print("done.")


if __name__ == "__main__":
    main()
