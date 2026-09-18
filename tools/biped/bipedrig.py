"""Derive a humanoid body plan from a voxel grid (.vox), the way voxrig.py does for quadrupeds.

    python bipedrig.py <model.vox> <outdir> --name Name --height-m 1.8

Writes <outdir>/layout.json (bone heads/tails in metres, voxel bands) and <outdir>/<name>_rules.py
(exact per-voxel bone table + bone_for_voxel(x, y, z)). Conventions: x = width (character's left is +x),
y = depth (faces -Y), z = up. Works for arms hanging down (A/I-pose) and for T-pose arms.

Body plan, read bottom-up from per-layer connected components (blobs):
  feet   bottom layers whose blobs reach further forward (y) than the leg columns above them
  legs   the lowest band of layers that still has two separate blobs, one each side of the midline
  hips / spine / chest   the torso above the crotch, split 1/6 : 1/3 : 1/2 up to the neck
  arms   hanging: layers with >= 3 blobs -> the two outboard blobs; T-pose: layers whose x-extent
         exceeds the torso by >= 2 voxels a side -> everything beyond the torso edge
  head   the blob above the neck (the narrowest layer in the top 45% of the body)
  hands  the bottom 20% of a hanging arm / outer 20% of a T-pose arm (weapon-slot carrier)
"""
import sys, os, json, struct
from collections import defaultdict


def load_vox(path):
    d = open(path, "rb").read()
    assert d[:4] == b"VOX ", "not a MagicaVoxel file"
    i = 8; size = None; voxels = []
    while i < len(d):
        cid = d[i:i + 4]; n, m = struct.unpack_from("<II", d, i + 4); body = d[i + 12:i + 12 + n]
        if cid == b"SIZE" and size is None: size = struct.unpack_from("<III", body, 0)
        elif cid == b"XYZI" and not voxels:
            cnt = struct.unpack_from("<I", body, 0)[0]
            voxels = [tuple(body[4 + 4 * k: 8 + 4 * k]) for k in range(cnt)]
        i += 12 + n
    return size, voxels                    # voxels: (x, y, z, colour index)


def blobs(cells):
    """8-connected components of a set of (x, y) cells."""
    cells = set(cells); out = []
    while cells:
        seed = cells.pop(); comp = {seed}; stack = [seed]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (x + dx, y + dy)
                    if nb in cells: cells.remove(nb); comp.add(nb); stack.append(nb)
        out.append(comp)
    return out


def fill_layer(cells, X, Y):
    """Add every empty cell that cannot reach the grid border (hollow-shell interiors)."""
    cells = set(cells); outside = set(); stack = [(x, y) for x in range(-1, X + 1) for y in (-1, Y)] + [(x, y) for y in range(-1, Y + 1) for x in (-1, X)]
    while stack:
        c = stack.pop()
        if c in outside or c in cells or not (-1 <= c[0] <= X and -1 <= c[1] <= Y): continue
        outside.add(c); x, y = c; stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return {(x, y) for x in range(X) for y in range(Y) if (x, y) not in outside}


def ext(comp, k):
    v = [c[k] for c in comp]; return min(v), max(v)


