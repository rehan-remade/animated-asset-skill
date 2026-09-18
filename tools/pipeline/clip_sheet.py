#!/usr/bin/env python3
"""Contact sheet of the preview frames a biped build wrote: clip_sheet.py <asset dir> [--per-sheet 11]"""
import json, os, sys
from PIL import Image, ImageDraw
D = sys.argv[1]; per = int(sys.argv[sys.argv.index("--per-sheet") + 1]) if "--per-sheet" in sys.argv else 11
clips = [c for c in json.load(open(os.path.join(D, "clips.json"))) if os.path.exists(os.path.join(D, "previews", f"{c}_0.png"))]
n, W = 6, 220
for gi in range(0, len(clips), per):
    g = clips[gi:gi + per]; sheet = Image.new("RGB", (W * n, (W + 22) * len(g)), (30, 30, 34)); d = ImageDraw.Draw(sheet)
    for r, c in enumerate(g):
        y = r * (W + 22); d.text((8, y + 4), c, fill=(240, 240, 240))
        for i in range(n):
            p = os.path.join(D, "previews", f"{c}_{i}.png")
            if os.path.exists(p): sheet.paste(Image.open(p).convert("RGB").resize((W, W)), (i * W, y + 22))
    out = os.path.join(D, f"clip_sheet_{gi // per + 1}.png"); sheet.save(out); print(out, g)
