# ---- extra clip: Rear (72f one-shot: crouch -> rear up on the hind legs, paw the
# air -> hold -> drop with a landing absorb -> rest). Exec'd inside the build
# namespace: every helper/constant of generic_quad_build.py is a plain global.
#
# Geometry notes (why the pitch is split): the hips bone pivots at 0.33 L / body-mid,
# which is far from the hind roots on every test creature (Cow: 0.4 m above them,
# Fox: 0.2 m behind them). So the body is pitched about the hips, then TRANSLATED
# (dy, dz) so the hind roots sit straight above their planted paws at a chosen height
# (knee bend). Whatever fraction of the total pitch would drive the rump/tail slab
# into the ground moves to the chest (arch) instead — the Fox's tail hangs 0.35 m
# behind its 0.2 m legs and only 0.1 m off the ground, so it can only pitch ~12 deg
# at the hips; the chest supplies the rest of its ~45 deg front lift.
EXTRA_ACTION = new_action("Rear")
EXTRA_LENGTH = 72
RLEN = EXTRA_LENGTH
LTOT = L1 + L2                     # full leg reach (== HIP_Z)
HIPS_W2L_R = pb["hips"].bone.matrix_local.to_3x3().inverted()

# ---- tuning (angles fixed, distances scale with the leg reach) --------------------
TOTAL_PITCH = 48.0                 # nose-up at the front (hips + chest), deg
HIPS_SHARES = (48.0, 42.0, 36.0, 30.0, 24.0, 18.0, 12.0)   # hips part, tried high -> low
CHEST_MAX = 34.0                   # chest arch cap (seam gap at the chest/hips boundary)
HIND_HS = (0.80, 0.90, 0.97)       # hind root height at the hold, x HIP_Z (bent -> straight)
BODY_CLEAR = 0.015   # required body-mesh ground clearance (m); the guard only needs >= -0.01, and 0.06*HIP_Z starved long-legged rigs into the chest-kink fallback
CROUCH = 0.10 * HIP_Z              # anticipation dip
LAND = 0.12 * HIP_Z                # landing absorb dip
HEAD_LEVEL = 0.30                  # head pitches down this fraction of the total pitch
EAR_FWD = 12.0
TAIL_UP = 30.0
PAW_R = 0.62                       # front foot distance from its root, x LTOT
PAW_PHI0, PAW_AMP = 45.0, 25.0     # deg from world-down toward the nose; +-swing
PAW_PERIOD = 12                    # frames per paw stroke (~2.3 strokes in the hold)

# phase boundaries (frames)
F_CROUCH, F_RISE, F_HOLD_END, F_LAND, F_ABSORB, F_UP = 9, 20, 48, 58, 61, 67


def _leg_root(leg):
    """World root of a leg + parent tilt (same maths as key_planted_legs)."""
    par = pb["chest" if leg[0] == "F" else "hips"]
    M = par.matrix @ par.bone.matrix_local.inverted()
    root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
    v = M.to_3x3() @ Vector((0, 0, -1))
    return root, math.atan2(-v.y, -v.z)


def _set_body(hp, cp, dy, dz, head_dn, ear, tail_up):
    """Direct pose (no keys) for the pre-search."""
    pb["hips"].location = tuple(HIPS_W2L_R @ Vector((0.0, dy, dz)))
    pb["hips"].rotation_euler = (math.radians(-HP_D * hp), 0, 0)
    pb["chest"].rotation_euler = (math.radians(-C_D * cp), 0, 0)
    pb["head"].rotation_euler = (math.radians(H_D * head_dn), 0, 0)
    pb["earL"].rotation_euler = (math.radians(E_F * ear), 0, 0)
    pb["earR"].rotation_euler = (math.radians(E_F * ear), 0, 0)
    pb["tail"].rotation_euler = (math.radians(T_U * tail_up), 0, 0)
    bpy.context.view_layer.update()


def _key_body(f, hp, cp, dy, dz, head_dn, ear, tail_up):
    key_hips_world(f, dy, dz)
    key_rot("hips", f, (-HP_D * hp, 0, 0))
    key_rot("chest", f, (-C_D * cp, 0, 0))
    key_rot("head", f, (H_D * head_dn, 0, 0))
    key_rot("earL", f, (E_F * ear, 0, 0))
    key_rot("earR", f, (E_F * ear, 0, 0))
    key_rot("tail", f, (T_U * tail_up, 0, 0))


# body-only vertex set (legs excluded: a tilted paw box legitimately dips below its tip)
_BODY_G = {obj.vertex_groups[n].index for n in ("hips", "chest", "head", "earL", "earR", "tail")}
_BODY_V = [v.index for v in obj.data.vertices if any(g.group in _BODY_G for g in v.groups)]


def _mesh_min_z(dg):
    oe = obj.evaluated_get(dg)
    mw = oe.matrix_world
    vs = oe.data.vertices
    return min((mw @ vs[i].co).z for i in _BODY_V)


