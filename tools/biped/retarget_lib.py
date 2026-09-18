"""Retarget humanoid clips from a source armature (glTF/FBX) onto a voxel biped rig. Runs inside Blender.

Method (proven on tiny-voxel's Player rig, 2026-09-18):
  1. add any target bones the map names but the rig lacks (hands, weapon slots), placed from the source's local offsets
  2. re-roll every mapped target bone so its rest frame == the source bone's rest frame up to the minimal rotation
     between the two bone directions (Align) — after this a pure world-rotation copy is exact, roll included
  3. per frame: W_target = W_source for every mapped bone (hips also copy translation, scaled by leg height)
  4. guards: direction identity (|angle| < 0.5 deg), NaNs, hips excursion, feet-below-floor clamp, loop closure
"""
import bpy, math, json
from mathutils import Matrix, Vector


def import_source(path):
    before = set(bpy.data.objects); acts_before = set(bpy.data.actions)
    if path.lower().endswith((".glb", ".gltf")): bpy.ops.import_scene.gltf(filepath=path)
    elif path.lower().endswith(".fbx"): bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=False, ignore_leaf_bones=True)
    else: raise SystemExit("source must be .glb/.gltf/.fbx: " + path)
    new = [o for o in bpy.data.objects if o not in before]
    src = next(o for o in new if o.type == "ARMATURE")
    meshes = [o for o in new if o.type == "MESH"]
    acts = {}
    for a in bpy.data.actions:
        if a not in acts_before:
            acts[a.name] = a; a.name = "SRC_" + a.name
    return src, meshes, acts


def facing_fix(src, bone_map):
    """Sources must face -Y like the target. Uses the foot bone direction (toes point forward)."""
    foot = next((s for t, s in bone_map.items() if t.lower().startswith("foot") and s and s in src.data.bones), None)
    if not foot: return False
    b = src.data.bones[foot]; d = (src.matrix_world.to_3x3() @ (b.tail_local - b.head_local))
    if d.y > abs(d.x) * 0.5 and d.y > 0:
        src.matrix_world = Matrix.Rotation(math.pi, 4, "Z") @ src.matrix_world
        bpy.context.view_layer.update(); return True
    return False


