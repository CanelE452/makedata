"""Build a labeled 3x3 contact sheet from the floor-compare renders + sanity
checks (magenta / clipping / tone). cv2 env (pathfinder)."""
import os
import numpy as np
import cv2

D = "data/pallet/_floor_compare"
ORDER = [
    ("00_BEFORE_current.png", "BEFORE: shipped grating floor (1 type)"),
    ("01_concrete_floor_02.png", "01 concrete_floor_02"),
    ("02_damaged_concrete_floor.png", "02 damaged_concrete"),
    ("03_asphalt_02.png", "03 asphalt_02"),
    ("04_concrete_pavers_02.png", "04 concrete_pavers (panels)"),
    ("05_concrete_floor_painted.png", "05 concrete_painted"),
    ("06_cobblestone_floor_08.png", "06 cobblestone_08"),
    ("07_gravel_concrete_02.png", "07 gravel_concrete"),
    ("08_brick_floor_02.png", "08 brick_floor_02"),
]
TW, TH = 320, 240
GAP = 8
COLS = 3


def magenta_frac(im):
    b, g, r = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
    return float(((r > 150) & (b > 150) & (g < 90)).mean())


tiles = []
print("\n=== FLOOR COMPARE SANITY ===")
print(f"{'file':30s} {'meanBGR':>18s} {'magenta%':>9s} {'clip%':>7s}")
for fn, label in ORDER:
    p = os.path.join(D, fn)
    im = cv2.imread(p)
    if im is None:
        print(f"{fn:30s}  MISSING")
        continue
    mg = magenta_frac(im) * 100
    clip = float((im.max(2) >= 252).mean()) * 100
    mean = im.reshape(-1, 3).mean(0)
    print(f"{fn:30s} ({mean[0]:5.1f},{mean[1]:5.1f},{mean[2]:5.1f}) "
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

out = os.path.join(D, "_SHEET_floor_compare.png")
cv2.imwrite(out, sheet)
print(f"\n[OK] sheet -> {out}  ({sheet.shape[1]}x{sheet.shape[0]})")
