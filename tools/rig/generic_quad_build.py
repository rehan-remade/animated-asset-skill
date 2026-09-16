"""Generic quadruped rig + animation builder (runs inside headless Blender 5.2).

  blender -b --factory-startup --python generic_quad_build.py -- <model.vox> <outdir> [render] [video] [export] \
      --layout <layout.json> --rules <name_rules.py> --name <Name> [--extra <dir of clip modules>] [--only-clips A,B]

layout.json and the rules module come from voxrig.py (derived from the voxel grid). Builds the voxel mesh with
rigid per-bone weights, a 14-bone rig (hips/chest/head/2 ears/tail + 4x upper/lower legs), the base clips
Idle / Walk / Gallop / Graze / Alert with numeric gait guards, then exec's each module in --extra (Trot, Jump,
Sit, Sleep, Shake, Stretch, LookAround, Rear) in this namespace, and exports <Name>_animated.glb with every clip.
Gait constants are scaled by K = HIP_Z / 0.125 (leg reach relative to the corgi the gaits were tuned on).
"""
import math
import os
import struct
import sys

import bpy
from mathutils import Vector

bpy.ops.wm.read_factory_settings(use_empty=True)  # no default cube/light/cam

import json, importlib.util
argv = sys.argv[sys.argv.index("--") + 1:]
def _opt(flag, default=None):
    if flag in argv:
        i = argv.index(flag); v = argv[i + 1]; del argv[i:i + 2]; return v
    return default
LAYOUT = json.load(open(_opt("--layout")))
RULES_PATH = _opt("--rules")
NAME = _opt("--name", "Creature")
EXTRA_DIR = _opt("--extra")          # dir of extra clip modules, exec'd in this namespace after Idle
ONLY_CLIPS = _opt("--only-clips")     # comma list: restrict video/still renders to these clips
_spec = importlib.util.spec_from_file_location("rules", RULES_PATH); _rules = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_rules)
bone_for_voxel = _rules.bone_for_voxel  # single source of truth for weights (shared with the baker)

VOX_PATH = argv[0]
OUT_DIR = argv[1]
DO_RENDER = "render" in argv[2:]
DO_VIDEO = "video" in argv[2:]
DO_EXPORT = "export" in argv[2:]

S = LAYOUT["S"]
CX, CY = LAYOUT["CX"], LAYOUT["CY"]
FPS = 24
K = LAYOUT["HIP_Z"] / 0.125          # leg-reach scale relative to the corgi the gait was tuned on
KH = LAYOUT["height_m"] / 0.70       # height scale (sniff target, cameras)
KL = LAYOUT["length_m"] / 0.90       # length scale (cameras)
KC = max(KH, KL)
KNEE_WALK = LAYOUT["HIP_Z"] >= 0.30  # long legs: 2-bone IK in the walk too (columns read stiff)
def _clamp(v, lo, hi): return max(lo, min(hi, v))

# ---- walk tuning (corgi waddle: quick cadence, tiny stride, big roll) --------
CYC = int(_clamp(round(16 * math.sqrt(K)), 12, 36))
STRIDE_F = 0.075 * K
STRIDE_H = 0.075 * K
STEP_H_F = 0.030 * K
STEP_H_H = 0.026 * K
STANCE = 0.60
PEEL = 0.15
PEEL_H = 0.008 * K
BODY_DROP = 0.003 * K
                     # z=0, and the engine hoof snap then buries the stub legs
                     # into the belly (baked paw-plane audit: keep >= -0.2 vox)
BOB_AMP = 0.006 * K
SURGE_AMP = 0.004 * K
ROLL_AMP = 5.0       # deg — the waddle
PITCH_AMP = 1.2
HEAD_BOB = 2.0       # deg, head counter-nod
WAG_WALK = 7.0       # deg, tail yaw sway with the roll (butt wiggle)
EAR_BOB = 3.0        # deg, passive ear pitch against the bob
PHASE = {"HL": 0.00, "FL": 0.75, "HR": 0.50, "FR": 0.25}
LX_SIGN = -1.0       # local-X sign tilting a bone tail toward -Y (stag-verified)
KNEE_S = {"F": 1.0, "H": -1.0}   # carpus apex forward, hock apex backward

# ---- vox load ----------------------------------------------------------------
def load_vox(path):
    buf = open(path, "rb").read()
    off, size, vox, pal = 8, None, [], None
    while off < len(buf):
        cid = buf[off:off + 4]
        content, children = struct.unpack_from("<ii", buf, off + 4)
        off += 12
        c = off
        if cid == b"SIZE":
            size = struct.unpack_from("<iii", buf, c)
        elif cid == b"XYZI":
            n, = struct.unpack_from("<i", buf, c)
            vox = [struct.unpack_from("<4B", buf, c + 4 + i * 4) for i in range(n)]
        elif cid == b"RGBA":
            pal = [struct.unpack_from("<4B", buf, c + i * 4) for i in range(256)]
        off = c + content
        if cid != b"MAIN":
            off += children
    return size, vox, pal


