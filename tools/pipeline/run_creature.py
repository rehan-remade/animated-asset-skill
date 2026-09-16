#!/usr/bin/env python3
"""Stages 2-4 for one creature: image -> 3D mesh -> voxels -> rigged + animated glTF.

  run_creature.py <Name> --image-url <picked concept URL> --len-m 0.9 [--out ./assets] [--video]
  run_creature.py <Name> --glb existing_mesh.glb  --len-m 1.2          # skip the fal mesh step
  run_creature.py <Name> --vox existing.vox                             # skip straight to the rig

Outputs (under <out>/<Name>/):  <Name>_mesh.glb, <Name>.vox, previews/, layout.json, <name>_rules.py,
<Name>_rigged.blend, <Name>_animated.glb (all clips), report.json (guards + timings), run.log.

Environment:  BLENDER (default: `blender` on PATH), VOXELIZER (default: tools/voxelizer/build/voxelizer),
              FAL_KEY (or ~/.fal/key) for the Hunyuan step.  --len-m is the animal's real-world length;
              1 voxel = 5 cm, so a 0.9 m corgi is 18 voxels long.
"""
import json, os, re, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools", "rig"))
import voxrig

BLENDER = os.environ.get("BLENDER") or shutil.which("blender") or "blender"
VOXELIZER = os.environ.get("VOXELIZER") or os.path.join(ROOT, "tools", "voxelizer", "build", "voxelizer")
RIG = os.path.join(ROOT, "tools", "rig"); CLIPS = os.path.join(RIG, "clips")
S = 0.05   # metres per voxel cell

def sh(cmd, log, timeout=3600):
    t = time.time(); env = {**os.environ, "DISPLAY": ""}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    open(log, "a").write(f"\n$ {' '.join(cmd)}\n{r.stdout}\n{r.stderr}\n"); return r, time.time() - t

def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): print(__doc__); sys.exit(1)
    name = a[0]
    def opt(f, d=None): return a[a.index(f) + 1] if f in a else d
    img = opt("--image-url"); glb = opt("--glb"); vox_in = opt("--vox"); len_m = float(opt("--len-m", "1.0"))
    out_root = os.path.abspath(opt("--out", "assets")); video = "--video" in a; extra = opt("--extra", CLIPS)
    D = os.path.join(out_root, name); os.makedirs(D, exist_ok=True); log = os.path.join(D, "run.log")
    rep = {"name": name, "stages": {}}
    def stage(k, **kw):
        rep["stages"][k] = kw; json.dump(rep, open(os.path.join(D, "report.json"), "w"), indent=1); print(f"  [{name}] {k}: {kw}", flush=True)
    if not os.path.exists(VOXELIZER) and not vox_in:
        sys.exit(f"voxelizer not found at {VOXELIZER}. Build it: cmake -S tools/voxelizer -B tools/voxelizer/build && cmake --build tools/voxelizer/build")

    # ---- stage 2: image -> 3D (fal Hunyuan-3D) -------------------------------------------------
    if not vox_in and not glb:
        if not img: sys.exit("need --image-url (the picked concept), --glb, or --vox")
        import fal_client as F
        glb = os.path.join(D, f"{name}_mesh.glb")
        if not os.path.exists(glb):
            t = time.time(); job = F.submit(F.HUNYUAN, F.mesh_payload(img, 100000)); r = F.wait(job, poll=10, budget=1200, label=name)
            F.download(r["model_glb"]["url"], glb)
            if r.get("thumbnail"): F.download(r["thumbnail"]["url"], os.path.join(D, f"{name}_mesh_thumb.png"))
            stage("mesh", secs=round(time.time() - t), glb_mb=round(os.path.getsize(glb) / 1e6, 1))

    # ---- stage 3: voxelize with automatic facing ------------------------------------------------
    vox = os.path.join(D, f"{name}.vox")
    if vox_in: shutil.copy(vox_in, vox)
    else:
        N = max(6, round(len_m * 10)) * 2; prev = os.path.join(D, "previews"); os.makedirs(prev, exist_ok=True)
        yaw = 0; tries = []
        for _ in range(4):
            r, dt = sh([VOXELIZER, glb, "--long-axis", str(N), "--yaw", str(yaw), "--out", vox, "--previews", prev], log)
            if r.returncode: sys.exit(f"voxelizer failed: {r.stderr[-400:]}")
            size, v, pal = voxrig.load_vox(vox); occ = voxrig.occ_of(v); fr = voxrig.facing_report(size, occ)
            tries.append((yaw, list(size), fr["head_at_low_y"]))
            if not fr["long_axis_is_y"]: yaw = (yaw + 90) % 360; continue
            if not fr["head_at_low_y"]: yaw = (yaw + 180) % 360; continue
            break
        stage("voxelize", yaw=yaw, size=list(size), voxels=len(v), N=N, tries=tries,
              note="check previews/<Name>_vox_side.png: the head must be on the LEFT. If not, re-run with --vox after fixing --yaw manually.")
    size, v, pal = voxrig.load_vox(vox); occ = voxrig.occ_of(v)

    # ---- stage 4: derive the rig layout + bone rules, then rig + animate + export ----------------
    lay = voxrig.analyze(size, occ, S); lay.pop("layers", None)
    json.dump(lay, open(os.path.join(D, "layout.json"), "w"), indent=1)
    rules = os.path.join(D, f"{name.lower()}_rules.py"); open(rules, "w").write(voxrig.gen_rules(lay, name))
    flags = ["export"] + (["video"] if video else [])
    cmd = [BLENDER, "-b", "--factory-startup", "--python", os.path.join(RIG, "generic_quad_build.py"), "--", vox, D, *flags,
           "--layout", os.path.join(D, "layout.json"), "--rules", rules, "--name", name]
    if extra and os.path.isdir(extra): cmd += ["--extra", extra]
    r, dt = sh(cmd, log); out = r.stdout + r.stderr
    guards = [l for l in out.splitlines() if re.search(r"GUARD|ref speed|grounded|suspension|EXTRA CLIP|CLIPS:", l)]
    glb_out = os.path.join(D, f"{name}_animated.glb")
    ok = "DIRECTION GUARD: OK" in out and os.path.exists(glb_out) and "EXTRA CLIP FAILED" not in out
    susp = "suspension: YES" in out
    stage("rig", secs=round(dt, 1), ok=ok, gallop_airborne=susp, legs_cells=lay["ZL"], hip_z_m=lay["HIP_Z"], guards=guards, err=(None if ok else out[-800:]))
    rep["ok"] = ok; json.dump(rep, open(os.path.join(D, "report.json"), "w"), indent=1)
    print(f"\n{'OK' if ok else 'FAILED'}  {glb_out if ok else '(see run.log)'}")
    if ok and not susp: print("  note: gallop has no airborne frame (legs too short) - Walk and the other clips are fine, Gallop will look like a fast trot.")
    sys.exit(0 if ok else 2)

if __name__ == "__main__": main()
