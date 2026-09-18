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
    def __init__(self, tgt, src, bone_map, hips="hips"):
        self.tgt, self.src, self.map = tgt, src, bone_map
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

    def bake(self, src_act, name, loop=False, hit=None):
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
        for f in range(f0, f1 + 1):
            self.scene.frame_set(f)
            Ws = {sb: src.matrix_world @ src.pose.bones[sb].matrix for sb in self.map.values()}
            Wt = {}; pose = {}
            for tb in self.order:
                bone = tgt.data.bones[tb]; Rt = tr[tb]; par = bone.parent.name if bone.parent else None
                rel = (tr[par].inverted() @ Rt) if par else Rt
                base = (Wt[par] @ rel) if par else rel
                if tb in self.map:
                    sb = self.map[tb]; Rw = Ws[sb].to_3x3()
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
                    dy_t = (W.to_3x3() @ Vector((0, 1, 0))).normalized(); dy_s = (Rw @ Vector((0, 1, 0))).normalized()
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
        """A small voxel prop in the weapon slot, sized from the character. Frame: grip at the slot origin,
        length along slot +y, blade edge / axe head along x, thickness along z."""
        slot = self.slots.get(side)
        if not slot: return None
        H = self.H; c = H / 36.0                                   # prop voxel = 1/36 of the height (5 cm at 1.8 m)
        wood, steel, gold, gem, dark = (0.36, 0.22, 0.10, 1), (0.72, 0.74, 0.78, 1), (0.85, 0.65, 0.20, 1), (0.25, 0.55, 1.0, 1), (0.15, 0.15, 0.17, 1)
        cells = {}                                                  # (x, y, z) -> colour, y = along the length
        def box(x0, x1, y0, y1, z0, z1, col):
            for x in range(x0, x1):
                for y in range(y0, y1):
                    for z in range(z0, z1): cells[(x, y, z)] = col
        if kind == "sword":
            box(0, 1, -3, 0, 0, 1, dark); box(-2, 3, 0, 1, 0, 1, gold); box(0, 1, 1, 15, 0, 1, steel); box(0, 1, 15, 16, 0, 1, steel); grip = -3
        elif kind == "axe":
            box(0, 1, -3, 12, 0, 1, wood); box(-3, 1, 9, 13, 0, 1, steel); box(-4, -3, 10, 12, 0, 1, steel); grip = -3
        elif kind == "pickaxe":
            box(0, 1, -3, 12, 0, 1, wood); box(-4, 5, 11, 13, 0, 1, steel); box(-5, -4, 11, 12, 0, 1, steel); box(5, 6, 11, 12, 0, 1, steel); grip = -3
        else:                                                       # staff: held at the middle, orb on top
            box(0, 1, -12, 14, 0, 1, wood); box(-1, 2, 14, 17, -1, 2, gem); grip = -12
        FACE = [((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]), ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
                ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]), ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
                ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]), ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)])]
        verts, vmap, faces, cols = [], {}, [], []
        def vid(k):
            if k not in vmap: vmap[k] = len(verts); verts.append(((k[0] - 0.5) * c, k[1] * c, (k[2] - 0.5) * c))
            return vmap[k]
        for (x, y, z), col in cells.items():
            for (dx, dy, dz), corners in FACE:
                if (x + dx, y + dy, z + dz) in cells: continue
                faces.append(tuple(vid((x + a, y + b, z + d)) for a, b, d in corners)); cols.append(col)
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
