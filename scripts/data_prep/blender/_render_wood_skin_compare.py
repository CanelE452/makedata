"""Wood-skin diversification catalog: render every config wood variant on the
same scene_2 pallet / camera / HDRI so the user can confirm the planks look
*slightly* different (grain/colour/tone) yet realistic.

Run (separate Blender process, does NOT touch any MCP cube scene):
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
     --python scripts/data_prep/blender/_render_wood_skin_compare.py

Output: data/pallet/_wood_skin_compare/individual/{variant}.png
        data/pallet/_wood_skin_compare/catalog_wood_skins.png  (labelled grid)
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
from blender_config import ORIENTATION_OVERRIDES, PALLET_COLOR_VARIANTS
import randomizers
from pallet_geometry import get_pallet_geometry, snap_object_to_ground

OUT_DIR = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_wood_skin_compare")
IND_DIR = os.path.join(OUT_DIR, "individual")
os.makedirs(IND_DIR, exist_ok=True)

PALLET = "Pallet_2"          # scene_2 (wood group)
FIXED_HDRI = "empty_warehouse_01_2k.hdr"
FIXED_HDRI_STRENGTH = 0.9
RES = (512, 512)
SAMPLES = 96


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
    scene.cycles.samples = SAMPLES
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
    cam = bpy.data.objects.get("WoodSkinCam")
    if cam is None:
        cam_data = bpy.data.cameras.new("WoodSkinCam")
        cam_data.sensor_width = cfg.SENSOR_WIDTH
        cam_data.lens = cfg.FX * cam_data.sensor_width / RES[0]
        cam = bpy.data.objects.new("WoodSkinCam", cam_data)
        bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    elev = math.radians(34.0)   # 3/4 view: see top deck-boards + a side
    azim = math.radians(40.0)
    dist = 1.7
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


def apply_variant(pallet_obj, pallet_name, variant):
    randomizers.PALLET_COLOR_GROUP_FOR_MODEL = {pallet_name: "wood"}
    randomizers.PALLET_COLOR_VARIANTS = {"wood": [dict(variant, weight=1.0)]}
    randomizers._pallet_variant_materials = {}
    return randomizers.randomize_pallet_appearance(pallet_obj, pallet_name)


def assemble_sheet(items):
    """items: list of (name, png_path). Build a labelled grid PNG via Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        print(f"[sheet] Pillow unavailable ({exc}); skipping catalog grid")
        return None
    cols = 4
    rows = (len(items) + cols - 1) // cols
    cw, ch = RES[0], RES[1]
    pad, label_h = 8, 26
    cell_w, cell_h = cw + pad, ch + label_h + pad
    sheet = Image.new("RGB", (cols * cell_w + pad, rows * cell_h + pad), (32, 32, 36))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    for i, (name, fp) in enumerate(items):
        r, c = divmod(i, cols)
        x = pad + c * cell_w
        y = pad + r * cell_h
        try:
            im = Image.open(fp).convert("RGB").resize((cw, ch))
            sheet.paste(im, (x, y))
        except Exception as exc:
            draw.rectangle([x, y, x + cw, y + ch], fill=(80, 0, 0))
            print(f"[sheet] failed to load {fp}: {exc}")
        draw.text((x + 4, y + ch + 4), name, fill=(235, 235, 235), font=font)
    out = os.path.join(OUT_DIR, "catalog_wood_skins_v2.png")
    sheet.save(out)
    return out


def main():
    setup_render()
    setup_fixed_world()

    pobj = get_obj(PALLET)
    if pobj is None:
        print(f"[FATAL] {PALLET} not in scene")
        return
    hide_all_pallets()
    show_pallet(PALLET)
    pobj.location = (0.0, 0.0, pobj.location[2])
    snap_object_to_ground(pobj, ground_z=0.0)
    bpy.context.view_layer.update()
    geom = get_pallet_geometry(PALLET, pobj, ORIENTATION_OVERRIDES)
    make_camera(geom)

    variants = PALLET_COLOR_VARIANTS.get("wood", [])
    rendered = []
    for variant in variants:
        vname = variant["name"]
        info = apply_variant(pobj, PALLET, variant)
        fp = os.path.join(IND_DIR, f"{vname}.png")
        bpy.context.scene.render.filepath = fp
        bpy.ops.render.render(write_still=True)
        tex = variant.get("texture", "(flat)")
        print(f"[OK] {vname:<16} tex={tex} uv={variant.get('uv_scale')} uvrot={variant.get('uv_rotation', 0)} tint={variant.get('tint')}")
        rendered.append((vname, fp))

    sheet = assemble_sheet(rendered)
    with open(os.path.join(OUT_DIR, "_manifest.json"), "w") as f:
        json.dump({
            "pallet": PALLET,
            "hdri": FIXED_HDRI,
            "individual": [fp for _, fp in rendered],
            "catalog": sheet,
        }, f, indent=2)
    print(f"[DONE] {len(rendered)} variants -> {IND_DIR}")
    if sheet:
        print(f"[SHEET] {sheet}")


if __name__ == "__main__":
    main()
