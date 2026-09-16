"""Voxel-grid analysis for quadrupeds: facing check, body-plan layout, bone-rule generation.
Grid convention after facing normalisation (matches the project): x lateral (+X = animal's
left), y along the body with the HEAD at low y (model faces -Y), z up. 1 cell = S metres."""
import json, struct, math
from collections import defaultdict, deque

def load_vox(path):
    buf = open(path, "rb").read(); off = 8; size = None; vox = []; pal = None
    while off < len(buf):
        cid = buf[off:off+4]; content, children = struct.unpack_from("<ii", buf, off+4); off += 12; c = off
        if cid == b"SIZE": size = struct.unpack_from("<iii", buf, c)
        elif cid == b"XYZI":
            n, = struct.unpack_from("<i", buf, c); vox = [struct.unpack_from("<4B", buf, c+4+i*4) for i in range(n)]
        elif cid == b"RGBA": pal = [struct.unpack_from("<4B", buf, c+i*4) for i in range(256)]
        off = c + content
        if cid != b"MAIN": off += children
    return size, vox, pal

def occ_of(vox): return {(x,y,z) for x,y,z,_ in vox}

def layer_stats(size, occ):
    X,Y,Z = size; out = []
    for z in range(Z):
        cells = {(x,y) for (x,y,zz) in occ if zz == z}
        comps = 0; seen = set()
        for c in cells:
            if c in seen: continue
            comps += 1; dq = deque([c]); seen.add(c)
            while dq:
                x,y = dq.popleft()
                for n in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                    if n in cells and n not in seen: seen.add(n); dq.append(n)
        out.append((z, len(cells), comps))
    return out

def top_profile(size, occ):
    X,Y,Z = size; prof = {}
    for y in range(Y):
        zs = [z for (x,yy,z) in occ if yy == y]
        prof[y] = max(zs) if zs else -1
    return prof

def facing_report(size, occ):
    """Which end is the head? The taller end (head/ears/neck rise above the back)."""
    X,Y,Z = size; prof = top_profile(size, occ)
    n = max(2, int(Y*0.30))
    front = [prof[y] for y in range(0, n) if prof[y] >= 0]
    back  = [prof[y] for y in range(Y-n, Y) if prof[y] >= 0]
    f = sum(front)/max(1,len(front)); b = sum(back)/max(1,len(back))
    return {"long_axis_is_y": Y >= X, "front_top": round(f,2), "back_top": round(b,2), "head_at_low_y": f >= b}

