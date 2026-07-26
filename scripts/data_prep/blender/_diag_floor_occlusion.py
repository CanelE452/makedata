"""Diagnose the "floor is always grey regardless of label" bug.

User hypothesis: the fresh FloorRandPlane (z=-6mm) is occluded by an UN-hidden
ground mesh that belongs to the BG_industrial background. randomize_background()
runs EVERY frame and re-shows ALL BG_industrial children (set_render_visibility
-> hide_render=False on the whole hierarchy). _hide_floor_grating() runs ONCE
(cached) and only hides 3 meshes. So from frame 2 onward any industrial ground
mesh re-appears at z~=0 and covers the plane.

This script reproduces the EXACT gen_dataset_v4 ordering for one frame:
  setup_render -> randomize_background('industrial') -> randomize_pallet
  -> randomize_floor -> sample_camera_elev -> raycast the camera grid.

Outputs (stdout only, NO render here = GPU-safe):
  (1) all z~=0 floor/ground meshes: name, z-range, xy-size, hide_render, mats
  (2) what the camera grid actually hits (first mesh per ray) + plane hit count
  (3) explicit verdict: is the plane visible or occluded, and by what.

Run: blender -b synth_data_scene.blend --python _diag_floor_occlusion.py
"""
import os
import sys
import math

import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import blender_config as cfg
from blender_config import ORIENTATION_OVERRIDES, FLOOR_PLANE_NAME, FLOOR_PLANE_Z
import randomizers
from randomizers import (
    setup_render, randomize_background, randomize_pallet,
    randomize_pallet_appearance, randomize_floor, get_obj,
)
from pallet_geometry import get_pallet_geometry


def list_low_meshes(tag):
    print(f"\n=== [{tag}] meshes spanning z in [-0.20, 0.30] (candidate floors) ===")
    rows = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        ws = [o.matrix_world @ Vector(c) for c in o.bound_box]
        zs = [v.z for v in ws]
        xs = [v.x for v in ws]
        ys = [v.y for v in ws]
        zmin, zmax = min(zs), max(zs)
        # mesh that has surface near ground level
        if zmin > 0.30 or zmax < -0.20:
            continue
        dx, dy = max(xs) - min(xs), max(ys) - min(ys)
        # only "floor-like": reasonably wide footprint
        if dx < 1.0 and dy < 1.0:
            continue
        mats = [m.name if m else None for m in o.data.materials]
        rows.append((o.name, zmin, zmax, dx, dy, o.hide_render, mats))
    rows.sort(key=lambda r: (r[5], -(r[3] * r[4])))  # shown first, biggest first
    print(f"  {'mesh':36s} {'z_min':>7s} {'z_max':>7s} {'dx':>6s} {'dy':>6s} "
          f"{'hide_r':>6s}  mats")
    for nm, zmn, zmx, dx, dy, hid, mats in rows:
        h = "HIDDEN" if hid else "shown"
        print(f"  {nm:36s} {zmn:7.3f} {zmx:7.3f} {dx:6.1f} {dy:6.1f} {h:>6s}  {mats}")
    return rows


def raycast_camera_grid(geom):
    scene = bpy.context.scene
    cam = scene.camera
    dg = bpy.context.evaluated_depsgraph_get()
    cam_data = cam.data
    frame = cam_data.view_frame(scene=scene)
    mw = cam.matrix_world
    origin = mw.translation
    tr, br, bl, tl = frame
    GX, GY = 13, 11
    hits = {}
    nearest = {}
    plane_name = FLOOR_PLANE_NAME
    for iy in range(GY):
        fy = iy / (GY - 1)
        left = bl.lerp(tl, fy)
        right = br.lerp(tr, fy)
        for ix in range(GX):
            fx = ix / (GX - 1)
            pt_cam = left.lerp(right, fx)
            world_pt = mw @ pt_cam
            direction = (world_pt - origin).normalized()
            hit, loc, nrm, idx, obj, mtx = scene.ray_cast(dg, origin, direction)
            if not hit:
                hits["(sky/none)"] = hits.get("(sky/none)", 0) + 1
                continue
            n = obj.name
            hits[n] = hits.get(n, 0) + 1
            d = (loc - origin).length
            if n not in nearest or d < nearest[n]:
                nearest[n] = d
    total = GX * GY
    print(f"\n=== CAMERA RAY HITS ({GX}x{GY}={total} rays through image plane) ===")
    for n, c in sorted(hits.items(), key=lambda kv: -kv[1]):
        d = nearest.get(n, float("nan"))
        tag = "  <-- FRESH PLANE" if n == plane_name else ""
        print(f"  {c:3d} rays ({100*c/total:4.1f}%)  {n:34s} nearDist={d:6.2f}{tag}")
    return hits


