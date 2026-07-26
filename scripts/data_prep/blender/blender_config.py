"""Blender synthetic-data configuration loaded from config/synthetic/blender.yaml."""

import json
import os

import numpy as np

try:
    import yaml
except ImportError:  # Blender may not have PyYAML in every environment.
    yaml = None


def _detect_project_root():
    try:
        import bpy

        project_root = os.path.abspath(
            os.path.join(os.path.dirname(bpy.data.filepath), "..", "..", "..")
        )
        if not os.path.isdir(os.path.join(project_root, "data", "pallet")):
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        return project_root
    except Exception:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


PROJECT_ROOT = _detect_project_root()
BLENDER_SYNTH_CONFIG_PATH = os.environ.get(
    "FOUNDATIONPOSE_BLENDER_CONFIG",
    os.path.join(PROJECT_ROOT, "config", "synthetic", "blender.yaml"),
)


def _load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()
    if yaml is not None:
        return yaml.safe_load(text)
    return json.loads(text)


def _resolve_project_path(path_value):
    if path_value is None:
        return None
    if os.path.isabs(path_value):
        return path_value
    return os.path.join(PROJECT_ROOT, path_value)


def _float_tuple(values):
    return tuple(float(v) for v in values)


def _int_tuple(values):
    return tuple(int(v) for v in values)


_CFG = _load_config(BLENDER_SYNTH_CONFIG_PATH)

_RENDER = _CFG["render"]
_OUTPUT = _CFG["output"]
_ASSETS = _CFG["assets"]
_BACKGROUND = _CFG["background"]
_APPEARANCE = _CFG["appearance"]
_CAMERA = _CFG["camera"]
_QUALITY = _CFG["quality"]
_GENERATION = _CFG["generation"]
_PLACEMENT = _CFG["placement"]
_RANDOMIZATION = _CFG["randomization"]
_GEOMETRY = _CFG["geometry"]
_OVERLAY = _CFG["overlay"]
_LIGHTING = _CFG["lighting"]


# Render
NUM_FRAMES = int(_RENDER["num_frames"])
IMAGE_WIDTH = int(_RENDER["image_width"])
IMAGE_HEIGHT = int(_RENDER["image_height"])
SENSOR_WIDTH = float(_RENDER["sensor_width"])
FX = float(_RENDER["intrinsics"]["fx"])
FY = float(_RENDER["intrinsics"]["fy"])
CX = float(_RENDER["intrinsics"]["cx"])
CY = float(_RENDER["intrinsics"]["cy"])
VIEW_TRANSFORM = str(_RENDER["view_transform"])
VIEW_LOOK = str(_RENDER["view_look"])
IMAGE_FILE_FORMAT = str(_RENDER["file_format"])
IMAGE_COLOR_MODE = str(_RENDER["color_mode"])
TAA_RENDER_SAMPLES = int(_RENDER["taa_render_samples"])


# Paths
OUTPUT_BASE_DIR = _resolve_project_path(_OUTPUT["base_dir"])
OUTPUT_VERSION_PREFIX = str(_OUTPUT["version_prefix"])
OVERLAY_SUBDIR = str(_OUTPUT["overlay_subdir"])
SAVE_OVERLAY = bool(_OUTPUT.get("save_overlay", True))
OUTPUT_DIR_OVERRIDE = os.environ.get("FOUNDATIONPOSE_BLENDER_OUTPUT_DIR")


def _next_output_dir():
    base = OUTPUT_BASE_DIR
    version = 1
    while os.path.exists(os.path.join(base, f"{OUTPUT_VERSION_PREFIX}{version}")):
        version += 1
    return os.path.join(base, f"{OUTPUT_VERSION_PREFIX}{version}")


OUTPUT_DIR = _resolve_project_path(OUTPUT_DIR_OVERRIDE) if OUTPUT_DIR_OVERRIDE else _next_output_dir()
OVERLAY_DIR = os.path.join(OUTPUT_DIR, OVERLAY_SUBDIR) if SAVE_OVERLAY else None


