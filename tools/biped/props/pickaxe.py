"""Miner's pickaxe: wooden 2x2 handle along +y with a wide two-spike steel head at the top.
Tool frame per CONTRACT.md: origin = grip, length along +y, head across x, thickness along z."""

CELL = 0.0625  # tools: H/24 for a 1.5 m dwarf

WOOD = (150, 95, 45)
STEEL = (190, 195, 205)      # polished arms and points
IRON = (130, 135, 145)       # forged eye / socket
LEATHER = (80, 55, 35)       # dark wraps: grip, butt cap, binding under the head

HANDLE_Y0 = -4               # butt; the grip sits around y = -1..1 at the origin
HANDLE_LEN = 14              # cells of handle from the butt to the head's underside
HEAD_Y0 = HANDLE_Y0 + HANDLE_LEN - 1     # underside of the head (y = 9)
HEAD_TOP = HEAD_Y0 + 3                   # top of the eye (y = 12) -> 4 tall at the centre
THICK = (-1, 0)              # 2 cells thick along z, centred on the origin
EYE_X = range(-2, 2)         # 4-wide socket boss around the 2x2 handle
EYE_Z = range(-2, 2)         # 4 thick, the only part fatter than 2 in z

# Arm profile, mirrored about the handle centre (x = 0 in world units, between cells -1 and 0):
# offset d -> (lowest y, highest y); right arm at x = d, left arm at x = -1 - d.
# With the 4-wide eye the head is 14 wide (x = -7..6). The arms step down from
# 3 tall to 2-tall points over the last 3 cells and curve toward the grip like a real pick.
ARMS = {
    2: (HEAD_Y0, HEAD_Y0 + 2),          # 3 tall, shoulder
    3: (HEAD_Y0, HEAD_Y0 + 2),          # 3 tall
    4: (HEAD_Y0, HEAD_Y0 + 1),          # 2 tall
    5: (HEAD_Y0 - 1, HEAD_Y0),          # 2 tall, one step down
    6: (HEAD_Y0 - 2, HEAD_Y0 - 1),      # 2 tall point, two steps down
}


def _box(cells, xs, ys, zs, col):
    for x in xs:
        for y in ys:
            for z in zs:
                cells[(x, y, z)] = col


def _build():
    cells = {}
    # --- handle: 2x2 wood from the butt up through the eye ---
    _box(cells, (-1, 0), range(HANDLE_Y0, HEAD_TOP + 1), THICK, WOOD)
    _box(cells, (-1, 0), (HANDLE_Y0,), THICK, LEATHER)          # butt cap
    _box(cells, (-1, 0), range(-1, 2), THICK, LEATHER)          # grip wrap, ~3 cells at the origin

    # --- head arms: bright steel, 2 thick ---
    for d, (y0, y1) in ARMS.items():
        _box(cells, (-1 - d, d), range(y0, y1 + 1), THICK, STEEL)
    # --- eye: dark forged socket boss, 4x4 footprint, 4 tall ---
    _box(cells, EYE_X, range(HEAD_Y0, HEAD_TOP + 1), EYE_Z, IRON)
    # --- binding: dark leather collar just under the eye, same footprint ---
    _box(cells, EYE_X, (HEAD_Y0 - 2, HEAD_Y0 - 1), EYE_Z, LEATHER)
    return cells


CELLS = _build()
ANCHOR = (0.0, 0.0, 0.0)
NOTES = "pickaxe: grip at origin, handle along +y (butt y=-4), two-spike steel head across x (14 wide, symmetric about the handle) at y=7..12, 2 thick in z (eye 4)"
