"""Exhaustive verification of the v4 re-pilot (background diversity + relaxed raycast).

Checks per frame:
  - simple-quad: front face 0-1-2-3 polygon is non-self-intersecting
  - 0->1 is the TOP edge (id0,id1 higher on image than id2,id3)  [smaller y]
  - id0 is LEFT of id1 (x0 < x1)
  - connector crossings == 0 (4 connector edges 0-4,1-5,2-6,3-7 pairwise non-crossing)
  - front_is_camera_near == True
  - magenta scan on the rendered image (fraction of strongly magenta pixels)
  - records raycast_visibility + whether it is a partial-occlusion frame (<0.55)
Run with system python (needs numpy + PIL). No Blender.
"""
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = sys.argv[1] if len(sys.argv) > 1 else "data/pallet/training_data_v4"

CONNECTOR_EDGES = [(0, 4), (1, 5), (2, 6), (3, 7)]


def seg_proper_intersect(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def quad_self_intersect(q):
    # polygon edges 0-1,1-2,2-3,3-0; check the two diagon* non-adjacent pairs
    e = [(0, 1), (1, 2), (2, 3), (3, 0)]
    for i in range(4):
        for j in range(i + 1, 4):
            a, b = e[i]; c, d = e[j]
            if len({a, b, c, d}) < 4:
                continue
            if seg_proper_intersect(q[a], q[b], q[c], q[d]):
                return True
    return False


def conn_cross(uv8):
    n = 0
    for i in range(4):
        for j in range(i + 1, 4):
            a, b = CONNECTOR_EDGES[i]; c, d = CONNECTOR_EDGES[j]
            if seg_proper_intersect(uv8[a], uv8[b], uv8[c], uv8[d]):
                n += 1
    return n


def magenta_frac(img_path):
    im = Image.open(img_path).convert("RGB")
    im = im.resize((128, 96))
    a = np.asarray(im, dtype=np.int32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # strong magenta: high R, high B, low G
    mag = (r > 180) & (b > 180) & (g < 90)
    return float(mag.mean())


def reproject_check(j):
    """Recompute projection of the 8 3D cuboid corners with the stored camera and
    compare to stored projected_cuboid -> confirms GT keypoints are pure geometry
    (occlusion-independent)."""
    obj = j["objects"][0]
    cam = j["camera_data"]
    K = np.array([[cam["intrinsics"]["fx"], 0, cam["intrinsics"]["cx"]],
                  [0, cam["intrinsics"]["fy"], cam["intrinsics"]["cy"]],
                  [0, 0, 1]], dtype=np.float64)
    cub_world = np.array(obj["cuboid"], dtype=np.float64)  # 8x3 world (perm-ordered)
    cam_pos = np.array(cam["location_worldframe"], dtype=np.float64)
    look_at = cub_world.mean(axis=0)
    # EXACT build_view_matrix (OpenCV: R_w2c = [right, -cam_up, forward])
    forward = look_at - cam_pos; forward = forward / np.linalg.norm(forward)
    up = np.array([0, 0, 1.0])
    right = np.cross(forward, up); right = right / np.linalg.norm(right)
    cam_up = np.cross(right, forward)
    R = np.stack([right, -cam_up, forward], axis=0)
    t = -R @ cam_pos
    pc = (R @ cub_world.T).T + t
    proj = (K @ pc.T).T
    uv = proj[:, :2] / proj[:, 2:3]
    stored = np.array(obj["projected_cuboid"], dtype=np.float64)
    err = np.linalg.norm(uv - stored, axis=1)
    return float(err.max()), float(err.mean())


def verify_split(split):
    jdir = os.path.join(ROOT, split, "json")
    idir = os.path.join(ROOT, split, "images")
    rows = []
    for jp in sorted(glob.glob(os.path.join(jdir, "*.json"))):
        fid = os.path.basename(jp)[:-5]
        j = json.load(open(jp))
        obj = j["objects"][0]
        uv = np.array(obj["projected_cuboid"], dtype=np.float64)  # 8x2
        q = uv[[0, 1, 2, 3]]
        si = quad_self_intersect(q)
        top_ok = (uv[0][1] + uv[1][1]) / 2 < (uv[2][1] + uv[3][1]) / 2  # smaller y = higher
        left_ok = uv[0][0] < uv[1][0]
        cx = conn_cross(uv)
        front_near = bool(obj.get("front_is_camera_near", False))
        rayv = float(obj.get("raycast_visibility", -1))
        vis = float(obj.get("visibility", -1))
        area = None
        img_path = os.path.join(idir, fid + ".png")
        mfrac = magenta_frac(img_path) if os.path.isfile(img_path) else -1
        rmax, rmean = reproject_check(j)
        hdri = j["camera_data"].get("hdri_environment", "?")
        rows.append(dict(fid=fid, si=si, top=top_ok, left=left_ok, cx=cx,
                         front_near=front_near, ray=rayv, vis=vis, mag=mfrac,
                         reproj_max=rmax, hdri=hdri,
                         partial=(0.0 <= rayv < 0.55)))
    return rows


def main():
    allrows = []
    for split in ("train", "val"):
        rows = verify_split(split)
        allrows += [(split, r) for r in rows]
        n = len(rows)
        si_bad = sum(r["si"] for r in rows)
        top_bad = sum(not r["top"] for r in rows)
        left_bad = sum(not r["left"] for r in rows)
        cx_bad = sum(r["cx"] > 0 for r in rows)
        fn_bad = sum(not r["front_near"] for r in rows)
        mag_bad = sum(r["mag"] > 0.02 for r in rows)
        reproj_bad = sum(r["reproj_max"] > 1.0 for r in rows)
        partial = sum(r["partial"] for r in rows)
        rays = [r["ray"] for r in rows]
        hdris = {}
        for r in rows:
            hdris[r["hdri"]] = hdris.get(r["hdri"], 0) + 1
        print(f"\n===== {split}  (n={n}) =====")
        print(f"  self-intersect quad : {si_bad} bad  (want 0)")
        print(f"  0->1 TOP edge       : {top_bad} bad  (want 0)")
        print(f"  id0 LEFT of id1     : {left_bad} bad  (want 0)")
        print(f"  connector_cross>0   : {cx_bad} bad  (want 0)")
        print(f"  front_is_cam_near F : {fn_bad} bad  (want 0)")
        print(f"  magenta>2% pixels   : {mag_bad} bad  (want 0)")
        print(f"  reproj GT err>1px   : {reproj_bad} bad  (want 0)  "
              f"max={max(r['reproj_max'] for r in rows):.3f}px")
        print(f"  partial-occ(<0.55)  : {partial}/{n}  ({100*partial/n:.0f}%)")
        print(f"  raycast vis range   : {min(rays):.2f}..{max(rays):.2f} "
              f"mean {np.mean(rays):.2f}")
        print(f"  HDRI distribution   : {hdris}")
    # list the most-occluded frames (lowest ray) for visual spot-check
    flat = [r for _, r in allrows]
    flat.sort(key=lambda r: r["ray"])
    print("\n  most-occluded frames (lowest raycast vis), for crop spot-check:")
    for r in flat[:8]:
        print(f"    {r['fid']} ray={r['ray']:.2f} vis={r['vis']:.2f} "
              f"reproj_max={r['reproj_max']:.3f} hdri={r['hdri']}")


if __name__ == "__main__":
    main()
