"""Isaac Sim synthetic-data configuration loaded from config/synthetic/isaac_sim.yaml."""

import json
import os

try:
    import yaml
except ImportError:
    yaml = None


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
ISAAC_SIM_SYNTH_CONFIG_PATH = os.environ.get(
    "FOUNDATIONPOSE_ISAACSIM_CONFIG",
    os.path.join(PROJECT_ROOT, "config", "synthetic", "isaac_sim.yaml"),
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


def _tuple_floats(values):
    return tuple(float(v) for v in values)


def _dict_floats(values):
    return {str(k): float(v) for k, v in values.items()}


_CFG = _load_config(ISAAC_SIM_SYNTH_CONFIG_PATH)

_PATHS = _CFG["paths"]
_RENDER = _CFG["render"]
_GENERATION = _CFG["generation"]
_CAMERA = _CFG["camera"]
_DISTRACTORS = _CFG["distractors"]
_CARGO = _CFG["cargo"]
_PALLET = _CFG["pallet"]
_BACKGROUND = _CFG["background"]
_MATERIALS = _CFG["materials"]
_LIGHTING = _CFG["lighting"]


# Paths
GLTF_DIR = _resolve_project_path(_PATHS["gltf_dir"])
GLTF_FILES = [str(name) for name in _PATHS["gltf_files"]]
USD_CACHE_DIR = _resolve_project_path(_PATHS["usd_cache_dir"])
DEFAULT_OUTPUT_DIR = _resolve_project_path(_PATHS["default_output_dir"])
ISAAC_ASSETS_ROOT = _resolve_project_path(_PATHS["isaac_assets_root"]).replace("\\", "/")
HDRI_DIR_LOCAL = _resolve_project_path(_PATHS["hdri_dir"]).replace("\\", "/")
PROCEDURAL_TEX_DIR = _resolve_project_path(_PATHS["procedural_texture_dir"])


# Render
IMAGE_WIDTH = int(_RENDER["image_width"])
IMAGE_HEIGHT = int(_RENDER["image_height"])
FOCAL_LENGTH = float(_RENDER["focal_length"])
SENSOR_WIDTH = float(_RENDER["sensor_width"])
PALLET_TARGET_SIZE = float(_RENDER["pallet_target_size"])
WARMUP_STEPS = int(_RENDER["warmup_steps"])
RT_SUBFRAMES_PT = int(_RENDER["rt_subframes_pt"])
RT_SUBFRAMES_RTL = int(_RENDER["rt_subframes_rtl"])
MIN_VISIBILITY = float(_GENERATION["min_visibility"])
MAX_FRAME_RETRIES = int(_GENERATION["max_retries"])


# Camera
CAMERA_MODE_PROBS = [float(v) for v in _CAMERA["mode_probabilities"]]
CAMERA_CONSTRAINTS = _dict_floats(_CAMERA["mode_a"])
CAMERA_MODE_B = _dict_floats(_CAMERA["mode_b"])
FRONT_VIEW_CONSTRAINTS = _dict_floats(_CAMERA["mode_c"])
LOOK_AT_TARGET = _tuple_floats(_CAMERA["look_at_target"])
LOOK_AT_JITTER = float(_CAMERA["look_at_jitter"])
FRONT_VIEW_PROBABILITY = _CAMERA.get("front_view_probability")
if FRONT_VIEW_PROBABILITY is not None:
    FRONT_VIEW_PROBABILITY = float(FRONT_VIEW_PROBABILITY)


# Distractors / cargo
MAX_DISTRACTORS_PER_FRAME = int(_DISTRACTORS["max_per_frame"])
MAX_DISTRACTOR_POOL = int(_DISTRACTORS["max_pool"])
DISTRACTOR_ACTIVE_COUNT_MIN = int(_DISTRACTORS["active_count_min"])
DISTRACTOR_DEFAULT_HALF_EXTENTS = _tuple_floats(_DISTRACTORS["default_pallet_half_extents"])
DISTRACTOR_FLOOR_SAMPLING = {
    "max_attempts": int(_DISTRACTORS["floor_sampling"]["max_attempts"]),
    "corridor_half_width": float(_DISTRACTORS["floor_sampling"]["corridor_half_width"]),
    "xy_range": _tuple_floats(_DISTRACTORS["floor_sampling"]["xy_range"]),
    "z_range": _tuple_floats(_DISTRACTORS["floor_sampling"]["z_range"]),
    "fallback_away_multiplier": float(_DISTRACTORS["floor_sampling"]["fallback_away_multiplier"]),
    "fallback_jitter_xy": _tuple_floats(_DISTRACTORS["floor_sampling"]["fallback_jitter_xy"]),
}
DISTRACTOR_CARGO_LOCAL_FRACTION = float(_DISTRACTORS["cargo_local_fraction"])
DISTRACTOR_CARGO_ROTATION_RANGE = {
    axis: _tuple_floats(_DISTRACTORS["cargo_rotation_deg"][axis])
    for axis in ("x", "y", "z")
}
DISTRACTOR_CARGO_PRIMITIVE_Z_SCALE_RANGE = _tuple_floats(_DISTRACTORS["cargo_primitive_z_scale_range"])
DISTRACTOR_FLOOR_ROTATION_RANGE = {
    axis: _tuple_floats(_DISTRACTORS["floor_rotation_deg"][axis])
    for axis in ("x", "y", "z")
}
DISTRACTOR_PROP_SCALE_RANGE = _tuple_floats(_DISTRACTORS["prop_scale_range"])
DISTRACTOR_PRIMITIVE_SCALE_RANGES = {
    axis: _tuple_floats(_DISTRACTORS["primitive_scale_ranges"][axis])
    for axis in ("x", "y", "z")
}
DISTRACTOR_PRIMITIVE_COLOR_RANGES = {
    "cardboard": {
        "min": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["cardboard"]["min"]),
        "max": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["cardboard"]["max"]),
    },
    "plastic": {
        "min": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["plastic"]["min"]),
        "max": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["plastic"]["max"]),
    },
    "concrete": {
        "base": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["concrete"]["base"]),
        "g_multiplier": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["concrete"]["g_multiplier"]),
        "b_multiplier": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["concrete"]["b_multiplier"]),
    },
    "metal": {
        "base": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["metal"]["base"]),
        "b_multiplier": _tuple_floats(_DISTRACTORS["primitive_color_ranges"]["metal"]["b_multiplier"]),
    },
}
DISTRACTOR_PROPS = [str(path) for path in _DISTRACTORS["nucleus_props"]]
DISTRACTOR_CATEGORIES = {
    str(name): [str(path) for path in paths]
    for name, paths in _DISTRACTORS["categories"].items()
}
DISTRACTOR_PROPS_LOCAL = [path for group in DISTRACTOR_CATEGORIES.values() for path in group]

