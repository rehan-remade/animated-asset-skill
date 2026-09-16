# Trot: 2-beat diagonal gait (FL+HR together, FR+HL together), cadence between
# walk and gallop, stance ~0.5, moderate lift, 2x-frequency bob, light pitch,
# bouncing ears, level tail with a light wag.  Exec'd inside generic_quad_build.
TCYC = max(10, int(round(0.7 * CYC)))
STANCE_T = 0.50
PHASE_T = {"FL": 0.00, "HR": 0.00, "FR": 0.50, "HL": 0.50}
STRIDE_T = {"F": 0.085 * K, "H": 0.090 * K}          # between walk (0.075K) and gallop (0.10-0.11K)
STEP_T = {"F": 1.3 * STEP_H_F, "H": 1.3 * STEP_H_H}   # moderate lift
BOB_T = 0.007 * K                                     # 2 beats per cycle
SURGE_T = 0.005 * K
PITCH_T = 3.0           # deg, slight nose-up/down at 2x cycle frequency (zero at the footfalls)
ROLL_T = 1.5            # deg, trots have little roll
HEAD_NOD_T = 2.0        # deg, head counter-nod
EAR_BOUNCE_T = 9.0      # deg, ears trail the bob
TAIL_WAG_T = 6.0        # deg
TROT_KNEE = True        # 2-bone IK on every creature: the trot must show a real lift/tuck
# reach geometry: at touchdown the foot is half a stride ahead of its root, so a
# 2-bone leg of length HIP_Z only reaches the ground if the body sits lower by
# REACH_T; the base drop covers that plus the bob peak so no foot floats at contact.
REACH_T = HIP_Z - math.sqrt(HIP_Z * HIP_Z - (0.5 * STRIDE_T["H"]) ** 2)
BODY_DROP_T = BOB_T + 0.6 * REACH_T
# pitch pivot compensation: hips_rx rotates about the hips bone head (0.33 L); a
# dz term makes the pitch effectively rotate about the midpoint of the leg roots
# so a long body (Hippo: 1.4 m lever) does not lift its front feet off the ground.
_PIV_Y = BONES["hips"][0][1]
_MID_Y = 0.5 * (LEG_Y["F"] + LEG_Y["H"])
PITCH_LEVER_T = _PIV_Y - _MID_Y


def trot_channels(t):
    # body lowest at mid-stance (t=0.25, 0.75), highest at the diagonal swap
    bob = -BOB_T * math.cos(4 * math.pi * (t - 0.25))
    surge = SURGE_T * math.sin(4 * math.pi * t + 0.9)
    roll = ROLL_T * math.sin(2 * math.pi * t)
    nose_up = PITCH_T * math.sin(4 * math.pi * t)          # zero at every footfall
    pitch_dz = -PITCH_LEVER_T * math.sin(math.radians(nose_up))
    return {"dy": -surge, "dz": -BODY_DROP_T + bob + pitch_dz,
            "hips_rx": -HP_D * nose_up, "hips_ry": roll,
            "chest_rx": C_D * 0.4 * nose_up, "chest_ry": -roll * 0.5,
            "head_rx": H_D * HEAD_NOD_T * math.sin(4 * math.pi * t),   # counter-nod
            "head_ry": 0.0,
            "ear": -E_F * EAR_BOUNCE_T * math.cos(4 * math.pi * (t - 0.25) + 0.6),
            "tail_rx": T_U * 1.5,
            "tail_rz": T_Y * TAIL_WAG_T * math.sin(2 * math.pi * t)}


def trot_foot(leg, t):
    return foot_traj((t + PHASE_T[leg]) % 1.0, STRIDE_T[leg[0]], STEP_T[leg[0]],
                     stance=STANCE_T, peel=0.18, peelh=PEEL_H, sharp=0.72)


