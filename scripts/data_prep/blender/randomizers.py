"""씬 랜덤화 함수: 팔레트, 디스트랙터, 박스, 카메라, HDRI."""

import glob
import math
import os
import random

import bmesh
import bpy
from mathutils import Vector as mathutils_Vector
from mathutils.bvhtree import BVHTree

from blender_config import (
    PALLET_NAMES, PALLET_WEIGHTS, DISTRACTOR_NAMES, BOX_NAMES,
    PALLET_SURFACE_Z, HDRI_BASE_STRENGTH, HDRI_DIR, FX, IMAGE_WIDTH, IMAGE_HEIGHT,
    SENSOR_WIDTH, VIEW_TRANSFORM, VIEW_LOOK, IMAGE_FILE_FORMAT, IMAGE_COLOR_MODE,
    TAA_RENDER_SAMPLES, PALLET_PLACEMENT_X_RANGE, PALLET_PLACEMENT_Y_RANGE,
    PALLET_PLACEMENT_ATTEMPTS, BACKGROUND_WEIGHTS,
    PALLET_SOURCE_DIR, ORIENTATION_OVERRIDES, BOX_SHAPE_PROFILES,
    BACKGROUND_ASSETS, BACKGROUND_KEYS,
    PALLET_SOURCE_ASSETS,
    CAMERA_VIEW_MODES,
    PALLET_COLOR_GROUP_FOR_MODEL,
    PALLET_COLOR_VARIANTS,
    WOOD_TEXTURE_DIR,
    FLOOR_TEXTURE_DIR, FLOOR_PLANE_NAME, FLOOR_PLANE_SIZE, FLOOR_PLANE_Z,
    FLOOR_GRATING_HIDE, FLOOR_GRATING_HIDE_EXACT, FLOOR_BG_GROUND_HIDE,
    FLOOR_UV_SCALE_RANGE,
    FLOOR_TINT_RANGE, FLOOR_CANDIDATES,
    FLOOR_SATURATION_BOOST, FLOOR_VALUE_SCALE,
    PALLET_COLLISION_MARGIN,
    AABB_OVERLAP_DEFAULT_MARGIN,
    STATIC_OBSTACLE_SETTINGS,
    CAMERA_RANDOMIZATION,
    DISTRACTOR_RANDOMIZATION,
    BOX_RANDOMIZATION,
    HDRI_RANDOMIZATION,
)
from pallet_geometry import (
    get_obj_aabb_world as _get_obj_aabb_world,
    get_normalized_scale,
    get_pallet_geometry,
    has_mesh_geometry,
    is_ground_contact_ok,
    mesh_overlap as _mesh_overlap,
    object_height_world,
    set_object_pose_grounded,
    set_render_visibility,
)


_background_roots = {}
_box_base_scales = {}
_pallet_assets_initialized = False
_pallet_choice_bag = []
_pallet_variant_materials = {}


