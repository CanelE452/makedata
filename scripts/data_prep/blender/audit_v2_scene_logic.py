"""Visual and structural audit for the v2 scene-logic 500-frame pilot.

This script is bpy-free and uses only PIL, numpy, and the standard library.
It creates an overlay for every discovered frame, checks frame-level visual
integrity, and builds small contact sheets. RGB decoding is strict.

Outputs default to <input>/eda:
  audit_frames.csv
  audit_summary.json
  overlay_all/*.png
  contact_sheets/*.png
  failure_examples.csv
  failure_examples/*.png
  debug_geometry/*.png
  audit_README.md
  summary.json (preserved, with concise visual_audit merge)
  README.md (preserved, with concise Visual Audit section)

Phase 5 adds a source-mask integrity pass on top of the scalar area checks. Its reports go to
--mask-report-out (default <out>/mask_integrity):
  mask_hashes.csv
  mask_duplicate_groups.json
  mask_pixel_inclusion_failures.csv
  mask_integrity_source_masks*.png (also written into <out>/contact_sheets/)

Role split against audit_pnp_eligibility.py (Phase 4): that script answers "is the target big
enough to solve PnP" and therefore only needs M0's bbox/area; this script answers "is the M0..M4
mask SET internally consistent" (strict decode, hashes, pixel-level inclusion, duplicates,
projected-cuboid alignment). The foreground-bbox primitive is shared (foreground_bbox below), the
empty-M0 verdict stays on the pre-existing empty_target_mask column instead of being recomputed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFile, ImageFont

# Strict decode: a truncated PNG must raise instead of being silently zero-filled. Another import
# in the same process can flip this global, so pin it here.
ImageFile.LOAD_TRUNCATED_IMAGES = False


DEFAULT_DIR = "data/pallet/_v2_scene_logic_500_seed7500"
DEFAULT_OUT_DIRNAME = "eda"
MASK_NAMES = ["m0", "m1", "m2", "m3", "m4"]
DEFAULT_MASK_REPORT_DIRNAME = "mask_integrity"
# Which scene component removes target pixels on each M(i-1) -> M(i) transition
# (scene_placement_v2.OCCLUSION_DECOMPOSITION_ORDER / _MASK_AREA_KEYS).
MASK_STAGE_OCCLUDER_SOURCE = {"m1": "static", "m2": "cargo", "m3": "context", "m4": "explicit"}
# Foreground pixels of a target mask must lie inside the projected cuboid hull, so anything above
# this is flagged for review. [미검증 시작값] - reported only, never a hard audit failure.
DEFAULT_HULL_OUTSIDE_WARN_RATIO = 0.20
FRONT_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0)]
REAR_EDGES = [(4, 5), (5, 6), (6, 7), (7, 4)]
CONN_EDGES = [(0, 4), (1, 5), (2, 6), (3, 7)]
AUDIT_COLUMNS = [
    "idx",
    "frame_id",
    "mode",
    "diagnostic_mode",
    "audit_pass",
    "failure_count",
    "failures",
    "record_present",
    "label_present",
    "rgb_present",
    "rgb_decode_ok",
    "rgb_decode_error",
    "rgb_sha256",
    "duplicate_rgb_hash",
    "duplicate_record_index",
    "required_label_missing_count",
    "required_label_missing",
    "file_count_mismatch",
    "accepted_frame",
    "exact_collision_count",
    "pallet_obstacle_collision_count",
    "cargo_collision_count",
    "context_context_collision_count",
    "camera_clearance_pass",
    "support_required",
    "support_pass",
    "ground_continuity_pass",
    "ground_probe_count",
    "ground_probe_fail_count",
    "ground_probe_max_step_m",
    "procedural_floor_edge_risk",
    "procedural_floor_edge_margin_m",
    "ground_continuity_reason",
    "anchor_reject_reason",
    "reject_reason",
    "front_near",
    "front_dist",
    "rear_dist",
    "connector_crossings",
    "points_2d_finite",
    "points_2d_in_image_count",
    "mask_monotonic_ok",
    "empty_target_mask",
    "mask_strict_decode_ok",
    "mask_shape_consistent",
    "mask_rgb_shape_match",
    "mask_pixel_inclusion_ok",
    "mask_pixel_inclusion_violation_px",
    "mask_pixel_inclusion_violations",
    "mask_empty_stages",
    "mask_within_frame_duplicate_groups",
    "mask_within_frame_duplicate_class",
    "mask_cross_frame_duplicate_stages",
    "mask_cross_frame_duplicate_class",
    "mask_m0_hull_bbox_iou",
    "mask_m0_hull_outside_ratio",
    "mask_m4_hull_bbox_iou",
    "mask_m4_hull_outside_ratio",
    "mask_hull_align_warn",
    "mask_hull_align_reason",
    "magenta_ratio",
    "magenta_fail",
    "all_pass_gate",
    "fatal_pass",
    "fatal_failure_count",
    "fatal_failures",
]
MASK_FRAME_COLUMNS = [c for c in AUDIT_COLUMNS if c.startswith("mask_")]


def per_mask_columns(name: str) -> list[str]:
    return [
        f"mask_{name}_present",
        f"mask_{name}_decode_ok",
        f"mask_{name}_area",
        f"mask_{name}_error",
        f"mask_{name}_sha256",
        f"mask_{name}_content_sha256",
        f"mask_{name}_width",
        f"mask_{name}_height",
    ]


for _name in MASK_NAMES:
    AUDIT_COLUMNS.extend(per_mask_columns(_name))


def audit_columns(mask_names: list[str]) -> list[str]:
    cols = [c for c in AUDIT_COLUMNS if not c.startswith("mask_") or c in MASK_FRAME_COLUMNS]
    if "duplicate_filename" not in cols:
        insert_at = cols.index("duplicate_rgb_hash") if "duplicate_rgb_hash" in cols else len(cols)
        cols.insert(insert_at, "duplicate_filename")
    for name in mask_names:
        cols.extend(per_mask_columns(name))
    return cols


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit v2 scene-logic frames and overlays.")
    p.add_argument("--dir", default=DEFAULT_DIR, help="Input dataset root.")
    p.add_argument("--out", default=None, help="Output directory. Default: <dir>/eda")
    p.add_argument("--mask-names", default=",".join(MASK_NAMES), help="Comma-separated mask suffixes.")
    p.add_argument("--target-mask", default="m0", help="Mask suffix used for empty-target check.")
    p.add_argument("--max-sheet-frames", type=int, default=20, help="Max frames per contact sheet.")
    p.add_argument("--magenta-threshold", type=float, default=0.0, help="Fail if magenta ratio is greater than this.")
    p.add_argument("--expected-frame-count", type=int, default=None, help="Require this exact count and contiguous index range.")
    p.add_argument("--expected-start-index", type=int, default=0, help="First required index when --expected-frame-count is set.")
    p.add_argument("--mask-report-out", default=None, help=f"Mask integrity report directory. Default: <out>/{DEFAULT_MASK_REPORT_DIRNAME}")
    p.add_argument("--hull-outside-warn-ratio", type=float, default=DEFAULT_HULL_OUTSIDE_WARN_RATIO, help="Warn when this fraction of mask foreground falls outside the projected cuboid hull.")
    p.add_argument("--self-test", action="store_true", help="Run a synthetic fixture test for audit outputs.")
    return p.parse_args()


def as_path(s: str | os.PathLike[str]) -> Path:
    return Path(s).expanduser().resolve()


def read_json(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def scan_missing_texture_logs(root: Path) -> dict[str, Any]:
    """Find Blender missing-image diagnostics in this dataset's own logs."""
    patterns = (
        re.compile(r"\bERROR\s+Image file\b.*\bdoes not exist\b", re.IGNORECASE),
        re.compile(r"\bmissing texture\b", re.IGNORECASE),
        re.compile(r"\bcould not load image\b", re.IGNORECASE),
    )
    matches: list[dict[str, Any]] = []
    log_dir = root / "logs"
    for path in sorted(log_dir.rglob("*.log")) if log_dir.exists() else []:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in patterns):
                matches.append(
                    {
                        "file": str(path.relative_to(root)),
                        "line_number": line_number,
                        "line": line.strip(),
                    }
                )
    return {"count": len(matches), "matches": matches}


def load_records(root: Path) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    seen = Counter()
    errors = []
    source_used = None
    ignored_sources: list[str] = []

    def add_record(obj: Any, source: str) -> None:
        if not isinstance(obj, dict):
            return
        idx = obj.get("idx", obj.get("frame_index"))
        try:
            idx_i = int(idx)
        except Exception:
            errors.append(f"{source}: record without integer idx")
            return
        seen[idx_i] += 1
        rec = dict(obj)
        rec["_record_source"] = source
        records[idx_i] = rec

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
    for suffix in mask_names:
        for path in (root / "mask").glob(f"f*_{suffix}.png"):
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


