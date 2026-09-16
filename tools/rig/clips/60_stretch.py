# Stretch (96f one-shot, returns to rest): a two-part canine stretch.
#   Part A  play bow / downward dog: the front legs fold into an L (upper leg
#           swings forward to ST_PHI_F, shank stays vertical so the paw stays
#           flat on the ground and slides forward), the chest drops with them,
#           the rump stays high on straight hind columns, nose low and forward,
#           ears forward, tail up with a slow wag.  Hold ~22f.
#   Part B  rear stretch: rise, then the hind upper legs swing BACK to
#           ST_PSI_H (shank vertical, paw flat, sliding back), the rump sinks,
#           the body pitches nose-up, head up, ears back.  Hold ~16f.
# Every frame the body pitch + drop are solved by bisection on the evaluated
# leg roots so the folding legs' roots sit exactly where their L-pose needs
# them (paw tips stay on the ground, no knee pop, no paw-box tilt) while the
# planted legs stay rigid columns on their rest spots (key_planted_legs style).
EXTRA_ACTION = new_action("Stretch")
EXTRA_LENGTH = 96

# ---- timeline ----------------------------------------------------------------------
ST_A_IN, ST_A_HOLD, ST_A_OUT, ST_REST1 = 1, 16, 38, 48
ST_B_IN, ST_B_HOLD, ST_B_OUT = 60, 76, 88

# ---- pose targets (angles; every distance below derives from L1/L2 = leg bones) -------
ST_PHI_F = 78.0                    # deg, bow: front upper leg forward from vertical
ST_PSI_H = 42.0                    # deg, rear stretch: hind upper leg back from vertical
ST_CHEST_A, ST_CHEST_B = 0.35, 0.40  # share of the body pitch carried by the chest bone
ST_HEAD_TOTAL = 50.0               # deg, cap on the head bone's total nose-down in the bow
ST_HEAD_B = 18.0                   # deg, head up in the rear stretch
ST_EAR_A, ST_EAR_B = 10.0, -8.0    # ears forward in the bow, back in the stretch
ST_REST_H = HIP_Z - BODY_DROP      # leg root height at rest (columns bury BODY_DROP)


def st_prog(f, f0, f1):
    if f <= f0:
        return 0.0
    if f >= f1:
        return 1.0
    return smoothstep((f - f0) / (f1 - f0))


def st_pA(f):
    if f <= ST_A_HOLD:
        return st_prog(f, ST_A_IN, ST_A_HOLD)
    if f <= ST_A_OUT:
        return 1.0
    return 1.0 - st_prog(f, ST_A_OUT, ST_REST1)


def st_pB(f):
    if f < ST_REST1:
        return 0.0
    if f <= ST_B_IN:
        return st_prog(f, ST_REST1, ST_B_IN)
    if f <= ST_B_HOLD:
        return 1.0
    return 1.0 - st_prog(f, ST_B_HOLD, ST_B_OUT)


def st_root_h(p, ang):
    """Root height for an L-leg (upper tilted p*ang, shank vertical) whose paw sits
    on the ground; at p=0 this is the rest column (buried BODY_DROP like Idle)."""
    return L1 * math.cos(math.radians(p * ang)) + L2 - BODY_DROP * (1.0 - p)


# ---- mesh bookkeeping for the ground checks -----------------------------------------
def st_group_idx(names):
    gi = {vgroups[n].index for n in names}
    return [v.index for v in mesh.vertices if any(g.group in gi for g in v.groups)]


ST_PAW_IDX = st_group_idx([f"{leg}.lower" for leg in LEGS])
ST_HEAD_IDX = st_group_idx(["head", "earL", "earR"])
_paw = set(ST_PAW_IDX)
ST_BODY_IDX = [i for i in range(len(mesh.vertices)) if i not in _paw]


def st_eval(f):
    """Evaluate frame f -> (world z per mesh vertex, {leg: tip world}, head tip world)."""
    scene.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    oe = obj.evaluated_get(dg)
    me = oe.data
    n = len(me.vertices)
    co = [0.0] * (3 * n)
    me.vertices.foreach_get("co", co)
    r = oe.matrix_world[2]
    zs = [r[0] * co[3 * i] + r[1] * co[3 * i + 1] + r[2] * co[3 * i + 2] + r[3] for i in range(n)]
    ae = arm.evaluated_get(dg)
    tips = {leg: (ae.matrix_world @ ae.pose.bones[f"{leg}.lower"].tail).copy() for leg in LEGS}
    head = (ae.matrix_world @ ae.pose.bones["head"].tail).copy()
    return zs, tips, head