def _hind_root_mean():
    a, _ = _leg_root("HL"); b, _ = _leg_root("HR")
    return 0.5 * (a + b)


def _plant_hind_direct():
    for l in ("HL", "HR"):
        r, d = _leg_root(l)
        u, lo = solve_leg(r.y - LEG_Y["H"], 0.0, l, r.z, d, knee=True)
        pb[f"{l}.upper"].rotation_euler = (math.radians(u), 0, 0)
        pb[f"{l}.lower"].rotation_euler = (math.radians(lo), 0, 0)


# ---- pre-search: steepest hips share / deepest knee bend that keeps the body off the ground
HIPS_PITCH, CHEST_PITCH, HIND_H_PEAK = None, None, None
_search = []
for _hp in HIPS_SHARES:
    _cp = min(TOTAL_PITCH - _hp, CHEST_MAX)
    for _hh in HIND_HS:
        clear_pose()
        _set_body(_hp, _cp, 0.0, 0.0, HEAD_LEVEL * (_hp + _cp), EAR_FWD, TAIL_UP)
        _r0 = _hind_root_mean()
        _dy, _dz = LEG_Y["H"] - _r0.y, _hh * HIP_Z - _r0.z     # hips translation is world-linear
        _set_body(_hp, _cp, _dy, _dz, HEAD_LEVEL * (_hp + _cp), EAR_FWD, TAIL_UP)
        _plant_hind_direct()
        arm.update_tag(refresh={'OBJECT', 'DATA'}); obj.update_tag(refresh={'OBJECT', 'DATA'})
        bpy.context.view_layer.update()
        _dg = bpy.context.evaluated_depsgraph_get(); _dg.update()   # FRESH evaluation per candidate (a cached depsgraph returned the previous candidate's mesh)
        _mz = _mesh_min_z(_dg)
        _search.append((_hp, _cp, _hh, round(_mz, 3)))
        if _mz >= BODY_CLEAR:
            HIPS_PITCH, CHEST_PITCH, HIND_H_PEAK = _hp, _cp, _hh
            break
    if HIPS_PITCH is not None:
        break
if HIPS_PITCH is None:                      # nothing clears: least aggressive option
    HIPS_PITCH, CHEST_PITCH, HIND_H_PEAK = HIPS_SHARES[-1], CHEST_MAX, HIND_HS[-1]
    print(f"REAR WARNING: no candidate cleared BODY_CLEAR={BODY_CLEAR}; falling back to hips={HIPS_PITCH} chest={CHEST_PITCH} (chest-kink pose)")
clear_pose()
print("REAR pitch search (hips, chest, hind_h, body_minz):", _search)
print(f"REAR peak: hips={HIPS_PITCH:.0f} chest={CHEST_PITCH:.0f} total={HIPS_PITCH+CHEST_PITCH:.0f}deg "
      f"hind_root_h={HIND_H_PEAK:.2f}xHIP_Z clear>={BODY_CLEAR:.3f}")
PEAK_PITCH = HIPS_PITCH + CHEST_PITCH
HIPS_FRAC = HIPS_PITCH / PEAK_PITCH


# ---- schedule -----------------------------------------------------------------------
def _lerp(a, b, t): return a + (b - a) * t


def _sched(f):
    """-> (total pitch, hind_root_height, front_air_blend, paw_phase or None)"""
    rest_h = HIP_Z - BODY_DROP
    if f <= F_CROUCH:                       # anticipation: sink, tiny nose-down
        s = smoothstep((f - 1) / (F_CROUCH - 1))
        return -4.0 * s, rest_h - CROUCH * s, 0.0, None
    if f <= F_RISE:                         # rise
        s = smoothstep((f - F_CROUCH) / (F_RISE - F_CROUCH))
        pitch = _lerp(-4.0, PEAK_PITCH, s)
        h = _lerp(rest_h - CROUCH, HIND_H_PEAK * HIP_Z, s)
        air = smoothstep((f - F_CROUCH) / (F_RISE - F_CROUCH - 3))   # front feet leave early
        return pitch, h, air, None
    if f <= F_HOLD_END:                     # hold + paw the air
        u = (f - F_RISE) / (F_HOLD_END - F_RISE)
        sway = 2.0 * math.sin(2 * math.pi * u * 1.5)
        return PEAK_PITCH + sway, HIND_H_PEAK * HIP_Z, 1.0, (f - F_RISE) / PAW_PERIOD
    if f <= F_LAND:                         # drop
        s = smoothstep((f - F_HOLD_END) / (F_LAND - F_HOLD_END))
        pitch = _lerp(PEAK_PITCH, 0.0, s)
        h = _lerp(HIND_H_PEAK * HIP_Z, rest_h - LAND, s)
        return pitch, h, 1.0 - s, None
    if f <= F_ABSORB:                       # landing absorb (stay low, nose dips)
        s = (f - F_LAND) / (F_ABSORB - F_LAND)
        return -3.0 * math.sin(math.pi * s), rest_h - LAND, 0.0, None
    if f <= F_UP:                           # back up to rest height
        s = smoothstep((f - F_ABSORB) / (F_UP - F_ABSORB))
        return 0.0, _lerp(rest_h - LAND, rest_h, s), 0.0, None
    return 0.0, rest_h, 0.0, None


