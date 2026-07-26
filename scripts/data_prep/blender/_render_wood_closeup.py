"""Close-up render of the textured wood pallet materials (grain/knot check).

Loads the config wood variants (texture+normal+rough) and renders each scene
pallet at close distance so the user can confirm real wood grain shows up.

Run (separate Blender process, does NOT touch any MCP cube scene):
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
     --python scripts/data_prep/blender/_render_wood_closeup.py

Output: data/pallet/_mat_test10b/closeup/{pallet}_{variant}.png
"""
import os
import sys
import math
import json

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import blender_config as cfg
from blender_config import ORIENTATION_OVERRIDES, PALLET_COLOR_VARIANTS, PALLET_COLOR_GROUP_FOR_MODEL
import randomizers
from pallet_geometry import get_pallet_geometry, snap_object_to_ground

OUT_DIR = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_mat_test10b", "closeup")
os.makedirs(OUT_DIR, exist_ok=True)

FIXED_HDRI = "empty_warehouse_01_2k.hdr"
FIXED_HDRI_STRENGTH = 0.9
RES = (640, 480)

# scene_1=Pallet_1(plastic group), scene_2/3=Pallet_2/3(wood group)
GROUP = {"Pallet_1": "plastic", "Pallet_2": "wood", "Pallet_3": "wood"}
# pick a representative subset of variants to render close up
PICK = {
    "Pallet_1": ["weathered_mid", "weathered_dark", "weathered_warm"],
    "Pallet_2": ["worn_natural", "worn_dark", "weathered_warm"],
    "Pallet_3": ["faded_gray", "light_beige", "weathered_brown"],
}


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
    scene.cycles.samples = 96
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = cfg.VIEW_TRANSFORM
    try:
        scene.view_settings.look = cfg.VIEW_LOOK
    except Exception:
        pass


def _look_at_quat(direction):
    from mathutils import Vector
    return Vector(direction).normalized().to_track_quat("-Z", "Y")


def make_camera(geom):
    cam = bpy.data.objects.get("CloseupCam")
    if cam is None:
        cam_data = bpy.data.cameras.new("CloseupCam")
        cam_data.sensor_width = cfg.SENSOR_WIDTH
        cam_data.lens = cfg.FX * cam_data.sensor_width / RES[0]
        cam = bpy.data.objects.new("CloseupCam", cam_data)
        bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    elev = math.radians(28.0)   # low angle so deck-board grain is visible
    azim = math.radians(35.0)
    dist = 1.35                 # close-up
    offset = np.array([
        dist * math.cos(elev) * math.cos(azim),
        dist * math.cos(elev) * math.sin(azim),
        dist * math.sin(elev),
    ])
    cam_pos = cen + offset
    cam.location = tuple(cam_pos)
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = _look_at_quat(cen - cam_pos)
    return cam


def apply_variant(pallet_obj, pallet_name, family, variant):
    randomizers.PALLET_COLOR_GROUP_FOR_MODEL = {pallet_name: family}
    randomizers.PALLET_COLOR_VARIANTS = {family: [dict(variant, weight=1.0)]}
    # invalidate cached variant materials so each render rewires fresh
    randomizers._pallet_variant_materials = {}
    return randomizers.randomize_pallet_appearance(pallet_obj, pallet_name)


def main():
    setup_render()
    setup_fixed_world()
    rendered = []

    for pallet_name in ("Pallet_1", "Pallet_2", "Pallet_3"):
        pobj = get_obj(pallet_name)
        if pobj is None:
            print(f"[skip] {pallet_name} not in scene")
            continue
        family = GROUP[pallet_name]
        variants = {v["name"]: v for v in PALLET_COLOR_VARIANTS.get(family, [])}

        hide_all_pallets()
        show_pallet(pallet_name)
        pobj.location = (0.0, 0.0, pobj.location[2])
        snap_object_to_ground(pobj, ground_z=0.0)
        bpy.context.view_layer.update()
        geom = get_pallet_geometry(pallet_name, pobj, ORIENTATION_OVERRIDES)
        make_camera(geom)

        for vname in PICK.get(pallet_name, []):
            variant = variants.get(vname)
            if variant is None:
                print(f"[skip] {pallet_name} has no variant {vname}")
                continue
            info = apply_variant(pobj, pallet_name, family, variant)
            fn = f"{pallet_name}_{vname}.png"
            fp = os.path.join(OUT_DIR, fn)
            bpy.context.scene.render.filepath = fp
            bpy.ops.render.render(write_still=True)
            print(f"[OK] {fn}  textured={bool(variant.get('texture'))} tint={variant.get('tint')}")
            rendered.append(fp)

    with open(os.path.join(OUT_DIR, "_manifest.json"), "w") as f:
        json.dump({"rendered": rendered}, f, indent=2)
    print(f"[DONE] {len(rendered)} closeups -> {OUT_DIR}")


if __name__ == "__main__":
    main()
