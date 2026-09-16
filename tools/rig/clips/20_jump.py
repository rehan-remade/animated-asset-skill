# Jump: one-shot standing hop (crouch -> launch -> airborne tuck -> land -> recover).
# Exec'd inside generic_quad_build.py's namespace; all helpers/constants are globals.
#
# Body motion while grounded is authored in LEG-LENGTH units through two channels:
#   hF   = front-leg-root height offset (x HIP_Z)      -> body drop / absorb
#   frac = hind-root minus front-root height (x HIP_Z) -> pitch, converted to degrees per creature
# so a 3 m Hippo and a 0.9 m Fox fold their legs by the same fraction. The hips-bone
# location is then solved numerically so the front roots land on the authored height.
# Grounded feet are keyed every frame from the evaluated leg roots; a folded stub leg tilts
# its paw BOX, so each foot target is raised until the leg's lowest vertex clears the ground.
# That hover fixed point runs away to the shank-tilt cap for a few mm of slack (tilt -> dip ->
# raise -> more slack -> more tilt), so the cap itself is ramped with the AUTHORED body drop:
# near the rest height the shank stays plumb and the leg shortens by swinging at the hip (a
# small foot slide), and the allowed tilt (with its hover) grows as the body sinks -- otherwise
# the legs pop from straight columns to fully folded, hovering, splayed legs on one frame.
import bpy as _bpy

EXTRA_ACTION = new_action("Jump")
EXTRA_LENGTH = 44
_N = EXTRA_LENGTH
_B0 = -BODY_DROP                       # rest body height offset (Idle frame 1)
_REACH = L1 + L2                       # == HIP_Z, full leg length
_SL = min(0.004 * K, BODY_DROP + 0.0005)  # slack band where the knee starts folding (column penetration <= rest)
_CLEAR = max(0.008, BODY_DROP + 0.0005)  # keep every leg vertex above this (rule: mesh >= -0.01)
_MESH_MIN = min(-0.01, -BODY_DROP - 0.002)  # rest columns already sink BODY_DROP (Idle f1 does too)
_LEVER = LEG_Y["H"] - LEG_Y["F"]       # front-to-hind leg root distance
_R0 = HIP_Z + _B0                      # leg root height at rest

# ---- vertex sets: belly clearance caps the crouch; per-leg sets drive the paw clearance ----
def _group_idx(names):
    s = set()
    for g in names:
        gi = obj.vertex_groups[g].index
        s.update(v.index for v in obj.data.vertices if any(vg.group == gi for vg in v.groups))
    return sorted(s)


_torso_idx = _group_idx(("chest", "hips", "tail"))
_body_idx = _group_idx(("chest", "hips"))
_tail_idx = _group_idx(("tail",))
_leg_idx = {leg: _group_idx((f"{leg}.lower", f"{leg}.upper")) for leg in LEGS}
# crouch cap from the chest+hips slab only: a low-hanging tail slab is handled by the belly pass
# (tail-down pose given up, then a per-frame lift for what remains) instead of capping the whole clip
_torso_min = min(obj.data.vertices[i].co.z for i in _body_idx) if _body_idx else HIP_Z
_torso_min_all = min(obj.data.vertices[i].co.z for i in _torso_idx) if _torso_idx else HIP_Z
_BELLY_CLEAR = 0.012
# paw box half-length along the body: a shank tilted by phi drops a box corner half*sin(phi).
# Cap the grounded shank tilt so that dip stays ~0.22 shank lengths; the foot SLIDES fore/aft
# (legs splay) instead of hair-pinning when the body sinks further.
def _paw_half(leg):
    gi = obj.vertex_groups[f"{leg}.lower"].index
    ys = [v.co.y for v in obj.data.vertices if any(vg.group == gi for vg in v.groups)]
    return max(max(ys) - LEG_Y[leg[0]], LEG_Y[leg[0]] - min(ys)) if ys else 0.5 * L2
_PAW_HALF = max(_paw_half(l) for l in LEGS)
PHI_MAX = math.degrees(math.asin(min(1.0, 0.22 * L2 / _PAW_HALF)))
# crouch depth the legs can take with the upper bone tilted <= 55 deg and the shank at its tilt cap
_LEG_GIVE = L1 * (1 - math.cos(math.radians(55))) + L2 * (1 - math.cos(math.radians(PHI_MAX)))


