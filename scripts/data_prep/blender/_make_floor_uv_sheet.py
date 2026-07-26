"""Stitch the floor-UV comparison grid + report (a) pattern contrast (grey std,
mush detector) and (b) dominant pattern PERIOD in px via row/col autocorrelation,
expressed as a fraction of the pallet's on-screen width so we can judge whether a
floor repeat reads SMALLER than the pallet. Rows = texture, cols = metres_per_tile.
Run in pallet-pose env (needs cv2). Out: data/pallet/_floor_uv_test/_sheet.png"""
import os
import numpy as np
import cv2

OUT = os.path.join("data", "pallet", "_floor_uv_test")
TEXTURES = ["red_brick", "tile_white", "cobblestone_floor_08"]
MPT = [1.0, 1.5, 2.0, 3.0, 6.0]


def _pattern_period_px(roi_gray):
    """Estimate dominant repeat period (px) along the horizontal axis via 1-D
    autocorrelation of the column-mean profile. Returns first strong peak lag."""
    prof = roi_gray.mean(axis=0).astype(np.float64)
    prof -= prof.mean()
    if prof.std() < 1e-6:
        return 0.0
    ac = np.correlate(prof, prof, mode="full")
    ac = ac[ac.size // 2:]
    ac /= ac[0]
    n = len(ac)
    # first local maximum after the central lobe crosses below ~0.2
    crossed = np.where(ac < 0.2)[0]
    if len(crossed) == 0:
        return 0.0
    start = crossed[0]
    if start >= n - 2:
        return 0.0
    seg = ac[start:]
    peak = int(np.argmax(seg)) + start
    if ac[peak] < 0.25:
        return 0.0
    return float(peak)


def _pallet_width_px(im):
    """Rough pallet on-screen width: the pallet (wood, mid-bright, near image
    centre, above the floor band) -- estimate via the bright/structured central
    blob. We approximate with the width of the strong-gradient central region in
    the upper-middle band. Falls back to a fixed fraction if detection fails."""
    h, w = im.shape[:2]
    band = im[int(h*0.30):int(h*0.65), :]
    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(g, 40, 120)
    cols = edges.sum(axis=0)
    idx = np.where(cols > cols.max() * 0.15)[0] if cols.max() > 0 else []
    if len(idx) > 5:
        return float(idx[-1] - idx[0])
    return float(w * 0.45)


cells, std_tab, per_tab = {}, {}, {}
pallet_w = {}
for name in TEXTURES:
    for m in MPT:
        p = os.path.join(OUT, f"{name}_mpt{m:.1f}.png")
        im = cv2.imread(p)
        if im is None:
            print("MISSING", p); continue
        h, w = im.shape[:2]
        roi = im[int(h*0.72):int(h*0.96), int(w*0.20):int(w*0.80)]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
        std = float(gray.std())
        per = _pattern_period_px(gray)
        pw = _pallet_width_px(im)
        std_tab[(name, m)] = std
        per_tab[(name, m)] = per
        pallet_w[(name, m)] = pw
        rel = per / pw if pw > 0 else 0.0
        lab = im.copy()
        cv2.putText(lab, name, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
        cv2.putText(lab, f"mpt={m:.1f}m std={std:.0f}", (8, h-34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)
        cv2.putText(lab, f"period~{per:.0f}px ({rel*100:.0f}% pallet)", (8, h-12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,200,0), 2)
        cells[(name, m)] = lab

h, w = next(iter(cells.values())).shape[:2]
rows, cols = len(TEXTURES), len(MPT)
sheet = np.zeros((rows*h, cols*w, 3), np.uint8)
for ri, name in enumerate(TEXTURES):
    for ci, m in enumerate(MPT):
        if (name, m) in cells:
            sheet[ri*h:(ri+1)*h, ci*w:(ci+1)*w] = cells[(name, m)]
sp = os.path.join(OUT, "_sheet.png")
cv2.imwrite(sp, sheet)
print("sheet ->", sp)

pw_mean = np.mean([v for v in pallet_w.values() if v > 0])
print(f"\n  approx pallet on-screen width ~ {pw_mean:.0f}px (1.1 m)")
print("\n=== floor pattern grey std (mush detector) ===")
print("  lower std => grey mush / pattern lost; higher => pattern visible")
print(f"  {'texture':24s} " + "  ".join(f"mpt{m:.1f}" for m in MPT))
for name in TEXTURES:
    vals = "  ".join(f"{std_tab.get((name,m),0):6.1f}" for m in MPT)
    print(f"  {name:24s} {vals}")

print("\n=== dominant repeat period (px) ; % of pallet width ===")
print("  want period << pallet width (each repeat smaller than pallet)")
print(f"  {'texture':24s} " + "  ".join(f"mpt{m:.1f}" for m in MPT))
for name in TEXTURES:
    vals = "  ".join(
        f"{per_tab.get((name,m),0):4.0f}/{(per_tab.get((name,m),0)/pw_mean*100 if pw_mean>0 else 0):3.0f}%"
        for m in MPT)
    print(f"  {name:24s} {vals}")
