# Rigging & animation traps (stage 4)

Hard-won lessons from the Stag/Player/Bear builds. Every one of these cost
a debugging session; do not re-learn them.

## Blender 5.2 headless

- Binary: whatever `blender` resolves to (set `BLENDER=/path/to/blender` if it is not on PATH; Blender 5.2 LTS)
  The build scripts run inside Blender's bundled Python (`blender -b --python ...`), so nothing to pip-install.
- `--factory-startup` still loads the default cube — start scripts with
  `bpy.ops.wm.read_factory_settings(use_empty=True)`.
- `action.fcurves` is GONE → `action.layers[*].strips[*].channelbag(slot).fcurves`.
  After `ad.action = act`, also set `ad.action_slot = act.slots[0]`.
- FFMPEG video export needs `image_settings.media_type = "VIDEO"` set FIRST.
- Workbench + vertex colors: `display.shading.color_type = "VERTEX"`.
- glTF import creates an "Icosphere" bone-shape mesh that is NOT in the
  .glb — don't chase it when validating exports.
- `view_layer.update()` mid-keying re-applies keyed fcurves at the current
  frame over hand-set pose values. Key first, `scene.frame_set(f)`, THEN
  update and read — or derive from parent pose matrices.

## Loading the .vox

Parse directly (RIFF-like: SIZE/XYZI/RGBA chunks) — Blender has no native
importer. Emit only exterior faces; per-face corner colors from the
palette, sRGB→linear, into a CORNER FLOAT_COLOR attribute. MagicaVoxel is
Z-up like Blender. The voxelizer outputs models facing -Y (Blender
forward) when stage 3's QA gate passed; if a legacy model faces elsewhere,
remap indices at import — flip ONE axis and you MIRROR the model, e.g.
-X-facing fix is `(x,y,z) -> (Wy-1-y, x, z)`.

## Rig

- Rule-based rigid weights (region rules in voxel coords from the
  `--ascii` slices) beat nearest-bone. Keep rules in
  `tools/creatures/<name>_rules.py`; claim parents first so shared
  boundary voxels stay body-side and limbs stretch instead of tearing.
- Pose-bone `location` is in the bone's LOCAL rest frame; for a
  -Y-pointing bone (quadruped hips/spine) local Z ≈ world -Z, so keying
  `location.z = -drop` RAISES the body. Never assume the frame: measure
  `bone.matrix_local.to_3x3()` once and convert world→local via its
  inverse.
- Rotation signs: probe() self-calibration (key a small angle, measure
  which way the tail moves) — never guess bone-local axes.

## Gait correctness (the big ones)

- **Walk DIRECTION is set by stance sweep, not phase order.** A planted
  foot must sweep toward the TAIL (body-fixed, in-place animation).
  Swapping phase offsets does NOT fix a backwards walk. Drive legs from an
  explicit foot trajectory (2-bone sagittal IK) where the planted-phase
  sweep direction is written directly.
- **Verify direction by rig math, NEVER by looking at renders and NEVER
  by vision-LLM judges** (a 3-critic panel passed a backwards walk; a
  blind 2-judge panel failed a correct one). Definitive check: open the
  .blend, per frame read the foot bone tail in world space, project
  through the preview camera (`world_to_camera_view`); over a leg's full
  stance the image-x must move tailward and world-Y must rise ~one stride.
- **Never give verifiers the parameter under test as ground truth** —
  blind them.
- **Ungulate knee folds:** front carpus apex points FORWARD (hoof curls
  back beneath it); hind hock apex points BACKWARD (hind hooves reach
  forward in a gallop gather). Front and hind legs use OPPOSITE 2-bone-IK
  branches. Check at a high-flexion frame (gallop gather), not at
  near-straight stance. Plantigrades (bears): both fold forward.
- **Ungulate legs are stilts:** high joint (hock/carpus ~55-60% up),
  short thigh + long straight shank, low delicate hoof arc. A low mid-leg
  knee with big swing flex reads as a human march.
