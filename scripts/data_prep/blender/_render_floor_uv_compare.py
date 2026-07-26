"""Floor UV-scale comparison: fixed pallet (1.1 m) + camera + HDRI, sweep
metres_per_tile across several values for a few pattern-rich floors so the user
can pick a value where the floor pattern reads SMALLER than the pallet.

metres_per_tile = world metres spanned by ONE full texture image (which itself
holds many bricks/tiles). uv_scale = FLOOR_PLANE_SIZE / metres_per_tile.
Smaller metres_per_tile -> smaller on-floor pattern relative to the pallet.

Renders a grid sheet: rows = texture, cols = metres_per_tile. Same camera, so
the pallet stays the same size; only the floor pattern scale changes.

Run: blender -b synth_data_scene.blend --python _render_floor_uv_compare.py
Out: data/pallet/_floor_uv_test/<tex>_mpt<val>.png + _sheet.png
"""
import os, sys, math
import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import blender_config as cfg
from blender_config import ORIENTATION_OVERRIDES, FLOOR_PLANE_Z, FLOOR_PLANE_SIZE
from randomizers import (setup_render, randomize_background, randomize_pallet,
                         randomize_pallet_appearance, get_obj,
                         _hide_floor_grating, _hide_bg_ground,
                         _ensure_floor_plane, _build_floor_material)
from pallet_geometry import get_pallet_geometry

OUT = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_floor_uv_test")
os.makedirs(OUT, exist_ok=True)
RES = (640, 480)

# pattern-rich, easy-to-read floors so tile/brick size is obvious vs the pallet
TEXTURES = ["red_brick", "tile_white", "cobblestone_floor_08"]
# world metres per full texture repeat. current range is 4-9 (pattern too big).
MPT_VALUES = [1.0, 1.5, 2.0, 3.0, 6.0]


def force_floor(plane, name, mpt, pallet_pos):
    _hide_floor_grating()
    _hide_bg_ground()
    plane.location = (float(pallet_pos[0]), float(pallet_pos[1]), FLOOR_PLANE_Z)
    plane.hide_render = False
    plane.hide_viewport = False
    uv_scale = max(1.0, FLOOR_PLANE_SIZE / mpt)
    _build_floor_material(plane.data.materials[0], name, uv_scale, (1.0, 1.0, 1.0))
    bpy.context.view_layer.update()


def main():
    import random as _r
    _r.seed(7); np.random.seed(7)
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

    randomize_background()
    pallet_name, _ = randomize_pallet(chosen_idx=2)  # wooden pallet, ~1.1 m
    pobj = get_obj(pallet_name)
    geom = get_pallet_geometry(pallet_name, pobj, ORIENTATION_OVERRIDES)
    pallet_pos = tuple(geom["centroid_world"])
    randomize_pallet_appearance(pobj, pallet_name)
    plane = _ensure_floor_plane()

    # fixed oblique camera: low-ish elevation so a wide span of floor is visible
    # around the pallet, making pattern-vs-pallet scale obvious.
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    elev = math.radians(34.0); az = math.radians(40.0); dist = 4.0
    cam = cen + dist * np.array([math.cos(elev)*math.cos(az),
                                 math.cos(elev)*math.sin(az), math.sin(elev)])
    cam_obj = sc.camera
    cam_obj.location = tuple(cam)
    d = Vector(tuple(cen)) - Vector(tuple(cam))
    cam_obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()

    grid = {}  # (tex, mpt) -> path
    for name in TEXTURES:
        for mpt in MPT_VALUES:
            force_floor(plane, name, mpt, pallet_pos)
            p = os.path.join(OUT, f"{name}_mpt{mpt:.1f}.png")
            sc.render.filepath = p
            bpy.ops.render.render(write_still=True)
            grid[(name, mpt)] = p
            print(f"  rendered {name} mpt={mpt:.1f} -> {p}")

    # stitch grid sheet: rows = texture, cols = mpt. Annotate each cell.
    try:
        import cv2
        cell_imgs = {}
        floor_std = {}
        for (name, mpt), p in grid.items():
            im = cv2.imread(p)
            if im is None:
                continue
            h, w = im.shape[:2]
            roi = im[int(h*0.72):int(h*0.96), int(w*0.28):int(w*0.72)]
            # spatial stddev of grey = pattern contrast (mush -> low std)
            grey = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
            std = float(grey.std())
            floor_std[(name, mpt)] = std
            cv2.putText(im, f"{name}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 255, 0), 2)
            cv2.putText(im, f"mpt={mpt:.1f}m  std={std:.1f}", (8, h - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
            cell_imgs[(name, mpt)] = im

        if cell_imgs:
            h, w = next(iter(cell_imgs.values())).shape[:2]
            rows, cols = len(TEXTURES), len(MPT_VALUES)
            sheet = np.zeros((rows * h, cols * w, 3), np.uint8)
            for ri, name in enumerate(TEXTURES):
                for ci, mpt in enumerate(MPT_VALUES):
                    im = cell_imgs.get((name, mpt))
                    if im is None:
                        continue
                    sheet[ri*h:(ri+1)*h, ci*w:(ci+1)*w] = im
            sp = os.path.join(OUT, "_sheet.png")
            cv2.imwrite(sp, sheet)
            print(f"  sheet -> {sp}")

        print("\n=== floor pattern contrast (grey std in floor ROI) ===")
        print("  higher std = pattern visible; collapsing std = grey mush")
        print(f"  {'texture':22s} " + " ".join(f"mpt{m:.1f}" for m in MPT_VALUES))
        for name in TEXTURES:
            vals = " ".join(f"{floor_std.get((name,m),0):6.1f}" for m in MPT_VALUES)
            print(f"  {name:22s} {vals}")
    except Exception as e:
        print(f"  [sheet] skipped ({e})")


if __name__ == "__main__":
    main()