def _ensure_fallback_plastic_material():
    mat = bpy.data.materials.get("PalletPlasticFallback")
    if mat is None:
        mat = bpy.data.materials.new(name="PalletPlasticFallback")
        mat.use_nodes = True
    if not mat.node_tree:
        return mat

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = (0.09, 0.34, 0.18, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.58
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _ensure_fallback_wood_material():
    mat = bpy.data.materials.get("PalletWoodFallback")
    if mat is None:
        mat = bpy.data.materials.new(name="PalletWoodFallback")
        mat.use_nodes = True
    if not mat.node_tree:
        return mat

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = (0.39, 0.26, 0.15, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.78
    bsdf.inputs["Specular IOR Level"].default_value = 0.22
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _material_has_shader(mat):
    return bool(mat and mat.node_tree and len(mat.node_tree.nodes) > 0 and len(mat.node_tree.links) > 0)


def _base_material_name(name):
    if "." in name:
        stem, suffix = name.rsplit(".", 1)
        if suffix.isdigit():
            return stem
    return name


def _fallback_material_for_pallet(pallet_name):
    if pallet_name in {"Pallet_0", "Pallet_1"}:
        return bpy.data.materials.get("blinn1") or _ensure_fallback_plastic_material()
    if pallet_name == "Pallet_2":
        return bpy.data.materials.get("lambert16") or _ensure_fallback_wood_material()
    return _ensure_fallback_wood_material()


def _resolve_material_replacement(mat, pallet_name):
    candidate_names = []
    if mat is not None:
        candidate_names.append(_base_material_name(mat.name))
        candidate_names.append(mat.name)

    if pallet_name in {"Pallet_0", "Pallet_1"}:
        candidate_names.append("blinn1")
    elif pallet_name == "Pallet_2":
        candidate_names.append("lambert16")

    seen = set()
    for name in candidate_names:
        if not name or name in seen:
            continue
        seen.add(name)
        candidate = bpy.data.materials.get(name)
        if _material_has_shader(candidate):
            return candidate

    return _fallback_material_for_pallet(pallet_name)


def _repair_imported_materials(wrapper, pallet_name):
    repaired = 0
    for mesh_obj in [wrapper, *wrapper.children_recursive]:
        if mesh_obj.type != "MESH" or not mesh_obj.data.materials:
            continue
        for idx, mat in enumerate(mesh_obj.data.materials):
            if _material_has_shader(mat):
                continue
            replacement = _resolve_material_replacement(mat, pallet_name)
            if replacement is not None:
                mesh_obj.data.materials[idx] = replacement
                repaired += 1
    if repaired:
        print(f"  [PALLET] Repaired {repaired} empty material slots for {wrapper.name}")


def _choose_weighted_option(options):
    if not options:
        return None
    weights = [max(0.0, float(opt.get("weight", 1.0))) for opt in options]
    total = sum(weights)
    if total <= 0:
        return random.choice(options)
    return random.choices(options, weights=weights, k=1)[0]


def _get_shader_input(node, *names):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def _disconnect_input_links(node_tree, socket):
    if socket is None:
        return
    for link in list(socket.links):
        node_tree.links.remove(link)


def _ensure_principled_output(mat):
    mat.use_nodes = True
    node_tree = mat.node_tree
    nodes = node_tree.nodes
    links = node_tree.links

    output = next((node for node in nodes if node.type == 'OUTPUT_MATERIAL'), None)
    bsdf = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
    if output is None or bsdf is None:
        nodes.clear()
        output = nodes.new(type="ShaderNodeOutputMaterial")
        output.location = (320, 0)
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    elif not output.inputs["Surface"].is_linked:
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return bsdf


def _material_source_name(mat):
    if mat is None:
        return None
    base_name = mat.get("pallet_variant_base")
    if base_name:
        return base_name
    return _base_material_name(mat.name)


_wood_image_cache = {}


def _load_wood_image(filename, is_data):
    """Load (and cache) a wood texture image; data maps use Non-Color space."""
    if not filename:
        return None
    path = filename if os.path.isabs(filename) else os.path.join(WOOD_TEXTURE_DIR, filename)
    key = os.path.normpath(path)
    img = _wood_image_cache.get(key)
    if img is not None and img.name in bpy.data.images:
        return img
    if not os.path.isfile(path):
        print(f"  [PALLET] Missing wood texture: {path}")
        return None
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.reload()
        if img.size[0] == 0 or img.size[1] == 0:
            print(f"  [PALLET] Wood texture decoded empty: {path}")
            return None
    except Exception as exc:  # pragma: no cover - defensive
        print(f"  [PALLET] Wood texture load error ({exc}): {path}")
        return None
    if is_data:
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    _wood_image_cache[key] = img
    return img


def _clear_variant_extra_nodes(node_tree, bsdf):
    """Remove previously-added texture/tint nodes so re-config is idempotent."""
    keep = {n for n in node_tree.nodes if n.type in ("OUTPUT_MATERIAL", "BSDF_PRINCIPLED")}
    for node in list(node_tree.nodes):
        if node is bsdf or node in keep:
            continue
        if node.name.startswith("PalletWood_"):
            node_tree.nodes.remove(node)


def _configure_textured_material(mat, variant, roughness, specular):
    """Wire albedo (× tint multiply), normal and roughness maps into the BSDF.

    Brightness/tone DR is done with a multiply tint on the albedo so the grain
    is preserved (no flat base-color repaint). Returns True on success."""
    albedo_img = _load_wood_image(variant.get("texture"), is_data=False)
    if albedo_img is None:
        return False

    bsdf = _ensure_principled_output(mat)
    node_tree = mat.node_tree
    nodes = node_tree.nodes
    links = node_tree.links

    base_socket = _get_shader_input(bsdf, "Base Color")
    rough_socket = _get_shader_input(bsdf, "Roughness")
    spec_socket = _get_shader_input(bsdf, "Specular IOR Level", "Specular")
    metal_socket = _get_shader_input(bsdf, "Metallic")
    normal_socket = _get_shader_input(bsdf, "Normal")
    for sock in (base_socket, rough_socket, spec_socket, metal_socket, normal_socket):
        _disconnect_input_links(node_tree, sock)
    _clear_variant_extra_nodes(node_tree, bsdf)

    uv_scale = float(variant.get("uv_scale", 1.0))
    # uv_rotation (deg about Z/W axis): some plank textures have grain running
    # across the texture's V axis, so the deck-board UV maps them perpendicular
    # to the slat direction (looks "vertical / cross-grain"). 90deg re-aligns the
    # grain with the deck-board length. Rotation is applied around the (0.5,0.5)
    # UV centre so the mapped region stays on the deck.
    uv_rotation = float(variant.get("uv_rotation", 0.0))
    tex_coord = nodes.new("ShaderNodeTexCoord"); tex_coord.name = "PalletWood_TexCoord"
    tex_coord.location = (-1100, 0)
    mapping = nodes.new("ShaderNodeMapping"); mapping.name = "PalletWood_Mapping"
    mapping.location = (-900, 0)
    if uv_scale != 1.0:
        mapping.inputs["Scale"].default_value = (uv_scale, uv_scale, uv_scale)
    if uv_rotation != 0.0:
        import math as _m
        ang = _m.radians(uv_rotation)
        mapping.vector_type = "POINT"
        mapping.inputs["Rotation"].default_value[2] = ang
        # Rotate about the (0.5,0.5) UV centre: out = R*(in) + (c - R*c).
        c = 0.5
        cx = c - (_m.cos(ang) * c - _m.sin(ang) * c)
        cy = c - (_m.sin(ang) * c + _m.cos(ang) * c)
        mapping.inputs["Location"].default_value = (cx, cy, 0.0)
    links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])

    # Albedo
    albedo = nodes.new("ShaderNodeTexImage"); albedo.name = "PalletWood_Albedo"
    albedo.location = (-650, 250)
    albedo.image = albedo_img
    links.new(mapping.outputs["Vector"], albedo.inputs["Vector"])

    # Tint multiply for brightness DR (keeps grain).
    tint = variant.get("tint")
    tint_strength = float(variant.get("tint_strength", 1.0))
    if tint is not None and base_socket is not None:
        mix = nodes.new("ShaderNodeMixRGB"); mix.name = "PalletWood_Tint"
        mix.location = (-330, 250)
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = max(0.0, min(1.0, tint_strength))
        links.new(albedo.outputs["Color"], mix.inputs["Color1"])
        mix.inputs["Color2"].default_value = (tint[0], tint[1], tint[2], 1.0)
        links.new(mix.outputs["Color"], base_socket)
    elif base_socket is not None:
        links.new(albedo.outputs["Color"], base_socket)

    # Roughness map (Non-Color) -> Roughness, else flat value.
    rough_img = _load_wood_image(variant.get("roughness_map"), is_data=True)
    if rough_img is not None and rough_socket is not None:
        rnode = nodes.new("ShaderNodeTexImage"); rnode.name = "PalletWood_Rough"
        rnode.location = (-650, -50)
        rnode.image = rough_img
        links.new(mapping.outputs["Vector"], rnode.inputs["Vector"])
        links.new(rnode.outputs["Color"], rough_socket)
    elif rough_socket is not None:
        rough_socket.default_value = float(roughness)

    # Normal map (Non-Color) -> Normal Map -> Normal.
    normal_img = _load_wood_image(variant.get("normal"), is_data=True)
    if normal_img is not None and normal_socket is not None:
        nnode = nodes.new("ShaderNodeTexImage"); nnode.name = "PalletWood_Normal"
        nnode.location = (-650, -350)
        nnode.image = normal_img
        links.new(mapping.outputs["Vector"], nnode.inputs["Vector"])
        nmap = nodes.new("ShaderNodeNormalMap"); nmap.name = "PalletWood_NormalMap"
        nmap.location = (-330, -350)
        links.new(nnode.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], normal_socket)

    if spec_socket is not None:
        spec_socket.default_value = float(specular)
    if metal_socket is not None:
        metal_socket.default_value = 0.0
    return True


