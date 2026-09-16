# ---- extra clip: Sleep (96f, LOOPABLE: already lying down, slow breathing) --------
# Lying pose is derived from the mesh itself (auto-rigged voxel legs are boxes
# of very different proportions): body drops so the main belly slab hovers
# ~0.05*K above the ground, legs fold in one of three modes chosen per leg pair:
#   S "sphinx": lower leg lies FLAT on the ground pointing forward, knee behind
#     (needs a lower-leg box that is longer than it is thick, else the flipped
#      slab stands up like a wall);
#   T "tuck":   lower leg stays vertical (paw flat on the ground) and the upper
#     swings forward/backward so the paw ends up ahead of / under the body;
#   K "fold":   lower leg folds 180 deg back against the thigh (paw at the hip),
#     no ground contact at all, the whole leg disappears into the body silhouette.
#     Small rigs whose .upper groups own torso voxels (Cat: the whole lower
#     torso slab is 'upper leg') use K with a near-zero thigh swing so the body
#     does not shear; other rigs only get K as a second pass when the S/T pose is
#     poor (belly stays high, or a T pair leaves a tall shin standing behind).
# Every candidate pose is checked analytically against the rest voxels (rigid
# weights), then the whole clip is verified on the evaluated mesh (guard).
EXTRA_ACTION = new_action("Sleep")
SLEN = 96
EXTRA_LENGTH = SLEN
BREATH_P = 48                       # 2 s breathing period
BR_DZ = 0.009 * K                   # body rise per breath (~0.4 voxel; only UP from the rest pose)
BR_CHEST = 2.2                      # deg, chest pitch swell
CHEST0_TRY = (5.0, 2.5, 0.0)        # deg, constant nose-down chest pitch (head sinks); the
                                    # pitch sinks the front leg roots, so it is traded off
                                    # against how low the belly can go
HEAD_CAP = 35.0                     # deg, max head pitch down
HEAD_AXIS_MAX = 85.0                # deg, head axis may hang at most this far below level
                                    # (Sheep's rest axis is already 49 deg down; 60 capped it at 11)
SHEAR_RATIO = 1.6                   # .upper y-extent / .lower y-extent above this = thigh owns torso voxels
THU_CAP = math.radians(30.0)        # max thigh swing for such torso-owning thighs
K_THU = (0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0)   # deg, K-fold thigh swings tried (small first)
STUB_H = 1.5 * S                    # a T-pair shin taller than this, swung > 60 deg, is a 'standing stub'
HEAD_YAW = 8.0                      # deg, small lazy yaw
EAR_BACK = 25.0                     # deg, ears relaxed back
TAIL_CURL = 40.0                    # deg, tail yaw toward the body
TAIL_UP_TRY = (4.0, 12.0, 20.0, 30.0, 40.0, 50.0)   # deg, tail pitch up: first one that clears the ground
CLEAR = 0.012                       # m, analytic clearance above ground for flipped slabs
TOUCH = -0.004                      # m, a paw resting on the ground may sit this low analytically
_STEP = 0.01                        # m, belly raise step when a fold does not clear

# ---- rest geometry per bone (vertex groups are rigid, first-claim) -----------------
_me = obj.data
_gi = {vg.index: vg.name for vg in obj.vertex_groups}
_grp = {n: [] for n in BONE_ORDER}
for _v in _me.vertices:
    if _v.groups:
        _grp[_gi[_v.groups[0].group]].append(_v.index)
_co = [0.0] * (3 * len(_me.vertices))
_me.vertices.foreach_get("co", _co)
_REST = {n: [(_co[3 * i + 1], _co[3 * i + 2]) for i in ids] for n, ids in _grp.items()}   # (y, z)

# main belly slab: lowest S-level of hips+chest holding >= 35% of the most populated
# low level (udders / dangling bits below it are ignored for the drop, but guarded)
_body_ids = _grp["hips"] + _grp["chest"]
_lv = {}
for i in _body_ids:
    _lv[round(_co[3 * i + 2] / S)] = _lv.get(round(_co[3 * i + 2] / S), 0) + 1
_low_levels = sorted(k for k in _lv if k * S <= _BM)
_peak = max(_lv[k] for k in _low_levels)
BODY_BOTTOM = next(k * S for k in _low_levels if _lv[k] >= 0.35 * _peak)
BODY_MIN_REST = min(_co[3 * i + 2] for i in _body_ids)
print(f"SLEEP geo: body_bottom={BODY_BOTTOM:.3f} (abs min {BODY_MIN_REST:.3f}) levels="
      + " ".join(f"{k*S:.2f}:{_lv[k]}" for k in _low_levels[:6]))


