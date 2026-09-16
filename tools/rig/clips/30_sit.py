# Sit (72f): dog-style sit. stand -> rump drops (hind legs FOLD with 2-bone IK,
# front legs stay straight columns, body pitches nose-up about the front paws)
# -> 30f hold with a head look + tail wag -> rise back to stand. All paws stay
# planted; the hind paws slide forward under the body as the thigh folds flat.
#
# The hold pose is SOLVED per creature from the rig geometry, not hand-tuned:
#   hips pitch th, chest pitch ph = ratio*th, and a world (dy, dz) body offset so that
#     (a) both front leg roots stay pinned above their paws at standing height
#         (front columns stay vertical: the body pivots about the front legs),
#     (b) the hind hip roots end at SIT_DEPTH*HIP_Z,
#     (c) the torso mesh (rump/belly/udder, NOT the tail) stays >= RUMP_CLEAR above the ground.
#   The spine arch (ratio) is swept: the gentlest arch that reaches the target depth
#   wins; when no arch can (rump already hangs low, e.g. Fox) the sit stops with the
#   rump resting on the ground and the achieved depth is reported in EXTRA_GUARD.
#   The tail is NOT a depth limiter: a hanging tail slab (Wolf) is lifted (TAIL_PITCH
#   swept up to 95 deg) until it clears the ground and lies along it behind the rump;
#   only when even that cannot clear it (Cat) does the tail rejoin the clearance set.
# Hind fold: stifle-forward (thigh forward, shank vertical with the knee above the
# paw) so the rigid paw box stays flat on the ground. During the sit-down / rise the
# hind paw is NOT slid linearly: each frame the paw target is derived from the hip
# root so the shank leans at most SHANK_TILT+SHANK_SWING (paw box corner dip stays
# under ~0.5 vox instead of the ~1 vox a linear slide gave). The thick thigh block does
# clip the ground plane on big-legged rigs (Cow/Hippo) the same way the shipped
# Walk/Gallop leg blocks already do — that is a rig-fidelity limit, reported as
# "leg mesh minz" in the guard, never a bone tip.
# Rest frames (s=0: f1..f4, f70..f73) match the Idle stand: straight-column legs
# (column solve, zero bend) and the body at -BODY_DROP; the 2-bone hind solve is
# blended in over the first KNEE_BLEND of the sit fraction so there is no pop against
# Idle and no kink in the standing frames (the guard measures f1 against Idle f1).
EXTRA_ACTION = new_action("Sit")
EXTRA_LENGTH = 72
_SL = EXTRA_LENGTH
_DOWN = (4, 22)          # stand -> sit
_UP = (52, 70)           # sit -> stand (70..73 = stand, frame 73 == frame 1)
SIT_DEPTH = 0.35         # hind hip-root height at the hold, fraction of HIP_Z
RUMP_LIMIT = 0.60        # a rump-limited sit still counts as a sit only if hind root <= this x rest
RUMP_CLEAR = 0.005       # m, lowest torso mesh point must stay above this (rump may rest on the ground)
CHEST_RATIOS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.5, 7.0)   # chest pitch / hips pitch candidates (spine arch)
SHANK_TILT = 3.0         # deg, hind lower bone leans knee-forward at the hold (paw box corner dips w*sin)
SHANK_SWING = 8.0        # deg, extra knee-forward shank lean at mid-transition (sin(pi*s) bump); the paw
                         # slides so the shank never tilts more than this -> the rigid paw box stays near flat
KNEE_BLEND = 0.03        # sit fraction over which the hind legs go column -> 2-bone fold
HEAD_LEVEL = 0.6         # head counters this fraction of the body pitch (ends slightly nose-up)
EAR_PERK = 6.0           # deg
TAIL_UP = 8.0            # deg, extra tail lift while sitting (minimum; raised by the tail sweep)
TAIL_MAX = 95.0          # deg, cap of the tail lift sweep
WAG_AMP, WAG_HZ = 13.0, 2.4
LOOK_YAW = 14.0          # deg, head look during the hold
HEAD_DIP = 7.0           # deg, transient head dip during the sit-down / rise
STAND_H = HIP_Z - BODY_DROP          # front root height that keeps columns planted (same as Idle)
_W2L = pb["hips"].bone.matrix_local.to_3x3().inverted()
TAIL_PITCH = 4.0 + TAIL_UP           # deg at the hold; solved below


