#!/usr/bin/env python
"""MOSS-SoundEffect v2.0 (OpenMOSS, Apache-2.0) text-to-audio — run INSIDE its venv:

    /workspace/tmp/audiogen/moss-tts/moss_soundeffect_v2/.venv/bin/python backends/moss_gen.py \
        --prompt "..." --seconds 6 --seed 1 --steps 100 --out x.wav

DiT 1.3B + flow matching + DAC VAE (48 kHz) + Qwen3-1.7B text encoder. Weights:
/workspace/tmp/audiogen/moss-v2 (downloaded from OpenMOSS-Team/MOSS-SoundEffect-v2.0).
"""
import argparse
import json
import time

import torch

WEIGHTS = "/workspace/tmp/audiogen/moss-v2"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seconds", type=float, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--cfg", type=float, default=4.0)
    ap.add_argument("--shift", type=float, default=5.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from moss_soundeffect_v2 import MossSoundEffectPipeline
    t0 = time.time()
    pipe = MossSoundEffectPipeline.from_pretrained(WEIGHTS, torch_dtype=torch.bfloat16, device="cuda")
    audio = pipe(a.prompt, seconds=float(a.seconds), num_inference_steps=a.steps, cfg_scale=a.cfg,
                 sigma_shift=a.shift, seed=a.seed)
    # write the WAV ourselves: pipe.save_audio -> torchaudio -> torchcodec, which wants ffmpeg 4-7 libs (host has 8)
    import wave
    import numpy as np
    wav = audio.detach().float().cpu()
    if wav.ndim == 3:
        wav = wav[0]
    if wav.ndim == 1:
        wav = wav[None]
    x = wav.numpy().T   # (T, C)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(a.out, "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(int(pipe.sample_rate)); w.writeframes(pcm.tobytes())
    print(json.dumps({"model": "moss_v2", "file": a.out, "seed": a.seed, "steps": a.steps, "cfg": a.cfg,
                      "seconds": a.seconds, "prompt": a.prompt, "secs_wall": round(time.time() - t0, 1)}))


if __name__ == "__main__":
    main()
