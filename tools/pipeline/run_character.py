#!/usr/bin/env python3
"""rpg-character stages 2-4: image -> 3D mesh -> voxels -> derived humanoid rig -> retargeted RPG clips -> glTF.

  run_character.py <Name> --image-url <picked concept URL> --height-m 1.8 [--out ./assets] [--render]
  run_character.py <Name> --glb mesh.glb --height-m 1.8        # skip the fal mesh step
  run_character.py <Name> --vox model.vox --height-m 1.8       # skip straight to the rig (a standing, -Y facing humanoid .vox)
  options: --source anims/kaykit/Knight.glb --map maps/kaykit.json --preset presets/rpg_kaykit.json --only Idle,Slash --no-props
           --relax-arms 15   (degrees; pulls hanging upper arms toward the body — for chunky sleeves that read as raised arms)

Outputs (under <out>/<Name>/): <Name>_mesh.glb, <Name>.vox, previews/, layout.json, <name>_rules.py, <Name>_rigged.blend,
<Name>_animated.glb (every clip + prop meshes on the weapon slot), clips.json (loop / hit frame / prop), report.json, run.log.
Environment: BLENDER (default `blender` on PATH), VOXELIZER (default tools/voxelizer/build/voxelizer), FAL_KEY or ~/.fal/key.
"""
import json, os, re, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE)); BIPED = os.path.join(ROOT, "tools", "biped")
sys.path.insert(0, HERE); sys.path.insert(0, BIPED)
import bipedrig

BLENDER = os.environ.get("BLENDER") or shutil.which("blender") or "blender"
VOXELIZER = os.environ.get("VOXELIZER") or os.path.join(ROOT, "tools", "voxelizer", "build", "voxelizer")
CELL = 0.05   # metres per voxel

def sh(cmd, log, timeout=3600):
    t = time.time(); r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, "DISPLAY": ""})
    open(log, "a").write(f"\n$ {' '.join(cmd)}\n{r.stdout}\n{r.stderr}\n"); return r, time.time() - t