def _sit_frac(f):
    if f < _DOWN[0]:
        return 0.0
    if f < _DOWN[1]:
        return smoothstep((f - _DOWN[0]) / (_DOWN[1] - _DOWN[0]))
    if f <= _UP[0]:
        return 1.0
    if f < _UP[1]:
        return 1.0 - smoothstep((f - _UP[0]) / (_UP[1] - _UP[0]))
    return 0.0


# ---- torso mesh candidates (lowest vertex per bone/y column; rigid weights) --------
_TORSO = ("hips", "chest", "head", "tail", "earL", "earR")
_TORSO_NOTAIL = ("hips", "chest", "head", "earL", "earR")
_CLEAR_BONES = _TORSO_NOTAIL         # bones whose mesh constrains the body solve
_GI = {vg.index: vg.name for vg in obj.vertex_groups}
_VBONE = {}
_cand = {}
for _v in obj.data.vertices:
    if not _v.groups:
        continue
    _bn = _GI[_v.groups[0].group]
    _VBONE[_v.index] = _bn
    if _bn in _TORSO:
        _k = (_bn, round(_v.co.y, 4))
        if _k not in _cand or _v.co.z < _cand[_k].z:
            _cand[_k] = _v.co.copy()
_TORSO_PTS = {}
for (_bn, _), _co in _cand.items():
    _TORSO_PTS.setdefault(_bn, []).append(_co)


def _set_body(th, ph, dz, dy=0.0):
    """Pose (no keys) the body channels of the sit at pitch th/ph, world drop dz, world shift dy."""
    pb["hips"].rotation_euler = (math.radians(-HP_D * th), 0, 0)
    pb["chest"].rotation_euler = (math.radians(-C_D * ph), 0, 0)
    pb["head"].rotation_euler = (math.radians(H_D * HEAD_LEVEL * (th + ph)), 0, 0)
    pb["tail"].rotation_euler = (math.radians(T_U * TAIL_PITCH), 0, 0)
    pb["hips"].location = _W2L @ Vector((0.0, dy, dz))
    bpy.context.view_layer.update()


def _root(leg):
    par = pb["chest" if leg[0] == "F" else "hips"]
    M = par.matrix @ par.bone.matrix_local.inverted()
    root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
    v = M.to_3x3() @ Vector((0, 0, -1))
    return root, math.atan2(-v.y, -v.z)


def _torso_min_z(bones=None):
    mz = 9.9
    for bn, pts in _TORSO_PTS.items():
        if bn not in (bones if bones is not None else _CLEAR_BONES):
            continue
        b = pb[bn]
        M = arm.matrix_world @ b.matrix @ b.bone.matrix_local.inverted()
        for co in pts:
            mz = min(mz, (M @ co).z)
    return mz


def _body_for(th, ph):
    """(dy, dz) that pin the front roots above their paws at STAND_H (front columns stay
    vertical: the body pivots about the front legs), and the resulting hind root z."""
    _set_body(th, ph, 0.0)
    rF = 0.5 * (_root("FL")[0] + _root("FR")[0])
    dz, dy = STAND_H - rF.z, LEG_Y["F"] - rF.y
    _set_body(th, ph, dz, dy)
    zH = 0.5 * (_root("HL")[0].z + _root("HR")[0].z)
    return dy, dz, zH


def _solve(hH, ratio):
    lo, hi = 0.0, 75.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        dy, dz, zH = _body_for(mid, ratio * mid)
        if zH > hH:
            lo = mid
        else:
            hi = mid
    th = 0.5 * (lo + hi)
    dy, dz, zH = _body_for(th, ratio * th)
    return th, ratio * th, dz, zH, _torso_min_z(), dy


_TARGET = SIT_DEPTH * HIP_Z


def _depth_for(ratio):
    """Deepest hind-root height (>= target) whose torso mesh clears the ground at this arch."""
    if _solve(_TARGET, ratio)[4] >= RUMP_CLEAR:
        return _TARGET
    lo, hi = _TARGET, 0.85 * HIP_Z
    for _ in range(16):
        mid = 0.5 * (lo + hi)
        if _solve(mid, ratio)[4] >= RUMP_CLEAR:
            hi = mid
        else:
            lo = mid
    return hi


def _pick_arch():
    """Spine arch: the gentlest one that reaches the target depth, else the one that
    sits deepest with the rump resting on the ground (rump-limited creatures)."""
    ratio, hH = CHEST_RATIOS[0], _depth_for(CHEST_RATIOS[0])
    sweep = [(ratio, hH / HIP_Z)]
    for r in CHEST_RATIOS[1:]:
        if hH <= _TARGET + 1e-4:
            break
        d = _depth_for(r)
        sweep.append((r, d / HIP_Z))
        if d < hH - 0.02 * HIP_Z:
            ratio, hH = r, d
    note = "target depth" if hH <= _TARGET + 1e-4 else "depth limited by rump/ground contact"
    return ratio, hH, note, sweep


