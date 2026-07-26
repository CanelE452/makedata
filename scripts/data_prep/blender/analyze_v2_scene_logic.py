"""EDA for the v2 scene-logic 500-frame pilot.

This script is intentionally bpy-free. It reads the on-disk frame records,
labels, RGB images, and masks, then writes row-level metrics and aggregate
reports. RGB decoding is strict: PIL truncated-image loading is not enabled.

Outputs default to <input>/eda:
  frame_metrics.csv
  summary.json
  baseline_vs_new.json
  reject_reasons.csv
  charts/*.png (22 files, English chart text)
  contact_sheets/
  failure_examples/
  debug_geometry/
  README.md
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402


DEFAULT_DIR = "data/pallet/_v2_scene_logic_500_seed7500"
DEFAULT_OUT_DIRNAME = "eda"
DEFAULT_BASELINE = "data/pallet/_v2_pilot_2k/diagnosis/pilot_frames.csv"
MASK_NAMES = ["m0", "m1", "m2", "m3", "m4"]
GATE_COLUMNS = ["G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass"]
GATE_LABEL_KEYS = [
    ("G1_Vvis>=4", "G1_pass"),
    ("G2_extocc_1to4", "G2_pass"),
    ("G3_visible>=0.5unocc", "G3_pass"),
    ("G4_center_inframe", "G4_pass"),
    ("G5_luma_floor", "G5_pass"),
]

REQUIRED_FRAME_METRIC_FIELDS = [
    "idx",
    "seed",
    "diagnostic_mode",
    "pallet_type",
    "scene_preset",
    "background_asset",
    "floor_mode",
    "elev_target",
    "elev_actual",
    "azimuth_bin",
    "v_target",
    "V_actual",
    "V_vis",
    "projected_size_target",
    "projected_size_actual",
    "anchor_attempts",
    "anchor_reject_reason",
    "n_context_requested",
    "n_context_placed",
    "n_context_visible",
    "n_cargo_placed",
    "explicit_occluder_placed",
    "exact_collision_count",
    "pallet_obstacle_collision_count",
    "cargo_collision_count",
    "context_context_collision_count",
    "min_camera_clearance",
    "support_pass",
    "f_target",
    "f_static",
    "f_cargo",
    "f_context",
    "f_explicit",
    "f_total",
    "explicit_abs_error",
    "front_face_visibility",
    "left_opening_visibility",
    "right_opening_visibility",
    "luma_frame",
    "luma_pallet",
    "magenta_fraction",
    "corrupt_rgb",
    "corrupt_mask",
    "G1_pass",
    "G2_pass",
    "G3_pass",
    "G4_pass",
    "G5_pass",
    "all_pass",
    "reject_reason",
]

REQUIRED_SCENE_LOGIC_FIELDS = [
    "anchor_attempts",
    "anchor_reject_reason",
    "n_context_requested",
    "n_context_placed",
    "n_context_visible",
    "n_cargo_placed",
    "explicit_occluder_placed",
    "exact_collision_count",
    "pallet_obstacle_collision_count",
    "cargo_collision_count",
    "context_context_collision_count",
    "min_camera_clearance",
    "support_pass",
    "f_static",
    "f_cargo",
    "f_context",
    "f_explicit",
    "f_total",
    "explicit_abs_error",
    "front_face_visibility",
    "left_opening_visibility",
    "right_opening_visibility",
    "corrupt_rgb",
    "corrupt_label",
    "corrupt_mask",
    "corrupt_any",
    "placement_attempts",
    "context_placement_attempts",
    "cargo_placement_attempts",
    "occluder_feedback_iterations",
    "runtime_s",
]

SCENE_LOGIC_NUMERIC_FIELDS = [
    "anchor_attempts",
    "n_context_requested",
    "n_context_placed",
    "n_context_visible",
    "context_visible_pixel_ratio",
    "context_screen_area_ratio",
    "n_cargo_requested",
    "n_cargo_placed",
    "exact_collision_count",
    "pallet_obstacle_collision_count",
    "cargo_collision_count",
    "context_context_collision_count",
    "min_camera_clearance",
    "f_static",
    "f_cargo",
    "f_context",
    "f_explicit",
    "f_total",
    "explicit_abs_error",
    "front_face_visibility",
    "left_opening_visibility",
    "right_opening_visibility",
    "front_visibility_after_cargo",
    "left_opening_visibility_after_cargo",
    "right_opening_visibility_after_cargo",
    "placement_attempts",
    "context_placement_attempts",
    "cargo_placement_attempts",
    "occluder_feedback_iterations",
    "runtime_s",
]

CHART_PLAN = [
    {"number": 1, "filename": "01_baseline_2k_vs_new_500_gate_fail_rate.png", "title": "Baseline 2k vs New 500 Gate Fail Rate", "metrics": GATE_COLUMNS},
    {"number": 2, "filename": "02_all_pass_rate_by_diagnostic_mode.png", "title": "All-pass Rate by Diagnostic Mode", "metrics": ["diagnostic_mode", "all_pass"]},
    {"number": 3, "filename": "03_occlusion_source_stacked_contribution_by_mode.png", "title": "Occlusion Source Contribution by Mode", "metrics": ["diagnostic_mode", "f_static", "f_cargo", "f_context", "f_explicit"]},
    {"number": 4, "filename": "04_clean_static_f_static_histogram.png", "title": "Clean-static f_static Histogram", "metrics": ["diagnostic_mode", "f_static"]},
    {"number": 5, "filename": "05_cargo_only_f_cargo_histogram.png", "title": "Cargo-only f_cargo Histogram", "metrics": ["diagnostic_mode", "f_cargo"]},
    {"number": 6, "filename": "06_context_rich_f_context_histogram.png", "title": "Context-rich f_context Histogram", "metrics": ["diagnostic_mode", "f_context"]},
    {"number": 7, "filename": "07_controlled_occlusion_f_target_vs_f_explicit.png", "title": "Controlled-occlusion f_target vs f_explicit", "metrics": ["diagnostic_mode", "f_target", "f_explicit"]},
    {"number": 8, "filename": "08_f_target_bin_vs_f_explicit_actual_bin.png", "title": "f_target Bin vs f_explicit Actual Bin", "metrics": ["f_target_bin", "f_explicit_actual_bin"]},
    {"number": 9, "filename": "09_explicit_abs_error_histogram_quantiles.png", "title": "Explicit Absolute Error Histogram and Quantiles", "metrics": ["explicit_abs_error"]},
    {"number": 10, "filename": "10_occluder_side_target_vs_actual.png", "title": "Occluder Side Target vs Actual", "metrics": ["occluder_side_target", "occluder_side_actual"]},
    {"number": 11, "filename": "11_anchor_reject_reason_distribution.png", "title": "Anchor Reject Reason Distribution", "metrics": ["anchor_reject_reason"]},
    {"number": 12, "filename": "12_collision_reject_reason_distribution.png", "title": "Collision Reject Reason Distribution", "metrics": ["collision_reject_reason"]},
    {"number": 13, "filename": "13_context_object_count_vs_screen_area.png", "title": "Context Object Count vs Screen Area", "metrics": ["n_context_visible", "context_screen_area_ratio"]},
    {"number": 14, "filename": "14_context_screen_area_vs_f_context.png", "title": "Context Screen Area vs f_context", "metrics": ["context_screen_area_ratio", "f_context"]},
    {"number": 15, "filename": "15_g1_g3_fail_rate_by_occlusion_source.png", "title": "G1/G3 Fail Rate by Occlusion Source", "metrics": ["G1_pass", "G3_pass", "f_static", "f_cargo", "f_context", "f_explicit"]},
    {"number": 16, "filename": "16_all_pass_by_elevation_bin.png", "title": "All-pass by Elevation Bin", "metrics": ["elev_bin_target", "elev_target", "all_pass"]},
    {"number": 17, "filename": "17_all_pass_by_projected_size_bin.png", "title": "All-pass by Projected-size Bin", "metrics": ["proj_size_bin_target", "projected_size_target", "all_pass"]},
    {"number": 18, "filename": "18_all_pass_by_cargo_on.png", "title": "All-pass by Cargo On", "metrics": ["cargo_on", "all_pass"]},
    {"number": 19, "filename": "19_front_opening_visibility_distributions.png", "title": "Front and Opening Visibility Distributions", "metrics": ["front_face_visibility", "left_opening_visibility", "right_opening_visibility"]},
    {"number": 20, "filename": "20_placement_attempt_count_and_runtime_distribution.png", "title": "Placement Attempts and Runtime Distribution", "metrics": ["placement_attempts", "anchor_attempts", "context_placement_attempts", "cargo_placement_attempts", "occluder_feedback_iterations", "runtime_s"]},
    {"number": 21, "filename": "21_camera_geometry_prescription_distribution.png", "title": "Camera and Geometry Prescription Distribution", "metrics": ["elev_target", "azimuth_bin", "v_target", "projected_size_target", "exposure_ev", "resolution", "aspect", "fx"]},
    {"number": 22, "filename": "22_magenta_corrupt_empty_mask_counts.png", "title": "Magenta, Corrupt, and Empty-mask Counts", "metrics": ["magenta_fraction", "corrupt_rgb", "corrupt_mask", "empty_target_mask"]},
]


FRAME_COLUMNS = [
    "idx",
    "seed",
    "frame_id",
    "diagnostic_mode",
    "rendered",
    "realize_ok",
    "record_present",
    "record_source",
    "label_present",
    "rgb_present",
    "rgb_decode_ok",
    "rgb_decode_error",
    "corrupt_rgb",
    "corrupt_rgb_reason",
    "corrupt_label",
    "corrupt_mask",
    "corrupt_mask_reasons",
    "corrupt_any",
    "rgb_width",
    "rgb_height",
    "label_width",
    "label_height",
    "resolution_match",
    "missing_field_count",
    "missing_fields",
    "pallet_type",
    "pallet",
    "scene_preset",
    "background_asset",
    "floor_mode",
    "floor_texture",
    "material_variant_target",
    "material_variant_actual",
    "cargo_on",
    "n_cargo",
    "n_cargo_requested",
    "n_cargo_placed",
    "cargo_placement_attempts",
    "cargo_support_pass",
    "cargo_collision_pass",
    "occluder_placed",
    "occluder_asset",
    "occluder_size_class",
    "occluder_side",
    "explicit_occluder_placed",
    "explicit_occluder_visible_pixels",
    "explicit_collision_pass",
    "explicit_solver_fail_reason",
    "occluder_feedback_iterations",
    "occluder_side_target",
    "occluder_side_actual",
    "position_mode",
    "placement_mode",
    "placement_attempts",
    "anchor_attempts",
    "anchor_translation",
    "anchor_reject_reason",
    "anchor_reject_counts_by_reason",
    "support_surface_name",
    "n_context_requested",
    "n_context_placed",
    "n_context_visible",
    "context_visible_pixel_ratio",
    "context_screen_area_ratio",
    "context_placement_attempts",
    "context_reject_counts_by_reason",
    "exact_collision_count",
    "tested_collision_pairs",
    "broad_phase_hits",
    "exact_collision_hits",
    "collision_reject_reason",
    "pallet_obstacle_collision_count",
    "cargo_collision_count",
    "context_context_collision_count",
    "min_camera_clearance",
    "camera_clearance_pass",
    "support_pass",
    "static_collision_pass",
    "static_los_pass",
    "aspect",
    "resolution",
    "fx",
    "fy",
    "cx",
    "cy",
    "exposure_ev",
    "elev_target",
    "elev_actual",
    "elev_bin_target",
    "elevation_deg_target",
    "elevation_deg_actual",
    "azimuth_deg_target",
    "azimuth_bin",
    "projected_size_target",
    "projected_size_actual",
    "proj_size_bin_target",
    "proj_size_ratio_target",
    "v_target",
    "V_actual",
    "V_vis",
    "ext_occ_corners",
    "front_visibility_cos",
    "facing_margin",
    "f_target",
    "f_target_bin",
    "f_static",
    "f_cargo",
    "f_context",
    "f_explicit",
    "f_occ",
    "f_total",
    "explicit_abs_error",
    "f_explicit_target",
    "f_explicit_actual",
    "f_actual_bin",
    "f_explicit_actual_bin",
    "front_face_visibility",
    "left_opening_visibility",
    "right_opening_visibility",
    "opening_visibility_reason",
    "front_visibility_after_cargo",
    "left_opening_visibility_after_cargo",
    "right_opening_visibility_after_cargo",
    "luma_frame",
    "luma_pallet",
    "mask_area_unocc_label",
    "mask_area_target_only",
    "mask_area_after_static",
    "mask_area_after_cargo",
    "mask_area_after_cargo_label",
    "mask_area_after_context",
    "mask_area_visible",
    "mask_area_visible_label",
    "occlusion_decomposition_order",
    "runtime_s",
    "stage_runtime_s",
    "G1_pass",
    "G2_pass",
    "G3_pass",
    "G4_pass",
    "G5_pass",
    "all_pass",
    "reject_reason",
    "magenta_fraction",
    "magenta_ratio",
    "empty_target_mask",
    "source_files_missing",
    "notes",
]
for _name in MASK_NAMES:
    FRAME_COLUMNS.extend([f"mask_{_name}_present", f"mask_{_name}_area", f"mask_{_name}_decode_ok", f"mask_{_name}_decode_error"])


def frame_columns(mask_names: list[str]) -> list[str]:
    dynamic_mask_columns = {
        f"mask_{name}_{suffix}"
        for name in MASK_NAMES
        for suffix in ("present", "area", "decode_ok", "decode_error")
    }
    cols = [c for c in FRAME_COLUMNS if c not in dynamic_mask_columns]
    for name in mask_names:
        cols.extend([f"mask_{name}_present", f"mask_{name}_area", f"mask_{name}_decode_ok", f"mask_{name}_decode_error"])
    return cols


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze v2 scene-logic frame outputs.")
    p.add_argument("--dir", default=DEFAULT_DIR, help="Input dataset root.")
    p.add_argument("--out", default=None, help="Output directory. Default: <dir>/eda")
    p.add_argument("--baseline", default=DEFAULT_BASELINE, help="Baseline pilot_frames.csv path.")
    p.add_argument("--mask-names", default=",".join(MASK_NAMES), help="Comma-separated mask suffixes.")
    p.add_argument("--self-test", action="store_true", help="Run a synthetic fixture test and validate required fields/charts.")
    return p.parse_args()


def as_path(s: str | os.PathLike[str]) -> Path:
    return Path(s).expanduser().resolve()


def read_json(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_records(root: Path) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    seen = Counter()
    sources = Counter()
    errors: list[str] = []
    source_used = None
    ignored_sources: list[str] = []

    def add_record(obj: Any, source: str) -> None:
        if not isinstance(obj, dict):
            return
        idx = obj.get("idx")
        if idx is None:
            idx = obj.get("frame_index")
        try:
            idx_i = int(idx)
        except Exception:
            errors.append(f"{source}: record without integer idx")
            return
        seen[idx_i] += 1
        rec = dict(obj)
        rec["_record_source"] = source
        records[idx_i] = rec
        sources[source] += 1

    def read_records_json(path: Path) -> None:
        obj = read_json(path)
        data = obj
        if isinstance(obj, dict):
            data = obj.get("records", obj.get("frames", obj))
        if isinstance(data, list):
            for item in data:
                add_record(item, "records.json")
        elif isinstance(data, dict):
            for key, item in data.items():
                if isinstance(item, dict) and item.get("idx") is None:
                    item = dict(item)
                    item["idx"] = key
                add_record(item, "records.json")
        else:
            errors.append("records.json: unsupported JSON structure")

    jsonl = root / "records.jsonl"
    js = root / "records.json"
    if jsonl.exists():
        source_used = "records.jsonl"
        try:
            with jsonl.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        add_record(json.loads(line), f"records.jsonl:{line_no}")
                    except Exception as e:
                        errors.append(f"records.jsonl:{line_no}: {e}")
        except Exception as e:
            errors.append(f"records.jsonl: {e}")
        if js.exists():
            ignored_sources.append("records.json")
    elif js.exists():
        source_used = "records.json"
        read_records_json(js)

    return records, {
        "source_used": source_used,
        "ignored_sources": ignored_sources,
        "record_sources": dict(sources),
        "duplicate_record_indices": sorted([k for k, v in seen.items() if v > 1]),
        "errors": errors,
    }


def discover_indices(root: Path, records: dict[int, dict[str, Any]], mask_names: list[str]) -> list[int]:
    indices = set(records.keys())
    for path in (root / "rgb").glob("f*_rgb.png"):
        m = re.match(r"f(\d+)_rgb\.png$", path.name)
        if m:
            indices.add(int(m.group(1)))
    for path in (root / "labels").glob("f*_label.json"):
        m = re.match(r"f(\d+)_label\.json$", path.name)
        if m:
            indices.add(int(m.group(1)))
    mask_dir = root / "mask"
    for suffix in mask_names:
        for path in mask_dir.glob(f"f*_{suffix}.png"):
            m = re.match(r"f(\d+)_" + re.escape(suffix) + r"\.png$", path.name)
            if m:
                indices.add(int(m.group(1)))
    return sorted(indices)


def nested(obj: Any, keys: list[Any]) -> Any | None:
    cur = obj
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return None
    return cur


def first_value(*values: Any) -> Any | None:
    for v in values:
        if v is not None:
            return v
    return None


def compact_json(v: Any) -> str | Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return v


def dict_value(v: Any) -> dict[str, Any] | None:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            obj = json.loads(v)
        except Exception:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def bool_value(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
    return None


def float_value(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        if math.isfinite(f):
            return f
    except Exception:
        return None
    return None


def int_value(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except Exception:
        return None


def derive_explicit_occluder_placed(rec: dict[str, Any], v2: dict[str, Any] | None) -> bool | None:
    raw = first_value(rec.get("explicit_occluder_placed"), nested(v2, ["explicit_occluder_placed"]))
    b = bool_value(raw)
    if b is not None:
        return b
    pixels = int_value(first_value(rec.get("explicit_occluder_visible_pixels"), nested(v2, ["explicit_occluder_visible_pixels"])))
    if pixels is not None:
        return pixels > 0
    f_explicit = float_value(first_value(rec.get("f_explicit"), nested(v2, ["f_explicit"])))
    if f_explicit is not None:
        return f_explicit > 0
    return None


def f_bin(x: Any) -> int | None:
    f = float_value(x)
    if f is None:
        return None
    if f < 0.10:
        return 0
    if f < 0.20:
        return 1
    if f < 0.35:
        return 2
    return 3


def strict_rgb_stats(path: Path) -> dict[str, Any]:
    out = {
        "present": path.exists(),
        "decode_ok": False,
        "decode_error": None,
        "width": None,
        "height": None,
        "magenta_ratio": None,
    }
    if not path.exists():
        out["decode_error"] = "missing"
        return out
    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            arr = np.asarray(rgb)
            out["width"], out["height"] = rgb.size
            mag = (arr[:, :, 0] > 180) & (arr[:, :, 1] < 90) & (arr[:, :, 2] > 180)
            out["magenta_ratio"] = float(mag.mean()) if arr.size else None
            out["decode_ok"] = True
    except Exception as e:
        out["decode_error"] = str(e)
    return out


def mask_stats(path: Path) -> dict[str, Any]:
    out = {"present": path.exists(), "decode_ok": False, "decode_error": None, "area": None}
    if not path.exists():
        out["decode_error"] = "missing"
        return out
    try:
        with Image.open(path) as im:
            arr = np.asarray(im.convert("L"))
            out["area"] = int((arr > 127).sum())
            out["decode_ok"] = True
    except Exception as e:
        out["decode_error"] = str(e)
    return out


def label_parts(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    lab = read_json(path) if path.exists() else None
    if not isinstance(lab, dict):
        return None, None, None
    obj = None
    objects = lab.get("objects")
    if isinstance(objects, list) and objects:
        obj = objects[0]
    if not isinstance(obj, dict):
        obj = None
    v2 = obj.get("v2_labels") if isinstance(obj, dict) else None
    if not isinstance(v2, dict):
        v2 = None
    return lab, obj, v2


def gate_from_label_or_record(gates: Any, rec: dict[str, Any], label_key: str, csv_key: str) -> bool | None:
    if isinstance(gates, dict):
        v = gates.get(label_key)
        if v is not None:
            return bool_value(v)
    return bool_value(rec.get(csv_key))


def derive_reject_reason(row: dict[str, Any]) -> str | None:
    all_pass = bool_value(row.get("all_pass"))
    if all_pass is True:
        return "accepted"
    failed = []
    for c in GATE_COLUMNS:
        if bool_value(row.get(c)) is False:
            failed.append(c.replace("_pass", ""))
    if failed:
        return "|".join(failed)
    return row.get("reject_reason") or None


def has_key(obj: Any, key: str) -> bool:
    return isinstance(obj, dict) and key in obj


def has_nested_key(obj: Any, keys: list[Any]) -> bool:
    cur = obj
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return False
    return True


def any_key(obj: Any, keys: list[str]) -> bool:
    return isinstance(obj, dict) and any(key in obj for key in keys)


FIELD_KEY_ALIASES = {
    "seed": [("rec", ["seed", "frame_seed"]), ("v2", ["seed", "frame_seed"])],
    "diagnostic_mode": [("rec", ["diagnostic_mode", "mode", "scene_mode"]), ("v2", ["diagnostic_mode"])],
    "pallet_type": [("rec", ["pallet_type", "pallet"]), ("v2", ["pallet_type"]), ("obj", ["name"])],
    "scene_preset": [("rec", ["scene_preset"]), ("cam", ["scene_preset"]), ("v2", ["scene_preset"])],
    "background_asset": [("rec", ["background_asset"]), ("cam", ["background_asset"])],
    "floor_mode": [("rec", ["floor_mode"]), ("cam", ["floor_mode"])],
    "elev_target": [("rec", ["elev_target"]), ("v2", ["elev_target", "elevation_deg_target"])],
    "elev_actual": [("rec", ["elev_actual"]), ("v2", ["elev_actual", "elevation_deg_actual"])],
    "azimuth_bin": [("rec", ["azimuth_bin"])],
    "v_target": [("rec", ["v_target"]), ("v2", ["v_target"])],
    "V_actual": [("rec", ["V_actual"]), ("v2", ["V_actual"])],
    "V_vis": [("rec", ["V_vis"]), ("v2", ["V_vis", "V_vis_actual"])],
    "projected_size_target": [("rec", ["projected_size_target", "projected_size_ratio_target", "proj_size_ratio"]), ("v2", ["projected_size_target", "proj_size_ratio_target"])],
    "projected_size_actual": [("rec", ["projected_size_actual", "projected_size_ratio_actual", "proj_size_ratio_actual"]), ("v2", ["projected_size_actual", "proj_size_ratio_actual"])],
    "magenta_fraction": [("rec", ["magenta_fraction", "magenta_ratio"])],
    "corrupt_rgb": [("rec", ["corrupt_rgb"])],
    "corrupt_mask": [("rec", ["corrupt_mask"])],
    "reject_reason": [("rec", ["reject_reason"])],
    "all_pass": [("rec", ["all_pass"]), ("gates", ["all_pass"])],
    "G1_pass": [("rec", ["G1_pass"]), ("gates", ["G1_Vvis>=4"])],
    "G2_pass": [("rec", ["G2_pass"]), ("gates", ["G2_extocc_1to4"])],
    "G3_pass": [("rec", ["G3_pass"]), ("gates", ["G3_visible>=0.5unocc"])],
    "G4_pass": [("rec", ["G4_pass"]), ("gates", ["G4_center_inframe"])],
    "G5_pass": [("rec", ["G5_pass"]), ("gates", ["G5_luma_floor"])],
}


def field_key_present(
    field: str,
    row: dict[str, Any],
    rec: dict[str, Any],
    cam: dict[str, Any],
    obj: dict[str, Any] | None,
    v2: dict[str, Any] | None,
    gates: Any,
) -> bool:
    if row.get(field) not in (None, ""):
        return True
    sources = {
        "rec": rec,
        "cam": cam,
        "obj": obj if isinstance(obj, dict) else {},
        "v2": v2 if isinstance(v2, dict) else {},
        "gates": gates if isinstance(gates, dict) else {},
    }
    if any_key(rec, [field]) or any_key(sources["v2"], [field]) or any_key(cam, [field]):
        return True
    for source_name, keys in FIELD_KEY_ALIASES.get(field, []):
        if any_key(sources.get(source_name), keys):
            return True
    return False


def build_frame_row(root: Path, idx: int, rec: dict[str, Any] | None, mask_names: list[str]) -> dict[str, Any]:
    frame = f"f{idx:04d}"
    label_path = root / "labels" / f"{frame}_label.json"
    rgb_path = root / "rgb" / f"{frame}_rgb.png"
    label_exists = label_path.exists()
    lab, obj, v2 = label_parts(label_path)
    cam = lab.get("camera_data") if isinstance(lab, dict) and isinstance(lab.get("camera_data"), dict) else {}
    rec = rec or {}
    gates = obj.get("safety_gates") if isinstance(obj, dict) else None
    rgb = strict_rgb_stats(rgb_path)
    row = {c: None for c in FRAME_COLUMNS}
    row.update(
        {
            "idx": idx,
            "seed": first_value(rec.get("seed"), rec.get("frame_seed"), nested(v2, ["seed"]), nested(v2, ["frame_seed"])),
            "frame_id": frame,
            "diagnostic_mode": first_value(rec.get("diagnostic_mode"), rec.get("mode"), rec.get("scene_mode"), nested(v2, ["diagnostic_mode"])),
            "rendered": bool_value(rec.get("rendered")),
            "realize_ok": bool_value(rec.get("realize_ok")),
            "record_present": bool(rec),
            "record_source": rec.get("_record_source"),
            "label_present": lab is not None,
            "rgb_present": rgb["present"],
            "rgb_decode_ok": rgb["decode_ok"],
            "rgb_decode_error": rgb["decode_error"],
            "corrupt_rgb": first_value(rec.get("corrupt_rgb"), (rgb["present"] and not rgb["decode_ok"])),
            "corrupt_rgb_reason": first_value(rec.get("corrupt_rgb_reason"), rgb["decode_error"] if rgb["present"] and not rgb["decode_ok"] else None),
            "corrupt_label": label_exists and lab is None,
            "corrupt_mask": rec.get("corrupt_mask"),
            "corrupt_mask_reasons": compact_json(rec.get("corrupt_mask_reasons")),
            "rgb_width": rgb["width"],
            "rgb_height": rgb["height"],
            "label_width": cam.get("width"),
            "label_height": cam.get("height"),
            "magenta_fraction": first_value(
                rgb["magenta_ratio"] if rgb["decode_ok"] else None,
                rec.get("magenta_fraction"),
                rec.get("magenta_ratio"),
            ),
            "magenta_ratio": first_value(
                rgb["magenta_ratio"] if rgb["decode_ok"] else None,
                rec.get("magenta_ratio"),
                rec.get("magenta_fraction"),
            ),
            "reject_reason": rec.get("reject_reason"),
        }
    )
    if row["rgb_width"] is not None and row["label_width"] is not None:
        row["resolution_match"] = (int(row["rgb_width"]) == int(row["label_width"]) and int(row["rgb_height"]) == int(row["label_height"]))

    floor = cam.get("floor") if isinstance(cam.get("floor"), dict) else {}
    intr = cam.get("intrinsics") if isinstance(cam.get("intrinsics"), dict) else {}
    dims = obj.get("dimensions_m") if isinstance(obj, dict) and isinstance(obj.get("dimensions_m"), dict) else {}

    row.update(
        {
            "pallet_type": first_value(rec.get("pallet_type"), rec.get("pallet"), nested(v2, ["pallet_type"]), obj.get("name") if obj else None),
            "pallet": first_value(rec.get("pallet"), rec.get("pallet_type"), nested(v2, ["pallet_type"]), obj.get("name") if obj else None),
            "scene_preset": first_value(rec.get("scene_preset"), cam.get("scene_preset")),
            "background_asset": first_value(rec.get("background_asset"), cam.get("background_asset")),
            "floor_mode": first_value(rec.get("floor_mode"), cam.get("floor_mode")),
            "floor_texture": first_value(rec.get("floor_texture"), floor.get("floor_texture")),
            "material_variant_target": nested(v2, ["material_variant_target"]),
            "material_variant_actual": nested(v2, ["material_variant_actual"]),
            "cargo_on": first_value(rec.get("cargo_on"), nested(v2, ["cargo_on"])),
            "n_cargo": first_value(rec.get("n_cargo"), nested(v2, ["n_cargo_actual"])),
            "n_cargo_requested": first_value(rec.get("n_cargo_requested"), nested(v2, ["n_cargo_requested"])),
            "n_cargo_placed": first_value(rec.get("n_cargo_placed"), rec.get("n_cargo"), nested(v2, ["n_cargo_placed"]), nested(v2, ["n_cargo_actual"])),
            "cargo_placement_attempts": first_value(rec.get("cargo_placement_attempts"), nested(v2, ["cargo_placement_attempts"])),
            "cargo_support_pass": first_value(rec.get("cargo_support_pass"), nested(v2, ["cargo_support_pass"])),
            "cargo_collision_pass": first_value(rec.get("cargo_collision_pass"), nested(v2, ["cargo_collision_pass"])),
            "occluder_placed": first_value(rec.get("occluder_placed"), nested(v2, ["occluder_placed"])),
            "occluder_asset": first_value(rec.get("occluder_name"), nested(v2, ["occluder_asset"])),
            "occluder_size_class": rec.get("occluder_size_class"),
            "occluder_side": rec.get("occluder_side"),
            "explicit_occluder_placed": derive_explicit_occluder_placed(rec, v2),
            "explicit_occluder_visible_pixels": first_value(rec.get("explicit_occluder_visible_pixels"), nested(v2, ["explicit_occluder_visible_pixels"])),
            "explicit_collision_pass": first_value(rec.get("explicit_collision_pass"), nested(v2, ["explicit_collision_pass"])),
            "explicit_solver_fail_reason": first_value(rec.get("explicit_solver_fail_reason"), nested(v2, ["explicit_solver_fail_reason"])),
            "occluder_feedback_iterations": first_value(rec.get("occluder_feedback_iterations"), nested(v2, ["occluder_feedback_iterations"])),
            "occluder_side_target": first_value(rec.get("occluder_side_target"), nested(v2, ["occluder_side_target"])),
            "occluder_side_actual": first_value(rec.get("occluder_side_actual"), nested(v2, ["occluder_side_actual"])),
            "position_mode": first_value(rec.get("position_mode"), nested(v2, ["position_mode"])),
            "placement_mode": first_value(rec.get("placement_mode"), nested(v2, ["placement_mode"])),
            "placement_attempts": first_value(rec.get("placement_attempts"), rec.get("anchor_attempts"), nested(v2, ["placement_attempts"])),
            "anchor_attempts": first_value(rec.get("anchor_attempts"), nested(v2, ["anchor_attempts"])),
            "anchor_translation": compact_json(first_value(rec.get("anchor_translation"), nested(v2, ["anchor_translation"]))),
            "anchor_reject_reason": first_value(rec.get("anchor_reject_reason"), nested(v2, ["anchor_reject_reason"])),
            "anchor_reject_counts_by_reason": compact_json(first_value(rec.get("anchor_reject_counts_by_reason"), nested(v2, ["anchor_reject_counts_by_reason"]))),
            "support_surface_name": first_value(rec.get("support_surface_name"), nested(v2, ["support_surface_name"])),
            "n_context_requested": first_value(rec.get("n_context_requested"), nested(v2, ["n_context_requested"])),
            "n_context_placed": first_value(rec.get("n_context_placed"), nested(v2, ["n_context_placed"])),
            "n_context_visible": first_value(rec.get("n_context_visible"), nested(v2, ["n_context_visible"])),
            "context_visible_pixel_ratio": first_value(rec.get("context_visible_pixel_ratio"), nested(v2, ["context_visible_pixel_ratio"])),
            "context_screen_area_ratio": first_value(rec.get("context_screen_area_ratio"), nested(v2, ["context_screen_area_ratio"])),
            "context_placement_attempts": first_value(rec.get("context_placement_attempts"), nested(v2, ["context_placement_attempts"])),
            "context_reject_counts_by_reason": compact_json(first_value(rec.get("context_reject_counts_by_reason"), nested(v2, ["context_reject_counts_by_reason"]))),
            "exact_collision_count": first_value(rec.get("exact_collision_count"), nested(v2, ["exact_collision_count"])),
            "tested_collision_pairs": first_value(rec.get("tested_collision_pairs"), nested(v2, ["tested_collision_pairs"])),
            "broad_phase_hits": first_value(rec.get("broad_phase_hits"), nested(v2, ["broad_phase_hits"])),
            "exact_collision_hits": first_value(rec.get("exact_collision_hits"), nested(v2, ["exact_collision_hits"])),
            "collision_reject_reason": first_value(rec.get("collision_reject_reason"), nested(v2, ["collision_reject_reason"])),
            "pallet_obstacle_collision_count": first_value(rec.get("pallet_obstacle_collision_count"), nested(v2, ["pallet_obstacle_collision_count"])),
            "cargo_collision_count": first_value(rec.get("cargo_collision_count"), nested(v2, ["cargo_collision_count"])),
            "context_context_collision_count": first_value(rec.get("context_context_collision_count"), nested(v2, ["context_context_collision_count"])),
            "min_camera_clearance": first_value(rec.get("min_camera_clearance"), nested(v2, ["min_camera_clearance"])),
            "camera_clearance_pass": first_value(rec.get("camera_clearance_pass"), nested(v2, ["camera_clearance_pass"])),
            "support_pass": first_value(rec.get("support_pass"), nested(v2, ["support_pass"])),
            "static_collision_pass": first_value(rec.get("static_collision_pass"), nested(v2, ["static_collision_pass"])),
            "static_los_pass": first_value(rec.get("static_los_pass"), nested(v2, ["static_los_pass"])),
            "aspect": first_value(rec.get("aspect"), cam.get("aspect_label"), cam.get("aspect_ratio")),
            "resolution": first_value(rec.get("resolution"), cam.get("resolution")),
            "fx": first_value(rec.get("fx"), intr.get("fx")),
            "fy": intr.get("fy"),
            "cx": intr.get("cx"),
            "cy": intr.get("cy"),
            "exposure_ev": first_value(rec.get("exposure_ev"), cam.get("exposure_ev"), nested(v2, ["exposure_ev"])),
            "elev_target": first_value(rec.get("elev_target"), nested(v2, ["elev_target"]), nested(v2, ["elevation_deg_target"])),
            "elev_actual": first_value(rec.get("elev_actual"), nested(v2, ["elev_actual"]), nested(v2, ["elevation_deg_actual"])),
            "elev_bin_target": first_value(rec.get("elev_bin"), nested(v2, ["elev_bin_target"])),
            "elevation_deg_target": first_value(rec.get("elev_target"), nested(v2, ["elevation_deg_target"])),
            "elevation_deg_actual": first_value(rec.get("elev_actual"), nested(v2, ["elevation_deg_actual"])),
            "azimuth_deg_target": first_value(rec.get("azimuth_target"), nested(v2, ["azimuth_deg_target"])),
            "azimuth_bin": rec.get("azimuth_bin"),
            "projected_size_target": first_value(
                rec.get("projected_size_target"),
                rec.get("projected_size_ratio_target"),
                rec.get("proj_size_ratio"),
                nested(v2, ["projected_size_target"]),
                nested(v2, ["proj_size_ratio_target"]),
            ),
            "projected_size_actual": first_value(
                rec.get("projected_size_actual"),
                rec.get("projected_size_ratio_actual"),
                rec.get("proj_size_ratio_actual"),
                nested(v2, ["projected_size_actual"]),
                nested(v2, ["proj_size_ratio_actual"]),
            ),
            "proj_size_bin_target": first_value(rec.get("proj_size_bin"), nested(v2, ["proj_size_bin_target"])),
            "proj_size_ratio_target": first_value(rec.get("proj_size_ratio"), nested(v2, ["proj_size_ratio_target"])),
            "v_target": first_value(rec.get("v_target"), nested(v2, ["v_target"])),
            "V_actual": first_value(rec.get("V_actual"), nested(v2, ["V_actual"])),
            "V_vis": first_value(rec.get("V_vis"), nested(v2, ["V_vis_actual"])),
            "ext_occ_corners": first_value(rec.get("ext_occ"), nested(v2, ["ext_occ_corners_actual"])),
            "front_visibility_cos": first_value(rec.get("front_cos"), obj.get("front_visibility_cos") if obj else None),
            "facing_margin": first_value(rec.get("facing_margin"), obj.get("facing_margin") if obj else None),
            "f_target": first_value(rec.get("f_target"), nested(v2, ["f_target"])),
            "f_target_bin": first_value(rec.get("f_target_bin"), nested(v2, ["f_target_bin"])),
            "f_static": first_value(rec.get("f_static"), nested(v2, ["f_static"])),
            "f_cargo": first_value(rec.get("f_cargo"), rec.get("f_cargo_meas"), nested(v2, ["f_cargo"])),
            "f_context": first_value(rec.get("f_context"), nested(v2, ["f_context"])),
            "f_explicit": first_value(rec.get("f_explicit"), nested(v2, ["f_explicit"])),
            "f_occ": first_value(rec.get("f_occ_meas"), nested(v2, ["f_occ"])),
            "f_total": first_value(rec.get("f_total"), rec.get("f_total_meas"), nested(v2, ["f_total"])),
            "explicit_abs_error": first_value(rec.get("explicit_abs_error"), nested(v2, ["explicit_abs_error"])),
            "f_explicit_target": first_value(rec.get("f_explicit_target"), nested(v2, ["f_explicit_target"])),
            "f_explicit_actual": first_value(rec.get("f_explicit_actual"), nested(v2, ["f_explicit_actual"])),
            "f_explicit_actual_bin": first_value(rec.get("f_explicit_actual_bin"), nested(v2, ["f_explicit_actual_bin"])),
            "f_actual_bin": first_value(rec.get("f_actual_bin"), nested(v2, ["f_actual_bin"])),
            "front_face_visibility": first_value(rec.get("front_face_visibility"), nested(v2, ["front_face_visibility"])),
            "left_opening_visibility": first_value(rec.get("left_opening_visibility"), nested(v2, ["left_opening_visibility"])),
            "right_opening_visibility": first_value(rec.get("right_opening_visibility"), nested(v2, ["right_opening_visibility"])),
            "opening_visibility_reason": first_value(rec.get("opening_visibility_reason"), nested(v2, ["opening_visibility_reason"])),
            "front_visibility_after_cargo": first_value(rec.get("front_visibility_after_cargo"), nested(v2, ["front_visibility_after_cargo"])),
            "left_opening_visibility_after_cargo": first_value(rec.get("left_opening_visibility_after_cargo"), nested(v2, ["left_opening_visibility_after_cargo"])),
            "right_opening_visibility_after_cargo": first_value(rec.get("right_opening_visibility_after_cargo"), nested(v2, ["right_opening_visibility_after_cargo"])),
            "luma_frame": first_value(rec.get("luma_frame"), nested(v2, ["luma_actual"])),
            "luma_pallet": first_value(rec.get("luma_pallet"), nested(v2, ["luma_pallet_actual"])),
            "mask_area_unocc_label": first_value(rec.get("mask_area_unocc"), nested(v2, ["mask_area_unocc"])),
            "mask_area_target_only": first_value(rec.get("mask_area_target_only"), rec.get("mask_area_unocc"), nested(v2, ["mask_area_target_only"]), nested(v2, ["mask_area_unocc"])),
            "mask_area_after_static": first_value(rec.get("mask_area_after_static"), nested(v2, ["mask_area_after_static"])),
            "mask_area_after_cargo": first_value(rec.get("mask_area_after_cargo"), nested(v2, ["mask_area_after_cargo"])),
            "mask_area_after_cargo_label": nested(v2, ["mask_area_after_cargo"]),
            "mask_area_after_context": first_value(rec.get("mask_area_after_context"), nested(v2, ["mask_area_after_context"])),
            "mask_area_visible": first_value(rec.get("mask_area_visible"), nested(v2, ["mask_area_visible"])),
            "mask_area_visible_label": first_value(rec.get("mask_area_visible"), nested(v2, ["mask_area_visible"])),
            "occlusion_decomposition_order": first_value(
                rec.get("occlusion_decomposition_order"),
                nested(v2, ["occlusion_decomposition_order"]),
                "M0_target_only>M1_static>M2_cargo>M3_context>M4_full",
            ),
            "runtime_s": first_value(rec.get("runtime_s"), nested(v2, ["runtime_s"])),
            "stage_runtime_s": compact_json(first_value(rec.get("stage_runtime_s"), nested(v2, ["stage_runtime_s"]))),
        }
    )
    if row["resolution"] is None and row["rgb_width"] is not None:
        row["resolution"] = f"{row['rgb_width']}x{row['rgb_height']}"
    if row["fy"] is None and row["fx"] is not None:
        row["fy"] = row["fx"]
    if row.get("elevation_deg_target") is None:
        row["elevation_deg_target"] = row.get("elev_target")
    if row.get("elevation_deg_actual") is None:
        row["elevation_deg_actual"] = row.get("elev_actual")
    if row.get("proj_size_ratio_target") is None:
        row["proj_size_ratio_target"] = row.get("projected_size_target")
    if row.get("f_explicit_actual") is None:
        row["f_explicit_actual"] = row.get("f_explicit")
    if row.get("explicit_abs_error") is None and float_value(row.get("f_explicit_actual")) is not None and float_value(row.get("f_explicit_target")) is not None:
        row["explicit_abs_error"] = abs(float_value(row.get("f_explicit_actual")) - float_value(row.get("f_explicit_target")))
    if row.get("f_target_bin") is None:
        fb = f_bin(row.get("f_target"))
        row["f_target_bin"] = fb if fb is None else str(fb)
    if row.get("f_actual_bin") is None:
        fb = f_bin(row.get("f_total"))
        row["f_actual_bin"] = fb if fb is None else str(fb)
    explicit_bin = f_bin(row.get("f_explicit_actual"))
    row["f_explicit_actual_bin"] = (
        explicit_bin if explicit_bin is None else str(explicit_bin)
    )

    for label_key, csv_key in GATE_LABEL_KEYS:
        row[csv_key] = gate_from_label_or_record(gates, rec, label_key, csv_key)
    if isinstance(gates, dict):
        row["all_pass"] = bool_value(gates.get("all_pass"))
    else:
        row["all_pass"] = bool_value(rec.get("all_pass"))
    row["reject_reason"] = derive_reject_reason(row)

    missing_sources = []
    if not rec:
        missing_sources.append("record")
    if lab is None:
        missing_sources.append("label")
    if not rgb["present"]:
        missing_sources.append("rgb")
    elif not rgb["decode_ok"]:
        missing_sources.append("rgb_decode")
    for name in mask_names:
        ms = mask_stats(root / "mask" / f"{frame}_{name}.png")
        row[f"mask_{name}_present"] = ms["present"]
        row[f"mask_{name}_area"] = ms["area"]
        row[f"mask_{name}_decode_ok"] = ms["decode_ok"]
        row[f"mask_{name}_decode_error"] = ms["decode_error"]
        if not ms["present"]:
            missing_sources.append(f"mask_{name}")
        elif not ms["decode_ok"]:
            missing_sources.append(f"mask_{name}_decode")
    if row.get("mask_area_target_only") is None:
        row["mask_area_target_only"] = row.get(f"mask_{mask_names[0]}_area") if mask_names else None
    if row.get("mask_area_after_static") is None and len(mask_names) > 1:
        row["mask_area_after_static"] = row.get(f"mask_{mask_names[1]}_area")
    if row.get("mask_area_after_cargo") is None and len(mask_names) > 2:
        row["mask_area_after_cargo"] = row.get(f"mask_{mask_names[2]}_area")
    if row.get("mask_area_after_context") is None and len(mask_names) > 3:
        row["mask_area_after_context"] = row.get(f"mask_{mask_names[3]}_area")
    if row.get("mask_area_visible") is None and len(mask_names) > 4:
        row["mask_area_visible"] = row.get(f"mask_{mask_names[4]}_area")
    target_area = int_value(row.get(f"mask_{mask_names[0]}_area")) if mask_names else None
    row["empty_target_mask"] = (target_area == 0) if target_area is not None else None
    row["source_files_missing"] = ";".join(missing_sources)
    if row.get("corrupt_mask") is None:
        row["corrupt_mask"] = any(row.get(f"mask_{name}_present") and not row.get(f"mask_{name}_decode_ok") for name in mask_names)
    row["corrupt_any"] = any(bool_value(row.get(k)) is True for k in ("corrupt_rgb", "corrupt_label", "corrupt_mask"))

    required = [
        "pallet_type",
        "scene_preset",
        "cargo_on",
        "aspect",
        "resolution",
        "fx",
        "elev_target",
        "v_target",
        "f_target",
        "f_total",
        "V_actual",
        "V_vis",
        "all_pass",
        "magenta_fraction",
    ] + REQUIRED_FRAME_METRIC_FIELDS + REQUIRED_SCENE_LOGIC_FIELDS
    render_failed = (
        bool_value(row.get("rendered")) is False
        or bool_value(row.get("realize_ok")) is False
    )
    missing = (
        []
        if render_failed
        else [
            k
            for k in dict.fromkeys(required)
            if not field_key_present(k, row, rec, cam, obj, v2, gates)
        ]
    )
    row["missing_field_count"] = len(missing)
    row["missing_fields"] = ";".join(missing)
    if dims:
        row["notes"] = f"dim_w={dims.get('width')};dim_d={dims.get('depth')};dim_h={dims.get('height')}"
    return row


def csv_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        return f"{v:.8g}"
    return str(v)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for row in rows:
            w.writerow({c: csv_value(row.get(c)) for c in columns})


def counter_from(rows: list[dict[str, Any]], key: str, include_missing: bool = False) -> Counter:
    c = Counter()
    for r in rows:
        v = r.get(key)
        if v is None or v == "":
            if include_missing:
                c["(missing)"] += 1
            continue
        c[str(v)] += 1
    return c


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    vals = []
    for r in rows:
        f = float_value(r.get(key))
        if f is not None:
            vals.append(f)
    return vals


def summarize_numeric(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {
            "n": 0,
            "mean": None,
            "min": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "max": None,
        }
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "n": int(arr.size),
        "mean": float(np.mean(arr)),
        "min": float(np.min(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
    }


def row_is_rendered(row: dict[str, Any]) -> bool:
    rendered = bool_value(row.get("rendered"))
    if rendered is not None:
        return rendered
    realize_ok = bool_value(row.get("realize_ok"))
    if realize_ok is not None:
        return realize_ok
    return bool_value(row.get("all_pass")) is not None


def row_has_visible_explicit_occluder(row: dict[str, Any]) -> bool:
    visible_pixels = int_value(row.get("explicit_occluder_visible_pixels"))
    if visible_pixels is not None:
        return visible_pixels > 0
    f_explicit = float_value(first_value(row.get("f_explicit_actual"), row.get("f_explicit")))
    return f_explicit is not None and f_explicit > 0.0


def summarize_new(rows: list[dict[str, Any]], root: Path, record_meta: dict[str, Any]) -> dict[str, Any]:
    n = len(rows)
    rendered_rows = [r for r in rows if row_is_rendered(r)]
    rendered_count = len(rendered_rows)
    realize_fail_count = sum(1 for r in rows if bool_value(r.get("realize_ok")) is False)
    all_pass = sum(1 for r in rendered_rows if bool_value(r.get("all_pass")) is True)
    gate_fail = {
        g: sum(1 for r in rendered_rows if bool_value(r.get(g)) is False)
        for g in GATE_COLUMNS
    }
    decode_fail = [r["idx"] for r in rows if r.get("rgb_present") and not r.get("rgb_decode_ok")]
    missing_field_counter = Counter()
    required_scene_missing_counter = Counter()
    for r in rows:
        for f in str(r.get("missing_fields") or "").split(";"):
            if f:
                missing_field_counter[f] += 1
                if f in REQUIRED_SCENE_LOGIC_FIELDS:
                    required_scene_missing_counter[f] += 1
    corrupt_counts = {
        "corrupt_rgb": sum(1 for r in rows if bool_value(r.get("corrupt_rgb")) is True),
        "corrupt_label": sum(1 for r in rows if bool_value(r.get("corrupt_label")) is True),
        "corrupt_mask": sum(1 for r in rows if bool_value(r.get("corrupt_mask")) is True),
        "corrupt_any": sum(1 for r in rows if bool_value(r.get("corrupt_any")) is True),
    }
    scene_numeric = {key: summarize_numeric(numeric_values(rows, key)) for key in SCENE_LOGIC_NUMERIC_FIELDS}
    f_numeric = {
        key: summarize_numeric(numeric_values(rows, key))
        for key in ("f_target", "f_static", "f_cargo", "f_context", "f_explicit", "f_total")
    }
    attempt_runtime = {
        key: summarize_numeric(numeric_values(rows, key))
        for key in (
            "placement_attempts",
            "anchor_attempts",
            "context_placement_attempts",
            "cargo_placement_attempts",
            "occluder_feedback_iterations",
            "runtime_s",
        )
    }

    clean_rows = rows_for_mode(rows, "clean-static")
    clean_rendered_rows = [r for r in clean_rows if row_is_rendered(r)]
    clean_static_numeric = summarize_numeric(numeric_values(clean_rendered_rows, "f_static"))
    clean_static_ge_035 = sum(
        1
        for r in clean_rendered_rows
        if (value := float_value(r.get("f_static"))) is not None and value >= 0.35
    )
    clean_static = {
        "frame_count": len(clean_rows),
        "rendered_count": len(clean_rendered_rows),
        "f_static": clean_static_numeric,
        "f_static_q95": clean_static_numeric["p95"],
        "f_static_ge_0_35_count": clean_static_ge_035,
        "f_static_ge_0_35_rate": (
            clean_static_ge_035 / len(clean_rendered_rows)
            if clean_rendered_rows
            else None
        ),
    }

    controlled_rows = rows_for_mode(rows, "controlled-occlusion")
    controlled_rendered_rows = [r for r in controlled_rows if row_is_rendered(r)]
    controlled_error = summarize_numeric(
        numeric_values(controlled_rendered_rows, "explicit_abs_error")
    )
    controlled_visible = sum(
        1 for r in controlled_rows if row_has_visible_explicit_occluder(r)
    )
    controlled_rendered_visible = sum(
        1 for r in controlled_rendered_rows if row_has_visible_explicit_occluder(r)
    )
    actual_sides = [
        str(r.get("occluder_side_actual")).strip().lower()
        for r in controlled_rendered_rows
        if r.get("occluder_side_actual") not in (None, "")
    ]
    actual_side_count = Counter(actual_sides)
    required_actual_sides = ("left", "right", "bottom", "center")
    covered_actual_sides = [
        side for side in required_actual_sides if actual_side_count.get(side, 0) > 0
    ]
    actual_side_observation_count = len(actual_sides)
    center_count = actual_side_count.get("center", 0)
    controlled_occlusion = {
        "frame_count": len(controlled_rows),
        "rendered_count": len(controlled_rendered_rows),
        "explicit_abs_error": controlled_error,
        "explicit_abs_error_q50": controlled_error["p50"],
        "explicit_abs_error_q90": controlled_error["p90"],
        "explicit_abs_error_q95": controlled_error["p95"],
        "explicit_visible_count": controlled_visible,
        "explicit_visible_ratio": (
            controlled_visible / len(controlled_rows) if controlled_rows else None
        ),
        "explicit_visible_count_rendered": controlled_rendered_visible,
        "explicit_visible_ratio_rendered": (
            controlled_rendered_visible / len(controlled_rendered_rows)
            if controlled_rendered_rows
            else None
        ),
        "actual_side_count": dict(sorted(actual_side_count.items())),
        "actual_side_observation_count": actual_side_observation_count,
        "required_actual_sides": list(required_actual_sides),
        "covered_actual_sides": covered_actual_sides,
        "missing_actual_sides": [
            side for side in required_actual_sides if side not in covered_actual_sides
        ],
        "actual_side_coverage_count": len(covered_actual_sides),
        "actual_side_coverage_ratio": len(covered_actual_sides) / len(required_actual_sides),
        "all_four_actual_sides_present": len(covered_actual_sides) == len(required_actual_sides),
        "actual_center_count": center_count,
        "actual_center_share": (
            center_count / actual_side_observation_count
            if actual_side_observation_count
            else None
        ),
        "actual_center_frame_share": (
            center_count / len(controlled_rendered_rows)
            if controlled_rendered_rows
            else None
        ),
    }

    by_mode: dict[str, dict[str, Any]] = {}
    for mode in sorted(set(str(r.get("diagnostic_mode") or "(missing)") for r in rows)):
        mode_rows = [r for r in rows if str(r.get("diagnostic_mode") or "(missing)") == mode]
        total = len(mode_rows)
        mode_rendered = [r for r in mode_rows if row_is_rendered(r)]
        mode_pass = sum(1 for r in mode_rendered if bool_value(r.get("all_pass")) is True)
        by_mode[mode] = {
            "frame_count": total,
            "rendered_count": len(mode_rendered),
            "realize_fail_count": sum(
                1 for r in mode_rows if bool_value(r.get("realize_ok")) is False
            ),
            "all_pass_count": mode_pass,
            "all_pass_rate": (
                mode_pass / len(mode_rendered) if mode_rendered else None
            ),
            "gate_fail_rate": {
                g: (
                    sum(
                        1
                        for r in mode_rendered
                        if bool_value(r.get(g)) is False
                    )
                    / len(mode_rendered)
                    if mode_rendered
                    else None
                )
                for g in GATE_COLUMNS
            },
        }
    overall = {
        "frame_count": n,
        "rendered_count": rendered_count,
        "rendered_rate": rendered_count / n if n else None,
        "realize_fail_count": realize_fail_count,
        "realize_fail_rate": realize_fail_count / n if n else None,
        "all_pass_count": all_pass,
        "all_pass_rate": all_pass / rendered_count if rendered_count else None,
        "G1_fail_count": gate_fail["G1_pass"],
        "G1_fail_rate": (
            gate_fail["G1_pass"] / rendered_count if rendered_count else None
        ),
        "G3_fail_count": gate_fail["G3_pass"],
        "G3_fail_rate": (
            gate_fail["G3_pass"] / rendered_count if rendered_count else None
        ),
    }
    return {
        "root": str(root),
        "frame_count": n,
        "record_count": sum(1 for r in rows if r.get("record_present")),
        "label_count": sum(1 for r in rows if r.get("label_present")),
        "rgb_present_count": sum(1 for r in rows if r.get("rgb_present")),
        "rgb_decode_ok_count": sum(1 for r in rows if r.get("rgb_decode_ok")),
        "rgb_decode_fail_indices": decode_fail,
        "rendered_count": rendered_count,
        "realize_fail_count": realize_fail_count,
        "all_pass_count": all_pass,
        "all_pass_rate": (all_pass / rendered_count if rendered_count else None),
        "gate_fail_count": gate_fail,
        "gate_fail_rate": {
            g: (gate_fail[g] / rendered_count if rendered_count else None)
            for g in GATE_COLUMNS
        },
        "overall": overall,
        "clean_static": clean_static,
        "controlled_occlusion": controlled_occlusion,
        "attempt_runtime": attempt_runtime,
        "reject_reason_count": dict(counter_from(rows, "reject_reason", include_missing=True)),
        "diagnostic_mode_count": dict(counter_from(rows, "diagnostic_mode", include_missing=True)),
        "scene_preset_count": dict(counter_from(rows, "scene_preset", include_missing=True)),
        "pallet_count": dict(counter_from(rows, "pallet", include_missing=True)),
        "resolution_count": dict(counter_from(rows, "resolution", include_missing=True)),
        "aspect_count": dict(counter_from(rows, "aspect", include_missing=True)),
        "occluder_side_count": dict(counter_from(rows, "occluder_side", include_missing=True)),
        "occluder_size_class_count": dict(counter_from(rows, "occluder_size_class", include_missing=True)),
        "missing_field_count_by_name": dict(missing_field_counter.most_common()),
        "required_scene_logic_fields": REQUIRED_SCENE_LOGIC_FIELDS,
        "required_scene_logic_missing_count_by_name": dict(required_scene_missing_counter.most_common()),
        "scene_logic": {
            "anchor_reject_reason_count": dict(counter_from(rows, "anchor_reject_reason", include_missing=True)),
            "collision_reject_reason_count": dict(counter_from(rows, "collision_reject_reason", include_missing=True)),
            "support_pass_count": dict(counter_from(rows, "support_pass", include_missing=True)),
            "explicit_occluder_placed_count": dict(counter_from(rows, "explicit_occluder_placed", include_missing=True)),
            "placement_mode_count": dict(counter_from(rows, "placement_mode", include_missing=True)),
            "corrupt_counts": corrupt_counts,
            "numeric": scene_numeric,
        },
        "by_diagnostic_mode": by_mode,
        "numeric": {
            **f_numeric,
            "luma_frame": summarize_numeric(numeric_values(rows, "luma_frame")),
            "luma_pallet": summarize_numeric(numeric_values(rows, "luma_pallet")),
            "magenta_ratio": summarize_numeric(numeric_values(rows, "magenta_ratio")),
        },
        "prescription_distribution": {
            "aspect_count": dict(counter_from(rows, "aspect", include_missing=True)),
            "resolution_count": dict(counter_from(rows, "resolution", include_missing=True)),
            "elev_target": summarize_numeric(numeric_values(rows, "elev_target")),
            "azimuth_bin_count": dict(
                counter_from(rows, "azimuth_bin", include_missing=True)
            ),
            "v_target_count": dict(
                counter_from(rows, "v_target", include_missing=True)
            ),
            "projected_size_target": summarize_numeric(
                numeric_values(rows, "projected_size_target")
            ),
            "exposure_ev": summarize_numeric(numeric_values(rows, "exposure_ev")),
            "fx": summarize_numeric(numeric_values(rows, "fx")),
        },
        "record_meta": record_meta,
    }


def load_baseline(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        return [], {"path": str(path), "error": "baseline CSV missing"}
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows.append(dict(r))
    except Exception as e:
        return [], {"path": str(path), "error": str(e)}
    return rows, {"path": str(path), "error": None}


def summarize_baseline(rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    rendered = [r for r in rows if r.get("stage") == "rendered"]
    all_pass = sum(1 for r in rendered if bool_value(r.get("all_pass")) is True)
    gate_fail = {g: sum(1 for r in rendered if bool_value(r.get(g)) is False) for g in GATE_COLUMNS}
    reject_reason_count = Counter(r.get("reject_reason") or "(missing)" for r in rows)
    f_target_bins = Counter(str(f_bin(r.get("f_target"))) for r in rendered if f_bin(r.get("f_target")) is not None)
    f_actual_bins = Counter(str(f_bin(r.get("f_actual"))) for r in rendered if f_bin(r.get("f_actual")) is not None)
    return {
        "meta": meta,
        "row_count": len(rows),
        "stage_count": dict(Counter(r.get("stage") or "(missing)" for r in rows)),
        "rendered_count": len(rendered),
        "all_pass_count": all_pass,
        "all_pass_rate": (all_pass / len(rendered) if rendered else None),
        "gate_fail_count": gate_fail,
        "gate_fail_rate": {g: (gate_fail[g] / len(rendered) if rendered else None) for g in GATE_COLUMNS},
        "reject_reason_count": dict(reject_reason_count),
        "f_target_bin_count": dict(f_target_bins),
        "f_actual_bin_count": dict(f_actual_bins),
        "V_actual_count": dict(Counter(r.get("V_actual") or "(missing)" for r in rendered)),
        "V_vis_count": dict(Counter(r.get("V_vis") or "(missing)" for r in rendered)),
        "scene_preset_count": dict(Counter(r.get("scene_preset") or "(missing)" for r in rendered)),
        "resolution_count": dict(Counter(r.get("resolution") or "(missing)" for r in rendered)),
        "elev_target": summarize_numeric([v for r in rendered if (v := float_value(r.get("elev_target"))) is not None]),
        "projected_size_target": summarize_numeric([v for r in rendered if (v := float_value(first_value(r.get("projected_size_target"), r.get("proj_size_ratio")))) is not None]),
        "azimuth_bin_count": dict(Counter(r.get("azimuth_bin") or "(missing)" for r in rendered)),
        "v_target_count": dict(Counter(r.get("v_target") or "(missing)" for r in rendered)),
    }


def ensure_chart_dir(out: Path) -> Path:
    charts = out / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    return charts


def no_data_plot(path: Path, title: str, message: str = "No data available") -> None:
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.axis("off")
    ax.set_title(title, fontsize=14)
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def bar_plot(counter: Counter | dict[str, Any], path: Path, title: str, xlabel: str = "", ylabel: str = "Count", top: int | None = None) -> None:
    items = list(counter.items())
    items = [(str(k), int(v)) for k, v in items if v is not None]
    items.sort(key=lambda kv: kv[1], reverse=True)
    if top:
        items = items[:top]
    if not items:
        no_data_plot(path, title)
        return
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(12, 8))
    x = np.arange(len(labels))
    ax.bar(x, vals, color="#4C72B0")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    for i, v in enumerate(vals):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def hist_plot(vals: list[float], path: Path, title: str, xlabel: str, bins: int = 30) -> None:
    if not vals:
        no_data_plot(path, title)
        return
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.hist(vals, bins=bins, color="#55A868", edgecolor="white")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.axvline(float(np.mean(vals)), color="#C44E52", linestyle="--", label=f"mean={np.mean(vals):.3g}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def multi_hist_plot(series: dict[str, list[float]], path: Path, title: str, xlabel: str, bins: int = 30) -> None:
    series = {k: v for k, v in series.items() if v}
    if not series:
        no_data_plot(path, title)
        return
    fig, ax = plt.subplots(figsize=(10, 7))
    for name, vals in series.items():
        ax.hist(vals, bins=bins, alpha=0.45, label=f"{name} n={len(vals)}")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def quantile_hist_plot(vals: list[float], path: Path, title: str, xlabel: str, bins: int = 30) -> None:
    if not vals:
        no_data_plot(path, title)
        return
    arr = np.asarray(vals, dtype=np.float64)
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.hist(arr, bins=bins, color="#55A868", edgecolor="white")
    for q, color in ((50, "#C44E52"), (90, "#4C72B0"), (95, "#8172B3")):
        val = float(np.percentile(arr, q))
        ax.axvline(val, color=color, linestyle="--", label=f"q{q}={val:.3g}")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def grouped_bar(series: dict[str, dict[str, int]], path: Path, title: str, ylabel: str = "Count") -> None:
    labels = sorted(set().union(*[set(v.keys()) for v in series.values()])) if series else []
    if not labels:
        no_data_plot(path, title)
        return
    names = list(series.keys())
    x = np.arange(len(labels))
    width = 0.8 / max(1, len(names))
    fig, ax = plt.subplots(figsize=(12, 8))
    for i, name in enumerate(names):
        vals = [series[name].get(l, 0) for l in labels]
        ax.bar(x - 0.4 + width / 2 + i * width, vals, width, label=name)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def grouped_value_bar(series: dict[str, dict[str, float | None]], path: Path, title: str, ylabel: str = "Rate") -> None:
    labels = sorted(set().union(*[set(v.keys()) for v in series.values()])) if series else []
    if not labels:
        no_data_plot(path, title)
        return
    names = list(series.keys())
    x = np.arange(len(labels))
    width = 0.8 / max(1, len(names))
    fig, ax = plt.subplots(figsize=(12, 8))
    for i, name in enumerate(names):
        vals = [float(series[name].get(label) or 0.0) for label in labels]
        ax.bar(x - 0.4 + width / 2 + i * width, vals, width, label=name)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, max(1.0, ax.get_ylim()[1]))
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def stacked_value_bar(series: dict[str, dict[str, float | None]], path: Path, title: str, ylabel: str = "Mean fraction") -> None:
    if not series:
        no_data_plot(path, title)
        return
    labels = list(series.keys())
    keys = ["f_static", "f_cargo", "f_context", "f_explicit"]
    x = np.arange(len(labels))
    bottom = np.zeros(len(labels), dtype=np.float64)
    fig, ax = plt.subplots(figsize=(12, 8))
    for key in keys:
        vals = np.asarray([float(series[label].get(key) or 0.0) for label in labels], dtype=np.float64)
        ax.bar(x, vals, bottom=bottom, label=key)
        bottom += vals
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def value_bar_plot(values: dict[str, float | int | None], path: Path, title: str, ylabel: str = "Value") -> None:
    items = [(str(k), float(v)) for k, v in values.items() if float_value(v) is not None]
    if not items:
        no_data_plot(path, title)
        return
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(12, 8))
    x = np.arange(len(labels))
    ax.bar(x, vals, color="#8172B3")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    for i, v in enumerate(vals):
        ax.text(i, v, f"{v:.3g}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def mean_values(rows: list[dict[str, Any]], keys: list[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in keys:
        vals = numeric_values(rows, key)
        out[key] = float(np.mean(vals)) if vals else None
    return out


def sum_values(rows: list[dict[str, Any]], keys: list[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in keys:
        vals = numeric_values(rows, key)
        out[key] = float(np.sum(vals)) if vals else None
    return out


def bool_true_counts(rows: list[dict[str, Any]], keys: list[str]) -> Counter:
    return Counter({key: sum(1 for r in rows if bool_value(r.get(key)) is True) for key in keys})


def stage_runtime_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for r in rows:
        obj = dict_value(r.get("stage_runtime_s"))
        if not obj:
            continue
        for key, value in obj.items():
            f = float_value(value)
            if f is not None:
                totals[str(key)] += f
    return dict(sorted(totals.items()))


def rows_for_mode(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("diagnostic_mode") or "") == mode]


def all_pass_rate_by(rows: list[dict[str, Any]], group_key: str) -> dict[str, float | None]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(group_key) or "(missing)")].append(r)
    out: dict[str, float | None] = {}
    for key, group_rows in sorted(groups.items()):
        total = len(group_rows)
        out[key] = sum(1 for r in group_rows if bool_value(r.get("all_pass")) is True) / total if total else None
    return out


def all_pass_rate_by_derived(rows: list[dict[str, Any]], group_fn: Callable[[dict[str, Any]], str]) -> dict[str, float | None]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[group_fn(r)].append(r)
    out: dict[str, float | None] = {}
    for key, group_rows in sorted(groups.items()):
        total = len(group_rows)
        out[key] = sum(1 for r in group_rows if bool_value(r.get("all_pass")) is True) / total if total else None
    return out


def numeric_bin(value: Any, bins: list[float], prefix: str) -> str:
    f = float_value(value)
    if f is None:
        return "(missing)"
    low = "-inf"
    for upper in bins:
        if f < upper:
            return f"{prefix} [{low},{upper:g})"
        low = f"{upper:g}"
    return f"{prefix} [{low},inf)"


def scatter_plot(rows: list[dict[str, Any]], x_key: str, y_key: str, path: Path, title: str, xlabel: str, ylabel: str, color_key: str | None = None) -> None:
    points = []
    colors = []
    for r in rows:
        x = float_value(r.get(x_key))
        y = float_value(r.get(y_key))
        if x is None or y is None:
            continue
        points.append((x, y))
        colors.append(str(r.get(color_key) or "(missing)") if color_key else "")
    if not points:
        no_data_plot(path, title)
        return
    fig, ax = plt.subplots(figsize=(10, 7))
    if color_key:
        for name in sorted(set(colors)):
            xs = [p[0] for p, c in zip(points, colors) if c == name]
            ys = [p[1] for p, c in zip(points, colors) if c == name]
            ax.scatter(xs, ys, alpha=0.65, label=name)
        ax.legend()
    else:
        ax.scatter([p[0] for p in points], [p[1] for p in points], alpha=0.65, color="#4C72B0")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def cross_tab_plot(rows: list[dict[str, Any]], row_key: str, col_key: str, path: Path, title: str) -> None:
    table: defaultdict[str, Counter] = defaultdict(Counter)
    for r in rows:
        table[str(r.get(row_key) or "(missing)")][str(r.get(col_key) or "(missing)")] += 1
    if not table:
        no_data_plot(path, title)
        return
    row_labels = sorted(table.keys())
    col_labels = sorted(set().union(*[set(c.keys()) for c in table.values()]))
    data = np.asarray([[table[row].get(col, 0) for col in col_labels] for row in row_labels], dtype=np.float64)
    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(data, cmap="viridis")
    ax.set_title(title)
    ax.set_xlabel(col_key)
    ax.set_ylabel(row_key)
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=35, ha="right")
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, str(int(data[i, j])), ha="center", va="center", color="white" if data[i, j] > data.max() / 2 else "black", fontsize=8)
    fig.colorbar(im, ax=ax, label="Count")
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def occlusion_component_means_by_mode(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    modes = sorted(set(str(r.get("diagnostic_mode") or "(missing)") for r in rows))
    for mode in modes:
        mode_rows = [r for r in rows if str(r.get("diagnostic_mode") or "(missing)") == mode]
        out[mode] = mean_values(mode_rows, ["f_static", "f_cargo", "f_context", "f_explicit"])
    return out


def dominant_occlusion_source(row: dict[str, Any]) -> str:
    vals = {k: float_value(row.get(k)) for k in ["f_static", "f_cargo", "f_context", "f_explicit"]}
    vals = {k: v for k, v in vals.items() if v is not None}
    if not vals:
        return "(missing)"
    key, val = max(vals.items(), key=lambda kv: kv[1])
    return key if val > 0 else "none"


def gate_fail_rate_by_source(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[dominant_occlusion_source(r)].append(r)
    out = {"G1_fail": {}, "G3_fail": {}}
    for source, group_rows in sorted(grouped.items()):
        total = len(group_rows)
        out["G1_fail"][source] = sum(1 for r in group_rows if bool_value(r.get("G1_pass")) is False) / total if total else None
        out["G3_fail"][source] = sum(1 for r in group_rows if bool_value(r.get("G3_pass")) is False) / total if total else None
    return out


def magenta_corrupt_empty_counts(rows: list[dict[str, Any]]) -> Counter:
    return Counter(
        {
            "magenta_fraction_gt_0": sum(1 for r in rows if (float_value(r.get("magenta_fraction")) or 0.0) > 0.0),
            "corrupt_rgb": sum(1 for r in rows if bool_value(r.get("corrupt_rgb")) is True),
            "corrupt_mask": sum(1 for r in rows if bool_value(r.get("corrupt_mask")) is True),
            "empty_target_mask": sum(1 for r in rows if bool_value(r.get("empty_target_mask")) is True),
        }
    )


def camera_geometry_distribution_plot(rows: list[dict[str, Any]], path: Path, title: str) -> None:
    if not rows:
        no_data_plot(path, title)
        return
    fig, axes = plt.subplots(2, 4, figsize=(19, 9))
    panels = [
        ("elev_target", "Elevation target"),
        ("azimuth_bin", "Azimuth bin"),
        ("v_target", "V target"),
        ("projected_size_target", "Projected size target"),
        ("exposure_ev", "Exposure EV"),
        ("fx", "fx"),
        ("aspect", "Aspect"),
        ("resolution", "Resolution"),
    ]
    for ax, (key, label) in zip(axes.ravel(), panels):
        vals = numeric_values(rows, key)
        if vals:
            ax.hist(vals, bins=20, color="#4C72B0", edgecolor="white")
            ax.set_xlabel(label)
            ax.set_ylabel("Count")
        else:
            counts = counter_from(rows, key, include_missing=True)
            if counts:
                labels = list(counts.keys())[:12]
                ax.bar(np.arange(len(labels)), [counts[l] for l in labels], color="#4C72B0")
                ax.set_xticks(np.arange(len(labels)))
                ax.set_xticklabels(labels, rotation=35, ha="right")
            ax.set_xlabel(label)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def chart_mapping() -> list[dict[str, Any]]:
    return [dict(spec) for spec in CHART_PLAN]


def validate_chart_plan(columns: list[str]) -> list[str]:
    errors = []
    numbers = [int(spec["number"]) for spec in CHART_PLAN]
    filenames = [str(spec["filename"]) for spec in CHART_PLAN]
    if sorted(numbers) != list(range(1, 23)):
        errors.append("chart numbers must be exactly 1..22")
    if len(set(numbers)) != len(numbers):
        errors.append("chart numbers must be unique")
    if len(set(filenames)) != len(filenames):
        errors.append("chart filenames must be unique")
    column_set = set(columns)
    for spec in CHART_PLAN:
        for metric in spec["metrics"]:
            if metric not in column_set:
                errors.append(f"chart {spec['number']:02d} references missing column: {metric}")
    for field in REQUIRED_FRAME_METRIC_FIELDS:
        if field not in column_set:
            errors.append(f"required frame metric field missing from frame columns: {field}")
    for field in REQUIRED_SCENE_LOGIC_FIELDS:
        if field not in column_set:
            errors.append(f"required scene-logic field missing from frame columns: {field}")
    return errors


def validate_generated_charts(chart_files: list[str]) -> list[str]:
    errors = []
    expected = [str(spec["filename"]) for spec in CHART_PLAN]
    actual = [Path(p).name for p in chart_files]
    if actual != expected:
        errors.append(f"generated chart order/name mismatch: expected={expected} actual={actual}")
    for path in chart_files:
        if not Path(path).exists():
            errors.append(f"generated chart missing on disk: {path}")
    return errors


def save_charts(out: Path, rows: list[dict[str, Any]], baseline: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    charts = ensure_chart_dir(out)
    chart_files: list[str] = []

    specs = {int(spec["number"]): spec for spec in CHART_PLAN}

    def add(number: int, fn: Callable[[Path], None]) -> None:
        spec = specs[number]
        path = charts / str(spec["filename"])
        fn(path)
        chart_files.append(str(path))

    add(
        1,
        lambda p: grouped_value_bar(
            {
                "baseline_2k": baseline.get("gate_fail_rate", {}),
                "new_500": summary.get("gate_fail_rate", {}),
            },
            p,
            specs[1]["title"],
            "Fail rate",
        ),
    )
    add(2, lambda p: value_bar_plot(all_pass_rate_by(rows, "diagnostic_mode"), p, specs[2]["title"], "All-pass rate"))
    add(3, lambda p: stacked_value_bar(occlusion_component_means_by_mode(rows), p, specs[3]["title"]))
    add(4, lambda p: hist_plot(numeric_values(rows_for_mode(rows, "clean-static"), "f_static"), p, specs[4]["title"], "f_static"))
    add(5, lambda p: hist_plot(numeric_values(rows_for_mode(rows, "cargo-only"), "f_cargo"), p, specs[5]["title"], "f_cargo"))
    add(6, lambda p: hist_plot(numeric_values(rows_for_mode(rows, "context-rich"), "f_context"), p, specs[6]["title"], "f_context"))
    add(7, lambda p: scatter_plot(rows_for_mode(rows, "controlled-occlusion"), "f_target", "f_explicit", p, specs[7]["title"], "f_target", "f_explicit"))
    controlled_rows = rows_for_mode(rows, "controlled-occlusion")
    add(8, lambda p: cross_tab_plot(controlled_rows, "f_target_bin", "f_explicit_actual_bin", p, specs[8]["title"]))
    add(9, lambda p: quantile_hist_plot(numeric_values(controlled_rows, "explicit_abs_error"), p, specs[9]["title"], "explicit_abs_error"))
    add(10, lambda p: cross_tab_plot(controlled_rows, "occluder_side_target", "occluder_side_actual", p, specs[10]["title"]))
    add(11, lambda p: bar_plot(counter_from(rows, "anchor_reject_reason", include_missing=True), p, specs[11]["title"], top=20))
    add(12, lambda p: bar_plot(counter_from(rows, "collision_reject_reason", include_missing=True), p, specs[12]["title"], top=20))
    add(13, lambda p: scatter_plot(rows, "n_context_visible", "context_screen_area_ratio", p, specs[13]["title"], "n_context_visible", "context_screen_area_ratio", "diagnostic_mode"))
    add(14, lambda p: scatter_plot(rows, "context_screen_area_ratio", "f_context", p, specs[14]["title"], "context_screen_area_ratio", "f_context", "diagnostic_mode"))
    add(15, lambda p: grouped_value_bar(gate_fail_rate_by_source(rows), p, specs[15]["title"], "Fail rate"))
    add(
        16,
        lambda p: value_bar_plot(
            all_pass_rate_by_derived(rows, lambda r: str(r.get("elev_bin_target") or numeric_bin(r.get("elev_target"), [10, 20, 30, 40, 50], "elev"))),
            p,
            specs[16]["title"],
            "All-pass rate",
        ),
    )
    add(
        17,
        lambda p: value_bar_plot(
            all_pass_rate_by_derived(rows, lambda r: str(r.get("proj_size_bin_target") or numeric_bin(r.get("projected_size_target"), [0.05, 0.10, 0.20, 0.35], "size"))),
            p,
            specs[17]["title"],
            "All-pass rate",
        ),
    )
    add(18, lambda p: value_bar_plot(all_pass_rate_by(rows, "cargo_on"), p, specs[18]["title"], "All-pass rate"))
    add(
        19,
        lambda p: multi_hist_plot(
            {
                "front_face_visibility": numeric_values(rows, "front_face_visibility"),
                "left_opening_visibility": numeric_values(rows, "left_opening_visibility"),
                "right_opening_visibility": numeric_values(rows, "right_opening_visibility"),
            },
            p,
            specs[19]["title"],
            "Visibility",
        ),
    )
    add(
        20,
        lambda p: multi_hist_plot(
            {
                "placement_attempts": numeric_values(rows, "placement_attempts"),
                "anchor_attempts": numeric_values(rows, "anchor_attempts"),
                "context_placement_attempts": numeric_values(rows, "context_placement_attempts"),
                "cargo_placement_attempts": numeric_values(rows, "cargo_placement_attempts"),
                "occluder_feedback_iterations": numeric_values(rows, "occluder_feedback_iterations"),
                "runtime_s": numeric_values(rows, "runtime_s"),
            },
            p,
            specs[20]["title"],
            "Value",
        ),
    )
    add(21, lambda p: camera_geometry_distribution_plot(rows, p, specs[21]["title"]))
    add(22, lambda p: bar_plot(magenta_corrupt_empty_counts(rows), p, specs[22]["title"]))
    return chart_files


def write_reject_reasons(path: Path, rows: list[dict[str, Any]], baseline_rows: list[dict[str, Any]]) -> None:
    out_rows = []
    for dataset, source_rows in (("new", rows), ("baseline", baseline_rows)):
        if dataset == "new":
            total = len(source_rows) or 1
            c = Counter(r.get("reject_reason") or "(missing)" for r in source_rows)
            for reason, n in c.most_common():
                out_rows.append({"dataset": dataset, "stage": "all", "reject_reason": reason, "count": n, "fraction": n / total})
        else:
            by_stage: dict[str, Counter] = defaultdict(Counter)
            stage_total = Counter()
            for r in source_rows:
                st = r.get("stage") or "(missing)"
                by_stage[st][r.get("reject_reason") or "(missing)"] += 1
                stage_total[st] += 1
            for st, c in sorted(by_stage.items()):
                total = stage_total[st] or 1
                for reason, n in c.most_common():
                    out_rows.append({"dataset": dataset, "stage": st, "reject_reason": reason, "count": n, "fraction": n / total})
    write_csv(path, out_rows, ["dataset", "stage", "reject_reason", "count", "fraction"])


def write_readme(path: Path, root: Path, out: Path, summary: dict[str, Any], baseline_cmp: dict[str, Any], charts: list[str]) -> None:
    status = summary.get("status", "UNKNOWN")
    lines = [
        "# v2 Scene Logic EDA",
        "",
        f"- Input root: `{root}`",
        f"- Output root: `{out}`",
        f"- Status: `{status}`",
        f"- Frames discovered: {summary.get('frame_count')}",
        f"- RGB decode failures: {len(summary.get('rgb_decode_fail_indices', []))}",
        f"- Baseline path: `{baseline_cmp.get('baseline', {}).get('meta', {}).get('path')}`",
        "",
        "## Outputs",
        "",
        "- `frame_metrics.csv`: one row per discovered frame. Missing values are blank; no missing numeric value is coerced to zero.",
        "- `summary.json`: aggregate quality, missing-field, and distribution counts.",
        "- `baseline_vs_new.json`: baseline CSV recomputed on this run and compared with the new dataset.",
        "- `reject_reasons.csv`: reject-reason counts for the new dataset and the baseline.",
        "- `charts/*.png`: 22 fixed EDA charts with English chart text.",
        "- `contact_sheets/`: visual audit contact sheets when `audit_v2_scene_logic.py` is run against the same output root.",
        "- `failure_examples/`: visual audit failure crops/overlays when audit is run.",
        "- `debug_geometry/`: object-role geometry examples when audit is run.",
        "",
        "## Key Notes",
        "",
        "- RGB decode uses strict PIL loading. Truncated images are reported as decode failures.",
        "- Baseline values are recomputed from `pilot_frames.csv` every run.",
        "- Chart filenames and meanings follow the explicitly enumerated 22-chart spec.",
        "- Missing label/record/mask fields are counted in `missing_field_count_by_name`.",
        "- The script accepts partial datasets and writes a failing or warning summary instead of inventing default values.",
        "",
        "## Charts",
        "",
    ]
    mapping = {str(item["filename"]): item for item in baseline_cmp.get("chart_mapping", chart_mapping())}
    for c in charts:
        name = Path(c).name
        spec = mapping.get(name, {})
        metrics = ", ".join(spec.get("metrics", []))
        number = spec.get("number", "?")
        lines.append(f"- {number}. `{name}`: {spec.get('title', '')} [{metrics}]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_self_test_fixture(root: Path, baseline_csv: Path, mask_names: list[str]) -> None:
    (root / "rgb").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    (root / "mask").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (82, 76, 68)).save(root / "rgb" / "f0000_rgb.png")
    for i, name in enumerate(mask_names):
        arr = np.zeros((48, 64), dtype=np.uint8)
        arr[5 + i : 43 - i, 6 + i : 58 - i] = 255
        Image.fromarray(arr, mode="L").save(root / "mask" / f"f0000_{name}.png")

    v2_labels = {
        "pallet_type": "pallet_test",
        "cargo_on": True,
        "n_cargo_actual": 1,
        "position_mode": "floor",
        "f_target": 0.35,
        "f_static": 0.05,
        "f_cargo": 0.10,
        "f_context": 0.07,
        "f_explicit": 0.04,
        "f_total": 0.26,
        "explicit_abs_error": 0.01,
        "front_face_visibility": None,
        "left_opening_visibility": None,
        "right_opening_visibility": None,
        "V_actual": 8,
        "V_vis_actual": 7,
        "mask_area_target_only": 1824,
        "mask_area_after_static": 1720,
        "mask_area_after_cargo": 1600,
        "mask_area_after_context": 1500,
        "mask_area_visible": 1400,
    }
    label = {
        "camera_data": {
            "width": 64,
            "height": 48,
            "resolution": "64x48",
            "aspect_label": "landscape",
            "scene_preset": "self_test_scene",
            "background_asset": "self_test_warehouse",
            "floor_mode": "textured",
            "intrinsics": {"fx": 50.0, "fy": 50.0, "cx": 32.0, "cy": 24.0},
            "floor": {"floor_texture": "concrete"},
        },
        "objects": [
            {
                "name": "pallet_test",
                "dimensions_m": {"width": 1.1, "depth": 1.1, "height": 0.15},
                "safety_gates": {
                    "G1_Vvis>=4": True,
                    "G2_extocc_1to4": True,
                    "G3_visible>=0.5unocc": True,
                    "G4_center_inframe": True,
                    "G5_luma_floor": True,
                    "all_pass": True,
                },
                "v2_labels": v2_labels,
            }
        ],
    }
    (root / "labels" / "f0000_label.json").write_text(json.dumps(label, indent=2), encoding="utf-8")

    record = {
        "idx": 0,
        "seed": 12345,
        "diagnostic_mode": "self_test",
        "placement_mode": "constrained",
        "pallet_type": "pallet_test",
        "scene_preset": "self_test_scene",
        "background_asset": "self_test_warehouse",
        "floor_mode": "textured",
        "elev_target": 18.0,
        "elev_actual": 18.2,
        "azimuth_bin": 1,
        "projected_size_target": 0.18,
        "projected_size_actual": 0.181,
        "proj_size_bin": "medium",
        "v_target": 8,
        "V_actual": 8,
        "V_vis": 7,
        "anchor_translation": [0.0, 0.0, 0.0],
        "anchor_attempts": 3,
        "anchor_reject_reason": None,
        "anchor_reject_counts_by_reason": {"collision": 1},
        "support_surface_name": "floor",
        "n_context_requested": 2,
        "n_context_placed": 2,
        "n_context_visible": 1,
        "context_visible_pixel_ratio": 0.12,
        "context_screen_area_ratio": 0.20,
        "context_placement_attempts": 5,
        "context_reject_counts_by_reason": {"clearance": 1},
        "n_cargo_requested": 1,
        "n_cargo_placed": 1,
        "cargo_on": True,
        "cargo_placement_attempts": 2,
        "cargo_support_pass": True,
        "cargo_collision_pass": True,
        "front_visibility_after_cargo": 0.75,
        "left_opening_visibility_after_cargo": 0.68,
        "right_opening_visibility_after_cargo": 0.58,
        "explicit_occluder_placed": True,
        "exact_collision_count": 0,
        "tested_collision_pairs": 4,
        "broad_phase_hits": 1,
        "exact_collision_hits": 0,
        "collision_reject_reason": "none",
        "pallet_obstacle_collision_count": 0,
        "cargo_collision_count": 0,
        "context_context_collision_count": 0,
        "min_camera_clearance": 0.42,
        "camera_clearance_pass": True,
        "support_pass": True,
        "static_collision_pass": True,
        "static_los_pass": True,
        "f_target": 0.35,
        "f_static": 0.05,
        "f_cargo": 0.10,
        "f_context": 0.07,
        "f_explicit": 0.04,
        "f_total": 0.26,
        "explicit_abs_error": 0.01,
        "f_explicit_target": 0.05,
        "f_explicit_actual": 0.04,
        "occluder_feedback_iterations": 4,
        "occluder_side_target": "left",
        "occluder_side_actual": "left",
        "explicit_occluder_visible_pixels": 128,
        "explicit_collision_pass": True,
        "front_face_visibility": None,
        "left_opening_visibility": None,
        "right_opening_visibility": None,
        "opening_visibility_reason": "ok",
        "luma_frame": 82.0,
        "luma_pallet": 75.0,
        "magenta_fraction": 0.0,
        "corrupt_rgb": False,
        "corrupt_mask": False,
        "mask_invariants_pass": True,
        "mask_area_target_only": 1824,
        "mask_area_after_static": 1720,
        "mask_area_after_cargo": 1600,
        "mask_area_after_context": 1500,
        "mask_area_visible": 1400,
        "G1_pass": True,
        "G2_pass": True,
        "G3_pass": True,
        "G4_pass": True,
        "G5_pass": True,
        "all_pass": True,
        "reject_reason": "accepted",
        "runtime_s": 1.25,
        "stage_runtime_s": {"anchor": 0.2, "context": 0.3, "render": 0.75},
    }
    (root / "records.json").write_text(json.dumps({"records": [record]}, indent=2), encoding="utf-8")
    (root / "records.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    baseline_csv.parent.mkdir(parents=True, exist_ok=True)
    with baseline_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["stage", "all_pass", *GATE_COLUMNS, "reject_reason", "f_target", "f_actual", "V_actual", "V_vis", "scene_preset", "resolution"],
        )
        w.writeheader()
        row = {
            "stage": "rendered",
            "all_pass": "True",
            "G1_pass": "True",
            "G2_pass": "True",
            "G3_pass": "True",
            "G4_pass": "True",
            "G5_pass": "True",
            "reject_reason": "accepted",
            "f_target": "0.35",
            "f_actual": "0.26",
            "V_actual": "8",
            "V_vis": "7",
            "scene_preset": "baseline_self_test",
            "resolution": "64x48",
        }
        w.writerow(row)


def run_self_test(args: argparse.Namespace) -> int:
    mask_names = [x.strip() for x in args.mask_names.split(",") if x.strip()]
    with tempfile.TemporaryDirectory(prefix="scene_logic_analyze_selftest_") as tmp:
        tmp_root = Path(tmp)
        root = tmp_root / "fixture"
        out = root / DEFAULT_OUT_DIRNAME
        baseline = tmp_root / "baseline" / "pilot_frames.csv"
        write_self_test_fixture(root, baseline, mask_names)
        fixture_records, fixture_record_meta = load_records(root)
        if fixture_record_meta.get("source_used") != "records.jsonl":
            errors = [f"expected records.jsonl source priority, got {fixture_record_meta.get('source_used')}"]
        else:
            errors = []
        if fixture_record_meta.get("ignored_sources") != ["records.json"]:
            errors.append(f"expected records.json to be ignored, got {fixture_record_meta.get('ignored_sources')}")
        if fixture_record_meta.get("duplicate_record_indices"):
            errors.append("same record in records.jsonl and records.json was incorrectly marked duplicate")
        if sorted(fixture_records) != [0]:
            errors.append(f"expected one canonical fixture record, got indices={sorted(fixture_records)}")
        dup_root = tmp_root / "dup_fixture"
        dup_root.mkdir(parents=True, exist_ok=True)
        duplicate_record = {"idx": 7, "seed": 7}
        (dup_root / "records.jsonl").write_text(json.dumps(duplicate_record) + "\n" + json.dumps(duplicate_record) + "\n", encoding="utf-8")
        _, dup_meta = load_records(dup_root)
        if dup_meta.get("duplicate_record_indices") != [7]:
            errors.append(f"same-source duplicate idx was not detected: {dup_meta.get('duplicate_record_indices')}")
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--dir",
            str(root),
            "--baseline",
            str(baseline),
            "--mask-names",
            ",".join(mask_names),
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if proc.returncode != 0:
            errors.append(f"child analyze exited with {proc.returncode}")

        frame_csv = out / "frame_metrics.csv"
        if not frame_csv.exists():
            errors.append("frame_metrics.csv was not created")
            rows = []
            fieldnames = []
        else:
            with frame_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                rows = list(reader)

        expected_fields = REQUIRED_FRAME_METRIC_FIELDS + REQUIRED_SCENE_LOGIC_FIELDS
        missing_header = [f for f in expected_fields if f not in fieldnames]
        if missing_header:
            errors.append("required scene-logic headers missing: " + ",".join(missing_header))
        if len(rows) != 1:
            errors.append(f"expected one fixture row, got {len(rows)}")
        elif not missing_header:
            none_allowed = {"anchor_reject_reason", "front_face_visibility", "left_opening_visibility", "right_opening_visibility"}
            blank_required = [f for f in expected_fields if f not in none_allowed and rows[0].get(f) in (None, "")]
            if blank_required:
                errors.append("required scene-logic values blank in fixture row: " + ",".join(blank_required))
            for field in sorted(none_allowed):
                if rows[0].get(field) not in (None, ""):
                    errors.append(f"expected {field} fixture value to remain blank/None")
            missing_fields = set((rows[0].get("missing_fields") or "").split(";"))
            false_missing = sorted(field for field in none_allowed if field in missing_fields)
            if false_missing:
                errors.append("present None fields were marked missing: " + ",".join(false_missing))

        expected_chart_names = [str(spec["filename"]) for spec in CHART_PLAN]
        actual_chart_names = sorted(p.name for p in (out / "charts").glob("*.png")) if (out / "charts").exists() else []
        if actual_chart_names != expected_chart_names:
            errors.append(f"chart filenames mismatch: expected={expected_chart_names} actual={actual_chart_names}")

        summary_path = out / "summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            validation = summary.get("self_validation", {})
            if validation.get("chart_plan_errors"):
                errors.append("chart plan validation errors: " + ";".join(validation["chart_plan_errors"]))
            if validation.get("generated_chart_errors"):
                errors.append("generated chart validation errors: " + ";".join(validation["generated_chart_errors"]))
            if summary.get("required_scene_logic_missing_count_by_name"):
                errors.append("self-test fixture unexpectedly has required scene-logic missing fields")
            meta = summary.get("record_meta", {})
            if meta.get("source_used") != "records.jsonl" or meta.get("ignored_sources") != ["records.json"]:
                errors.append(f"summary record_meta did not preserve source priority: {meta}")
            for dirname in ("charts", "contact_sheets", "failure_examples", "debug_geometry"):
                if not (out / dirname).exists():
                    errors.append(f"required output directory missing: {dirname}")
        else:
            errors.append("summary.json was not created")

        baseline_cmp_path = out / "baseline_vs_new.json"
        if baseline_cmp_path.exists():
            baseline_cmp = json.loads(baseline_cmp_path.read_text(encoding="utf-8"))
            if baseline_cmp.get("baseline", {}).get("meta", {}).get("path") != str(baseline.resolve()):
                errors.append("baseline path was not read from the self-test CSV")
            if not baseline_cmp.get("chart_mapping"):
                errors.append("baseline_vs_new chart_mapping missing")
        else:
            errors.append("baseline_vs_new.json was not created")

        if errors:
            print("[self-test] FAIL")
            for e in errors:
                print(f"[self-test] {e}")
            return 1
        print(
            f"[self-test] PASS frame_fields={len(REQUIRED_FRAME_METRIC_FIELDS)} "
            f"scene_logic_fields={len(REQUIRED_SCENE_LOGIC_FIELDS)} charts={len(CHART_PLAN)}"
        )
        return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(args)
    root = as_path(args.dir)
    out = as_path(args.out) if args.out else root / DEFAULT_OUT_DIRNAME
    baseline_path = as_path(args.baseline)
    mask_names = [x.strip() for x in args.mask_names.split(",") if x.strip()]
    global MASK_NAMES
    MASK_NAMES = mask_names

    out.mkdir(parents=True, exist_ok=True)
    for dirname in ("charts", "contact_sheets", "failure_examples", "debug_geometry"):
        (out / dirname).mkdir(parents=True, exist_ok=True)
    records, record_meta = load_records(root)
    indices = discover_indices(root, records, mask_names) if root.exists() else []
    rows = [build_frame_row(root, idx, records.get(idx), mask_names) for idx in indices]
    columns = frame_columns(mask_names)
    write_csv(out / "frame_metrics.csv", rows, columns)

    baseline_rows, baseline_meta = load_baseline(baseline_path)
    baseline_summary = summarize_baseline(baseline_rows, baseline_meta)
    summary = summarize_new(rows, root, record_meta)
    plan_errors = validate_chart_plan(columns)
    summary["chart_mapping"] = chart_mapping()
    summary["self_validation"] = {
        "required_scene_logic_fields_present": not [f for f in REQUIRED_SCENE_LOGIC_FIELDS if f not in columns],
        "chart_plan_errors": plan_errors,
        "generated_chart_errors": [],
    }
    errors = []
    warnings = []
    errors.extend(record_meta.get("errors", []))
    if not root.exists():
        errors.append("input root missing")
    if not rows:
        errors.append("no frames discovered")
    errors.extend(plan_errors)
    if baseline_meta.get("error"):
        warnings.append(f"baseline issue: {baseline_meta['error']}")
    if summary["rgb_decode_fail_indices"]:
        warnings.append("strict RGB decode failures present")
    if summary["missing_field_count_by_name"]:
        warnings.append("missing fields present")
    summary["errors"] = errors
    summary["warnings"] = warnings
    summary["status"] = "FAIL" if errors else ("WARN" if warnings else "PASS")

    baseline_vs_new = {
        "baseline": baseline_summary,
        "new": summary,
        "delta": {
            "all_pass_rate": (
                (summary["all_pass_rate"] - baseline_summary["all_pass_rate"])
                if summary["all_pass_rate"] is not None and baseline_summary.get("all_pass_rate") is not None
                else None
            ),
            "gate_fail_count": {
                g: summary["gate_fail_count"].get(g, 0) - baseline_summary.get("gate_fail_count", {}).get(g, 0)
                for g in GATE_COLUMNS
            },
            "gate_fail_rate": {
                g: (
                    summary["gate_fail_rate"].get(g) - baseline_summary.get("gate_fail_rate", {}).get(g)
                    if summary["gate_fail_rate"].get(g) is not None and baseline_summary.get("gate_fail_rate", {}).get(g) is not None
                    else None
                )
                for g in GATE_COLUMNS
            },
        },
    }

    charts = save_charts(out, rows, baseline_summary, summary)
    generated_chart_errors = validate_generated_charts(charts)
    summary["self_validation"]["generated_chart_errors"] = generated_chart_errors
    if generated_chart_errors:
        summary["errors"].extend(generated_chart_errors)
        summary["status"] = "FAIL"
        baseline_vs_new["new"] = summary
    baseline_vs_new["chart_mapping"] = chart_mapping()
    write_reject_reasons(out / "reject_reasons.csv", rows, baseline_rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "baseline_vs_new.json").write_text(json.dumps(baseline_vs_new, indent=2, ensure_ascii=False), encoding="utf-8")
    write_readme(out / "README.md", root, out, summary, baseline_vs_new, charts)
    print(f"[analyze] status={summary['status']} frames={len(rows)} out={out}")
    if errors:
        print("[analyze] errors: " + "; ".join(errors))
    if warnings:
        print("[analyze] warnings: " + "; ".join(warnings))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
