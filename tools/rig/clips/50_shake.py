# Shake: wet-dog full-body shake, 48f one-shot that returns to rest (frame 49 == frame 1).
# A ~6 Hz roll oscillation travels along the body: hips roll, chest counter-rolls
# with a phase lag, head counter-rolls (+ a yaw whip) with a further lag; ears
# flop and the tail whips at the same frequency, everything decaying to rest.
# All four paws stay planted: the body is keyed first, then key_planted_legs().
#
# Geometry notes (why the amplitudes are creature-adaptive):
#  * Leg bones only rotate about local X, so a body roll tilts the leg COLUMNS in
#    the frontal plane: the L/R paw heights split by 2*|LEG_X|*sin(roll) and the
#    paw boxes tilt (corners dip w_paw*sin(roll) below the tip). Columns cannot
#    stretch, so the body is LIFTED per frame just enough to keep the low paw
#    corners above ground, and the hips roll is capped so the high side hovers
#    <= 0.06 (guard budget). Wide-legged creatures (Cow, Hippo) get less roll;
#    the head takes over the lost amplitude (it moves no feet).
#  * The hips roll is pivoted at GROUND level between the hind paws (translation
#    compensation): the whole hips+leg-column assembly rotates about the ground
#    line, so the paw TIPS stay put (lateral move LEG_X*(1-cos roll) ~ 2 mm) while
#    the body sways HIP_Z*sin(roll) over the planted feet. (Pivoting at leg-root
#    height instead swung the columns like pendulums: the tips skated
#    HIP_Z*sin(roll) sideways at 6 Hz, 2 voxels on Wolf.)
#  * The chest is a CONNECTED bone (no translation), so its roll pivots at the
#    spine and skates the front paw TIPS by ~(body_mid_z)*sin(a): its counter-roll
#    is capped so that skate stays <= 0.1 voxel (i.e. ~0 on tall bodies); the head
#    takes over the lost counter-roll (it moves no feet).
#  * The rest frame (1 and 49) matches Idle frame 1: straight columns, body at
#    -BODY_DROP, tail at the Idle carry angle (T_U*4).
EXTRA_ACTION = new_action("Shake")
EXTRA_LENGTH = 48
_SK_LEN = EXTRA_LENGTH
_SK_HZ = 6.0                 # shake frequency (4 frames / cycle at 24 fps)
_SK_ROLL_H = 12.0            # deg, nominal hips roll (capped by the paw guard below)
_SK_ROLL_C = 9.0             # deg, nominal chest counter-roll (capped by root slide)
_SK_ROLL_HD = 18.0           # deg, head counter-roll (gets the roll the hips lose)
_SK_YAW_HD = 10.0            # deg, head yaw whip with the head roll
_SK_PITCH_HD = 5.0           # deg, head dips a little while shaking
_SK_LAG = math.radians(40)   # phase lag per body segment (hips -> chest -> head)
_SK_EAR = 30.0               # deg, ear flop
_SK_TAIL = 30.0              # deg, tail yaw whip
_SK_TAIL_UP = 6.0
_SK_BOUNCE = 0.004 * K       # m, minimum body bounce at the roll extremes
_SK_TIP_LO, _SK_TIP_HI = -0.018, 0.058   # tip budget with margin inside [-0.02, 0.06]
_SK_FRAMES = list(range(1, _SK_LEN + 2))
_SK_W = 2 * math.pi * _SK_HZ / FPS


def _sk_env(f):
    """0 at f<=2 (rest), full by f=6, decays to 0 by f=44, rest afterwards."""
    return smoothstep((f - 2) / 4.0) * (1.0 - smoothstep((f - 12) / 32.0))


def _sk_osc(f, lag):
    return math.cos(_SK_W * (f - 1) - lag)


# ---- hips roll pivoted at GROUND level between the hind paws -----------------------
_SK_ML_H = pb["hips"].bone.matrix_local.copy()
_SK_W2L_H = _SK_ML_H.to_3x3().inverted()
_SK_PIVOT = Vector((0.5 * (LEG_X["HL"] + LEG_X["HR"]), LEG_Y["H"], 0.0))   # armature space
_SK_QL = _SK_ML_H.inverted() @ _SK_PIVOT                                       # in hips rest-local space


def _sk_key_hips(f, roll_deg, dz):
    b = pb["hips"]
    b.rotation_euler = (0.0, math.radians(roll_deg), 0.0)
    R = b.rotation_euler.to_matrix()
    loc = (_SK_QL - R @ _SK_QL) + _SK_W2L_H @ Vector((0.0, 0.0, dz))
    b.keyframe_insert("rotation_euler", frame=f)
    key_loc("hips", f, tuple(loc))