_ratio, _hH, _note, _sweep = _pick_arch()
print("SIT sweep (chest ratio -> deepest hind root xHIP_Z, tail free):", [(r, round(d, 3)) for r, d in _sweep])
TH, PH, DZ, ZH_HOLD, TMZ_HOLD, DY = _solve(_hH, _ratio)

# tail: a hanging tail slab must not be what stops the rump from reaching the ground.
# Lift it (3-deg steps, cap TAIL_MAX) until the tail mesh clears the ground at the hold;
# if even the cap cannot clear it, the tail rejoins the clearance set and the body is re-solved.
_set_body(TH, PH, DZ, DY)
_tail_mode = "tail clear at base lift"
if "tail" in _TORSO_PTS and _torso_min_z(("tail",)) < RUMP_CLEAR:
    for _tp in range(int(TAIL_PITCH), int(TAIL_MAX) + 1, 3):
        TAIL_PITCH = float(_tp)
        _set_body(TH, PH, DZ, DY)
        if _torso_min_z(("tail",)) >= RUMP_CLEAR:
            _tail_mode = f"tail lifted to {TAIL_PITCH:.0f} deg"
            break
    else:
        TAIL_PITCH = 4.0 + TAIL_UP
        _CLEAR_BONES = _TORSO
        _ratio, _hH, _note, _sweep = _pick_arch()
        print("SIT sweep (tail-limited re-solve):", [(r, round(d, 3)) for r, d in _sweep])
        TH, PH, DZ, ZH_HOLD, TMZ_HOLD, DY = _solve(_hH, _ratio)
        _tail_mode = "tail cannot clear -> tail-limited solve"
_set_body(TH, PH, DZ, DY)
TMZ_HOLD = _torso_min_z(_TORSO)
print(f"SIT tail: {_tail_mode}, tail minz {_torso_min_z(('tail',)):.3f}")

# hind paw target at the hold: stifle-forward fold (thigh forward, shank near-vertical
# with the knee above the paw leaning SHANK_TILT forward) so the rigid paw box stays
# flat on the ground. solve_leg picks the knee side from the leg letter: "H" gives the
# hock-back fold (shank lies flat on the ground and its box knifes in), so the hind
# legs are solved with the "F" knee side.
_rH = 0.5 * (_root("HL")[0] + _root("HR")[0])
_sg = math.radians(SHANK_TILT)
_dx_knee = math.sqrt(max(0.0, L1 * L1 - (ZH_HOLD - L2 * math.cos(_sg)) ** 2))
_dx_paw = _dx_knee - L2 * math.sin(_sg)
SLIDE = LEG_Y["H"] - (_rH.y - _dx_paw)        # forward slide of the hind paws (+ = toward the nose)


def _hind_paw_dx(h, s):
    """Forward offset (root.y - paw_y) of a hind paw for hip-root height h above the paw
    target, with the shank leaning knee-forward by SHANK_TILT + SHANK_SWING*sin(pi*s),
    capped at the lean the folding leg can geometrically reach (0 when the leg is straight)."""
    t = math.radians(SHANK_TILT + SHANK_SWING * math.sin(math.pi * s))
    c = (h - L1) / L2                                      # shank must reach down from the thigh
    if c >= 1.0:
        return 0.0
    t = min(t, math.acos(max(-1.0, c)))
    dxk = math.sqrt(max(0.0, L1 * L1 - (h - L2 * math.cos(t)) ** 2))
    return dxk - L2 * math.sin(t)
clear_pose()
print(f"SIT solve: hips {TH:.1f} deg, chest {PH:.1f} deg (ratio {_ratio:.2f}), drop {DZ:+.3f} shift {DY:+.3f}, "
      f"hind root z {ZH_HOLD:.3f} = {ZH_HOLD/HIP_Z:.2f}xHIP_Z, torso minz {TMZ_HOLD:.3f} ({_note}), "
      f"hind paw slide {SLIDE:.3f} ({SLIDE/S:.1f} vox), L1={L1:.3f} L2={L2:.3f}")


def _look(f):
    """head yaw envelope during the hold: glance left, hold, back."""
    if f < 28 or f > 48:
        return 0.0
    if f < 33:
        return smoothstep((f - 28) / 5.0)
    if f <= 42:
        return 1.0
    return 1.0 - smoothstep((f - 42) / 6.0)