def key_trot_frame(f, phi):
    c = trot_channels(phi)
    key_hips_world(f, c["dy"], c["dz"])
    key_rot("hips", f, (c["hips_rx"], c["hips_ry"], 0))
    key_rot("chest", f, (c["chest_rx"], c["chest_ry"], 0))
    key_rot("head", f, (c["head_rx"], c["head_ry"], 0))
    key_rot("earL", f, (c["ear"], 0, 0))
    key_rot("earR", f, (c["ear"], 0, 0))
    key_rot("tail", f, (c["tail_rx"], 0, c["tail_rz"]))
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for leg in LEGS:
        par = pb["chest" if leg[0] == "F" else "hips"]
        M = par.matrix @ par.bone.matrix_local.inverted()
        root = arm.matrix_world @ (M @ Vector(BONES[f"{leg}.upper"][0]))
        v = M.to_3x3() @ Vector((0, 0, -1))
        delta = math.atan2(-v.y, -v.z)
        fdx, zf = trot_foot(leg, phi)
        dx = fdx + (root.y - LEG_Y[leg[0]])
        ux, lx = solve_leg(dx, zf, leg, root.z, delta, knee=TROT_KNEE)
        key_rot(f"{leg}.upper", f, (ux, 0, 0))
        key_rot(f"{leg}.lower", f, (lx, 0, 0))


EXTRA_ACTION = new_action("Trot")
EXTRA_LENGTH = TCYC
for _f in range(1, TCYC + 2):
    key_trot_frame(_f, ((_f - 1) % TCYC) / TCYC)
make_cyclic(EXTRA_ACTION)

# ---- guard: planted paws sweep +Y (tailward) and touch the ground; body clear of the floor
_dg = bpy.context.evaluated_depsgraph_get()
_ok = True
_parts = []
_body_idx = None
for _leg in ("FL", "HL"):
    _ys, _zmin, _zmax_st = [], 9.9, -9.9
    for _f in range(1, TCYC + 1):
        _p = (((_f - 1) / TCYC) + PHASE_T[_leg]) % 1.0
        scene.frame_set(_f)
        _dg.update()
        _ae = arm.evaluated_get(_dg)
        _tip = _ae.matrix_world @ _ae.pose.bones[f"{_leg}.lower"].tail
        _zmin = min(_zmin, _tip.z)
        if _p < STANCE_T * 0.9:
            _ys.append((_p, _tip.y))
            _zmax_st = max(_zmax_st, _tip.z)
    _ys.sort()
    if _ys[-1][1] <= _ys[0][1] or _zmin > 0.06 or _zmin < -0.02:
        _ok = False
    _parts.append(f"{_leg} sweep {_ys[0][1]:+.3f}->{_ys[-1][1]:+.3f} minZ={_zmin:.3f} stanceMaxZ={_zmax_st:.3f}")
    print(f"TROT GUARD {_leg}: sweep {_ys[0][1]:+.3f}->{_ys[-1][1]:+.3f} minZ={_zmin:.3f} stanceMaxZ={_zmax_st:.3f}")

# diagonal timing + floor clearance of the whole mesh (body verts and paw verts separately)
_body_groups = {obj.vertex_groups[n].index for n in ("hips", "chest", "head", "earL", "earR", "tail") if n in obj.vertex_groups}
_body_idx = [v.index for v in obj.data.vertices if any(g.group in _body_groups for g in v.groups)]
_counts, _body_min, _mesh_min = [], 9.9, 9.9
for _f in range(1, TCYC + 1):
    scene.frame_set(_f)
    _dg.update()
    _ae = arm.evaluated_get(_dg)
    _zs = {l: (_ae.matrix_world @ _ae.pose.bones[f"{l}.lower"].tail).z for l in LEGS}
    _counts.append(sum(1 for l in LEGS if _zs[l] < 0.02))
    _oe = obj.evaluated_get(_dg)
    _mw = _oe.matrix_world
    _vs = _oe.data.vertices
    _mesh_min = min(_mesh_min, min((_mw @ v.co).z for v in _vs))
    _body_min = min(_body_min, min((_mw @ _vs[i].co).z for i in _body_idx))
if _body_min < -0.01:
    _ok = False
print("TROT grounded paws/frame:", _counts, f"| bodyMinZ={_body_min:.3f} meshMinZ={_mesh_min:.3f}")
_tv = STRIDE_T["H"] / (STANCE_T * TCYC / FPS)
print(f"TROT ref speed: {_tv:.3f} m/s -> trot_ref_speed = {_tv*10:.2f} voxels/s")
EXTRA_GUARD = (("OK forward+grounded" if _ok else "FAIL") + " | " + " | ".join(_parts)
               + f" | bodyMinZ={_body_min:.3f} meshMinZ={_mesh_min:.3f} | cyc={TCYC}f drop={BODY_DROP_T:.3f} grounded/frame={_counts}")