def st_root(leg):
    par = pb["chest" if leg[0] == "F" else "hips"]
    M = par.matrix @ par.bone.matrix_local.inverted()
    root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
    v = M.to_3x3() @ Vector((0, 0, -1))
    return root, math.atan2(-v.y, -v.z)


# ---- body ---------------------------------------------------------------------------
def st_key_body(f, pitch, chest_frac, dz, head, yaw, ear, tail_rx, tail_rz):
    """pitch > 0 = nose-down (whole body about the hips, share chest_frac on the chest)."""
    key_rot("hips", f, (HP_D * pitch * (1.0 - chest_frac), 0, 0))
    key_rot("chest", f, (C_D * pitch * chest_frac, 0, 0))
    key_rot("head", f, (H_D * head, 0, H_Y * yaw))
    key_rot("earL", f, (E_F * ear, 0, 0))
    key_rot("earR", f, (E_F * ear, 0, 0))
    key_rot("tail", f, (T_U * tail_rx, 0, T_Y * tail_rz))
    key_hips_world(f, 0.0, dz)


def st_root_heights(f, pitch, chest_frac):
    key_rot("hips", f, (HP_D * pitch * (1.0 - chest_frac), 0, 0))
    key_rot("chest", f, (C_D * pitch * chest_frac, 0, 0))
    key_hips_world(f, 0.0, 0.0)
    scene.frame_set(f)
    bpy.context.view_layer.update()
    return st_root("FL")[0].z, st_root("HL")[0].z


def st_solve_body(f, hF, hH, chest_frac, lo, hi):
    """Bisect the body pitch (keyed at f) so the front roots sit hF above the hind
    roots' target hH; returns (pitch, world dz) that puts both roots on target."""
    target = hF - hH
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        fz, hz = st_root_heights(f, mid, chest_frac)
        if (fz - hz) > target:   # too little nose-down
            lo = mid
        else:
            hi = mid
    pitch = 0.5 * (lo + hi)
    fz, hz = st_root_heights(f, pitch, chest_frac)
    return pitch, hH - hz


# ---- legs ---------------------------------------------------------------------------
def st_key_L_leg(f, leg, tilt, delta):
    """Upper leg tilted `tilt` deg from vertical in WORLD (+ = forward), shank vertical."""
    key_rot(f"{leg}.upper", f, (math.degrees(LX_SIGN * (math.radians(tilt) - delta)), 0, 0))
    key_rot(f"{leg}.lower", f, (-LX_SIGN * tilt, 0, 0))


def st_key_legs(f, pA, pB):
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for leg in LEGS:
        root, delta = st_root(leg)
        if leg[0] == "F" and pA > 0.0:
            st_key_L_leg(f, leg, pA * ST_PHI_F, delta)
        elif leg[0] == "H" and pB > 0.0:
            st_key_L_leg(f, leg, -pB * ST_PSI_H, delta)
        else:                                            # planted: vertical rest column
            st_key_L_leg(f, leg, 0.0, delta)             # (paw flat; its root height is held
                                                         #  at ST_REST_H by the body solve)



def st_fit_angle(f, ang, front, floor=0.0):
    """Largest L-leg angle (stepping down by 4 deg) whose hold pose keeps every
    non-paw vertex (upper-leg blocks, belly, head) >= floor (1 cm margin over the
    -0.01 ground rule) -- fat upper-leg blocks swung near-horizontal dip a corner."""
    global ST_PHI_F, ST_PSI_H
    while ang > 30.0:
        if front:
            ST_PHI_F = ang
            pitch, dz = st_solve_body(f, st_root_h(1.0, ang), ST_REST_H, ST_CHEST_A, 0.0, 60.0)
            st_key_body(f, pitch, ST_CHEST_A, dz, 0, 0, 0, 0, 0)
            st_key_legs(f, 1.0, 0.0)
        else:
            ST_PSI_H = ang
            pitch, dz = st_solve_body(f, ST_REST_H, st_root_h(1.0, ang), ST_CHEST_B, -40.0, 0.0)
            st_key_body(f, pitch, ST_CHEST_B, dz, 0, 0, 0, 0, 0)
            st_key_legs(f, 0.0, 1.0)
        zs, _, _ = st_eval(f)
        if min(zs[i] for i in ST_BODY_IDX) >= floor:
            break
        ang -= 4.0
    return ang


ST_PHI_F = st_fit_angle(ST_A_HOLD, ST_PHI_F, True)
ST_PSI_H = st_fit_angle(ST_B_IN, ST_PSI_H, False)

