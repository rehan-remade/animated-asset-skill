"""Build a rigged voxel biped from a .vox + derived layout, retarget a clip preset onto it, export glTF. Headless.

blender -b --factory-startup --python biped_build.py -- <model.vox> <outdir> --layout layout.json --rules <name>_rules.py \
    --name Name --source anims/kaykit/Knight.glb --map maps/kaykit.json --preset presets/rpg_kaykit.json \
    [--only Idle,Slash] [--no-props] [--render [--frames 6]] [--no-export]

Outputs: <Name>_rigged.blend, <Name>_animated.glb (every clip as a glTF animation + prop meshes on the weapon slot),
clips.json (loop / hit frame / prop per clip), report.json (guards), previews/<Clip>_<i>.png when --render.
"""
import bpy, sys, os, json, struct, importlib.util
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget_lib as rt

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(k, d=None): return argv[argv.index(k) + 1] if k in argv else d
VOX, OUT = argv[0], argv[1]
LAYOUT = json.load(open(arg("--layout")))
NAME = arg("--name", os.path.splitext(os.path.basename(VOX))[0])
SOURCE, MAP, PRESET = arg("--source"), arg("--map"), arg("--preset")
ONLY = set(arg("--only", "").split(",")) - {""}
PROPS, RENDER, EXPORT = "--no-props" not in argv, "--render" in argv, "--no-export" not in argv
FRAMES = int(arg("--frames", "6"))                       # preview frames per clip with --render
os.makedirs(OUT, exist_ok=True)
for _o in list(bpy.data.objects): bpy.data.objects.remove(_o, do_unlink=True)     # factory Cube/Light/Camera
spec = importlib.util.spec_from_file_location("rules", arg("--rules")); rules = importlib.util.module_from_spec(spec); spec.loader.exec_module(rules)

# ---- voxels -> mesh with per-face colour and bone -----------------------------------------------
def load_vox(path):
    buf = open(path, "rb").read(); off, size, vox, pal = 8, None, [], None
    while off < len(buf):
        cid = buf[off:off + 4]; content, children = struct.unpack_from("<ii", buf, off + 4); off += 12; c = off
        if cid == b"SIZE": size = struct.unpack_from("<iii", buf, c)
        elif cid == b"XYZI":
            n, = struct.unpack_from("<i", buf, c); vox = [struct.unpack_from("<4B", buf, c + 4 + i * 4) for i in range(n)]
        elif cid == b"RGBA": pal = [struct.unpack_from("<4B", buf, c + i * 4) for i in range(256)]
        off = c + content
        if cid != b"MAIN": off += children
    return size, vox, pal

def lin(c): c /= 255.0; return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

size, voxels, palette = load_vox(VOX)
X, Y, Z = size; S = LAYOUT["S"]; z0 = LAYOUT["bands"]["feet"][0]
CX, CY = X / 2.0, Y / 2.0
P = lambda v: Vector(((v[0] - CX) * S, (v[1] - CY) * S, (v[2] - z0) * S))   # voxel units -> metres, feet on the floor
occ = {(x, y, z): ci for x, y, z, ci in voxels}
FACE_DIRS = [((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]), ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
             ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]), ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
             ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]), ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)])]
verts, vmap, faces, face_bone, face_col = [], {}, [], [], []
def vidx(px, py, pz):
    k = (px, py, pz)
    if k not in vmap: vmap[k] = len(verts); verts.append(tuple(P(k)))
    return vmap[k]
for (x, y, z), ci in occ.items():
    bone = rules.bone_for_voxel(x, y, z)
    r, g, b, a = palette[ci - 1] if palette else (200, 200, 200, 255)
    for (dx, dy, dz), corners in FACE_DIRS:
        if (x + dx, y + dy, z + dz) in occ: continue
        faces.append(tuple(vidx(x + cx_, y + cy_, z + cz_) for cx_, cy_, cz_ in corners)); face_bone.append(bone); face_col.append((lin(r), lin(g), lin(b), 1.0))
mesh = bpy.data.meshes.new(NAME); mesh.from_pydata(verts, [], faces); mesh.update()
ca = mesh.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="CORNER"); li = 0
for poly, col in zip(mesh.polygons, face_col):
    for _ in range(poly.loop_total): ca.data[li].color = col; li += 1
obj = bpy.data.objects.new(NAME, mesh); bpy.context.collection.objects.link(obj)
mat = bpy.data.materials.new(NAME + "Vox"); mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]; vc = mat.node_tree.nodes.new("ShaderNodeVertexColor"); vc.layer_name = "Col"
mat.node_tree.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"]); bsdf.inputs["Roughness"].default_value = 0.85; mesh.materials.append(mat)

# ---- armature from the layout ---------------------------------------------------------------------
BONE_ORDER = ["hips", "spine", "chest", "head", "armL.upper", "armR.upper", "armL.lower", "armR.lower", "handL", "handR",
              "legL.upper", "legR.upper", "legL.lower", "legR.lower", "footL", "footR"]
PARENT = {"hips": "root", "spine": "hips", "chest": "spine", "head": "chest", "armL.upper": "chest", "armR.upper": "chest",
          "armL.lower": "armL.upper", "armR.lower": "armR.upper", "handL": "armL.lower", "handR": "armR.lower",
          "legL.upper": "hips", "legR.upper": "hips", "legL.lower": "legL.upper", "legR.lower": "legR.upper", "footL": "legL.lower", "footR": "legR.lower"}
