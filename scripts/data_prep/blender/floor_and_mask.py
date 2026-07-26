"""Floor randomization + visible(modal) mask helpers for the palletobj pipeline.

Two additions to gen_palletobj_scenarios:
  1) randomize_floor(pallet_pos): per-frame fresh ground plane under the pallet,
     textured with one of 14 floor textures (avoids the parking_lot grating
     trap). Ported from the v4 (USD) randomizers.randomize_floor.
  2) render_holdout_mask(scene, pal, mask_path): renders a 2-pass holdout mask
     (pallet = white emission, everything else = black, world = black) so the
     PNG is a binary visible mask. Occluders/cargo that cover the pallet turn
     those pixels black -> excluded automatically. Blender 5.1 EEVEE-Next does
     NOT expose IndexOB pass and the compositor API changed, so holdout is used.

All self-contained: no dependency on blender_config / randomizers.
"""
import bpy, os, math, random
import numpy as np
from mathutils import Vector

# ============================================================
# FLOOR CONFIG (ported from blender_config.py FLOOR_*)
# ============================================================
FLOOR_TEXTURE_DIR = r"E:/CODING/GitHub/FoundationPose/data/pallet/textures_floor"
FLOOR_PLANE_NAME = "FloorRandPlane"
FLOOR_PLANE_SIZE = 50.0      # metres; dominate oblique view
FLOOR_PLANE_Z = -0.006       # 6mm below z=0 so it never occludes on-ground raycast
FLOOR_GRATING_HIDE = ("Base_fence",)                          # parking_lot fence prefixes
FLOOR_GRATING_HIDE_EXACT = ("Base_base_m_0", "Base_marks_m_0")  # parking grating + lane marks
FLOOR_BG_GROUND_HIDE = ("Floor",)            # BG_industrial 20 asphalt tiles prefix
FLOOR_UV_SCALE_RANGE = (1.5, 3.0)            # metres per texture repeat
FLOOR_TINT_RANGE = (0.85, 1.05)              # per-frame MULTIPLY tint (each RGB)
FLOOR_SATURATION_BOOST = 2.0                 # counter Filmic + bright-HDRI wash-out
FLOOR_VALUE_SCALE = 0.85                     # mild darken, keep tonal spread
# All 14 textures present in textures_floor/ (user asked for 14)
FLOOR_CANDIDATES = [
    "tile_white", "wood_laminate", "tile_brown", "red_brick", "dirt_ground",
    "red_earth", "brick_floor_02", "asphalt_02", "concrete_floor_02",
    "cobblestone_floor_08", "gravel_concrete_02", "concrete_floor_painted",
    "concrete_pavers_02", "damaged_concrete_floor",
]

_floor_image_cache = {}
_floor_grating_hidden = False


def _floor_img(filename, non_color=False):
    key = (filename, non_color)
    img = _floor_image_cache.get(key)
    if img is not None:
        try:
            _ = img.name  # touch: raises ReferenceError if purged out from under us
            return img
        except ReferenceError:
            pass  # purged → reload below
    path = os.path.join(FLOOR_TEXTURE_DIR, filename)
    if not os.path.isfile(path):
        print(f"  [FLOOR] missing texture: {path}")
        return None
    img = bpy.data.images.load(path, check_existing=True)
    img.use_fake_user = True  # protect from orphans_purge (run_mass_10k purges every 50 frames)
    try:
        img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    except Exception:
        pass
    _floor_image_cache[key] = img
    return img


def _hide_floor_grating():
    """Hide parking_lot fence + grooved base_m grating + lane marks once."""
    global _floor_grating_hidden
    if _floor_grating_hidden:
        return
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if o.name in FLOOR_GRATING_HIDE_EXACT or any(
                o.name.startswith(p) for p in FLOOR_GRATING_HIDE):
            o.hide_render = True
            o.hide_viewport = True
            n += 1
    _floor_grating_hidden = True
    print(f"  [FLOOR] hid {n} grating/fence/marks meshes")