CARGO_ON_PALLET_PROBABILITY = float(_CARGO["on_pallet_probability"])
CARGO_OCCLUSION_TIERS = [
    (
        float(tier["probability"]),
        int(tier["max_count"]),
        _tuple_floats(tier["scale_range"]),
    )
    for tier in _CARGO["occlusion_tiers"]
]
PALLET_SURFACE_HEIGHT = float(_CARGO["surface_height"])
CARGO_Z_CLEARANCE = float(_CARGO["z_clearance"])


# Pallet appearance
PALLET_COLORS = [_tuple_floats(color) for color in _PALLET["colors"]]
PALLET_TILT_MAX = float(_PALLET["tilt_max"])
PALLET_COLOR_PALETTE_PROBABILITY = float(_PALLET["palette_probability"])
PALLET_COLOR_HSV_RANGE = {
    axis: _tuple_floats(_PALLET["hsv_range"][axis])
    for axis in ("h", "s", "v")
}
PALLET_POSITION_X_RANGE = _tuple_floats(_PALLET["position_xy_range"]["x"])
PALLET_POSITION_Y_RANGE = _tuple_floats(_PALLET["position_xy_range"]["y"])


# Background / assets
WAREHOUSE_USD = str(_BACKGROUND["warehouse_usd"])
WAREHOUSE_VARIANTS_LOCAL = [
    os.path.join(ISAAC_ASSETS_ROOT, rel_path).replace("\\", "/")
    for rel_path in _BACKGROUND["warehouse_local_variants"]
]
WAREHOUSE_USD_LOCAL = WAREHOUSE_VARIANTS_LOCAL[0] if WAREHOUSE_VARIANTS_LOCAL else ""
WAREHOUSE_BG_PROBABILITY = float(_BACKGROUND["warehouse_probability"])
OUTDOOR_BG_PROBABILITY = float(_BACKGROUND["outdoor_probability"])


# Materials
FLOOR_DIFFUSE_RANGE = tuple(_tuple_floats(rgb) for rgb in _MATERIALS["floor_diffuse_range"])
WALL_DIFFUSE_RANGE = tuple(_tuple_floats(rgb) for rgb in _MATERIALS["wall_diffuse_range"])
TEXTURE_REALISTIC_PROBABILITY = float(_MATERIALS["texture_realistic_probability"])


# Lighting
LIGHTING_RANDOMIZATION = {
    "dome_intensity_range": _tuple_floats(_LIGHTING["dome_intensity_range"]),
    "main": {
        "color_min": _tuple_floats(_LIGHTING["main"]["color_min"]),
        "color_max": _tuple_floats(_LIGHTING["main"]["color_max"]),
        "intensity_range": _tuple_floats(_LIGHTING["main"]["intensity_range"]),
        "position_min": _tuple_floats(_LIGHTING["main"]["position_min"]),
        "position_max": _tuple_floats(_LIGHTING["main"]["position_max"]),
        "rotation_min": _tuple_floats(_LIGHTING["main"]["rotation_min"]),
        "rotation_max": _tuple_floats(_LIGHTING["main"]["rotation_max"]),
    },
    "fill_1": {
        "color_min": _tuple_floats(_LIGHTING["fill_1"]["color_min"]),
        "color_max": _tuple_floats(_LIGHTING["fill_1"]["color_max"]),
        "intensity_range": _tuple_floats(_LIGHTING["fill_1"]["intensity_range"]),
        "position_min": _tuple_floats(_LIGHTING["fill_1"]["position_min"]),
        "position_max": _tuple_floats(_LIGHTING["fill_1"]["position_max"]),
        "visible_probability": float(_LIGHTING["fill_1"]["visible_probability"]),
    },
    "fill_2": {
        "color_min": _tuple_floats(_LIGHTING["fill_2"]["color_min"]),
        "color_max": _tuple_floats(_LIGHTING["fill_2"]["color_max"]),
        "intensity_range": _tuple_floats(_LIGHTING["fill_2"]["intensity_range"]),
        "position_min": _tuple_floats(_LIGHTING["fill_2"]["position_min"]),
        "position_max": _tuple_floats(_LIGHTING["fill_2"]["position_max"]),
        "visible_probability": float(_LIGHTING["fill_2"]["visible_probability"]),
    },
}