# chest counter-roll cap: front paw TIP skate <= 0.1 voxel. The chest rolls about its
# own (spine) axis, so a paw tip on the ground is a lever of the axis height.
_SK_CHEST_ARM = max(0.02, max(pb["chest"].bone.head_local.z, pb["chest"].bone.tail_local.z))
_SK_ROLL_C_EFF = min(_SK_ROLL_C, math.degrees(math.asin(min(1.0, 0.1 * S / _SK_CHEST_ARM))))
_SK_TAIL_REST = 4.0          # deg, Idle's tail carry angle (rest frame must match Idle f1)
_SK_DRIFT_MAX = 0.3 * S      # m, paw tip horizontal skate budget (planted claim is measured)


def _sk_key_body(roll_h, lifts):
    lost = max(0.0, _SK_ROLL_H - roll_h)          # roll the wide-legged hips could not take
    lost_c = max(0.0, _SK_ROLL_C - _SK_ROLL_C_EFF)  # counter-roll the connected chest could not take
    roll_hd = _SK_ROLL_HD + 0.5 * lost + 0.5 * lost_c
    yaw_hd = _SK_YAW_HD + 0.5 * lost
    for f in _SK_FRAMES:
        e = _sk_env(f)
        _sk_key_hips(f, roll_h * e * _sk_osc(f, 0.0), -BODY_DROP + lifts[f])
        key_rot("chest", f, (0.0, -_SK_ROLL_C_EFF * e * _sk_osc(f, _SK_LAG), 0.0))
        key_rot("head", f, (H_D * _SK_PITCH_HD * e,
                            -roll_hd * e * _sk_osc(f, 2 * _SK_LAG),
                            H_Y * yaw_hd * e * _sk_osc(f, 2 * _SK_LAG)))
        ear = E_F * _SK_EAR * e * _sk_osc(f, 2 * _SK_LAG + math.pi / 2)
        key_rot("earL", f, (ear, 0.0, 0.0))
        key_rot("earR", f, (ear, 0.0, 0.0))
        key_rot("tail", f, (T_U * (_SK_TAIL_REST + (_SK_TAIL_UP - _SK_TAIL_REST) * e), 0.0,
                            T_Y * _SK_TAIL * e * _sk_osc(f, 2 * _SK_LAG + math.pi / 2)))
    key_planted_legs(_SK_FRAMES)
    return roll_hd


def _sk_measure(frames, subs=(0.0,)):
    """per (frame+subframe): (tip min, tip max, mesh min z) from the evaluated rig.
    The evaluated object's bound_box is the deformed mesh's AABB (verified equal
    to a full vertex scan), so the mesh floor check is cheap enough to sample densely."""
    out = {}
    dg = bpy.context.evaluated_depsgraph_get()
    for f in frames:
        for sub in subs:
            if sub > 0 and f == frames[-1]:
                continue
            scene.frame_set(f, subframe=sub)
            dg.update()
            ae = arm.evaluated_get(dg)
            zs = [(ae.matrix_world @ ae.pose.bones[f"{l}.lower"].tail).z for l in LEGS]
            oe = obj.evaluated_get(dg)
            mz = min((oe.matrix_world @ Vector(c)).z for c in oe.bound_box)
            out[f + sub] = (min(zs), max(zs), mz)
    return out


# rest reference (Idle stance: body at -BODY_DROP, straight columns)
_sk_lift0 = {f: 0.0 for f in _SK_FRAMES}
_sk_key_body(0.0, _sk_lift0)
_SK_REST = _sk_measure([1])[1.0]
_SK_MESH_FLOOR = min(-0.01, _SK_REST[2] - 0.001)
_SK_SUBS = (0.0, 0.25, 0.5, 0.75)


def _sk_lifts_for(roll):
    """key the shake at this hips roll with the bounce only, measure, and return
    (lifts per key, worst high-side hover after lifting)."""
    base = {f: _SK_BOUNCE * _sk_env(f) * abs(_sk_osc(f, 0.0)) for f in _SK_FRAMES}
    _sk_key_body(roll, base)
    m = _sk_measure(_SK_FRAMES, subs=_SK_SUBS)
    # lift needed per sample (aim 0.8 mm inside the floors); a sub-frame sample
    # raises BOTH neighbouring keys, and the lift is held over +-1 key so the
    # interpolated lift never lags the interpolated dip
    need = {f: 0.0 for f in _SK_FRAMES}
    for t, (tmin, tmax, mz) in m.items():
        n = max(0.0, _SK_TIP_LO + 0.0008 - tmin, _SK_MESH_FLOOR + 0.0008 - mz)
        for f in (math.floor(t), math.ceil(t)):
            need[f] = max(need[f], n)
    lifts, worst_hi = {}, -9.9
    for f in _SK_FRAMES:
        nb = max(need.get(f - 1, 0.0), need[f], need.get(f + 1, 0.0))
        lifts[f] = base[f] + nb
        worst_hi = max(worst_hi, m[float(f)][1] + nb)
    # first/last key are rest by construction (env == 0 there): never lift them
    lifts[_SK_FRAMES[0]] = 0.0
    lifts[_SK_FRAMES[-1]] = 0.0
    return lifts, worst_hi