def analyze(size, occ, S):
    X,Y,Z = size; CX, CY = X/2.0, Y/2.0
    ls = layer_stats(size, occ)
    counts = [c for _,c,_ in ls]; comps = [k for _,_,k in ls]
    # leg zone: bottom layers that are still split into >=2 blobs; body starts at the first
    # single-blob layer (or a layer whose count doubles the paw layer). At least 1 cell, at most 45%.
    ZL = 1
    for z in range(1, Z):
        if comps[z] <= 1 and counts[z] >= 1.5*counts[0]: ZL = z; break
        if counts[z] >= 2.2*counts[0]: ZL = z; break
        ZL = z+1
    ZL = max(1, min(ZL, int(Z*0.45)))
    if Z >= 10 and ZL < 2: ZL = 2
    ZK = max(1, ZL//2)
    # tail FIRST: a trailing run of slices that are both thin (count) and narrow (x-span) — hanging tails reach z=0,
    # so they must be removed before paw clustering or they get glued to the hind legs
    counts_y = defaultdict(int); xs_y = defaultdict(list)
    for (x,y,z) in occ: counts_y[y] += 1; xs_y[y].append(x)
    mid_counts = sorted(counts_y[y] for y in range(int(Y*0.4), max(int(Y*0.4)+1, int(Y*0.6))))
    body_slice = mid_counts[len(mid_counts)//2] if mid_counts else 1
    mid_spans = sorted((max(xs_y[y]) - min(xs_y[y]) + 1) for y in range(int(Y*0.4), max(int(Y*0.4)+1, int(Y*0.6))) if xs_y[y])
    body_span = mid_spans[len(mid_spans)//2] if mid_spans else X       # body width, immune to ears/horns/antlers inflating X
    tail_ys = []
    for y in range(Y-1, int(Y*0.55), -1):
        if not counts_y[y]: break
        span = max(xs_y[y]) - min(xs_y[y]) + 1
        if span <= max(2, 0.5*body_span): tail_ys.append(y)   # narrow slice = tail; 1-2 cells wide is always a tail
        else: break
    TAIL = len(tail_ys) >= 1
    TAIL_Y0 = min(tail_ys) if TAIL else Y
    body_occ = {c for c in occ if c[1] < TAIL_Y0}
    # paws: cluster z=0 cells into 4 quadrants around the leg-cell centroid (tail excluded)
    paw = [(x,y) for (x,y,z) in body_occ if z == 0]
    legcells = [(x,y) for (x,y,z) in body_occ if z < ZL]
    cyl = sum(y for _,y in legcells)/len(legcells); cxl = sum(x for x,_ in legcells)/len(legcells)
    quads = defaultdict(list)
    for x,y in paw:
        quads[("F" if y < cyl else "H") + ("L" if x >= cxl else "R")].append((x,y))
    legs = {}
    for q in ("FL","FR","HL","HR"):
        cells = quads.get(q) or []
        if not cells:  # missing paw -> mirror its partner
            m = q[0] + ("R" if q[1]=="L" else "L"); cells = [(int(2*cxl - x), y) for x,y in quads.get(m, [(round(cxl),round(cyl))])]
        xs=[x for x,_ in cells]; ys=[y for _,y in cells]
        legs[q] = {"cx": sum(xs)/len(xs)+0.5, "cy": sum(ys)/len(ys)+0.5,
                   "box": [min(xs)-1, min(ys)-1, max(xs)+1, max(ys)+1]}
    LEG_Y = {"F": sum(legs[q]["cy"] for q in ("FL","FR"))/2, "H": sum(legs[q]["cy"] for q in ("HL","HR"))/2}
    # back line & head
    prof = top_profile(size, occ)
    mid = [prof[y] for y in range(int(Y*0.35), int(Y*0.65)) if prof[y] >= 0]
    BT = int(sorted(mid)[len(mid)//2]) if mid else Z-1          # body top (median back height)
    HEAD_Y = max(1, int(round(Y*0.22)))                          # front 22% above the legs is head
    head_cells = [(x,y,z) for (x,y,z) in occ if (y < HEAD_Y and z >= ZL) or (z > BT and y < Y*0.5)]
    if head_cells:
        hy = min(y for _,y,_ in head_cells); hz = max(z for *_,z in head_cells); hcz = sum(z for *_,z in head_cells)/len(head_cells)
    else: hy, hz, hcz = 0, BT, BT
    tail_cells = [(x,y,z) for (x,y,z) in occ if y >= TAIL_Y0]
    if TAIL:
        first = [c for c in tail_cells if c[1] == TAIL_Y0]; last = [c for c in tail_cells if c[1] == max(c2[1] for c2 in tail_cells)]
        rz = sum(z for *_,z in first)/len(first); tipz = sum(z for *_,z in last)/len(last); tipx = sum(x for x,*_ in last)/len(last)
        tail_root = [0, round((TAIL_Y0 - 0.5 - CY)*S, 4), round((rz + 0.5)*S, 4)]
        tail_tip  = [round((tipx + 0.5 - CX)*S, 4), round((max(c[1] for c in tail_cells) + 1.0 - CY)*S, 4), round((tipz + 0.5)*S, 4)]
        if abs(tail_tip[1]-tail_root[1]) < 1.5*S and abs(tail_tip[2]-tail_root[2]) < 1.0*S:   # stub: give the bone some length
            tail_tip = [tail_root[0], tail_root[1] + 2.0*S, tail_root[2] + 0.5*S]
    else:
        tail_root = [0, round((Y-1-CY)*S,4), round((BT+0.5)*S,4)]; tail_tip = [0, round((Y+1.5-CY)*S,4), round((BT+1.5)*S,4)]
    L = Y*S; H = Z*S
    leg_len = ZL*S
    layout = {
        "S": S, "X": X, "Y": Y, "Z": Z, "CX": CX, "CY": CY, "ZL": ZL, "ZK": ZK, "BT": BT, "HEAD_Y": HEAD_Y,
        "TAIL": TAIL, "MID_Y": int(Y*0.5), "CXL": cxl, "CYL": cyl,
        "legs": legs,
        "LEG_X": {q: round((legs[q]["cx"]-CX)*S, 4) for q in legs},
        "LEG_Y": {k: round((v-CY)*S, 4) for k,v in LEG_Y.items()},
        "HIP_Z": round((ZL+0.5)*S, 4), "KNEE_Z": round(ZK*S, 4), "leg_len": round(leg_len,4),
        "length_m": round(L,3), "height_m": round(H,3),
        "body_mid_z": round((ZL + BT)/2*S + 0.5*S, 4), "body_top_z": round((BT+1)*S, 4),
        "head_root": [0, round((HEAD_Y-CY)*S,4), round((BT+0.5)*S,4)],
        "head_tip":  [0, round((hy-CY-0.5)*S,4), round((hcz+1.0)*S,4)],
        "tail_root": tail_root, "tail_tip": tail_tip, "TAIL_Y0": TAIL_Y0, "tail_slices": len(tail_ys),
        "layers": ls,
    }
    return layout

def gen_rules(layout, name):
    L = layout; legs = L["legs"]
    boxes = {q: legs[q]["box"] for q in legs}
    return f'''"""Auto-derived voxel->bone rules for {name} (generated by voxrig.py). Grid {L["X"]}x{L["Y"]}x{L["Z"]}, S={L["S"]}.
Leg zone z<{L["ZL"]} (knee at z<{L["ZK"]}), body top z={L["BT"]}, head y<{L["HEAD_Y"]}, tail={L["TAIL"]}."""
ZL, ZK, BT, HEAD_Y, MID_Y, HALF_Y, Y = {L["ZL"]}, {L["ZK"]}, {L["BT"]}, {L["HEAD_Y"]}, {L["MID_Y"]}, {L["Y"]*0.5}, {L["Y"]}
TAIL, TAIL_Y0 = {"True" if L["TAIL"] else "False"}, {L["TAIL_Y0"]}
CXL, CYL = {L["CXL"]:.3f}, {L["CYL"]:.3f}
BOX = {json.dumps(boxes)}

def _in(box, x, y):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]

def bone_for_voxel(x, y, z):
    if TAIL and y >= TAIL_Y0:
        return "tail"
    if z < ZL:
        q = ("F" if y < CYL else "H") + ("L" if x >= CXL else "R")   # +X = animal's left
        if _in(BOX[q], x, y):
            return f"{{q}}.lower" if z < ZK else f"{{q}}.upper"
        # low body between the legs (belly) stays with the torso
        return "chest" if y <= MID_Y else "hips"
    if y < HEAD_Y or (z > BT and y < HALF_Y):
        return "head"
    return "chest" if y <= MID_Y else "hips"
'''

if __name__ == "__main__":
    import sys
    vox = sys.argv[1]; S = float(sys.argv[2]) if len(sys.argv) > 2 else 0.05
    size, v, pal = load_vox(vox); occ = occ_of(v)
    print("SIZE", size, "voxels", len(v)); print("FACING", facing_report(size, occ))
    lay = analyze(size, occ, S)
    print("LAYERS z:(count,comps)", [(z,c,k) for z,c,k in lay["layers"]])
    print("LAYOUT ZL", lay["ZL"], "ZK", lay["ZK"], "BT", lay["BT"], "HEAD_Y", lay["HEAD_Y"], "TAIL", lay["TAIL"])
    print("LEGS", {q: (round(l["cx"],1), round(l["cy"],1), l["box"]) for q,l in lay["legs"].items()})
    print("LEG_X", lay["LEG_X"], "LEG_Y", lay["LEG_Y"], "HIP_Z", lay["HIP_Z"], "KNEE_Z", lay["KNEE_Z"])