def bool_value(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
    return None


def first_value(*values: Any) -> Any | None:
    for v in values:
        if v is not None:
            return v
    return None


def int_value(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except Exception:
        return None


def finite_point_list(points: Any, expected: int | None = None) -> tuple[bool, np.ndarray | None]:
    try:
        arr = np.asarray(points, dtype=np.float64)
        if expected is not None and arr.shape[0] != expected:
            return False, None
        if arr.ndim != 2 or arr.shape[1] < 2:
            return False, None
        if not np.isfinite(arr[:, :2]).all():
            return False, None
        return True, arr
    except Exception:
        return False, None


def load_label(root: Path, idx: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    path = root / "labels" / f"f{idx:04d}_label.json"
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


def strict_open_rgb(path: Path) -> tuple[Image.Image | None, dict[str, Any]]:
    info = {"present": path.exists(), "decode_ok": False, "decode_error": None, "width": None, "height": None, "magenta_ratio": None}
    if not path.exists():
        info["decode_error"] = "missing"
        return None, info
    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            arr = np.asarray(rgb)
            info["width"], info["height"] = rgb.size
            mag = (arr[:, :, 0] > 180) & (arr[:, :, 1] < 90) & (arr[:, :, 2] > 180)
            info["magenta_ratio"] = float(mag.mean()) if arr.size else None
            info["decode_ok"] = True
            return rgb.copy(), info
    except Exception as e:
        info["decode_error"] = str(e)
        return None, info


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def mask_area(path: Path) -> dict[str, Any]:
    out = {"present": path.exists(), "decode_ok": False, "area": None, "error": None, "image": None}
    if not path.exists():
        out["error"] = "missing"
        return out
    try:
        with Image.open(path) as im:
            gray = im.convert("L")
            arr = np.asarray(gray)
            out["area"] = int((arr > 127).sum())
            out["decode_ok"] = True
            out["image"] = gray.copy()
    except Exception as e:
        out["error"] = str(e)
    return out


# ------------------------------------------------------------------------------------------
# Phase 5: source-mask integrity (strict decode, hashes, pixel-level inclusion, hull alignment)
# ------------------------------------------------------------------------------------------

def strict_decode_mask(path: Path) -> dict[str, Any]:
    """Strictly decode one source mask into a boolean foreground array plus its SHA256.

    Superset of mask_area(): keeps present/decode_ok/area/error/image so existing consumers work,
    and adds fg/sha256/width/height/all_black for the pixel-level checks. Truncated or
    CRC-corrupt PNGs fail here instead of decoding to a partially zeroed image.
    """
    out: dict[str, Any] = {
        "present": path.exists(),
        "decode_ok": False,
        "area": None,
        "error": None,
        "image": None,
        "fg": None,
        "sha256": None,
        "content_sha256": None,
        "width": None,
        "height": None,
        "all_black": None,
    }
    if not path.exists():
        out["error"] = "missing"
        return out
    out["sha256"] = sha256_file(path)
    try:
        with Image.open(path) as probe:
            probe.verify()  # structural/CRC pass; the handle is unusable afterwards
    except Exception as e:
        out["error"] = f"verify_failed: {e}"
        return out
    try:
        with Image.open(path) as im:
            gray = im.convert("L")
            gray.load()
            arr = np.asarray(gray)
            fg = arr > 127
            out["width"], out["height"] = gray.size
            out["area"] = int(fg.sum())
            out["all_black"] = bool(out["area"] == 0)
            # Byte SHA256 alone under-reports identical masks: Cycles writes sub-threshold
            # antialiasing noise, so two stages can share an identical >127 foreground and still
            # differ byte-wise. The content hash is the one that means "same mask".
            out["content_sha256"] = hashlib.sha256(
                f"{fg.shape[0]}x{fg.shape[1]}|".encode("ascii") + np.packbits(fg).tobytes()
            ).hexdigest()
            out["decode_ok"] = True
            out["image"] = gray.copy()
            out["fg"] = fg
    except Exception as e:
        out["error"] = str(e)
    return out


def foreground_bbox(mask: Any) -> dict[str, float | None]:
    """Foreground bbox of a boolean array or a decoded PIL 'L' mask (>127 = foreground)."""
    out: dict[str, float | None] = {
        "x0": None, "y0": None, "x1": None, "y1": None,
        "w": None, "h": None, "min_side": None,
    }
    if mask is None:
        return out
    arr = mask if isinstance(mask, np.ndarray) else np.asarray(mask)
    fg = arr if arr.dtype == bool else (arr > 127)
    if fg.ndim != 2:
        return out
    if not fg.any():
        return {"x0": None, "y0": None, "x1": None, "y1": None, "w": 0.0, "h": 0.0, "min_side": 0.0}
    rows = np.where(fg.any(axis=1))[0]
    cols = np.where(fg.any(axis=0))[0]
    x0, x1 = float(cols[0]), float(cols[-1])
    y0, y1 = float(rows[0]), float(rows[-1])
    w = x1 - x0 + 1.0
    h = y1 - y0 + 1.0
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "w": w, "h": h, "min_side": min(w, h)}


def mask_pixel_inclusion(masks: dict[str, dict[str, Any]], mask_names: list[str]) -> dict[str, Any]:
    """Pixel-level M4 subset-of M3 subset-of M2 subset-of M1 subset-of M0.

    The scalar area check only sees monotonic totals; this compares the boolean arrays so a
    later stage that gains a pixel somewhere while losing more elsewhere is still caught.
    """
    out: dict[str, Any] = {
        "checked": False,
        "ok": None,
        "pairs": [],
        "violation_pair_count": 0,
        "violation_px_total": 0,
        "max_violation_ratio": None,
        "shape_consistent": None,
        "reason": None,
    }
    usable = [name for name in mask_names if masks.get(name, {}).get("fg") is not None]
    if len(usable) < 2:
        out["reason"] = "insufficient_decoded_masks"
        return out
    shapes = {masks[name]["fg"].shape for name in usable}
    out["shape_consistent"] = len(shapes) == 1
    if len(usable) != len(mask_names):
        out["reason"] = "partial_mask_set"
    max_ratio = 0.0
    for outer_name, inner_name in zip(usable, usable[1:]):
        outer = masks[outer_name]["fg"]
        inner = masks[inner_name]["fg"]
        pair: dict[str, Any] = {
            "outer": outer_name,
            "inner": inner_name,
            "outer_area": int(outer.sum()),
            "inner_area": int(inner.sum()),
            "shape_mismatch": outer.shape != inner.shape,
            "violation_px": None,
            "violation_ratio": None,
        }
        if pair["shape_mismatch"]:
            pair["reason"] = f"shape {outer.shape} vs {inner.shape}"
            out["violation_pair_count"] += 1
        else:
            violation = int(np.count_nonzero(inner & ~outer))
            denom = max(1, pair["inner_area"])
            pair["violation_px"] = violation
            pair["violation_ratio"] = float(violation) / float(denom)
            if violation > 0:
                out["violation_pair_count"] += 1
                out["violation_px_total"] += violation
                max_ratio = max(max_ratio, pair["violation_ratio"])
        out["pairs"].append(pair)
    out["checked"] = True
    out["max_violation_ratio"] = max_ratio
    out["ok"] = out["violation_pair_count"] == 0
    return out


def _cross2(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def convex_hull_points(points: Any) -> np.ndarray | None:
    """Andrew monotone-chain hull. numpy-only so this audit keeps its PIL/numpy/stdlib footprint."""
    if points is None:
        return None
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] < 2 or not np.isfinite(p[:, :2]).all():
        return None
    pts = np.unique(np.round(p[:, :2], 6), axis=0)
    if len(pts) < 3:
        return pts
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    pts = pts[order]
    lower: list[np.ndarray] = []
    for q in pts:
        while len(lower) >= 2 and _cross2(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list[np.ndarray] = []
    for q in pts[::-1]:
        while len(upper) >= 2 and _cross2(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return pts
    return np.asarray(hull, dtype=np.float64)


def clip_polygon_to_rect(poly: np.ndarray | None, width: float, height: float) -> np.ndarray | None:
    """Sutherland-Hodgman clip to the image rectangle.

    Cuboid corners can land thousands of pixels off-screen (or behind the camera); clipping first
    keeps the rasterizer bounded and makes the hull bbox comparable to a mask bbox.
    """
    if poly is None or len(poly) < 3:
        return None
    out = [np.asarray(pt, dtype=np.float64) for pt in poly]
    edges = (
        (lambda pt: pt[0] >= 0.0, (0.0, 0.0), (0.0, 1.0)),
        (lambda pt: pt[0] <= width, (width, 0.0), (0.0, 1.0)),
        (lambda pt: pt[1] >= 0.0, (0.0, 0.0), (1.0, 0.0)),
        (lambda pt: pt[1] <= height, (0.0, height), (1.0, 0.0)),
    )
    for inside, origin, direction in edges:
        if not out:
            return None
        o = np.asarray(origin, dtype=np.float64)
        d = np.asarray(direction, dtype=np.float64)
        clipped: list[np.ndarray] = []
        for i, cur in enumerate(out):
            prev = out[i - 1]
            cur_in = inside(cur)
            prev_in = inside(prev)
            if cur_in != prev_in:
                seg = cur - prev
                denom = _cross2(np.zeros(2), d, seg)
                if abs(denom) > 1e-12:
                    t = _cross2(np.zeros(2), d, o - prev) / denom
                    clipped.append(prev + t * seg)
            if cur_in:
                clipped.append(cur)
        out = clipped
    if len(out) < 3:
        return None
    return np.asarray(out, dtype=np.float64)


def rasterize_polygon(poly: np.ndarray | None, width: int, height: int) -> np.ndarray | None:
    if poly is None or len(poly) < 3 or width <= 0 or height <= 0:
        return None
    img = Image.new("L", (int(width), int(height)), 0)
    ImageDraw.Draw(img).polygon([(float(x), float(y)) for x, y in poly], fill=255)
    return np.asarray(img) > 127


def bbox_iou(a: dict[str, float | None], b: dict[str, float | None]) -> float | None:
    if any(a.get(k) is None for k in ("x0", "y0", "x1", "y1")):
        return None
    if any(b.get(k) is None for k in ("x0", "y0", "x1", "y1")):
        return None
    ix0 = max(float(a["x0"]), float(b["x0"]))
    iy0 = max(float(a["y0"]), float(b["y0"]))
    ix1 = min(float(a["x1"]), float(b["x1"]))
    iy1 = min(float(a["y1"]), float(b["y1"]))
    iw = max(0.0, ix1 - ix0 + 1.0)
    ih = max(0.0, iy1 - iy0 + 1.0)
    inter = iw * ih
    area_a = (float(a["x1"]) - float(a["x0"]) + 1.0) * (float(a["y1"]) - float(a["y0"]) + 1.0)
    area_b = (float(b["x1"]) - float(b["x0"]) + 1.0) * (float(b["y1"]) - float(b["y0"]) + 1.0)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else None


def hull_alignment(fg: np.ndarray | None, hull: np.ndarray | None, width: Any, height: Any) -> dict[str, Any]:
    """Compare a mask's foreground with the projected-cuboid hull (bbox IoU + outside ratio)."""
    out: dict[str, Any] = {
        "bbox_iou": None,
        "center_dist_px": None,
        "outside_ratio": None,
        "outside_px": None,
        "mask_bbox": None,
        "hull_bbox": None,
        "reason": None,
    }
    if fg is None:
        out["reason"] = "mask_unavailable"
        return out
    if hull is None or len(hull) < 3:
        out["reason"] = "hull_unavailable"
        return out
    try:
        w = int(width)
        h = int(height)
    except Exception:
        out["reason"] = "image_size_unknown"
        return out
    if fg.shape != (h, w):
        out["reason"] = "mask_shape_mismatch"
        return out
    clipped = clip_polygon_to_rect(hull, float(w), float(h))
    if clipped is None:
        out["reason"] = "hull_outside_image"
        return out
    hull_mask = rasterize_polygon(clipped, w, h)
    if hull_mask is None:
        out["reason"] = "hull_rasterize_failed"
        return out
    m_box = foreground_bbox(fg)
    h_box = foreground_bbox(hull_mask)
    out["mask_bbox"] = [m_box["x0"], m_box["y0"], m_box["x1"], m_box["y1"]]
    out["hull_bbox"] = [h_box["x0"], h_box["y0"], h_box["x1"], h_box["y1"]]
    fg_area = int(fg.sum())
    if fg_area == 0:
        out["reason"] = "empty_mask"
        return out
    outside = int(np.count_nonzero(fg & ~hull_mask))
    out["outside_px"] = outside
    out["outside_ratio"] = float(outside) / float(fg_area)
    out["bbox_iou"] = bbox_iou(m_box, h_box)
    if m_box["x0"] is not None and h_box["x0"] is not None:
        mcx = 0.5 * (float(m_box["x0"]) + float(m_box["x1"]))
        mcy = 0.5 * (float(m_box["y0"]) + float(m_box["y1"]))
        hcx = 0.5 * (float(h_box["x0"]) + float(h_box["x1"]))
        hcy = 0.5 * (float(h_box["y0"]) + float(h_box["y1"]))
        out["center_dist_px"] = float(math.hypot(mcx - hcx, mcy - hcy))
    return out


MASK_STAGE_FRACTION_KEY = {
    "static": "f_static",
    "cargo": "f_cargo",
    "context": "f_context",
    "explicit": "f_explicit",
}


def occluder_source_states(rec_map: dict[str, Any], v2: dict[str, Any] | None) -> dict[str, str]:
    """Per-transition state used to judge identical stage masks inside one frame.

    "absent"              nothing was placed for that source
    "placed_no_occlusion" something was placed but the record's own occlusion fraction is 0
                          (a context prop next to the pallet occludes nothing - not a defect)
    "contradiction"       the record claims a non-zero occlusion fraction yet the mask is unchanged
    "unknown"             the record does not carry enough fields to decide
    """
    def pick(*keys: str) -> Any:
        for key in keys:
            val = first_value(rec_map.get(key), nested(v2, [key]))
            if val is not None:
                return val
        return None

    placed: dict[str, bool | None] = {}
    n_cargo = int_value(pick("n_cargo_placed", "n_cargo_actual"))
    cargo_on = bool_value(pick("cargo_on"))
    if n_cargo is not None:
        placed["cargo"] = n_cargo > 0
    elif cargo_on is not None:
        placed["cargo"] = cargo_on
    else:
        placed["cargo"] = None
    n_context = int_value(pick("n_context_placed"))
    placed["context"] = (n_context > 0) if n_context is not None else None
    explicit = bool_value(pick("explicit_occluder_placed", "occluder_placed"))
    placed["explicit"] = explicit
    # Static scene geometry has no placement counter; only its area-derived fraction is recorded.
    placed["static"] = None

    out: dict[str, str] = {}
    for source, frac_key in MASK_STAGE_FRACTION_KEY.items():
        raw = pick(frac_key)
        try:
            fraction = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            fraction = None
        if placed.get(source) is False:
            out[source] = "absent"
        elif fraction is None:
            out[source] = "unknown"
        elif fraction > 0.0:
            out[source] = "contradiction"
        elif placed.get(source) is True:
            out[source] = "placed_no_occlusion"
        else:
            out[source] = "absent"
    return out


def classify_stage_span(stages: list[str], mask_names: list[str], states: dict[str, str]) -> dict[str, Any]:
    """Classify identical stage masks inside one frame as a legitimate no-op or a defect."""
    order = {name: i for i, name in enumerate(mask_names)}
    idxs = sorted(order[s] for s in stages if s in order)
    spanned = [mask_names[i] for i in range(idxs[0] + 1, idxs[-1] + 1)] if idxs else []
    sources = [MASK_STAGE_OCCLUDER_SOURCE.get(name) for name in spanned]
    span_states = [states.get(src, "unknown") if src else "unknown" for src in sources]
    if not span_states:
        verdict = "unverified_no_op"
    elif "contradiction" in span_states:
        verdict = "unexpected_identical_stage"
    elif "unknown" in span_states:
        verdict = "unverified_no_op"
    elif all(state == "absent" for state in span_states):
        verdict = "expected_no_op"
    else:
        verdict = "no_op_placed_but_not_occluding"
    return {
        "stages": stages,
        "spanned_transitions": spanned,
        "occluder_sources": [s for s in sources if s],
        "occluder_states": span_states,
        "classification": verdict,
    }


def within_frame_mask_duplicates(
    masks: dict[str, dict[str, Any]],
    mask_names: list[str],
    states: dict[str, str],
) -> list[dict[str, Any]]:
    """Groups of two or more stages inside a frame that carry the same mask.

    Grouped on the foreground content hash; `byte_identical` says whether the PNG bytes also
    match (a byte-exact copy vs. the same silhouette re-rendered).
    """
    by_hash: dict[str, list[str]] = defaultdict(list)
    for name in mask_names:
        ms = masks.get(name) or {}
        if ms.get("decode_ok") and ms.get("content_sha256"):
            by_hash[str(ms["content_sha256"])].append(name)
    groups = []
    for digest, stages in by_hash.items():
        if len(stages) < 2:
            continue
        stages = [name for name in mask_names if name in set(stages)]
        info = classify_stage_span(stages, mask_names, states)
        info["content_sha256"] = digest
        info["byte_identical"] = len({masks[s].get("sha256") for s in stages}) == 1
        info["sha256"] = [masks[s].get("sha256") for s in stages]
        info["area"] = masks[stages[0]].get("area")
        info["all_black"] = masks[stages[0]].get("all_black")
        groups.append(info)
    groups.sort(key=lambda g: mask_names.index(g["stages"][0]))
    return groups


def front_is_near(lab: dict[str, Any] | None, obj: dict[str, Any] | None) -> tuple[bool | None, float | None, float | None]:
    if not lab or not obj:
        return None, None, None
    ok, corners = finite_point_list(obj.get("cuboid"), expected=8)
    if not ok or corners is None:
        return None, None, None
    try:
        cam = np.asarray(lab["camera_data"]["location_worldframe"], dtype=np.float64)
        df = float(np.linalg.norm(corners[:4].mean(axis=0) - cam))
        dr = float(np.linalg.norm(corners[4:].mean(axis=0) - cam))
        return bool(df < dr), df, dr
    except Exception:
        return None, None, None


def seg_intersects(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray) -> bool:
    def ccw(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    if len({tuple(p1), tuple(p2), tuple(p3), tuple(p4)}) < 4:
        return False
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def connector_crossings(pc: np.ndarray | None) -> int | None:
    if pc is None or pc.shape[0] < 8:
        return None
    segs = [(pc[a, :2], pc[b, :2]) for a, b in CONN_EDGES]
    n = 0
    for i in range(4):
        for j in range(i + 1, 4):
            if seg_intersects(segs[i][0], segs[i][1], segs[j][0], segs[j][1]):
                n += 1
    return n


def in_image_count(pc: np.ndarray | None, width: Any, height: Any) -> int | None:
    if pc is None:
        return None
    try:
        w = float(width)
        h = float(height)
    except Exception:
        return None
    pts = pc[:, :2]
    ok = (pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)
    return int(ok.sum())


def load_font(size: int = 14) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT = load_font(14)
SMALL_FONT = load_font(11)


def draw_overlay(base: Image.Image | None, lab: dict[str, Any] | None, obj: dict[str, Any] | None, idx: int, row: dict[str, Any], out_path: Path) -> None:
    if base is None:
        base = Image.new("RGB", (640, 480), (35, 35, 35))
    im = base.copy().convert("RGB")
    dr = ImageDraw.Draw(im)
    ok, pc = finite_point_list(obj.get("projected_cuboid") if obj else None, expected=8)
    cc_ok, cc = finite_point_list([obj.get("projected_cuboid_centroid")] if obj else None, expected=1)
    if ok and pc is not None:
        def line(edge: tuple[int, int], color: tuple[int, int, int], width: int) -> None:
            a, b = edge
            dr.line([tuple(pc[a, :2]), tuple(pc[b, :2])], fill=color, width=width)

        for e in REAR_EDGES:
            line(e, (60, 120, 255), 2)
        for e in CONN_EDGES:
            line(e, (255, 210, 0), 2)
        for e in FRONT_EDGES:
            line(e, (255, 30, 30), 4)
        for k, (x, y) in enumerate(pc[:, :2]):
            color = (255, 30, 30) if k < 4 else (60, 120, 255)
            dr.ellipse([x - 5, y - 5, x + 5, y + 5], fill=color, outline=(255, 255, 255))
            dr.text((x + 6, y - 6), str(k), fill=(255, 255, 0), font=SMALL_FONT)
    if cc_ok and cc is not None:
        x, y = cc[0, :2]
        dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 255, 0))
    header = f"f{idx:04d} mode={row.get('mode') or ''} audit={row.get('audit_pass')} gate={row.get('all_pass_gate')} fail={row.get('failure_count')}"
    dr.rectangle([0, 0, im.width, 20], fill=(0, 0, 0))
    dr.text((4, 3), header, fill=(255, 255, 255), font=SMALL_FONT)
    if row.get("failures"):
        dr.rectangle([0, im.height - 20, im.width, im.height], fill=(0, 0, 0))
        dr.text((4, im.height - 17), str(row.get("failures"))[:140], fill=(255, 210, 0), font=SMALL_FONT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)


def csv_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
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


def fatal_failure_reasons(row: dict[str, Any], mask_names: list[str]) -> list[str]:
    """Return frame defects that make a normal audit command fail."""
    reasons: list[str] = []
    artifacts_required = row.get("artifacts_required") is not False
    if not row.get("rgb_present"):
        if artifacts_required:
            reasons.append("missing_rgb")
    elif not row.get("rgb_decode_ok"):
        reasons.append("corrupt_rgb")
    for name in mask_names:
        if not row.get(f"mask_{name}_present"):
            if artifacts_required and "missing_mask" not in reasons:
                reasons.append("missing_mask")
        elif not row.get(f"mask_{name}_decode_ok"):
            if "corrupt_mask" not in reasons:
                reasons.append("corrupt_mask")
    if row.get("mask_monotonic_ok") is False:
        reasons.append("mask_nonmonotonic")
    if row.get("mask_pixel_inclusion_ok") is False:
        reasons.append("mask_pixel_inclusion")
    if row.get("mask_shape_consistent") is False:
        reasons.append("mask_shape_inconsistent")
    if row.get("mask_rgb_shape_match") is False:
        reasons.append("mask_rgb_shape_mismatch")
    if row.get("mask_cross_frame_duplicate_class") and "stale_or_mismatched_mask" in str(
        row.get("mask_cross_frame_duplicate_class")
    ):
        reasons.append("mask_stale_cross_frame_duplicate")
    if artifacts_required and int(row.get("required_label_missing_count") or 0) > 0:
        reasons.append("required_label_missing")
    if row.get("magenta_fail"):
        reasons.append("magenta")

    accepted = row.get("accepted_frame") is True
    if accepted and int(row.get("exact_collision_count") or 0) > 0:
        reasons.append("accepted_exact_collision")
    if accepted:
        camera_clearance = row.get("camera_clearance_pass")
        if camera_clearance is False:
            reasons.append("camera_clearance_fail")
        elif camera_clearance is None:
            reasons.append("camera_clearance_unknown")
    if row.get("support_required"):
        support = row.get("support_pass")
        if support is False:
            reasons.append("support_fail")
        elif support is None:
            reasons.append("support_unknown")
    return reasons


def evaluate_frame(
    root: Path,
    idx: int,
    rec: dict[str, Any] | None,
    mask_names: list[str],
    target_mask: str,
    duplicate_record_indices: set[int],
    duplicate_hashes: set[str],
    duplicate_filenames: set[str],
    magenta_threshold: float,
    hull_outside_warn_ratio: float = DEFAULT_HULL_OUTSIDE_WARN_RATIO,
) -> tuple[dict[str, Any], Image.Image | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, dict[str, Any]]]:
    frame = f"f{idx:04d}"
    lab, obj, v2 = load_label(root, idx)
    rgb_path = root / "rgb" / f"{frame}_rgb.png"
    rgb_img, rgb = strict_open_rgb(rgb_path)
    rgb_hash = sha256_file(rgb_path)
    ok2d, pc = finite_point_list(obj.get("projected_cuboid") if obj else None, expected=8)
    front_near, front_dist, rear_dist = front_is_near(lab, obj)
    crosses = connector_crossings(pc)
    cam = lab.get("camera_data") if isinstance(lab, dict) and isinstance(lab.get("camera_data"), dict) else {}
    width = rgb.get("width") or cam.get("width")
    height = rgb.get("height") or cam.get("height")
    in_count = in_image_count(pc, width, height)
    masks = {name: strict_decode_mask(root / "mask" / f"{frame}_{name}.png") for name in mask_names}
    areas = [masks[name]["area"] for name in mask_names if masks[name]["decode_ok"]]
    mask_monotonic_ok = None
    if len(areas) == len(mask_names):
        mask_monotonic_ok = all(areas[i] >= areas[i + 1] for i in range(len(areas) - 1))
    target = masks.get(target_mask)
    empty_target = None
    if target is not None and target["decode_ok"]:
        empty_target = (target["area"] == 0)

    rec_map = rec or {}
    diagnostic_mode = first_value(rec_map.get("diagnostic_mode"), rec_map.get("mode"), rec_map.get("scene_mode"), nested(v2, ["diagnostic_mode"]))
    mode = first_value(diagnostic_mode, rec_map.get("scene_preset"), cam.get("scene_preset"), nested(v2, ["scene_preset"]), "(missing)")
    rendered = bool_value(rec_map.get("rendered"))
    realize_ok = bool_value(rec_map.get("realize_ok"))
    reject_reason = rec_map.get("reject_reason")
    artifacts_required = not (
        realize_ok is False
        and reject_reason is not None
        and bool(str(reject_reason).strip())
    )
    gates = obj.get("safety_gates") if isinstance(obj, dict) else {}
    all_pass_gate = bool_value(gates.get("all_pass")) if isinstance(gates, dict) else None
    if all_pass_gate is None and rec:
        all_pass_gate = bool_value(rec.get("all_pass"))

    required_label_missing = []
    if artifacts_required:
        if lab is None:
            required_label_missing.append("label")
        if obj is None:
            required_label_missing.append("object")
        if not ok2d:
            required_label_missing.append("projected_cuboid")
        if front_near is None:
            required_label_missing.append("cuboid_or_camera_location")
        if width is None or height is None:
            required_label_missing.append("image_size")
        if all_pass_gate is None:
            required_label_missing.append("safety_gates.all_pass")
    exact_collision_count = int_value(first_value(rec_map.get("exact_collision_count"), nested(v2, ["exact_collision_count"])))
    pallet_obstacle_collision_count = int_value(first_value(rec_map.get("pallet_obstacle_collision_count"), nested(v2, ["pallet_obstacle_collision_count"])))
    cargo_collision_count = int_value(first_value(rec_map.get("cargo_collision_count"), nested(v2, ["cargo_collision_count"])))
    context_context_collision_count = int_value(first_value(rec_map.get("context_context_collision_count"), nested(v2, ["context_context_collision_count"])))
    camera_clearance_pass = bool_value(first_value(rec_map.get("camera_clearance_pass"), nested(v2, ["camera_clearance_pass"])))
    support_pass = bool_value(first_value(rec_map.get("support_pass"), nested(v2, ["support_pass"])))
    ground_continuity_pass = bool_value(
        first_value(rec_map.get("ground_continuity_pass"), nested(v2, ["ground_continuity_pass"]))
    )
    ground_probe_count = int_value(
        first_value(rec_map.get("ground_probe_count"), nested(v2, ["ground_probe_count"]))
    )
    ground_probe_fail_count = int_value(
        first_value(rec_map.get("ground_probe_fail_count"), nested(v2, ["ground_probe_fail_count"]))
    )
    ground_probe_max_step_m = first_value(
        rec_map.get("ground_probe_max_step_m"), nested(v2, ["ground_probe_max_step_m"])
    )
    procedural_floor_edge_risk = bool_value(
        first_value(
            rec_map.get("procedural_floor_edge_risk"),
            nested(v2, ["procedural_floor_edge_risk"]),
        )
    )
    procedural_floor_edge_margin_m = first_value(
        rec_map.get("procedural_floor_edge_margin_m"),
        nested(v2, ["procedural_floor_edge_margin_m"]),
    )
    ground_continuity_reason = first_value(
        rec_map.get("ground_continuity_reason"), nested(v2, ["ground_continuity_reason"])
    )
    accepted_frame = (rendered is True and realize_ok is not False) or (
        rendered is None and realize_ok is True
    )
    support_required = accepted_frame
    anchor_reject_reason = first_value(rec_map.get("anchor_reject_reason"), nested(v2, ["anchor_reject_reason"]))
    file_count_mismatch = artifacts_required and (
        (lab is None)
        or (not rgb["present"])
        or any(not masks[name]["present"] for name in mask_names)
    )

    # --- Phase 5: pixel-level mask integrity (scalar areas alone cannot see these) ---
    inclusion = mask_pixel_inclusion(masks, mask_names)
    # Missing files are reported by missing_mask_* and are legitimate for rejected proposals; this
    # column is only about whether the files that DO exist survive a strict decode.
    present_masks = [name for name in mask_names if masks[name]["present"]]
    strict_decode_ok = all(masks[name]["decode_ok"] for name in present_masks) if present_masks else None
    empty_stages = [name for name in mask_names if masks[name].get("all_black") is True]
    occluder_states = occluder_source_states(rec_map, v2)
    within_dupes = within_frame_mask_duplicates(masks, mask_names, occluder_states)
    mask_sizes = {
        (masks[name]["width"], masks[name]["height"])
        for name in mask_names
        if masks[name]["decode_ok"]
    }
    rgb_shape_match = None
    if mask_sizes and rgb["decode_ok"]:
        rgb_shape_match = mask_sizes == {(rgb["width"], rgb["height"])}
    hull = convex_hull_points(pc[:, :2]) if (ok2d and pc is not None) else None
    hull_align: dict[str, dict[str, Any]] = {}
    for slot, name in (("m0", mask_names[0] if mask_names else None), ("m4", mask_names[-1] if mask_names else None)):
        if name is None:
            hull_align[slot] = {"bbox_iou": None, "outside_ratio": None, "reason": "no_mask_names"}
            continue
        hull_align[slot] = hull_alignment(masks[name].get("fg"), hull, width, height)
    hull_ratios = [
        hull_align[slot]["outside_ratio"]
        for slot in ("m0", "m4")
        if hull_align[slot].get("outside_ratio") is not None
    ]
    hull_warn = (max(hull_ratios) > hull_outside_warn_ratio) if hull_ratios else None
    hull_reason = ";".join(
        f"{slot}:{hull_align[slot]['reason']}"
        for slot in ("m0", "m4")
        if hull_align[slot].get("reason")
    )

    row = {
        "idx": idx,
        "frame_id": frame,
        "mode": mode,
        "diagnostic_mode": diagnostic_mode,
        "record_present": bool(rec),
        "label_present": lab is not None,
        "rgb_present": rgb["present"],
        "rgb_decode_ok": rgb["decode_ok"],
        "rgb_decode_error": rgb["decode_error"],
        "rgb_sha256": rgb_hash,
        "duplicate_filename": f"{frame}_rgb.png" in duplicate_filenames or f"{frame}_label.json" in duplicate_filenames,
        "duplicate_rgb_hash": bool(rgb_hash and rgb_hash in duplicate_hashes),
        "duplicate_record_index": idx in duplicate_record_indices,
        "required_label_missing_count": len(required_label_missing),
        "required_label_missing": ";".join(required_label_missing),
        "file_count_mismatch": file_count_mismatch,
        "artifacts_required": artifacts_required,
        "accepted_frame": accepted_frame,
        "exact_collision_count": exact_collision_count,
        "pallet_obstacle_collision_count": pallet_obstacle_collision_count,
        "cargo_collision_count": cargo_collision_count,
        "context_context_collision_count": context_context_collision_count,
        "camera_clearance_pass": camera_clearance_pass,
        "support_required": support_required,
        "support_pass": support_pass,
        "ground_continuity_pass": ground_continuity_pass,
        "ground_probe_count": ground_probe_count,
        "ground_probe_fail_count": ground_probe_fail_count,
        "ground_probe_max_step_m": ground_probe_max_step_m,
        "procedural_floor_edge_risk": procedural_floor_edge_risk,
        "procedural_floor_edge_margin_m": procedural_floor_edge_margin_m,
        "ground_continuity_reason": ground_continuity_reason,
        "anchor_reject_reason": anchor_reject_reason,
        "reject_reason": reject_reason,
        "front_near": front_near,
        "front_dist": front_dist,
        "rear_dist": rear_dist,
        "connector_crossings": crosses,
        "points_2d_finite": ok2d,
        "points_2d_in_image_count": in_count,
        "mask_monotonic_ok": mask_monotonic_ok,
        "empty_target_mask": empty_target,
        "mask_strict_decode_ok": strict_decode_ok,
        "mask_shape_consistent": inclusion["shape_consistent"],
        "mask_rgb_shape_match": rgb_shape_match,
        "mask_pixel_inclusion_ok": inclusion["ok"],
        "mask_pixel_inclusion_violation_px": inclusion["violation_px_total"] if inclusion["checked"] else None,
        "mask_pixel_inclusion_violations": ";".join(
            f"{p['inner']}!<={p['outer']}:" + ("shape" if p["shape_mismatch"] else str(p["violation_px"]))
            for p in inclusion["pairs"]
            if p["shape_mismatch"] or (p["violation_px"] or 0) > 0
        ),
        "mask_empty_stages": ";".join(empty_stages),
        "mask_within_frame_duplicate_groups": ";".join("+".join(g["stages"]) for g in within_dupes),
        "mask_within_frame_duplicate_class": ";".join(sorted({g["classification"] for g in within_dupes})),
        "mask_cross_frame_duplicate_stages": "",
        "mask_cross_frame_duplicate_class": "",
        "mask_m0_hull_bbox_iou": hull_align["m0"].get("bbox_iou"),
        "mask_m0_hull_outside_ratio": hull_align["m0"].get("outside_ratio"),
        "mask_m4_hull_bbox_iou": hull_align["m4"].get("bbox_iou"),
        "mask_m4_hull_outside_ratio": hull_align["m4"].get("outside_ratio"),
        "mask_hull_align_warn": hull_warn,
        "mask_hull_align_reason": hull_reason,
        "magenta_ratio": rgb["magenta_ratio"],
        "magenta_fail": (rgb["magenta_ratio"] is not None and rgb["magenta_ratio"] > magenta_threshold),
        "all_pass_gate": all_pass_gate,
    }
    for name in mask_names:
        ms = masks[name]
        row[f"mask_{name}_present"] = ms["present"]
        row[f"mask_{name}_decode_ok"] = ms["decode_ok"]
        row[f"mask_{name}_area"] = ms["area"]
        row[f"mask_{name}_error"] = ms["error"]
        row[f"mask_{name}_sha256"] = ms["sha256"]
        row[f"mask_{name}_content_sha256"] = ms["content_sha256"]
        row[f"mask_{name}_width"] = ms["width"]
        row[f"mask_{name}_height"] = ms["height"]
    row["_mask_inclusion"] = inclusion
    row["_mask_within_frame_duplicates"] = within_dupes
    row["_mask_occluder_states"] = occluder_states
    row["_mask_hull_align"] = hull_align

    failures = []
    if not rec:
        failures.append("missing_record")
    if lab is None:
        if artifacts_required:
            failures.append("missing_label")
    if not rgb["present"]:
        if artifacts_required:
            failures.append("missing_rgb")
    elif not rgb["decode_ok"]:
        failures.append("corrupt_rgb")
    if row["duplicate_rgb_hash"]:
        failures.append("duplicate_rgb_hash")
    if row["duplicate_filename"]:
        failures.append("duplicate_filename")
    if row["duplicate_record_index"]:
        failures.append("duplicate_record_index")
    if required_label_missing:
        failures.append("required_label_missing")
    if file_count_mismatch:
        failures.append("file_count_mismatch")
    if exact_collision_count is not None and exact_collision_count > 0:
        failures.append("exact_collision")
    if pallet_obstacle_collision_count is not None and pallet_obstacle_collision_count > 0:
        failures.append("pallet_obstacle_collision")
    if cargo_collision_count is not None and cargo_collision_count > 0:
        failures.append("cargo_collision")
    if context_context_collision_count is not None and context_context_collision_count > 0:
        failures.append("context_context_collision")
    if accepted_frame and camera_clearance_pass is False:
        failures.append("camera_clearance_fail")
    elif accepted_frame and camera_clearance_pass is None:
        failures.append("camera_clearance_unknown")
    if support_pass is False:
        failures.append("support_fail")
    elif support_required and support_pass is None:
        failures.append("support_unknown")
    # Ground continuity is reported only by post-Phase-2 runs; older datasets leave it None
    # and must not be retro-failed, so only an explicit False counts.
    if ground_continuity_pass is False:
        failures.append("ground_continuity_fail")
    if procedural_floor_edge_risk is True:
        failures.append("procedural_floor_edge_risk")
    if anchor_reject_reason and str(anchor_reject_reason).lower() not in {"accepted", "none", "ok"}:
        failures.append("anchor_reject")
    if front_near is False:
        failures.append("front_not_near")
    if artifacts_required and front_near is None:
        failures.append("front_near_unknown")
    if crosses is None:
        if artifacts_required:
            failures.append("connector_crossing_unknown")
    elif crosses > 0:
        failures.append("connector_crossing")
    if artifacts_required and not ok2d:
        failures.append("nonfinite_or_missing_2d")
    if mask_monotonic_ok is False:
        failures.append("mask_nonmonotonic")
    if artifacts_required and mask_monotonic_ok is None:
        failures.append("mask_monotonic_unknown")
    if empty_target is True:
        failures.append("empty_target_mask")
    if artifacts_required and empty_target is None:
        failures.append("empty_target_unknown")
    if row["magenta_fail"]:
        failures.append("magenta")
    for name in mask_names:
        if not masks[name]["present"]:
            if artifacts_required:
                failures.append(f"missing_mask_{name}")
        elif not masks[name]["decode_ok"]:
            failures.append(f"corrupt_mask_{name}")
    if inclusion["ok"] is False:
        failures.append("mask_pixel_inclusion")
    if inclusion["shape_consistent"] is False:
        failures.append("mask_shape_inconsistent")
    if rgb_shape_match is False:
        failures.append("mask_rgb_shape_mismatch")
    if any(g["classification"] == "unexpected_identical_stage" for g in within_dupes):
        failures.append("mask_within_frame_duplicate_unexpected")
    fatal_failures = fatal_failure_reasons(row, mask_names)
    row["fatal_pass"] = len(fatal_failures) == 0
    row["fatal_failure_count"] = len(fatal_failures)
    row["fatal_failures"] = ";".join(fatal_failures)
    row["failure_count"] = len(failures)
    row["failures"] = ";".join(failures)
    row["audit_pass"] = len(failures) == 0
    # Boolean foreground planes are only needed for the per-frame checks above; dropping them
    # keeps peak memory at the pre-Phase-5 level for 400+ frame datasets.
    for name in mask_names:
        masks[name]["fg"] = None
    return row, rgb_img, lab, obj, masks


def ground_continuity_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """N-frame ground-continuity roll-up: pass rate, failure indices, floor-edge headroom."""
    measured = [r for r in rows if r.get("ground_continuity_pass") is not None]
    passed = [r for r in measured if r.get("ground_continuity_pass") is True]
    margins = [
        float(r["procedural_floor_edge_margin_m"])
        for r in rows
        if r.get("procedural_floor_edge_margin_m") is not None
    ]
    reason_counter: Counter[str] = Counter()
    for r in measured:
        reason = r.get("ground_continuity_reason")
        if reason:
            for token in str(reason).split(";"):
                reason_counter[token] += 1
    return {
        "measured_frame_count": len(measured),
        "unmeasured_frame_count": len(rows) - len(measured),
        "pass_count": len(passed),
        "fail_count": len(measured) - len(passed),
        "pass_rate": (len(passed) / len(measured)) if measured else None,
        "fail_indices": [
            r["idx"] for r in measured if r.get("ground_continuity_pass") is False
        ],
        "probe_fail_total": sum(
            int(r.get("ground_probe_fail_count") or 0) for r in measured
        ),
        "max_probe_step_m": max(
            (
                float(r["ground_probe_max_step_m"])
                for r in rows
                if r.get("ground_probe_max_step_m") is not None
            ),
            default=None,
        ),
        "floor_edge_risk_indices": [
            r["idx"] for r in rows if r.get("procedural_floor_edge_risk") is True
        ],
        "min_floor_edge_margin_m": min(margins) if margins else None,
        "reason_counts": dict(reason_counter.most_common()),
    }


def collect_hash_duplicates(root: Path) -> set[str]:
    hashes = []
    for path in (root / "rgb").glob("f*_rgb.png"):
        h = sha256_file(path)
        if h:
            hashes.append(h)
    c = Counter(hashes)
    return {h for h, n in c.items() if n > 1}


def geometry_signature(root: Path, idx: int) -> dict[str, Any]:
    """Camera/K/pose fingerprint used to separate a stale mask from a genuinely identical scene."""
    lab, obj, _ = load_label(root, idx)
    cam = lab.get("camera_data") if isinstance(lab, dict) else None
    cam = cam if isinstance(cam, dict) else {}
    obj = obj if isinstance(obj, dict) else {}
    intr = cam.get("intrinsics") if isinstance(cam.get("intrinsics"), dict) else {}
    return {
        "K": [intr.get(k) for k in ("fx", "fy", "cx", "cy")],
        "resolution": [cam.get("width"), cam.get("height")],
        "camera_location_worldframe": cam.get("location_worldframe"),
        "camera_look_worldframe": cam.get("look_worldframe"),
        "pose_transform": obj.get("pose_transform"),
        "projected_cuboid": obj.get("projected_cuboid"),
        "target_asset": first_value(obj.get("source_asset"), obj.get("name")),
        "label_present": lab is not None,
    }


GEOMETRY_SIGNATURE_FIELDS = (
    "K",
    "resolution",
    "camera_location_worldframe",
    "camera_look_worldframe",
    "pose_transform",
    "projected_cuboid",
    "target_asset",
)


def compare_geometry_signatures(signatures: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-check geometry for frames whose mask bytes are identical."""
    if len(signatures) < 2:
        return {"geometry_identical": None, "differing_fields": [], "comparable": False}
    if any(not s.get("label_present") for s in signatures):
        return {"geometry_identical": None, "differing_fields": [], "comparable": False}
    differing = []
    for field in GEOMETRY_SIGNATURE_FIELDS:
        ref = json.dumps(signatures[0].get(field), sort_keys=True, default=str)
        if any(json.dumps(s.get(field), sort_keys=True, default=str) != ref for s in signatures[1:]):
            differing.append(field)
    return {"geometry_identical": not differing, "differing_fields": differing, "comparable": True}


def cross_frame_mask_duplicates(
    root: Path,
    rows: list[dict[str, Any]],
    mask_names: list[str],
    target_mask: str,
) -> list[dict[str, Any]]:
    """Same stage, different frames, same mask.

    Grouped on the foreground content hash (byte-exact duplicates are a subset, flagged by
    `byte_identical`). Classification rules:
      - all-black target-stage duplicate            -> empty_target_defect
      - all-black non-target stage duplicate        -> all_black_stage_duplicate (fully occluded)
      - non-black + geometry differs across frames  -> stale_or_mismatched_mask (real defect)
      - non-black + geometry identical              -> duplicate_with_identical_geometry
    """
    # All-black masks are grouped by CONTENT, not by bytes: sub-threshold anti-aliased pixels and
    # differing resolutions give every empty mask its own SHA256, so byte grouping would silently
    # miss the empty-target case this check exists for. [확인: 500-frame run, 3 empty 960x540 M0
    # masks with 3 different hashes]
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for name in mask_names:
            digest = row.get(f"mask_{name}_content_sha256")
            if not (row.get(f"mask_{name}_decode_ok") and digest):
                continue
            key = "__all_black__" if row.get(f"mask_{name}_area") == 0 else str(digest)
            buckets[(name, key)].append(row)
    groups: list[dict[str, Any]] = []
    signature_cache: dict[int, dict[str, Any]] = {}
    for (name, key), member_rows in buckets.items():
        if len(member_rows) < 2:
            continue
        member_rows = sorted(member_rows, key=lambda r: int(r["idx"]))
        indices = [int(r["idx"]) for r in member_rows]
        area = member_rows[0].get(f"mask_{name}_area")
        all_black = key == "__all_black__"
        byte_hashes = [str(r.get(f"mask_{name}_sha256")) for r in member_rows]
        byte_identical = len(set(byte_hashes)) == 1
        for idx in indices:
            if idx not in signature_cache:
                signature_cache[idx] = geometry_signature(root, idx)
        cross = compare_geometry_signatures([signature_cache[i] for i in indices])
        if all_black:
            classification = "empty_target_defect" if name == target_mask else "all_black_stage_duplicate"
        elif cross["geometry_identical"] is False:
            classification = "stale_or_mismatched_mask"
        elif cross["geometry_identical"] is True:
            classification = "duplicate_with_identical_geometry"
        else:
            classification = "duplicate_geometry_unverifiable"
        rgb_hashes = {r.get("rgb_sha256") for r in member_rows}
        groups.append(
            {
                "stage": name,
                "group_key": key,
                "grouped_by": "content_all_black" if all_black else "content_sha256",
                "content_sha256": None if all_black else key,
                "byte_identical": byte_identical,
                "sha256": byte_hashes,
                "frame_count": len(indices),
                "indices": indices,
                "area": area,
                "all_black": all_black,
                "classification": classification,
                "geometry_cross_check": cross,
                "rgb_sha256_identical": len(rgb_hashes) == 1 and None not in rgb_hashes,
                "diagnostic_modes": sorted({str(r.get("diagnostic_mode") or r.get("mode") or "") for r in member_rows}),
            }
        )
    groups.sort(key=lambda g: (mask_names.index(g["stage"]), g["indices"][0]))
    return groups


CROSS_FRAME_DUPLICATE_FAILURES = {
    "stale_or_mismatched_mask": "mask_stale_cross_frame_duplicate",
    "duplicate_geometry_unverifiable": "mask_duplicate_geometry_unverifiable",
}


def apply_mask_duplicate_findings(
    rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    mask_names: list[str],
) -> None:
    """Fold the cross-frame verdicts back into the per-frame failure columns."""
    by_idx = {int(r["idx"]): r for r in rows}
    stages: dict[int, list[str]] = defaultdict(list)
    classes: dict[int, set[str]] = defaultdict(set)
    for group in groups:
        for idx in group["indices"]:
            stages[idx].append(group["stage"])
            classes[idx].add(group["classification"])
    for idx, row in by_idx.items():
        row["mask_cross_frame_duplicate_stages"] = ";".join(stages.get(idx, []))
        row["mask_cross_frame_duplicate_class"] = ";".join(sorted(classes.get(idx, set())))
        extra = [
            CROSS_FRAME_DUPLICATE_FAILURES[c]
            for c in sorted(classes.get(idx, set()))
            if c in CROSS_FRAME_DUPLICATE_FAILURES
        ]
        if not extra:
            continue
        failures = [f for f in str(row.get("failures") or "").split(";") if f]
        for token in extra:
            if token not in failures:
                failures.append(token)
        row["failures"] = ";".join(failures)
        row["failure_count"] = len(failures)
        row["audit_pass"] = len(failures) == 0
        fatal = fatal_failure_reasons(row, mask_names)
        row["fatal_pass"] = len(fatal) == 0
        row["fatal_failure_count"] = len(fatal)
        row["fatal_failures"] = ";".join(fatal)


MASK_HASH_COLUMNS = [
    "idx",
    "frame_id",
    "diagnostic_mode",
    "stage",
    "path",
    "present",
    "decode_ok",
    "decode_error",
    "sha256",
    "content_sha256",
    "width",
    "height",
    "area",
    "all_black",
    "rgb_sha256",
    "within_frame_duplicate_group",
    "cross_frame_duplicate_frame_count",
    "cross_frame_duplicate_class",
]

MASK_INCLUSION_FAILURE_COLUMNS = [
    "idx",
    "frame_id",
    "diagnostic_mode",
    "outer_stage",
    "inner_stage",
    "outer_area",
    "inner_area",
    "violation_px",
    "violation_ratio",
    "shape_mismatch",
    "reason",
]


def build_mask_hash_rows(
    root: Path,
    rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    mask_names: list[str],
) -> list[dict[str, Any]]:
    group_by_key: dict[tuple[str, str], dict[str, Any]] = {(g["stage"], g["group_key"]): g for g in groups}
    out: list[dict[str, Any]] = []
    for row in rows:
        idx = int(row["idx"])
        frame = f"f{idx:04d}"
        within = {}
        for group in row.get("_mask_within_frame_duplicates") or []:
            for stage in group["stages"]:
                within[stage] = "+".join(group["stages"]) + f" [{group['classification']}]"
        for name in mask_names:
            digest = row.get(f"mask_{name}_sha256")
            content = row.get(f"mask_{name}_content_sha256")
            area = row.get(f"mask_{name}_area")
            key = "__all_black__" if area == 0 else str(content)
            cross = group_by_key.get((name, key)) if content else None
            out.append(
                {
                    "idx": idx,
                    "frame_id": frame,
                    "diagnostic_mode": row.get("diagnostic_mode") or row.get("mode"),
                    "stage": name,
                    "path": str(Path("mask") / f"{frame}_{name}.png"),
                    "present": row.get(f"mask_{name}_present"),
                    "decode_ok": row.get(f"mask_{name}_decode_ok"),
                    "decode_error": row.get(f"mask_{name}_error"),
                    "sha256": digest,
                    "content_sha256": content,
                    "width": row.get(f"mask_{name}_width"),
                    "height": row.get(f"mask_{name}_height"),
                    "area": area,
                    "all_black": (area == 0) if area is not None else None,
                    "rgb_sha256": row.get("rgb_sha256"),
                    "within_frame_duplicate_group": within.get(name, ""),
                    "cross_frame_duplicate_frame_count": cross["frame_count"] if cross else "",
                    "cross_frame_duplicate_class": cross["classification"] if cross else "",
                }
            )
    return out


def build_mask_inclusion_failure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        inclusion = row.get("_mask_inclusion") or {}
        for pair in inclusion.get("pairs", []):
            if not pair["shape_mismatch"] and not (pair.get("violation_px") or 0) > 0:
                continue
            out.append(
                {
                    "idx": int(row["idx"]),
                    "frame_id": row.get("frame_id"),
                    "diagnostic_mode": row.get("diagnostic_mode") or row.get("mode"),
                    "outer_stage": pair["outer"],
                    "inner_stage": pair["inner"],
                    "outer_area": pair["outer_area"],
                    "inner_area": pair["inner_area"],
                    "violation_px": pair.get("violation_px"),
                    "violation_ratio": pair.get("violation_ratio"),
                    "shape_mismatch": pair["shape_mismatch"],
                    "reason": pair.get("reason") or inclusion.get("reason") or "",
                }
            )
    return out


def mask_integrity_summary(
    rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    inclusion_failures: list[dict[str, Any]],
    mask_names: list[str],
    hull_outside_warn_ratio: float,
) -> dict[str, Any]:
    within_class = Counter()
    for row in rows:
        for group in row.get("_mask_within_frame_duplicates") or []:
            within_class[group["classification"]] += 1
    cross_class = Counter(g["classification"] for g in groups)
    hull_ratios = [
        float(row[key])
        for row in rows
        for key in ("mask_m0_hull_outside_ratio", "mask_m4_hull_outside_ratio")
        if row.get(key) is not None
    ]
    ious = [
        float(row["mask_m0_hull_bbox_iou"])
        for row in rows
        if row.get("mask_m0_hull_bbox_iou") is not None
    ]
    return {
        "mask_names": mask_names,
        "frame_count": len(rows),
        "mask_file_count": len(rows) * len(mask_names),
        "strict_decode_fail_indices": [r["idx"] for r in rows if r.get("mask_strict_decode_ok") is False],
        "pixel_inclusion_checked_count": sum(1 for r in rows if r.get("mask_pixel_inclusion_ok") is not None),
        "pixel_inclusion_fail_indices": sorted({int(r["idx"]) for r in inclusion_failures}),
        "pixel_inclusion_failure_pair_count": len(inclusion_failures),
        "pixel_inclusion_violation_px_total": int(
            sum(int(r.get("violation_px") or 0) for r in inclusion_failures)
        ),
        "shape_inconsistent_indices": [r["idx"] for r in rows if r.get("mask_shape_consistent") is False],
        "rgb_shape_mismatch_indices": [r["idx"] for r in rows if r.get("mask_rgb_shape_match") is False],
        "empty_stage_frame_count": sum(1 for r in rows if r.get("mask_empty_stages")),
        "empty_target_mask_indices": [r["idx"] for r in rows if r.get("empty_target_mask") is True],
        "within_frame_duplicate_frame_count": sum(
            1 for r in rows if r.get("_mask_within_frame_duplicates")
        ),
        "within_frame_duplicate_class_counts": dict(within_class.most_common()),
        "within_frame_byte_exact_group_count": sum(
            1
            for row in rows
            for group in (row.get("_mask_within_frame_duplicates") or [])
            if group.get("byte_identical")
        ),
        "cross_frame_duplicate_group_count": len(groups),
        "cross_frame_byte_exact_group_count": sum(1 for g in groups if g.get("byte_identical")),
        "cross_frame_duplicate_class_counts": dict(cross_class.most_common()),
        "cross_frame_stale_indices": sorted(
            {i for g in groups if g["classification"] == "stale_or_mismatched_mask" for i in g["indices"]}
        ),
        "cross_frame_empty_target_indices": sorted(
            {i for g in groups if g["classification"] == "empty_target_defect" for i in g["indices"]}
        ),
        "hull_outside_warn_ratio": hull_outside_warn_ratio,
        "hull_align_warn_indices": [r["idx"] for r in rows if r.get("mask_hull_align_warn") is True],
        "hull_outside_ratio_max": max(hull_ratios) if hull_ratios else None,
        "hull_outside_ratio_median": float(np.median(hull_ratios)) if hull_ratios else None,
        "hull_bbox_iou_median_m0": float(np.median(ious)) if ious else None,
        "hull_metric_unavailable_count": sum(1 for r in rows if r.get("mask_hull_align_reason")),
    }


def mask_integrity_sheet_rows(rows: list[dict[str, Any]], max_frames: int) -> list[dict[str, Any]]:
    """Defective frames first, then a sample of clean ones so the sheet is interpretable."""
    def rank(row: dict[str, Any]) -> int:
        if row.get("mask_pixel_inclusion_ok") is False or row.get("mask_shape_consistent") is False:
            return 0
        if row.get("mask_cross_frame_duplicate_class"):
            return 1
        if row.get("empty_target_mask") is True or row.get("mask_empty_stages"):
            return 2
        if row.get("mask_hull_align_warn") is True:
            return 3
        if row.get("mask_within_frame_duplicate_class") == "unexpected_identical_stage":
            return 4
        return 5

    ordered = sorted(rows, key=lambda r: (rank(r), int(r["idx"])))
    return ordered[:max_frames]


def make_mask_integrity_sheet(
    root: Path,
    rows: list[dict[str, Any]],
    masks_cache: dict[int, dict[str, dict[str, Any]]],
    out_path: Path,
    mask_names: list[str],
    max_frames: int,
) -> int:
    """Source-mask contact sheet annotated with the Phase 5 verdicts (rgb + M0..M4 per row)."""
    selected = rows[:max_frames]
    thumb = (128, 96)
    label_w = 150
    row_h = thumb[1] + 34
    width = label_w + (1 + len(mask_names)) * thumb[0]
    if not selected:
        sheet = Image.new("RGB", (max(900, width), 220), (30, 30, 30))
        dr = ImageDraw.Draw(sheet)
        dr.text((12, 12), "Mask Integrity Source Masks", fill=(255, 255, 255), font=FONT)
        dr.text((12, 80), "No frames available", fill=(255, 210, 0), font=FONT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path)
        return 0
    sheet = Image.new("RGB", (width, 30 + len(selected) * row_h), (18, 18, 18))
    dr = ImageDraw.Draw(sheet)
    dr.text((8, 6), "Mask Integrity Source Masks (rgb + M0..M4, sha8/area/verdict)", fill=(255, 255, 255), font=FONT)
    for r_i, row in enumerate(selected):
        idx = int(row["idx"])
        y = 30 + r_i * row_h
        verdict = "ok"
        color = (140, 255, 140)
        cross_classes = str(row.get("mask_cross_frame_duplicate_class") or "").split(";")
        if row.get("mask_pixel_inclusion_ok") is False or row.get("mask_shape_consistent") is False:
            verdict, color = "inclusion", (255, 90, 90)
        elif "stale_or_mismatched_mask" in cross_classes:
            verdict, color = "stale dup", (255, 90, 90)
        elif row.get("empty_target_mask") is True:
            verdict, color = "empty M0", (255, 90, 90)
        elif any(cross_classes) and cross_classes != [""]:
            verdict, color = sorted(c for c in cross_classes if c)[0][:16], (255, 150, 60)
        elif row.get("mask_hull_align_warn") is True:
            verdict, color = "hull warn", (255, 210, 0)
        dr.text((6, y + 4), f"f{idx:04d}", fill=(255, 255, 0), font=SMALL_FONT)
        dr.text((6, y + 18), str(row.get("diagnostic_mode") or row.get("mode") or "")[:20], fill=(180, 180, 180), font=SMALL_FONT)
        dr.text((6, y + 32), verdict, fill=color, font=SMALL_FONT)
        dup = str(row.get("mask_within_frame_duplicate_groups") or "")
        if dup:
            dr.text((6, y + 46), f"dup {dup}"[:22], fill=(150, 200, 255), font=SMALL_FONT)
        rgb_path = root / "rgb" / f"f{idx:04d}_rgb.png"
        try:
            rgb = Image.open(rgb_path).convert("RGB")
        except Exception:
            rgb = Image.new("RGB", thumb, (60, 0, 0))
        sheet.paste(resize_fit(rgb, thumb), (label_w, y))
        dr.text((label_w + 4, y + thumb[1] + 2), "rgb", fill=(255, 255, 255), font=SMALL_FONT)
        for j, name in enumerate(mask_names):
            ms = masks_cache.get(idx, {}).get(name)
            if ms and ms.get("image") is not None:
                im = ms["image"].convert("RGB")
            else:
                im = Image.new("RGB", thumb, (40, 40, 40))
            x = label_w + (j + 1) * thumb[0]
            sheet.paste(resize_fit(im, thumb), (x, y))
            digest = str(row.get(f"mask_{name}_sha256") or "")[:8]
            area = row.get(f"mask_{name}_area")
            dr.text((x + 4, y + thumb[1] + 2), f"{name} a={area if area is not None else '-'}", fill=(255, 255, 255), font=SMALL_FONT)
            dr.text((x + 4, y + thumb[1] + 15), digest, fill=(170, 170, 255), font=SMALL_FONT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return len(selected)


def write_mask_integrity_reports(
    report_dir: Path,
    contact_dir: Path,
    root: Path,
    rows: list[dict[str, Any]],
    masks_cache: dict[int, dict[str, dict[str, Any]]],
    mask_names: list[str],
    target_mask: str,
    max_sheet_frames: int,
    hull_outside_warn_ratio: float,
) -> dict[str, Any]:
    groups = cross_frame_mask_duplicates(root, rows, mask_names, target_mask)
    apply_mask_duplicate_findings(rows, groups, mask_names)
    hash_rows = build_mask_hash_rows(root, rows, groups, mask_names)
    inclusion_failures = build_mask_inclusion_failure_rows(rows)
    summary = mask_integrity_summary(rows, groups, inclusion_failures, mask_names, hull_outside_warn_ratio)

    report_dir.mkdir(parents=True, exist_ok=True)
    write_csv(report_dir / "mask_hashes.csv", hash_rows, MASK_HASH_COLUMNS)
    write_csv(report_dir / "mask_pixel_inclusion_failures.csv", inclusion_failures, MASK_INCLUSION_FAILURE_COLUMNS)
    (report_dir / "mask_duplicate_groups.json").write_text(
        json.dumps(
            {
                "root": str(root),
                "mask_names": mask_names,
                "target_mask": target_mask,
                "stage_occluder_source": MASK_STAGE_OCCLUDER_SOURCE,
                "classification_rules": {
                    "expected_no_op": "identical stages inside one frame whose spanned occluder sources were all absent",
                    "no_op_placed_but_not_occluding": "an occluder was placed but its recorded occlusion fraction is 0",
                    "unverified_no_op": "same, but at least one source flag was missing from the record",
                    "unexpected_identical_stage": "the record claims a non-zero occlusion fraction yet the stage mask is byte-identical",
                    "empty_target_defect": "all-black target-stage mask shared by different frames",
                    "all_black_stage_duplicate": "all-black non-target stage shared by different frames (fully occluded)",
                    "stale_or_mismatched_mask": "identical mask bytes but different camera/K/pose across frames",
                    "duplicate_with_identical_geometry": "identical mask bytes AND identical camera/K/pose",
                    "duplicate_geometry_unverifiable": "identical mask bytes but geometry could not be compared",
                },
                "cross_frame_same_stage": groups,
                "within_frame": [
                    {
                        "idx": int(row["idx"]),
                        "diagnostic_mode": row.get("diagnostic_mode") or row.get("mode"),
                        "occluder_source_states": row.get("_mask_occluder_states"),
                        **group,
                    }
                    for row in rows
                    for group in (row.get("_mask_within_frame_duplicates") or [])
                ],
                "summary": summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sheet_rows = mask_integrity_sheet_rows(rows, max_sheet_frames)
    sheet_pages: list[dict[str, Any]] = []
    pages = chunked(mask_integrity_sheet_rows(rows, len(rows)), max_sheet_frames) or [[]]
    for page_no, page_rows in enumerate(pages, 1):
        name = f"mask_integrity_source_masks_{page_no:03d}.png"
        n = make_mask_integrity_sheet(root, page_rows, masks_cache, contact_dir / name, mask_names, max_sheet_frames)
        sheet_pages.append({"file": name, "frames": n})
    first = make_mask_integrity_sheet(
        root, sheet_rows, masks_cache, contact_dir / "mask_integrity_source_masks.png", mask_names, max_sheet_frames
    )
    shutil.copyfile(contact_dir / "mask_integrity_source_masks.png", report_dir / "mask_integrity_source_masks.png")

    summary["outputs"] = {
        "report_dir": str(report_dir),
        "mask_hashes": "mask_hashes.csv",
        "mask_duplicate_groups": "mask_duplicate_groups.json",
        "mask_pixel_inclusion_failures": "mask_pixel_inclusion_failures.csv",
        "source_mask_sheet": "mask_integrity_source_masks.png",
        "source_mask_sheet_pages": sheet_pages,
        "source_mask_sheet_frames": first,
    }
    return summary


def collect_duplicate_filenames(root: Path) -> set[str]:
    names = []
    for sub in ("rgb", "labels", "mask"):
        base = root / sub
        if base.exists():
            names.extend([p.name for p in base.rglob("*") if p.is_file()])
    c = Counter(names)
    return {name for name, n in c.items() if n > 1}


def resize_fit(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, (25, 25, 25))
    img = im.convert("RGB").copy()
    img.thumbnail((size[0], size[1]), Image.LANCZOS)
    x = (size[0] - img.width) // 2
    y = (size[1] - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def make_contact_sheet(paths: list[Path], out_path: Path, title: str, max_frames: int) -> int:
    paths = [p for p in paths if p.exists()][:max_frames]
    if not paths:
        sheet = Image.new("RGB", (800, 220), (30, 30, 30))
        dr = ImageDraw.Draw(sheet)
        dr.text((12, 12), title, fill=(255, 255, 255), font=FONT)
        dr.text((12, 80), "No frames available", fill=(255, 210, 0), font=FONT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path)
        return 0
    cell = (240, 180)
    cols = min(5, len(paths))
    rows = int(math.ceil(len(paths) / cols))
    header_h = 28
    sheet = Image.new("RGB", (cols * cell[0], header_h + rows * cell[1]), (18, 18, 18))
    dr = ImageDraw.Draw(sheet)
    dr.text((8, 6), title, fill=(255, 255, 255), font=FONT)
    for i, p in enumerate(paths):
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            im = Image.new("RGB", cell, (60, 0, 0))
        thumb = resize_fit(im, cell)
        x = (i % cols) * cell[0]
        y = header_h + (i // cols) * cell[1]
        sheet.paste(thumb, (x, y))
        ImageDraw.Draw(sheet).text((x + 4, y + 4), p.stem, fill=(255, 255, 0), font=SMALL_FONT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return len(paths)


def make_source_mask_sheet(root: Path, rows: list[dict[str, Any]], masks_cache: dict[int, dict[str, dict[str, Any]]], out_path: Path, mask_names: list[str], max_frames: int) -> int:
    selected = rows[:max_frames]
    if not selected:
        sheet = Image.new("RGB", (900, 220), (30, 30, 30))
        dr = ImageDraw.Draw(sheet)
        dr.text((12, 12), "Source Mask Examples", fill=(255, 255, 255), font=FONT)
        dr.text((12, 80), "No frames available", fill=(255, 210, 0), font=FONT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path)
        return 0
    thumb = (120, 90)
    label_w = 110
    cols = 1 + len(mask_names)
    row_h = thumb[1] + 24
    sheet = Image.new("RGB", (label_w + cols * thumb[0], 28 + len(selected) * row_h), (18, 18, 18))
    dr = ImageDraw.Draw(sheet)
    dr.text((8, 6), "Source Mask Examples", fill=(255, 255, 255), font=FONT)
    for r_i, row in enumerate(selected):
        idx = int(row["idx"])
        y = 28 + r_i * row_h
        dr.text((6, y + 6), f"f{idx:04d}", fill=(255, 255, 0), font=SMALL_FONT)
        rgb_path = root / "rgb" / f"f{idx:04d}_rgb.png"
        try:
            rgb = Image.open(rgb_path).convert("RGB")
        except Exception:
            rgb = Image.new("RGB", thumb, (60, 0, 0))
        sheet.paste(resize_fit(rgb, thumb), (label_w, y))
        dr.text((label_w + 4, y + thumb[1] + 2), "rgb", fill=(255, 255, 255), font=SMALL_FONT)
        for j, name in enumerate(mask_names):
            ms = masks_cache.get(idx, {}).get(name)
            if ms and ms.get("image") is not None:
                im = ms["image"].convert("RGB")
            else:
                im = Image.new("RGB", thumb, (40, 40, 40))
            x = label_w + (j + 1) * thumb[0]
            sheet.paste(resize_fit(im, thumb), (x, y))
            area = row.get(f"mask_{name}_area")
            area_txt = "" if area is None else str(area)
            dr.text((x + 4, y + thumb[1] + 2), f"{name} area={area_txt}", fill=(255, 255, 255), font=SMALL_FONT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return len(selected)


def chunked(rows: list[Any], size: int) -> list[list[Any]]:
    size = max(1, size)
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def make_contact_sheet_pages(paths: list[Path], out_dir: Path, prefix: str, title: str, max_frames: int) -> dict[str, Any]:
    out: dict[str, Any] = {"frames": len([p for p in paths if p.exists()]), "pages": []}
    pages = chunked(paths, max_frames) or [[]]
    for page_no, page_paths in enumerate(pages, 1):
        name = f"{prefix}_{page_no:03d}.png"
        n = make_contact_sheet(page_paths, out_dir / name, f"{title} page {page_no}/{len(pages)}", max_frames)
        out["pages"].append({"file": name, "frames": n})
    return out


def make_source_mask_sheet_pages(
    root: Path,
    rows: list[dict[str, Any]],
    masks_cache: dict[int, dict[str, dict[str, Any]]],
    out_dir: Path,
    prefix: str,
    title: str,
    mask_names: list[str],
    max_frames: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {"frames": len(rows), "pages": []}
    pages = chunked(rows, max_frames) or [[]]
    for page_no, page_rows in enumerate(pages, 1):
        name = f"{prefix}_{page_no:03d}.png"
        n = make_source_mask_sheet(root, page_rows, masks_cache, out_dir / name, mask_names, max_frames)
        out["pages"].append({"file": name, "frames": n, "title": f"{title} page {page_no}/{len(pages)}"})
    return out


def failure_categories(row: dict[str, Any]) -> set[str]:
    text = str(row.get("failures") or "").lower()
    cats = set()
    if any(token in text for token in ("collision", "exact_collision")):
        cats.add("collision")
    if "anchor" in text:
        cats.add("anchor")
    if any(token in text for token in ("occlusion", "empty_target", "mask_nonmonotonic", "mask_monotonic", "g1", "g3")):
        cats.add("occlusion")
    if any(token in text for token in ("missing", "corrupt", "magenta", "duplicate", "file_count")):
        cats.add("integrity")
    if any(token in text for token in ("front", "connector", "2d", "label")):
        cats.add("geometry")
    return cats or {"other"}


def write_debug_geometry_examples(
    overlay_dir: Path,
    debug_dir: Path,
    rows: list[dict[str, Any]],
    contact_dir: Path,
    max_frames: int,
) -> dict[str, Any]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    selected = [
        r
        for r in rows
        if str(r.get("diagnostic_mode") or r.get("mode") or "") in {"context-rich", "controlled-occlusion"}
    ][:max_frames]
    copied = []
    for r in selected:
        src = overlay_dir / f"f{int(r['idx']):04d}.png"
        dst = debug_dir / f"f{int(r['idx']):04d}_debug_geometry.png"
        if src.exists():
            shutil.copyfile(src, dst)
            copied.append(dst)
    if not copied:
        note = debug_dir / "README.md"
        note.write_text(
            "No context-rich or controlled-occlusion frames were available for debug geometry examples.\n",
            encoding="utf-8",
        )
    sheet = make_contact_sheet(copied, contact_dir / "debug_geometry_context_controlled_examples.png", "Context/Controlled Debug Geometry Examples", max_frames)
    return {"frames": len(copied), "contact_sheet": "debug_geometry_context_controlled_examples.png", "contact_sheet_frames": sheet}


def write_readme(path: Path, root: Path, out: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# v2 Scene Logic Visual Audit",
        "",
        f"- Input root: `{root}`",
        f"- Output root: `{out}`",
        f"- Status: `{summary.get('status')}`",
        f"- Frames audited: {summary.get('frame_count')}",
        f"- Audit pass frames: {summary.get('audit_pass_count')}",
        "",
        "## Checks",
        "",
        "- Strict RGB decode, with corrupt files reported.",
        "- One overlay is generated for every discovered frame. Missing/corrupt frames get a diagnostic placeholder.",
        "- FRONT face distance is checked against the REAR face.",
        "- Connector line crossings are counted from 2D cuboid points.",
        "- 2D cuboid points must be finite.",
        "- Source mask areas are assumed non-increasing in the configured mask order.",
        "- Source masks are decoded strictly (structural/CRC verify + full load) and hashed with SHA256.",
        "- Pixel-level inclusion `M4 subset-of M3 subset-of M2 subset-of M1 subset-of M0` is compared on boolean arrays,",
        "  so a later stage that gains pixels is caught even when the total area still shrinks.",
        "- Identical mask bytes are grouped within a frame and across frames. Within-frame identity is",
        "  expected when the spanned occluder source was not placed (clean-static, no cargo/context/explicit).",
        "  Across frames, an all-black target mask is an empty-target defect and a non-black duplicate is",
        "  cross-checked against camera/K/pose before it is called stale.",
        "- Mask foreground is compared against the projected-cuboid convex hull (bbox IoU + outside ratio).",
        "- RGB and mask resolutions must match.",
        "- Empty target mask uses the configured `--target-mask` suffix.",
        "- Duplicate filenames, duplicate RGB hashes, and duplicate record indices are reported.",
        "- Magenta contamination uses R>180, G<90, B>180 pixel ratio.",
        "",
        "## Outputs",
        "",
        "- `audit_frames.csv`: one row per frame with all check results.",
        "- `overlay_all/*.png`: full-set overlays.",
        "- `contact_sheets/*.png`: mode, pass/fail, failure-reason, source-mask, and debug sheets. Sheets are paged at the configured max frame count so the full frame set is covered.",
        "- `failure_examples.csv` and `failure_examples/*.png`: all failing frame overlays.",
        "- `debug_geometry/*.png`: context-rich and controlled-occlusion geometry examples when those modes exist.",
        "- `audit_summary.json`: aggregate counts and failure distribution (including `mask_integrity`).",
        f"- `{summary.get('mask_integrity', {}).get('outputs', {}).get('report_dir', 'mask_integrity/')}`:"
        " `mask_hashes.csv`, `mask_duplicate_groups.json`, `mask_pixel_inclusion_failures.csv`,"
        " `mask_integrity_source_masks.png`.",
        "- `audit_README.md`: audit-specific output notes.",
        "- Existing `summary.json` and `README.md` are preserved; only concise visual audit sections are merged into them.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concise_visual_audit(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "frame_count": summary.get("frame_count"),
        "audit_pass_count": summary.get("audit_pass_count"),
        "audit_fail_count": summary.get("audit_fail_count"),
        "failure_count_by_type": summary.get("failure_count_by_type", {}),
        "rgb_decode_fail_count": len(summary.get("rgb_decode_fail_indices", [])),
        "missing_label_count": len(summary.get("missing_label_indices", [])),
        "missing_rgb_count": len(summary.get("missing_rgb_indices", [])),
        "magenta_fail_count": len(summary.get("magenta_fail_indices", [])),
        "missing_texture_log_count": int(summary.get("missing_texture_logs", {}).get("count", 0)),
        "mask_monotonic_fail_count": len(summary.get("mask_monotonic_fail_indices", [])),
        "empty_target_mask_count": len(summary.get("empty_target_mask_indices", [])),
        "mask_pixel_inclusion_fail_count": len(
            summary.get("mask_integrity", {}).get("pixel_inclusion_fail_indices", [])
        ),
        "mask_cross_frame_duplicate_group_count": summary.get("mask_integrity", {}).get(
            "cross_frame_duplicate_group_count", 0
        ),
        "mask_stale_duplicate_count": len(
            summary.get("mask_integrity", {}).get("cross_frame_stale_indices", [])
        ),
        "exact_collision_count": len(summary.get("exact_collision_indices", [])),
        "support_fail_count": len(summary.get("support_fail_indices", [])),
        "outputs": {
            "audit_summary": "audit_summary.json",
            "audit_readme": "audit_README.md",
            "audit_frames": "audit_frames.csv",
            "overlay_all": "overlay_all/",
            "contact_sheets": "contact_sheets/",
            "failure_examples": "failure_examples/",
            "debug_geometry": "debug_geometry/",
        },
    }


def merge_visual_audit_summary(path: Path, audit_summary: dict[str, Any]) -> None:
    existing = read_json(path)
    if not isinstance(existing, dict):
        existing = {}
    merged = dict(existing)
    merged["visual_audit"] = concise_visual_audit(audit_summary)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")


def visual_audit_readme_section(summary: dict[str, Any]) -> str:
    lines = [
        "## Visual Audit",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Frames audited: {summary.get('frame_count')}",
        f"- Audit pass frames: {summary.get('audit_pass_count')}",
        f"- Audit fail frames: {summary.get('audit_fail_count')}",
        f"- Detailed summary: `audit_summary.json`",
        f"- Detailed README: `audit_README.md`",
        f"- Contact sheets: `contact_sheets/`",
        f"- Overlays: `overlay_all/`",
        "",
    ]
    return "\n".join(lines)


def merge_visual_audit_readme(path: Path, summary: dict[str, Any]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else "# v2 Scene Logic EDA\n"
    marker = "## Visual Audit"
    idx = existing.find(marker)
    prefix = existing[:idx].rstrip() if idx >= 0 else existing.rstrip()
    text = prefix + "\n\n" + visual_audit_readme_section(summary) + "\n"
    path.write_text(text, encoding="utf-8")


def write_self_test_fixture(root: Path, mask_names: list[str]) -> None:
    (root / "rgb").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    (root / "mask").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (70, 70, 65)).save(root / "rgb" / "f0000_rgb.png")
    # Nested rectangles inside the projected cuboid below, so the fixture also satisfies the
    # pixel-level inclusion chain and the hull-alignment check.
    for i, name in enumerate(mask_names):
        arr = np.zeros((48, 64), dtype=np.uint8)
        arr[16 + i : 32 - i, 21 + i : 43 - i] = 255
        Image.fromarray(arr, mode="L").save(root / "mask" / f"f0000_{name}.png")

    label = {
        "camera_data": {
            "width": 64,
            "height": 48,
            "location_worldframe": [0.0, -5.0, 1.0],
            "scene_preset": "self_test_scene",
        },
        "objects": [
            {
                "name": "pallet_test",
                "cuboid": [
                    [-0.5, -1.0, 0.0],
                    [0.5, -1.0, 0.0],
                    [0.5, -1.0, 0.2],
                    [-0.5, -1.0, 0.2],
                    [-0.5, 1.0, 0.0],
                    [0.5, 1.0, 0.0],
                    [0.5, 1.0, 0.2],
                    [-0.5, 1.0, 0.2],
                ],
                "projected_cuboid": [
                    [20, 15],
                    [44, 15],
                    [44, 33],
                    [20, 33],
                    [24, 18],
                    [40, 18],
                    [40, 30],
                    [24, 30],
                ],
                "projected_cuboid_centroid": [32, 24],
                "safety_gates": {"all_pass": True},
                "v2_labels": {"scene_preset": "self_test_scene"},
            }
        ],
    }
    (root / "labels" / "f0000_label.json").write_text(json.dumps(label, indent=2), encoding="utf-8")
    record = {
        "idx": 0,
        "scene_preset": "self_test_scene",
        "all_pass": True,
        "anchor_reject_reason": None,
        "rendered": True,
        "realize_ok": True,
        "exact_collision_count": 0,
        "camera_clearance_pass": True,
        "support_pass": True,
        "f_static": 0.0,
        "n_cargo_placed": 0,
        "n_context_placed": 0,
        "explicit_occluder_placed": False,
    }
    (root / "records.json").write_text(json.dumps({"records": [record]}, indent=2), encoding="utf-8")
    (root / "records.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


def run_self_test(args: argparse.Namespace) -> int:
    mask_names = [x.strip() for x in args.mask_names.split(",") if x.strip()]
    if args.target_mask not in mask_names:
        mask_names = [args.target_mask] + mask_names
    with tempfile.TemporaryDirectory(prefix="scene_logic_audit_selftest_") as tmp:
        tmp_root = Path(tmp)
        root = tmp_root / "fixture"
        out = root / DEFAULT_OUT_DIRNAME
        write_self_test_fixture(root, mask_names)
        fixture_records, fixture_record_meta = load_records(root)
        errors = []
        if fixture_record_meta.get("source_used") != "records.jsonl":
            errors.append(f"expected records.jsonl source priority, got {fixture_record_meta.get('source_used')}")
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
        out.mkdir(parents=True, exist_ok=True)
        (out / "charts").mkdir(parents=True, exist_ok=True)
        sentinel_summary = {
            "status": "EDA_PASS",
            "eda_sentinel": True,
            "nested": {"keep": 1},
            "chart_mapping": [{"filename": "sentinel_chart.png"}],
        }
        (out / "summary.json").write_text(json.dumps(sentinel_summary, indent=2), encoding="utf-8")
        (out / "README.md").write_text("# Existing EDA README\n\nEDA README SENTINEL\n", encoding="utf-8")
        Image.new("RGB", (8, 8), (10, 20, 30)).save(out / "charts" / "sentinel_chart.png")
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--dir",
            str(root),
            "--mask-names",
            ",".join(mask_names),
            "--target-mask",
            args.target_mask,
            "--max-sheet-frames",
            str(args.max_sheet_frames),
            "--magenta-threshold",
            str(args.magenta_threshold),
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if proc.returncode != 0:
            errors.append(f"child audit exited with {proc.returncode}")
        audit_summary_path = out / "audit_summary.json"
        if not audit_summary_path.exists():
            errors.append("audit_summary.json was not created")
            audit_summary = {}
        else:
            audit_summary = json.loads(audit_summary_path.read_text(encoding="utf-8"))
            if audit_summary.get("status") != "PASS":
                errors.append(f"expected PASS audit summary, got {audit_summary.get('status')}")
            if audit_summary.get("frame_count") != 1 or audit_summary.get("audit_pass_count") != 1:
                errors.append("expected one passing audit fixture frame")
            meta = audit_summary.get("record_meta", {})
            if meta.get("source_used") != "records.jsonl" or meta.get("ignored_sources") != ["records.json"]:
                errors.append(f"audit_summary record_meta did not preserve source priority: {meta}")
            if meta.get("duplicate_record_indices"):
                errors.append("audit_summary incorrectly reports cross-source duplicate indices")
        summary_path = out / "summary.json"
        if not summary_path.exists():
            errors.append("summary.json was not preserved")
            summary = {}
        else:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("status") != "EDA_PASS" or summary.get("eda_sentinel") is not True:
                errors.append("EDA summary top-level keys were overwritten")
            if summary.get("nested", {}).get("keep") != 1:
                errors.append("EDA summary nested keys were not preserved")
            visual = summary.get("visual_audit")
            if not isinstance(visual, dict) or visual.get("audit_pass_count") != 1:
                errors.append("visual_audit merge missing or incorrect")
        readme_path = out / "README.md"
        if not readme_path.exists():
            errors.append("README.md was not preserved")
        else:
            readme = readme_path.read_text(encoding="utf-8")
            if "EDA README SENTINEL" not in readme:
                errors.append("EDA README content was overwritten")
            if "## Visual Audit" not in readme:
                errors.append("Visual Audit section was not merged into README.md")
        if not (out / "charts" / "sentinel_chart.png").exists():
            errors.append("existing chart file was removed")
        required_paths = [
            out / "audit_frames.csv",
            out / "audit_README.md",
            out / "audit_summary.json",
            out / "overlay_all" / "f0000.png",
            out / "contact_sheets" / "manifest.json",
            out / "contact_sheets" / "pass_examples.png",
            out / "contact_sheets" / "failure_examples.png",
            out / "contact_sheets" / "source_masks.png",
            out / "contact_sheets" / "all_pass_001.png",
            out / "contact_sheets" / "source_masks_001.png",
            out / "contact_sheets" / "mask_integrity_source_masks.png",
            out / "debug_geometry",
            out / DEFAULT_MASK_REPORT_DIRNAME / "mask_hashes.csv",
            out / DEFAULT_MASK_REPORT_DIRNAME / "mask_duplicate_groups.json",
            out / DEFAULT_MASK_REPORT_DIRNAME / "mask_pixel_inclusion_failures.csv",
            out / DEFAULT_MASK_REPORT_DIRNAME / "mask_integrity_source_masks.png",
        ]
        for path in required_paths:
            if not path.exists():
                errors.append(f"required audit output missing: {path.name}")
        if errors:
            print("[self-test] FAIL")
            for e in errors:
                print(f"[self-test] {e}")
            return 1
        print("[self-test] PASS audit_outputs=ok")
        return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(args)
    root = as_path(args.dir)
    out = as_path(args.out) if args.out else root / DEFAULT_OUT_DIRNAME
    mask_names = [x.strip() for x in args.mask_names.split(",") if x.strip()]
    if args.target_mask not in mask_names:
        mask_names = [args.target_mask] + mask_names
    global MASK_NAMES
    MASK_NAMES = mask_names

    out.mkdir(parents=True, exist_ok=True)
    overlay_dir = out / "overlay_all"
    contact_dir = out / "contact_sheets"
    failure_dir = out / "failure_examples"
    debug_dir = out / "debug_geometry"
    mask_report_dir = as_path(args.mask_report_out) if args.mask_report_out else out / DEFAULT_MASK_REPORT_DIRNAME
    overlay_dir.mkdir(parents=True, exist_ok=True)
    contact_dir.mkdir(parents=True, exist_ok=True)
    failure_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    mask_report_dir.mkdir(parents=True, exist_ok=True)

    records, record_meta = load_records(root)
    indices = discover_indices(root, records, mask_names) if root.exists() else []
    duplicate_hashes = collect_hash_duplicates(root) if root.exists() else set()
    duplicate_filenames = collect_duplicate_filenames(root) if root.exists() else set()
    duplicate_records = set(record_meta.get("duplicate_record_indices", []))
    missing_texture_logs = scan_missing_texture_logs(root) if root.exists() else {"count": 0, "matches": []}

    rows: list[dict[str, Any]] = []
    masks_cache: dict[int, dict[str, dict[str, Any]]] = {}
    for idx in indices:
        row, rgb_img, lab, obj, masks = evaluate_frame(
            root,
            idx,
            records.get(idx),
            mask_names,
            args.target_mask,
            duplicate_records,
            duplicate_hashes,
            duplicate_filenames,
            args.magenta_threshold,
            args.hull_outside_warn_ratio,
        )
        rows.append(row)
        masks_cache[idx] = masks
        draw_overlay(rgb_img, lab, obj, idx, row, overlay_dir / f"f{idx:04d}.png")

    # Phase 5 runs before the failure roll-up because cross-frame verdicts can fail a frame.
    mask_integrity = write_mask_integrity_reports(
        mask_report_dir,
        contact_dir,
        root,
        rows,
        masks_cache,
        mask_names,
        args.target_mask,
        args.max_sheet_frames,
        args.hull_outside_warn_ratio,
    )

    columns = audit_columns(mask_names)
    write_csv(out / "audit_frames.csv", rows, columns)
    failures = [r for r in rows if not r.get("audit_pass")]
    failures.sort(key=lambda r: (-int(r.get("failure_count") or 0), int(r["idx"])))
    write_csv(out / "failure_examples.csv", failures, columns)
    for r in failures:
        src = overlay_dir / f"f{int(r['idx']):04d}.png"
        if src.exists():
            shutil.copyfile(src, failure_dir / src.name)

    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_mode[str(r.get("mode") or "(missing)")].append(r)
    sheet_manifest = {}
    for mode, mode_rows in sorted(by_mode.items()):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", mode)[:60] or "missing"
        paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in mode_rows]
        paged = make_contact_sheet_pages(paths, contact_dir, f"mode_{safe}", f"Mode: {mode}", args.max_sheet_frames)
        sheet_manifest[f"mode_{safe}"] = {"mode": mode, **paged}
        first_page = contact_dir / paged["pages"][0]["file"] if paged.get("pages") else None
        if first_page and first_page.exists():
            shutil.copyfile(first_page, contact_dir / f"mode_{safe}.png")
    gate_pass_rows = [r for r in rows if r.get("all_pass_gate") is True]
    gate_fail_rows = [r for r in rows if r.get("all_pass_gate") is False]
    gate_unknown_rows = [r for r in rows if r.get("all_pass_gate") is None]
    pass_paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in gate_pass_rows]
    fail_paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in gate_fail_rows]
    unknown_gate_paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in gate_unknown_rows]
    audit_pass_paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in rows if r.get("audit_pass")]
    audit_fail_paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in failures]
    sheet_manifest["all_pass"] = make_contact_sheet_pages(pass_paths, contact_dir, "all_pass", "G1-G5 All-pass Frames", args.max_sheet_frames)
    sheet_manifest["all_fail"] = make_contact_sheet_pages(fail_paths, contact_dir, "all_fail", "G1-G5 Fail Frames", args.max_sheet_frames)
    sheet_manifest["all_pass_unknown"] = make_contact_sheet_pages(unknown_gate_paths, contact_dir, "all_pass_unknown", "Missing G1-G5 Gate Frames", args.max_sheet_frames)
    sheet_manifest["pass_examples.png"] = {"frames": make_contact_sheet(pass_paths, contact_dir / "pass_examples.png", "G1-G5 Pass Examples", args.max_sheet_frames)}
    sheet_manifest["failure_examples.png"] = {"frames": make_contact_sheet(fail_paths, contact_dir / "failure_examples.png", "G1-G5 Failure Examples", args.max_sheet_frames)}
    sheet_manifest["audit_pass"] = make_contact_sheet_pages(audit_pass_paths, contact_dir, "audit_pass", "Audit Pass Frames", args.max_sheet_frames)
    sheet_manifest["audit_fail"] = make_contact_sheet_pages(audit_fail_paths, contact_dir, "audit_fail", "Audit Fail Frames", args.max_sheet_frames)
    category_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in failures:
        for category in failure_categories(r):
            category_rows[category].append(r)
    for category in ("collision", "anchor", "occlusion"):
        paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in category_rows.get(category, [])]
        sheet_manifest[f"failure_category_{category}"] = make_contact_sheet_pages(paths, contact_dir, f"failure_{category}", f"{category.title()} Failure Frames", args.max_sheet_frames)
    failure_counter_for_sheets = Counter()
    for r in failures:
        for item in str(r.get("failures") or "").split(";"):
            if item:
                failure_counter_for_sheets[item] += 1
    for failure_name, _ in failure_counter_for_sheets.most_common():
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", failure_name)[:60] or "failure"
        rows_for_failure = [r for r in failures if failure_name in str(r.get("failures") or "").split(";")]
        paths = [overlay_dir / f"f{int(r['idx']):04d}.png" for r in rows_for_failure]
        sheet_manifest[f"failure_reason_{safe}"] = make_contact_sheet_pages(paths, contact_dir, f"failure_reason_{safe}", f"Failure: {failure_name}", args.max_sheet_frames)
    source_rows = failures[: args.max_sheet_frames]
    if len(source_rows) < args.max_sheet_frames:
        source_rows = source_rows + [r for r in rows if r.get("audit_pass")][: args.max_sheet_frames - len(source_rows)]
    sheet_manifest["source_masks.png"] = {
        "frames": make_source_mask_sheet(root, source_rows, masks_cache, contact_dir / "source_masks.png", mask_names, args.max_sheet_frames)
    }
    sheet_manifest["source_masks_all"] = make_source_mask_sheet_pages(root, rows, masks_cache, contact_dir, "source_masks", "Source Masks", mask_names, args.max_sheet_frames)
    sheet_manifest["debug_geometry"] = write_debug_geometry_examples(overlay_dir, debug_dir, rows, contact_dir, args.max_sheet_frames)

    failure_counter = Counter()
    for r in failures:
        for item in str(r.get("failures") or "").split(";"):
            if item:
                failure_counter[item] += 1
    fatal_failure_counter = Counter()
    for r in rows:
        for item in str(r.get("fatal_failures") or "").split(";"):
            if item:
                fatal_failure_counter[item] += 1
    if missing_texture_logs["count"]:
        fatal_failure_counter["missing_texture"] += int(missing_texture_logs["count"])

    expected_indices: set[int] | None = None
    if args.expected_frame_count is not None and args.expected_frame_count >= 0:
        expected_indices = set(
            range(
                int(args.expected_start_index),
                int(args.expected_start_index) + int(args.expected_frame_count),
            )
        )
    discovered_indices = set(indices)
    missing_expected_indices = (
        sorted(expected_indices - discovered_indices)
        if expected_indices is not None
        else []
    )
    unexpected_indices = (
        sorted(discovered_indices - expected_indices)
        if expected_indices is not None
        else []
    )
    summary = {
        "root": str(root),
        "out": str(out),
        "frame_count": len(rows),
        "audit_pass_count": sum(1 for r in rows if r.get("audit_pass")),
        "audit_fail_count": len(failures),
        "all_pass_gate_count": sum(1 for r in rows if r.get("all_pass_gate") is True),
        "all_fail_gate_count": sum(1 for r in rows if r.get("all_pass_gate") is False),
        "all_pass_gate_unknown_count": sum(1 for r in rows if r.get("all_pass_gate") is None),
        "failure_count_by_type": dict(failure_counter.most_common()),
        "fatal_failure_count": sum(fatal_failure_counter.values()),
        "fatal_failure_count_by_type": dict(fatal_failure_counter.most_common()),
        "fatal_failure_indices": [r["idx"] for r in rows if not r.get("fatal_pass")],
        "rgb_decode_fail_indices": [r["idx"] for r in rows if r.get("rgb_present") and not r.get("rgb_decode_ok")],
        "missing_rgb_indices": [
            r["idx"]
            for r in rows
            if r.get("artifacts_required") is not False and not r.get("rgb_present")
        ],
        "missing_label_indices": [
            r["idx"]
            for r in rows
            if r.get("artifacts_required") is not False and not r.get("label_present")
        ],
        "duplicate_record_indices": sorted(duplicate_records),
        "duplicate_filenames": sorted(duplicate_filenames),
        "duplicate_rgb_hash_count": len(duplicate_hashes),
        "magenta_fail_indices": [r["idx"] for r in rows if r.get("magenta_fail")],
        "missing_texture_logs": missing_texture_logs,
        "file_count_by_kind": {
            "records": len(records),
            "rgb": len(list((root / "rgb").glob("f*_rgb.png"))) if root.exists() else 0,
            "labels": len(list((root / "labels").glob("f*_label.json"))) if root.exists() else 0,
            "mask_files": len(list((root / "mask").glob("f*_*.png"))) if root.exists() else 0,
            "overlays": len(list(overlay_dir.glob("*.png"))),
        },
        "file_count_mismatch_indices": [r["idx"] for r in rows if r.get("file_count_mismatch")],
        "required_label_missing_indices": [r["idx"] for r in rows if int(r.get("required_label_missing_count") or 0) > 0],
        "empty_target_mask_indices": [r["idx"] for r in rows if r.get("empty_target_mask")],
        "mask_monotonic_fail_indices": [r["idx"] for r in rows if r.get("mask_monotonic_ok") is False],
        "front_not_near_indices": [r["idx"] for r in rows if r.get("front_near") is False],
        "connector_crossing_indices": [r["idx"] for r in rows if int(r.get("connector_crossings") or 0) > 0],
        "exact_collision_indices": [r["idx"] for r in rows if int(r.get("exact_collision_count") or 0) > 0],
        "support_fail_indices": [r["idx"] for r in rows if r.get("support_pass") is False],
        "support_unknown_required_indices": [
            r["idx"]
            for r in rows
            if r.get("support_required") and r.get("support_pass") is None
        ],
        "ground_continuity": ground_continuity_summary(rows),
        "camera_clearance_fail_indices": [
            r["idx"] for r in rows if r.get("camera_clearance_pass") is False
        ],
        "camera_clearance_unknown_accepted_indices": [
            r["idx"]
            for r in rows
            if r.get("accepted_frame") and r.get("camera_clearance_pass") is None
        ],
        "expected_frame_count": args.expected_frame_count,
        "expected_start_index": args.expected_start_index,
        "missing_expected_indices": missing_expected_indices,
        "unexpected_indices": unexpected_indices,
        "mask_names": mask_names,
        "target_mask": args.target_mask,
        "mask_monotonic_assumption": "areas must be non-increasing in mask_names order",
        "mask_integrity": mask_integrity,
        "record_meta": record_meta,
        "contact_sheets": sheet_manifest,
        "errors": [],
        "warnings": [],
    }
    summary["errors"].extend(record_meta.get("errors", []))
    if not root.exists():
        summary["errors"].append("input root missing")
    if not rows:
        summary["errors"].append("no frames discovered")
    if args.expected_frame_count is not None and args.expected_frame_count < 0:
        summary["errors"].append("expected frame count must be nonnegative")
    if missing_expected_indices or unexpected_indices:
        summary["errors"].append(
            "frame index range mismatch: "
            f"missing={missing_expected_indices} unexpected={unexpected_indices}"
        )
    if missing_texture_logs["count"]:
        summary["errors"].append(
            f"missing texture/image diagnostics present in Blender logs: "
            f"{missing_texture_logs['count']}"
        )
    if any(not r.get("fatal_pass") for r in rows):
        summary["errors"].append(
            "fatal frame audit failures present: "
            + ", ".join(
                f"{name}={count}"
                for name, count in fatal_failure_counter.most_common()
                if name != "missing_texture"
            )
        )
    if failures and not any(not r.get("fatal_pass") for r in rows):
        summary["warnings"].append("audit failures present")
    summary["status"] = "FAIL" if summary["errors"] else ("WARN" if summary["warnings"] else "PASS")
    (out / "contact_sheets" / "manifest.json").write_text(json.dumps(sheet_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "audit_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_readme(out / "audit_README.md", root, out, summary)
    merge_visual_audit_summary(out / "summary.json", summary)
    merge_visual_audit_readme(out / "README.md", summary)
    print(f"[audit] status={summary['status']} frames={len(rows)} failures={len(failures)} out={out}")
    if summary["errors"]:
        print("[audit] errors: " + "; ".join(summary["errors"]))
    if summary["warnings"]:
        print("[audit] warnings: " + "; ".join(summary["warnings"]))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