def main():
    import random as _r
    _r.seed(7)
    np.random.seed(7)
    setup_render()

    # ---- mimic gen_dataset_v4 retry loop ordering for one accepted frame ----
    bg = randomize_background()
    print(f"\n[BG] chosen background = {bg}")

    pallet_name, _ = randomize_pallet(chosen_idx=1)
    pobj = get_obj(pallet_name)
    geom = get_pallet_geometry(pallet_name, pobj, ORIENTATION_OVERRIDES)
    pallet_pos = tuple(geom["centroid_world"])
    randomize_pallet_appearance(pobj, pallet_name)

    # snapshot BEFORE floor randomization
    list_low_meshes("AFTER randomize_background, BEFORE randomize_floor")

    floor_info = randomize_floor(pallet_pos)
    print(f"\n[FLOOR] {floor_info}")
    plane = get_obj(FLOOR_PLANE_NAME)
    if plane is not None:
        print(f"[FLOOR] FloorRandPlane loc={tuple(round(v,3) for v in plane.location)} "
              f"hide_render={plane.hide_render}")

    list_low_meshes("AFTER randomize_floor (frame 1)")

    # ---- now SIMULATE frame 2: randomize_background runs again, floor cached ----
    print("\n############ SIMULATING FRAME 2 (bg re-shown, grating cached-hide) ############")
    randomizers._floor_force_state["i"] = 1
    bg2 = randomize_background()
    floor_info2 = randomize_floor(pallet_pos)
    print(f"[FRAME2] bg={bg2} floor={floor_info2['floor_texture']}")
    rows2 = list_low_meshes("FRAME 2 (this is what training frames 2..N look like)")

    # build the camera the same way gen does, aim at pallet centroid
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    elev = math.radians(45.0)
    az = math.radians(35.0)
    dist = 4.0
    cam = cen + dist * np.array([math.cos(elev)*math.cos(az),
                                 math.cos(elev)*math.sin(az),
                                 math.sin(elev)])
    cam_obj = bpy.context.scene.camera
    cam_obj.location = tuple(cam)
    d = Vector(tuple(cen)) - Vector(tuple(cam))
    cam_obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()

    hits = raycast_camera_grid(geom)

    # ---- verdict ----
    plane_hits = hits.get(FLOOR_PLANE_NAME, 0)
    ground_occluders = [r for r in rows2
                        if (not r[5]) and r[0] != FLOOR_PLANE_NAME
                        and r[1] >= FLOOR_PLANE_Z - 0.05]  # at/above plane, shown
    print("\n=== VERDICT ===")
    print(f"  FloorRandPlane ray hits (frame2 camera) = {plane_hits}")
    print(f"  shown ground meshes AT/ABOVE the plane (would occlude): "
          f"{[r[0] for r in ground_occluders]}")
    if plane_hits == 0 and ground_occluders:
        print("  => PLANE IS OCCLUDED by background ground mesh(es). "
              "User hypothesis CONFIRMED.")
    elif plane_hits > 0:
        print("  => Plane IS visible to camera; grey likely a texture/UV issue.")


if __name__ == "__main__":
    main()
