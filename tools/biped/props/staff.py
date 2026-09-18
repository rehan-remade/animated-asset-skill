"""Wizard's staff: dark gnarled wood shaft, gold claw cradling a cyan crystal orb.

Tool frame (see CONTRACT.md): origin = grip point at the middle of the shaft,
length along +y (orb at high y, gold-shod butt at low y), thickness along x/z.
Importing this module only defines CELL, CELLS, ANCHOR, NOTES.
"""

CELL = 0.0625  # tools: H/24 for a 1.5 m dwarf

WOOD_DARK = (110, 70, 35)     # shaft
WOOD_KNOT = (150, 95, 45)     # knots (lighter so the bands read)
GOLD = (220, 170, 60)         # claw, collar, butt cap
CYAN = (60, 220, 255)         # crystal orb
CYAN_PALE = (180, 245, 255)   # small glint on the orb

SHAFT_Y0, SHAFT_Y1 = -13, 12  # inclusive: 26 cells, centred on the grip at y=0
SHAFT_XZ = (-1, 0)            # 2x2 cross-section centred on the origin

ORB_R = 3.2                   # -> 6 wide at the equator, 4x4-minus-corners caps
COLLAR_Y = 12                 # gold socket overrides the shaft's top cell
ORB_YC = 16                   # sphere centre (cell boundary) -> orb spans y=13..18


def _box(cells, xs, ys, zs, col):
    for x in xs:
        for y in ys:
            for z in zs:
                cells[(x, y, z)] = col


def _shaft(cells):
    _box(cells, SHAFT_XZ, range(SHAFT_Y0, SHAFT_Y1 + 1), SHAFT_XZ, WOOD_DARK)


def _knot(cells, y0, dx, dz):
    """3x3 ring, 2 cells long, bulging one cell toward (dx, dz) so the wood looks gnarled."""
    xs = range(-1 + min(dx, 0), 1 + max(dx, 0))
    zs = range(-1 + min(dz, 0), 1 + max(dz, 0))
    _box(cells, xs, (y0, y0 + 1), zs, WOOD_KNOT)


def _sphere(yc, r):
    """Cells whose centre lies inside a sphere on the shaft axis, centred at height yc."""
    n = int(r) + 1
    out = set()
    for x in range(-n - 1, n + 1):
        for y in range(int(yc) - n - 1, int(yc) + n + 1):
            for z in range(-n - 1, n + 1):
                if (x + 0.5) ** 2 + (y + 0.5 - yc) ** 2 + (z + 0.5) ** 2 < r * r:
                    out.add((x, y, z))
    return out


def _corner_l(sx, sz):
    """Three cells hugging one diagonal corner of the 6x6 head footprint."""
    for ax, az in ((2, 1), (2, 2), (1, 2)):
        yield (ax if sx > 0 else -1 - ax, az if sz > 0 else -1 - az)


def _head(cells):
    orb = _sphere(ORB_YC, ORB_R)
    for c in orb:
        cells[c] = CYAN
    # glint: 2x2 pale patch high on the +z face
    for (x, y, z) in ((-1, 16, 2), (0, 16, 2), (-1, 17, 2), (0, 17, 2)):
        if (x, y, z) in orb:
            cells[(x, y, z)] = CYAN_PALE
    # collar: 4x4 gold socket on the shaft top (hides the orb's bottom cap layer above it)
    _box(cells, range(-2, 2), (COLLAR_Y,), range(-2, 2), GOLD)
    _box(cells, range(-2, 2), (COLLAR_Y + 1,), range(-2, 2), GOLD)
    # claw: four prongs on the diagonals. 3-cell L base at y=13 (cup rim), then a corner
    # column y=14..16 that grips the orb just past its equator; orb cells are never overwritten
    for sx in (1, -1):
        for sz in (1, -1):
            for x, z in _corner_l(sx, sz):
                if (x, COLLAR_Y + 1, z) not in orb:
                    cells[(x, COLLAR_Y + 1, z)] = GOLD
            x = 2 if sx > 0 else -3
            z = 2 if sz > 0 else -3
            for y in (COLLAR_Y + 2, COLLAR_Y + 3, COLLAR_Y + 4):
                cells[(x, y, z)] = GOLD


def _build():
    cells = {}
    _shaft(cells)
    _knot(cells, -9, -1, -1)   # lower knot bulges toward -x/-z
    _knot(cells, 6, 1, 1)      # upper knot bulges toward +x/+z
    _box(cells, SHAFT_XZ, (SHAFT_Y0, SHAFT_Y0 + 1), SHAFT_XZ, GOLD)  # gold-shod butt
    _head(cells)
    return cells


CELLS = _build()
ANCHOR = (0.0, 0.0, 0.0)
NOTES = ("tool frame: grip at origin (middle of shaft), shaft along y from -13 to +12, "
         "gold collar+claw at y=12..16 and cyan orb at y=13..18 (+y end), gold-shod butt at -y; "
         "2x2 shaft centred on the origin, head 6x6 footprint")