def _configure_variant_material(mat, variant):
    base_color = variant["base_color"]
    roughness = variant.get("roughness", 0.6)
    specular = variant.get("specular", 0.25)

    if variant.get("texture") and _configure_textured_material(mat, variant, roughness, specular):
        return mat

    bsdf = _ensure_principled_output(mat)
    node_tree = mat.node_tree
    _clear_variant_extra_nodes(node_tree, bsdf)

    base_socket = _get_shader_input(bsdf, "Base Color")
    rough_socket = _get_shader_input(bsdf, "Roughness")
    specular_socket = _get_shader_input(bsdf, "Specular IOR Level", "Specular")
    metallic_socket = _get_shader_input(bsdf, "Metallic")

    _disconnect_input_links(node_tree, base_socket)
    _disconnect_input_links(node_tree, rough_socket)
    _disconnect_input_links(node_tree, specular_socket)
    _disconnect_input_links(node_tree, metallic_socket)

    if base_socket is not None:
        base_socket.default_value = (*base_color, 1.0)
    if rough_socket is not None:
        rough_socket.default_value = float(roughness)
    if specular_socket is not None:
        specular_socket.default_value = float(specular)
    if metallic_socket is not None:
        metallic_socket.default_value = 0.0
    return mat


def _get_or_create_pallet_variant_material(source_mat, pallet_name, family_name, variant):
    source_mat = source_mat or _fallback_material_for_pallet(pallet_name)
    source_name = _material_source_name(source_mat) or pallet_name
    cache_key = (family_name, variant["name"], source_name)
    cached = _pallet_variant_materials.get(cache_key)
    if cached is not None and cached.name in bpy.data.materials:
        return cached

    mat_name = f"PalletVariant_{family_name}_{variant['name']}_{source_name}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = source_mat.copy() if source_mat is not None else bpy.data.materials.new(name=mat_name)
        mat.name = mat_name
    mat["pallet_variant_base"] = source_name
    mat["pallet_color_family"] = family_name
    mat["pallet_color_name"] = variant["name"]
    _configure_variant_material(mat, variant)
    _pallet_variant_materials[cache_key] = mat
    return mat


def randomize_pallet_appearance(pallet_obj, pallet_name):
    family_name = PALLET_COLOR_GROUP_FOR_MODEL.get(pallet_name, "plastic")
    variants = PALLET_COLOR_VARIANTS.get(family_name) or PALLET_COLOR_VARIANTS.get("plastic", [])
    variant = _choose_weighted_option(variants)
    if variant is None:
        return None

    slots_updated = 0
    for mesh_obj in [pallet_obj, *pallet_obj.children_recursive]:
        if mesh_obj.type != "MESH":
            continue
        materials = mesh_obj.data.materials
        if not materials:
            source_mat = _fallback_material_for_pallet(pallet_name)
            materials.append(_get_or_create_pallet_variant_material(source_mat, pallet_name, family_name, variant))
            slots_updated += 1
            continue

        for idx, current_mat in enumerate(materials):
            source_name = _material_source_name(current_mat)
            source_mat = bpy.data.materials.get(source_name) if source_name else None
            source_mat = source_mat or _resolve_material_replacement(current_mat, pallet_name)
            materials[idx] = _get_or_create_pallet_variant_material(source_mat, pallet_name, family_name, variant)
            slots_updated += 1

    return {
        "family": family_name,
        "name": variant["name"],
        "base_color": [round(float(v), 4) for v in variant["base_color"]],
        "roughness": float(variant.get("roughness", 0.6)),
        "specular": float(variant.get("specular", 0.25)),
        "slots_updated": slots_updated,
    }


def get_obj(name):
    return bpy.data.objects.get(name)


def get_obj_aabb_world(obj):
    return _get_obj_aabb_world(obj)


def aabb_overlap_xy(a_min, a_max, b_min, b_max, margin=AABB_OVERLAP_DEFAULT_MARGIN):
    """Check XY AABB overlap with safety margin to prevent physical overlap."""
    return not (a_max[0] + margin < b_min[0] or b_max[0] + margin < a_min[0] or
                a_max[1] + margin < b_min[1] or b_max[1] + margin < a_min[1])


def _bvh_from_obj(obj):
    """Build BVH tree from object's evaluated mesh in world space."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    try:
        bm.from_object(obj, depsgraph)
        bm.transform(obj.matrix_world)
        return BVHTree.FromBMesh(bm)
    finally:
        bm.free()


def mesh_overlap(obj_a, obj_b):
    return _mesh_overlap(obj_a, obj_b)


def check_raycast_visibility(pallet_obj, cam_pos, sample_points):
    """Cast rays from camera to pallet sample points and estimate visible pallet area."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    pallet_children = set(pallet_obj.children_recursive) | {pallet_obj}

    origin = mathutils_Vector(cam_pos)
    visible = 0
    total = len(sample_points)

    for pt in sample_points:
        target = mathutils_Vector(pt)
        direction = (target - origin).normalized()
        result, loc, normal, idx, hit_obj, matrix = bpy.context.scene.ray_cast(
            depsgraph, origin, direction)

        if not result:
            visible += 1
        elif hit_obj in pallet_children:
            visible += 1
        else:
            # Any nearer hit that is not the pallet itself counts as occlusion,
            # including background fences, walls, crates, boxes, and distractors.
            pass

    return visible / total if total > 0 else 0.0


def _has_mesh_children(obj):
    return has_mesh_geometry(obj)


def obj_z_min_local(obj):
    aabb_min, _ = get_obj_aabb_world(obj)
    return float(aabb_min[2])


def obj_height(obj):
    return object_height_world(obj)


def setup_render():
    initialize_pallet_assets()

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = IMAGE_WIDTH
    scene.render.resolution_y = IMAGE_HEIGHT
    scene.render.resolution_percentage = 100
    # Filmic strongly desaturates highlights, washing brightly-lit floor regions
    # to grey. FLOOR_VIEW_TRANSFORM env lets a preview render with Standard to
    # show true floor colour without touching the global config.
    scene.view_settings.view_transform = os.environ.get(
        "FLOOR_VIEW_TRANSFORM", VIEW_TRANSFORM)
    try:
        scene.view_settings.look = VIEW_LOOK
    except Exception:
        scene.view_settings.look = "None"
    scene.render.image_settings.file_format = IMAGE_FILE_FORMAT
    scene.render.image_settings.color_mode = IMAGE_COLOR_MODE

    if hasattr(scene.eevee, 'taa_render_samples') and TAA_RENDER_SAMPLES > 0:
        scene.eevee.taa_render_samples = TAA_RENDER_SAMPLES

    cam = scene.camera
    if cam and cam.data:
        cam.data.sensor_fit = 'HORIZONTAL'
        cam.data.sensor_width = SENSOR_WIDTH
        cam.data.lens = FX * SENSOR_WIDTH / IMAGE_WIDTH
        cam.data.shift_x = 0
        cam.data.shift_y = 0


