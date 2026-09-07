#!/usr/bin/env python
"""Build the sprite atlas the game actually loads (code-side).

Reads assets/assets.json (game key -> loose PNG path, regen'd from manifest.yaml),
packs every sprite into atlas page(s) with padding, and writes:
  assets/art/atlas.json      {built, pages:[...], frames:{key:{page,x,y,w,h}}, count}
  assets/art/atlas-0.png ... page images (RGBA)

The browser loads ONLY art/atlas.json + page PNGs for the WebGL scene — never the
loose files (those remain as the accept archive; DOM icons for HUD/toolbar/fly
coins are runtime-sliced from the atlas as data URLs, so they load nothing extra).
Run after every accept:
  assets/regen.py && assets/atlas.py
"""
import json
from datetime import date
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "art"
MAX_SIDE = 2048
PAD = 8
# Atlas is a build artifact; loose keepers stay full-res. Display sizes are small
# (toolbar icons render at 44px, face parts at ~25px), so cap source dims per
# outbox id. Scene plate stays full-res (fullscreen background). Aspect is always
# preserved, and game layout is resolution-independent, so this is visually safe.
MAX_DIM_DEFAULT = 512
MAX_DIM = {  # outbox id -> max width/height px in the atlas
    'scene_diner': 1600,   # effectively no-op today (1584 wide)
    'grill': 1024, 'soda_machine': 1024, 'fryer': 1024, 'trash_bin': 1024,
}


class MaxRects:
    """Single-bin MaxRects packer, best-short-side-fit. Pixels, top-left origin."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.free = [(0, 0, w, h)]

    def free_rects_for(self, fx, fy, w, fh_used):
        # NOTE: needs the free rect dims; recompute by re-scanning is complex,
        # so instead we split against ALL free rects intersecting the placed box.
        placed = (fx, fy, w, fh_used)
        out = []
        for r in self.free:
            out.extend(self.split_rect(r, placed))
        self.free = out
        return []

    @staticmethod
    def split_rect(f, p):
        fx, fy, fw, fh = f
        px, py, pw, ph = p
        if px >= fx + fw or px + pw <= fx or py >= fy + fh or py + ph <= fy:
            return [f]
        rects = []
        if py > fy:
            rects.append((fx, fy, fw, py - fy))  # top
        if py + ph < fy + fh:
            rects.append((fx, py + ph, fw, fy + fh - py - ph))  # bottom
        if px > fx:
            rects.append((fx, py, px - fx, ph))  # left
        if px + pw < fx + fw:
            rects.append((px + pw, py, fx + fw - px - pw, ph))  # right
        return [r for r in rects if r[2] > 0 and r[3] > 0]

    def prune(self):
        rects = self.free
        keep = []
        for i, a in enumerate(rects):
            if any(i != j and self.contains(b, a) for j, b in enumerate(rects)):
                continue
            keep.append(a)
        self.free = keep

    @staticmethod
    def contains(a, b):
        return (a[0] <= b[0] and a[1] <= b[1]
                and a[0] + a[2] >= b[0] + b[2] and a[1] + a[3] >= b[1] + b[3])

    def place(self, w, h):
        """Find + claim a spot; returns (x, y) or None."""
        best, bs, bl = None, None, None
        for r in self.free:
            fx, fy, fw, fh = r
            if fw >= w and fh >= h:
                s, lg = min(fw - w, fh - h), max(fw - w, fh - h)
                if best is None or (s, lg) < (bs, bl):
                    best, bs, bl = r, s, lg
        if best is None:
            return None
        fx, fy, _, _ = best
        self.free_rects_for(fx, fy, w, h)
        self.prune()
        return (fx, fy)


def main():
    mapping = json.loads((HERE / "assets.json").read_text())
    items = []
    for key in sorted(mapping):
        src = HERE / mapping[key]
        if src.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
            continue   # audio keepers live in assets.json too (sfx bank); the atlas packs images only
        im = Image.open(src).convert("RGBA")
        cap = MAX_DIM.get(mapping[key].split('/')[0], MAX_DIM_DEFAULT)
        if max(im.width, im.height) > cap:
            im.thumbnail((cap, cap), Image.LANCZOS)
        items.append((key, src, im))
    # biggest first for tighter packing
    items.sort(key=lambda t: -(t[2].width * t[2].height))

    pages, frames = [], {}
    bins = []  # list of (MaxRects, {key: (img, x, y)})

    def new_page():
        bins.append((MaxRects(MAX_SIDE, MAX_SIDE), {}))
        return bins[-1]

    new_page()
    for key, src, im in items:
        w, h = im.width + PAD * 2, im.height + PAD * 2
        assert w <= MAX_SIDE and h <= MAX_SIDE, f"{key} {w}x{h} exceeds {MAX_SIDE}"
        spot = None
        for b, _ in bins:
            spot = b.place(w, h)
            if spot:
                break
        else:
            b, _ = new_page()
            spot = b.place(w, h)
            assert spot, f"fresh page cannot fit {key}"
        b, placed = bins[[b for b, _ in bins].index(b)]
        placed[key] = (im, spot[0] + PAD, spot[1] + PAD)

    for i, (b, placed) in enumerate(bins):
        # trim page to used bounds (keep POT-friendly: round up to 16px)
        mx = max(x + im.width for im, x, y in placed.values()) + PAD
        my = max(y + im.height for im, x, y in placed.values()) + PAD
        W, H = (mx + 15) // 16 * 16, (my + 15) // 16 * 16
        page = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for key, (im, x, y) in placed.items():
            page.alpha_composite(im, (x, y))
            frames[key] = {"page": i, "x": x, "y": y, "w": im.width, "h": im.height}
        name = f"atlas-{i}.png"
        page.save(OUT / name, optimize=True)
        pages.append(name)
        print(f"page {i}: {W}x{H}, {len(placed)} sprites")

    (OUT / "atlas.json").write_text(json.dumps(
        {"built": str(date.today()), "pages": pages,
         "frames": frames, "count": len(frames)}, indent=1) + "\n")
    print(f"wrote atlas.json with {len(frames)} frames over {len(pages)} page(s)")


if __name__ == "__main__":
    main()
