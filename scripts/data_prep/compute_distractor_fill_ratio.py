"""Asset pre-compute: silhouette fill_ratio + domain_plausible for the 209 distractor pool.

Standalone tool (base python + trimesh + PIL + numpy). NOT a scene render -- it loads
each distractor mesh ONCE and computes an orthographic silhouette metric used by the
v2 occlusion Layer to back-calculate d_occ (porous objects such as racks/fences give a
low fill_ratio, so the occluded fraction of the pallet must not be inferred from the
distractor's projected bbox alone).

fill_ratio(azimuth) = silhouette_area / projected_bbox_area
    silhouette_area  = area of the object's outline as seen side-on (holes subtracted)
    projected_bbox   = the up-aligned axis-aligned bounding rectangle of that view
Reported = mean / std over 8 azimuths (rotation about the object's up axis).

Up axis is auto-detected as the grounded axis (bounds-min closest to 0): Poly Haven
gltf + Sketchfab glb are Y-up, Google-Scanned-Objects obj are Z-up (verified on
samples). fill_ratio is scale-invariant, so the steel_frame_shelves_01 21 m anomaly
does not matter.

Method per azimuth: trimesh.projected (exact hole subtraction) as primary; PIL
triangle rasterization (res=512) as a robust fallback when projected() fails on an
edge-on/degenerate view. Meshes above FACE_RASTER_CAP faces use raster directly
(organic high-poly, where exact holes matter little and projected() is slow).

Also assigns domain_plausible (indoor / outdoor_day / outdoor_night) by a coarse,
conservative folder+source rule (see domain_plausible_rule). day == night per object
(object plausibility is indoor-vs-outdoor; day/night is a lighting axis, not an object
axis) -- kept as two explicit columns for the scene_preset selector.

Output: rewrites distractors_manifest.csv, appending columns (existing columns/rows
untouched):
    fill_ratio_mean, fill_ratio_std, fill_ratio_min, fill_ratio_max, fill_ratio_method,
    dp_indoor, dp_outdoor_day, dp_outdoor_night

Run:  python scripts/data_prep/compute_distractor_fill_ratio.py
      python scripts/data_prep/compute_distractor_fill_ratio.py --dry_run   # no manifest write
"""

import argparse
import csv
import os
import time

import numpy as np
import trimesh
from PIL import Image, ImageDraw

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", ".."))
DISTRACTOR_DIR = os.path.join(PROJECT_ROOT, "data", "pallet", "distractors")
MANIFEST = os.path.join(DISTRACTOR_DIR, "distractors_manifest.csv")

N_AZIMUTHS = 8
RASTER_RES = 512
FACE_RASTER_CAP = 120000  # above this, raster only (projected() too slow, organic holes)
EXTREME_THRESHOLD = 0.15

NEW_COLUMNS = [
    "fill_ratio_mean", "fill_ratio_std", "fill_ratio_min", "fill_ratio_max",
    "fill_ratio_method", "dp_indoor", "dp_outdoor_day", "dp_outdoor_night",
]


# --------------------------------------------------------------------------- #
# domain_plausible rule (coarse, conservative). Reported verbatim in the task.
#   indoor folder  -> indoor only         (household / office / decor)
#   road   folder  -> outdoor only        (traffic / street furniture)
#   large  folder  -> indoor + outdoor    (vehicles, shelves, generators, barrels)
#   medium folder  -> indoor + outdoor    (carts, tools, crates, chairs, desks)
#   small  folder  -> by source:
#       polyhaven  -> indoor + outdoor    (industrial: cans, tools, crates, cement)
#       sketchfab  -> indoor + outdoor    (PPE hard hats)
#       gso        -> indoor only         (consumer goods: games/DVDs/food/electronics)
# When ambiguous, choose the more restrictive (indoor-only) option.
# --------------------------------------------------------------------------- #
def domain_plausible_rule(folder, source):
    folder = (folder or "").strip().lower()
    source = (source or "").strip().lower()
    if folder == "indoor":
        indoor, outdoor = True, False
    elif folder == "road":
        indoor, outdoor = False, True
    elif folder in ("large", "medium"):
        indoor, outdoor = True, True
    elif folder == "small":
        if source in ("polyhaven", "sketchfab"):
            indoor, outdoor = True, True
        else:  # gso consumer goods -> conservative indoor only
            indoor, outdoor = True, False
    else:  # unknown folder -> conservative indoor only
        indoor, outdoor = True, False
    return indoor, outdoor, outdoor  # dp_indoor, dp_outdoor_day, dp_outdoor_night


# --------------------------------------------------------------------------- #
# Silhouette fill_ratio
# --------------------------------------------------------------------------- #
def load_mesh(path):
    g = trimesh.load(path, force="mesh", process=True)
    if isinstance(g, trimesh.Scene):
        parts = [m for m in g.geometry.values() if hasattr(m, "vertices")]
        g = trimesh.util.concatenate(parts) if parts else None
    return g


def _up_axis(mesh):
    """Grounded axis = the axis whose bounds-min is closest to 0."""
    return int(np.argmin(np.abs(mesh.bounds[0])))


def _vertices_zup(mesh):
    u = _up_axis(mesh)
    R = np.eye(3)
    if u == 0:      # X up -> Z
        R = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])[:3, :3]
    elif u == 1:    # Y up -> Z
        R = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])[:3, :3]
    return mesh.vertices @ R.T