# Assets
PALLET_NAMES = [str(name) for name in _ASSETS["pallet_names"]]
PALLET_WEIGHTS = [float(weight) for weight in _ASSETS["pallet_weights"]]
PALLET_SOURCE_DIR = _resolve_project_path(_ASSETS["pallet_source_dir"])
PALLET_SOURCE_ASSETS = {
    str(name): str(asset)
    for name, asset in _ASSETS["pallet_source_assets"].items()
}
DISTRACTOR_NAMES = [str(name) for name in _ASSETS["distractor_names"]]
BOX_NAMES = [str(name) for name in _ASSETS["box_names"]]
BOX_SHAPE_PROFILES = [
    {
        "name": str(profile["name"]),
        "scale": _float_tuple(profile["scale"]),
    }
    for profile in _ASSETS["box_shape_profiles"]
]


# Backgrounds
BACKGROUND_ASSETS = {}
for key, asset_cfg in _BACKGROUND["assets"].items():
    item = dict(asset_cfg)
    if "filepath" in item:
        item["filepath"] = _resolve_project_path(item["filepath"])
    item["weight"] = float(item.get("weight", 1.0))
    BACKGROUND_ASSETS[str(key)] = item
BACKGROUND_KEYS = [str(key) for key in _BACKGROUND.get("keys", list(BACKGROUND_ASSETS.keys()))]
BACKGROUND_WEIGHTS = {
    key: float(BACKGROUND_ASSETS.get(key, {}).get("weight", 1.0))
    for key in BACKGROUND_KEYS
}


# Appearance
PALLET_COLOR_GROUP_FOR_MODEL = {
    str(name): str(group)
    for name, group in _APPEARANCE["pallet_color_group_for_model"].items()
}
def _variant_entry(variant):
    entry = {
        "name": str(variant["name"]),
        "base_color": _float_tuple(variant["base_color"]),
        "roughness": float(variant["roughness"]),
        "specular": float(variant["specular"]),
        "weight": float(variant["weight"]),
    }
    # Optional texture-based wood material (albedo + normal + roughness maps).
    # When "texture" is present, the material wires an Image Texture into Base
    # Color (× tint multiply for brightness DR) instead of a flat color.
    if variant.get("texture"):
        entry["texture"] = str(variant["texture"])
    if variant.get("normal"):
        entry["normal"] = str(variant["normal"])
    if variant.get("roughness_map"):
        entry["roughness_map"] = str(variant["roughness_map"])
    if variant.get("tint") is not None:
        entry["tint"] = _float_tuple(variant["tint"])
    if variant.get("tint_strength") is not None:
        entry["tint_strength"] = float(variant["tint_strength"])
    if variant.get("uv_scale") is not None:
        entry["uv_scale"] = float(variant["uv_scale"])
    if variant.get("uv_rotation") is not None:
        entry["uv_rotation"] = float(variant["uv_rotation"])
    return entry


PALLET_COLOR_VARIANTS = {
    str(group): [_variant_entry(variant) for variant in variants]
    for group, variants in _APPEARANCE["pallet_color_variants"].items()
}

WOOD_TEXTURE_DIR = os.path.join(PROJECT_ROOT, "data", "pallet", "textures_wood")