def _set_hierarchy_parent(root, children):
    for child in children:
        child.parent = root
        child.matrix_parent_inverse = root.matrix_world.inverted()


def _mark_hierarchy_visibility(root, visible):
    set_render_visibility(root, visible)
    root.hide_select = not visible
    for child in root.children_recursive:
        child.hide_select = not visible


def _legacy_pallet_name(name):
    return f"Legacy_{name}"


def _delete_object_hierarchy(root):
    """Remove an object and its entire child hierarchy from the .blend.

    Datablocks (mesh/material/image) left with zero users are dropped by Blender
    on the next save, so no manual orphan purge is needed here."""
    victims = [root, *root.children_recursive]
    for obj in victims:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    print(f"  [PALLET] Deleted stale pallet hierarchy ({len(victims)} objects)")


def _import_pallet_asset(wrapper_name, source_asset):
    filepath = os.path.join(PALLET_SOURCE_DIR, source_asset)
    if not os.path.isfile(filepath):
        print(f"  [PALLET] Missing USD asset: {filepath}")
        return None

    existing = set(bpy.data.objects.keys())
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    else:
        bpy.ops.wm.usd_import(filepath=filepath)
    new_roots = [
        obj for obj in bpy.data.objects
        if obj.name not in existing and obj.parent is None
    ]
    if not new_roots:
        print(f"  [PALLET] Import created no roots: {source_asset}")
        return None

    wrapper = bpy.data.objects.new(wrapper_name, None)
    wrapper.empty_display_type = 'PLAIN_AXES'
    wrapper["pallet_source_file"] = source_asset
    bpy.context.scene.collection.objects.link(wrapper)
    _set_hierarchy_parent(wrapper, new_roots)
    _mark_hierarchy_visibility(wrapper, False)
    bpy.context.view_layer.update()
    print(f"  [PALLET] Imported {source_asset} -> {wrapper_name}")
    return wrapper


def initialize_pallet_assets():
    global _pallet_assets_initialized
    if _pallet_assets_initialized:
        return

    for pallet_name in PALLET_NAMES:
        source_asset = PALLET_SOURCE_ASSETS[pallet_name]
        obj = get_obj(pallet_name)
        if obj and obj.get("pallet_source_file") == source_asset:
            _mark_hierarchy_visibility(obj, False)
            continue

        stale = None
        if obj is not None:
            obj.name = _legacy_pallet_name(pallet_name)
            _mark_hierarchy_visibility(obj, False)
            stale = obj

        imported = _import_pallet_asset(pallet_name, source_asset)
        if imported is None:
            # Import failed: keep the previously-baked pallet as an active fallback.
            if stale is not None:
                stale.name = pallet_name
                stale["pallet_source_file"] = source_asset
                _mark_hierarchy_visibility(stale, False)
        else:
            _repair_imported_materials(imported, pallet_name)
            # Import succeeded: the config-mismatched baked pallet is now dead
            # weight. DELETE the whole hierarchy instead of leaving a Legacy_*
            # rename, so stale pallets can't pile up in the .blend and get
            # re-baked on the next asset swap (root cause of the leftover
            # Legacy_Pallet_2/3 that survived the P2/P3 NoAI replacement).
            if stale is not None:
                _delete_object_hierarchy(stale)

    _pallet_assets_initialized = True


