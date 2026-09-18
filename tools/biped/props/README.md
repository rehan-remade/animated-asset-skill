# Voxel prop modules (weapons in the hand slot)

Each asset is one Python module in `assets/` that defines:

```python
CELL = 0.05                     # metres per cell (tools use 0.0625 = H/24 for a 1.5 m dwarf; stations 0.05)
CELLS = {(x, y, z): (r, g, b), ...}   # integer cell coords -> sRGB colour 0..255
ANCHOR = (0.0, 0.0, 0.0)        # point in cell units that sits at the object origin
NOTES = "one line on orientation"
```

Frames:
- **Tools** (sword, axe, pickaxe, staff): origin = the grip point (where the fist is). Length runs along **+y**
  (blade tip / axe head / orb at high y; pommel / handle butt at negative y). Blade edge, axe head and pickaxe
  head extend along **x**. Thickness along **z**. Grip about 3 cells long around the origin. A 1.5 m dwarf holds
  a sword 16–20 cells long (1.0–1.25 m: oversized game style), an axe/pickaxe 14–16 cells with a fat head, a
  staff 26–28 cells with a 5-cell orb on top. Everything at least 2 cells thick; 1-cell parts vanish on camera.
- **Stations** (log, ore rock, training dummy, spell target): origin at the **floor centre** of the piece,
  z up (z=0 is the floor layer), the side that faces the character is **-y**. Real scale at 0.05 m cells:
  a log ~0.9 m long lying along x and ~0.4 m tall; a boulder ~0.8 m wide/tall with 3–4 glowing cyan ore
  cells; a training dummy ~1.6 m tall (post + straw body + wooden head); a spell target = a stone ring
  ~1 m wide on the floor with 4 rune stones + a floating 3-cell crystal at 1.2 m.
- **Palette**: flat colours, 2–4 per asset, warm wood (150,95,45)/(110,70,35), steel (190,195,205)/(130,135,145),
  cyan magic (60,220,255), gold (220,170,60), stone (120,122,130)/(90,92,100), straw (210,180,90).

Preview: `python render_cells.py assets/<name>.py` writes `previews/<name>.png` (front / side / 3/4 views).
Look at it. Iterate until the silhouette reads at 200 px. Keep CELLS under ~600 cells.
