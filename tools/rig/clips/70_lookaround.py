# LookAround: idle variant, 120f loop. Head yaw sweeps left (hold) -> centre ->
# right (hold, with a head tilt), ear perks at each turn, one weight shift
# (hips roll + tiny tailward dy) and slow breathing. Legs stay planted.
EXTRA_ACTION = new_action("LookAround")
EXTRA_LENGTH = 120
_LA_LEN = EXTRA_LENGTH
_LA_YAW = 30.0          # deg, look left/right
_LA_TILT = 10.0         # deg, head roll during the right hold
_LA_PERK = 12.0         # deg, ear pitch forward at each turn
_LA_ROLL = 2.0          # deg, hips roll for the weight shift
_LA_DY = 0.006 * K      # m, tailward lean with the weight shift (scales with K)
_LA_BREATH = 0.002 * K  # m, breathing dz half-amplitude (up-only, peak 2x)
_LA_BREATH_P = 60.0     # frames per breath (2 breaths per loop)

key_stand_legs(1)

# head: yaw (+ = look LEFT, +X), tilt (head cock) during the right-side hold.
# The head bone is pitched in rest (Sheep -49 deg nose-down, Cat +40 up, ...),
# so keying the yaw on bone-local Z would turn it into yaw+roll (a 30 deg turn
# became ~22 deg of roll on Sheep). Instead rotate about WORLD up (yaw) and the
# WORLD forward axis (tilt), both expressed in head-local (rest) space, and key
# the resulting XYZ euler (continuity-matched to the previous key).
_LA_HT = [(1, 0, 0), (10, 0, 0),
          (20, _LA_YAW, 0), (40, _LA_YAW, 0),           # look LEFT, hold 20f
          (52, 0, 0), (60, 0, 0),                       # back to centre, pause
          (70, -_LA_YAW, 0), (78, -_LA_YAW, _LA_TILT),  # look RIGHT, then tilt
          (88, -_LA_YAW, _LA_TILT),                     # hold (tilted)
          (102, 0, 0), (_LA_LEN + 1, 0, 0)]
_LA_HM = (arm.matrix_world.to_3x3() @ pb["head"].bone.matrix_local.to_3x3()).inverted()
_LA_HZ = (_LA_HM @ Vector((0, 0, 1))).normalized()     # world up in head-local (+angle = look LEFT, +X)
_LA_HF = (_LA_HM @ Vector((0, -1, 0))).normalized()    # world forward (-Y) in head-local, for the tilt
_LA_Mat = type(pb["head"].bone.matrix_local.to_3x3())  # mathutils.Matrix without a new import
_LA_prev = None
for _fr, _yaw, _tilt in _LA_HT:
    _R = (_LA_Mat.Rotation(math.radians(_yaw), 3, _LA_HZ)
          @ _LA_Mat.Rotation(math.radians(_tilt), 3, _LA_HF))
    _e = _R.to_euler("XYZ", _LA_prev) if _LA_prev is not None else _R.to_euler("XYZ")
    _LA_prev = _e
    key_rot("head", _fr, tuple(math.degrees(a) for a in _e))

# ears perk forward at each turn, relax during the hold
for _fr, _a in ((1, 0), (14, 0), (20, 1), (32, 1), (40, 0),
                (64, 0), (70, 1), (82, 1), (90, 0), (_LA_LEN + 1, 0)):
    key_rot("earL", _fr, (E_F * _LA_PERK * _a, 0, 0))
    key_rot("earR", _fr, (E_F * _LA_PERK * _a, 0, 0))


def _la_shift(f):
    """weight-shift envelope 0..1: on 40->52, hold, off 90->104"""
    if f <= 40 or f >= 104:
        return 0.0
    if f < 52:
        return smoothstep((f - 40) / 12.0)
    if f <= 90:
        return 1.0
    return 1.0 - smoothstep((f - 90) / 14.0)


# body: breathing dz (up-only so the paws never sink below the rest depth),
# chest breath, weight shift roll + tiny dy + a lift that keeps the LOW side's
# paw corners at rest depth (measured on the evaluated mesh), every 4 frames
_LA_BODY_FRAMES = list(range(1, _LA_LEN + 2, 4))


def _la_key_body(lift, roll):
    for _f in _LA_BODY_FRAMES:
        _ph = 2 * math.pi * (_f - 1) / _LA_BREATH_P
        _w = _la_shift(_f)
        _breath = _LA_BREATH * (1.0 - math.cos(_ph))          # 0 .. 2*amp, up only
        key_hips_world(_f, _LA_DY * _w, -BODY_DROP + _breath + lift * _w)
        key_rot("hips", _f, (0, roll * _w, 0))
        key_rot("chest", _f, (C_D * 0.6 * math.sin(_ph + 0.5), 0, 0))
        # lazy tail sway (60f period, loops)
        key_rot("tail", _f, (T_U * 4.0, 0, T_Y * 3.0 * math.sin(2 * math.pi * (_f - 1) / 60.0)))
    # paws stay planted while the body breathes / rolls / leans
    key_planted_legs(_LA_BODY_FRAMES)