CROUCH_F = min(0.28, max(0.12, (_torso_min - _BELLY_CLEAR) / HIP_Z), _LEG_GIVE / HIP_Z)   # front-root drop, x HIP_Z
ABSORB_F = min(0.22, CROUCH_F)
APEX = 0.90 * HIP_Z


def _pdeg(frac):
    """Pitch (deg, nose-up +) that lifts the hind roots frac*HIP_Z above the front roots."""
    return math.degrees(math.asin(max(-0.99, min(0.99, frac * HIP_Z / _LEVER))))


P24 = min(16.0, _pdeg(0.25))           # nose-down at touchdown: hind paws 0.25 leg-lengths up
print(f"JUMP scale: HIP_Z={HIP_Z:.3f} lever={_LEVER:.3f} torso_min={_torso_min:.3f} (incl.tail {_torso_min_all:.3f}) "
      f"crouch={CROUCH_F * HIP_Z:.3f} absorb={ABSORB_F * HIP_Z:.3f} apex={APEX:.3f} P24={P24:.1f}deg "
      f"pawHalf={_PAW_HALF:.3f} phiMax={PHI_MAX:.1f}deg")


def _ease_in(u):
    """u^2 (1.5 - 0.5 u^2): quadratic start, unit slope at the end. A stub leg's fold/slide grows
    like sqrt(body drop), so a crouch that starts quadratically folds the legs LINEARLY in time
    (smoothstep starts at 3u^2 -- twice the first-frame leg change -- and smoothstep^2 dumps the
    change into frames 3-4 instead)."""
    u = max(0.0, min(1.0, u))
    return u * u * (1.5 - 0.5 * u * u)


def _interp(keys, f):
    """Piecewise smoothstep interpolation of (frame, value[, ease]) keypoints; a key's optional
    third element is the easing used for the segment that ENDS at that key."""
    if f <= keys[0][0]:
        return keys[0][1]
    for k0, k1 in zip(keys, keys[1:]):
        if f <= k1[0]:
            ease = k1[2] if len(k1) > 2 else smoothstep
            return k0[1] + (k1[1] - k0[1]) * ease((f - k0[0]) / (k1[0] - k0[0]))
    return keys[-1][1]


# ---- body channels -----------------------------------------------------------------------
# front-root height (x HIP_Z) while grounded: crouch f1-8, hold, push f9-12; absorb f24-27, recover
_HF = [(1, 0), (8, -CROUCH_F, _ease_in), (9, -0.95 * CROUCH_F), (10, -0.75 * CROUCH_F), (11, -0.42 * CROUCH_F), (12, 0),
       (24, 0), (27, -ABSORB_F), (30, -0.6 * ABSORB_F), (34, -0.15 * ABSORB_F), (37, 0), (_N, 0)]
# pitch (deg, nose-up +): ground frames derived from leg-length fracs, flight frames free
_PITCH = [(1, 0), (8, _pdeg(0.08)), (11, _pdeg(0.02)), (12, 0),
          (14, 14), (17, 9), (20, -4), (24, -P24),
          (26, -_pdeg(0.13)), (27, -_pdeg(0.08)), (30, -_pdeg(0.03)), (33, 0), (_N, 0)]
_DY = [(1, 0), (8, 0.012 * K), (12, -0.004 * K), (18, -0.008 * K), (24, 0), (_N, 0)]   # + = tailward
_HEAD = [(1, 0), (8, -22), (11, -8), (13, 10), (17, 3), (21, -5), (24, -6), (27, -14), (33, -2), (_N, 0)]  # + = up
_EAR = [(1, 0), (8, -8), (12, -14), (18, -6), (23, 6), (27, 10), (34, 0), (_N, 0)]          # + = forward
_TAIL = [(1, 0), (8, -10), (12, 18), (18, 22), (24, 6), (27, -6), (34, 0), (_N, 0)]         # + = up


def _leg_root(leg):
    par = pb["chest" if leg[0] == "F" else "hips"]
    M = par.matrix @ par.bone.matrix_local.inverted()
    root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
    v = M.to_3x3() @ Vector((0, 0, -1))
    return root, math.atan2(-v.y, -v.z)