def _dip(f):
    """small head dip while the body is in motion (looks down as it settles / pushes up)."""
    for a, b in (_DOWN, _UP):
        if a <= f <= b:
            return math.sin(math.pi * (f - a) / (b - a))
    return 0.0


def _key_sit_frame(f):
    s = _sit_frac(f)
    th, ph = TH * s, PH * s
    key_rot("hips", f, (-HP_D * th, 0, 0))
    key_rot("chest", f, (-C_D * ph, 0, 0))
    key_rot("head", f, (H_D * (HEAD_LEVEL * (th + ph) + HEAD_DIP * _dip(f)), 0, H_Y * LOOK_YAW * _look(f)))
    key_rot("earL", f, (E_F * EAR_PERK * s, 0, 0))
    key_rot("earR", f, (E_F * EAR_PERK * s, 0, 0))
    wag = WAG_AMP * s * math.sin(2 * math.pi * (f - _DOWN[1]) * WAG_HZ / FPS)
    key_rot("tail", f, (T_U * (4.0 + (TAIL_PITCH - 4.0) * s), 0, T_Y * wag))
    key_hips_world(f, 0.0, 0.0)
    scene.frame_set(f)
    bpy.context.view_layer.update()
    rF = 0.5 * (_root("FL")[0] + _root("FR")[0])
    key_hips_world(f, LEG_Y["F"] - rF.y, STAND_H - rF.z)   # front roots pinned above the front paws
    scene.frame_set(f)
    bpy.context.view_layer.update()
    w = smoothstep(s / KNEE_BLEND)                          # 0 = Idle column, 1 = 2-bone fold
    for leg in LEGS:
        root, delta = _root(leg)
        if leg[0] == "F":
            ux, lx = solve_leg(root.y - LEG_Y["F"], 0.0, leg, root.z, delta)
        else:
            zf = -BODY_DROP * (1.0 - s)                     # s=0: target BODY_DROP under ground = Idle column tip
            paw_y = root.y - _hind_paw_dx(root.z - zf, s)  # == LEG_Y["H"] - SLIDE at s=1 (same formula as the hold)
            uc, lc = solve_leg(root.y - paw_y, zf, leg, root.z, delta)                        # straight column (Idle)
            uk, lk = solve_leg(root.y - paw_y, zf, "F" + leg[1], root.z, delta, knee=True)    # stifle-forward fold
            ux, lx = (1 - w) * uc + w * uk, (1 - w) * lc + w * lk
        key_rot(f"{leg}.upper", f, (ux, 0, 0))
        key_rot(f"{leg}.lower", f, (lx, 0, 0))


for _f in range(1, _SL + 2):
    _key_sit_frame(_f)
make_cyclic(EXTRA_ACTION)

# ---- guard: evaluated bone tips, hip root heights, mesh vs ground (ALL frames), loop,
#      and the f1 pose vs the Idle stand (rest pose shifted down by BODY_DROP) ----------
_dg = bpy.context.evaluated_depsgraph_get()
_tmin, _tmax = 9.9, -9.9
_mats = {}
_hold_f = (_DOWN[1] + _UP[0]) // 2
_torso_mz, _leg_mz, _leg_mz_hold = 9.9, 9.9, 9.9
_torso_mz_f, _leg_mz_f = 0, 0
for _f in range(1, _SL + 2):
    scene.frame_set(_f)
    _dg.update()
    _ae = arm.evaluated_get(_dg)
    for _l in LEGS:
        _z = (_ae.matrix_world @ _ae.pose.bones[f"{_l}.lower"].tail).z
        _tmin, _tmax = min(_tmin, _z), max(_tmax, _z)
    if _f in (1, _SL, _SL + 1):
        _mats[_f] = [_ae.pose.bones[b.name].matrix.copy() for b in _ae.pose.bones]
    if _f == 1:
        _hips_rest = (_ae.matrix_world @ _ae.pose.bones["hips"].head).z
        _hroot_rest = (_ae.matrix_world @ _ae.pose.bones["HL.upper"].head).z
        _sit_tails = {_b.name: (_ae.matrix_world @ _b.tail).copy() for _b in _ae.pose.bones}
        _u = (_ae.pose.bones["HL.upper"].tail - _ae.pose.bones["HL.upper"].head)
        _lo = (_ae.pose.bones["HL.lower"].tail - _ae.pose.bones["HL.lower"].head)
        _knee_bend_f1 = math.degrees(_u.angle(_lo))
    if _f == _hold_f:
        _hips_hold = (_ae.matrix_world @ _ae.pose.bones["hips"].head).z
        _hroot_hold = (_ae.matrix_world @ _ae.pose.bones["HL.upper"].head).z
        _knee = _ae.matrix_world @ _ae.pose.bones["HL.upper"].tail
        _paw = _ae.matrix_world @ _ae.pose.bones["HL.lower"].tail
    _ev = obj.evaluated_get(_dg)
    _MW = _ev.matrix_world
    for _v in _ev.data.vertices:
        _z = (_MW @ _v.co).z
        if _VBONE.get(_v.index) in _TORSO:
            if _z < _torso_mz:
                _torso_mz, _torso_mz_f = _z, _f
        else:
            if _z < _leg_mz:
                _leg_mz, _leg_mz_f = _z, _f
            if _f == _hold_f:
                _leg_mz_hold = min(_leg_mz_hold, _z)
