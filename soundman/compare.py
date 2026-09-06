#!/usr/bin/env python
"""compare.py — one prompt, every installed text-to-SFX model, side by side.

    python3 compare.py --id sfx_soda_pour_loop [--models sa3_small_sfx,tangoflux,...] \
        [--seeds 1,2] [--out scratch/models_compare] [--seconds 6]

For each model: render raw takes (native rate/channels) into
<out>/<id>/<model>/raw/, post them the soundman way (mono 48 kHz, highpass 80,
peak -1 dB, loop crossfade if the manifest says loop) into <out>/<id>/<model>/,
then build <out>/<id>/audition.wav (model by model, 0.5 s gaps, in the order of
SHEET.md) + waveform.png + SHEET.md (model, license, wall time, meters).

Models live outside the repo (see backends/*.py headers):
    sa3_small_sfx / sa3_small_sfx_base / sa3_medium / sao1   ComfyUI API (:8188)
    tangoflux                                                 /workspace/tmp/audiogen/tangoflux
    moss_v2                                                   /workspace/tmp/audiogen/moss-tts
    audiox_turbo                                              /workspace/tmp/audiogen/audiox-turbo
Everything under scratch/ is audition-only; nothing is approved or referenced.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run import ffmpeg_post, make_loop, peak_normalize, read_wav, write_wav, waveform_png  # noqa: E402
from backends import comfy_sa  # noqa: E402

AG = Path("/workspace/tmp/audiogen")
MODELS = {
    "sa3_small_sfx": {"kind": "comfy", "license": "Stability Community (commercial <$1M/yr)", "steps": 50},
    "sa3_small_sfx_base": {"kind": "comfy", "license": "Stability Community (commercial <$1M/yr)", "steps": 50},
    "sa3_medium": {"kind": "comfy", "license": "Stability Community (commercial <$1M/yr)", "steps": 50},
    "sao1": {"kind": "comfy", "license": "Stability Community (commercial <$1M/yr)", "steps": 100},
    "tangoflux": {"kind": "venv", "python": AG / "tangoflux/bin/python", "script": HERE / "backends/tangoflux_gen.py",
                  "license": "NON-COMMERCIAL research only (SAO terms)", "steps": 50},
    "moss_v2": {"kind": "venv", "python": AG / "moss-tts/moss_soundeffect_v2/.venv/bin/python", "script": HERE / "backends/moss_gen.py",
                "license": "Apache-2.0", "steps": 100},
    "audiox_turbo": {"kind": "venv", "python": AG / "audiox-turbo/.venv/bin/python", "script": HERE / "backends/audiox_gen.py",
                     "license": "CC-BY-NC-4.0 (NON-COMMERCIAL)", "steps": 4},
}


def meters(x, sr):
    F = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / sr)
    cent = float((F * fr).sum() / (F.sum() + 1e-9))
    rms = 20 * np.log10(float(np.sqrt((x ** 2).mean())) + 1e-9)
    peak = 20 * np.log10(float(np.abs(x).max()) + 1e-9)
    return {"centroid_hz": int(round(cent)), "rms_db": float(round(rms, 1)), "crest_db": float(round(peak - rms, 1))}   # plain floats: yaml.safe_dump chokes on np.float64


def render_one(model, prompt, negative, seconds, seed, raw_out, steps=None, cfg=None):
    m = MODELS[model]
    steps = int(steps or m["steps"])
    if m["kind"] == "comfy":
        return comfy_sa.generate(model, prompt, seconds, seed, raw_out, negative=negative, steps=steps, cfg=cfg, quiet=True)
    cmd = [str(m["python"]), str(m["script"]), "--prompt", prompt, "--seconds", str(seconds), "--seed", str(seed),
           "--steps", str(steps), "--out", str(raw_out)]
    if cfg is not None and model == "moss_v2":
        cmd += ["--cfg", str(cfg)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{model} failed:\n{r.stderr[-2000:]}")
    line = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
    return json.loads(line[-1]) if line else {"model": model, "file": str(raw_out)}


def post(raw_path, final_path, sr, hp, fade_ms, peak_db, loop, secs, xfade):
    """Same post as run.py: ffmpeg highpass (+fade for one-shots), mono 48k, loop splice, peak-normalize."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        ffmpeg_post(raw_path, tmp, sr, hp, fade_ms, loop)
        y, syr = read_wav(tmp)
        if loop:
            need = int(sr * (secs + xfade))
            if len(y) < need:   # model rendered exactly `secs`: fold a copy so the splice has material
                y = np.concatenate([y, y])[:need]
            y = make_loop(y, sr, secs, xfade)
        write_wav(final_path, peak_normalize(y, peak_db), sr)
    finally:
        tmp.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="manifest asset id (prompt/seconds/loop come from it)")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--prompt", help="override the manifest prompt")
    ap.add_argument("--negative", default="")
    ap.add_argument("--out", default="scratch/models_compare")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--no-announce", action="store_true", help="skip the 'Sounds ready.' voice line")
    a = ap.parse_args()

    man = yaml.safe_load(open(HERE / "manifest.yaml"))
    asset = next((x for x in man["assets"] if x["id"] == a.id), None)
    if not asset:
        sys.exit(f"unknown id {a.id}")
    sr = int(man.get("sample_rate", 48000)); postc = man.get("post", {})
    hp = int(postc.get("highpass", 80)); fade_ms = float(postc.get("fade_out_ms", 12))
    peak_db = float(postc.get("peak_db", -1.0)); xfade = float(postc.get("loop_xfade", 0.5))
    loop = bool(asset.get("loop", False)); secs = a.seconds or float(asset["seconds"])
    prompt = a.prompt or asset["prompt"]
    render_secs = secs + (xfade if loop else 0.0)
    models = [m for m in a.models.split(",") if m]
    seeds = [int(s) for s in a.seeds.split(",")]
    root = (HERE / a.out / a.id); root.mkdir(parents=True, exist_ok=True)

    old_rows = json.loads((root / "rows.json").read_text()) if (root / "rows.json").exists() else []
    rows = []
    for model in models:
        if model not in MODELS:
            print(f"skip unknown model {model}"); continue
        mdir = root / model; (mdir / "raw").mkdir(parents=True, exist_ok=True)
        for si, seed in enumerate(seeds, 1):
            raw = mdir / "raw" / f"{a.id}_{model}_v{si:02d}_raw.wav"
            final = mdir / f"{a.id}_{model}_v{si:02d}.wav"
            if a.skip_existing and final.exists():
                prev = next((r for r in old_rows if r.get("model") == model and r.get("take") == si), None)
                print(f"skip {final.name}"); rows.append(prev or {"model": model, "take": si, "file": str(final.relative_to(HERE)), "cached": True}); continue
            t0 = time.time()
            try:
                info = render_one(model, prompt, a.negative, render_secs, seed, raw)
            except Exception as e:  # keep going: one broken backend must not kill the sheet
                print(f"[{model}] FAILED: {str(e)[-800:]}")
                rows.append({"model": model, "take": si, "error": str(e)[-300:]}); continue
            post(raw, final, sr, hp, fade_ms, peak_db, loop, secs, xfade)
            y, _ = read_wav(final)
            row = {"model": model, "take": si, "seed": seed, "file": str(final.relative_to(HERE)), "license": MODELS[model]["license"],
                   "secs_wall": round(time.time() - t0, 1), "steps": info.get("steps"), **meters(y, sr)}
            rows.append(row)
            print(f"[{model}] v{si:02d} {row['secs_wall']}s  centroid {row['centroid_hz']} Hz  crest {row['crest_db']} dB")

    # merge with earlier runs: rows for (model, take) not rendered this time survive, in MODELS order
    touched = {(r["model"], r["take"]) for r in rows}
    rows = rows + [r for r in old_rows if (r.get("model"), r.get("take")) not in touched]
    order = {m: i for i, m in enumerate(MODELS)}
    rows.sort(key=lambda r: (order.get(r.get("model"), 99), r.get("take", 0)))
    # audition: every successful take, model by model, 0.5 s gaps
    gap = np.zeros(int(sr * 0.5), dtype=np.float32); parts = []
    for r in rows:
        if r.get("file"):
            y, _ = read_wav(HERE / r["file"]); parts += [y, gap]
    if parts:
        write_wav(root / "audition.wav", np.concatenate(parts), sr)
        waveform_png(root / "audition.wav", root / "waveform.png")
    sheet = [f"# model compare — {a.id} — {date.today().isoformat()}", "",
             f"prompt: {prompt}", f"seconds: {secs}  loop: {loop}  seeds: {seeds}", "",
             "| # | model | take | wall s | steps | centroid Hz | crest dB | license | file |", "|---|---|---|---|---|---|---|---|---|"]
    n = 0
    for r in rows:
        if r.get("file"):
            n += 1
            sheet.append(f"| {n} | {r['model']} | v{r['take']:02d} | {r.get('secs_wall','')} | {r.get('steps','')} | {r.get('centroid_hz','')} | {r.get('crest_db','')} | {r.get('license','')} | {r['file']} |")
        else:
            sheet.append(f"| – | {r['model']} | v{r['take']:02d} | FAILED | | | | | {r.get('error','')} |")
    sheet += ["", "audition.wav = the rows above in order, 0.5 s gaps. Scratch only — nothing here is approved."]
    (root / "SHEET.md").write_text("\n".join(sheet) + "\n")
    (root / "rows.json").write_text(json.dumps(rows, indent=1))
    # desk listing: each model becomes a "sound" so daw.html?src=<out>/<id> can A/B them with the automation
    sounds = {}
    for r in rows:
        if r.get("file"):
            sounds.setdefault(r["model"], {"keepers": [], "audition": None, "loop": loop, "model": r["model"], "prompt": prompt,
                                           "params": asset.get("params"), "layers": asset.get("layers")})["keepers"].append(Path(r["file"]).name)
    for m, e in sounds.items():
        gap = np.zeros(int(sr * 0.35), dtype=np.float32); parts = []
        for f in e["keepers"]:
            y, _ = read_wav(root / m / f); parts += [y, gap]
        write_wav(root / m / "audition.wav", np.concatenate(parts), sr); e["audition"] = "audition.wav"
    (root / "sounds.json").write_text(json.dumps(sounds, indent=1, sort_keys=True) + "\n")
    print(f"-> {root.relative_to(HERE)}/ (SHEET.md, audition.wav, waveform.png)")
    if not a.no_announce and any(r.get("file") and not r.get("cached") for r in rows):
        try:
            from present import announce
            announce("Sounds ready.", "alan")   # the whole voice ritual now: one line per batch
        except Exception as e:
            print("announce failed:", e)


if __name__ == "__main__":
    main()