def _rot(y, z, th):
    """Rotate a (y,z) offset the way the leg solver does: th > 0 tilts a straight-down
    bone (0,-1) FORWARD to (-sin th, -cos th) (same convention as solve_leg's theta)."""
    c, s = math.cos(th), math.sin(th)
    return y * c + z * s, -y * s + z * c


def _leg_min_z(leg, root_y, root_z, thu, thl):
    """Analytic lowest voxel corner of one leg (upper about root, lower about knee)."""
    ly = LEG_Y[leg[0]]
    ky, kz = root_y - L1 * math.sin(thu), root_z - L1 * math.cos(thu)
    zmin = 9.9
    for y, z in _REST[f"{leg}.upper"]:
        zmin = min(zmin, root_z + _rot(y - ly, z - HIP_Z, thu)[1])
    for y, z in _REST[f"{leg}.lower"]:
        zmin = min(zmin, kz + _rot(y - ly, z - KNEE_Z, thl)[1])
    return zmin


_EXT = {}          # per pair: (upper y-extent, lower y-extent, lower height, shear-prone)
for _p in ("F", "H"):
    _ls = [l for l in LEGS if l[0] == _p]
    _ue = max(max(y for y, z in _REST[f"{l}.upper"]) - min(y for y, z in _REST[f"{l}.upper"]) for l in _ls)
    _le = max(max(y for y, z in _REST[f"{l}.lower"]) - min(y for y, z in _REST[f"{l}.lower"]) for l in _ls)
    _lh = max(max(z for y, z in _REST[f"{l}.lower"]) - min(z for y, z in _REST[f"{l}.lower"]) for l in _ls)
    _EXT[_p] = (_ue, _le, _lh, _ue >= SHEAR_RATIO * _le)
print("SLEEP thighs: " + " ".join(f"{p}: upper_y={_EXT[p][0]:.2f} lower_y={_EXT[p][1]:.2f} lower_h={_EXT[p][2]:.2f}"
                                  f"{' SHEAR-PRONE' if _EXT[p][3] else ''}" for p in ("F", "H")))


def _fold(pair, h, allow_k):
    """Fold angles (thu, thl, mode, kz) for a leg pair whose roots sit at height h.
    Returns None when no fold keeps every leg voxel above the ground (>= TOUCH).
    Candidate order: S, T, then K (allow_k). Shear-prone pairs (thigh group owns
    torso voxels) try K FIRST and clamp every swing to THU_CAP."""
    legs = [l for l in LEGS if l[0] == pair]
    tail_ext = max(max(y for y, z in _REST[f"{l}.lower"]) - LEG_Y[pair] for l in legs)
    lower_h = _EXT[pair][2]
    shear = _EXT[pair][3]
    st, kk = [], []
    # S: lower flat forward, knee behind at kz (flipped slab's tail side goes down)
    kz = tail_ext + CLEAR
    if lower_h >= 1.25 * tail_ext and h - kz >= 0.15 * L1 and h - kz < L1:
        thu = -math.atan2(math.sqrt(L1 * L1 - (h - kz) ** 2), h - kz)
        st.append((thu, math.pi / 2, "S", kz))
    # T: lower vertical, upper swings; front prefers forward, hind prefers backward
    if L2 <= h <= L1 + L2:
        psi = math.acos(_clamp((h - L2) / L1, -1.0, 1.0))
        order = (1.0, -1.0) if pair == "F" else (-1.0, 1.0)
        for sgn in order:
            st.append((sgn * psi, 0.0, "T" + ("f" if sgn > 0 else "b"), 0.0))
    # K: shin folded back against the thigh (paw at the hip), thigh swung back (b) or fwd (f)
    if allow_k or shear:
        for a in K_THU:
            for sgn in (-1.0, 1.0):
                if a == 0.0 and sgn > 0:
                    continue
                thu = sgn * math.radians(a)
                kk.append((thu, thu + math.pi, "K" + ("f" if sgn > 0 else "b"), 0.0))
    cands = (kk + st) if shear else (st + kk)
    for thu, thl, mode, kz in cands:
        if shear and abs(thu) > THU_CAP + 1e-6:
            continue
        if min(_leg_min_z(l, LEG_Y[pair], h, thu, thl) for l in legs) >= TOUCH:
            return thu, thl, mode, kz
    return None


# ---- choose the body drop: lowest belly that both leg pairs can fold under ----------
_chest_lever = BONES["chest"][0][1] - LEG_Y["F"]        # front roots sink with the chest pitch


