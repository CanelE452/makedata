"""Headless floor-texture comparison render (BEFORE + 8 floor candidates).

The v4 pipeline keeps the *near-ground floor* fixed: the mesh `Base_base_m_0`
(material `base_m`, texture `base_m_diffuse.jpeg`) always sits under the pallet.
Only the HDRI / horizon changes between frames, so the model may overfit to that
single concrete floor. This script swaps ONLY the `base_m` material textures
(diffuse + normal, optional roughness) to each candidate in
`data/pallet/textures_floor/`, keeping geometry, camera, HDRI, and the pallet
fixed, so we can compare looks. Geometry is untouched => grounding / shadows /
labels are unaffected.

Run (separate Blender process, does NOT touch any MCP cube scene):
  "/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
     data/pallet/blender_scene/synth_data_scene.blend \
     --python scripts/data_prep/blender/_render_floor_compare.py

Output: data/pallet/_floor_compare/{NN}_{name}.png
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
from pallet_geometry import (
    get_pallet_geometry, snap_object_to_ground, get_normalized_scale,
)

OUT_DIR = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_floor_compare")
os.makedirs(OUT_DIR, exist_ok=True)
FLOOR_TEX_DIR = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "textures_floor")

# Fixed HDRI + camera so only the FLOOR changes between renders.
FIXED_HDRI = "empty_warehouse_01_2k.hdr"
FIXED_HDRI_STRENGTH = 0.7
RES = (640, 480)

# A representative pallet (wood) placed on the floor.
PALLET_NAME = "Pallet_2"
PALLET_VARIANT = {
    "name": "weathered_brown",
    "texture": "weathered_brown_planks_diff.png",
    "normal": "weathered_brown_planks_nor_gl.png",
    "roughness_map": "weathered_brown_planks_rough.png",
    "uv_scale": 1.0, "tint": [1.00, 0.92, 0.82], "tint_strength": 1.0,
    "base_color": [0.38, 0.29, 0.22], "roughness": 0.80, "specular": 0.16,
}

# Floor candidates (id used for filenames in textures_floor/). uv_scale tiles the
# 2k texture across the large floor mesh; tint nudges tone toward warehouse dark.
FLOOR_CANDIDATES = [
    {"name": "concrete_floor_02",     "uv_scale": 3.0, "tint": [0.95, 0.95, 0.95]},
    {"name": "damaged_concrete_floor","uv_scale": 2.5, "tint": [1.00, 1.00, 1.00]},
    {"name": "asphalt_02",            "uv_scale": 3.0, "tint": [1.00, 1.00, 1.00]},
    {"name": "concrete_pavers_02",    "uv_scale": 2.0, "tint": [0.95, 0.95, 0.95]},
    {"name": "concrete_floor_painted","uv_scale": 2.5, "tint": [1.00, 1.00, 1.00]},
    {"name": "cobblestone_floor_08",  "uv_scale": 2.0, "tint": [0.85, 0.85, 0.85]},
    {"name": "gravel_concrete_02",    "uv_scale": 2.5, "tint": [0.92, 0.92, 0.92]},
    {"name": "brick_floor_02",        "uv_scale": 2.0, "tint": [1.00, 1.00, 1.00]},
]

# Metal grating / fence meshes overlaid on top of base_m. Raycast dump
# (_dump_floor_meshes.py) confirmed base_m IS the floor the camera sees, but the
# Base_fence* meshes (a grey grating/fence that rises to z~7) sit on top and
# clutter the top-down view, occluding both the swapped floor and the pallet.
# Hide ALL of them so each candidate floor + the pallet read cleanly. (LP_merge*
# is the pallet itself, so it is NOT listed here.)
GRATING_PREFIXES = ("Base_fence",)

FLOOR_MAT = "base_m"
MARKS_MESH = "Base_marks_m_0"   # lane markings overlay; hide for non-concrete floors

# Diagnostics (_diag_floor3) proved Base_base_m_0 is NOT a flat plane: it is a
# grooved grating/trench geometry. A solid color shows through (red/green test),
# but real floor textures get chopped into grey grating slats by its UVs, so the
# albedo never reads as a clean concrete/brick/asphalt surface. Instead of
# retexturing that mesh, we DROP A FRESH FLAT PLANE at z=0 under the pallet and
# texture THAT. The old grating + fence are hidden so only the clean plane shows.
COMPARE_PLANE = "FloorComparePlane"


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


def _look_at_quat(direction):
    from mathutils import Vector
    return Vector(direction).normalized().to_track_quat("-Z", "Y")


def make_camera(geom):
    cam_data = bpy.data.cameras.new("FloorCmpCam")
    cam_data.sensor_width = cfg.SENSOR_WIDTH
    cam_data.lens = cfg.FX * cam_data.sensor_width / RES[0]
    cam = bpy.data.objects.new("FloorCmpCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    # Oblique 3/4 view (~v4 mid elevation): low enough that the flat pallet shows
    # its side faces and reads as a 3D object, high enough that the floor texture
    # fills the lower frame so candidates are easy to compare side by side.
    elev = math.radians(42.0)
    azim = math.radians(40.0)
    dist = 2.6
    offset = np.array([
        dist * math.cos(elev) * math.cos(azim),
        dist * math.cos(elev) * math.sin(azim),
        dist * math.sin(elev),
    ])
    cam_pos = cen + offset
    cam.location = tuple(cam_pos)
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = _look_at_quat(cen - cam_pos)
    bpy.context.view_layer.update()
    return cam


# --------------------------------------------------------------------------- #
# Floor material override (textures only; geometry untouched).
# --------------------------------------------------------------------------- #
def _img(filename, non_color=False):
    img = bpy.data.images.get(filename)
    if img is None:
        path = os.path.join(FLOOR_TEX_DIR, filename)
        img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def make_compare_plane(geom, size=14.0):
    """Create (once) a large flat plane at z=0 centered under the pallet, with its
    own material we retexture per candidate. Replaces the grooved grating floor."""
    obj = get_obj(COMPARE_PLANE)
    if obj is None:
        mesh = bpy.data.meshes.new(COMPARE_PLANE)
        obj = bpy.data.objects.new(COMPARE_PLANE, mesh)
        bpy.context.scene.collection.objects.link(obj)
        from mathutils import Vector
        h = size / 2.0
        verts = [Vector((-h, -h, 0)), Vector((h, -h, 0)),
                 Vector((h, h, 0)), Vector((-h, h, 0))]
        mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
        mesh.update()
        # planar UVs spanning [0,1] so our Mapping uv_scale tiles predictably
        mesh.uv_layers.new(name="UVMap")
        uvl = mesh.uv_layers.active.data
        for i, uv in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
            uvl[i].uv = uv
        mat = bpy.data.materials.new("FloorCompareMat")
        mat.use_nodes = True
        obj.data.materials.append(mat)
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    obj.location = (cen[0], cen[1], 0.0)  # z=0 ground, same as snap_object_to_ground
    obj.hide_render = False
    obj.hide_viewport = False
    return obj


def build_floor_material(candidate, mat=None):
    """Rebuild the target material's node graph with the candidate's
    diffuse/normal/roughness, a Mapping node for uv_scale, and a MULTIPLY tint."""
    if mat is None:
        mat = bpy.data.materials[FLOOR_MAT]
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-300, 0)
    out.location = (100, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    name = candidate["name"]
    uvs = float(candidate.get("uv_scale", 5.0))
    tint = candidate.get("tint", [1.0, 1.0, 1.0])

    texcoord = nt.nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-1400, 0)
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (-1200, 0)
    mapping.inputs["Scale"].default_value = (uvs, uvs, uvs)
    nt.links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])

    # Diffuse + MULTIPLY tint
    diff = nt.nodes.new("ShaderNodeTexImage")
    diff.location = (-1000, 200)
    diff.image = _img(f"{name}_diff.png")
    nt.links.new(mapping.outputs["Vector"], diff.inputs["Vector"])

    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 1.0
    mix.location = (-700, 200)
    mix.inputs["Color2"].default_value = (tint[0], tint[1], tint[2], 1.0)
    nt.links.new(diff.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness
    rough = nt.nodes.new("ShaderNodeTexImage")
    rough.location = (-1000, -100)
    rough.image = _img(f"{name}_rough.png", non_color=True)
    nt.links.new(mapping.outputs["Vector"], rough.inputs["Vector"])
    nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    # Normal
    nrm = nt.nodes.new("ShaderNodeTexImage")
    nrm.location = (-1000, -400)
    nrm.image = _img(f"{name}_nor_gl.png", non_color=True)
    nt.links.new(mapping.outputs["Vector"], nrm.inputs["Vector"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.location = (-700, -400)
    nt.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])


def set_marks_visible(visible):
    o = get_obj(MARKS_MESH)
    if o:
        o.hide_render = not visible
        o.hide_viewport = not visible


def hide_grating():
    """Hide fence overlays AND the grooved base_m grating floor + lane marks, so
    only our fresh FloorComparePlane is visible as the ground."""
    targets = GRATING_PREFIXES + ("Base_base_m_0", MARKS_MESH)
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if o.name in ("Base_base_m_0", MARKS_MESH) or any(
                o.name.startswith(p) for p in GRATING_PREFIXES):
            o.hide_render = True
            o.hide_viewport = True
            n += 1
    print(f"[grating] hid {n} overlay/grating meshes (fence + base_m + marks)")


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    setup_render()
    setup_fixed_world()

    hide_all_pallets()
    show_pallet(PALLET_NAME)
    pobj = get_obj(PALLET_NAME)
    pobj.scale = tuple(get_normalized_scale(
        pobj, ORIENTATION_OVERRIDES.get(PALLET_NAME, (0, 0, 0))))
    pobj.location = (-9.0, -7.0, pobj.location[2])
    snap_object_to_ground(pobj, ground_z=0.0)
    bpy.context.view_layer.update()

    # Give the pallet a realistic wood material so it stands out on every floor.
    randomizers.PALLET_COLOR_GROUP_FOR_MODEL = {PALLET_NAME: "wood"}
    randomizers.PALLET_COLOR_VARIANTS = {"wood": [dict(PALLET_VARIANT, weight=1.0)]}
    randomizers.randomize_pallet_appearance(pobj, PALLET_NAME)

    geom = get_pallet_geometry(PALLET_NAME, pobj, ORIENTATION_OVERRIDES)
    make_camera(geom)

    plane = make_compare_plane(geom)
    plane_mat = plane.data.materials[0]

    rendered = []

    # BEFORE: the current shipped floor (grooved base_m grating + lane marks),
    # plane hidden, fence hidden (fence is also hidden at v4 elevations).
    for o in bpy.data.objects:
        if o.type == "MESH" and any(o.name.startswith(p) for p in GRATING_PREFIXES):
            o.hide_render = o.hide_viewport = True
    plane.hide_render = plane.hide_viewport = True
    set_marks_visible(True)
    bpy.context.view_layer.update()
    fp = os.path.join(OUT_DIR, "00_BEFORE_current.png")
    render_to(fp)
    rendered.append(("00_BEFORE_current", fp))
    print("[OK] 00_BEFORE_current (shipped grating floor)")

    # Candidates: hide grating/base_m/marks, show the fresh plane, retexture it.
    hide_grating()
    plane.hide_render = plane.hide_viewport = False
    for i, cand in enumerate(FLOOR_CANDIDATES, start=1):
        build_floor_material(cand, mat=plane_mat)
        bpy.context.view_layer.update()
        nm = f"{i:02d}_{cand['name']}"
        fp = os.path.join(OUT_DIR, f"{nm}.png")
        render_to(fp)
        rendered.append((nm, fp))
        print(f"[OK] {nm}  uv={cand['uv_scale']} tint={cand['tint']}")

    import json
    with open(os.path.join(OUT_DIR, "_manifest.json"), "w") as f:
        json.dump({"pallet": PALLET_NAME, "hdri": FIXED_HDRI,
                   "elev_deg": 42.0, "rendered": [r[0] for r in rendered]}, f, indent=2)
    print(f"[DONE] {len(rendered)} renders -> {OUT_DIR}")


if __name__ == "__main__":
    main()
