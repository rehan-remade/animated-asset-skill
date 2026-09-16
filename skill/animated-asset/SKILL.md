---
name: animated-asset
description: Create a fully rigged, animated voxel creature from a one-line idea — fal text-to-image → Hunyuan-3D → C++ voxelizer → headless Blender rig + 13 animation clips → glTF. Use when asked to add, generate or create a new creature, animal, animated asset or voxel model (e.g. "add a corgi", "make a wolf", "generate a new animal").
---

# Animated asset pipeline

Turns a one-line idea ("a cheerful corgi") into a rigged voxel creature with 13 animation
clips, exported as glTF. Four stages, each with a QA gate. Run them in order; never skip a
gate — a bad early artifact wastes every later stage.

Exactly ONE gate is a manual user pick — present the material, then stop and wait:
  1. concept selection (stage 1): the user picks one of four generated concept images.
Every other gate is automated; ask the user only when one fails twice in a row.

## Layout

```
assets/<Name>/                      (PascalCase name, e.g. Corgi)
  concept/candidate_{1..4}.png      stage 1 candidates + concept_sheet.png + concept.json (CDN urls)
  <Name>_mesh.glb                   stage 2: Hunyuan-3D output
  <Name>.vox                        stage 3: MagicaVoxel voxels, 5 cm cells, facing -Y
  previews/<Name>_vox_{front,side,top}.png
  layout.json, <name>_rules.py      stage 4: derived body plan + voxel->bone rules
  <Name>_rigged.blend               stage 4: the rig, all clips stashed in the NLA
  <Name>_animated.glb               stage 4: EXPORT — every clip as a glTF animation
  report.json, run.log              guards, timings, everything that was run
```

Tools live in this repo: `tools/pipeline/concept.py`, `tools/pipeline/run_creature.py`,
`tools/voxelizer/` (build once with CMake), `tools/rig/` (Blender scripts + clip modules).
Requirements: Blender 5.2 LTS on PATH (or `BLENDER=/path`), a fal API key (`FAL_KEY` or
`~/.fal/key`), Python 3.10+ with Pillow for the contact sheets.

## Stage 1 — concept image (fal text-to-image)

Model: `bytedance/seedream/v5/pro/text-to-image`. Use the `fal-ai` MCP tools (`run_model` /
`submit_job` + `check_job`) when that server is connected; otherwise run

```
python tools/pipeline/concept.py <Name> --idea "a cheerful corgi" --len-m 0.9 \
       --anatomy "<2-3 sentences of BLOCKY anatomy>" --colors "<flat colour regions>"
```

Prompt rules (the template is in `concept.py` and [references/fal-generation.md](references/fal-generation.md)):
depict the animal AS voxel art ("large chunky visible cubes, MagicaVoxel style, roughly N cubes
long"), side three-quarter view, legs clearly separated from each other and the ground, plain
light-grey background, whole model in frame. Thin parts (tails, whiskers, antler tines) must be
thickened into slabs or omitted — they shred at 5 cm. `--len-m` is the real-world length;
cube counts in the prompt follow from it (1 cube = 10 cm in the prompt, 5 cm in the voxels).

**Auto QA first:** view each candidate. Reject any that are not blocky axis-aligned cubes,
lack a plain background, crop the body, fuse the limbs, or grow thin appendages. Fewer than 2
survivors → regenerate before involving the user.

**USER PICK (mandatory):** show `concept_sheet.png` and STOP until they choose. Keep the picked
candidate's fal CDN URL — stage 2 takes it directly.

## Stage 2 — image to 3D (Hunyuan-3D), Stage 3 — voxelize, Stage 4 — rig + animate

One command runs all three and writes the report:

```
python tools/pipeline/run_creature.py <Name> --image-url <picked CDN url> --len-m 0.9
```

What it does, and the gates it applies:

- **Mesh** — `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d`, `generate_type: Normal`, PBR on,
  `face_count: 100000` (plenty for voxels, 4x smaller download). ~2.5 min. If the rear comes out
  wrong (Hunyuan hallucinates unseen views), pass a back-view image via `back_image_url`.
- **Voxelize** — `tools/voxelizer` cuts the mesh at 5 cm cells (`--long-axis` = 2 x metres x 10).
  Facing is detected from the voxel grid (the taller end is the head) and the yaw is swept
  automatically. **Check `previews/<Name>_vox_side.png`: the head must be at the image LEFT.** The
  heuristic fails on animals whose rump is higher than the head (rhino, boar) or whose tail is
  raised (skunk); fix those by re-running the voxelizer with `--yaw` and passing `--vox`.
- **Rig** — `tools/rig/voxrig.py` derives the body plan from the grid (leg zone = bottom layers
  still split into separate blobs, tail = narrow trailing slices, head = whatever rises at the
  front) and writes `<name>_rules.py` (voxel -> bone). `generic_quad_build.py` builds a 14-bone
  quadruped rig with rigid per-bone weights, authors Idle / Walk / Gallop / Graze / Alert, then
  exec's every module in `tools/rig/clips/` (Trot, Jump, Sit, Sleep, Shake, Stretch, LookAround,
  Rear) and exports the glTF. Gaits are scaled by leg length; the same maths runs on a fox and a hippo.

**QA gate (numeric, never visual):** `report.json` → `stages.rig.guards`. `DIRECTION GUARD: OK`
means every planted foot sweeps tailward and touches the ground in the Walk; `suspension: YES`
means the Gallop has an airborne frame (legs one voxel tall can't — the clip still exports).
Every extra clip prints its own `EXTRA CLIP <Name>: N frames | guard: OK ...`. Read
[references/rigging-traps.md](references/rigging-traps.md) before touching any rig code — it is the
accumulated list of things that silently produce wrong animation, including why vision-model
judges cannot be trusted to tell a forward walk from a backward one.

Optional: add `--video` to render a 3/4-view preview MP4 per clip into `previews/`.

## Stage 5 — use it

`<Name>_animated.glb` imports into Godot, Unity, Unreal and three.js with all clips as named
animations (`Idle`, `Walk`, `Gallop`, ... same names on every animal, so a state machine can key on
them). The `.blend` keeps the rig editable. (tiny-voxel additionally bakes the clips into its own
rigid-part runtime format; that baker is engine-specific and not part of this repo.)

## Wrap up

Report one line per stage: model used, voxel dims and count, clips exported, and any gate that
needed a retry. Leave the unpicked candidates in `concept/` — never delete.

## Scope

Quadrupeds only. The rig is one body plan with derived proportions; bipeds, birds, snakes and
anything with a moving tail need their own build script. Blocky voxel animals are the easy case
for both meshing and weights — nothing here claims organic characters.
