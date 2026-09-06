#!/usr/bin/env python
"""AudioX-Turbo (HKUST) text-to-audio, 4-step distilled — run INSIDE its venv from the
repo dir (configs/ are relative there):

    cd /workspace/tmp/audiogen/audiox-turbo && .venv/bin/python \
        /workspace/vibe-arcade/soundman/backends/audiox_gen.py --prompt "..." --seconds 6 --seed 1 --out x.wav

License: CC-BY-NC-4.0 (non-commercial) — flagged in the compare sheet.
"""
import argparse
import json
import os
import time
from pathlib import Path

import torch
from einops import rearrange

REPO = Path("/workspace/tmp/audiogen/audiox-turbo")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seconds", type=float, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.chdir(REPO)

    from audiox_turbo.inference import load_audiox_turbo_model
    from audiox_turbo.inference.generation import generate_diffusion_cond_dmd
    from audiox_turbo.data.utils import load_and_process_audio

    t0 = time.time()
    device = "cuda"
    model, cfg = load_audiox_turbo_model(
        "configs/audiox_turbo_infer_4step.json", "checkpoints/audiox_turbo/audiox_turbo.ckpt",
        pretransform_ckpt_path="checkpoints/pretransform/vae.ckpt", device=device)
    sr = cfg["sample_rate"]; sample_size = cfg["sample_size"]; fps = cfg.get("video_fps", 5)
    secs = 10   # the conditioner's temporal embedding is fixed at 50 frames = 10 s @ 5 fps; render 10 s, trim below
    video_tensor = torch.zeros(secs * fps, 3, 224, 224)
    sync_features = torch.zeros(1, 240, 768, device=device)
    audio_tensor = load_and_process_audio(None, sr, 0, secs)
    conditioning = [{
        "video_prompt": {"video_tensors": video_tensor.unsqueeze(0), "video_sync_frames": sync_features},
        "text_prompt": a.prompt, "audio_prompt": audio_tensor.unsqueeze(0),
        "seconds_start": 0, "seconds_total": secs}]
    out = generate_diffusion_cond_dmd(model, steps=a.steps, conditioning=conditioning, sample_size=sample_size,
                                      seed=a.seed, device=device)
    out = rearrange(out, "b d n -> d (b n)").float().cpu()
    out = out[:, : int(sr * a.seconds)]
    # write the WAV ourselves: torchaudio.save -> torchcodec, which wants ffmpeg 4-7 libs (host has 8)
    import wave
    import numpy as np
    x = out.numpy().T if out.dim() == 2 else out.numpy()[:, None]   # (T, C)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(a.out, "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(int(sr)); w.writeframes(pcm.tobytes())
    print(json.dumps({"model": "audiox_turbo", "file": a.out, "seed": a.seed, "steps": a.steps, "seconds": a.seconds,
                      "prompt": a.prompt, "secs_wall": round(time.time() - t0, 1), "sr": sr}))


if __name__ == "__main__":
    main()
