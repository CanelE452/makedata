"""GPU-free dump: which mesh does the camera actually see as the near floor?

_render_floor_compare swaps the `base_m` material, but DIAG_A_red showed the
near-ground floor the camera sees is a SEPARATE grating mesh, not base_m. This
script reproduces the exact pallet + camera of _render_floor_compare, then for a
grid of rays through the image plane reports the FIRST mesh + material hit. That
tells us the real floor mesh name(s) to retexture (or which grating to hide).

No render => safe to run alongside nothing GPU-heavy. Output: stdout only.
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
from blender_config import ORIENTATION_OVERRIDES
import randomizers
from pallet_geometry import get_pallet_geometry, snap_object_to_ground, get_normalized_scale
import _render_floor_compare as R


def main():
    R.setup_fixed_world()
    R.hide_all_pallets()
    R.show_pallet(R.PALLET_NAME)
    pobj = R.get_obj(R.PALLET_NAME)
    pobj.scale = tuple(get_normalized_scale(pobj, ORIENTATION_OVERRIDES.get(R.PALLET_NAME, (0, 0, 0))))
    pobj.location = (-9.0, -7.0, pobj.location[2])
    snap_object_to_ground(pobj, ground_z=0.0)
    bpy.context.view_layer.update()
    geom = get_pallet_geometry(R.PALLET_NAME, pobj, ORIENTATION_OVERRIDES)
    cam = R.make_camera(geom)
    R.set_marks_visible(False)
    R.hide_grating()  # hide same fence meshes the render hides, then see what's left

    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()

    # Build camera rays for a coarse grid over the image (skip the pallet center).
    cam_data = cam.data
    res_x, res_y = R.RES
    # Camera frame corners at distance 1 (Blender view_frame gives -Z forward dirs).
    frame = cam_data.view_frame(scene=scene)  # 4 corners in cam space
    mw = cam.matrix_world
    origin = mw.translation

    # interpolate grid in camera-space frame
    tr, br, bl, tl = frame  # order: top-right, bottom-right, bottom-left, top-left
    GX, GY = 9, 7
    hits = {}  # (objname, matname) -> count
    nearest = {}  # objname -> min distance
    pallet_children = set()
    po = R.get_obj(R.PALLET_NAME)
    for m in [po, *po.children_recursive]:
        pallet_children.add(m.name)

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
                key = ("(sky/none)", "-")
                hits[key] = hits.get(key, 0) + 1
                continue
            matname = "-"
            try:
                if obj.data.materials and idx < len(obj.data.polygons):
                    mi = obj.data.polygons[idx].material_index
                    m = obj.data.materials[mi]
                    matname = m.name if m else "-"
            except Exception:
                pass
            dist = (loc - origin).length
            key = (obj.name, matname)
            hits[key] = hits.get(key, 0) + 1
            if obj.name not in nearest or dist < nearest[obj.name]:
                nearest[obj.name] = dist

    print("\n=== RAY HITS (image grid 9x7 = 63 rays) ===")
    for (objn, matn), c in sorted(hits.items(), key=lambda kv: -kv[1]):
        tag = " <PALLET>" if objn in pallet_children else ""
        d = nearest.get(objn, float("nan"))
        print(f"  {c:3d} rays  obj={objn:32s} mat={matn:20s} nearDist={d:.2f}{tag}")

    # Also list all meshes whose bbox covers the near-camera ground region, with z range.
    print("\n=== LARGE LOW MESHES (candidate floors / gratings) ===")
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        ws = [o.matrix_world @ Vector(c) for c in o.bound_box]
        zs = [v.z for v in ws]
        xs = [v.x for v in ws]
        ys = [v.y for v in ws]
        dx, dy = max(xs) - min(xs), max(ys) - min(ys)
        if min(zs) < 1.0 and dx > 4 and dy > 4:
            mats = [m.name if m else None for m in o.data.materials]
            vis = "HIDDEN" if o.hide_render else "shown"
            print(f"  {vis:6s} {o.name:34s} z[{min(zs):.2f},{max(zs):.2f}] "
                  f"size[{dx:.1f}x{dy:.1f}] mats={mats}")


if __name__ == "__main__":
    main()
