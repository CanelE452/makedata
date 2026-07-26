"""Floor-fix visual test: fixed camera + pallet, swap ONLY the floor texture
across a labelled set, render each, and stitch a comparison sheet. Confirms each
floor now reads as its label (red_brick=red, tile_white=white, wood=wood grain,
dirt, asphalt) instead of the same grey asphalt (the BG_industrial occlusion bug).

Reproduces gen_dataset_v4 ordering: setup_render -> randomize_background ->
randomize_pallet -> randomize_floor (forced texture) -> _hide_bg_ground (inside
randomize_floor) -> place camera -> CYCLES render.

Run: blender -b synth_data_scene.blend --python _render_floor_fix_test.py
Out: data/pallet/_floor_fix_test/<texture>.png + _sheet.png
"""
import os, sys, math
import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import blender_config as cfg
from blender_config import (ORIENTATION_OVERRIDES, FLOOR_PLANE_NAME,
                            FLOOR_PLANE_Z, FLOOR_PLANE_SIZE)
import randomizers
from randomizers import (setup_render, randomize_background, randomize_pallet,
                         randomize_pallet_appearance, get_obj,
                         _hide_floor_grating, _hide_bg_ground,
                         _ensure_floor_plane, _build_floor_material)
from pallet_geometry import get_pallet_geometry

OUT = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_floor_fix_test")
os.makedirs(OUT, exist_ok=True)
RES = (640, 480)
# one floor per requested label family + a couple of greys for contrast check
FLOORS = ["red_brick", "tile_white", "wood_laminate", "dirt_ground",
          "asphalt_02", "concrete_floor_02"]


def force_floor(plane, name, pallet_pos):
    _hide_floor_grating()
    _hide_bg_ground()
    plane.location = (float(pallet_pos[0]), float(pallet_pos[1]), FLOOR_PLANE_Z)
    plane.hide_render = False
    plane.hide_viewport = False
    uv_scale = max(1.0, FLOOR_PLANE_SIZE / 6.0)   # fixed 6 m repeat for fair compare
    _build_floor_material(plane.data.materials[0], name, uv_scale, (1.0, 1.0, 1.0))
    bpy.context.view_layer.update()


def main():
    import random as _r
    _r.seed(3); np.random.seed(3)
    setup_render()
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 24
    sc.cycles.use_denoising = True
    try:
        sc.cycles.device = "GPU"
    except Exception:
        pass
    sc.render.resolution_x, sc.render.resolution_y = RES

    randomize_background()  # industrial (shows asphalt floors -> our hide kills them)
    pallet_name, _ = randomize_pallet(chosen_idx=2)  # wooden pallet for context
    pobj = get_obj(pallet_name)
    geom = get_pallet_geometry(pallet_name, pobj, ORIENTATION_OVERRIDES)
    pallet_pos = tuple(geom["centroid_world"])
    randomize_pallet_appearance(pobj, pallet_name)
    plane = _ensure_floor_plane()

    # fixed oblique camera (low elevation so the ground fills the frame)
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    elev = math.radians(32.0); az = math.radians(40.0); dist = 4.2
    cam = cen + dist * np.array([math.cos(elev)*math.cos(az),
                                 math.cos(elev)*math.sin(az), math.sin(elev)])
    cam_obj = sc.camera
    cam_obj.location = tuple(cam)
    d = Vector(tuple(cen)) - Vector(tuple(cam))
    cam_obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

    # fixed sun-ish world strength so floors aren't washed out (use existing HDRI)
    bpy.context.view_layer.update()

    paths = []
    means = []
    for name in FLOORS:
        force_floor(plane, name, pallet_pos)
        p = os.path.join(OUT, f"{name}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
        print(f"  rendered {name} -> {p}")

    # stitch sheet + measure mean BGR of the lower-center floor region
    try:
        import cv2
        imgs = []
        for name, p in zip(FLOORS, paths):
            im = cv2.imread(p)
            if im is None:
                continue
            h, w = im.shape[:2]
            roi = im[int(h*0.70):int(h*0.95), int(w*0.30):int(w*0.70)]
            b, g, r = [float(roi[..., c].mean()) for c in range(3)]
            means.append((name, r, g, b))
            cv2.putText(im, f"{name}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 255, 0), 2)
            cv2.putText(im, f"floor RGB={r:.0f},{g:.0f},{b:.0f}", (8, h - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            imgs.append(im)
        if imgs:
            cols = 3
            rows = (len(imgs) + cols - 1) // cols
            h, w = imgs[0].shape[:2]
            sheet = np.zeros((rows * h, cols * w, 3), np.uint8)
            for i, im in enumerate(imgs):
                ry, cx = divmod(i, cols)
                sheet[ry*h:(ry+1)*h, cx*w:(cx+1)*w] = im
            sp = os.path.join(OUT, "_sheet.png")
            cv2.imwrite(sp, sheet)
            print(f"  sheet -> {sp}")
        print("\n=== floor ROI mean RGB per texture ===")
        for name, r, g, b in means:
            print(f"  {name:18s} R={r:6.1f} G={g:6.1f} B={b:6.1f}")
    except Exception as e:
        print(f"  [sheet] skipped ({e})")


if __name__ == "__main__":
    main()
