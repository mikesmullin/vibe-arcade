#!/usr/bin/env python
"""assetgen: manifest.yaml -> ComfyUI (FLUX.2 klein) -> transparent PNG sprites.

    .venv/bin/python run.py                 # everything in manifest.yaml
    .venv/bin/python run.py patty grill     # only these asset ids
    .venv/bin/python run.py --no-refs patty # ignore style refs (pure txt2img)
    .venv/bin/python run.py --force ...     # regenerate even if output exists
"""
import argparse, io, json, os, sys, time, uuid
from pathlib import Path

import requests, yaml
from PIL import Image

HERE = Path(__file__).resolve().parent
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")


# ----------------------------------------------------------------- comfy api
def upload(path: Path, subfolder="assetgen") -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{COMFY}/upload/image",
                          files={"image": (path.name, f, "image/png")},
                          data={"subfolder": subfolder, "overwrite": "true"})
    r.raise_for_status()
    j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def run_graph(graph: dict) -> list[Image.Image]:
    cid = uuid.uuid4().hex
    r = requests.post(f"{COMFY}/prompt", json={"prompt": graph, "client_id": cid})
    if r.status_code != 200:
        sys.exit(f"ComfyUI rejected graph: {r.text[:2000]}")
    pid = r.json()["prompt_id"]
    while True:
        h = requests.get(f"{COMFY}/history/{pid}").json()
        if pid in h:
            break
        time.sleep(0.4)
    st = h[pid].get("status", {})
    if st.get("status_str") == "error":
        sys.exit("ComfyUI error: " + json.dumps(st.get("messages"), indent=1)[:3000])
    out = []
    for node in h[pid]["outputs"].values():
        for im in node.get("images", []):
            b = requests.get(f"{COMFY}/view", params={"filename": im["filename"],
                             "subfolder": im["subfolder"], "type": im["type"]}).content
            out.append(Image.open(io.BytesIO(b)).convert("RGB"))
    return out


