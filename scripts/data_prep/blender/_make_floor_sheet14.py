"""Build a labeled 4x4 contact sheet from the 14 floor-applied renders + sanity
checks (magenta / clipping / mean tone). cv2 env (pathfinder)."""
import os
import numpy as np
import cv2

D = "data/pallet/_floor_applied14"
ORDER = [
    ("01_asphalt_02.png", "01 asphalt_02"),
    ("02_brick_floor_02.png", "02 brick_floor_02"),
    ("03_cobblestone_floor_08.png", "03 cobblestone_08"),
    ("04_concrete_floor_02.png", "04 concrete_floor_02"),
    ("05_concrete_floor_painted.png", "05 concrete_painted"),
    ("06_concrete_pavers_02.png", "06 concrete_pavers"),
    ("07_damaged_concrete_floor.png", "07 damaged_concrete"),
    ("08_dirt_ground.png", "08 dirt_ground"),
    ("09_gravel_concrete_02.png", "09 gravel_concrete"),
    ("10_red_brick.png", "10 red_brick"),
    ("11_red_earth.png", "11 red_earth"),
    ("12_tile_brown.png", "12 tile_brown"),
    ("13_tile_white.png", "13 tile_white"),
    ("14_wood_laminate.png", "14 wood_laminate"),
]
TW, TH = 320, 240
GAP = 8
COLS = 4


def magenta_frac(im):
    b, g, r = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
    return float(((r > 150) & (b > 150) & (g < 90)).mean())


tiles = []
print("\n=== FLOOR APPLIED 14 SANITY ===")
print(f"{'file':32s} {'meanBGR':>18s} {'magenta%':>9s} {'clip%':>7s}")
for fn, label in ORDER:
    p = os.path.join(D, fn)
    im = cv2.imread(p)
    if im is None:
        print(f"{fn:32s}  MISSING")
        continue
    mg = magenta_frac(im) * 100
    clip = float((im.max(2) >= 252).mean()) * 100
    mean = im.reshape(-1, 3).mean(0)
    print(f"{fn:32s} ({mean[0]:5.1f},{mean[1]:5.1f},{mean[2]:5.1f}) "
          f"{mg:8.3f} {clip:6.2f}")
    t = cv2.resize(im, (TW, TH), interpolation=cv2.INTER_AREA)
    cv2.rectangle(t, (0, 0), (TW - 1, 18), (0, 0, 0), -1)
    cv2.putText(t, label, (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (255, 255, 255), 1, cv2.LINE_AA)
    tiles.append(t)

rows = (len(tiles) + COLS - 1) // COLS
sheet = np.full((rows * TH + (rows + 1) * GAP, COLS * TW + (COLS + 1) * GAP, 3),
                40, np.uint8)
for i, t in enumerate(tiles):
    r, c = divmod(i, COLS)
    y = GAP + r * (TH + GAP)
    x = GAP + c * (TW + GAP)
    sheet[y:y + TH, x:x + TW] = t

out = os.path.join(D, "_SHEET_floor_applied14.png")
cv2.imwrite(out, sheet)
print(f"\n[OK] sheet -> {out}  ({sheet.shape[1]}x{sheet.shape[0]})")