def srgb_to_linear(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# claim order: parents first so shared boundary verts stay body-side
BONE_ORDER = ["hips", "chest", "head", "earL", "earR", "tail",
              "FL.upper", "FR.upper", "HL.upper", "HR.upper",
              "FL.lower", "FR.lower", "HL.lower", "HR.lower"]

# ---- build mesh ---------------------------------------------------------------
size, voxels, palette = load_vox(VOX_PATH)
occ = {(x, y, z): ci for x, y, z, ci in voxels}

verts, vmap, faces, face_bone, face_col = [], {}, [], [], []

FACE_DIRS = [
    ((1, 0, 0),  [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
    ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
    ((0, 1, 0),  [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
    ((0, 0, 1),  [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)]),
]


def vidx(px, py, pz):
    key = (px, py, pz)
    if key not in vmap:
        vmap[key] = len(verts)
        verts.append(((px - CX) * S, (py - CY) * S, pz * S))
    return vmap[key]


for (x, y, z), ci in occ.items():
    bone = bone_for_voxel(x, y, z)
    r, g, b, a = palette[ci - 1] if palette else (200, 200, 200, 255)
    col = (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)
    for (dx, dy, dz), corners in FACE_DIRS:
        if (x + dx, y + dy, z + dz) in occ:
            continue
        faces.append(tuple(vidx(x + cx_, y + cy_, z + cz_) for cx_, cy_, cz_ in corners))
        face_bone.append(bone)
        face_col.append(col)

mesh = bpy.data.meshes.new(NAME)
mesh.from_pydata(verts, [], faces)
mesh.update()

ca = mesh.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="CORNER")
li = 0
for poly, col in zip(mesh.polygons, face_col):
    for _ in range(poly.loop_total):
        ca.data[li].color = col
        li += 1

obj = bpy.data.objects.new(NAME, mesh)
bpy.context.collection.objects.link(obj)

mat = bpy.data.materials.new(NAME + "Vox")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
vc = mat.node_tree.nodes.new("ShaderNodeVertexColor")
vc.layer_name = "Col"
mat.node_tree.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.85
mesh.materials.append(mat)

# ---- armature -------------------------------------------------------------------
arm_data = bpy.data.armatures.new(NAME + "Rig")
arm = bpy.data.objects.new(NAME + "Rig", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")

# leg centers measured from the ASCII slices (model is slightly off-center)
LEG_X = LAYOUT["LEG_X"]
LEG_Y = LAYOUT["LEG_Y"]
KNEE_Z, HIP_Z = LAYOUT["KNEE_Z"], LAYOUT["HIP_Z"]
_L = LAYOUT["length_m"]; _BM = LAYOUT["body_mid_z"]; _BTZ = LAYOUT["body_top_z"]
_HR = tuple(LAYOUT["head_root"]); _HT = tuple(LAYOUT["head_tip"])
_TR = tuple(LAYOUT["tail_root"]); _TT = tuple(LAYOUT["tail_tip"])
_EZ = _HT[2] + 0.02
BONES = {
    "root":  ((0, 0.55 * _L, 0.0), (0, 0.33 * _L, 0.0), None, False),
    "hips":  ((0, 0.33 * _L, _BM), (0, 0.06 * _L, _BM + 0.01), "root", False),
    "chest": ((0, 0.06 * _L, _BM + 0.01), (0, -0.20 * _L, _BM + 0.02), "hips", True),
    "head":  (_HR, _HT, "chest", False),
    "earL":  ((0.05 * _L, _HT[1] + 0.05 * _L, _EZ), (0.05 * _L, _HT[1] + 0.05 * _L, _EZ + 0.06), "head", False),
    "earR":  ((-0.05 * _L, _HT[1] + 0.05 * _L, _EZ), (-0.05 * _L, _HT[1] + 0.05 * _L, _EZ + 0.06), "head", False),
    "tail":  (_TR, _TT, "hips", False),
}
for leg in ("FL", "FR", "HL", "HR"):
    lx, ly = LEG_X[leg], LEG_Y[leg[0]]
    parent = "chest" if leg[0] == "F" else "hips"
    BONES[f"{leg}.upper"] = ((lx, ly, HIP_Z), (lx, ly, KNEE_Z), parent, False)
    BONES[f"{leg}.lower"] = ((lx, ly, KNEE_Z), (lx, ly, 0.0), f"{leg}.upper", True)

ebs = arm_data.edit_bones
for name in ["root"] + BONE_ORDER:
    h, t, parent, connect = BONES[name]
    b = ebs.new(name)
    b.head, b.tail = Vector(h), Vector(t)
    if parent:
        b.parent = ebs[parent]
        b.use_connect = connect
bpy.ops.object.mode_set(mode="OBJECT")

# ---- weights (rigid, first-claim in parent-first order) ------------------------
vgroups = {n: obj.vertex_groups.new(name=n) for n in BONE_ORDER}
claimed = set()
by_bone = {n: [] for n in BONE_ORDER}
for f_i, poly in enumerate(mesh.polygons):
    by_bone[face_bone[f_i]].extend(poly.vertices)
for name in BONE_ORDER:
    fresh = [v for v in set(by_bone[name]) if v not in claimed]
    if fresh:
        vgroups[name].add(fresh, 1.0, "REPLACE")
        claimed.update(fresh)

obj.parent = arm
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm

# ---- animation helpers -----------------------------------------------------------
scene = bpy.context.scene
scene.render.fps = FPS

pb = arm.pose.bones
for b in pb:
    b.rotation_mode = "XYZ"

L1 = HIP_Z - KNEE_Z
L2 = KNEE_Z
LEGS = ("FL", "FR", "HL", "HR")


def clear_pose():
    for b in pb:
        b.location = (0, 0, 0)
        b.rotation_euler = (0, 0, 0)


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def foot_traj(p, stride, steph, stance=STANCE, peel=PEEL, peelh=PEEL_H, sharp=0.85):
    """Paw path in sagittal plane; p=0 contact. Returns (fwd, height).
    sharp < 0.85 makes the swing lift ramp faster off the ground — short legs
    need it or takeoff/landing frames read as grounded (no suspension)."""
    if p < stance:
        u = p / stance
        z = 0.0
        if u > 1.0 - peel:
            w = (u - (1.0 - peel)) / peel
            z = peelh * w * w
        return stride * (0.5 - u), z
    u = (p - stance) / (1.0 - stance)
    return stride * (-0.5 + smoothstep(u)), steph * math.sin(math.pi * u ** sharp)


def solve_leg(dx, zf, leg, hip_h, delta=0.0, knee=False):
    """Stub legs default to RIGID COLUMN legs (no knee). The L1/L2 triangle
    is nearly degenerate (total reach 0.125), so any IK slack bends the shank
    15-26 deg, the tilted paw BOX swings its corners below the bone tip, and
    the engine's hoof ground snap then shoves the paw up into the belly —
    in-game the corgi read as sunk to its chest. A column aimed straight at
    the target keeps the box flat; its <=3 mm length surplus buries a paw
    0.03 world voxels, which is invisible.
    knee=True restores 2-bone IK for gaits that must TUCK mid-air (gallop):
    columns cannot fold, and a folded paw's dip happens off the ground where
    the snap preserves the authored clearance anyway."""
    if not knee:
        theta = math.atan2(dx, max(0.02, hip_h - zf))
        return math.degrees(LX_SIGN * (theta - delta)), 0.0
    dz = hip_h - zf
    D = math.hypot(dx, dz)
    D = max(abs(L1 - L2) + 1e-3, min(D, L1 + L2 - 1e-3))
    theta = math.atan2(dx, dz)
    a1 = math.acos(max(-1, min(1, (L1*L1 + D*D - L2*L2) / (2*L1*D))))
    a2 = math.acos(max(-1, min(1, (L1*L1 + L2*L2 - D*D) / (2*L1*L2))))
    s = KNEE_S[leg[0]]
    return (math.degrees(LX_SIGN * (theta - delta + s*a1)),
            math.degrees(LX_SIGN * (-s*(math.pi - a2))))


def key_rot(bone, frame, xyz_deg):
    b = pb[bone]
    b.rotation_euler = [math.radians(a) for a in xyz_deg]
    b.keyframe_insert("rotation_euler", frame=frame)


def key_loc(bone, frame, loc):
    b = pb[bone]
    b.location = loc
    b.keyframe_insert("location", frame=frame)


HIPS_W2L = None


def key_hips_world(frame, dy, dz):
    """Body offset in WORLD space (dy: +Y = tailward, dz: +Z = up)."""
    global HIPS_W2L
    if HIPS_W2L is None:
        HIPS_W2L = pb["hips"].bone.matrix_local.to_3x3().inverted()
    key_loc("hips", frame, tuple(HIPS_W2L @ Vector((0.0, dy, dz))))


def key_stand_legs(frame, hip_h=HIP_Z - BODY_DROP):
    for leg in LEGS:
        ux, lx = solve_leg(0.0, 0.0, leg, hip_h)
        key_rot(f"{leg}.upper", frame, (ux, 0, 0))
        key_rot(f"{leg}.lower", frame, (lx, 0, 0))


def new_action(name):
    act = bpy.data.actions.new(name)
    if arm.animation_data is None:
        arm.animation_data_create()
    arm.animation_data.action = act
    clear_pose()
    return act


def make_cyclic(act):
    for layer in act.layers:
        for strip in layer.strips:
            for slot in act.slots:
                cb = strip.channelbag(slot)
                if cb:
                    for fc in cb.fcurves:
                        if not any(m.type == "CYCLES" for m in fc.modifiers):
                            fc.modifiers.new("CYCLES")


# ---- sign self-calibration (never guess bone-local axes) ---------------------------
def world_point(bone):
    bpy.context.view_layer.update()
    return (arm.matrix_world @ pb[bone].tail).copy()


clear_pose()
REST = {b: world_point(b) for b in ("head", "earL", "tail")}


def probe_sign(bone, axis, point_bone, comp, positive):
    """Sign of +20deg on `axis` that moves point_bone's tail toward `positive`
    along component comp ('x'/'y'/'z')."""
    clear_pose()
    e = [0.0, 0.0, 0.0]
    e["xyz".index(axis)] = math.radians(20)
    pb[bone].rotation_euler = e
    d = world_point(point_bone) - REST[point_bone]
    clear_pose()
    v = getattr(d, comp)
    if not positive:
        v = -v
    return 1.0 if v > 0 else -1.0


H_D = probe_sign("head", "x", "head", "z", False)    # head pitch-down
C_D = probe_sign("chest", "x", "head", "z", False)   # chest pitch-down
HP_D = probe_sign("hips", "x", "head", "z", False)   # whole-body nose-down
H_Y = probe_sign("head", "z", "head", "x", True)     # head yaw-left
E_F = probe_sign("earL", "x", "earL", "y", False)    # ear pitch-forward (-Y)
T_U = probe_sign("tail", "x", "tail", "z", True)     # tail pitch-up
T_Y = probe_sign("tail", "z", "tail", "x", True)     # tail yaw-left
print(f"CAL signs: headD={H_D} chestD={C_D} hipsD={HP_D} headY={H_Y} "
      f"earF={E_F} tailU={T_U} tailY={T_Y}")

# ---- sniff-down calibration (no neck: chest + head do the plunge) -------------------
# The huge head cannot reach the ground without folding under the chest, so
# the fold is CAPPED at 75 deg and the search just gets the nose as low as the
# cap allows (~3 cells) — the chunky scale sells the sniff from there.
SNIFF_CHEST = 6.0    # gentle: chest pitch drops the front-leg roots, and the
SNIFF_DROP = 0.008 * K
TARGET_MUZ_Z = 0.13 * KH
SNIFF_HEAD_MAX = 75.0


def sniff_muzzle_z(t):
    clear_pose()
    pb["chest"].rotation_euler = (math.radians(C_D * SNIFF_CHEST), 0, 0)
    pb["head"].rotation_euler = (math.radians(H_D * t), 0, 0)
    return world_point("head").z - SNIFF_DROP


lo, hi = 20.0, SNIFF_HEAD_MAX
for _ in range(40):
    mid = 0.5 * (lo + hi)
    if sniff_muzzle_z(mid) > TARGET_MUZ_Z:
        lo = mid
    else:
        hi = mid
SNIFF_HEAD = min(0.5 * (lo + hi), SNIFF_HEAD_MAX)
print(f"CAL sniff: head={SNIFF_HEAD:.1f} muzzle_z={sniff_muzzle_z(SNIFF_HEAD):.3f}")
clear_pose()

# ---- gallop tuning (bound: hind pair, front pair, suspension) -----------------------
GCYC = int(_clamp(round(10 * math.sqrt(K)), 8, 16))
STANCE_G = 0.28
PHASE_G = {"HL": 0.00, "HR": 0.04, "FL": 0.52, "FR": 0.56}
STRIDE_G = {"F": 0.10 * K, "H": 0.11 * K}
STEP_G = {"F": 0.060 * K, "H": 0.070 * K}
BODY_DROP_G = 0.022 * K
BOB_G = 0.012 * K
SURGE_G = 0.008 * K
GPITCH = 9.0            # deg, bounding rock
EAR_FLOP = 14.0         # deg, ears trail the bounce
TAIL_UP_G = 12.0


def walk_channels(t):
    bob = -BOB_AMP * math.cos(4 * math.pi * (t + 0.05))
    surge = SURGE_AMP * math.sin(4 * math.pi * t + 0.9)
    roll = ROLL_AMP * math.sin(2 * math.pi * t)
    pitch = PITCH_AMP * math.sin(4 * math.pi * t + 0.7)
    return {"dy": -surge, "dz": -BODY_DROP + bob,
            "hips_rx": pitch, "hips_ry": roll,
            "chest_rx": -pitch * 0.6, "chest_ry": -roll * 0.5,
            "head_rx": -H_D * HEAD_BOB * math.sin(4 * math.pi * t + 1.2),
            "head_ry": 0.0,
            "ear": E_F * EAR_BOB * math.sin(4 * math.pi * t + 2.0),
            "tail_rx": T_U * 3.0,
            "tail_rz": T_Y * WAG_WALK * math.sin(2 * math.pi * t)}


def gallop_channels(g):
    bob = -BOB_G * math.cos(2 * math.pi * (g - 0.45))
    surge = SURGE_G * math.sin(2 * math.pi * (g - 0.1))
    nose_up = GPITCH * math.cos(2 * math.pi * (g - 0.12))
    return {"dy": -surge, "dz": -BODY_DROP_G + bob,
            "hips_rx": -HP_D * nose_up, "hips_ry": 0.0,
            "chest_rx": C_D * 0.45 * nose_up, "chest_ry": 0.0,
            "head_rx": -H_D * 0.35 * nose_up,
            "head_ry": 0.0,
            "ear": -E_F * EAR_FLOP * math.cos(2 * math.pi * (g - 0.12)),
            "tail_rx": T_U * TAIL_UP_G,
            "tail_rz": T_Y * 4.0 * math.sin(2 * math.pi * g)}


def walk_foot(leg, t):
    stride = STRIDE_F if leg[0] == "F" else STRIDE_H
    steph = STEP_H_F if leg[0] == "F" else STEP_H_H
    return foot_traj((t + PHASE[leg]) % 1.0, stride, steph)


def gallop_foot(leg, g):
    return foot_traj((g + PHASE_G[leg]) % 1.0, STRIDE_G[leg[0]], STEP_G[leg[0]],
                     stance=STANCE_G, peel=0.25, peelh=0.012, sharp=0.62)


def key_gait_frame(f, phi, w):
    """Key one frame of a gait: w=0 walk, w=1 gallop (blend-safe like stag)."""
    cw = walk_channels(phi)
    cg = gallop_channels(phi)

    def L(k):
        return (1 - w) * cw[k] + w * cg[k]

    key_hips_world(f, L("dy"), L("dz"))
    key_rot("hips", f, (L("hips_rx"), L("hips_ry"), 0))
    key_rot("chest", f, (L("chest_rx"), L("chest_ry"), 0))
    key_rot("head", f, (L("head_rx"), L("head_ry"), 0))
    key_rot("earL", f, (L("ear"), 0, 0))
    key_rot("earR", f, (L("ear"), 0, 0))
    key_rot("tail", f, (L("tail_rx"), 0, L("tail_rz")))
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for leg in LEGS:
        par = pb["chest" if leg[0] == "F" else "hips"]
        M = par.matrix @ par.bone.matrix_local.inverted()
        root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
        v = M.to_3x3() @ Vector((0, 0, -1))
        delta = math.atan2(-v.y, -v.z)
        fw = walk_foot(leg, phi)
        fg = gallop_foot(leg, phi)
        fdx = (1 - w) * fw[0] + w * fg[0]
        zf = (1 - w) * fw[1] + w * fg[1]
        dx = fdx + (root.y - LEG_Y[leg[0]])
        ux, lx = solve_leg(dx, zf, leg, root.z, delta, knee=(w > 0.5) or KNEE_WALK)
        key_rot(f"{leg}.upper", f, (ux, 0, 0))
        key_rot(f"{leg}.lower", f, (lx, 0, 0))


def key_planted_legs(frames):
    """Key all four legs so the paws stay planted at their rest ground spots
    while the body (already keyed at these frames) pitches/drops around them.
    Body keys MUST exist first: the scene is evaluated per frame, then the leg
    roots come from the parents' pose matrices (eval-stomp-safe like gaits)."""
    for f in frames:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        for leg in LEGS:
            par = pb["chest" if leg[0] == "F" else "hips"]
            M = par.matrix @ par.bone.matrix_local.inverted()
            root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
            v = M.to_3x3() @ Vector((0, 0, -1))
            delta = math.atan2(-v.y, -v.z)
            dx = root.y - LEG_Y[leg[0]]
            ux, lx = solve_leg(dx, 0.0, leg, root.z, delta)
            key_rot(f"{leg}.upper", f, (ux, 0, 0))
            key_rot(f"{leg}.lower", f, (lx, 0, 0))


# ---- clip 1: Walk -------------------------------------------------------------------
walk = new_action("Walk")
for f in range(1, CYC + 2):
    key_gait_frame(f, ((f - 1) % CYC) / CYC, 0.0)
make_cyclic(walk)

# walk guard: planted paws must sweep +Y (tailward) AND touch the ground
dg = bpy.context.evaluated_depsgraph_get()
ok = True
sweep_speeds = []
for leg in ("FL", "HL"):
    ys, zmin = [], 9.9
    for f in range(1, CYC + 1):
        p = (((f - 1) / CYC) + PHASE[leg]) % 1.0
        scene.frame_set(f)
        dg.update()
        ae = arm.evaluated_get(dg)
        tip = ae.matrix_world @ ae.pose.bones[f"{leg}.lower"].tail
        zmin = min(zmin, tip.z)
        if p < STANCE * 0.9:
            ys.append((p, tip.y))
    ys.sort()
    if ys[-1][1] <= ys[0][1] or zmin > 0.06:   # tail may hover by the box dip
        ok = False
    dur = (ys[-1][0] - ys[0][0]) * CYC / FPS
    if dur > 0:
        sweep_speeds.append((ys[-1][1] - ys[0][1]) / dur)
    print(f"WALK GUARD {leg}: sweep {ys[0][1]:+.3f}->{ys[-1][1]:+.3f} minZ={zmin:.3f}")
if sweep_speeds:
    v = sum(sweep_speeds) / len(sweep_speeds)
    print(f"WALK ref speed: {v:.3f} m/s -> walk_ref_speed = {v*10:.2f} voxels/s")
print("DIRECTION GUARD:", "OK forward+grounded" if ok else "FAIL")

# ---- clip 2: Gallop -----------------------------------------------------------------
gallop = new_action("Gallop")
for f in range(1, GCYC + 2):
    key_gait_frame(f, ((f - 1) % GCYC) / GCYC, 1.0)
make_cyclic(gallop)

dg = bpy.context.evaluated_depsgraph_get()
counts = []
gallop_sweep = []
for f in range(1, GCYC + 1):
    scene.frame_set(f)
    dg.update()
    ae = arm.evaluated_get(dg)
    zs = {l: (ae.matrix_world @ ae.pose.bones[f"{l}.lower"].tail).z for l in LEGS}
    n = sum(1 for l in LEGS if zs[l] < 0.02)   # gallop legs are knee-IK: the
    # tail IS the paw tip (the 0.06 column-hover allowance is walk-only)
    counts.append(n)
print("GALLOP grounded paws/frame:", counts,
      "| suspension:", "YES" if 0 in counts else "NO")
gv = STRIDE_G["H"] / (STANCE_G * GCYC / FPS)   # authored stance sweep speed
print(f"GALLOP ref speed: {gv:.3f} m/s -> gallop_ref_speed = {gv*10:.2f} voxels/s")

# ---- clip 3: Graze = ground sniff (96f: down -> sweep sniffs -> up) -----------------
graze = new_action("Graze")
GLEN = 96


def sniff_pose(fr, frac, peck=0.0, yaw=0.0):
    key_rot("chest", fr, (C_D * SNIFF_CHEST * frac, 0, 0))
    key_rot("head", fr, (H_D * (SNIFF_HEAD * frac + peck), 0, H_Y * yaw))


GT = [(1, 0.35, 0, 0), (6, 0.35, 0, 0), (14, 1, 0, 0),
      (18, 1, 4, 0), (21, 1, 0, 0), (25, 1, 4, 0), (28, 1, 0, 0),
      (36, 1, 0, -10),                                  # sniff trail, right
      (40, 1, 4, -10), (43, 1, 0, -10), (47, 1, 4, -10), (50, 1, 0, -10),
      (58, 1, 0, 9),                                    # sniff trail, left
      (62, 1, 4, 9), (65, 1, 0, 9), (69, 1, 4, 9), (72, 1, 0, 9),
      (80, 1, 0, 0), (90, 0.35, 0, 0), (GLEN, 0.35, 0, 0)]
for fr, frac, peck, yaw in GT:
    sniff_pose(fr, frac, peck, yaw)
# tail: slow interested wag the whole time the nose is down
for f in range(1, GLEN + 2, 4):
    down = 1.0 if 14 <= f <= 80 else 0.4
    key_rot("tail", f, (T_U * 4.0, 0, T_Y * 9.0 * down * math.sin(2 * math.pi * f / 32.0)))
for fr, dz in ((1, 0.0), (14, SNIFF_DROP), (80, SNIFF_DROP), (GLEN, 0.0)):
    key_hips_world(fr, 0, -BODY_DROP - dz)
# paws stay planted while the chest pitches and the body drops
key_planted_legs([1, 6, 10, 14, 36, 58, 80, 86, 90, GLEN])
make_cyclic(graze)

# ---- clip 4: Alert (96f: ears PERK + head snap -> stare -> scan -> fast wag) --------
alert = new_action("Alert")
ALEN = 96
A_PERK = 10.0        # deg, ears snap forward-up
A_HEAD_UP = 6.0
A_YAW = 16.0


def alert_pose(fr, up, yaw, perk):
    key_rot("chest", fr, (-C_D * 1.5 * up, 0, 0))
    key_rot("head", fr, (-H_D * A_HEAD_UP * up, 0, H_Y * A_YAW * yaw))
    key_rot("earL", fr, (E_F * A_PERK * perk, 0, 0))
    key_rot("earR", fr, (E_F * A_PERK * perk, 0, 0))


AT = [(1, 0, 0, 0), (4, 0, 0, 0), (7, 1, 0.9, 1),   # SNAP up-left, ears perk
      (34, 1, 0.9, 1),                              # frozen stare
      (44, 1, -0.9, 1), (68, 1, -0.9, 1),           # sweep right, hold
      (78, 1, 0, 1), (88, 0.3, 0, 0.3), (ALEN, 0, 0, 0)]
for fr, up, yaw, perk in AT:
    alert_pose(fr, up, yaw, perk)
key_hips_world(1, 0, -BODY_DROP)
key_hips_world(4, 0, -BODY_DROP)
key_hips_world(7, 0.012 * K, -BODY_DROP - 0.003 * K)
for f in range(10, 80, 4):
    key_hips_world(f, 0.012 * K, -BODY_DROP - 0.003 * K
                   + 0.002 * K * math.sin(2 * math.pi * (f - 7) / 20))
key_hips_world(84, 0.012 * K, -BODY_DROP - 0.003 * K)
key_hips_world(ALEN, 0, -BODY_DROP)
# the give-away: excited fast wag while staring (3.4 Hz butt wag)
for f in range(1, ALEN + 2, 2):
    amp = 14.0 if 7 <= f <= 78 else 4.0
    key_rot("tail", f, (T_U * 8.0, 0, T_Y * amp * math.sin(2 * math.pi * f * 3.4 / FPS)))
# paws planted through the weight rock
key_planted_legs([1, 4, 7, 34, 44, 68, 78, 88, ALEN])
make_cyclic(alert)

# ---- clip 5: Idle (144f: breathing, head TILT, wag bursts, ear twitch) --------------
idle = new_action("Idle")
ILEN = 144
key_stand_legs(1)
for f in range(1, ILEN + 2, 6):                     # breathing, 2 s period
    ph = 2 * math.pi * (f - 1) / 48.0
    key_hips_world(f, 0, -BODY_DROP + 0.003 * K * math.sin(ph))
    key_rot("chest", f, (C_D * 0.6 * math.sin(ph + 0.5), 0, 0))
for fr, rl in ((1, 0.0), (48, 0.7), (104, -0.7), (ILEN + 1, 0.0)):   # weight sway
    key_rot("hips", fr, (0, rl, 0))
# the corgi head TILT (roll around the head axis), then a glance right
HT = [(1, 0, 0), (30, 0, 0), (38, 14, 0), (66, 14, 0), (74, -0, 0),
      (96, 0, -8), (112, 0, -8), (122, 0, 0), (ILEN + 1, 0, 0)]
for fr, tilt, yaw in HT:
    key_rot("head", fr, (0, tilt, H_Y * yaw))
# two wag bursts: a lazy one, then a happy one
for f in range(1, ILEN + 2, 2):
    if 16 <= f <= 34:
        amp, hz = 6.0, 1.6
    elif 100 <= f <= 132:
        amp, hz = 12.0, 2.8
    else:
        amp, hz = 1.5, 0.5
    key_rot("tail", f, (T_U * 4.0, 0, T_Y * amp * math.sin(2 * math.pi * f * hz / FPS)))
# one ear twitch (right ear flicks at f=80)
for fr, a in ((76, 0), (80, 9), (84, 0)):
    key_rot("earR", fr, (E_F * a, 0, 0))
key_rot("earL", 1, (0, 0, 0))
key_rot("earL", ILEN + 1, (0, 0, 0))
make_cyclic(idle)

# ---- extra clips: each module is exec'd HERE with the full build namespace ----------
CLIP_END = {"Walk": CYC, "Gallop": GCYC, "Graze": GLEN, "Alert": ALEN, "Idle": ILEN}
ALL_CLIPS = [walk, gallop, graze, alert, idle]
EXTRA_GUARDS = {}
if EXTRA_DIR:
    import glob as _glob, traceback as _tb
    for _path in sorted(_glob.glob(os.path.join(EXTRA_DIR, "*.py"))):
        _src = open(_path).read(); _ns = globals()
        try:
            exec(compile(_src, _path, "exec"), _ns)
            _act = _ns["EXTRA_ACTION"]; _len = int(_ns["EXTRA_LENGTH"])
            CLIP_END[_act.name] = _len; ALL_CLIPS.append(_act)
            EXTRA_GUARDS[_act.name] = _ns.get("EXTRA_GUARD", "n/a")
            print(f"EXTRA CLIP {_act.name}: {_len} frames | guard: {EXTRA_GUARDS[_act.name]}")
        except Exception as _e:
            print(f"EXTRA CLIP FAILED {os.path.basename(_path)}: {_e!r}"); _tb.print_exc()
print("CLIPS:", [a.name for a in ALL_CLIPS])


def activate(act):
    arm.animation_data.action = act
    if act.slots:
        arm.animation_data.action_slot = act.slots[0]
    scene.frame_start, scene.frame_end = 1, CLIP_END[act.name]


try:
    ad = arm.animation_data
    for act in ALL_CLIPS:
        tr = ad.nla_tracks.new()
        tr.name = act.name
        strip = tr.strips.new(act.name, 1, act)
        if hasattr(strip, "action_slot") and act.slots:
            strip.action_slot = act.slots[0]
        tr.mute = True
except Exception as e:
    print("NLA stash skipped:", e)

activate(walk)

os.makedirs(OUT_DIR, exist_ok=True)
blend_path = os.path.join(OUT_DIR, f"{NAME}_rigged.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print("SAVED", blend_path)

# ---- preview renders -----------------------------------------------------------------
def make_cam(name, loc, target=(0, 0.0, 0.35), ortho=None):
    cam_d = bpy.data.cameras.new(name)
    if ortho:
        cam_d.type = "ORTHO"
        cam_d.ortho_scale = ortho
    cam = bpy.data.objects.new(name, cam_d)
    bpy.context.collection.objects.link(cam)
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return cam


if DO_RENDER or DO_VIDEO:
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "VERTEX"
    scene.display.shading.show_object_outline = True
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.film_transparent = False
    gm = bpy.data.meshes.new("PreviewGround")
    gm.from_pydata([(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)], [], [(0, 1, 2, 3)])
    gm.update()
    go = bpy.data.objects.new("PreviewGround", gm)
    bpy.context.collection.objects.link(go)

def make_cam_scaled(name, loc, target=(0, 0.0, 0.35), ortho=None):
    loc = tuple(v * KC for v in loc); target = tuple(v * KC for v in target)
    return make_cam(name, loc, target=target, ortho=(ortho * KC if ortho else None))

cam_side = make_cam_scaled("CamSide", (2.2, 0.05, 0.60), target=(0, 0.05, 0.33), ortho=1.6)
cam_3q = make_cam_scaled("Cam3Q", (1.40, -1.40, 0.90), target=(0, 0.02, 0.33))
cam_front = make_cam_scaled("CamFront", (0.08, -1.9, 0.62), target=(0, 0.0, 0.36))

SHOTS = {
    "Walk": [(cam_side, "side", (1, 3, 5, 7, 9, 11, 13, 15)),
             (cam_3q, "3q", (1, 5, 9, 13))],
    "Gallop": [(cam_side, "side", (1, 3, 5, 7, 9)),
               (cam_3q, "3q", (2, 6, 9))],
    "Graze": [(cam_side, "side", (1, 14, 25, 43, 65, 90)),
              (cam_3q, "3q", (14, 43, 65))],
    "Alert": [(cam_3q, "3q", (1, 7, 30, 50, 78, 90)),
              (cam_front, "front", (7, 50))],
    "Idle": [(cam_3q, "3q", (1, 50, 80, 116)),
             (cam_front, "front", (50, 116))],
}

if DO_RENDER:
    scene.render.image_settings.file_format = "PNG"
    for act in ALL_CLIPS:
        if act.name not in SHOTS: continue
        activate(act)
        for cam, tag, frs in SHOTS[act.name]:
            scene.camera = cam
            for f in frs:
                scene.frame_set(f)
                scene.render.filepath = os.path.join(
                    OUT_DIR, f"{act.name.lower()}_{tag}_{f:03d}.png")
                bpy.ops.render.render(write_still=True)
    print("RENDERED stills")

if DO_VIDEO:
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    _LOOPS = {"Walk": 6, "Gallop": 10}
    _only = set(ONLY_CLIPS.split(",")) if ONLY_CLIPS else None
    for act in ALL_CLIPS:
        if _only and act.name not in _only: continue
        loops, cam = _LOOPS.get(act.name, 1), cam_3q
        activate(act)
        scene.frame_end = CLIP_END[act.name] * loops
        scene.camera = cam
        scene.render.filepath = os.path.join(
            OUT_DIR, f"{NAME}_{act.name.lower()}_preview.mp4")
        bpy.ops.render.render(animation=True)
        print(f"VIDEO {act.name} done")
    activate(walk)

if DO_EXPORT:
    activate(walk)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    arm.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(OUT_DIR, f"{NAME}_animated.glb"),
        export_format="GLB", use_selection=True,
        export_animations=True, export_animation_mode="ACTIONS")
    print("EXPORTED glb")

print("DONE")
