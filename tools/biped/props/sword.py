"""Oversized game-style one-hand sword for the 1.5 m voxel dwarf.

Tool frame (see CONTRACT.md): origin = grip point (fist), length along +y with the
tip at high +y, pommel at negative y, blade edges along x, thickness along z.
All widths are even and centred on the x=0 / z=0 cell boundary so the grip (2 wide)
sits exactly under the blade (4 wide) and guard (8 wide).
"""

CELL = 0.0625  # H/24 for a 1.5 m dwarf (tool scale)

# palette
GOLD = (220, 170, 60)
STEEL = (190, 195, 205)
STEEL_DARK = (130, 135, 145)
LEATHER = (110, 70, 35)
LEATHER_DARK = (90, 55, 30)

_Z2 = range(-1, 1)   # 2 cells thick (blade, grip, pommel)
_Z4 = range(-2, 2)   # 4 cells thick (guard) so it reads edge-on


def _box(cells, xs, ys, zs, col):
    for x in xs:
        for y in ys:
            for z in zs:
                cells[(x, y, z)] = col


def _build():
    c = {}
    # pommel: flat gold knob, 4 wide, 2 cells below the grip
    _box(c, range(-2, 2), range(-3, -1), _Z2, GOLD)
    # grip: 3 cells around the origin, 2x2, alternating leather wrap
    for y in range(-1, 2):
        _box(c, range(-1, 1), [y], _Z2, LEATHER if y % 2 else LEATHER_DARK)
    # crossguard: 8 across x, 2 along y, 4 thick
    _box(c, range(-4, 4), range(2, 4), _Z4, GOLD)
    # blade: 4 wide, full width y=4..13, dark 2-wide fuller down the centre
    _box(c, range(-2, 2), range(4, 14), _Z2, STEEL)
    _box(c, range(-1, 1), range(5, 12), _Z2, STEEL_DARK)
    # point: narrows to 2 wide over the last 3 cells
    _box(c, range(-1, 1), range(14, 17), _Z2, STEEL)
    return c


CELLS = _build()
ANCHOR = (0.0, 0.5, 0.0)  # origin at the centre of the grip
NOTES = "sword: grip at origin, blade along +y (tip at y=16), edges along x, blade 2 cells thick along z, pommel at y=-3"