def _search(chest0, allow_k):
    # phase 1 keeps the author's floor (S/T poses need room for a knee); the fully folded
    # phase-2 pass may put the belly almost on the ground
    belly = max(0.02 * K, CLEAR + 0.01) if allow_k else min(0.05 * K, 0.4 * BODY_BOTTOM)
    for step in range(40):
        drop = BODY_BOTTOM - belly
        hF = HIP_Z - drop - _chest_lever * math.sin(math.radians(chest0))
        fF, fH = _fold("F", hF, allow_k), _fold("H", HIP_Z - drop, allow_k)
        if fF and fH and BODY_MIN_REST - drop >= CLEAR - 0.005:
            return belly, drop, {"F": fF, "H": fH}, step
        belly += _STEP
    return None


def _poor(res):
    """Phase-1 pose that does not read as lying: belly still high, or a T pair whose
    shin (taller than a voxel) stands vertical behind a near-horizontal thigh."""
    if res[0] > 0.05 * K + 0.02:
        return True
    for p, (thu, thl, mode, kz) in res[2].items():
        if mode[0] == "T" and abs(thu) > math.radians(60.0) and _EXT[p][2] >= STUB_H:
            return True
    return False


def _best_over_chest(allow_k):
    best = None
    for c0 in CHEST0_TRY:                    # keep the chest pitch unless it costs > 2 cm of belly
        r = _search(c0, allow_k)
        if r and (best is None or r[0] < best[0] - 0.02):
            best = r + (c0,)
    return best


_best = _best_over_chest(False)              # phase 1: S/T (K only for shear-prone pairs)
PHASE = 1
if _best is None or _poor(_best):            # phase 2: K allowed everywhere, taken only if it lowers the belly
    _alt = _best_over_chest(True)
    if _alt and (_best is None or _alt[0] <= _best[0] - 0.02):
        _best, PHASE = _alt, 2
if _best is None:
    raise RuntimeError("Sleep: no ground-safe fold found for this creature")
BELLY, DROP, FOLD, STEPS, CHEST0 = _best
print(f"SLEEP fold: phase={PHASE} belly={BELLY:.3f} drop={DROP:.3f} steps={STEPS} chest0={CHEST0} "
      f"F={FOLD['F'][2]} thu={math.degrees(FOLD['F'][0]):.0f} H={FOLD['H'][2]} thu={math.degrees(FOLD['H'][0]):.0f}")


def _leg_angles(leg, f):
    """World fold angles -> bone-local X rotations, from the evaluated parent (like key_planted_legs)."""
    par = pb["chest" if leg[0] == "F" else "hips"]
    M = par.matrix @ par.bone.matrix_local.inverted()
    root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
    v = M.to_3x3() @ Vector((0, 0, -1))
    delta = math.atan2(-v.y, -v.z)
    thu, thl, mode, kz = FOLD[leg[0]]
    if mode[0] == "K":                       # folded-in leg has no ground contact: rides with the body
        pass
    elif mode[0] == "T":                     # paw stays exactly on the ground as the body breathes
        psi = math.acos(_clamp((root.z - L2) / L1, -1.0, 1.0))
        thu = math.copysign(psi, thu)
    else:                                    # flat forearm stays on the ground (knee height fixed)
        dz = root.z - kz
        thu = -math.atan2(math.sqrt(max(0.0, L1 * L1 - dz * dz)), dz)
    return (math.degrees(LX_SIGN * (thu - delta)), math.degrees(LX_SIGN * (thl - thu)))


# ---- body: drop + slow breathing (body rises ~0.4 voxel, chest pitches UP a hair) ---
# Both only move AWAY from the ground relative to the exhale pose, so the exhale pose
# (frame 1) is the ground-clearance worst case.
def _breath(f):
    return 0.5 - 0.5 * math.cos(2 * math.pi * (f - 1) / BREATH_P)


KEYS = list(range(1, SLEN + 2, 4))
for f in KEYS:
    b = _breath(f)
    key_hips_world(f, 0.0, -DROP + BR_DZ * b)
    key_rot("hips", f, (0, 0, 0))
    key_rot("chest", f, (C_D * (CHEST0 - BR_CHEST * _breath(f + 3)), 0, 0))   # ribcage lifts on inhale

# ---- head: as far down as the ground allows (cap 35 deg, axis <= HEAD_AXIS_MAX below level) --
_hr, _ht = BONES["head"][0], BONES["head"][1]
_rest_down = math.degrees(math.atan2(_hr[2] - _ht[2], _hr[1] - _ht[1]))   # + = muzzle already hangs
_cap = min(HEAD_CAP, max(0.0, HEAD_AXIS_MAX - _rest_down))
scene.frame_set(1)
bpy.context.view_layer.update()
_head_ids = _grp["head"] + _grp["earL"] + _grp["earR"]


def _mesh_min_z(ids, dg=None):
    dg = dg or bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    buf = [0.0] * (3 * len(ev.data.vertices))
    ev.data.vertices.foreach_get("co", buf)
    m = ev.matrix_world
    return min(m[2][0] * buf[3 * i] + m[2][1] * buf[3 * i + 1] + m[2][2] * buf[3 * i + 2] + m[2][3] for i in ids)