def _hide_bg_ground():
    """Hide BG_industrial's own asphalt ground tiles (Floor*) EVERY frame.
    set_bg() re-shows the BG hierarchy each frame and those tiles (z~=0) would
    occlude our fresh plane (z=-6mm)."""
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if o.name == FLOOR_PLANE_NAME:
            continue
        if any(o.name.startswith(p) for p in FLOOR_BG_GROUND_HIDE):
            if not o.hide_render:
                o.hide_render = True
                o.hide_viewport = True
                n += 1
    return n


def _ensure_floor_plane():
    obj = bpy.data.objects.get(FLOOR_PLANE_NAME)
    if obj is not None:
        return obj
    mesh = bpy.data.meshes.new(FLOOR_PLANE_NAME)
    obj = bpy.data.objects.new(FLOOR_PLANE_NAME, mesh)
    bpy.context.scene.collection.objects.link(obj)
    h = FLOOR_PLANE_SIZE / 2.0
    verts = [(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    mesh.uv_layers.new(name="UVMap")
    uvl = mesh.uv_layers.active.data
    for i, uv in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uvl[i].uv = uv
    mat = bpy.data.materials.new("FloorRandMat")
    mat.use_nodes = True
    obj.data.materials.append(mat)
    obj.use_fake_user = True
    return obj


def _build_floor_material(mat, name, uv_scale, tint):
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (100, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (-300, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    texcoord = nt.nodes.new("ShaderNodeTexCoord"); texcoord.location = (-1400, 0)
    mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-1200, 0)
    mapping.inputs["Scale"].default_value = (uv_scale, uv_scale, uv_scale)
    nt.links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])
    diff = nt.nodes.new("ShaderNodeTexImage"); diff.location = (-1000, 200)
    diff.image = _floor_img(f"{name}_diff.png")
    nt.links.new(mapping.outputs["Vector"], diff.inputs["Vector"])
    hsv = nt.nodes.new("ShaderNodeHueSaturation"); hsv.location = (-850, 200)
    hsv.inputs["Saturation"].default_value = FLOOR_SATURATION_BOOST
    hsv.inputs["Value"].default_value = FLOOR_VALUE_SCALE
    if diff.image is not None:
        nt.links.new(diff.outputs["Color"], hsv.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixRGB"); mix.location = (-700, 200)
    mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 1.0
    mix.inputs["Color2"].default_value = (tint[0], tint[1], tint[2], 1.0)
    nt.links.new(hsv.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    rough = nt.nodes.new("ShaderNodeTexImage"); rough.location = (-1000, -100)
    rough.image = _floor_img(f"{name}_rough.png", non_color=True)
    if rough.image is not None:
        nt.links.new(mapping.outputs["Vector"], rough.inputs["Vector"])
        nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    nrm = nt.nodes.new("ShaderNodeTexImage"); nrm.location = (-1000, -400)
    nrm.image = _floor_img(f"{name}_nor_gl.png", non_color=True)
    if nrm.image is not None:
        nt.links.new(mapping.outputs["Vector"], nrm.inputs["Vector"])
        nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (-700, -400)
        nt.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])


def randomize_floor(pallet_pos):
    """Per-frame floor randomization. Call AFTER set_bg() and BEFORE raycast_floor
    so the raycast lands on the fresh plane. Returns a descriptor for annotation."""
    _hide_floor_grating()
    _hide_bg_ground()
    plane = _ensure_floor_plane()
    plane.location = (float(pallet_pos[0]), float(pallet_pos[1]), FLOOR_PLANE_Z)
    plane.hide_render = False
    plane.hide_viewport = False
    name = random.choice(FLOOR_CANDIDATES)
    metres_per_tile = random.uniform(*FLOOR_UV_SCALE_RANGE)
    uv_scale = max(1.0, FLOOR_PLANE_SIZE / metres_per_tile)
    t = [random.uniform(*FLOOR_TINT_RANGE) for _ in range(3)]
    _build_floor_material(plane.data.materials[0], name, uv_scale, t)
    bpy.context.view_layer.update()
    return {
        "floor_texture": name,
        "floor_metres_per_tile": round(float(metres_per_tile), 3),
        "floor_uv_scale": round(float(uv_scale), 3),
        "floor_tint": [round(float(v), 3) for v in t],
    }


# ============================================================
# VISIBLE (MODAL) MASK — 2-pass holdout
# ============================================================
_mask_mats = {}


def _get_mask_mats():
    if not _mask_mats:
        for nm, v in (("__MASK_WHITE", 1.0), ("__MASK_BLACK", 0.0)):
            m = bpy.data.materials.get(nm) or bpy.data.materials.new(nm)
            m.use_nodes = True
            nt = m.node_tree
            nt.nodes.clear()
            e = nt.nodes.new("ShaderNodeEmission")
            e.inputs["Color"].default_value = (v, v, v, 1.0)
            e.inputs["Strength"].default_value = 1.0
            o = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(e.outputs["Emission"], o.inputs["Surface"])
            m.use_fake_user = True
            _mask_mats[nm] = m
    return _mask_mats["__MASK_WHITE"], _mask_mats["__MASK_BLACK"]


def render_holdout_mask(scene, pal, mask_path):
    """Render a binary visible mask: pal=white, all else=black, world=black.
    Occlusion is automatic (occluders render black over the pallet)."""
    white, black = _get_mask_mats()
    backup = {}
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        backup[ob.name] = [s.material for s in ob.material_slots]
        tgt = white if ob is pal else black
        if not ob.material_slots:
            ob.data.materials.append(tgt)
        else:
            for s in ob.material_slots:
                s.material = tgt
    # black world + standard view transform + BW output
    wbk = scene.world
    scene.world = None
    vbk = scene.view_settings.view_transform
    try:
        scene.view_settings.view_transform = 'Standard'
    except Exception:
        pass
    fbk = scene.render.filepath
    cbk = scene.render.image_settings.color_mode
    scene.render.filepath = mask_path
    scene.render.image_settings.color_mode = 'BW'
    bpy.ops.render.render(write_still=True)
    # restore
    scene.render.filepath = fbk
    scene.render.image_settings.color_mode = cbk
    scene.world = wbk
    scene.view_settings.view_transform = vbk
    for name, mats in backup.items():
        ob = bpy.data.objects.get(name)
        if not ob:
            continue
        if not mats:
            ob.data.materials.clear()
        else:
            for i, m in enumerate(mats):
                if i < len(ob.material_slots):
                    ob.material_slots[i].material = m
    return mask_path


def mask_png_to_coco(mask_path):
    """Read holdout mask png -> COCO-style dict: bbox(xywh), area(px),
    uncompressed RLE (column-major counts, pycocotools-compatible)."""
    from PIL import Image as _Img
    arr = np.array(_Img.open(mask_path).convert("L"))
    binary = arr > 127
    h, w = binary.shape
    ys, xs = np.where(binary)
    if len(xs) == 0:
        return {"bbox_xywh": [0, 0, 0, 0], "area_px": 0,
                "rle": {"size": [h, w], "counts": [int(h * w)]}}
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    flat = binary.T.flatten()  # column-major (COCO Fortran order)
    diff = np.diff(flat.astype(np.int8))
    idx = np.where(diff != 0)[0] + 1
    bounds = np.concatenate([[0], idx, [len(flat)]])
    runs = [int(r) for r in np.diff(bounds)]
    if flat[0]:  # mask starts with foreground -> COCO counts begin with a 0-run
        runs = [0] + runs
    return {"bbox_xywh": [x0, y0, x1 - x0 + 1, y1 - y0 + 1],
            "area_px": int(binary.sum()),
            "rle": {"size": [h, w], "counts": runs}}