- **Numeric gait guards beat stills:** per-frame grounded-foot counts
  (foot world z < 5 cm) instantly expose bugs. Walk-amble ≈ [2,3]
  alternating; transverse gallop ≈ [1,2,2,3,3,3,2,2,2,1,0,0] with a
  suspension window. IK clamps when hypot(reach, root_z) > leg length —
  lower the body, don't lengthen the stride.
- Gait transitions: master phase clock with cadence lerp; blend body
  channels and foot POSITIONS (never parameters); rescale total phase to
  an integer so end frames equal the target cycle's phase-0 pose. (The
  engine now crossfades clips at runtime, so transition clips are
  optional.)
- Short-legged animals: tighten bound pairs + raise STEP height to get a
  true airborne frame; flight-phase paw heights sit at 2–5 cm otherwise.

## Stub legs (sub-voxel buckets): rigid columns + audit the BAKED paw plane

A bucket-1/2 creature with 2-cell legs (corgi: total reach 0.125 m) makes
2-bone IK nearly degenerate: 1 mm of crouch slack bends the shank 15–26 deg,
the tilted paw BOX swings its corners below the bone tip, and the ENGINE's
hoof ground snap then shoves each paw up into the belly — in-game the
creature reads as sunk to its chest while every preview video looks fine
(the burial only manifests after the snap). Rules learned (corgi 2026-07-24):

- Stance-dominant clips (Idle/Alert/Graze/Walk): rigid-column legs — aim the
  whole leg at the target, no knee (`solve_leg(..., knee=False)` in
  corgi_build.py). The <= 3 mm length surplus buries invisibly.
- Tuck gaits (Gallop): knee IK is still right — the fold happens mid-air
  where the snap preserves the authored clearance; keep the deep crouch.
- Keep stance body drops <= ~0.005 m; chest pitch drops the front-leg roots
  by 0.20 x sin(pitch), so posed clips (sniff) must stay gentle (<= ~6 deg)
  and let the head do the acting.
- ALWAYS audit the baked artifact, not the Blender scene:
  `python tools/creatures/check_cvx2.py assets/creatures/<name>.cvx2`
  replays the engine's compose math and prints per-clip paw-plane min-y.
  Stance clips should sit >= -0.25 world voxels; -0.4 or lower reads as
  sunk on a short-legged animal.

## Bipeds

NOTE: there is no in-repo biped build script — only the quadruped
`stag_build.py` is committed. `tools/creatures/player_rules.py` holds the
player's bone rules; reconstruct a biped script from `stag_build.py` +
those rules + this section. The original `player_build.py` (old session
scratchpad) had: humanoid rig, 9 clips
(Idle/Walk/Sprint/CrouchIdle/CrouchWalk/Jump/Fall/Land/Punch), FOOT bones
with world-flat compensation `foot_x = -(upper+lower)` + toe-off pitch.
Bipeds are normalized to real height in Blender (player: S = 1.8/height),
NOT by the 10 cm voxel rule — a 32-voxel humanoid would be 3.2 m tall.
Chibi proportions: hanging hip→ankle ≈ total leg length, so EVERY gait
needs body drop before stride reach (walk 0.045, sprint 0.065 + lean).
Pelvis yaw > 4–5° visibly shears waistband voxels.

## Engine hookup

- Clip rate-lock, creatures: measure the authored ground speed (median
  per-frame stance sweep of foot bones, foot z within 2 cm of its min)
  and write it as `<clip>_ref_speed` in the .def — engine units are
  voxels/s, i.e. measured m/s x 10 (see assets/creatures/stag.def).
- Clip rate-lock, PLAYER only: app.cpp uses anim divisors, calibrated
  through the Walk anchor (0.423 m/s ↔ divisor 14, k = 33.1; divisor =
  m/s x 33.1). Anchor walk-family gaits on Walk; the engine deliberately
  runs Sprint hotter than measured.
- Before opening files in a user's live Blender (MCP), check
  `bpy.data.filepath` + `is_dirty`.
- The Blender MCP add-on auto-starts on launch only if Preferences →
  System → Network → Allow Online Access is ticked; sessions cannot launch
  Blender themselves (permission classifier) — ask the user, then poll
  port 9876.