# ---------------------------------------------------------------------------
# Floor randomization (gen_dataset_v4). The shipped scene floor `Base_base_m_0`
# is NOT a flat plane -- it is a grooved grating/trench geometry, so real floor
# textures get chopped into grey slats (proved by _diag_floor3 / floor compare).
# Fix: drop ONE fresh flat plane at z=0 under the pallet and texture THAT, hiding
# the grating + fence + lane-marks overlays. All scene objects ground to z=0
# (pallet, boxes, distractors via snap_object_to_ground), so a z=0 plane is the
# exact ground they sit on -> grounding/shadows preserved. The plane is dropped a
# hair (FLOOR_PLANE_Z) BELOW z=0 so it never occludes the on-ground raycast
# silhouette points (bottom corners at z~=0) -> visibility gate unaffected.
FLOOR_TEXTURE_DIR = os.path.join(PROJECT_ROOT, "data", "pallet", "textures_floor")
FLOOR_PLANE_NAME = "FloorRandPlane"
FLOOR_PLANE_SIZE = 50.0          # metres. Must dominate the oblique view: at low
# elevation the near foreground extends far past the pallet, so a small plane
# leaves the (grey) HDRI ground visible in front -> floors looked identical. A
# large plane makes the chosen texture fill the whole ground.
FLOOR_PLANE_Z = -0.006           # 6mm below ground (sub-pixel) to clear raycast
FLOOR_GRATING_HIDE = ("Base_fence",)          # name prefixes to hide
FLOOR_GRATING_HIDE_EXACT = ("Base_base_m_0", "Base_marks_m_0")  # exact mesh names
# BG_industrial ships its OWN grey asphalt ground: 20 "Floor*_Asphalt_0" FBX
# meshes whose surface sits at z~=0. randomize_background() re-shows the whole
# BG_industrial hierarchy every frame (set_render_visibility), so these asphalt
# floors re-appear and OCCLUDE our FloorRandPlane (z=-6mm just below) -> the floor
# reads as the SAME grey asphalt no matter which floor_texture we picked. We must
# hide these every frame (after the bg is shown), so the fresh plane is the only
# visible ground. Prefix-matched so all Floor.NNN variants are caught.
FLOOR_BG_GROUND_HIDE = ("Floor",)             # BG_industrial asphalt ground prefix
# Smaller UV scale -> larger floor pattern on screen (was 2.0-3.5; patterns too
# fine to tell floors apart). Tint keeps a slight per-channel hue jitter (not just
# grey darken) so even same-texture frames vary in warmth.
FLOOR_UV_SCALE_RANGE = (1.5, 3.0)             # metres per texture repeat. Small
# tiles so floor patterns (brick ~0.2m, tile ~0.4m) read at a realistic scale,
# smaller than the 1.1m pallet. Past LARGE 4-9m made motifs pallet-sized
# (unrealistic); the grey-mush risk that once motivated large tiles was actually the
# BG asphalt occlusion, now fixed by FLOOR_BG_GROUND_HIDE. Tiles = FLOOR_PLANE_SIZE / value.
FLOOR_TINT_RANGE = (0.85, 1.05)               # per-frame MULTIPLY tint (each RGB)
FLOOR_SATURATION_BOOST = 2.0   # counter Filmic + bright-HDRI wash-out (floor sat ~7%
# without it). Strong boost so hue survives even in brightly-lit highlight regions.
FLOOR_VALUE_SCALE = 0.85       # mild darken only: keep the light/dark tonal SPREAD
# across candidates (white tile must stay light, asphalt dark) -- heavy darkening
# flattened every floor to the same mid-tone and lost tonal contrast.
# 11 candidate floors chosen for STRONG colour/tone/pattern contrast (not grey-
# concrete clustered). Each stem expects _diff/_nor_gl/_rough.png in
# textures_floor/. Mix: bright tile, warm wood, terracotta/brown tile, red brick,
# brown dirt, red earth (colour) + a few greys (dark asphalt, mid concrete,
# cobble) for realism. Grey-concrete family trimmed to 3.
FLOOR_CANDIDATES = [
    # --- colour / warm / bright (boosted weight) ---
    "tile_white",          # bright off-white tile (R~205) - lightest
    "wood_laminate",       # warm honey wood planks (warm +56)
    "tile_brown",          # terracotta honey tile (warm +53)
    "red_brick",           # saturated red/orange brick (R142 warm +62)
    "dirt_ground",         # olive-brown earth/dirt
    "red_earth",           # reddish cracked ground (warm +49)
    "brick_floor_02",      # dark brown brick (existing)
    # --- grey / dark (trimmed to give tonal contrast vs the colour set) ---
    "asphalt_02",          # dark grey asphalt (R~91) - darkest
    "concrete_floor_02",   # mid grey concrete
    "cobblestone_floor_08",# light grey cobble (R~146)
    "gravel_concrete_02",  # light warm gravel
]


