#!/usr/bin/env python
"""Train a style LoRA on the keepers in out/ using ComfyUI's built-in trainer.

    .venv/bin/python train.py --name dinerart_v1 --steps 500 --rank 16 --lr 1e-4

Dataset = every out/<id>/<name>.png that exists (a keeper) -> its raw render out/<id>/raw/<name>.png,
padded to a white 1024x1024 square, captioned "<trigger>, <asset prompt>, <state>".
The finished LoRA is copied to ComfyUI models/loras/<name>.safetensors.
"""
import argparse, os, shutil, sys, time
from pathlib import Path
import yaml
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import HERE, run_graph, COMFY  # noqa

COMFY_DIR = Path(os.environ.get("COMFY_DIR", "/workspace/tmp/ComfyUI"))

ap = argparse.ArgumentParser()
ap.add_argument("--name", default="dinerart_v1")
ap.add_argument("--trigger", default="dnrart style")
ap.add_argument("--steps", type=int, default=500)
ap.add_argument("--rank", type=int, default=16)
ap.add_argument("--lr", type=float, default=1e-4)
ap.add_argument("--batch", type=int, default=1)
ap.add_argument("--size", type=int, default=768)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--ckpt-depth", type=int, default=2, help="gradient checkpointing depth (higher = less VRAM)")
ap.add_argument("--offload", action="store_true", help="offload to CPU RAM (slow, lowest VRAM)")
ap.add_argument("--dry", action="store_true", help="only build the dataset")
a = ap.parse_args()

m = yaml.safe_load(open(HERE / "manifest.yaml"))
cfg = m["comfy"]
ds = COMFY_DIR / "input" / f"lora_{a.name}"
shutil.rmtree(ds, ignore_errors=True); ds.mkdir(parents=True)

n = 0
for asset in m["assets"]:
    aid = asset["id"]
    for state, text in (asset.get("states") or {"": ""}).items():
        name = f"{aid}_{state}" if state else aid
        final, raw = HERE / "out" / aid / f"{name}.png", HERE / "out" / aid / "raw" / f"{name}.png"
        if not (final.exists() and raw.exists()):
            continue
        im = Image.open(raw).convert("RGB")
        s = max(im.size)
        sq = Image.new("RGB", (s, s), (255, 255, 255)); sq.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
        sq.resize((a.size, a.size), Image.LANCZOS).save(ds / f"{name}.png")
        cap = f"{a.trigger}, a single isolated 2D casual cooking game asset: {asset['prompt']}"
        if text: cap += f", {text}"
        cap += ", glossy cel-shaded cartoon, 3/4 elevated view, on a plain white background"
        (ds / f"{name}.txt").write_text(cap)
        n += 1
print(f"dataset: {n} images in {ds}")
if a.dry or n == 0:
    sys.exit(0)

g = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": cfg["model"], "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": cfg["text_encoder"], "type": "flux2", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": cfg["vae"]}},
    "4": {"class_type": "LoadImageTextDataSetFromFolder", "inputs": {"folder": ds.name}},
    "5": {"class_type": "MakeTrainingDataset", "inputs": {"images": ["4", 0], "texts": ["4", 1], "vae": ["3", 0], "clip": ["2", 0]}},
    "6": {"class_type": "TrainLoraNode", "inputs": {
        "model": ["1", 0], "latents": ["5", 0], "positive": ["5", 1],
        "batch_size": a.batch, "grad_accumulation_steps": 1, "steps": a.steps, "learning_rate": a.lr,
        "rank": a.rank, "optimizer": "AdamW", "loss_function": "MSE", "seed": a.seed,
        "training_dtype": "bf16", "lora_dtype": "bf16", "quantized_backward": False, "algorithm": "LoRA",
        "gradient_checkpointing": True, "checkpoint_depth": a.ckpt_depth, "offloading": a.offload,
        "existing_lora": "[None]", "bucket_mode": False, "bypass_mode": False}},
    "7": {"class_type": "SaveLoRA", "inputs": {"lora": ["6", 0], "prefix": f"loras/{a.name}"}},
}
print(f"training {a.name}: steps={a.steps} rank={a.rank} lr={a.lr} ... (watch ComfyUI log for progress)")
t = time.time()
run_graph(g)
outs = sorted((COMFY_DIR / "output" / "loras").glob(f"{a.name}_*.safetensors"), key=os.path.getmtime)
if not outs:
    sys.exit("training finished but no LoRA file found in ComfyUI output/loras")
dst = COMFY_DIR / "models" / "loras" / f"{a.name}.safetensors"
dst.parent.mkdir(exist_ok=True)
shutil.copy(outs[-1], dst)
print(f"done in {(time.time()-t)/60:.1f} min -> {dst}")
