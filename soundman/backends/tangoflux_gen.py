#!/usr/bin/env python
"""TangoFlux (declare-lab) text-to-audio — run INSIDE its venv:

    /workspace/tmp/audiogen/tangoflux/bin/python backends/tangoflux_gen.py \
        --prompt "..." --seconds 6 --seed 1 --steps 50 --out scratch/x.wav

44.1 kHz stereo out (we downmix later in the runner). Weights auto-download to the
HF cache on first run (~4 GB + FLAN-T5). License: non-commercial research
(Stable Audio Open terms) — flagged in the compare sheet.
"""
import argparse
import json
import time

import torch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seconds", type=float, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--guidance", type=float, default=4.5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="declare-lab/TangoFlux")
    a = ap.parse_args()

    from tangoflux import TangoFluxInference
    t0 = time.time()
    model = TangoFluxInference(name=a.name, device="cuda")
    torch.manual_seed(a.seed)
    # generate() has no seed and inference_flow() re-seeds to 0 every call -> call the flow directly
    with torch.no_grad():
        latents = model.model.inference_flow(a.prompt, duration=a.seconds, num_inference_steps=a.steps,
                                             guidance_scale=a.guidance, seed=a.seed, disable_progress=True)
        audio = model.vae.decode(latents.transpose(2, 1)).sample.cpu()[0]
    audio = audio[:, : int(a.seconds * model.vae.config.sampling_rate)]
    if not torch.is_tensor(audio):
        audio = torch.as_tensor(audio)
    audio = audio.detach().float().cpu()
    if audio.dim() == 1:
        audio = audio[None]
    if audio.shape[0] > audio.shape[-1]:
        audio = audio.T
    out, sr = audio, 44100
    # write the WAV ourselves: torchaudio.save -> torchcodec, which wants ffmpeg 4-7 libs (host has 8)
    import wave
    import numpy as np
    x = out.numpy().T if out.dim() == 2 else out.numpy()[:, None]   # (T, C)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(a.out, "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(int(sr)); w.writeframes(pcm.tobytes())
    dt = time.time() - t0
    print(json.dumps({"model": "tangoflux", "file": a.out, "seed": a.seed, "steps": a.steps, "guidance": a.guidance,
                      "seconds": a.seconds, "prompt": a.prompt, "secs_wall": round(dt, 1), "sr": 44100}))


if __name__ == "__main__":
    main()