HEAD_P = 0.0
for _p in [_cap - 5 * k for k in range(int(_cap // 5) + 1)] + [0.0]:
    pb["head"].rotation_euler = (math.radians(H_D * _p), 0, math.radians(H_Y * HEAD_YAW))
    pb["chest"].rotation_euler = (math.radians(C_D * CHEST0), 0, 0)
    key_hips_world(1, 0.0, -DROP)
    bpy.context.view_layer.update()
    if not _head_ids or _mesh_min_z(_head_ids) >= CLEAR:
        HEAD_P = _p
        break
for f in (1, SLEN + 1):
    key_rot("head", f, (H_D * HEAD_P, 0, H_Y * HEAD_YAW))
    key_rot("earL", f, (-E_F * EAR_BACK, 0, 0))
    key_rot("earR", f, (-E_F * EAR_BACK, 0, 0))
# tail curled toward the body (pitched up until its voxels clear the ground), one lazy sway per loop
TAIL_UP = TAIL_UP_TRY[-1]
for _t in TAIL_UP_TRY:
    pb["tail"].rotation_euler = (math.radians(T_U * _t), 0, math.radians(T_Y * TAIL_CURL))
    bpy.context.view_layer.update()
    if not _grp["tail"] or _mesh_min_z(_grp["tail"]) >= CLEAR:
        TAIL_UP = _t
        break
for f in range(1, SLEN + 2, 8):
    key_rot("tail", f, (T_U * TAIL_UP, 0, T_Y * (TAIL_CURL + 4.0 * math.sin(2 * math.pi * (f - 1) / SLEN))))

# ---- legs: folded, re-solved per key so paws stay put while the body breathes -------
for f in KEYS:
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for leg in LEGS:
        ux, lx = _leg_angles(leg, f)
        key_rot(f"{leg}.upper", f, (ux, 0, 0))
        key_rot(f"{leg}.lower", f, (lx, 0, 0))
make_cyclic(EXTRA_ACTION)

# ---- guard: every frame, evaluated mesh + paw tips ------------------------------------
_leg_ids = [i for l in LEGS for i in _grp[f"{l}.upper"] + _grp[f"{l}.lower"]]
_body_all = [i for n in ("hips", "chest", "head", "tail", "earL", "earR") for i in _grp[n]]
_dg = bpy.context.evaluated_depsgraph_get()
g_body, g_legs, g_tip, g_tipmax = 9.9, 9.9, 9.9, -9.9
for f in range(1, SLEN + 1):
    scene.frame_set(f)
    _dg.update()
    ae = arm.evaluated_get(_dg)
    for l in LEGS:
        tz = (ae.matrix_world @ ae.pose.bones[f"{l}.lower"].tail).z
        g_tip, g_tipmax = min(g_tip, tz), max(g_tipmax, tz)
    g_body = min(g_body, _mesh_min_z(_body_all, _dg))
    g_legs = min(g_legs, _mesh_min_z(_leg_ids, _dg))
scene.frame_set(1)
_dg.update()
ae = arm.evaluated_get(_dg)
_paws = " ".join(f"{l}:{(ae.matrix_world @ ae.pose.bones[f'{l}.lower'].tail).y:+.2f}" for l in LEGS)
# pose-quality signal: the trunk (hips+chest+thighs) must actually be near the ground at the exhale pose
_trunk_ids = _grp["hips"] + _grp["chest"] + [i for l in LEGS for i in _grp[f"{l}.upper"]]
g_trunk = _mesh_min_z(_trunk_ids, _dg)
_lie_lim = 0.05 * K + 0.02
_lying = BELLY <= _lie_lim or g_trunk <= _lie_lim
_ok = g_body >= -0.01 and g_legs >= -0.01 and g_tip >= -0.02 and _lying
_thu = " ".join(f"{p}={FOLD[p][2]}{math.degrees(FOLD[p][0]):+.0f}" for p in ("F", "H"))
EXTRA_GUARD = (f"{'OK' if _ok else 'FAIL'} sleep: body_min_z={g_body:.3f} leg_mesh_min_z={g_legs:.3f} "
               f"paw_tip_z=[{g_tip:.3f},{g_tipmax:.3f}] belly={BELLY:.3f} trunk_z={g_trunk:.3f} "
               f"(lying{'' if _lying else ' NOT'} <= {_lie_lim:.3f}) drop={DROP:.3f} steps={STEPS} phase={PHASE} "
               f"fold {_thu} chest0={CHEST0:.1f} head_down={HEAD_P:.0f} tail_up={TAIL_UP:.0f} paw_y {_paws}")
print("SLEEP GUARD:", EXTRA_GUARD)
