"""Tight close-up renders of scene_1 (Pallet_1, plastic group) to verify the
plastic material reads as SMOOTH + uniform color (no wood grain) after the
config switch (plastic group -> flat plastic variants).

Reuses the pipeline's own appearance override (randomize_pallet_appearance reads
config/synthetic/blender.yaml plastic variants). Renders 3 close-ups under the
fixed warehouse HDRI at slightly different azimuths/variants.

Run (separate Blender process; does NOT touch any MCP cube scene):
  "/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
     data/pallet/blender_scene/synth_data_scene.blend \
     --python scripts/data_prep/blender/_render_plastic_closeup.py
Output: data/pallet/_mat_test10c/closeup/scene_1_plastic_{i}.png
"""
import math
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import blender_config as cfg
from blender_config import ORIENTATION_OVERRIDES, PALLET_COLOR_VARIANTS
import randomizers
from pallet_geometry import get_pallet_geometry, snap_object_to_ground

OUT_DIR = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_mat_test10e", "closeup")
os.makedirs(OUT_DIR, exist_ok=True)

FIXED_HDRI = "empty_warehouse_01_2k.hdr"
FIXED_HDRI_STRENGTH = 0.9
RES = (720, 540)
PALLET = "Pallet_1"   # scene_1.usd = plastic group

# pick 3 plastic variants to show (by name) + camera azimuth for each
SHOTS = [
    ("ind_blue", 35.0, 32.0),
    ("black", 120.0, 28.0),
    ("ind_red", 220.0, 30.0),
    ("ind_green", 300.0, 30.0),
]


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


def setup_world():
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
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = cfg.VIEW_TRANSFORM
    try:
        scene.view_settings.look = cfg.VIEW_LOOK
    except Exception:
        pass


def make_camera(geom, elev_deg, azim_deg, dist=1.5):
    cam = bpy.context.scene.camera
    if cam is None:
        cam_data = bpy.data.cameras.new("CloseupCam")
        cam = bpy.data.objects.new("CloseupCam", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        bpy.context.scene.camera = cam
    cam.data.sensor_width = cfg.SENSOR_WIDTH
    cam.data.lens = cfg.FX * cam.data.sensor_width / RES[0]
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)
    offset = np.array([
        dist * math.cos(elev) * math.cos(azim),
        dist * math.cos(elev) * math.sin(azim),
        dist * math.sin(elev),
    ])
    cam_pos = cen + offset
    cam.location = tuple(cam_pos)
    from mathutils import Vector
    d = Vector(cen - cam_pos).normalized()
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = d.to_track_quat("-Z", "Y")


def apply_named_variant(pobj, variant_name):
    variants = PALLET_COLOR_VARIANTS["plastic"]
    v = next((x for x in variants if x["name"] == variant_name), variants[0])
    randomizers.PALLET_COLOR_GROUP_FOR_MODEL = {PALLET: "plastic"}
    randomizers.PALLET_COLOR_VARIANTS = {"plastic": [dict(v, weight=1.0)]}
    info = randomizers.randomize_pallet_appearance(pobj, PALLET)
    # restore real config dicts for any later use
    randomizers.PALLET_COLOR_VARIANTS = {"plastic": variants}
    return info


def main():
    setup_render()
    setup_world()
    hide_all_pallets()
    show_pallet(PALLET)
    pobj = get_obj(PALLET)
    if pobj is None:
        print(f"[ERR] {PALLET} not in scene")
        return
    pobj.location = (0.0, 0.0, pobj.location[2])
    snap_object_to_ground(pobj, ground_z=0.0)
    bpy.context.view_layer.update()
    geom = get_pallet_geometry(PALLET, pobj, ORIENTATION_OVERRIDES)

    for i, (vname, azim, elev) in enumerate(SHOTS):
        info = apply_named_variant(pobj, vname)
        make_camera(geom, elev, azim)
        fp = os.path.join(OUT_DIR, f"scene_1_plastic_{i}_{vname}.png")
        bpy.context.scene.render.filepath = fp
        bpy.ops.render.render(write_still=True)
        bc = info.get("base_color") if isinstance(info, dict) else None
        print(f"[OK] {os.path.basename(fp)}  base_color={bc}")
    print(f"[DONE] closeups -> {OUT_DIR}")


if __name__ == "__main__":
    main()
