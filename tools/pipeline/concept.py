#!/usr/bin/env python3
"""Stage 1: generate 4 voxel-style concept images for an animal with fal Seedream and build a contact sheet to pick from.

  concept.py <Name> --idea "a cheerful corgi" --len-m 0.9 [--anatomy "..."] [--colors "..."] [--pose standing] [--out ./assets]
  concept.py <Name> --kind humanoid --idea "a dwarf miner" --height-m 1.8 [--anatomy "..."] [--colors "..."]   # for rpg-character

Writes <out>/<Name>/concept/candidate_{1..4}.png, concept_sheet.png and concept.json (the fal CDN URLs -
pass the picked one to run_creature.py --image-url). Needs FAL_KEY (or ~/.fal/key). ~$0.07 per image.
"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fal_client as F

HUMANOID = ("A 3D render of a voxel art game character: {idea}, standing upright in a relaxed A-pose facing the camera at a "
 "slight three-quarter angle, arms hanging straight down and held a little away from the body, legs apart and clearly separated, "
 "feet flat on the ground. Built from large chunky visible cubes on a strict grid, roughly {H} cubes tall, MagicaVoxel style, "
 "crisp axis-aligned blocky edges, no smooth curves. A big blocky head, {anatomy}. Flat colors in clean regions: {colors}. "
 "Centered, entire figure in frame, plain solid light-gray background, soft even studio lighting, no shadows on background.")

TEMPLATE = ("A 3D render of a voxel art game asset: {idea} {pose}, viewed from a side three-quarter angle. "
 "Built from large chunky visible cubes on a strict grid, roughly {L} cubes long and {H} cubes tall, MagicaVoxel style, "
 "crisp axis-aligned blocky edges, no smooth curves. {anatomy}. Legs clearly separated from each other and from the ground. "
 "Flat colors in clean regions: {colors}. Centered, entire model in frame, plain solid light-gray background, "
 "soft even studio lighting, no shadows on background.")

def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): print(__doc__); sys.exit(1)
    name = a[0]
    def opt(f, d=None): return a[a.index(f) + 1] if f in a else d
    idea = opt("--idea") or sys.exit("need --idea"); len_m = float(opt("--len-m", "1.0")); pose = opt("--pose", "standing")
    anatomy = opt("--anatomy", "a compact blocky body, a clearly separate head, four sturdy legs, thin parts thickened into slabs or omitted")
    colors = opt("--colors", "two or three flat colours in clean regions"); n = int(opt("--n", "4"))
    if opt("--kind", "animal") == "humanoid":
        H = round(float(opt("--height-m", "1.8")) * 10)
        anatomy = opt("--anatomy", "a boxy torso, two thick arms ending in mitten hands, two sturdy legs, no thin accessories")
        prompt = HUMANOID.format(idea=idea, H=H, anatomy=anatomy, colors=colors)
    else:
        L = round(len_m * 10); H = max(4, round(L * 0.6))
        prompt = TEMPLATE.format(idea=idea, pose=pose, L=L, H=H, anatomy=anatomy, colors=colors)
    D = os.path.join(os.path.abspath(opt("--out", "assets")), name, "concept"); os.makedirs(D, exist_ok=True)
    print(f"[{name}] generating {n} concepts ...", flush=True)
    r = F.wait(F.submit(F.SEEDREAM, F.concept_payload(prompt, n)), poll=5, budget=600, label=name)
    urls = [im["url"] for im in r["images"]]; paths = []
    for i, u in enumerate(urls, 1):
        p = os.path.join(D, f"candidate_{i}.png"); F.download(u, p); paths.append(p)
    json.dump({"prompt": prompt, "urls": urls, "paths": paths}, open(os.path.join(D, "concept.json"), "w"), indent=1)
    sheet = os.path.join(D, "concept_sheet.png")
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "contact_sheet.py"), "--out", sheet, "--columns", "2",
                        *[f"{p}|candidate {i+1}|1" for i, p in enumerate(paths)]], check=True)
    except Exception as e: print("  (contact sheet skipped:", e, ")")
    print(f"\nPick one, then:\n  run_creature.py {name} --image-url <url> --len-m {len_m}\n")
    for i, u in enumerate(urls, 1): print(f"  {i}: {u}")

if __name__ == "__main__": main()
