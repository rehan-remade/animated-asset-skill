# Retargeting notes (read before touching tools/biped)

**Method.** For every mapped target bone t with source bone s:
1. At rest, compute `Align = rotation_difference(dir_t, dir_s)` (the minimal rotation taking the target
   bone's direction onto the source's) and **re-roll the target bone** so its rest frame is
   `Align⁻¹ · R_s`. Its direction is unchanged (so the mesh weights are unchanged) but its local axes now
   match the source's convention, roll included.
2. Per frame, set the target bone's **world rotation equal to the source's** (`W_t = W_s`). Solve the pose
   basis top-down from the parents' world matrices — no depsgraph updates per bone.
3. The hips also copy translation, scaled by the ratio of upper-leg heights. Feet below z=0 are lifted per
   frame through `hips.location`.

Why not the usual "copy the world-space delta from rest": with a T-pose source and a hanging-arm target a
delta about Z leaves the hanging arm hanging — the pose never lifts. Re-rolling first makes a plain world
copy exact; the direction check then reports 0.000°.

**Missing bones.** Hands/weapon slots the target lacks are created from the source's local offset in the
nearest mapped ancestor's frame, scaled by that ancestor's length ratio; a skipped wrist chains the hand
onto the forearm tail. Sources without a slot bone (Mixamo) get a default slot at the hand tail — props
then point along the hand, fine for a staff, wrong for a sword grip: add a slot in the map if you have one.

**Things that bit us (2026-09-18).**
- Blender's glTF importer keeps source clip names; `Idle` clashed with the target clip `Idle` — source
  actions are renamed `SRC_*` on import and deleted after baking.
- Blender 5.x slotted actions: `act.slots.new(id_type="OBJECT", name=...)` and assign `ad.action_slot`
  before `keyframe_insert`. Stash clips in muted NLA tracks; export with `export_animation_mode="ACTIONS"`.
- Bone-parented props anchor at the bone **tail**: subtract the slot length on the local y.
- KayKit meshes are stylised (the evaluated knight is 2.3 units tall on a 1.24-unit rig; the sword is
  1.8 long). Never size a prop from source geometry — props are sized from the target character.
- Root-motion clips (KayKit `Dodge_*`, `*_RM` in Quaternius) copy the hips travel as-is; strip it in the
  engine or pick the in-place variant.
- Facing: sources must face -Y like the target. `facing_fix` checks the source foot direction and spins the
  source armature 180° if needed (Mixamo imports usually face -Y already).
- Body plan: hanging arms merge into the torso at the shoulders — grow free columns first, then a
  shoulder pass over cells beyond the trunk's x-extent, contiguous with the column and capped at 0.8× its
  height; a wide chibi head above would otherwise be eaten as shoulders. The head starts at the first
  layer above the shoulder line that is narrower than the trunk.
- Chibi proportions: the pelvis block (0.35× leg height above the crotch) moves with the legs, as in
  tiny-voxel's hand-made Player rules (87% per-voxel agreement, all bands identical).

**Guards are maths.** `dir_err_deg` (identity check), NaNs, hips excursion, floor fix, loop gap
(first/last pose angle for loops), hit frame (weapon-slot speed peak). A vision-model panel once approved
a backwards quadruped walk on this project; nothing visual gates a clip.