def analyze(size, voxels, height_m):
    X, Y, Z = size
    shell = defaultdict(set)
    for x, y, z, _ in voxels: shell[z].add((x, y))
    occ = {z: fill_layer(c, X, Y) for z, c in shell.items()}       # solid slices for the analysis
    zs = sorted(occ); z0, z1 = zs[0], zs[-1]
    H = z1 - z0 + 1; S = height_m / H
    cx = (X - 1) / 2.0; cy = (Y - 1) / 2.0
    layer = {z: blobs(occ[z]) for z in zs}

    # --- legs: the lowest band with one blob either side of the midline
    def two_legs(z):
        bs = layer.get(z, [])
        if len(bs) < 2: return None
        big = sorted(bs, key=len, reverse=True)[:2]
        cs = sorted((sum(c[0] for c in b) / len(b), b) for b in big)
        return (cs[0][1], cs[1][1]) if cs[0][0] < cx < cs[1][0] else None
    if not two_legs(z0):
        raise SystemExit("bottom layer is not two legs (found %d blob(s)); is the model standing on two feet?" % len(layer[z0]))
    ZL = z0                                                   # last layer with two separate legs (crotch below ZL+1)
    while two_legs(ZL + 1): ZL += 1
    legR, legL = two_legs((z0 + ZL) // 2)                     # R = -x side (character's right), L = +x
    leg_h = ZL + 1 - z0
    pelvis = int(round(0.35 * leg_h))                         # chibi pelvis block moves with the legs
    ZJ = ZL + 1 + pelvis                                      # hip joint layer boundary (torso starts here)
    ZJ_from_legs = ZJ
    # feet: bottom layers whose blobs reach >= 2 voxels further forward (-y) than the mid-leg column
    ymid = min(ext(legR, 1)[0], ext(legL, 1)[0])
    ZF = z0 - 1
    for z in range(z0, ZL + 1):
        pair = two_legs(z)
        if pair and min(ext(pair[0], 1)[0], ext(pair[1], 1)[0]) <= ymid - 2: ZF = z
        else: break

    def torso_blob(z):
        mids = [b for b in layer[z] if ext(b, 0)[0] <= cx <= ext(b, 0)[1]]
        return max(mids, key=len) if mids else max(layer[z], key=len)

    # --- arms. The trunk's x-extent is measured just above the crotch (solid there even when the torso shell
    #     above has holes). Arm cells are the cells outside it; a column starts where both sides have blobs lying
    #     entirely outside the trunk (free-hanging arms), continues while contiguous, and may end with a few
    #     "merged" layers (shoulders fused into the torso), capped at 0.8x the free part so a wide head is not eaten.
    torso_w = {z: ext(torso_blob(z), 0) for z in zs}
    tz = [z for z in (ZL + 1, ZL + 2) if z in layer]
    trunk = ext(max((max(layer[z], key=len) for z in tz), key=len), 0) if tz else torso_w[ZL]
    def outside(z):
        return {c for c in occ[z] if c[0] < trunk[0]}, {c for c in occ[z] if c[0] > trunk[1]}
    def contiguous(prev, cur): return any(max(abs(a[0] - c[0]), abs(a[1] - c[1])) <= 1 for a in prev for c in cur)
    def accept(c): return bool(c) and max(c) >= z0 + 0.5 * H and len(c) >= max(3, 0.12 * H)
    arm_layers = {}; col = {}; prev = None; counts = []
    DEBUG = os.environ.get("BIPEDRIG_DEBUG")
    for z in range(ZL + 1, z1 + 1):
        R, L = outside(z); n = len(R) + len(L)
        if DEBUG: print("  arm z%2d R%d L%d col=%s contig=%s" % (z, len(R), len(L), sorted(col)[:1] + sorted(col)[-1:], contiguous(prev, R | L) if (col and n) else "-"))
        if col and n and contiguous(prev, R | L):
            med = sorted(counts)[len(counts) // 2]
            if z >= z0 + 0.75 * H and n > 2.5 * med:            # a hat / wide head sitting on the shoulders: stop below it
                break
            col[z] = (R, L, "hang"); prev = R | L; counts.append(n); continue
        if col:                                                 # column ended
            if accept(col): break
            col = {}; prev = None; counts = []                 # junk (e.g. legs beside a skirt): discard, keep scanning
        if R and L: col[z] = (R, L, "hang"); prev = R | L; counts = [n]
    if accept(col): arm_layers = col
    if arm_layers:
        mode = "hang"
    else:
        # T-pose: no free-hanging columns; arms are the wide band(s) whose x-extent exceeds the trunk by >= 2 a side
        mode = "tpose"
        trunk_w0 = trunk[1] - trunk[0] + 1
        for z in range(ZJ, z1 + 1):
            tb = torso_blob(z); lo, hi = torso_w[z]
            if (hi - lo + 1) >= trunk_w0 + 4:
                r = {c for c in tb if c[0] < trunk[0]}; l = {c for c in tb if c[0] > trunk[1]}
                if r and l: arm_layers[z] = (r, l, "tpose")
        if not arm_layers: raise SystemExit("no arms found (no outboard blobs above the crotch and no wide T-pose band)")
    az = sorted(arm_layers); A0, A1 = az[0], az[-1]
    armR = set().union(*[arm_layers[z][0] for z in az]); armL = set().union(*[arm_layers[z][1] for z in az])
    trunk_w = trunk[1] - trunk[0] + 1
    if leg_h < 0.22 * H and mode == "hang":                   # legs hidden by a skirt/apron: hands hang at hip height
        ZJ = max(ZJ_from_legs, min(A0, z0 + int(0.5 * H)))
    ZJ = max(ZJ, z0 + 2); ZJ = min(ZJ, A1 - 2)
    # head: first layer above the shoulder line narrower than the trunk (a neck / the head), else straight above it
    ZH = next((z for z in range(A1 + 1, z1 + 1) if torso_w[z][1] - torso_w[z][0] + 1 < trunk_w), A1 + 1)
    if ZH > z1: raise SystemExit("no head above the shoulder line")
    ZN = ZH - 1

    def centroid(cells):
        n = len(cells); return (sum(c[0] for c in cells) / n, sum(c[1] for c in cells) / n)

    m = lambda v: round(v * S, 4)
    torso_h = ZH - ZJ
    z_hips, z_spine, z_chest = ZJ, ZJ + max(1, round(torso_h / 6)), ZJ + max(2, round(torso_h / 2))
    legs = {}
    for name, cells in (("R", legR), ("L", legL)):
        cxl, cyl = centroid(cells)
        ankle = ZF + 1
        knee = ankle + (ZJ - ankle) * 0.45
        legs[name] = dict(cx=cxl + 0.5, cy=cyl + 0.5, hip_z=ZJ, knee_z=knee, ankle_z=ankle, cells=len(cells))
    arms = {}
    for name, cells in (("R", armR), ("L", armL)):
        if mode == "hang":
            cxa, cya = centroid(cells)
            top = A1 + 1; bot = A0; n = top - bot
            shoulder = top - 0.3 * n                            # voxels above the joint are shoulder bulk
            wrist = bot + 0.2 * n
            elbow = wrist + (shoulder - wrist) * 0.45
            P = lambda zz: (cxa + 0.5, cya + 0.5, zz)
            arms[name] = dict(mode=mode, shoulder=P(shoulder), elbow=P(elbow), wrist=P(wrist), hand_end=P(bot), cells=len(cells))
        else:
            xs = ext(cells, 0); cya = centroid(cells)[1]; zc = (A0 + A1 + 1) / 2.0
            inner, outer = (xs[1] + 1, xs[0]) if name == "R" else (xs[0], xs[1] + 1)
            span = outer - inner
            P = lambda u: (inner + span * u, cya + 0.5, zc)
            arms[name] = dict(mode=mode, shoulder=P(0.0), elbow=P(0.45), wrist=P(0.8), hand_end=P(1.0), cells=len(cells))
    C = lambda zz: [cx + 0.5, cy + 0.5, zz]
    layout = dict(
        S=S, size=[X, Y, Z], height_m=height_m, facing="-Y", arm_mode=mode,
        bands=dict(feet=[z0, ZF], legs=[z0, ZJ - 1], hips=[z_hips, z_spine - 1], spine=[z_spine, z_chest - 1],
                   chest=[z_chest, ZN], head=[ZH, z1], arms=[A0, A1]),
        bones=dict(hips=dict(head=C(ZJ), tail=C(z_spine)), spine=dict(head=C(z_spine), tail=C(z_chest)),
                   chest=dict(head=C(z_chest), tail=C(ZH)), head=dict(head=C(ZH), tail=C(z1 + 1))),
        legs=legs, arms=arms,
    )
    for side in ("L", "R"):
        lg = legs[side]; ar = arms[side]
        layout["bones"][f"leg{side}.upper"] = dict(head=[lg["cx"], lg["cy"], lg["hip_z"]], tail=[lg["cx"], lg["cy"], lg["knee_z"]])
        layout["bones"][f"leg{side}.lower"] = dict(head=[lg["cx"], lg["cy"], lg["knee_z"]], tail=[lg["cx"], lg["cy"], lg["ankle_z"]])
        layout["bones"][f"foot{side}"] = dict(head=[lg["cx"], lg["cy"], lg["ankle_z"]], tail=[lg["cx"], lg["cy"] - max(2.0, (ZF + 1 - z0) * 1.5), z0 + 0.5])
        layout["bones"][f"arm{side}.upper"] = dict(head=list(ar["shoulder"]), tail=list(ar["elbow"]))
        layout["bones"][f"arm{side}.lower"] = dict(head=list(ar["elbow"]), tail=list(ar["wrist"]))
        layout["bones"][f"hand{side}"] = dict(head=list(ar["wrist"]), tail=list(ar["hand_end"]))
    layout["bones_m"] = {k: dict(head=[m(v) for v in b["head"]], tail=[m(v) for v in b["tail"]]) for k, b in layout["bones"].items()}
    warn = []
    if ZF < z0: warn.append("no feet found (toes should reach >= 2 voxels forward of the shins)")
    if (ZJ - z0) / H < 0.2: warn.append("legs shorter than 20%% of the height (%d layers)" % (ZJ - z0))
    if (z1 + 1 - ZH) / H > 0.45: warn.append("head taller than 45%% of the height (%d layers): shoulder line probably wrong" % (z1 + 1 - ZH))
    if (A1 + 1 - z0) / H < 0.5: warn.append("shoulder line below half height")
    if abs(len(armR) - len(armL)) > 0.5 * max(len(armR), len(armL), 1): warn.append("arms very asymmetric (%d vs %d cells)" % (len(armR), len(armL)))
    layout["warnings"] = warn; layout["ok"] = not warn

    # --- exact per-voxel assignment
    assign = {}
    for z in zs:
        for (x, y) in occ[z]:
            b = None
            if z in arm_layers:
                r, l = arm_layers[z][0], arm_layers[z][1]
                side = "R" if (x, y) in r else "L" if (x, y) in l else None
                if side:
                    ar = arms[side]
                    if mode == "hang":
                        t = z + 0.5
                        b = f"hand{side}" if t < ar["wrist"][2] else f"arm{side}.lower" if t < ar["elbow"][2] else f"arm{side}.upper"
                    else:
                        inner, outer = ar["shoulder"][0], ar["hand_end"][0]
                        u = (x + 0.5 - inner) / (outer - inner) if outer != inner else 0
                        b = f"hand{side}" if u > 0.8 else f"arm{side}.lower" if u > 0.45 else f"arm{side}.upper"
            if b is None:
                if z >= ZH: b = "head"
                elif z >= z_chest: b = "chest"
                elif z >= z_spine: b = "spine"
                elif z >= z_hips: b = "hips"
                else:
                    side = "L" if x > cx else "R"
                    b = f"foot{side}" if z <= ZF else (f"leg{side}.lower" if z + 0.5 < legs[side]["knee_z"] else f"leg{side}.upper")
            assign[(x, y, z)] = b
    return layout, assign


def facing_report(size, voxels):
    """Is the model upright, wider than deep, with toes pointing -Y? Used by the yaw sweep in run_character.py."""
    X, Y, Z = size
    occ = defaultdict(set)
    for x, y, z, _ in voxels: occ[z].add((x, y))
    zs = sorted(occ); z0 = zs[0]
    cx = (X - 1) / 2.0
    bottom = layer_cells = occ[z0]
    legs = blobs(bottom)
    two = len(legs) >= 2 and sorted(sum(c[0] for c in b) / len(b) for b in sorted(legs, key=len, reverse=True)[:2])[0] < cx < sorted(sum(c[0] for c in b) / len(b) for b in sorted(legs, key=len, reverse=True)[:2])[1]
    band = int(max(2, round(0.05 * (zs[-1] - z0 + 1))))
    feet = set().union(*[occ[z] for z in zs[:band]]); legs_mid = set().union(*[occ[z] for z in zs if band * 2 <= z - z0 <= band * 4]) or feet
    fy = sum(c[1] for c in feet) / len(feet); ly = sum(c[1] for c in legs_mid) / len(legs_mid)
    return dict(two_legs=two, wider_than_deep=X >= Y, toes_neg_y=fy < ly - 0.3, toes_pos_y=fy > ly + 0.3, size=[X, Y, Z])


def write_rules(path, assign, name):
    by_bone = defaultdict(list)
    for k, b in assign.items(): by_bone[b].append(k)
    with open(path, "w") as f:
        f.write(f'"""Exact voxel->bone table for {name} (generated by bipedrig.py). Passed to the biped builder."""\n')
        f.write("BONES = %r\n" % sorted(by_bone))
        f.write("_T = {}\n")
        for b in sorted(by_bone):
            cells = sorted(by_bone[b])
            f.write("for _c in %r: _T[_c] = %r\n" % (cells, b))
        f.write("\n\ndef bone_for_voxel(x, y, z):\n    b = _T.get((x, y, z))\n    if b is None:  # a voxel not in the table (edited model): nearest table cell\n"
                "        b = _T[min(_T, key=lambda c: (c[0]-x)**2 + (c[1]-y)**2 + (c[2]-z)**2)]\n    return b\n")


if __name__ == "__main__":
    argv = sys.argv[1:]
    vox, outdir = argv[0], argv[1]
    name = argv[argv.index("--name") + 1] if "--name" in argv else os.path.splitext(os.path.basename(vox))[0]
    height = float(argv[argv.index("--height-m") + 1]) if "--height-m" in argv else 1.8
    size, voxels = load_vox(vox)
    layout, assign = analyze(size, voxels, height)
    os.makedirs(outdir, exist_ok=True)
    json.dump(layout, open(os.path.join(outdir, "layout.json"), "w"), indent=1)
    write_rules(os.path.join(outdir, f"{name.lower()}_rules.py"), assign, name)
    counts = defaultdict(int)
    for b in assign.values(): counts[b] += 1
    print("LAYOUT %s: size %s, %d voxels, S=%.4f m, arms=%s, bands=%s" % (name, list(size), len(voxels), layout["S"], layout["arm_mode"], layout["bands"]))
    print("ASSIGN", dict(sorted(counts.items())))