def _draw_pallet_index(valid_indices):
    global _pallet_choice_bag

    valid_indices = list(valid_indices)
    if not _pallet_choice_bag:
        _pallet_choice_bag = valid_indices.copy()
        extra_count = max(0, len(valid_indices) // 2)
        if extra_count > 0:
            weights = [PALLET_WEIGHTS[i] for i in valid_indices]
            total_w = sum(weights)
            weights = [w / total_w for w in weights]
            _pallet_choice_bag.extend(random.choices(valid_indices, weights=weights, k=extra_count))
        random.shuffle(_pallet_choice_bag)

    for pos, idx in enumerate(_pallet_choice_bag):
        if idx in valid_indices:
            return _pallet_choice_bag.pop(pos)

    _pallet_choice_bag = []
    return random.choice(valid_indices)


def choose_next_pallet_index():
    valid_indices = [i for i, n in enumerate(PALLET_NAMES)
                     if get_obj(n) is not None and _has_mesh_children(get_obj(n))
                     and PALLET_WEIGHTS[i] > 0]
    if not valid_indices:
        return -1
    return _draw_pallet_index(valid_indices)


def choose_camera_mode_name():
    items = list(CAMERA_VIEW_MODES.items())
    if not items:
        return "mid_random"
    names = [name for name, _ in items]
    weights = [max(0.0, float(cfg.get("weight", 1.0))) for _, cfg in items]
    total = sum(weights)
    if total <= 0:
        return random.choice(names)
    return random.choices(names, weights=weights, k=1)[0]


def _sample_biased_uniform(min_value, max_value, bias=1.0):
    if max_value <= min_value:
        return float(min_value)
    bias = max(0.01, float(bias))
    t = random.random() ** (1.0 / bias)
    return float(min_value + (max_value - min_value) * t)


def _ensure_background_root(bg_key):
    root = _background_roots.get(bg_key)
    if root and root.name in bpy.data.objects:
        return root

    cfg = BACKGROUND_ASSETS.get(bg_key)
    if cfg is None:
        return None

    if cfg["kind"] == "existing":
        root = get_obj(cfg["root_name"])
    elif cfg["kind"] == "gltf":
        root = get_obj(cfg["root_name"])
        if root is None:
            filepath = cfg["filepath"]
            if not os.path.isfile(filepath):
                print(f"  [BG] Missing background asset: {filepath}")
                return None
            existing = set(bpy.data.objects.keys())
            bpy.ops.import_scene.gltf(filepath=filepath)
            new_roots = [
                obj for obj in bpy.data.objects
                if obj.name not in existing and obj.parent is None
            ]
            root = bpy.data.objects.new(cfg["root_name"], None)
            root.empty_display_type = 'PLAIN_AXES'
            bpy.context.scene.collection.objects.link(root)
            _set_hierarchy_parent(root, new_roots)
    else:
        return None

    if root is not None:
        _background_roots[bg_key] = root
    return root


def initialize_backgrounds():
    available = {}
    for bg_key in BACKGROUND_KEYS:
        root = _ensure_background_root(bg_key)
        if root is not None:
            available[bg_key] = root
    return available


def randomize_background():
    available = initialize_backgrounds()
    if not available:
        return None

    keys = list(available.keys())
    weights = [max(0.0, float(BACKGROUND_WEIGHTS.get(key, 1.0))) for key in keys]
    total = sum(weights)
    if total <= 0:
        chosen_key = random.choice(keys)
    else:
        chosen_key = random.choices(keys, weights=weights, k=1)[0]
    for bg_key, root in available.items():
        set_render_visibility(root, bg_key == chosen_key)
    bpy.context.view_layer.update()
    return chosen_key


def _collect_static_obstacles():
    """Collect AABBs of all fixed scene objects that pallets could collide with.
    Only objects in the currently visible background are considered."""

    skip_prefixes = STATIC_OBSTACLE_SETTINGS["skip_prefixes"]
    moveable = set(PALLET_NAMES + DISTRACTOR_NAMES + BOX_NAMES)

    static_obstacles = []
    for obj in bpy.data.objects:
        if obj.name in moveable:
            continue
        if any(obj.name.startswith(p) for p in skip_prefixes):
            continue
        if obj.type not in ('MESH', 'EMPTY'):
            continue
        if obj.hide_render:
            continue

        try:
            aabb_min, aabb_max = get_obj_aabb_world(obj)
            # Only care about objects above ground and with some size
            if (
                aabb_max[2] > STATIC_OBSTACLE_SETTINGS["min_height"]
                and (aabb_max[0] - aabb_min[0]) > STATIC_OBSTACLE_SETTINGS["min_width"]
            ):
                static_obstacles.append((obj.name, aabb_min, aabb_max))
        except Exception:
            pass

    print(f"  [STATIC] Collected {len(static_obstacles)} fixed obstacles")
    return static_obstacles


def randomize_pallet(chosen_idx=None):
    """Select one pallet (weighted: plastic 60%, wooden 40%), hide others."""
    # Filter to pallets that exist and have mesh geometry
    valid_indices = [i for i, n in enumerate(PALLET_NAMES)
                     if get_obj(n) is not None and _has_mesh_children(get_obj(n))]
    if not valid_indices:
        return None, -1

    if chosen_idx is None:
        chosen_idx = _draw_pallet_index(valid_indices)
    if chosen_idx not in valid_indices:
        return None, -1
    chosen_name = PALLET_NAMES[chosen_idx]
    chosen_obj = get_obj(chosen_name)

    static_obs = _collect_static_obstacles()

    for name in PALLET_NAMES:
        obj = get_obj(name)
        if obj is None:
            continue
        obj.scale = tuple(get_normalized_scale(
            obj,
            ORIENTATION_OVERRIDES.get(name, (0, 0, 0)),
        ))
    bpy.context.view_layer.update()

    for name in PALLET_NAMES:
        obj = get_obj(name)
        if obj is None:
            continue
        set_render_visibility(obj, name == chosen_name)

    # Try placing pallet in a clear spot (no overlap with static obstacles)
    placed = False
    for _ in range(PALLET_PLACEMENT_ATTEMPTS):
        px = random.uniform(PALLET_PLACEMENT_X_RANGE[0], PALLET_PLACEMENT_X_RANGE[1])
        py = random.uniform(PALLET_PLACEMENT_Y_RANGE[0], PALLET_PLACEMENT_Y_RANGE[1])
        yaw = random.uniform(0, 2 * math.pi)
        set_object_pose_grounded(
            chosen_obj,
            px,
            py,
            yaw,
            base_rot_deg=ORIENTATION_OVERRIDES.get(chosen_name, (0, 0, 0)),
            ground_z=0.0,
        )
        bpy.context.view_layer.update()
        p_min, p_max = get_obj_aabb_world(chosen_obj)

        collision = False
        for obs_name, obs_min, obs_max in static_obs:
            if aabb_overlap_xy(p_min, p_max, obs_min, obs_max, margin=PALLET_COLLISION_MARGIN):
                collision = True
                break

        if not collision:
            placed = True
            break

    if not placed:
        px = random.uniform(PALLET_PLACEMENT_X_RANGE[0], PALLET_PLACEMENT_X_RANGE[1])
        py = random.uniform(PALLET_PLACEMENT_Y_RANGE[0], PALLET_PLACEMENT_Y_RANGE[1])
        yaw = random.uniform(0, 2 * math.pi)
        set_object_pose_grounded(
            chosen_obj,
            px,
            py,
            yaw,
            base_rot_deg=ORIENTATION_OVERRIDES.get(chosen_name, (0, 0, 0)),
            ground_z=0.0,
        )

    return chosen_name, chosen_idx


def randomize_camera(pallet_pos, pallet_geom=None, distance_range=None, camera_mode_name=None):
    """Sample camera from a weighted view mode while always looking at the pallet."""
    scene = bpy.context.scene
    cam = scene.camera
    if cam is None:
        return None, None

    px, py, pz = pallet_pos

    mode_cfg = CAMERA_VIEW_MODES.get(camera_mode_name, {})
    if distance_range is None:
        distance_range = mode_cfg.get("distance", (1.5, 6.5))
    distance_bias = mode_cfg.get("distance_bias", 1.0)
    distance = _sample_biased_uniform(distance_range[0], distance_range[1], bias=distance_bias)
    height_base = mode_cfg.get("height_base", (0.4, 0.8))
    height_scale = mode_cfg.get("height_scale", (0.10, 0.25))
    height = random.uniform(height_base[0], height_base[1]) + distance * random.uniform(height_scale[0], height_scale[1])

    angle_mode = mode_cfg.get("angle_mode", "full")
    if angle_mode == "front_bias" and pallet_geom is not None:
        front_dir = -pallet_geom["depth_dir_world"]
        base_angle = math.atan2(front_dir[1], front_dir[0])
        if random.random() < CAMERA_RANDOMIZATION["front_bias_reverse_probability"]:
            base_angle += math.pi
        jitter_deg = float(mode_cfg.get("angle_jitter_deg", 25.0))
        h_angle = base_angle + math.radians(random.uniform(-jitter_deg, jitter_deg))
    else:
        h_angle = random.uniform(0, 2 * math.pi)

    cam_x = px + distance * math.cos(h_angle)
    cam_y = py + distance * math.sin(h_angle)
    cam_z = height

    cam.location = (cam_x, cam_y, cam_z)
    cam_pos = (cam_x, cam_y, cam_z)

    center_prob = float(mode_cfg.get("center_prob", 0.5))
    look_offset = mode_cfg.get("look_offset", (0.08, 0.5))
    edge_crop_prob = float(mode_cfg.get("edge_crop_prob", 0.0))
    if random.random() < edge_crop_prob:
        # Edge-crop: compute offset to push pallet near frame edge
        # Pallet projected half-width ≈ 0.55 * FX / distance pixels
        # To place pallet edge at image edge: offset = (IMAGE_WIDTH/2) * distance / FX
        # Use 60-90% of that to keep pallet partially visible
        edge_fraction = random.uniform(0.60, 0.90)
        max_offset = (IMAGE_WIDTH / 2.0) * distance / FX * edge_fraction
        perp_angle = h_angle + math.pi / 2
        offset_mag = max_offset * random.choice([-1, 1])
        look_x = px + offset_mag * math.cos(perp_angle)
        look_y = py + offset_mag * math.sin(perp_angle)
    elif random.random() >= center_prob:
        perp_angle = h_angle + math.pi / 2
        offset_mag = random.uniform(look_offset[0], look_offset[1]) * random.choice([-1, 1])
        look_x = px + offset_mag * math.cos(perp_angle)
        look_y = py + offset_mag * math.sin(perp_angle)
    else:
        look_x, look_y = px, py

    if pallet_geom is not None:
        look_base_z = pallet_geom["top_z_world"]
    else:
        look_base_z = max(pz, PALLET_SURFACE_Z / 2.0)
    look_z = max(
        CAMERA_RANDOMIZATION["look_z_min"],
        look_base_z * random.uniform(*CAMERA_RANDOMIZATION["look_z_scale_range"]),
    )
    look_at = (look_x, look_y, look_z)

    direction = mathutils_Vector(look_at) - mathutils_Vector(cam_pos)
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()

    return cam_pos, look_at


def randomize_distractors(pallet_pos, cam_pos, prefer_occlusion=False,
                          distractor_names=None, hide_names=None):
    """Place distractors around the pallet and optionally encourage partial occlusion.

    distractor_names / hide_names are the ADDITIVE v2 occlusion-pool hooks:
      - distractor_names=None (default) -> legacy path: shuffle the hard-coded
        DISTRACTOR_NAMES and take a random count (unchanged behaviour).
      - distractor_names=[...] -> v2 path: the caller (distractor_pool_v2) already
        chose the exact `Dist_<name>` set for this frame (size_class +
        domain_plausible + scene_preset). hide_names is the full 209 pool, hidden
        first so distractors shown in an earlier frame do not linger.
    """
    placed_aabbs = []
    placed_objs = []
    for name in PALLET_NAMES + BOX_NAMES:
        obj = get_obj(name)
        if obj and not obj.hide_render:
            try:
                placed_aabbs.append(get_obj_aabb_world(obj))
                placed_objs.append(obj)
            except Exception:
                pass

    px, py = pallet_pos[0], pallet_pos[1]
    cx, cy = cam_pos[0], cam_pos[1]
    cam_to_pallet_angle = math.atan2(py - cy, px - cx)

    if distractor_names is not None:
        # v2 path: exact per-frame set already selected by distractor_pool_v2. Hide
        # the whole pool first (stale-visibility guard across scene_presets), then
        # place the selected ones; any that fail to place are hidden in the loop.
        if hide_names:
            for name in hide_names:
                obj = get_obj(name)
                if obj is not None:
                    set_render_visibility(obj, False)
        used = list(distractor_names)
        hidden = []
    else:
        # legacy path (unchanged): shuffle the hard-coded pool, take a random count.
        shuffled = list(DISTRACTOR_NAMES)
        random.shuffle(shuffled)
        max_count = (
            DISTRACTOR_RANDOMIZATION["max_count_heavy"]
            if prefer_occlusion
            else DISTRACTOR_RANDOMIZATION["max_count_light"]
        )
        n_use = random.randint(
            DISTRACTOR_RANDOMIZATION["min_count"],
            min(max_count, len(shuffled)),
        )
        used = shuffled[:n_use]
        hidden = shuffled[n_use:]
    central_occluder_count = 0
    max_central_occluders = 2 if prefer_occlusion else 1
    # Even in "light" mode, 30% chance of placing a central occluder
    allow_central = prefer_occlusion or (random.random() < 0.30)
    cam_pallet_dist = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)

    for name in used:
        obj = get_obj(name)
        if obj is None:
            continue
        set_render_visibility(obj, True)

        placed = False
        for _ in range(DISTRACTOR_RANDOMIZATION["placement_attempts"]):
            if allow_central and central_occluder_count < max_central_occluders:
                offset_angle = (
                    cam_to_pallet_angle
                    + math.pi
                    + random.uniform(
                        -DISTRACTOR_RANDOMIZATION["central_angle_jitter_rad"],
                        DISTRACTOR_RANDOMIZATION["central_angle_jitter_rad"],
                    )
                )
                # Scale distance proportionally to camera-pallet distance
                # Place at 20-50% of the way from pallet toward camera
                fraction = random.uniform(0.20, 0.50)
                dist = max(0.7, cam_pallet_dist * fraction)
                lateral = random.uniform(*DISTRACTOR_RANDOMIZATION["central_lateral_range"])
                x = px + dist * math.cos(offset_angle) + lateral * math.cos(cam_to_pallet_angle + math.pi / 2)
                y = py + dist * math.sin(offset_angle) + lateral * math.sin(cam_to_pallet_angle + math.pi / 2)
            else:
                side = random.choice([-1, 1])
                angle_min, angle_max = DISTRACTOR_RANDOMIZATION["side_angle_fraction_range"]
                offset_angle = cam_to_pallet_angle + side * random.uniform(math.pi * angle_min, math.pi * angle_max)
                dist = random.uniform(*DISTRACTOR_RANDOMIZATION["side_distance_range"])
                x = px + dist * math.cos(offset_angle)
                y = py + dist * math.sin(offset_angle)

            set_object_pose_grounded(
                obj,
                x,
                y,
                random.uniform(*DISTRACTOR_RANDOMIZATION["yaw_range_rad"]),
                ground_z=0.0,
            )

            bpy.context.view_layer.update()
            a_min, a_max = get_obj_aabb_world(obj)

            overlap = False
            for b_min, b_max in placed_aabbs:
                if aabb_overlap_xy(a_min, a_max, b_min, b_max):
                    overlap = True
                    break
            if not overlap:
                for pobj in placed_objs:
                    if mesh_overlap(obj, pobj):
                        overlap = True
                        break

            if not overlap and is_ground_contact_ok(obj, target_z=0.0):
                placed_aabbs.append((a_min, a_max))
                placed_objs.append(obj)
                if allow_central and central_occluder_count < max_central_occluders:
                    central_occluder_count += 1
                placed = True
                break

        if not placed:
            set_render_visibility(obj, False)

    for name in hidden:
        obj = get_obj(name)
        if obj:
            set_render_visibility(obj, False)