def _la_mesh_min(f):
    scene.frame_set(f)
    _dg = bpy.context.evaluated_depsgraph_get(); _dg.update()
    _oe = obj.evaluated_get(_dg); _M = _oe.matrix_world
    return min((_M @ v.co).z for v in _oe.data.vertices)


_la_key_body(0.0, _LA_ROLL)
_LA_M0 = _la_mesh_min(1)                     # rest depth (paw plane at -BODY_DROP)
_LA_MROLL = _la_mesh_min(61)                 # w=1, breath=0 -> pure roll dip
# Column legs cannot compress: a rigid roll drops the low side's paw corners by
# hw*sin(roll) and (after lifting the body to compensate) hovers the high side
# by 2*hw*sin(roll) - BODY_DROP. Cap the roll so that hover stays <= 0.25 voxel;
# wide bodies (Cow, Hippo) get a smaller roll than the nominal 2 deg.
_LA_HW = max(1e-3, (_LA_M0 - _LA_MROLL) / math.sin(math.radians(_LA_ROLL)))
_LA_ROLL_EFF = min(_LA_ROLL, math.degrees(math.asin(min(1.0, (0.25 * S + BODY_DROP) / (2 * _LA_HW)))))
_LA_LIFT = _LA_HW * math.sin(math.radians(_LA_ROLL_EFF)) * 1.05
_la_key_body(_LA_LIFT, _LA_ROLL_EFF)
# residual pass: the tailward lean also tilts the paw columns (their box corners
# dip); measure what is left at full shift and lift the body by that too
_LA_RESID = max(0.0, _LA_M0 - _la_mesh_min(61))
_LA_LIFT += _LA_RESID * 1.05
_la_key_body(_LA_LIFT, _LA_ROLL_EFF)
print(f"LOOKAROUND roll {_LA_ROLL_EFF:.2f} deg, lift {_LA_LIFT:.4f} (resid {_LA_RESID:.4f}, half-width {_LA_HW:.3f}, rest mesh min {_LA_M0:+.4f}, rolled@2deg {_LA_MROLL:+.4f})")
make_cyclic(EXTRA_ACTION)

# ---- guard: tips in [-0.02, 0.06], mesh above ground, first == last, yaw extremes --
_dg = bpy.context.evaluated_depsgraph_get()
_tmin, _tmax = 9.9, -9.9
_headx = {}
_poses = {}
for _f in range(1, _LA_LEN + 2):
    scene.frame_set(_f)
    _dg.update()
    _ae = arm.evaluated_get(_dg)
    for _leg in LEGS:
        _tip = _ae.matrix_world @ _ae.pose.bones[f"{_leg}.lower"].tail
        _tmin = min(_tmin, _tip.z); _tmax = max(_tmax, _tip.z)
    if _f in (1, 30, 80, _LA_LEN + 1):
        _headx[_f] = (_ae.matrix_world @ _ae.pose.bones["head"].tail).x
    if _f in (1, _LA_LEN + 1):
        _poses[_f] = [_ae.pose.bones[b.name].matrix.copy() for b in arm.pose.bones]
_first_last = max(abs(a[i][j] - b[i][j]) for a, b in zip(_poses[1], _poses[_LA_LEN + 1])
                  for i in range(4) for j in range(4))
_meshmin = min(_la_mesh_min(_f) for _f in (1, 16, 31, 46, 52, 61, 76, 90, 97, 104))
_dxL = _headx[30] - _headx[1]   # look LEFT hold -> head tip should move +X
_dxR = _headx[80] - _headx[1]   # look RIGHT hold -> -X
_ok = (-0.02 <= _tmin and _tmax <= 0.06 and _meshmin >= min(-0.01, _LA_M0 - 0.001)
       and _first_last < 1e-4 and _dxL > 0.02 * KH and _dxR < -0.02 * KH)
EXTRA_GUARD = (f"{'OK' if _ok else 'FAIL'} tips z [{_tmin:+.3f},{_tmax:+.3f}] "
               f"meshMinZ={_meshmin:+.4f} (rest {_LA_M0:+.4f}) firstLastDiff={_first_last:.1e} "
               f"headTip dx left={_dxL:+.3f} right={_dxR:+.3f} (H_Y={H_Y:+.0f}) roll={_LA_ROLL_EFF:.2f}deg")
print("LOOKAROUND GUARD:", EXTRA_GUARD)
scene.frame_set(1)