def _paw_target(leg, root, phase):
    """World target of a pawing front foot relative to its root (sagittal plane)."""
    sgn = 1.0 if leg == "FL" else -1.0
    w = math.sin(2 * math.pi * phase) * sgn
    phi = math.radians(PAW_PHI0 + PAW_AMP * w)
    R = LTOT * (PAW_R + 0.12 * w)
    return Vector((root.x, root.y - R * math.sin(phi), root.z - R * math.cos(phi)))


# ---- key every frame ----------------------------------------------------------------
for f in range(1, RLEN + 1):
    pitch, hind_h, air, paw = _sched(f)
    if f == 1 or f == RLEN:
        _key_body(f, 0.0, 0.0, 0.0, -BODY_DROP, 0.0, 0.0, 0.0)
        key_stand_legs(f)                       # exact rest, identical first/last frame
        continue
    up = max(pitch, 0.0)
    hp = pitch if pitch < 0 else pitch * HIPS_FRAC     # the nose-down dips are hips-only
    cp = up * (1.0 - HIPS_FRAC)
    _key_body(f, hp, cp, 0.0, 0.0, HEAD_LEVEL * up, EAR_FWD * air, TAIL_UP * air)
    scene.frame_set(f); bpy.context.view_layer.update()
    r0 = _hind_root_mean()
    # keep the hind roots straight above their planted paws, at the scheduled height
    key_hips_world(f, LEG_Y["H"] - r0.y, hind_h - r0.z)
    scene.frame_set(f); bpy.context.view_layer.update()
    for leg in LEGS:
        root, delta = _leg_root(leg)
        if leg[0] == "H" or air <= 0.0:
            tgt = Vector((root.x, LEG_Y[leg[0]], 0.0))          # planted at the rest spot
        else:
            ta = _paw_target(leg, root, paw if paw is not None else 0.0)
            tg = Vector((root.x, LEG_Y["F"], 0.0))
            tgt = tg.lerp(ta, air)
        ux, lx = solve_leg(root.y - tgt.y, tgt.z, leg, root.z, delta, knee=True)
        key_rot(f"{leg}.upper", f, (ux, 0, 0))
        key_rot(f"{leg}.lower", f, (lx, 0, 0))

# ---- guard ------------------------------------------------------------------------------
dg = bpy.context.evaluated_depsgraph_get()
hind_lo, hind_hi, front_lo, front_hold_lo, body_lo = 9.9, -9.9, 9.9, 9.9, 9.9
for f in range(1, RLEN + 1):
    scene.frame_set(f); dg.update()
    ae = arm.evaluated_get(dg)
    tips = {l: (ae.matrix_world @ ae.pose.bones[f"{l}.lower"].tail).z for l in LEGS}
    for l in ("HL", "HR"):
        hind_lo = min(hind_lo, tips[l]); hind_hi = max(hind_hi, tips[l])
    for l in ("FL", "FR"):
        front_lo = min(front_lo, tips[l])
        if F_RISE + 2 <= f <= F_HOLD_END - 2:
            front_hold_lo = min(front_hold_lo, tips[l])
    if f % 2 == 1 or f in (F_CROUCH, F_RISE, F_LAND, F_ABSORB):
        body_lo = min(body_lo, _mesh_min_z(dg))


def _pose_sig(f):
    scene.frame_set(f); dg.update(); ae = arm.evaluated_get(dg)
    return {b.name: (tuple(round(v, 4) for v in b.rotation_euler), tuple(round(v, 4) for v in b.location))
            for b in ae.pose.bones}


loop_ok = _pose_sig(1) == _pose_sig(RLEN)
ok = (-0.02 <= hind_lo and hind_hi <= 0.06 and front_hold_lo >= 0.35 * HIP_Z
      and front_lo >= -0.02 and body_lo >= -0.01 and loop_ok)
EXTRA_GUARD = (f"{'OK' if ok else 'FAIL'} peak_pitch={PEAK_PITCH:.0f}deg(hips {HIPS_PITCH:.0f}+chest {CHEST_PITCH:.0f}) "
               f"hind_root={HIND_H_PEAK:.2f}xHIP_Z hind_tip=[{hind_lo:+.3f},{hind_hi:+.3f}] "
               f"front_tip_min={front_lo:+.3f} front_hold_min={front_hold_lo:.3f}(>= {0.35*HIP_Z:.3f}) "
               f"body_minz={body_lo:+.3f} last==first={loop_ok}")
print("REAR GUARD:", EXTRA_GUARD)

# one-shot that ends on the exact rest pose (frame 72 == frame 1); cyclic modifiers are
# harmless here and match the other clips if a player runs past the end
make_cyclic(EXTRA_ACTION)
