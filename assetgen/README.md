# assetgen — a prop factory for Cooking Fever style sprites

This folder turns a **list of game assets** into a **folder of transparent PNG sprites**, using a local ComfyUI
install on the RTX 5090. You describe each asset (and its states) once in [`manifest.yaml`](manifest.yaml), run
[`run.py`](run.py), and the individual files pop out in [`out/`](out/). Everything below was built and generated in one
evening on 2026-09-04.

![all keepers](docs/keepers_sheet.png)

## What is here

| Path | What |
|---|---|
| [`manifest.yaml`](manifest.yaml) | The source of truth: style prompt skeletons, reference images, and one entry per asset (17 assets, 24 sprites). |
| [`run.py`](run.py) | The runner: builds a ComfyUI API graph per asset/state, submits it, pulls the render, removes the background, crops, saves. |
| [`train.py`](train.py) | Trains a style LoRA on the keepers with ComfyUI's built-in trainer (optional, see verdict below). |
| [`ab.py`](ab.py), [`sheet.py`](sheet.py) | A/B comparison sheets and contact sheets for review. |
| [`refs/`](refs/) | The Cooking Fever screenshot that started this ([`screenshot_diner.png`](refs/screenshot_diner.png)), object crops from it, and the [`style_sheet.png`](refs/style_sheet.png) strip used as the global style reference. |
| [`out/<id>/`](out/) | Final sprites, e.g. [`out/patty/`](out/patty/). Raw renders and prompts live in `out/<id>/raw/` (git-ignored). |
| [`docs/`](docs/) | Review sheets from the iterations, and the [planning conversation](docs/plan_conversation.md) this implements. |

Assets of interest:

- Patty state chain: [raw](out/patty/patty_raw.png) → [cooking](out/patty/patty_cooking.png) → [cooked](out/patty/patty_cooked.png) → [burnt](out/patty/patty_burnt.png)
- Sausage state chain: [raw](out/sausage/sausage_raw.png) → [cooked](out/sausage/sausage_cooked.png) → [burnt](out/sausage/sausage_burnt.png)
- Bun as three props: [whole](out/bun_whole/bun_whole.png), [top](out/bun_top/bun_top.png), [bottom](out/bun_bottom/bun_bottom.png)
- Stations and props: [grill](out/grill/grill.png), [soda machine](out/soda_machine/soda_machine.png), [trash bin](out/trash_bin/trash_bin.png), [frying pan](out/frying_pan/frying_pan.png), [deep fryer](out/fryer/fryer.png), [prep tray](out/prep_tray/prep_tray.png), [napkin dispenser](out/napkin_dispenser/napkin_dispenser.png), [plate](out/plate/plate.png)
- Food and drink: [cup empty](out/cup/cup_empty.png) / [full](out/cup/cup_full.png), [coffee mug empty](out/coffee_mug/coffee_mug_empty.png) / [full](out/coffee_mug/coffee_mug_full.png), [cheese slice](out/cheese_slice/cheese_slice.png), [fries raw](out/fries/fries_raw.png) / [cooked](out/fries/fries_cooked.png) (stateful pair, same carton via `chain: edit`, magenta key so the pale raw sticks survive), [ketchup bottle](out/ketchup_bottle/ketchup_bottle.png)

## How we made it

1. **Plan.** The [planning conversation](docs/plan_conversation.md) settled the shape of the thing: don't generate
   whole kitchen screenshots, generate isolated props against a flat background with one locked camera and one locked
   style, and drive it from a manifest so adding an asset is adding a row.
2. **Inventory.** ComfyUI was already installed at `/workspace/tmp/ComfyUI` but only had MiniMax video models, no image
   checkpoints, no custom nodes. Rather than install Manager, IP-Adapter and an SDXL checkpoint, we picked one model
   that covers everything (see next section) and downloaded three files (~16 GB).
3. **Style bible.** Seven objects were cropped out of the reference screenshot (grill, pan, patties, buns, plated
   burger, ice cream machine, bin) and tiled into [`refs/style_sheet.png`](refs/style_sheet.png). That strip is passed
   as a reference image to every generation.