def _get_box_base_scale(obj):
    if obj.name not in _box_base_scales:
        _box_base_scales[obj.name] = tuple(obj.scale)
    return _box_base_scales[obj.name]


def _reset_box_scale(obj):
    obj.scale = _get_box_base_scale(obj)


def _apply_box_shape_profile(obj, occlusion_target):
    profiles = BOX_SHAPE_PROFILES
    if occlusion_target == "heavy":
        excluded = set(BOX_RANDOMIZATION["profile_exclude"].get("heavy", []))
    else:
        excluded = set(BOX_RANDOMIZATION["profile_exclude"].get("light", []))
    profiles = [p for p in BOX_SHAPE_PROFILES if p["name"] not in excluded] or BOX_SHAPE_PROFILES

    profile = random.choice(profiles)
    jitter = (
        random.uniform(*BOX_RANDOMIZATION["shape_scale_jitter_xy"]),
        random.uniform(*BOX_RANDOMIZATION["shape_scale_jitter_xy"]),
        random.uniform(*BOX_RANDOMIZATION["shape_scale_jitter_z"]),
    )
    base_scale = _get_box_base_scale(obj)
    obj.scale = tuple(
        base_scale[i] * profile["scale"][i] * jitter[i]
        for i in range(3)
    )
    return profile["name"]


