"""Woodcutter's axe (single-bit felling axe) for the voxel dwarf.

Tool frame (see CONTRACT.md): origin = grip point (fist), length along +y with
the head at high +y and the handle butt at negative y, head extends along x
(mostly to -x, poll to +x), thickness along z.
"""

CELL = 0.0625  # H/24 for a 1.5 m dwarf (tool scale per CONTRACT.md)

# palette (flat, 4 colours)
_WOOD = (150, 95, 45)
_WOOD_DARK = (110, 70, 35)
_STEEL = (130, 135, 145)            # dark iron: eye/socket + poll
_STEEL_EDGE = (190, 195, 205)       # bright steel: the whole bit on the -x side

# handle: 2x2 thick, 14 cells long, butt at y=-4, top at y=9 (pokes 1 cell out of the eye)
_HANDLE_Y0, _HANDLE_Y1 = -4, 9
_GRIP_Y0, _GRIP_Y1 = -1, 1          # 3-cell dark wrap around the fist (origin)

# head: x from -5 (edge) to +1 (poll) = 7 wide
_HEAD_Y0, _HEAD_Y1 = 5, 9           # bit body: 5 rows tall
_COLLAR_Y0, _COLLAR_Y1 = 6, 8       # eye/socket: 3 rows tall so the bit shows above and below it
_EYE_X = range(-1, 1)               # eye/socket around the haft, 4 cells thick (z -2..1)
_POLL_X = [1]                       # hammer poll on +x, 2 thick (kept thin so it never hides the bit)
_BLADE_X = range(-5, -1)            # bit, 2 cells thick (z -1..0)
_FLARE_X = range(-5, -3)            # the two outermost columns flare 1 cell up and down (7 tall at the edge)


def _box(cells, xs, ys, zs, colour):
    for x in xs:
        for y in ys:
            for z in zs:
                cells[(x, y, z)] = colour


def _build():
    cells = {}
    # --- handle ------------------------------------------------------------
    _box(cells, range(-1, 1), range(_HANDLE_Y0, _HANDLE_Y1 + 1), range(-1, 1), _WOOD)
    _box(cells, range(-1, 1), range(_GRIP_Y0, _GRIP_Y1 + 1), range(-1, 1), _WOOD_DARK)
    # --- head (overwrites the handle cells it encloses) --------------------
    # blade / bit: 2 thick, bright steel so it separates from the dark eye at 200 px
    _box(cells, _BLADE_X, range(_HEAD_Y0, _HEAD_Y1 + 1), range(-1, 1), _STEEL_EDGE)
    # flared bit: outermost two columns extend one cell below and above the body
    _box(cells, _FLARE_X, [_HEAD_Y0 - 1, _HEAD_Y1 + 1], range(-1, 1), _STEEL_EDGE)
    # eye / socket: fat 4-thick block around the haft (haft pokes out above it at y=9); poll 2 thick
    _box(cells, _EYE_X, range(_COLLAR_Y0, _COLLAR_Y1 + 1), range(-2, 2), _STEEL)
    _box(cells, _POLL_X, range(_COLLAR_Y0, _COLLAR_Y1 + 1), range(-1, 1), _STEEL)
    return cells


CELLS = _build()
ANCHOR = (0.0, 0.0, 0.0)  # cell corner (0,0,0) = centre of the 2x2 haft at the fist
NOTES = "tool frame: grip at origin, haft along +y (butt y=-4, top y=9), head y=4..10 with 4-thick eye at y=6..8, single bit flares to -x with lighter edge, poll to +x, thickness along z"