H = LAYOUT["height_m"]
arm_data = bpy.data.armatures.new(NAME + "Rig"); arm = bpy.data.objects.new(NAME + "Rig", arm_data); bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm; bpy.ops.object.mode_set(mode="EDIT"); ebs = arm_data.edit_bones
root = ebs.new("root"); root.head, root.tail = Vector((0, 0.08 * H, 0)), Vector((0, -0.14 * H, 0))
for name in BONE_ORDER:
    b = ebs.new(name); spec_b = LAYOUT["bones"][name]
    b.head, b.tail = P(spec_b["head"]), P(spec_b["tail"]); b.parent = ebs[PARENT[name]]
    b.use_connect = name.endswith(".lower") or name.startswith("hand") or name.startswith("foot") or name in ("spine", "chest", "head")
bpy.ops.object.mode_set(mode="OBJECT")

# ---- rigid weights, parents first so shared boundary verts stay body-side --------------------------
vgroups = {n: obj.vertex_groups.new(name=n) for n in BONE_ORDER}; claimed = set(); by_bone = {n: [] for n in BONE_ORDER}
for f_i, poly in enumerate(mesh.polygons): by_bone[face_bone[f_i]].extend(poly.vertices)
for name in BONE_ORDER:
    fresh = [v for v in set(by_bone[name]) if v not in claimed]
    if fresh: vgroups[name].add(fresh, 1.0, "REPLACE"); claimed.update(fresh)
obj.parent = arm; mod = obj.modifiers.new("Armature", "ARMATURE"); mod.object = arm
scene = bpy.context.scene; scene.render.fps = 24
print("RIG %s: %d voxels, %d verts, %d bones, height %.2f m, S=%.4f" % (NAME, len(occ), len(verts), len(arm_data.bones), obj.dimensions.z, S))

report = {"name": NAME, "vox": os.path.abspath(VOX), "voxels": len(occ), "height_m": round(obj.dimensions.z, 3), "bones": len(arm_data.bones), "clips": {}}
clips_out = {}
if SOURCE:
    src, src_meshes, src_acts = rt.import_source(SOURCE)
    bone_map = json.load(open(MAP))
    if rt.facing_fix(src, bone_map): print("SOURCE FACING flipped 180 deg to face -Y")
    bone_map = rt.prepare_target(arm, src, bone_map)
    R = rt.Retargeter(arm, src, bone_map)
    preset = {k: v for k, v in json.load(open(PRESET)).items() if not k.startswith("_")}
    for name, spec_c in preset.items():
        if ONLY and name not in ONLY: continue
        if spec_c["src"] not in src_acts: print("MISSING source clip", spec_c["src"], "for", name); continue
        info = R.bake(src_acts[spec_c["src"]], name, loop=spec_c.get("loop", False), hit=spec_c.get("hit"))
        info["prop"] = spec_c.get("prop"); report["clips"][name] = info
        clips_out[name] = {k: info[k] for k in ("frames", "fps", "loop", "hit_frame", "prop")}
    props = {}
    if PROPS and R.slots:
        for kind in sorted({v.get("prop") for v in preset.values() if v.get("prop")}):
            p = R.add_prop_box("R", kind)
            if p: props[kind] = p
        print("PROPS", list(props))
    report["hscale"] = round(R.hscale, 3); report["slots"] = R.slots
    rt.cleanup_source(src, src_meshes, src_acts)

json.dump(clips_out, open(os.path.join(OUT, "clips.json"), "w"), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f"{NAME}_rigged.blend"))
if EXPORT:
    bpy.ops.object.select_all(action="DESELECT")
    for o in [arm, obj] + [o for o in bpy.data.objects if o.name.startswith("Prop_")]: o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, f"{NAME}_animated.glb"), export_format="GLB", use_selection=True,
                              export_animations=True, export_animation_mode="ACTIONS")
    print("EXPORTED", os.path.join(OUT, f"{NAME}_animated.glb"))
if RENDER and report["clips"]:
    scene.render.engine = "BLENDER_WORKBENCH"; scene.display.shading.light = "STUDIO"; scene.display.shading.color_type = "VERTEX"; scene.display.shading.show_shadows = True
    scene.render.resolution_x = scene.render.resolution_y = 360; scene.render.image_settings.file_format = "PNG"
    if scene.world is None: scene.world = bpy.data.worlds.new("W")
    scene.world.color = (0.16, 0.16, 0.18)
    bpy.ops.mesh.primitive_plane_add(size=6 * H, location=(0, 0, -0.002)); floor = bpy.context.object; floor.name = "PreviewFloor"
    fm = bpy.data.materials.new("Floor"); fm.diffuse_color = (0.30, 0.30, 0.33, 1); floor.data.materials.append(fm)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam")); scene.collection.objects.link(cam); scene.camera = cam
    cam.location = Vector((1.5, -1.5, 0.75)) * H; aim = Vector((0, 0, 0.47 * H))
    cam.rotation_euler = (aim - cam.location).to_track_quat("-Z", "Y").to_euler(); cam.data.lens = 40
    ad = arm.animation_data; prop_objs = {o.name[5:]: o for o in bpy.data.objects if o.name.startswith("Prop_")}
    for name, info in report["clips"].items():
        act = bpy.data.actions[name]; ad.action = act; ad.action_slot = act.slots[0]
        for k, o in prop_objs.items(): o.hide_render = (k != info.get("prop"))
        f0 = 1; f1 = f0 + info["frames"]; n = FRAMES
        for i in range(n):
            scene.frame_set(round(f0 + (f1 - f0) * i / (n - 1)))
            scene.render.filepath = os.path.join(OUT, "previews", f"{name}_{i}.png"); bpy.ops.render.render(write_still=True)
    ad.action = None
json.dump(report, open(os.path.join(OUT, "report.json"), "w"), indent=1)
print("DONE", len(report["clips"]), "clips,", sum(1 for v in report["clips"].values() if v["ok"]), "ok")