# pass A: rotations + zero body offset
for _f in range(1, _N + 1):
    _p = _interp(_PITCH, _f)
    key_rot("hips", _f, (-HP_D * _p, 0, 0))
    key_rot("chest", _f, (-C_D * 0.35 * _p, 0, 0))
    key_rot("head", _f, (-H_D * _interp(_HEAD, _f), 0, 0))
    _e = E_F * _interp(_EAR, _f)
    key_rot("earL", _f, (_e, 0, 0))
    key_rot("earR", _f, (_e, 0, 0))
    key_rot("tail", _f, (T_U * _interp(_TAIL, _f), 0, 0))
    key_hips_world(_f, _interp(_DY, _f), _B0)
# pass B: how far the pitch alone moves the front roots at each frame
_pdrop = {}
for _f in range(1, _N + 1):
    scene.frame_set(_f)
    _bpy.context.view_layer.update()
    _pdrop[_f] = _R0 - _leg_root("FL")[0].z
# pass C: body height. Grounded: front roots follow _HF. Flight f12-24: ballistic parabola with
# apex f18, eased up to the touchdown height where the nose-down body has its front roots at rest.
_E24 = _pdrop[24]
def _dz(f):
    if 12 <= f <= 24:
        u = (f - 18) / 6.0
        return APEX * (1 - u * u) + _E24 * smoothstep((f - 15) / 9.0)
    return _interp(_HF, f) * HIP_Z + _pdrop[f]


_dz_adj = {}
for _f in range(1, _N + 1):
    key_hips_world(_f, _interp(_DY, _f), _B0 + _dz(_f))
# pass D: belly clearance -- a crouching body may not sink its torso into the ground.
# Some rigs hang the tail bone down to the rump's bottom edge (or lower), so a tail slab is the
# first thing to touch down: raise the tail just enough (bisection on the tail-up angle; a
# wolf lifting its tail as it coils is fine), then lift the body for whatever chest/hips remain.
def _tail_min_z(f):
    scene.frame_set(f)
    dg = _bpy.context.evaluated_depsgraph_get()
    dg.update()
    oe = obj.evaluated_get(dg)
    return min((oe.matrix_world @ oe.data.vertices[i].co).z for i in _tail_idx)


_belly_lift = 0.0
_tail_raised = 0
_tail_up_max = 0.0
for _f in range(1, _N + 1):
    if 12 <= _f <= 24:
        continue
    if _tail_idx and _tail_min_z(_f) < _BELLY_CLEAR:
        lo = _interp(_TAIL, _f)
        hi = 75.0
        key_rot("tail", _f, (T_U * hi, 0, 0))
        if _tail_min_z(_f) >= _BELLY_CLEAR:
            for _ in range(9):
                mid = 0.5 * (lo + hi)
                key_rot("tail", _f, (T_U * mid, 0, 0))
                if _tail_min_z(_f) >= _BELLY_CLEAR:
                    hi = mid
                else:
                    lo = mid
        key_rot("tail", _f, (T_U * hi, 0, 0))
        _tail_raised += 1
        _tail_up_max = max(_tail_up_max, hi - _interp(_TAIL, _f))
    scene.frame_set(_f)
    dg = _bpy.context.evaluated_depsgraph_get()
    dg.update()
    oe = obj.evaluated_get(dg)
    tz = min((oe.matrix_world @ oe.data.vertices[i].co).z for i in _torso_idx)
    if tz < _BELLY_CLEAR:
        _dz_adj[_f] = _BELLY_CLEAR - tz
        _belly_lift = max(_belly_lift, _dz_adj[_f])
        key_hips_world(_f, _interp(_DY, _f), _B0 + _dz(_f) + _dz_adj[_f])
print(f"JUMP belly lift max={_belly_lift:.3f} on {len(_dz_adj)} frames; tail raised on {_tail_raised} frames "
      f"(max +{_tail_up_max:.1f} deg over the authored pose)")

