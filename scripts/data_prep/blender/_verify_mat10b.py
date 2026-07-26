"""Verify the textured-wood 10-frame test (_mat_test10b).

Per-frame: scene, elevation, conn_cross, front_near, magenta%, and a grain
proxy = luminance std inside the projected pallet cuboid polygon (higher = more
visible wood grain vs flat color). Run with conda pallet-pose (cv2/numpy)."""
import json
import glob
import os

import numpy as np
import cv2

ROOT = "data/pallet/_mat_test10b/train"
SCENE_TONE = {}  # filled from variant logging not available; tone inferred from RGB


def poly_mask(shape, pts):
    m = np.zeros(shape[:2], np.uint8)
    p = np.array(pts, np.int32).reshape(-1, 1, 2)
    cv2.fillConvexPoly(m, cv2.convexHull(p), 255)
    return m


def main():
    jpaths = sorted(glob.glob(os.path.join(ROOT, "json", "*.json")))
    scene_count = {}
    print(f"{'frame':6s} {'scene':9s} {'elev':6s} {'tone(meanRGB inside)':24s} "
          f"{'grain':6s} {'connX':6s} {'frontNear':9s} {'magenta%':8s} verdict")
    print("-" * 100)
    all_pass = True
    for jp in jpaths:
        d = json.load(open(jp))
        o = d["objects"][0]
        fid = os.path.basename(jp).split(".")[0]
        img = cv2.imread(os.path.join(ROOT, "images", fid + ".png"))[:, :, ::-1].astype(np.float32) / 255.0
        scene = o["source_asset"]
        scene_count[scene] = scene_count.get(scene, 0) + 1
        elev = o.get("camera_elevation_deg", float("nan"))
        connx = o.get("edge_connector_crossings", -1)
        front_near = o.get("front_is_camera_near", None)

        # magenta over whole image
        a = img
        magenta = ((a[..., 0] > 0.7) & (a[..., 2] > 0.7) & (a[..., 1] < 0.35)).mean() * 100

        # grain + tone inside projected cuboid
        pts = o["projected_cuboid"]
        mask = poly_mask(img.shape, pts)
        sel = a[mask > 0]
        if sel.size:
            mean_rgb = sel.mean(0)
            lum = sel @ [0.299, 0.587, 0.114]
            grain = float(lum.std())
        else:
            mean_rgb = np.zeros(3); grain = 0.0

        verdict = "PASS"
        if connx not in (0,):
            verdict = "FAIL(connX)"; all_pass = False
        if front_near is not True:
            verdict = "FAIL(frontNear)"; all_pass = False
        if magenta > 0.05:
            verdict = "FAIL(magenta)"; all_pass = False
        if grain < 0.020:
            verdict = "WARN(flat?)"  # not a hard fail; occlusion may reduce visible area

        print(f"{fid:6s} {scene:9s} {elev:6.1f} "
              f"[{mean_rgb[0]:.2f},{mean_rgb[1]:.2f},{mean_rgb[2]:.2f}]{'':9s} "
              f"{grain:6.3f} {connx:6d} {str(front_near):9s} {magenta:8.3f} {verdict}")

    print("-" * 100)
    print("scene dist:", scene_count)
    print("ALL PASS" if all_pass else "SOME FAIL")


if __name__ == "__main__":
    main()