def prepare_target(tgt, src, bone_map):
    """Add missing bones, re-roll mapped bones. Returns the (possibly pruned) map: target bone -> source bone."""
    bone_map = {t: s for t, s in bone_map.items() if not t.startswith("_")}
    missing_src = [s for s in bone_map.values() if s and s not in src.data.bones]
    if missing_src: print("MAP WARNING: source lacks", missing_src)
    src_rest = {b.name: (src.matrix_world @ b.matrix_local) for b in src.data.bones}
    bpy.context.view_layer.objects.active = tgt
    bpy.ops.object.mode_set(mode="EDIT")
    eb = tgt.data.edit_bones

    def reroll(tb, sb):
        b = eb[tb]; d_t = (b.tail - b.head).normalized()
        Rs = src_rest[sb].to_3x3(); d_s = (Rs @ Vector((0, 1, 0))).normalized()
        A = d_t.rotation_difference(d_s).to_matrix()
        M = (A.inverted() @ Rs).to_4x4(); M.translation = b.head.copy(); L = b.length
        b.matrix = tgt.matrix_world.inverted() @ M; b.length = L

    def mapped_ancestor(sb):
        p = src.data.bones[sb].parent
        while p is not None:
            for t, s in bone_map.items():
                if s == p.name and t in eb: return t, p.name
            p = p.parent
        raise RuntimeError("no mapped ancestor for " + sb)

    for tb, sb in bone_map.items():
        if tb in eb and sb and sb in src.data.bones: reroll(tb, sb)
    added = []
    for tb, sb in list(bone_map.items()):
        if tb in eb: continue
        if not sb or sb not in src.data.bones:
            # no source bone (e.g. Mixamo has no weapon slot): a default slot at the parent's tail, same frame
            parent_t = tb.replace("slot", "")            # handslotR -> handR
            if parent_t not in eb: print("SKIP", tb, "(no source bone and no parent)"); bone_map.pop(tb); continue
            pe = eb[parent_t]; b = eb.new(tb); b.parent = pe
            b.head = pe.tail.copy(); b.tail = pe.tail + (pe.tail - pe.head).normalized() * 0.05; b.roll = pe.roll
            bone_map.pop(tb); added.append(tb); continue
        pt, ps = mapped_ancestor(sb); pe = eb[pt]
        Rp_t = (tgt.matrix_world @ pe.matrix).to_3x3(); Rp_s = src_rest[ps].to_3x3()
        ratio = pe.length / max(src.data.bones[ps].length, 1e-4)
        d_t = (Rp_t @ (Rp_s.inverted() @ (src_rest[sb].to_3x3() @ Vector((0, 1, 0))))).normalized()
        b = eb.new(tb); b.parent = pe
        if src.data.bones[sb].parent.name == ps:            # direct child: keep the source's local offset, scaled
            off_local = Rp_s.inverted() @ (src_rest[sb].translation - src_rest[ps].translation)
            b.head = tgt.matrix_world.inverted() @ ((tgt.matrix_world @ pe.head) + Rp_t @ (off_local * ratio))
        else:                                               # a wrist etc. was skipped: chain onto the parent's tail
            b.head = pe.tail.copy()
        b.tail = b.head + d_t * max(0.03, src.data.bones[sb].length * ratio)
        reroll(tb, sb); added.append(tb)
    bpy.ops.object.mode_set(mode="POSE")
    for pb in tgt.pose.bones:
        pb.rotation_mode = "QUATERNION"; pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.scale = (1, 1, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    if added: print("ADDED BONES", added)
    return bone_map


class Retargeter:
    def __init__(self, tgt, src, bone_map, hips="hips", relax_arms_deg=0.0):
        self.tgt, self.src, self.map = tgt, src, bone_map
        self.relax = math.radians(relax_arms_deg)                  # pull hanging upper arms toward the body (chunky sleeves)
        self.src_rest = {b.name: (src.matrix_world @ b.matrix_local) for b in src.data.bones}
        self.tgt_rest = {b.name: (tgt.matrix_world @ b.matrix_local) for b in tgt.data.bones}
        self.order = []
        def walk(b):
            self.order.append(b.name); [walk(c) for c in b.children]
        [walk(b) for b in tgt.data.bones if b.parent is None]
        self.hips = hips
        leg_t = next(t for t in bone_map if "leg" in t.lower() and "upper" in t.lower())
        self.hscale = self.tgt_rest[leg_t].translation.z / max(self.src_rest[bone_map[leg_t]].translation.z, 1e-4)
        self.feet = [t for t in tgt.data.bones.keys() if t.lower().startswith(("foot", "toe"))]
        self.slots = {s: t for t in tgt.data.bones.keys() for s in ("R", "L") if t.lower() == f"handslot{s}".lower()}
        self.ad = tgt.animation_data or tgt.animation_data_create()
        self.scene = bpy.context.scene
        self.H = max((o.dimensions.z for o in bpy.data.objects if o.type == "MESH" and o.find_armature() == tgt), default=1.8)

    def bake(self, src_act, name, loop=False, hit=None, add=None):
        """add = {"pitch_deg": {"spine": 25, "chest": 15}, "window": [0.15, 0.85]} bends those bones forward
        (about the world lateral axis) with a smooth envelope over that fraction of the clip — e.g. a chop
        aimed at a log on the ground instead of a rock at chest height."""
        src_ad = self.src.animation_data or self.src.animation_data_create()
        src_ad.action = src_act
        if src_act.slots: src_ad.action_slot = src_act.slots[0]
        f0, f1 = int(round(src_act.frame_range[0])), int(round(src_act.frame_range[1]))
        if f1 <= f0: f1 = f0 + 1
        act = bpy.data.actions.new(name); slot = act.slots.new(id_type="OBJECT", name=self.tgt.name)
        self.ad.action = act; self.ad.action_slot = slot
        nan = 0; maxdir = 0.0; minfoot = 9.0; hips_ex = 0.0; floor_fix = 0.0
        first_pose = None; last_pose = None; slot_track = []
        tgt, src, tr, sr = self.tgt, self.src, self.tgt_rest, self.src_rest
        pitch = (add or {}).get("pitch_deg", {}); w0, w1 = (add or {}).get("window", [0.0, 1.0])
        def envelope(f):
            u = (f - f0) / max(f1 - f0, 1)
            if u <= w0 or u >= w1: return 0.0
            t = (u - w0) / (w1 - w0); return math.sin(math.pi * t) ** 2          # smooth in / out, peak mid-window
        for f in range(f0, f1 + 1):
            self.scene.frame_set(f)
            env = envelope(f) if pitch else 0.0
            Ws = {sb: src.matrix_world @ src.pose.bones[sb].matrix for sb in self.map.values()}
            Wt = {}; pose = {}
            for tb in self.order:
                bone = tgt.data.bones[tb]; Rt = tr[tb]; par = bone.parent.name if bone.parent else None
                rel = (tr[par].inverted() @ Rt) if par else Rt
                base = (Wt[par] @ rel) if par else rel
                if tb in self.map:
                    sb = self.map[tb]; Rw = Ws[sb].to_3x3()
                    if env and tb in pitch:                          # forward bend about the world lateral axis
                        Rw = Matrix.Rotation(math.radians(pitch[tb]) * env, 3, "X") @ Rw
                    if self.relax and tb.lower().startswith("arm") and "upper" in tb.lower():
                        d = (Rw @ Vector((0, 1, 0))).normalized()    # only while the arm hangs (not raised / forward)
                        k = max(0.0, -d.z) ** 2
                        if k > 0:                                    # right arm sits at -x: rotate about world Y toward the body
                            side = -1.0 if d.x < 0 else 1.0
                            Rw = Matrix.Rotation(-side * self.relax * k, 3, "Y") @ Rw
                    W = Rw.to_4x4(); W.translation = base.translation
                    if tb == self.hips:
                        W.translation = Rt.translation + (Ws[sb].translation - sr[sb].translation) * self.hscale
                    Wt[tb] = W
                    basis = base.inverted() @ W; q = basis.to_quaternion()
                    if any(math.isnan(c) for c in q): nan += 1; continue
                    pb = tgt.pose.bones[tb]; pb.rotation_quaternion = q; pb.keyframe_insert("rotation_quaternion", frame=f)
                    pose[tb] = q.copy()
                    if tb == self.hips:
                        pb.location = basis.translation; pb.keyframe_insert("location", frame=f)
                        hips_ex = max(hips_ex, (W.translation - Rt.translation).length)
                    dy_t = (W.to_3x3() @ Vector((0, 1, 0))).normalized(); dy_s = (Rw @ Vector((0, 1, 0))).normalized()   # Rw includes any additive bend
                    maxdir = max(maxdir, math.degrees(dy_t.angle(dy_s, 0.0)))
                else:
                    Wt[tb] = base
            if hit and hit in self.slots: slot_track.append(Wt[self.slots[hit]].translation.copy())
            fz = min(min(Wt[t].translation.z, (Wt[t] @ Vector((0, tgt.data.bones[t].length, 0))).z) for t in self.feet) if self.feet else 0.0
            minfoot = min(minfoot, fz)
            if fz < -0.005:                                   # per-frame floor clamp through the hips
                pb = tgt.pose.bones[self.hips]; par = tgt.data.bones[self.hips].parent.name
                base = Wt[par] @ (tr[par].inverted() @ tr[self.hips])
                pb.location += base.to_3x3().inverted() @ Vector((0, 0, -fz)); pb.keyframe_insert("location", frame=f)
                floor_fix = max(floor_fix, -fz)
            if first_pose is None: first_pose = pose
            last_pose = pose
        loop_gap = max((math.degrees(first_pose[b].rotation_difference(last_pose[b]).angle) for b in first_pose if b in last_pose), default=0.0)
        hit_frame = None
        if len(slot_track) > 2:
            speeds = [(slot_track[i + 1] - slot_track[i - 1]).length for i in range(1, len(slot_track) - 1)]
            hit_frame = f0 + 1 + max(range(len(speeds)), key=speeds.__getitem__)
        track = self.ad.nla_tracks.new(); track.name = name
        strip = track.strips.new(name, f0, act); strip.action_slot = slot; track.mute = True
        self.ad.action = None
        ok = nan == 0 and maxdir < 0.5 and hips_ex < 0.6 * self.H
        info = dict(src=src_act.name[4:] if src_act.name.startswith("SRC_") else src_act.name, frames=f1 - f0, fps=self.scene.render.fps,
                    loop=loop, loop_gap_deg=round(loop_gap, 1), hit_frame=hit_frame, nan=nan, dir_err_deg=round(maxdir, 3),
                    min_foot_z=round(minfoot, 3), floor_fix_m=round(floor_fix, 3), hips_excursion_m=round(hips_ex, 3), ok=ok)
        print("CLIP %-10s %3d fr | dir %.3f deg | foot %+.3f (fix %.3f) | hips %.3f | %s%s%s" % (
            name, f1 - f0, maxdir, minfoot, floor_fix, hips_ex, "loop gap %.0f deg | " % loop_gap if loop else "",
            "hit f%d | " % hit_frame if hit_frame else "", "OK" if ok else "FAIL"))
        return info

    def add_prop_box(self, side="R", kind="sword"):
        """A voxel prop in the weapon slot, from tools/biped/props/<kind>.py (grip at the slot origin, length along
        the slot's +y, head/edge along x), scaled to the character: one prop cell = height / 27."""
        slot = self.slots.get(side)
        if not slot: return None
        import importlib.util, os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "props", kind + ".py")
        if os.path.exists(path):
            sp = importlib.util.spec_from_file_location("prop_" + kind, path); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
            cells = {k: tuple(v) for k, v in m.CELLS.items()}; anchor = Vector(getattr(m, "ANCHOR", (0, 0, 0)))
        else:                                                       # fallback: a plain box
            cells = {(x, y, 0): (190, 195, 205) for x in range(-1, 1) for y in range(-3, 16)}; anchor = Vector((0, 0, 0))
        c = self.H / 27.0
        FACE = [((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]), ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
                ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]), ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
                ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]), ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)])]
        lin = lambda v: (v / 255) / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4
        verts, vmap, faces, cols = [], {}, [], []
        def vid(k):
            if k not in vmap: vmap[k] = len(verts); verts.append(tuple((Vector(k) - anchor) * c))
            return vmap[k]
        for (x, y, z), col in cells.items():
            for (dx, dy, dz), corners in FACE:
                if (x + dx, y + dy, z + dz) in cells: continue
                faces.append(tuple(vid((x + a, y + b, z + d)) for a, b, d in corners)); cols.append((lin(col[0]), lin(col[1]), lin(col[2]), 1))
        me = bpy.data.meshes.new(f"Prop_{kind}"); me.from_pydata(verts, [], faces); me.update()
        ca = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="CORNER"); li = 0
        for poly, col in zip(me.polygons, cols):
            for _ in range(poly.loop_total): ca.data[li].color = col; li += 1
        mat = bpy.data.materials.new(f"Prop_{kind}"); mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]; vc = mat.node_tree.nodes.new("ShaderNodeVertexColor"); vc.layer_name = "Col"
        mat.node_tree.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"]); me.materials.append(mat)
        prop = bpy.data.objects.new(f"Prop_{kind}", me); bpy.context.collection.objects.link(prop)
        return self.attach(prop, side, along=0.0)

    def attach(self, obj, side, along=0.0):
        slot = self.slots[side]; Lb = self.tgt.data.bones[slot].length
        obj.parent = self.tgt; obj.parent_type = "BONE"; obj.parent_bone = slot
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.location = (0, along - Lb, 0); obj.rotation_euler = (0, 0, 0)   # grip at slot origin, length along slot +y
        return obj


def cleanup_source(src, meshes, acts):
    for o in meshes + [src]: bpy.data.objects.remove(o, do_unlink=True)
    for a in list(bpy.data.actions):
        if a.name.startswith("SRC_"): bpy.data.actions.remove(a)