4. **Runner.** [`run.py`](run.py) builds the ComfyUI graph in code and talks to the server over its HTTP API. The first
   patty chain worked on the first submission after one input-name fix.
5. **Iterate per asset class.** Each class got its own fix:
   - Patty: the first pass sat every patty on a bun. Prompt now says "only the meat, no bun" and each state names an
     explicit colour, which made the four states read clearly.
   - Bun halves: klein has a strong "burger" prior and drew a two-layer bun no matter how the prompt said "only the
     top half" ([sheet](docs/bun_grill_seed_explore.png)). Describing the object without the word bun ("dome-shaped
     dinner roll", "thick flat slice of bread like a puck") fixed it ([sheet](docs/bun_halves_fixed.png)).
   - Grill: adding the screenshot crop as a per-asset reference and picking the best of four seeds.
   - Everything else (cups, sausage, machines, plate, fries, cheese) was usable on the first try.
6. **LoRA experiment.** With 21 keepers we trained a style LoRA twice through ComfyUI's built-in trainer and A/B'd it on
   two held-out assets. It lost to the reference-image lock, so it is off by default (details below).

## Why these models

**FLUX.2 klein 4B** (`flux-2-klein-4b.safetensors`, Black Forest Labs, Apache-2.0, ungated on Hugging Face) is the only
diffusion model in the pipeline, because one model does every job the plan needed:

- **Text-to-image and image editing in one network.** klein accepts reference images as extra latents. That gives us the
  style lock (screenshot crops as references) *and* the state chain (previous state as reference, "redraw the same
  object but burnt") without IP-Adapter, ControlNet or img2img denoise tuning. A `chain: edit` step keeps silhouette,
  camera and outline weight, which is exactly what makes raw/cooked/burnt look like the same patty.
- **4-step distilled.** A 1024² sprite takes about 4 seconds on the 5090, a full four-state chain about 15 seconds.
  That is what makes seed exploration and A/B sheets cheap enough to do casually.
- **Licence.** Apache-2.0, so sprites can ship in a game. FLUX.1 dev and the 9B klein are non-commercial.
- **Fits with room to spare.** ~8 GB of weights in bf16 plus an 8 GB text encoder, with the 5090 still able to hold the
  VAE and reference latents. No FP8 or GGUF juggling.
- **Style.** The plan expected SDXL plus LoRAs to be needed for the casual-game look. In practice klein reproduced
  the screenshot's glossy cel-shading from the reference strip alone, so the SDXL stack was never installed.

Supporting files: `qwen_3_4b.safetensors` is the Qwen3-4B text encoder klein was trained with (taken from the Z-Image
Turbo Comfy repack, same file), and `flux2-vae.safetensors` is the FLUX.2 VAE (from the FLUX.2 dev Comfy repack).
Background removal uses **rembg** with the `isnet-general-use` model on CPU; on a flat white render it produces clean
edges and needs no GPU time.

## How the ComfyUI workflows are used

There are no saved workflow JSON files. [`run.py`](run.py) builds the graph as a Python dict in the API format and
POSTs it to `/prompt`, then polls `/history/<id>` and fetches the image from `/view`. Prompt text, seed, size, reference
images and the output prefix are just fields in that dict, which is what makes a manifest-driven batch trivial.

**Generation graph** (one per asset state):

```
UNETLoader(flux-2-klein-4b) ─┐
CLIPLoader(qwen_3_4b, flux2) → CLIPTextEncode(prompt) → [ReferenceLatent ×N] → KSampler ─→ VAEDecode → SaveImage
VAELoader(flux2-vae) ────────┘        ConditioningZeroOut → (negative)   ↑
                                      EmptyFlux2LatentImage(w,h) ────────┘
LoadImage(ref) → ImageScaleToTotalPixels(1 MP) → VAEEncode → ReferenceLatent   (repeated per reference)
```

- References are chained `ReferenceLatent` nodes on the positive conditioning: first the global style strip, then any
  per-asset crop from the screenshot, then, for state 2+, the previous state's raw render.
- KSampler: 4 steps, cfg 1.0, euler, simple scheduler, one fixed seed per asset so re-runs are reproducible.
- `chain: img2img` additionally VAE-encodes the previous render as the starting latent with a `denoise` value;
  `chain: none` draws each state independently. Optional `LoraLoaderModelOnly` is inserted between the UNET and
  the sampler when a LoRA is configured.
- Renders are done on a plain white background at 1024² (1536×1024 for wide stations); rembg then cuts out the object
  and the sprite is cropped to its bounding box with padding.

**Training graph** ([`train.py`](train.py)), built the same way from ComfyUI's experimental training nodes:

```
LoadImageTextDataSetFromFolder(input/lora_<name>) → MakeTrainingDataset(vae, clip) → TrainLoraNode(model) → SaveLoRA
```

The dataset is every keeper in `out/` (its raw white-background render, padded to a square) with a caption made from
the manifest prompt plus a trigger word. 1024² training OOMs on the 5090 (the trainer wants ~25 GB plus whatever else
is on the GPU); 768² with checkpoint depth 2 trains 500 steps in 9 minutes.

## Round two: a whole game's worth of assets (cook2.html)

[`../cook2.html`](../cook2.html) is a from-scratch three.js remake of the diner that uses only sprites from this
folder. The second batch added, all in one evening:

- **Scene plate** ([`out/scene_diner/`](out/scene_diner/)): the reference screenshot itself, edited by klein with
  "remove everything that is not the room and the counter" (`cutout: none`, the screenshot as the reference latent).
  The game draws it once as the background and once more, cropped below the counter edge, above the customers.
- **HUD icons** ([sheet](docs/hud_icons.png)): coins, stars on/off, XP badge, clock, customer, lock, heart, anger mark,
  plus a coin, a coin stack for tips and an empty speech bubble.
- **Puppet customers** ([sheet](docs/customer_parts.png)): per character a floating head (front + 3/4 side), a headless
  torso (front + side), an ear and a nose; shared eye (open/closed), eyebrow and four mouths
  ([sheet](docs/face_parts.png)). The game rigs these as a paper puppet and tweens between the two poses.
  - "Head only" / "body only" prompts leaked (heads came with shoulders, bodies with faces). The fix was a second
    edit pass: `draft_*` renders first, then a `template` that says "using the reference, erase the body / erase the
    head" with per-state `refs` pointing at the draft's raw render.
  - Face parts contain white, so they are generated on a green background with `cutout: key`. The key colour is
    sampled from the image corners because klein paints a muted green rather than the exact colour asked for.

**Debug harness in cook2.html** (ported from cook.html and the museum harness): open `cook2.html?debug` for the
time-travel panel (freeze, +1, +N frames of 1/60 s, reset T; keys `f` / `.` / `>`) and the poser. From the console,
`__cook.help()` lists everything: `__cook.dbg.step(n)`, `__cook.pose.enter('puppet:man',{bg:'grid',zoom:3})`,
`pose.show({ears:false})`, `pose.center(dx,dy)`, `pose.parts()`. Backdrops: any CSS colour, `'gradient'` or `'grid'`.
The left-docked toolbar (visible with `?debug` or `?pose=`) has move / scale / rotate tools: hovering outlines the
smallest sprite under the cursor, including parts inside composites, and each drag logs a `[edit]` line with before
and after values (`__cook.edit.dump()` prints them all). Puppet face parts log offsets in head-width units that paste
straight into `POSE` / `CHAR`; everything else logs design pixels.
This is how the double-ear bug was found: klein bakes ears (or an erased-ear skin patch) into every head it draws,
so the rigged ears are drawn in front of the head with per-character placement that covers the remnant.

New manifest features from this round: per-asset `template` / `state_template`, `bg`, `cutout: rembg|key|none`,
per-asset `refs`, and state values may be objects `{text, refs, seed}`.

## Usage

```sh
# ComfyUI must be running (models live in /workspace/tmp/ComfyUI/models):
cd /workspace/tmp/ComfyUI && .venv/bin/python main.py --listen 127.0.0.1 --port 8188 &

cd /workspace/vibe-arcade/assetgen
.venv/bin/python run.py                  # all assets (skips ones already in out/)
.venv/bin/python run.py patty grill      # just these ids
.venv/bin/python run.py --force patty    # regenerate
.venv/bin/python run.py --no-refs --out out_norefs patty   # A/B without style refs
.venv/bin/python run.py --seed-offset 7 patty              # quick re-roll
.venv/bin/python sheet.py out/_sheet.png # contact sheet of everything in out/

# explore seeds for one asset, then set the winner's seed in the manifest:
for k in 0 1 2 3; do .venv/bin/python run.py --force --seed-offset $k --out out_explore/s$k bun_top; done

# A/B several flag sets on the same assets -> out_ab/_ab.png
.venv/bin/python ab.py coffee_mug -- "--no-lora --no-refs" "--no-lora" "--lora dinerart_v2.safetensors --lora-strength 0.5"

# train a style LoRA on the keepers in out/, then try it:
.venv/bin/python train.py --name dinerart_v3 --steps 400 --rank 8 --lr 3e-5 --size 768
.venv/bin/python run.py --lora dinerart_v3.safetensors --lora-strength 0.5 ketchup_bottle
```

Setup was: `uv venv .venv -p 3.12 && uv pip install "rembg[cpu]" pillow pyyaml requests`.

## Manifest fields

- `comfy` — model file names, sampler steps/cfg, optional `lora: {name, strength, trigger}` (prefixes every prompt with
  the trigger and loads the LoRA; `--lora`, `--lora-strength`, `--no-lora` override from the CLI).
- `style.refs` — images passed as reference latents to every generation (the style lock).
- `style.template` / `state_template` — prompt skeletons; `{object}`, `{state}`, `{ref_clause}` get filled in.
- per asset: `id`, `prompt`, `size` (int or `[w, h]`), `seed`, optional `refs` (extra reference images, e.g. a crop
  from the screenshot), `export` (max px of the final sprite), `suffix`.
- `states:` map of `name: description`. `chain: edit` (default) feeds the previous state's image back as a reference so
  the object stays the same; `chain: img2img` also uses it as the init latent (`denoise`); `chain: none` draws each
  state independently.

Outputs: `out/<id>/<id>_<state>.png` (rembg cutout, cropped), `out/<id>/raw/` (untouched render + the exact prompt used).

## Lessons so far

- FLUX.2 klein reproduces the reference's glossy cel-shading well; the screenshot crop strip as a reference latent is
  enough to lock the look without a LoRA ([with refs](out/patty/) vs [without](docs/patty_no_refs.png)).
- Klein has a strong "burger" prior: asking for bun halves gave a stacked two-layer bun every time. Describing the
  object without the word bun fixed it.
- Same-silhouette states (patty raw→burnt, sausage, cup empty→full) work with `chain: edit`; states that change the
  shape (bun halves) should be independent props with their own seed.
- LoRA verdict: v1 (rank 16, lr 1e-4, 500 steps) destroyed the 4-step distillation
  ([strength sweep](docs/lora_v1_strength_sweep.png): fog at 0.8). v2 (rank 8, lr 3e-5, 400 steps) is stable at
  strength ≤0.5 but no better than the reference lock, and tints backgrounds at 1.0 ([A/B sheet](docs/lora_ab.png)).
  Production path = `style.refs` + per-asset crop refs, no LoRA. Revisit with 60+ keepers or a dedicated trainer
  (ai-toolkit) that handles distilled models better.
- The built-in trainer OOMs on the 5090 at 1024²; 768² with `--ckpt-depth 2` fits.

## Not done yet

- Scale normalisation: sprites are cropped to their own bounding box; relative sizes (bun vs grill) still need a "unit
  bun" pass before compositing.
- Drop shadows are stripped with the background; if the game wants them they should be a separate layer.
- The reference screenshot is from Cooking Fever and is here only as a style reference; every shipped sprite is a
  fresh generation.