# Camera / quality
CAMERA_VIEW_MODES = {
    str(name): {
        **cfg,
        "weight": float(cfg.get("weight", 1.0)),
        "distance": _float_tuple(cfg["distance"]),
        "distance_bias": float(cfg.get("distance_bias", 1.0)),
        "height_base": _float_tuple(cfg["height_base"]),
        "height_scale": _float_tuple(cfg["height_scale"]),
        "look_offset": _float_tuple(cfg["look_offset"]),
        "center_prob": float(cfg["center_prob"]),
        "angle_mode": str(cfg["angle_mode"]),
        "angle_jitter_deg": float(cfg["angle_jitter_deg"]),
        "min_area_ratio": float(cfg["min_area_ratio"]),
    }
    for name, cfg in _CAMERA["view_modes"].items()
}
CAMERA_DISTANCE_BUCKETS = {
    str(name): _float_tuple(bounds)
    for name, bounds in _CAMERA["distance_buckets"].items()
}
VISIBLE_MIN_FRACTION = float(_QUALITY["visible_min_fraction"])
OCCLUSION_HEAVY_RAY_RANGE = _float_tuple(_QUALITY["occlusion_heavy_ray_range"])
OCCLUSION_LIGHT_RAY_RANGE = _float_tuple(_QUALITY["occlusion_light_ray_range"])
MIN_PROJECTED_AREA_RATIO = float(_QUALITY["min_projected_area_ratio"])
FAR_VIEW_MIN_PROJECTED_AREA_RATIO = float(_QUALITY["far_view_min_projected_area_ratio"])


# Generation
MAX_FRAME_RETRIES = int(_GENERATION["max_retries"])
THREE_BOX_PROBABILITY = float(_GENERATION["three_box_probability"])
EMPTY_PALLET_PROBABILITY = float(_GENERATION.get("empty_pallet_probability", 0.0))
HEAVY_OCCLUSION_PROBABILITY = float(_GENERATION["heavy_occlusion_probability"])
ULTRA_FAR_HEAVY_OCCLUSION_PROBABILITY = float(_GENERATION["ultra_far_heavy_occlusion_probability"])


# Placement
PALLET_PLACEMENT_X_RANGE = _float_tuple(_PLACEMENT["pallet_xy_range"]["x"])
PALLET_PLACEMENT_Y_RANGE = _float_tuple(_PLACEMENT["pallet_xy_range"]["y"])
PALLET_PLACEMENT_ATTEMPTS = int(_PLACEMENT["pallet_attempts"])
PALLET_COLLISION_MARGIN = float(_PLACEMENT["collision_margin"])
AABB_OVERLAP_DEFAULT_MARGIN = float(_PLACEMENT["aabb_overlap_margin"])
STATIC_OBSTACLE_SETTINGS = {
    "skip_prefixes": tuple(str(v) for v in _PLACEMENT["static_obstacles"]["skip_prefixes"]),
    "min_height": float(_PLACEMENT["static_obstacles"]["min_height"]),
    "min_width": float(_PLACEMENT["static_obstacles"]["min_width"]),
}


