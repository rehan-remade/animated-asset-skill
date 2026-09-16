"""Compose labeled images into one contact sheet for user review.

Used by the animated-asset skill for the two manual pick gates:
  - concept candidates (stage 1): equal-scale grid, pick a concept
  - voxel bucket comparison (stage 3): per-panel integer upscales so the
    same asset at different cell sizes renders at equal PHYSICAL size

Usage:
  python tools/pipeline/contact_sheet.py --out sheet.png [--columns N]
         "path.png|label|scale" ["path2.png|label2|scale2" ...]

Each entry is image path, caption, and integer nearest-neighbor upscale
(use 1 for photos; for bucket previews use 4/2/1 for buckets 1, 1/2, 1/4
so voxel sizes compare truthfully). Requires Pillow (pip install pillow).
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw

PAD = 24
LABEL_H = 30
BG = (205, 205, 205)
INK = (40, 40, 40)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--columns", type=int, default=0, help="0 = all in one row")
    ap.add_argument("entries", nargs="+", help="path|label|scale")
    args = ap.parse_args()

    panels = []
    for e in args.entries:
        parts = e.split("|")
        if len(parts) != 3:
            sys.exit(f"bad entry (want path|label|scale): {e}")
        path, label, scale = parts[0], parts[1], int(parts[2])
        img = Image.open(path).convert("RGB")
        if scale > 1:
            img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        panels.append((img, label))

    cols = args.columns if args.columns > 0 else len(panels)
    rows = [panels[i:i + cols] for i in range(0, len(panels), cols)]
    row_h = [max(p.height for p, _ in r) + LABEL_H + PAD for r in rows]
    row_w = [sum(p.width for p, _ in r) + PAD * (len(r) + 1) for r in rows]
    W, H = max(row_w), sum(row_h) + PAD

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    y = PAD
    for r, rh in zip(rows, row_h):
        x = PAD
        ph = max(p.height for p, _ in r)
        for p, label in r:
            canvas.paste(p, (x, y + (ph - p.height) // 2))
            d.text((x, y + ph + 8), label, fill=INK)
            x += p.width + PAD
        y += rh
    canvas.save(args.out)
    print(f"{args.out} ({canvas.width}x{canvas.height}, {len(panels)} panels)")


if __name__ == "__main__":
    main()
