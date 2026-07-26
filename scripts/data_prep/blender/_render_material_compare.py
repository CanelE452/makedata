"""Headless before/after material comparison for scene_1/2/3 pallets.

Renders the SAME camera + SAME HDRI for each pallet (Pallet_1/2/3) under
several material palettes so the user can pick a realistic look.

Run (separate Blender process, does NOT touch any MCP cube scene):
  "/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
     data/pallet/blender_scene/synth_data_scene.blend \
     --python scripts/data_prep/blender/_render_material_compare.py

Output: data/pallet/_material_compare/{pallet}_{palette}.png  +  contact sheets.
"""
import os
import sys
import math

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import blender_config as cfg
from blender_config import ORIENTATION_OVERRIDES
import randomizers
from pallet_geometry import get_pallet_geometry, snap_object_to_ground

OUT_DIR = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_material_compare")
os.makedirs(OUT_DIR, exist_ok=True)

# Fixed HDRI + camera so only material changes between renders.
FIXED_HDRI = "empty_warehouse_01_2k.hdr"   # neutral indoor warehouse
FIXED_HDRI_STRENGTH = 0.9                   # slightly above pipeline 0.6 so material reads
RES = (640, 480)

# ---------------------------------------------------------------------------
# Palettes. Each maps a model -> list of variant dicts (name/base_color/rough/spec).
# "current" = exactly what config/synthetic/blender.yaml ships today.
# ---------------------------------------------------------------------------
PAL_CURRENT = {
    "plastic": [
        {"name": "black",     "base_color": [0.02, 0.02, 0.02], "roughness": 0.72, "specular": 0.20},
        {"name": "dark_green","base_color": [0.02, 0.06, 0.03], "roughness": 0.60, "specular": 0.28},
        {"name": "dark_gray", "base_color": [0.08, 0.08, 0.09], "roughness": 0.65, "specular": 0.24},
    ],
    "wood": [
        {"name": "dark_stain","base_color": [0.06, 0.04, 0.02], "roughness": 0.82, "specular": 0.14},
        {"name": "ebony",     "base_color": [0.03, 0.03, 0.03], "roughness": 0.78, "specular": 0.16},
    ],
}

# Option A: realistic wood-tone pallet (real warehouse wooden pallet, mid brown).
PAL_WOOD = {
    "plastic": [  # treat scene_1 ALSO as wood-look (real EUR pallets are wood)
        {"name": "pine",      "base_color": [0.34, 0.23, 0.12], "roughness": 0.78, "specular": 0.18},
        {"name": "oak",       "base_color": [0.40, 0.27, 0.15], "roughness": 0.75, "specular": 0.20},
        {"name": "weathered", "base_color": [0.30, 0.24, 0.17], "roughness": 0.85, "specular": 0.14},
    ],
    "wood": [
        {"name": "pine",      "base_color": [0.34, 0.23, 0.12], "roughness": 0.78, "specular": 0.18},
        {"name": "oak",       "base_color": [0.40, 0.27, 0.15], "roughness": 0.75, "specular": 0.20},
        {"name": "walnut",    "base_color": [0.26, 0.16, 0.09], "roughness": 0.80, "specular": 0.16},
        {"name": "weathered", "base_color": [0.30, 0.24, 0.17], "roughness": 0.85, "specular": 0.14},
    ],
}

# Option B: keep scene_1 as a realistic *plastic* pallet (mid-tone, not near-black),
# scene_2/3 wood. Plastic pallets in industry: blue/black/gray but NOT pitch black.
PAL_MIXED = {
    "plastic": [
        {"name": "ind_blue",  "base_color": [0.06, 0.10, 0.22], "roughness": 0.45, "specular": 0.35},
        {"name": "mid_gray",  "base_color": [0.18, 0.18, 0.19], "roughness": 0.50, "specular": 0.30},
        {"name": "graphite",  "base_color": [0.10, 0.10, 0.11], "roughness": 0.55, "specular": 0.30},
    ],
    "wood": [
        {"name": "pine",      "base_color": [0.34, 0.23, 0.12], "roughness": 0.78, "specular": 0.18},
        {"name": "oak",       "base_color": [0.40, 0.27, 0.15], "roughness": 0.75, "specular": 0.20},
        {"name": "walnut",    "base_color": [0.26, 0.16, 0.09], "roughness": 0.80, "specular": 0.16},
    ],
}

# Option C: wood with brightness DR (lighter + darker around realistic mean) so the
# trained model is robust to unseen pallets. Still no fluorescent / pure-white.
PAL_WOOD_DR = {
    "plastic": PAL_WOOD["wood"],
    "wood": [
        {"name": "light_birch","base_color": [0.50, 0.38, 0.24], "roughness": 0.72, "specular": 0.20},
        {"name": "pine",       "base_color": [0.34, 0.23, 0.12], "roughness": 0.78, "specular": 0.18},
        {"name": "oak",        "base_color": [0.40, 0.27, 0.15], "roughness": 0.75, "specular": 0.20},
        {"name": "walnut",     "base_color": [0.26, 0.16, 0.09], "roughness": 0.80, "specular": 0.16},
        {"name": "dark_used",  "base_color": [0.18, 0.13, 0.08], "roughness": 0.84, "specular": 0.14},
        {"name": "faded_gray", "base_color": [0.33, 0.30, 0.26], "roughness": 0.86, "specular": 0.13},
    ],
}