# ------------------------------------------------------------- graph builder
def build_graph(cfg, prompt, seed, w, h, refs=(), init=None, denoise=1.0, prefix="assetgen/x", lora=None):
    """FLUX.2 klein: txt2img, optionally with reference images (style / previous state)
    and optionally an init image (img2img) for stronger silhouette lock."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": cfg["model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": cfg["text_encoder"], "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": cfg["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
    }
    model = ["1", 0]
    if lora and lora.get("name"):
        g["0"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": lora["name"], "strength_model": lora.get("strength", 0.8)}}
        model = ["0", 0]
    pos = ["4", 0]
    n = 10
    for ref in refs:
        g[str(n)] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        g[str(n + 1)] = {"class_type": "ImageScaleToTotalPixels",
                         "inputs": {"image": [str(n), 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 1}}
        g[str(n + 2)] = {"class_type": "VAEEncode", "inputs": {"pixels": [str(n + 1), 0], "vae": ["3", 0]}}
        g[str(n + 3)] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [str(n + 2), 0]}}
        pos = [str(n + 3), 0]
        n += 4
    if init:
        g["6"] = {"class_type": "LoadImage", "inputs": {"image": init}}
        g["7"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["6", 0], "vae": ["3", 0]}}
        latent = ["7", 0]
    else:
        g["6"] = {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
        latent = ["6", 0]
    g["8"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": pos, "negative": ["5", 0], "latent_image": latent,
        "seed": seed, "steps": cfg.get("steps", 4), "cfg": cfg.get("cfg", 1.0),
        "sampler_name": "euler", "scheduler": "simple", "denoise": denoise}}
    g["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}}
    g["99"] = {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}}
    return g


# ------------------------------------------------------------ post-process
_session = None
def cutout(im: Image.Image, pad=24, export=None, fmt="png") -> Image.Image:
    global _session
    from rembg import new_session, remove
    if _session is None:
        _session = new_session("isnet-general-use")
    rgba = remove(im, session=_session, post_process_mask=True)
    a = rgba.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    box = a.getbbox()
    if box:
        l, t, r, b = box
        rgba = rgba.crop((max(0, l - pad), max(0, t - pad), min(rgba.width, r + pad), min(rgba.height, b + pad)))
    if export:
        rgba.thumbnail((export, export), Image.LANCZOS)
    return rgba


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--manifest", default=HERE / "manifest.yaml")
    ap.add_argument("--no-refs", action="store_true", help="skip style reference images")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", help="override output dir (e.g. for A/B runs)")
    ap.add_argument("--lora", help="LoRA file in ComfyUI models/loras (overrides manifest comfy.lora.name)")
    ap.add_argument("--lora-strength", type=float)
    ap.add_argument("--no-lora", action="store_true")
    ap.add_argument("--steps", type=int, help="override sampler steps")
    ap.add_argument("--seed-offset", type=int, default=0, help="add to every seed (quick re-roll)")
    a = ap.parse_args()

    m = yaml.safe_load(open(a.manifest))
    cfg, style = m["comfy"], m["style"]
    if a.steps: cfg["steps"] = a.steps
    lora = None if a.no_lora else dict(cfg.get("lora") or {})
    if lora is not None and a.lora: lora["name"] = a.lora
    if lora is not None and a.lora_strength is not None: lora["strength"] = a.lora_strength
    if lora and lora.get("name"): print(f"LoRA: {lora['name']} @ {lora.get('strength', 0.8)}")
    trigger = (lora or {}).get("trigger", "") if lora and lora.get("name") else ""
    out_root = HERE / (a.out or m.get("out", "out"))
    style_refs = [] if a.no_refs else [upload(HERE / p) for p in style.get("refs", [])]
    ref_clause = style.get("ref_clause", "") if style_refs else ""

    assets = [x for x in m["assets"] if not a.ids or x["id"] in a.ids]
    if not assets:
        sys.exit("no matching assets")
    t0 = time.time()
    for asset in assets:
        aid = asset["id"]
        states = asset.get("states") or {"": ""}
        chain = asset.get("chain", "edit")
        size = asset.get("size", 1024)
        w, h = (size, size) if isinstance(size, int) else size
        seed = asset.get("seed", 0) + a.seed_offset
        adir = out_root / aid
        (adir / "raw").mkdir(parents=True, exist_ok=True)
        asset_refs = [] if a.no_refs else [upload(HERE / p) for p in asset.get("refs", [])]
        prev_raw = None
        for i, (state, state_text) in enumerate(states.items()):
            name = f"{aid}_{state}" if state else aid
            final = adir / f"{name}.png"
            raw_path = adir / "raw" / f"{name}.png"
            if final.exists() and not a.force:
                print(f"skip {name} (exists)"); prev_raw = raw_path; continue

            obj = asset["prompt"] + (", " + state_text if state_text else "")
            refs, init, denoise = style_refs + asset_refs, None, 1.0
            if i > 0 and prev_raw and chain != "none":
                refs.append(upload(prev_raw))
                prompt = style["state_template"].format(object=obj, state=state_text,
                                                         ref_clause=ref_clause)
                if chain == "img2img":
                    init = refs[-1]
                    denoise = asset.get("denoise", 0.6)
            else:
                prompt = style["template"].format(object=obj, ref_clause=ref_clause)
            if asset.get("suffix"):
                prompt += " " + asset["suffix"]
            if trigger:
                prompt = trigger + ", " + prompt

            print(f"[{aid}] {name}  seed={seed}  refs={len(refs)}  {w}x{h}")
            t = time.time()
            imgs = run_graph(build_graph(cfg, prompt, seed, w, h, refs, init, denoise,
                                         prefix=f"assetgen/{aid}/{name}", lora=lora))
            imgs[0].save(raw_path)
            sprite = cutout(imgs[0], export=asset.get("export"))
            sprite.save(final)
            (adir / "raw" / f"{name}.txt").write_text(prompt + f"\nseed={seed}\n")
            print(f"   -> {final.relative_to(HERE)}  {sprite.size}  {time.time()-t:.1f}s")
            prev_raw = raw_path
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