# f1 vs the real Idle f1 (ears excluded: Idle's cyclic ear-twitch keys make its ear pose frame-dependent)
arm.animation_data.action = bpy.data.actions["Idle"]
scene.frame_set(1)
_dg.update()
_ae = arm.evaluated_get(_dg)
_idle_pop, _idle_pop_hind = 0.0, 0.0
for _b in _ae.pose.bones:
    if _b.name in ("earL", "earR"):
        continue
    _d = ((_ae.matrix_world @ _b.tail) - _sit_tails[_b.name]).length
    _idle_pop = max(_idle_pop, _d)
    if _b.name[0] == "H" and "." in _b.name:
        _idle_pop_hind = max(_idle_pop_hind, _d)
arm.animation_data.action = EXTRA_ACTION
scene.frame_set(1)
_loop = max(max(abs(a - b) for a, b in zip(m1.to_translation(), m2.to_translation()))
            for m1, m2 in zip(_mats[1], _mats[_SL + 1]))
_loop72 = max(max(abs(a - b) for a, b in zip(m1.to_translation(), m2.to_translation()))
              for m1, m2 in zip(_mats[1], _mats[_SL]))
_depth_ok = _hroot_hold <= 0.5 * _hroot_rest
_depth_limited_ok = (_note != "target depth") and _hroot_hold <= RUMP_LIMIT * _hroot_rest
_ok = ((_depth_ok or _depth_limited_ok) and -0.02 <= _tmin and _tmax <= 0.06
       and _torso_mz >= -0.01 and _loop < 1e-4 and _loop72 < 2e-3
       and _idle_pop < 0.25 * S and _idle_pop_hind < 1e-3 and _knee_bend_f1 < 1.0)
_tag = "OK" if _ok else "FAIL"
if _ok and not _depth_ok:
    _tag = f"OK (depth rump-limited, {_hroot_hold/_hroot_rest:.2f}x rest <= {RUMP_LIMIT:.2f}x)"
EXTRA_GUARD = (f"{_tag} hind hip root hold z={_hroot_hold:.3f} rest={_hroot_rest:.3f} "
               f"({_hroot_hold/_hroot_rest:.2f}x, {_hroot_hold/HIP_Z:.2f}xHIP_Z) | hips bone head z hold={_hips_hold:.3f} "
               f"rest={_hips_rest:.3f} ({_hips_hold/_hips_rest:.2f}x) | tips z [{_tmin:+.3f},{_tmax:+.3f}] | "
               f"torso mesh minz {_torso_mz:+.3f}@f{_torso_mz_f} leg mesh minz {_leg_mz:+.3f}@f{_leg_mz_f} (hold {_leg_mz_hold:+.3f}) "
               f"[all {_SL+1} frames] | HL knee y/z {_knee.y:+.3f}/{_knee.z:.3f} paw y/z {_paw.y:+.3f}/{_paw.z:+.3f} | "
               f"f1 vs Idle f1: pop {_idle_pop:.4f} m ({_idle_pop/S:.2f} vox, hind legs {_idle_pop_hind:.4f}) knee bend {_knee_bend_f1:.1f} deg | "
               f"loop f73-f1 {_loop:.5f} f72-f1 {_loop72:.4f} | pitch hips {TH:.1f} chest {PH:.1f} drop {DZ:+.3f} "
               f"shift {DY:+.3f} slide {SLIDE:.3f} tail {TAIL_PITCH:.0f} deg ({_note}; {_tail_mode})")
print("SIT GUARD:", EXTRA_GUARD)
