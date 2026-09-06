#!/usr/bin/env python
"""Contact sheet of generated sprites over a checker background: python sheet.py out/_sheet.png [asset ids]"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw
HERE = Path(__file__).resolve().parent
dst = Path(sys.argv[1]); ids = sys.argv[2:]
files = sorted(p for p in (HERE/"out").glob("*/*.png") if not ids or p.parent.name in ids)
T = 300
sheet = Image.new("RGB", (T*len(files), T+24), (200,200,200))
d = ImageDraw.Draw(sheet)
for i, p in enumerate(files):
    bg = Image.new("RGB", (T, T), (235,235,235))
    for y in range(0, T, 20):
        for x in range(0, T, 20):
            if (x//20+y//20) % 2: bg.paste((205,205,205), (x,y,x+20,y+20))
    im = Image.open(p).convert("RGBA"); im.thumbnail((T-16, T-16))
    bg.paste(im, ((T-im.width)//2, (T-im.height)//2), im)
    sheet.paste(bg, (i*T, 0)); d.text((i*T+6, T+5), p.stem, fill=(0,0,0))
sheet.save(dst); print(dst, sheet.size)