# hips roll amplitude: nominal 12 deg, capped so the high-side paw hover (after the
# lift that keeps the low side above ground) uses the tip budget; hover is ~linear
# in sin(roll) so a ratio update converges in a few passes (both directions).
_sk_lx = max(abs(LEG_X[l] - _SK_PIVOT.x) for l in LEGS)
_sk_box = LAYOUT["legs"]["HL"]["box"]
_sk_wp = 0.5 * (_sk_box[2] - _sk_box[0] + 1) * S
_sk_roll = min(_SK_ROLL_H, math.degrees(math.asin(min(1.0, (_SK_TIP_HI - 0.011) / (2 * _sk_lx + _sk_wp)))))
_SK_TARGET = _SK_TIP_HI - 0.003
_sk_lifts = None
for _it in range(8):
    _sk_lifts, worst_hi = _sk_lifts_for(_sk_roll)
    print(f"SHAKE iter {_it}: roll {_sk_roll:.2f} deg -> high paw hover {worst_hi:+.4f}, max lift {max(_sk_lifts.values()):.4f}")
    if worst_hi <= _SK_TIP_HI and (worst_hi >= _SK_TARGET - 0.004 or _sk_roll >= _SK_ROLL_H - 1e-6):
        break
    ratio = (_SK_TARGET + 0.011) / (worst_hi + 0.011)
    _sk_roll = min(_SK_ROLL_H, math.degrees(math.asin(min(1.0, math.sin(math.radians(_sk_roll)) * ratio))))
else:
    while worst_hi > _SK_TIP_HI:         # never leave a violating amplitude behind
        _sk_roll *= 0.9
        _sk_lifts, worst_hi = _sk_lifts_for(_sk_roll)
_SK_ROLL_HD_EFF = _sk_key_body(_sk_roll, _sk_lifts)
_SK_ROLL_H_EFF = _sk_roll
print(f"SHAKE amplitudes: hips roll {_SK_ROLL_H_EFF:.2f} deg, chest counter-roll {_SK_ROLL_C_EFF:.2f} deg, "
      f"head roll {_SK_ROLL_HD_EFF:.1f} deg, head yaw {_SK_YAW_HD + 0.5 * max(0.0, _SK_ROLL_H - _SK_ROLL_H_EFF):.1f} deg, max lift {max(_sk_lifts.values()):.4f} (bounce floor {_SK_BOUNCE:.4f})")
make_cyclic(EXTRA_ACTION)

# ---- guard: tips in [-0.02, 0.06] (integer + quarter frames), tips do not skate
# horizontally (<= 0.3 voxel from their rest spot), mesh above ground, last == first
_dg = bpy.context.evaluated_depsgraph_get()
_tmin, _tmax, _mmin, _drift = 9.9, -9.9, 9.9, 0.0
_poses = {}
_rest_tips = {}
for _f in _SK_FRAMES:
    for _sub in _SK_SUBS:
        if _f == _SK_FRAMES[-1] and _sub > 0:
            continue
        scene.frame_set(_f, subframe=_sub)
        _dg.update()
        _ae = arm.evaluated_get(_dg)
        for _leg in LEGS:
            _tip = _ae.matrix_world @ _ae.pose.bones[f"{_leg}.lower"].tail
            _tmin = min(_tmin, _tip.z); _tmax = max(_tmax, _tip.z)
            _rt = _rest_tips.setdefault(_leg, _tip.copy())       # frame 1 is visited first
            _drift = max(_drift, math.hypot(_tip.x - _rt.x, _tip.y - _rt.y))
        _oe = obj.evaluated_get(_dg); _M = _oe.matrix_world
        _mmin = min(_mmin, min((_M @ Vector(_c)).z for _c in _oe.bound_box))
        if _sub == 0.0 and _f in (1, _SK_FRAMES[-1]):
            _poses[_f] = [_ae.pose.bones[b.name].matrix.copy() for b in arm.pose.bones]
_first_last = max(abs(a[i][j] - b[i][j]) for a, b in zip(_poses[1], _poses[_SK_FRAMES[-1]])
                  for i in range(4) for j in range(4))
_ok = (-0.02 <= _tmin and _tmax <= 0.06 and _drift <= _SK_DRIFT_MAX
       and _mmin >= _SK_MESH_FLOOR - 1e-4 and _first_last < 1e-4)
EXTRA_GUARD = (f"{'OK' if _ok else 'FAIL'} roll hips={_SK_ROLL_H_EFF:.1f} chest={_SK_ROLL_C_EFF:.1f} "
               f"head={_SK_ROLL_HD_EFF:.1f}deg | tips z [{_tmin:+.3f},{_tmax:+.3f}] "
               f"tipSkate={_drift:.4f}(<={_SK_DRIFT_MAX:.3f}) "
               f"meshMinZ={_mmin:+.4f} (rest {_SK_REST[2]:+.4f}) firstLastDiff={_first_last:.1e} "
               f"maxLift={max(_sk_lifts.values()):.3f}")
print("SHAKE GUARD:", EXTRA_GUARD)
scene.frame_set(1)
