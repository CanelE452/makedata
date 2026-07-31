"""v2 PILOT 2k — FULL-SET 9kp cuboid overlay (bpy-FREE: PIL + numpy only).

Draws a 9-keypoint cuboid overlay for EVERY frame of the pilot render
(data/pallet/archive/superseded_runs/_v2_pilot_2k: labels/ + rgb/, idx 0..1999 continuous) so the whole
set can be eyeballed, not just the 84 audit samples. NO Blender, NO re-render, NO
commit. Reads on-disk labels/rgb only and draws 2D.

Drawing style is copied verbatim from _v2_pilot_audit.py::_draw_cuboid_overlay so
the full-set overlays match the audit overlays:
  FRONT face (corners 0-1-2-3) = thick red   -> should track the camera-facing side
  REAR  face (corners 4-5-6-7) = thin  blue
  connectors (0-4,1-5,2-6,3-7) = thin  yellow
  corner dots numbered 0..7, centroid = green dot.

Header per frame: idx, pallet, elevation(actual), azimuth(target), front_is_camera_near,
all_pass gate, front_visibility_cos, facing_margin.

Run:
  C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/_v2_pilot_overlay_all.py \
      --dir data/pallet/archive/superseded_runs/_v2_pilot_2k
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFile

# Some pilot RGBs can be truncated on disk; allow PIL to load what it can so a
# corrupt frame yields a (partial) overlay instead of crashing the whole batch.
ImageFile.LOAD_TRUNCATED_IMAGES = True

# 9kp cuboid edges (same convention as the audit).
_FRONT_E = [(0, 1), (1, 2), (2, 3), (3, 0)]
_REAR_E = [(4, 5), (5, 6), (6, 7), (7, 4)]
_CONN_E = [(0, 4), (1, 5), (2, 6), (3, 7)]


def _front_is_camera_near(obj, cam_loc):
    """FRONT face (cuboid 0-3) centroid nearer to camera than REAR (4-7)?"""
    C = np.array(obj["cuboid"], dtype=np.float64)
    cam = np.array(cam_loc, dtype=np.float64)
    df = float(np.linalg.norm(C[:4].mean(0) - cam))
    dr = float(np.linalg.norm(C[4:].mean(0) - cam))
    return bool(df < dr)


def _draw_overlay(rgb_path, lab, out_path):
    im = Image.open(rgb_path).convert("RGB")
    dr = ImageDraw.Draw(im)
    obj = lab["objects"][0]
    pc = obj["projected_cuboid"]
    cc = obj["projected_cuboid_centroid"]

    def L(a, b, col, w=3):
        dr.line([tuple(pc[a]), tuple(pc[b])], fill=col, width=w)

    for a, b in _REAR_E:
        L(a, b, (60, 120, 255), 2)      # rear = blue
    for a, b in _CONN_E:
        L(a, b, (255, 210, 0), 2)       # connectors = yellow
    for a, b in _FRONT_E:
        L(a, b, (255, 30, 30), 4)       # FRONT = thick red
    for k, (x, y) in enumerate(pc):
        col = (255, 30, 30) if k < 4 else (60, 120, 255)
        dr.ellipse([x - 5, y - 5, x + 5, y + 5], fill=col, outline=(255, 255, 255))
        dr.text((x + 6, y - 6), str(k), fill=(255, 255, 0))
    dr.ellipse([cc[0] - 4, cc[1] - 4, cc[0] + 4, cc[1] + 4], fill=(0, 255, 0))

    vl = obj.get("v2_labels", {})
    gates = obj.get("safety_gates", {})
    near = _front_is_camera_near(obj, lab["camera_data"]["location_worldframe"])
    idx = lab.get("_idx")
    hdr = (f"f{idx} {obj['name']} elev={vl.get('elevation_deg_actual')} "
           f"az={vl.get('azimuth_deg_target')} near={near} all_pass={gates.get('all_pass')} "
           f"fcos={obj.get('front_visibility_cos')} fmarg={obj.get('facing_margin')}")
    dr.rectangle([0, 0, im.width, 16], fill=(0, 0, 0))
    dr.text((3, 3), hdr, fill=(255, 255, 255))
    im.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/pallet/archive/superseded_runs/_v2_pilot_2k")
    ap.add_argument("--n", type=int, default=2000, help="number of frames idx 0..n-1")
    args = ap.parse_args()

    d = args.dir if os.path.isabs(args.dir) else os.path.abspath(args.dir)
    out_dir = os.path.join(d, "overlay_all")
    os.makedirs(out_dir, exist_ok=True)

    made = 0
    missing = []
    corrupt = []
    for idx in range(args.n):
        lp = os.path.join(d, "labels", f"f{idx:04d}_label.json")
        rp = os.path.join(d, "rgb", f"f{idx:04d}_rgb.png")
        if not (os.path.isfile(lp) and os.path.isfile(rp)):
            missing.append(idx)
            continue
        lab = json.load(open(lp, encoding="utf-8"))
        if not lab.get("objects"):
            missing.append(idx)
            continue
        lab["_idx"] = idx
        try:
            _draw_overlay(rp, lab, os.path.join(out_dir, f"f{idx:04d}.png"))
        except OSError as e:
            print(f"[overlay] WARN corrupt rgb idx {idx}: {e}", flush=True)
            corrupt.append(idx)
            continue
        made += 1
        if made % 100 == 0 or idx == args.n - 1:
            print(f"[overlay] {made}/{args.n} -> {out_dir}", flush=True)

    print(f"\n[overlay] DONE made={made} missing={len(missing)} corrupt={len(corrupt)}")
    if missing:
        print(f"[overlay] missing idx (first 20): {missing[:20]}")
    if corrupt:
        print(f"[overlay] corrupt idx: {corrupt}")
    print(f"[overlay] out_dir = {out_dir}")


if __name__ == "__main__":
    main()
