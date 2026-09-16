# animated-asset

**One sentence in. A rigged, animated voxel creature out.**

A [Claude Code](https://claude.com/claude-code) skill and the tools behind it: type "a cheerful corgi", pick one of four concept images, and a script does the rest — 3D mesh, voxels, a derived skeleton, 13 animation clips, glTF. I built it for my voxel game, then ran it on 40 animals in one go.

![38 voxel animals walking](docs/parade.gif)

## How it works

| Stage | What happens | Tool |
|---|---|---|
| 1. concept | fal Seedream draws 4 voxel-style concepts from a prompt template. **You pick one.** | `tools/pipeline/concept.py` or the fal MCP tools |
| 2. mesh | Hunyuan-3D turns the picked image into a textured mesh | fal, via `run_creature.py` |
| 3. voxelize | A small C++ voxelizer cuts the mesh into 5 cm cells, detects which end is the head | `tools/voxelizer` |
| 4. rig + animate | Headless Blender reads the body plan off the voxel grid, builds a 14-bone rig, authors 13 clips, checks the gaits with math, exports glTF | `tools/rig` |

![concept, mesh, voxels, rig](docs/pipeline-strip.png)

The trick that makes it work on any quadruped: the skeleton is **derived from the voxels**. The leg zone is the bottom layers that are still split into separate blobs, the tail is the narrow trailing slices, the head is whatever rises above the back at the front. The same gait maths then runs on every animal, scaled by leg length.

![voxels at three scales, then the rig](docs/voxels-rig.gif)

Gaits are verified numerically, never by eye: every planted foot has to sweep tailward and touch the ground, the gallop needs a frame with zero feet down, one-shot clips have to return to the rest pose. A vision-model panel once approved a backwards walk on this project; nothing visual is a gate anymore.

## Clips

Idle · Walk · Gallop · Graze · Alert · Trot · Jump · Sit · Sleep · Shake · Stretch · LookAround · Rear — same names on every animal, so a state machine can key on them. Each clip is a small Python module in `tools/rig/clips/`; adding one means writing a module that defines `EXTRA_ACTION`, `EXTRA_LENGTH` and an `EXTRA_GUARD` string.

## Quick start

Requirements: [Blender 5.2 LTS](https://www.blender.org/download/lts/) on your PATH (or `export BLENDER=/path/to/blender`), CMake + a C++17 compiler, Python 3.10+, and a [fal](https://fal.ai) API key.

```bash
git clone https://github.com/rehan-remade/animated-asset-skill
cd animated-asset-skill
pip install -r requirements.txt

# build the voxelizer once
cmake -S tools/voxelizer -B tools/voxelizer/build -DCMAKE_BUILD_TYPE=Release
cmake --build tools/voxelizer/build --config Release

export FAL_KEY=...            # or put the key in ~/.fal/key

# 1. concepts (4 images, ~$0.27) -> pick one from assets/Corgi/concept/concept_sheet.png
python tools/pipeline/concept.py Corgi --idea "a cheerful corgi" --len-m 0.9 \
  --anatomy "a long loaf body, two tall triangular ears as stepped cubes, four very short thick legs clearly separated, a stub tail" \
  --colors "orange back, white chest, muzzle and paws, black nose"

# 2-4. mesh (~$0.68, ~2.5 min) -> voxels -> rig + 13 clips (~10 s) -> glTF
python tools/pipeline/run_creature.py Corgi --image-url <picked url> --len-m 0.9
```

Output lands in `assets/Corgi/`: the mesh, the `.vox`, side/front/top previews, the derived `layout.json` and `corgi_rules.py`, `Corgi_rigged.blend`, `Corgi_animated.glb` with every clip, and a `report.json` with the guard results. Add `--video` for a preview MP4 per clip.

Already have a mesh or a `.vox`? Skip ahead with `--glb model.glb` or `--vox model.vox`.

### Using it as a Claude Code skill

Copy `skill/animated-asset/` into your project's `.claude/skills/` (or `~/.claude/skills/` for every project), keep the `tools/` folder somewhere Claude can run it, and connect the [fal MCP server](https://mcp.fal.ai/mcp) if you want stage 1 to happen inside the conversation. Then:

> add a corgi

Claude runs the stages, stops to let you pick a concept, and reports the guards. `references/rigging-traps.md` is the part worth reading even if you never run the skill: it is every way this pipeline produced wrong animation that looked right.

## What to expect

- **Quadrupeds only.** One body plan with derived proportions. Bipeds, birds and moving tails need their own build script.
- **Blocky animals are the easy case.** Voxel meshes are clean by construction and rigid weights are correct for them. Nothing here claims organic characters.
- **Facing can flip** on animals whose rump is higher than the head (rhino, boar) or whose tail is raised (skunk). Check the side preview; fix with `--yaw`.
- **Very short legs can't gallop.** A hedgehog with one-voxel legs passes the walk guard and fails the airborne check. The clip still exports; it reads as a fast trot.
- On the 40-animal batch this repo came from, 39 passed every guard on the first run. Cost was about $38 of fal credit for 160 concept images and 40 meshes, and 3 to 5 seconds of Blender per animal.

## Layout

```
skill/animated-asset/       SKILL.md + references (fal-generation.md, rigging-traps.md)
tools/voxelizer/            mesh -> .vox (C++17, vendored tinyobjloader / cgltf / stb)
tools/rig/                  generic_quad_build.py (rig + base clips + glTF export), voxrig.py (body plan + bone rules), clips/*.py
tools/pipeline/             concept.py, run_creature.py, fal_client.py, contact_sheet.py
examples/creatures.json     the prompt anatomy/colour lines used for the 40-animal batch
```

## Credits and licence

MIT. Vendored headers ([tinyobjloader](https://github.com/tinyobjloader/tinyobjloader), [cgltf](https://github.com/jkuhlmann/cgltf), [stb](https://github.com/nothings/stb)) keep their own MIT / public-domain licences. Seedream and Hunyuan-3D are third-party models served by fal under their own terms.

Built with Claude Code for [tiny-voxel](https://x.com/rehan_shei). I work at fal; this is a side project.