PALETTES = [
    ("current",  PAL_CURRENT),
    ("woodA",    PAL_WOOD),
    ("mixedB",   PAL_MIXED),
    ("wood_drC", PAL_WOOD_DR),
]

# Model -> color group (matches config). Pallet_1 plastic, 2/3 wood.
GROUP = {"Pallet_1": "plastic", "Pallet_2": "wood", "Pallet_3": "wood"}
SOURCE = {"Pallet_1": "scene_1.usd", "Pallet_2": "scene_2.usd", "Pallet_3": "scene_3.usd"}


def get_obj(name):
    return bpy.data.objects.get(name)


def hide_all_pallets():
    for n in ("Pallet_0", "Pallet_1", "Pallet_2", "Pallet_3"):
        o = get_obj(n)
        if o:
            for m in [o, *o.children_recursive]:
                m.hide_render = True
                m.hide_viewport = True


def show_pallet(name):
    o = get_obj(name)
    for m in [o, *o.children_recursive]:
        m.hide_render = False
        m.hide_viewport = False


def setup_fixed_world():
    world = bpy.context.scene.world
    world.use_nodes = True
    hdri_path = os.path.join(cfg.HDRI_DIR, FIXED_HDRI)
    img = bpy.data.images.get(FIXED_HDRI) or bpy.data.images.load(hdri_path)
    for node in world.node_tree.nodes:
        if node.type == "TEX_ENVIRONMENT":
            node.image = img
        if node.type == "MAPPING":
            node.inputs["Rotation"].default_value[2] = 0.6
        if node.type == "BACKGROUND":
            node.inputs["Strength"].default_value = FIXED_HDRI_STRENGTH


def setup_render():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.device = "GPU"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.get_devices()
        for dev in prefs.devices:
            dev.use = True
    except Exception as exc:
        print(f"[render] GPU setup skipped: {exc}")
    scene.cycles.samples = 64
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = cfg.VIEW_TRANSFORM
    try:
        scene.view_settings.look = cfg.VIEW_LOOK
    except Exception:
        pass


def make_camera(geom):
    cam_data = bpy.data.cameras.new("CompareCam")
    cam_data.sensor_width = cfg.SENSOR_WIDTH
    cam_data.lens = cfg.FX * cam_data.sensor_width / RES[0]
    cam = bpy.data.objects.new("CompareCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    # fixed 3/4 front view, elev ~40deg, dist ~2.2m
    elev = math.radians(40.0)
    azim = math.radians(35.0)
    dist = 2.3
    offset = np.array([
        dist * math.cos(elev) * math.cos(azim),
        dist * math.cos(elev) * math.sin(azim),
        dist * math.sin(elev),
    ])
    cam_pos = cen + offset
    cam.location = tuple(cam_pos)
    direction = cen - cam_pos
    rot = _look_at_quat(direction)
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = rot
    return cam


def _look_at_quat(direction):
    from mathutils import Vector
    d = Vector(direction).normalized()
    return d.to_track_quat("-Z", "Y")


def apply_variant(pallet_obj, pallet_name, variant):
    """Reuse the pipeline's own material override (Base Color/rough/spec)."""
    family = GROUP[pallet_name]
    randomizers.PALLET_COLOR_GROUP_FOR_MODEL = {pallet_name: family}
    randomizers.PALLET_COLOR_VARIANTS = {family: [dict(variant, weight=1.0)]}
    return randomizers.randomize_pallet_appearance(pallet_obj, pallet_name)


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    setup_render()
    setup_fixed_world()

    rendered = {}  # (pallet, palette) -> list of png paths

    for pallet_name in ("Pallet_1", "Pallet_2", "Pallet_3"):
        pobj = get_obj(pallet_name)
        if pobj is None:
            print(f"[skip] {pallet_name} not in scene")
            continue
        hide_all_pallets()
        show_pallet(pallet_name)
        # place on ground at a fixed spot
        pobj.location = (0.0, 0.0, pobj.location[2])
        snap_object_to_ground(pobj, ground_z=0.0)
        bpy.context.view_layer.update()
        geom = get_pallet_geometry(pallet_name, pobj, ORIENTATION_OVERRIDES)
        make_camera(geom)

        for palette_name, palette in PALETTES:
            group = GROUP[pallet_name]
            variants = palette[group]
            paths = []
            for vi, variant in enumerate(variants[:3]):  # up to 3 per palette
                info = apply_variant(pobj, pallet_name, variant)
                fn = f"{pallet_name}_{palette_name}_{variant['name']}.png"
                fp = os.path.join(OUT_DIR, fn)
                render_to(fp)
                print(f"[OK] {fn}  base={info['base_color']}")
                paths.append(fp)
            rendered[(pallet_name, palette_name)] = paths

    # write a manifest the post-process (PIL) step can read
    import json
    manifest = {f"{k[0]}|{k[1]}": v for k, v in rendered.items()}
    with open(os.path.join(OUT_DIR, "_manifest.json"), "w") as f:
        json.dump({"source": SOURCE, "palettes": [p[0] for p in PALETTES],
                   "rendered": manifest}, f, indent=2)
    print(f"[DONE] manifest -> {os.path.join(OUT_DIR, '_manifest.json')}")


if __name__ == "__main__":
    main()