def _raster_fill(y, z, faces, res=RASTER_RES):
    ymin, ymax, zmin, zmax = y.min(), y.max(), z.min(), z.max()
    w, h = ymax - ymin, zmax - zmin
    if w < 1e-9 or h < 1e-9:
        return np.nan
    if w >= h:
        W, H = res, max(1, int(round(res * h / w)))
    else:
        W, H = max(1, int(round(res * w / h))), res
    py = (y - ymin) / w * (W - 1)
    pz = (zmax - z) / h * (H - 1)
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    tri = np.stack([py[faces], pz[faces]], axis=-1)
    for t in tri:
        d.polygon([tuple(pt) for pt in t], fill=1)
    return float(np.asarray(img, dtype=bool).sum()) / float(W * H)


def fill_ratio(mesh):
    """Return (mean, std, min, max, per_az_list, method) over N_AZIMUTHS."""
    V0 = _vertices_zup(mesh)
    F = mesh.faces
    big = len(F) > FACE_RASTER_CAP
    base = mesh.copy()
    base.vertices = V0
    ratios, used_raster = [], False
    for k in range(N_AZIMUTHS):
        th = 2.0 * np.pi * k / N_AZIMUTHS
        c, s = np.cos(th), np.sin(th)
        Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
        V = V0 @ Rz.T
        y, z = V[:, 1], V[:, 2]
        by, bz = y.max() - y.min(), z.max() - z.min()
        bbox = by * bz
        r = np.nan
        if not big and bbox > 1e-9:
            try:
                mm = base.copy()
                mm.vertices = V
                sil = float(abs(mm.projected(normal=[1, 0, 0]).area))
                if sil > 0:
                    r = sil / bbox
            except Exception:
                r = np.nan
        if not np.isfinite(r) or r <= 0 or r > 1.05:
            r = _raster_fill(y, z, F)
            used_raster = True
        if np.isfinite(r):
            ratios.append(min(r, 1.0))
    if not ratios:
        return np.nan, np.nan, np.nan, np.nan, [], "failed"
    a = np.array(ratios, dtype=np.float64)
    method = "raster" if big else ("hybrid" if used_raster else "projected")
    return (float(a.mean()), float(a.std()), float(a.min()), float(a.max()),
            [round(float(x), 4) for x in a], method)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry_run", action="store_true", help="compute + print, do not rewrite manifest")
    ap.add_argument("--limit", type=int, default=0, help="process only first N rows (debug)")
    args = ap.parse_args()

    # utf-8-sig strips a leading BOM so the first column key is "folder" not "﻿folder".
    with open(MANIFEST, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    out_fields = fieldnames + [c for c in NEW_COLUMNS if c not in fieldnames]
    extremes, results = [], []
    t0 = time.time()
    for i, row in enumerate(rows):
        if args.limit and i >= args.limit:
            for c in NEW_COLUMNS:
                row.setdefault(c, "")
            continue
        mesh_path = os.path.join(DISTRACTOR_DIR, row["mesh"])
        di, dod, don = domain_plausible_rule(row.get("folder"), row.get("source"))
        try:
            mesh = load_mesh(mesh_path)
            mean, std, mn, mx, per_az, method = fill_ratio(mesh)
            nf = len(mesh.faces)
        except Exception as e:
            mean = std = mn = mx = float("nan")
            per_az, method, nf = [], f"error:{type(e).__name__}", -1
        row["fill_ratio_mean"] = "" if not np.isfinite(mean) else round(mean, 4)
        row["fill_ratio_std"] = "" if not np.isfinite(std) else round(std, 4)
        row["fill_ratio_min"] = "" if not np.isfinite(mn) else round(mn, 4)
        row["fill_ratio_max"] = "" if not np.isfinite(mx) else round(mx, 4)
        row["fill_ratio_method"] = method
        row["dp_indoor"] = int(di)
        row["dp_outdoor_day"] = int(dod)
        row["dp_outdoor_night"] = int(don)
        results.append((row["name"], row["folder"], row["source"], mean, std, method, nf))
        if np.isfinite(mean) and mean < EXTREME_THRESHOLD:
            extremes.append((row["name"], row["folder"], round(mean, 4), round(std, 4)))
        if (i + 1) % 20 == 0 or i + 1 == len(rows):
            print(f"  [{i + 1}/{len(rows)}] {row['name'][:40]:40s} "
                  f"fill={row['fill_ratio_mean']} ({method}) {time.time() - t0:.0f}s")

    if not args.dry_run:
        with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=out_fields)
            w.writeheader()
            w.writerows(rows)
        print(f"\n[WROTE] {MANIFEST}  (+{len(NEW_COLUMNS)} columns)")
    else:
        print("\n[DRY RUN] manifest not written")

    vals = [r[3] for r in results if np.isfinite(r[3])]
    print(f"\n=== fill_ratio over {len(vals)} assets ===")
    if vals:
        v = np.array(vals)
        print(f"  min {v.min():.3f}  p10 {np.percentile(v,10):.3f}  median {np.median(v):.3f}"
              f"  p90 {np.percentile(v,90):.3f}  max {v.max():.3f}")
    print(f"\n=== extreme (<{EXTREME_THRESHOLD}) : {len(extremes)} assets ===")
    for name, folder, mean, std in sorted(extremes, key=lambda x: x[2]):
        print(f"  {mean:.3f} +-{std:.3f}  [{folder}] {name}")
    print(f"\ntotal {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
