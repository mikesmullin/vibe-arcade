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
def chroma_key(im: Image.Image, key=None, tol=70, soft=50) -> Image.Image:
    """Flat-colour background removal with despill. key defaults to the median colour of the image corners (the
    model rarely paints the exact colour asked for). Works for green or magenta backdrops: pick the backdrop colour
    that is NOT in the object (green jacket -> magenta backdrop)."""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    if key is None:
        h, w = a.shape[:2]; m = max(4, min(h, w) // 25)
        corners = np.concatenate([a[:m, :m].reshape(-1, 3), a[:m, -m:].reshape(-1, 3), a[-m:, :m].reshape(-1, 3), a[-m:, -m:].reshape(-1, 3)])
        key = tuple(np.median(corners, axis=0))
    key = np.array(key, dtype=np.float32)
    d = np.sqrt(((a - key) ** 2).sum(-1))
    alpha = np.clip((d - tol) / soft, 0, 1)
    # channels that are "high" in the key colour (G for green, R+B for magenta) vs the rest
    hi = [i for i in range(3) if key[i] > 128] or [int(np.argmax(key))]
    lo = [i for i in range(3) if i not in hi] or [int(np.argmin(key))]
    dominance = a[..., hi].min(-1) - a[..., lo].max(-1)
    # drop pixels where the key hue dominates (darker shadows painted on the backdrop)
    alpha = np.minimum(alpha, np.clip((38 - dominance) / 16, 0, 1))
    # a pixel that does not lean toward the key hue at all is never background, however close it is in RGB
    # distance (dark brown skin vs a muted green backdrop was coming out 80% opaque)
    alpha = np.where(dominance <= 0, 1.0, alpha)
    # despill: pull the key channels down to the max of the other channels where they dominate, on soft edges only
    lim = a[..., lo].max(-1)
    for i in hi:
        a[..., i] = np.minimum(a[..., i], lim + (a[..., i] - lim) * alpha)
    out = np.dstack([a, alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def trim_neck(rgba: Image.Image, max_neck=0.62, zone=0.4, jaw=1.12, below=0.06) -> Image.Image:
    """Erase a neck under a head. The neck's waist is a local minimum of the row widths in the bottom `zone` of the
    silhouette with at least `below` of the image height still below it (a chin tip has nothing below). If that
    waist is narrower than `max_neck` of the widest row, everything from the jaw line (first row above the waist
    that is `jaw` times wider) downwards is erased."""
    import numpy as np
    a = np.asarray(rgba).copy()
    alpha = a[..., 3] > 40
    rows = np.where(alpha.any(1))[0]
    if len(rows) == 0:
        return rgba
    H = a.shape[0]
    w = alpha.sum(1).astype(np.float32)
    k = max(2, H // 200); ws = np.convolve(w, np.ones(2 * k + 1) / (2 * k + 1), mode="same")   # smoothed
    top, bot = rows.min(), rows.max()
    maxw = w[top:bot + 1].max()
    z0 = int(bot - (bot - top) * zone)
    win = max(3, int(H * 0.03))
    waist = None
    for y in range(z0, bot - int(below * H)):
        seg = ws[max(top, y - win):y + win + 1]
        if ws[y] <= seg.min() + 0.5 and ws[y] < max_neck * maxw:
            waist = y; break                     # topmost qualifying waist = closest to the jaw
    if waist is None:
        return rgba
    y = waist
    while y > top and ws[y] < ws[waist] * jaw:
        y -= 1
    a[y + 1:, :, 3] = 0
    print(f"   trim_neck: cut {bot - y} rows below the jaw (neck waist {ws[waist]:.0f}px of {maxw:.0f}px)")
    return Image.fromarray(a, "RGBA")


def skin_match(rgba: Image.Image, ref_path, tol=48, soft=30) -> Image.Image:
    """Recolour skin-coloured pixels of a body sprite so they match the face tone of a head sprite.
    The body's own skin tone is sampled from the top of its silhouette (the neck), the target from the head's
    centre; a per-channel gain is applied to pixels near the body's skin colour, with a soft falloff."""
    import numpy as np
    a = np.asarray(rgba.convert("RGBA")).astype(np.float32)
    h = np.asarray(Image.open(ref_path).convert("RGBA")).astype(np.float32)
    # head: median of opaque pixels in the central third
    H, W = h.shape[:2]; c = h[H // 3:2 * H // 3, W // 3:2 * W // 3]; c = c[c[..., 3] > 200][..., :3]
    target = np.median(c, axis=0)
    # body: median of opaque pixels in the top 8% of rows that carry any alpha (the neck stub), central half
    alpha = a[..., 3] > 200; rows = np.where(alpha.any(1))[0]; y0 = rows.min(); y1 = y0 + max(4, int(0.08 * (rows.max() - y0)))
    Wb = a.shape[1]; n = a[y0:y1, Wb // 4:3 * Wb // 4]; n = n[n[..., 3] > 200][..., :3]
    src = np.median(n, axis=0)
    gain = target / np.maximum(src, 1)
    d = np.sqrt(((a[..., :3] - src) ** 2).sum(-1))
    wgt = np.clip((tol + soft - d) / soft, 0, 1)[..., None]
    a[..., :3] = np.clip(a[..., :3] * (1 + (gain - 1) * wgt), 0, 255)
    print(f"   skin_match: body {src.astype(int)} -> face {target.astype(int)}")
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def cutout(im: Image.Image, pad=24, export=None, mode="rembg", trim=False) -> Image.Image:
    global _session
    if mode == "none":
        return im.convert("RGBA")
    if mode == "key":
        rgba = chroma_key(im)
    else:
        from rembg import new_session, remove
        if _session is None:
            _session = new_session("isnet-general-use")
        rgba = remove(im, session=_session, post_process_mask=True)
    if trim:
        rgba = trim_neck(rgba)
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
        seed0 = asset.get("seed", 0) + a.seed_offset
        adir = out_root / aid
        (adir / "raw").mkdir(parents=True, exist_ok=True)
        asset_refs = [] if a.no_refs else [upload(HERE / p) for p in asset.get("refs", [])]
        prev_raw = None
        for i, (state, state_val) in enumerate(states.items()):
            sdict = state_val if isinstance(state_val, dict) else {"text": state_val}
            state_text = sdict.get("text", "")
            name = f"{aid}_{state}" if state else aid
            final = adir / f"{name}.png"
            raw_path = adir / "raw" / f"{name}.png"
            if final.exists() and not a.force:
                print(f"skip {name} (exists)"); prev_raw = raw_path; continue

            seed = sdict.get("seed", seed0)
            obj = asset["prompt"] + (", " + state_text if state_text else "")
            refs, init, denoise = style_refs + asset_refs, None, 1.0
            if sdict.get("refs") and not a.no_refs:
                refs = refs + [upload(HERE / p) for p in sdict["refs"]]
            bg = asset.get("bg", style.get("bg", "pure white"))
            tmpl = asset.get("template", style["template"])
            stmpl = asset.get("state_template", style["state_template"])
            if i > 0 and prev_raw and chain != "none":
                refs.append(upload(prev_raw))
                prompt = stmpl.format(object=obj, state=state_text, ref_clause=ref_clause, bg=bg)
                if chain == "img2img":
                    init = refs[-1]
                    denoise = asset.get("denoise", 0.6)
            else:
                prompt = tmpl.format(object=obj, ref_clause=ref_clause, bg=bg)
            if asset.get("suffix"):
                prompt += " " + asset["suffix"]
            if trigger:
                prompt = trigger + ", " + prompt

            print(f"[{aid}] {name}  seed={seed}  refs={len(refs)}  {w}x{h}")
            t = time.time()
            imgs = run_graph(build_graph(cfg, prompt, seed, w, h, refs, init, denoise,
                                         prefix=f"assetgen/{aid}/{name}", lora=lora))
            imgs[0].save(raw_path)
            sprite = cutout(imgs[0], export=asset.get("export"), mode=asset.get("cutout", "rembg"), trim=asset.get("trim_neck", False))
            if asset.get("skin_match"):
                sprite = skin_match(sprite, HERE / asset["skin_match"])
            sprite.save(final)
            (adir / "raw" / f"{name}.txt").write_text(prompt + f"\nseed={seed}\n")
            print(f"   -> {final.relative_to(HERE)}  {sprite.size}  {time.time()-t:.1f}s")
            prev_raw = raw_path
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