def randomize_boxes(pallet_obj, pallet_name=None, occlusion_target="light", target_box_count=None):
    """Place varied cargo boxes on the pallet top plane."""
    min_boxes = BOX_RANDOMIZATION["min_boxes"]
    max_boxes = (
        BOX_RANDOMIZATION["max_boxes_heavy"]
        if occlusion_target == "heavy"
        else BOX_RANDOMIZATION["max_boxes_light"]
    )
    if target_box_count is not None and int(target_box_count) == 0:
        # Empty pallet — hide all boxes and return immediately
        for name in BOX_NAMES:
            obj = get_obj(name)
            if obj:
                _reset_box_scale(obj)
                set_render_visibility(obj, False)
        return 0
    if target_box_count is None:
        num_boxes = random.randint(min_boxes, min(max_boxes, len(BOX_NAMES)))
    else:
        num_boxes = max(min_boxes, min(int(target_box_count), min(max_boxes, len(BOX_NAMES))))
    selected = sorted(random.sample(range(len(BOX_NAMES)), min(num_boxes, len(BOX_NAMES))))

    pallet_geom = get_pallet_geometry(
        pallet_name,
        pallet_obj,
        ORIENTATION_OVERRIDES,
    )
    if pallet_geom is None:
        for name in BOX_NAMES:
            obj = get_obj(name)
            if obj:
                _reset_box_scale(obj)
                set_render_visibility(obj, False)
        return False

    top_center = pallet_geom["top_center_world"]
    top_z = pallet_geom["top_z_world"]
    width_dir = pallet_geom["width_dir_world"]
    depth_dir = pallet_geom["depth_dir_world"]
    width_span = pallet_geom["width_len_world"] * (
        BOX_RANDOMIZATION["width_span_factor_heavy"]
        if occlusion_target == "heavy"
        else BOX_RANDOMIZATION["width_span_factor_light"]
    )
    depth_span = pallet_geom["depth_len_world"] * (
        BOX_RANDOMIZATION["depth_span_factor_heavy"]
        if occlusion_target == "heavy"
        else BOX_RANDOMIZATION["depth_span_factor_light"]
    )
    pallet_yaw = math.atan2(width_dir[1], width_dir[0])

    slot_offsets = (
        BOX_RANDOMIZATION["slot_offsets_heavy"]
        if occlusion_target == "heavy"
        else BOX_RANDOMIZATION["slot_offsets_light"]
    )

    placed_boxes = []
    used_slots = []

    for i, name in enumerate(BOX_NAMES):
        obj = get_obj(name)
        if obj is None:
            continue

        if i in selected:
            set_render_visibility(obj, True)

            placed = False
            candidate_slots = slot_offsets.copy()
            random.shuffle(candidate_slots)
            for slot_u, slot_v in candidate_slots:
                if (slot_u, slot_v) in used_slots:
                    continue
                for _ in range(BOX_RANDOMIZATION["placement_attempts_per_slot"]):
                    _reset_box_scale(obj)
                    _apply_box_shape_profile(obj, occlusion_target)
                    jitter_u = slot_u + random.uniform(-BOX_RANDOMIZATION["slot_jitter"], BOX_RANDOMIZATION["slot_jitter"])
                    jitter_v = slot_v + random.uniform(-BOX_RANDOMIZATION["slot_jitter"], BOX_RANDOMIZATION["slot_jitter"])
                    world_xy = top_center + width_dir * (jitter_u * width_span) + depth_dir * (jitter_v * depth_span)
                    yaw = (
                        pallet_yaw
                        + random.choice(BOX_RANDOMIZATION["yaw_options_rad"])
                        + random.uniform(-BOX_RANDOMIZATION["yaw_jitter_rad"], BOX_RANDOMIZATION["yaw_jitter_rad"])
                    )
                    set_object_pose_grounded(
                        obj,
                        float(world_xy[0]),
                        float(world_xy[1]),
                        yaw,
                        ground_z=top_z,
                    )
                    bpy.context.view_layer.update()

                    overlap = False
                    for other in placed_boxes:
                        if mesh_overlap(obj, other):
                            overlap = True
                            break
                    if overlap:
                        continue

                    if not is_ground_contact_ok(obj, target_z=top_z):
                        continue

                    placed_boxes.append(obj)
                    used_slots.append((slot_u, slot_v))
                    placed = True
                    break
                if placed:
                    break

            if not placed:
                _reset_box_scale(obj)
                set_render_visibility(obj, False)
        else:
            _reset_box_scale(obj)
            set_render_visibility(obj, False)

    return len(placed_boxes)


