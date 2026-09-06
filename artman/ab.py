#!/usr/bin/env python
"""A/B sheet: run the same asset ids under several run.py flag sets and tile the results.

    .venv/bin/python ab.py coffee_mug ketchup_bottle -- "--no-lora --no-refs" "--no-refs" "" "--no-lora"
Each quoted string is one configuration; results land in out_ab/<n>_<slug>/ and out_ab/_ab.png.
"""
import subprocess, sys, re
from pathlib import Path
from PIL import Image, ImageDraw
HERE = Path(__file__).resolve().parent
ids, _, cfgs = sys.argv[1:sys.argv.index("--")], None, sys.argv[sys.argv.index("--") + 1:]
py = HERE / ".venv/bin/python"
rows = []
for i, c in enumerate(cfgs):
    slug = re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") or "default"
    out = HERE / "out_ab" / f"{i}_{slug}"
    subprocess.run([py, HERE / "run.py", "--force", "--out", str(out.relative_to(HERE)), *c.split(), *ids], check=True)
    rows.append((slug, sorted(p for p in out.glob("*/raw/*.png"))))
T = 280
sheet = Image.new("RGB", (140 + T * max(len(r[1]) for r in rows), (T + 20) * len(rows)), (210, 210, 210))
d = ImageDraw.Draw(sheet)
for r, (slug, files) in enumerate(rows):
    d.text((4, r * (T + 20) + T // 2), slug[:22], fill=(0, 0, 0))
    for k, p in enumerate(files):
        im = Image.open(p).convert("RGB"); im.thumbnail((T - 6, T - 6))
        sheet.paste(im, (140 + k * T + 3, r * (T + 20) + 3)); d.text((140 + k * T + 4, r * (T + 20) + T + 3), p.stem, fill=(0, 0, 0))
sheet.save(HERE / "out_ab" / "_ab.png"); print(HERE / "out_ab" / "_ab.png")
