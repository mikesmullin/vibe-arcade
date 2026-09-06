#!/usr/bin/env python
"""Stable Audio (3 small-sfx / 3 medium / Open 1.0) through the ComfyUI API.

Builds the API graph in code (no saved workflow JSON), POSTs it to /prompt,
polls /history, and pulls the rendered WAV via /view. ComfyUI is assumed to be
running (the art side's instance is fine — it shares the GPU by unloading models
as needed). Nothing here touches the game.

    python3 backends/comfy_sa.py --model sa3_small_sfx --prompt "..." --seconds 6 \
        --seed 1 --out scratch/x.wav [--steps 50 --cfg 7 --negative "..."]

Models (files under ComfyUI/models/):
    sa3_small_sfx       checkpoints/stable_audio_3_small_sfx.safetensors      + text_encoders/t5gemma_b_b_ul2.safetensors
    sa3_small_sfx_base  checkpoints/stable_audio_3_small_sfx_base.safetensors + same encoder
    sa3_medium          checkpoints/stable_audio_3_medium.safetensors         + same encoder
    sao1                checkpoints/stable-audio-open-1.0.safetensors         (encoder inside the checkpoint)
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HOST = "http://127.0.0.1:8188"

MODELS = {
    "sa3_small_sfx": {"ckpt": "stable_audio_3_small_sfx.safetensors", "clip": "t5gemma_b_b_ul2.safetensors",
                      "steps": 50, "cfg": 7.0, "sampler": "euler", "scheduler": "simple"},
    "sa3_small_sfx_base": {"ckpt": "stable_audio_3_small_sfx_base.safetensors", "clip": "t5gemma_b_b_ul2.safetensors",
                           "steps": 50, "cfg": 7.0, "sampler": "euler", "scheduler": "simple"},
    "sa3_medium": {"ckpt": "stable_audio_3_medium.safetensors", "clip": "t5gemma_b_b_ul2.safetensors",
                   "steps": 50, "cfg": 7.0, "sampler": "euler", "scheduler": "simple"},
    "sao1": {"ckpt": "stable-audio-open-1.0.safetensors", "clip": "t5_base.safetensors",   # google-t5/t5-base model.safetensors
             "steps": 100, "cfg": 7.0, "sampler": "dpmpp_3m_sde_gpu", "scheduler": "exponential"},
}


def api(path, data=None):
    req = urllib.request.Request(HOST + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def build_graph(m, prompt, negative, seconds, seed, steps, cfg, sampler, scheduler, prefix):
    g = {}
    g["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": m["ckpt"]}}
    clip = ["1", 1]
    if m["clip"]:
        g["2"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": m["clip"], "type": "stable_audio"}}
        clip = ["2", 0]
    g["3"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip}}
    g["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": clip}}
    g["5"] = {"class_type": "ConditioningStableAudio",
              "inputs": {"positive": ["3", 0], "negative": ["4", 0], "seconds_start": 0.0, "seconds_total": float(seconds)}}
    g["6"] = {"class_type": "EmptyLatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}}
    g["7"] = {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "seed": int(seed), "steps": int(steps), "cfg": float(cfg),
        "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
        "positive": ["5", 0], "negative": ["5", 1], "latent_image": ["6", 0]}}
    g["8"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}}
    g["9"] = {"class_type": "SaveAudio", "inputs": {"audio": ["8", 0], "filename_prefix": prefix}}
    return g


def generate(model, prompt, seconds, seed, out, negative="", steps=None, cfg=None, sampler=None, scheduler=None,
             timeout=900, quiet=False):
    m = MODELS[model]
    steps = steps or m["steps"]; cfg = cfg if cfg is not None else m["cfg"]
    sampler = sampler or m["sampler"]; scheduler = scheduler or m["scheduler"]
    prefix = f"soundman/{model}_{uuid.uuid4().hex[:8]}"
    graph = build_graph(m, prompt, negative, seconds, seed, steps, cfg, sampler, scheduler, prefix)
    t0 = time.time()
    r = api("/prompt", {"prompt": graph, "client_id": "soundman"})
    pid = r["prompt_id"]
    while True:
        h = api(f"/history/{pid}")
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error" or not st.get("completed", True):
                msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                raise SystemExit(f"comfy error: {json.dumps(msgs)[:1500]}")
            outs = h[pid]["outputs"]
            break
        if time.time() - t0 > timeout:
            raise SystemExit("comfy timeout")
        time.sleep(0.5)
    files = []
    for node in outs.values():
        for a in node.get("audio", []):
            files.append(a)
    if not files:
        raise SystemExit(f"comfy: no audio output: {json.dumps(outs)[:500]}")
    a = files[0]
    q = urllib.parse.urlencode({"filename": a["filename"], "subfolder": a.get("subfolder", ""), "type": a.get("type", "output")})
    with urllib.request.urlopen(HOST + "/view?" + q, timeout=120) as resp:
        data = resp.read()
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    # SaveAudio writes FLAC; keep the bytes exact and let the caller transcode (ffmpeg) if it wants wav
    if a["filename"].lower().endswith(".flac") and out.suffix.lower() == ".wav":
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tf:
            tf.write(data); tmp = tf.name
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, str(out)], check=True)
        Path(tmp).unlink(missing_ok=True)
    else:
        out.write_bytes(data)
    dt = time.time() - t0
    if not quiet:
        print(f"[{model}] {out} seed={seed} steps={steps} cfg={cfg} {dt:.1f}s")
    return {"model": model, "file": str(out), "seed": seed, "steps": steps, "cfg": cfg, "sampler": sampler,
            "scheduler": scheduler, "seconds": seconds, "prompt": prompt, "negative": negative, "secs_wall": round(dt, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(MODELS), required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="")
    ap.add_argument("--seconds", type=float, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--cfg", type=float)
    ap.add_argument("--sampler")
    ap.add_argument("--scheduler")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    info = generate(a.model, a.prompt, a.seconds, a.seed, a.out, a.negative, a.steps, a.cfg, a.sampler, a.scheduler)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