# ---- head in the bow: as low as the caps allow ----------------------------------------
# The head bone's total nose-down (rest declination + body pitch + head pitch) stays
# <= ST_HEAD_TOTAL so a big head never folds into the chest, and the head+ear mesh
# stays >= 0.02 above the ground.
ST_PITCH_A, ST_DZ_A = st_solve_body(ST_A_HOLD, st_root_h(1.0, ST_PHI_F), ST_REST_H, ST_CHEST_A, 0.0, 60.0)
st_key_body(ST_A_HOLD, ST_PITCH_A, ST_CHEST_A, ST_DZ_A, 0, 0, 0, 0, 0)
_hv = Vector(BONES["head"][1]) - Vector(BONES["head"][0])
ST_HEAD_DECL = math.degrees(math.atan2(-_hv.z, abs(_hv.y)))      # >0 = rest head points down
ST_HEAD_A = _clamp(ST_HEAD_TOTAL - ST_HEAD_DECL - ST_PITCH_A, 0.0, 30.0)
for _ in range(30):
    key_rot("head", ST_A_HOLD, (H_D * ST_HEAD_A, 0, 0))
    zs, _, _ = st_eval(ST_A_HOLD)
    if min(zs[i] for i in ST_HEAD_IDX) >= 0.02 or ST_HEAD_A <= -15.0:
        break
    ST_HEAD_A -= 2.5
ST_PITCH_B, ST_DZ_B = st_solve_body(ST_B_IN, ST_REST_H, st_root_h(1.0, ST_PSI_H), ST_CHEST_B, -40.0, 0.0)


_prev = None
for f in range(1, EXTRA_LENGTH + 1):
    pA, pB = st_pA(f), st_pB(f)
    if (pA, pB) != _prev:                                # holds reuse the solved body
        if pA > 0.0:
            cf = ST_CHEST_A
            pitch, dz = st_solve_body(f, st_root_h(pA, ST_PHI_F), ST_REST_H, cf, 0.0, 60.0)
        elif pB > 0.0:
            cf = ST_CHEST_B
            pitch, dz = st_solve_body(f, ST_REST_H, st_root_h(pB, ST_PSI_H), cf, -40.0, 0.0)
        else:
            cf, pitch, dz = ST_CHEST_A, 0.0, -BODY_DROP
        _prev = (pA, pB)
    head = pA * ST_HEAD_A - pB * ST_HEAD_B
    yaw = 7.0 * math.sin(2 * math.pi * (f - ST_A_HOLD) / (ST_A_OUT - ST_A_HOLD)) if ST_A_HOLD <= f <= ST_A_OUT else 0.0
    ear = pA * ST_EAR_A + pB * ST_EAR_B
    tail_rx = 4.0 + 12.0 * pA + 4.0 * pB
    tail_rz = 10.0 * pA * math.sin(2 * math.pi * f * 2.2 / FPS)
    st_key_body(f, pitch, cf, dz, head, yaw, ear, tail_rx, tail_rz)
    st_key_legs(f, pA, pB)

# ---- guard: tips in [-0.02, 0.06] every frame, body mesh >= -0.01, last == first -----------
_tmin, _tmax, _bmin, _pmin, _bf = 9.9, -9.9, 9.9, 9.9, 0
_first, _loop = None, 9.9
for f in range(1, EXTRA_LENGTH + 1):
    zs, tips, hd = st_eval(f)
    for leg in LEGS:
        _tmin = min(_tmin, tips[leg].z)
        _tmax = max(_tmax, tips[leg].z)
    bz = min(zs[i] for i in ST_BODY_IDX)
    if bz < _bmin:
        _bmin, _bf = bz, f
    _pmin = min(_pmin, min(zs[i] for i in ST_PAW_IDX))
    snap = [tips[l] for l in LEGS] + [hd]
    if f == 1:
        _first = snap
    elif f == EXTRA_LENGTH:
        _loop = max((a - b).length for a, b in zip(_first, snap))
_ok = (_tmin >= -0.02 and _tmax <= 0.06 and _bmin >= -0.01 and _pmin >= -0.02 and _loop < 1e-3)
EXTRA_GUARD = (f"{'OK' if _ok else 'FAIL'} tips[{_tmin:+.3f},{_tmax:+.3f}] body_min={_bmin:+.3f}@f{_bf} "
               f"paw_min={_pmin:+.3f} loop_d={_loop:.4f} | bow pitch={ST_PITCH_A:.1f} dz={ST_DZ_A:+.3f} "
               f"head={ST_HEAD_A:.1f}(decl {ST_HEAD_DECL:.0f}) frontL={ST_PHI_F:.0f} | rear pitch={ST_PITCH_B:.1f} "
               f"dz={ST_DZ_B:+.3f} hindL={ST_PSI_H:.0f}")
print("STRETCH GUARD:", EXTRA_GUARD)
make_cyclic(EXTRA_ACTION)