# Randomization details
CAMERA_RANDOMIZATION = {
    "front_bias_reverse_probability": float(_RANDOMIZATION["camera"]["front_bias_reverse_probability"]),
    "look_z_min": float(_RANDOMIZATION["camera"]["look_z_min"]),
    "look_z_scale_range": _float_tuple(_RANDOMIZATION["camera"]["look_z_scale_range"]),
}
DISTRACTOR_RANDOMIZATION = {
    "min_count": int(_RANDOMIZATION["distractors"]["min_count"]),
    "max_count_light": int(_RANDOMIZATION["distractors"]["max_count_light"]),
    "max_count_heavy": int(_RANDOMIZATION["distractors"]["max_count_heavy"]),
    "placement_attempts": int(_RANDOMIZATION["distractors"]["placement_attempts"]),
    "central_angle_jitter_rad": np.radians(float(_RANDOMIZATION["distractors"]["central_angle_jitter_deg"])),
    "central_distance_range": _float_tuple(_RANDOMIZATION["distractors"]["central_distance_range"]),
    "central_lateral_range": _float_tuple(_RANDOMIZATION["distractors"]["central_lateral_range"]),
    "side_angle_fraction_range": _float_tuple(_RANDOMIZATION["distractors"]["side_angle_fraction_range"]),
    "side_distance_range": _float_tuple(_RANDOMIZATION["distractors"]["side_distance_range"]),
    "yaw_range_rad": tuple(np.radians(_float_tuple(_RANDOMIZATION["distractors"]["yaw_range_deg"]))),
}
BOX_RANDOMIZATION = {
    "min_boxes": int(_RANDOMIZATION["boxes"]["min_boxes"]),
    "max_boxes_light": int(_RANDOMIZATION["boxes"]["max_boxes_light"]),
    "max_boxes_heavy": int(_RANDOMIZATION["boxes"]["max_boxes_heavy"]),
    "width_span_factor_light": float(_RANDOMIZATION["boxes"]["width_span_factor_light"]),
    "width_span_factor_heavy": float(_RANDOMIZATION["boxes"]["width_span_factor_heavy"]),
    "depth_span_factor_light": float(_RANDOMIZATION["boxes"]["depth_span_factor_light"]),
    "depth_span_factor_heavy": float(_RANDOMIZATION["boxes"]["depth_span_factor_heavy"]),
    "slot_offsets_light": [_float_tuple(v) for v in _RANDOMIZATION["boxes"]["slot_offsets_light"]],
    "slot_offsets_heavy": [_float_tuple(v) for v in _RANDOMIZATION["boxes"]["slot_offsets_heavy"]],
    "slot_jitter": float(_RANDOMIZATION["boxes"]["slot_jitter"]),
    "placement_attempts_per_slot": int(_RANDOMIZATION["boxes"]["placement_attempts_per_slot"]),
    "yaw_options_rad": tuple(np.radians(_float_tuple(_RANDOMIZATION["boxes"]["yaw_options_deg"]))),
    "yaw_jitter_rad": float(_RANDOMIZATION["boxes"]["yaw_jitter_rad"]),
    "shape_scale_jitter_xy": _float_tuple(_RANDOMIZATION["boxes"]["shape_scale_jitter_xy"]),
    "shape_scale_jitter_z": _float_tuple(_RANDOMIZATION["boxes"]["shape_scale_jitter_z"]),
    "profile_exclude": {
        str(name): [str(v) for v in values]
        for name, values in _RANDOMIZATION["boxes"]["profile_exclude"].items()
    },
}
HDRI_RANDOMIZATION = {
    "rotation_range_rad": _float_tuple(_RANDOMIZATION["hdri"]["rotation_range_rad"]),
    "exposure_range_ev": _float_tuple(_RANDOMIZATION["hdri"]["exposure_range_ev"]),
}


# Geometry
ORIENTATION_OVERRIDES = {
    str(name): _float_tuple(rot)
    for name, rot in _GEOMETRY["orientation_overrides"].items()
}
CANONICAL_BBOX_MIN = np.array(_GEOMETRY["canonical_bbox_min"], dtype=np.float64)
CANONICAL_BBOX_MAX = np.array(_GEOMETRY["canonical_bbox_max"], dtype=np.float64)
TARGET_CANONICAL_DIMS = CANONICAL_BBOX_MAX - CANONICAL_BBOX_MIN
PALLET_TOP_Z = {
    str(name): float(value)
    for name, value in _GEOMETRY["pallet_top_z"].items()
}
PALLET_SURFACE_Z = float(_GEOMETRY["pallet_surface_z"])


# Overlay
CUBOID_EDGES = [_int_tuple(edge) for edge in _OVERLAY["cuboid_edges"]]
CORNER_COLORS_RGB = [_int_tuple(color) for color in _OVERLAY["corner_colors_rgb"]]


# Lighting
HDRI_BASE_STRENGTH = float(_LIGHTING["hdri_base_strength"])
HDRI_DIR = _resolve_project_path(_LIGHTING["hdri_dir"])


# Intrinsics matrix
K = np.array(
    [
        [FX, 0.0, CX],
        [0.0, FY, CY],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)