# ---- foot targets ----------------------------------------------------------------------------
# ("G", dx): planted at the rest ground spot (+dx*HIP_Z tailward), height = ground (+clearance)
# ("A", dx, reach): airborne, foot at root + dx*HIP_Z tailward, reach*HIP_Z below the root
_FRONT = [(1, "G", 0), (12, "G", 0),
          (13, "A", 0.12, 0.97),          # trails just after takeoff
          (15, "A", -0.05, 0.55),         # folding up
          (18, "A", -0.22, 0.42),         # tucked forward/up at apex
          (21, "A", -0.16, 0.72),         # reaching for the ground
          (23, "A", -0.04, 0.99),
          (24, "G", 0), (_N, "G", 0)]
_HIND = [(1, "G", 0), (12, "G", 0),
         (13, "A", 0.28, 0.97),           # extended, pushing off behind
         (16, "A", 0.20, 0.72),
         (19, "A", -0.06, 0.48),          # tucked under
         (22, "A", -0.04, 0.72),
         (25, "A", 0.00, 0.99),
         (26, "G", 0), (_N, "G", 0)]


def _target_world(keys, f, root, leg):
    """World (y, z) foot target at frame f, blending planted spots and airborne offsets."""
    def one(k):
        if k[1] == "G":
            return (LEG_Y[leg[0]] + k[2] * HIP_Z, 0.0)
        return (root.y + k[2] * HIP_Z, root.z - k[3] * HIP_Z)
    if f <= keys[0][0]:
        return one(keys[0])
    for k0, k1 in zip(keys, keys[1:]):
        if f <= k1[0]:
            s = smoothstep((f - k0[0]) / (k1[0] - k0[0]))
            a, b = one(k0), one(k1)
            return (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
    return one(keys[-1])


def _solve(dx, zf, leg, hip_h, delta):
    """Airborne legs: knee IK when the leg has real slack, straight column when (nearly)
    extended, angle-blended in between (the leap is untouched by the ramp machinery below)."""
    D = math.hypot(dx, hip_h - zf)
    slack = _REACH - D
    if slack <= _SL:
        return solve_leg(dx, zf, leg, hip_h, delta, knee=False)
    uk, lk = solve_leg(dx, zf, leg, hip_h, delta, knee=True)
    if slack >= 3 * _SL:
        return uk, lk
    uc, lc = solve_leg(dx, zf, leg, hip_h, delta, knee=False)
    s = smoothstep((slack - _SL) / (2 * _SL))
    return uc + s * (uk - uc), lc + s * (lk - lc)


def _ik(dx, zf, leg, hip_h, delta, l1):
    """solve_leg(knee=True) with a VIRTUAL upper-bone length l1. Fully extended it is exactly
    the straight column (a2 = pi -> lower = 0), so shortening l1 by the rest slack makes the
    rest pose a column and lets the knee engage continuously as the body sinks."""
    dz = hip_h - zf
    D = math.hypot(dx, dz)
    theta = math.atan2(dx, dz)
    if D >= l1 + L2:                       # extended: the exact column (a 1 mm clamp margin
        return math.degrees(LX_SIGN * (theta - delta)), 0.0   # would already bend the knee 7 deg)
    D = max(abs(l1 - L2) + 1e-3, D)
    a1 = math.acos(max(-1.0, min(1.0, (l1 * l1 + D * D - L2 * L2) / (2 * l1 * D))))
    a2 = math.acos(max(-1.0, min(1.0, (l1 * l1 + L2 * L2 - D * D) / (2 * l1 * L2))))
    sgn = KNEE_S[leg[0]]
    return (math.degrees(LX_SIGN * (theta - delta + sgn * a1)),
            math.degrees(LX_SIGN * (-sgn * (math.pi - a2))))


def _shank_tilt(ux, lx, delta):
    """World tilt (deg, toward -Y/forward positive) of the shank for solved upper/lower angles."""
    return LX_SIGN * (ux + lx) + math.degrees(delta)


def _solve_slide(ty, tz, leg, root, delta, phi_lim, a=None):
    """Solve the leg toward the (ty, tz) world target; if the shank would tilt past phi_lim,
    move the foot along the body so the shank sits exactly at the cap (knee stays on its
    natural side) -- the leg splays instead of hair-pinning. Returns (ux, lx, slide).
    a (planted legs only) is the authored fold allowance: the rest slack _SL is absorbed by the
    column's penetration as in Idle, so the leg is solved with the upper bone shortened by
    _SL*(1-a) -- a straight column at a=0, the true 2-bone leg at a=1 -- and the cap geometry
    uses the same virtual bone, so no hip swing is spent on the rest slack."""
    # solve_leg's dx is positive toward -Y (forward): dx = root.y - foot.y
    if a is None:
        solve = _solve
        l1 = L1
    else:
        l1 = L1 - _SL * (1.0 - a)
        solve = lambda dx, zf, lg, hh, dl: _ik(dx, zf, lg, hh, dl, l1)
    ux, lx = solve(root.y - ty, tz, leg, root.z, delta)
    phi = _shank_tilt(ux, lx, delta)
    if abs(phi) <= phi_lim or phi_lim >= 89.0:
        return ux, lx, 0.0
    ph = math.radians(math.copysign(phi_lim, phi))
    kz = tz + L2 * math.cos(ph)                       # knee height for a capped shank
    dzk = kz - root.z
    ky = root.y - KNEE_S[leg[0]] * math.sqrt(max(0.0, l1 * l1 - dzk * dzk))
    fy = ky - L2 * math.sin(ph)                       # phi > 0: foot displaced toward -Y
    ux, lx = solve(root.y - fy, tz, leg, root.z, delta)
    return ux, lx, fy - ty


def _leg_min_z(dg):
    oe = obj.evaluated_get(dg)
    me = oe.data
    co = [0.0] * (3 * len(me.vertices))
    me.vertices.foreach_get("co", co)
    M = oe.matrix_world
    if abs(M[2][2] - 1) < 1e-6 and abs(M[2][3]) < 1e-9 and abs(M[2][0]) < 1e-9 and abs(M[2][1]) < 1e-9:
        zs = co[2::3]
    else:
        zs = [(M @ Vector((co[3 * i], co[3 * i + 1], co[3 * i + 2]))).z for i in range(len(me.vertices))]
    return {leg: min(zs[i] for i in _leg_idx[leg]) for leg in LEGS}, min(zs)


RAMP_FRAC = 0.5   # shank tilt cap reaches PHI_MAX once the body is this far into the crouch / absorb


def _ramp(f):
    """Authored fold allowance for planted legs: 0 at the rest height (plumb shank; the leg is
    the Idle column), 1 once the body drop reaches RAMP_FRAC of the crouch (f1-12) or absorb
    (f24-N) depth. Linear in the drop so the fold spreads over the first crouch frames."""
    if 12 < f < 24:
        return 1.0
    ref = CROUCH_F if f <= 12 else ABSORB_F
    return max(0.0, min(1.0, -_interp(_HF, f) / (RAMP_FRAC * ref))) if ref > 0 else 1.0


_hover = {leg: 0.0 for leg in LEGS}
_HOVER_LOG = []
_SLIDE_LOG = []
for _f in range(1, _N + 1):
    _a = _ramp(_f)
    scene.frame_set(_f)
    _bpy.context.view_layer.update()
    roots = {leg: _leg_root(leg) for leg in LEGS}
    tgt = {}
    for leg in LEGS:
        keys = _FRONT if leg[0] == "F" else _HIND
        tgt[leg] = _target_world(keys, _f, roots[leg][0], leg)
    _hover = {leg: 0.0 for leg in LEGS}       # cold start: lowest clearance fixed point
    for _it in range(24):
        slides = {}
        for leg in LEGS:
            root, delta = roots[leg]
            ty, tz = tgt[leg]
            # tilt cap: ramps in with the authored body drop while planted (plumb shank at rest,
            # PHI_MAX once crouched) and fades out as the foot leaves the ground (airborne tucks
            # may fold freely)
            planted = tz <= 1e-6
            lift = max(0.0, min(1.0, tz / (0.15 * HIP_Z)))
            uc, _ = solve_leg(root.y - ty, tz + _hover[leg], leg, root.z, delta, knee=False)
            phi_col = abs(_shank_tilt(uc, 0.0, delta))    # the plain column's own tilt is always allowed
            phi_g = phi_col + (PHI_MAX - phi_col) * _a
            phi_lim = phi_g + (90.0 - phi_g) * lift
            ux, lx, slides[leg] = _solve_slide(ty, tz + _hover[leg], leg, root, delta, phi_lim,
                                               _a if planted else None)
            key_rot(f"{leg}.upper", _f, (ux, 0, 0))
            key_rot(f"{leg}.lower", _f, (lx, 0, 0))
        scene.frame_set(_f)
        dg = _bpy.context.evaluated_depsgraph_get()
        dg.update()
        mins, _ = _leg_min_z(dg)
        moved = False
        for leg in LEGS:
            err = -_CLEAR - mins[leg]          # > 0: leg mesh dips below the clearance -> raise
            if err > 0.0005:
                _hover[leg] += err
                moved = True
        if not moved:
            break
    _HOVER_LOG.append((_f, dict(_hover)))
    _SLIDE_LOG.append((_f, slides))
_hmax = max(h[l] for _, h in _HOVER_LOG for l in LEGS)
_smax = max(abs(h[l]) for _, h in _SLIDE_LOG for l in LEGS)
print(f"JUMP paw clearance: max hover={_hmax:.3f} max splay slide={_smax:.3f} (phiMax={PHI_MAX:.1f}deg)")
print("JUMP ramp a: " + " ".join(f"f{f}:{_ramp(f):.2f}" for f in list(range(1, 13)) + list(range(24, 38))))
print("JUMP ramp FL hover/slide: " + " ".join(f"f{f}:{h['FL']:.3f}/{sl['FL']:+.3f}"
      for (f, h), (_, sl) in zip(_HOVER_LOG, _SLIDE_LOG) if f <= 12 or f >= 24))

# exact rest pose on the first and last frame (== Idle frame 1)
for _f in (1, _N):
    key_hips_world(_f, 0, _B0)
    for _b in ("hips", "chest", "head", "earL", "earR", "tail"):
        key_rot(_b, _f, (0, 0, 0))
    key_stand_legs(_f)

# ---- guard ----------------------------------------------------------------------------------
dg = _bpy.context.evaluated_depsgraph_get()
_minTip, _minMesh, _air_run, _air_best = 9.9, 9.9, 0, 0
for _f in range(1, _N + 1):
    scene.frame_set(_f)
    dg.update()
    ae = arm.evaluated_get(dg)
    zs = {l: (ae.matrix_world @ ae.pose.bones[f"{l}.lower"].tail).z for l in LEGS}
    _minTip = min(_minTip, min(zs.values()))
    _, mz = _leg_min_z(dg)
    _minMesh = min(_minMesh, mz)
    if all(z > 0.3 * HIP_Z for z in zs.values()):
        _air_run += 1
        _air_best = max(_air_best, _air_run)
    else:
        _air_run = 0
    if _f in (1, 8, 12, 13, 18, 24, 26, 27, _N):
        print(f"JUMP f{_f}: dz={_dz(_f):+.3f} pitch={_interp(_PITCH, _f):+.1f} tips="
              + " ".join(f"{l}:{z:+.3f}" for l, z in zs.items()) + f" meshMin={mz:+.3f}")
# rest match: frame N vs frame 1
scene.frame_set(1); dg.update(); ae = arm.evaluated_get(dg)
_m1 = {b.name: b.matrix.copy() for b in ae.pose.bones}
scene.frame_set(_N); dg.update(); ae = arm.evaluated_get(dg)
_rest_err = max(max(abs(a - b) for ra, rb in zip(_m1[n], ae.pose.bones[n].matrix) for a, b in zip(ra, rb))
                for n in _m1)
_ok = _air_best >= 3 and _minTip >= -0.02 and _minMesh >= _MESH_MIN and _rest_err < 1e-4
EXTRA_GUARD = (f"{'OK' if _ok else 'FAIL'} airborne={_air_best} minZ={_minTip:+.3f} "
               f"meshMinZ={_minMesh:+.3f} restErr={_rest_err:.1e} crouch={CROUCH_F * HIP_Z:.3f} apex={APEX:.3f} "
               f"bellyLift={_belly_lift:.3f} hover<={_hmax:.3f} splay<={_smax:.3f}")
print("JUMP GUARD:", EXTRA_GUARD)
make_cyclic(EXTRA_ACTION)