_hdri_cache = []

def _collect_hdri_images():
    """Collect HDRIs: load from cfg.HDRI_DIR (registry key hdri_root), then cache."""
    if _hdri_cache:
        return _hdri_cache

    # Load HDRIs from disk (warehouse/factory themed)
    hdri_dir = HDRI_DIR
    if os.path.isdir(hdri_dir):
        for ext in ("*.hdr", "*.exr"):
            for path in glob.glob(os.path.join(hdri_dir, ext)):
                name = os.path.basename(path)
                if name not in bpy.data.images:
                    img = bpy.data.images.load(path)
                    print(f"  [HDRI] Loaded: {name}")
                else:
                    img = bpy.data.images[name]
                # Force pixels resident once so EEVEE can build the GPU texture;
                # skip any HDRI that fails to decode (avoids magenta world render).
                try:
                    img.reload()
                    if img.size[0] == 0 or img.size[1] == 0:
                        print(f"  [HDRI] Skipped (no pixels): {name}")
                        continue
                except Exception as exc:
                    print(f"  [HDRI] Skipped (load error {exc}): {name}")
                    continue
                _hdri_cache.append(img)

    # Also include any already-loaded HDRIs
    for img in bpy.data.images:
        fp = img.filepath.lower()
        if ('.hdr' in fp or '.exr' in fp) and img not in _hdri_cache:
            _hdri_cache.append(img)

    print(f"  [HDRI] Total available: {len(_hdri_cache)}")
    return _hdri_cache


def randomize_hdri():
    """Randomize HDRI image, rotation, and exposure."""
    world = bpy.context.scene.world
    if world is None or not world.use_nodes:
        return

    hdris = _collect_hdri_images()

    for node in world.node_tree.nodes:
        if node.type == 'TEX_ENVIRONMENT' and hdris:
            node.image = random.choice(hdris)
        if node.type == 'MAPPING':
            node.inputs['Rotation'].default_value[2] = random.uniform(*HDRI_RANDOMIZATION["rotation_range_rad"])
        if node.type == 'BACKGROUND':
            exposure = random.uniform(*HDRI_RANDOMIZATION["exposure_range_ev"])
            node.inputs['Strength'].default_value = HDRI_BASE_STRENGTH * (2.0 ** exposure)


# --------------------------------------------------------------------------- #
# Floor randomization (fresh flat plane at z=0 + 8-texture per-frame swap).
# The shipped Base_base_m_0 is a grooved grating, not a plane, so real floor
# textures read as grey slats. We drop ONE fresh plane just under the pallet and
# retexture it per frame, hiding the grating/fence/marks overlays once.
# --------------------------------------------------------------------------- #
_floor_image_cache = {}
_floor_grating_hidden = False
_floor_force_state = {"i": 0}


def _floor_img(filename, non_color=False):
    """Load (cache) a floor texture; data maps use Non-Color colorspace."""
    key = (filename, non_color)
    img = _floor_image_cache.get(key)
    if img is not None and img.name in bpy.data.images:
        return img
    path = os.path.join(FLOOR_TEXTURE_DIR, filename)
    if not os.path.isfile(path):
        print(f"  [FLOOR] missing texture: {path}")
        return None
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    except Exception:
        pass
    _floor_image_cache[key] = img
    return img


def _hide_floor_grating():
    """Hide fence + grooved base_m grating + lane marks once, so only our fresh
    plane is the visible ground."""
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
    print(f"  [FLOOR] hid {n} grating/fence/marks overlay meshes")


def _hide_bg_ground():
    """Hide BG_industrial's own grey asphalt ground (20 'Floor*_Asphalt_0' FBX
    meshes whose surface sits at z~=0) EVERY frame. randomize_background()
    re-shows the whole BG_industrial hierarchy each frame, which re-enables these
    floors and they occlude our FloorRandPlane (z=-6mm) -> the floor always read as
    the same grey asphalt regardless of the chosen floor_texture. Not cached: must
    run after every randomize_background()."""
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
    """Create (once) a large flat plane with planar UVs and its own material."""
    obj = get_obj(FLOOR_PLANE_NAME)
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
    return obj


def _build_floor_material(mat, name, uv_scale, tint):
    """Rebuild plane material with diffuse(× tint)/roughness/normal + uv tiling."""
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
    # Bright industrial HDRIs wash the floor to grey (measured sat ~7%). Boost
    # saturation so colour survives, and darken a touch so it isn't blown out.
    hsv = nt.nodes.new("ShaderNodeHueSaturation"); hsv.location = (-850, 200)
    hsv.inputs["Saturation"].default_value = FLOOR_SATURATION_BOOST
    hsv.inputs["Value"].default_value = FLOOR_VALUE_SCALE
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
    """Per-frame floor randomization: hide grating once, position the fresh plane
    under the pallet, pick one of 8 textures with random uv_scale + tint.

    The plane sits FLOOR_PLANE_Z (6mm) below z=0 so it never occludes the
    on-ground raycast silhouette points (bottom corners at z~=0). Returns the
    chosen floor descriptor for annotation."""
    _hide_floor_grating()
    # randomize_background() (called before us every frame) re-shows the whole
    # BG_industrial hierarchy, including its 20 grey asphalt ground meshes that sit
    # at z~=0 and occlude our plane. Re-hide them per frame so the fresh plane is
    # the only visible ground.
    _hide_bg_ground()
    plane = _ensure_floor_plane()
    plane.location = (float(pallet_pos[0]), float(pallet_pos[1]), FLOOR_PLANE_Z)
    plane.hide_render = False
    plane.hide_viewport = False

    # Optional deterministic cycling for preview sheets (FLOOR_FORCE_SEQUENCE=1):
    # walk through FLOOR_CANDIDATES in order so a short example run shows distinct
    # floors. Default (unset) keeps uniform random.choice for training.
    if os.environ.get("FLOOR_FORCE_SEQUENCE") == "1":
        idx = _floor_force_state["i"] % len(FLOOR_CANDIDATES)
        name = FLOOR_CANDIDATES[idx]
    else:
        name = random.choice(FLOOR_CANDIDATES)
    metres_per_tile = random.uniform(*FLOOR_UV_SCALE_RANGE)
    # tiles across the whole plane so each repeat is ~metres_per_tile in world space
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