def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): print(__doc__); sys.exit(1)
    name = a[0]
    def opt(f, d=None): return a[a.index(f) + 1] if f in a else d
    img, glb, vox_in = opt("--image-url"), opt("--glb"), opt("--vox"); height = float(opt("--height-m", "1.8"))
    out_root = os.path.abspath(opt("--out", "assets"))
    source = opt("--source", os.path.join(BIPED, "anims", "kaykit", "Knight.glb")); bmap = opt("--map", os.path.join(BIPED, "maps", "kaykit.json"))
    preset = opt("--preset", os.path.join(BIPED, "presets", "rpg_kaykit.json"))
    D = os.path.join(out_root, name); os.makedirs(D, exist_ok=True); log = os.path.join(D, "run.log")
    rep = {"name": name, "height_m": height, "stages": {}}
    def stage(k, **kw):
        rep["stages"][k] = kw; json.dump(rep, open(os.path.join(D, "report.json"), "w"), indent=1); print(f"  [{name}] {k}: {kw}", flush=True)
    if not vox_in and not os.path.exists(VOXELIZER):
        sys.exit(f"voxelizer not found at {VOXELIZER}. Build it: cmake -S tools/voxelizer -B tools/voxelizer/build && cmake --build tools/voxelizer/build")

    # ---- stage 2: image -> 3D (fal Hunyuan-3D) ----------------------------------------------------
    if not vox_in and not glb:
        if not img: sys.exit("need --image-url (the picked concept), --glb, or --vox")
        import fal_client as F
        glb = os.path.join(D, f"{name}_mesh.glb")
        if not os.path.exists(glb):
            t = time.time(); r = F.wait(F.submit(F.HUNYUAN, F.mesh_payload(img, 100000)), poll=10, budget=1200, label=name)
            F.download(r["model_glb"]["url"], glb)
            stage("mesh", secs=round(time.time() - t), glb_mb=round(os.path.getsize(glb) / 1e6, 1))

    # ---- stage 3: voxelize; sweep the yaw until the model stands on two legs, wider than deep, toes to -Y ----
    vox = os.path.join(D, f"{name}.vox")
    if vox_in: shutil.copy(vox_in, vox)
    else:
        N = max(12, round(height / CELL)); prev = os.path.join(D, "previews"); os.makedirs(prev, exist_ok=True); tries = []
        for yaw in (0, 180, 90, 270):
            r, dt = sh([VOXELIZER, glb, "--fill", "--axis", "y", "--long-axis", str(N), "--yaw", str(yaw), "--out", vox, "--previews", prev], log)
            if r.returncode: sys.exit(f"voxelizer failed: {r.stderr[-400:]}")
            size, v = bipedrig.load_vox(vox); fr = bipedrig.facing_report(size, v); tries.append((yaw, fr))
            if fr["two_legs"] and fr["wider_than_deep"] and fr["toes_neg_y"]: break
        else:
            best = max(tries, key=lambda t: (t[1]["two_legs"], t[1]["wider_than_deep"], not t[1]["toes_pos_y"]))
            yaw = best[0]; sh([VOXELIZER, glb, "--fill", "--axis", "y", "--long-axis", str(N), "--yaw", str(yaw), "--out", vox, "--previews", prev], log)
            print(f"  [{name}] WARNING: no yaw satisfied every facing test; using yaw {yaw}. Check previews/{name}_vox_side.png (toes must point LEFT).")
        stage("voxelize", yaw=yaw, size=list(size), voxels=len(v), N=N, tries=[(y, {k: b for k, b in f.items() if k != 'size'}) for y, f in tries])

    # ---- stage 4a: derive the body plan --------------------------------------------------------------
    size, v = bipedrig.load_vox(vox)
    try: layout, assign = bipedrig.analyze(size, v, height)
    except SystemExit as e: stage("layout", ok=False, err=str(e)); sys.exit(f"body plan failed: {e}")
    json.dump(layout, open(os.path.join(D, "layout.json"), "w"), indent=1)
    rules = os.path.join(D, f"{name.lower()}_rules.py"); bipedrig.write_rules(rules, assign, name)
    stage("layout", ok=layout["ok"], warnings=layout["warnings"], arm_mode=layout["arm_mode"], bands=layout["bands"], S=round(layout["S"], 4))
    if not layout["ok"]: print(f"  [{name}] LAYOUT WARNINGS: " + "; ".join(layout["warnings"]) + " -- check previews/ and layout.json; the rig will still build.")

    # ---- stage 4b: mesh + rig + retarget + export (headless Blender) --------------------------------
    cmd = [BLENDER, "-b", "--factory-startup", "--python", os.path.join(BIPED, "biped_build.py"), "--", vox, D,
           "--layout", os.path.join(D, "layout.json"), "--rules", rules, "--name", name, "--source", source, "--map", bmap, "--preset", preset]
    if opt("--only"): cmd += ["--only", opt("--only")]
    if "--no-props" in a: cmd += ["--no-props"]
    if opt("--relax-arms"): cmd += ["--relax-arms", opt("--relax-arms")]
    if "--render" in a: cmd += ["--render"]
    r, dt = sh(cmd, log); out = r.stdout + r.stderr
    clips = [l for l in out.splitlines() if l.startswith("CLIP ")]
    glb_out = os.path.join(D, f"{name}_animated.glb")
    ok = os.path.exists(glb_out) and clips and all(l.rstrip().endswith("OK") for l in clips) and "Traceback" not in out and layout["ok"]
    stage("rig", secs=round(dt, 1), ok=bool(ok), clips=len(clips), failed=[l.split()[1] for l in clips if not l.rstrip().endswith("OK")],
          missing=[l for l in out.splitlines() if l.startswith("MISSING")], err=(None if ok else out[-1200:]))
    if "--render" in a and ok:
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "clip_sheet.py"), D], check=True)
        except Exception as e: print("  (clip sheet skipped:", e, ")")
    rep["ok"] = bool(ok); json.dump(rep, open(os.path.join(D, "report.json"), "w"), indent=1)
    print(f"\n{'OK' if ok else 'FAILED'}  {glb_out if ok else '(see run.log)'}")
    sys.exit(0 if ok else 2)

if __name__ == "__main__": main()
