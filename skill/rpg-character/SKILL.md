---
name: rpg-character
description: Create a rigged voxel humanoid with a full RPG animation set (idle/walk/run/jump, sword slash/stab/overhead, two-hand chop, mining, spellcasting, block, hit, death, interact, pick-up, sit) from a one-line idea or an existing mesh/.vox — fal concept + Hunyuan-3D → voxelizer → headless Blender derives the skeleton from the voxel grid and retargets CC0 KayKit clips onto it → glTF with weapon slots and props. Use when asked to make, rig or animate a character, hero, NPC, player avatar, villager, enemy humanoid, or to give a character sword / mining / chopping / magic animations.
---

# RPG character pipeline

One idea ("a dwarf miner") → a rigged voxel humanoid with 33 game-ready clips, weapon slots on both
hands and voxel props (sword, axe, pickaxe, staff), exported as glTF. The animations are not authored per
character: a CC0 humanoid clip library is **retargeted** onto a skeleton that is **derived from the voxel
grid**, so the same command works on a chibi dwarf and a lanky elf. Four stages, each with a gate.

Exactly ONE gate is a manual user pick — present the material, then stop and wait:
  1. concept selection (stage 1): the user picks one of four generated concept images.
Skip stage 1 entirely when the user already has a mesh (`--glb`) or a MagicaVoxel model (`--vox`).

## Layout

```
assets/<Name>/                      (PascalCase name)
  concept/candidate_{1..4}.png      stage 1 + concept_sheet.png + concept.json (fal CDN urls)
  <Name>_mesh.glb                   stage 2: Hunyuan-3D output
  <Name>.vox                        stage 3: 5 cm voxels, standing, facing -Y
  previews/<Name>_vox_{front,side,top}.png     + <Clip>_<i>.png frames with --render
  layout.json, <name>_rules.py      stage 4: derived body plan + exact voxel->bone table
  <Name>_rigged.blend               stage 4: rig, every clip stashed in the NLA
  <Name>_animated.glb               EXPORT: mesh + 19-bone rig + 33 animations + Prop_* meshes on handslotR
  clips.json                        per clip: frames, fps, loop, hit_frame, prop
  report.json, run.log              guards, timings, everything that was run
```

Tools: `tools/pipeline/concept.py --kind humanoid`, `tools/pipeline/run_character.py`, `tools/biped/`
(`bipedrig.py`, `biped_build.py`, `retarget_lib.py`, `maps/`, `presets/`, `anims/kaykit/Knight.glb`).
Requirements: Blender 5.2 LTS (`BLENDER=/path` if not on PATH), the voxelizer built once with CMake,
Python 3.10+ with Pillow, a fal key (`FAL_KEY` or `~/.fal/key`) for stages 1-2 only.

## Stage 1 — concept (fal Seedream)

```
python tools/pipeline/concept.py <Name> --kind humanoid --idea "a stout dwarf miner with a braided beard" \
       --height-m 1.5 --colors "rust beard, brown apron, grey shirt" [--anatomy "..."]
```

The humanoid template asks for a standing A-pose (arms hanging a little away from the body, legs apart,
feet flat), front three-quarter view, chunky cubes, plain background. **Auto QA first:** reject candidates
whose arms touch the torso or each other, whose legs are fused, that hold objects (props come later), or
that crop the feet. **USER PICK (mandatory):** show `concept_sheet.png`, stop, keep the picked CDN url.

## Stages 2-4 — one command

```
python tools/pipeline/run_character.py <Name> --image-url <picked url> --height-m 1.5 --render
```

- **Mesh** — Hunyuan-3D v3.1 (`face_count 100000`, PBR). ~2.5 min, ~$0.68.
- **Voxelize** — the voxelizer cuts the mesh at 5 cm on the vertical axis (`--axis y --long-axis H/0.05`)
  and sweeps the yaw over 0/180/90/270 until the grid stands on two legs, is wider than deep, and the
  toes point -Y. **Check `previews/<Name>_vox_side.png`: toes must point LEFT.** Fix a wrong pick by
  running the voxelizer by hand with `--yaw` and passing `--vox`.
- **Body plan** — `bipedrig.py` reads the grid bottom-up: feet (bottom layers that reach forward), legs
  (lowest band with two blobs either side of the midline, plus a chibi pelvis block), torso split
  1/6 : 1/3 : 1/2 into hips / spine / chest, arms (free-hanging outboard columns, then the merged
  shoulder layers; T-pose bands also work), head (first layer above the shoulder line narrower than the
  trunk), hands (bottom 20% of each arm). It writes bone heads/tails and an exact per-voxel bone table.
- **Rig + retarget** — `biped_build.py` builds the voxel mesh with rigid weights, a 17-bone rig
  (root, hips, spine, chest, head, arm upper/lower/hand x2, leg upper/lower/foot x2), imports the CC0
  KayKit rig, adds `handslotL/R` from the source's own slot offsets, re-rolls every mapped bone into the
  source's frame convention and copies the source's world rotation per frame (see
  [references/retargeting.md](references/retargeting.md)). Hips translation is scaled by leg height;
  feet are clamped to the floor through the hips. Props are voxel meshes from `tools/biped/props/*.py`
  (sword, axe, pickaxe, staff; grip at the slot origin, length along the slot's +y, one cell = height/27),
  bone-parented to `handslotR`. `Chop` carries an additive forward bend (preset `add`) so the axe lands on
  a log at the ground while `Mine` swings at a rock face at chest height.
- **Chunky sleeves** that read as raised arms in Idle (the KayKit idle holds the upper arms ~45° out):
  pass `--relax-arms 20..30` to pull hanging upper arms toward the body; the pull fades out as an arm is
  raised, so attacks are untouched. Check `previews/Idle_0.png` and decide.

**QA gate (numeric, never visual):** every `CLIP` line in `run.log` must end in `OK`:
`dir 0.000 deg` (the target bone points exactly where the source bone points, an identity check on
the maths), no NaNs, hips excursion under 60% of the height, floor fix reported. `clips.json` gives the
loop flag and the **hit frame** of each attack (peak weapon-slot speed) for gameplay events. With
`--render`, `clip_sheet_*.png` are for the *user* to enjoy, not for you to grade a walk by.

## The clip set (presets/rpg_kaykit.json)

Idle · Walk · Run · JumpStart · JumpLoop · JumpLand · SwordIdle · Slash · SlashDiag · Stab · Overhead ·
Chop (axe) · Mine (pickaxe) · Slice2H · Spin · Block · BlockHit · CastRaise · Cast · CastLong · Casting (staff) ·
Punch · Kick · Interact · PickUp · UseItem · Throw · Hit · Death · Cheer · DodgeBack · SitDown · SitIdle.
Add one by adding a line to the preset (any of the 76 source actions listed in
`anims/kaykit/SOURCE.md`). Other sources: `--source your.fbx --map maps/mixamo.json` for Mixamo
downloads (not redistributable — keep them out of repos), `maps/ual.json` for the Quaternius library.

## Stage 5 — use it

`<Name>_animated.glb` imports into Godot / Unity / Unreal / three.js with named animations; the
`Prop_*` nodes are children of `handslotR` — show the one `clips.json` names for the playing clip, or
attach your own item to the slot. For tiny-voxel's rigid-part runtime, bake with the engine's baker
(not in this repo).

## Scope

Standing humanoids with two arms and two legs. Arms may hang or be in T-pose. Capes, tails, wings,
skirts and held objects in the concept confuse the body plan — keep them out of the concept and add them
as props. No facial animation, no fingers (rigid mitten hands carry the slot).
