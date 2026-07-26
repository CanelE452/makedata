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
from PIL import Image, ImageDraw, ImageFont


DEFAULT_DIR = "data/pallet/_v2_scene_logic_500_seed7500"
DEFAULT_OUT_DIRNAME = "eda"
MASK_NAMES = ["m0", "m1", "m2", "m3", "m4"]
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
    "magenta_ratio",
    "magenta_fail",
    "all_pass_gate",
    "fatal_pass",
    "fatal_failure_count",
    "fatal_failures",
]
for _name in MASK_NAMES:
    AUDIT_COLUMNS.extend([f"mask_{_name}_present", f"mask_{_name}_decode_ok", f"mask_{_name}_area", f"mask_{_name}_error"])


def audit_columns(mask_names: list[str]) -> list[str]:
    cols = [c for c in AUDIT_COLUMNS if not c.startswith("mask_")]
    if "duplicate_filename" not in cols:
        insert_at = cols.index("duplicate_rgb_hash") if "duplicate_rgb_hash" in cols else len(cols)
        cols.insert(insert_at, "duplicate_filename")
    for name in mask_names:
        cols.extend([f"mask_{name}_present", f"mask_{name}_decode_ok", f"mask_{name}_area", f"mask_{name}_error"])
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
    masks = {name: mask_area(root / "mask" / f"{frame}_{name}.png") for name in mask_names}
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
    fatal_failures = fatal_failure_reasons(row, mask_names)
    row["fatal_pass"] = len(fatal_failures) == 0
    row["fatal_failure_count"] = len(fatal_failures)
    row["fatal_failures"] = ";".join(fatal_failures)
    row["failure_count"] = len(failures)
    row["failures"] = ";".join(failures)
    row["audit_pass"] = len(failures) == 0
    return row, rgb_img, lab, obj, masks


def collect_hash_duplicates(root: Path) -> set[str]:
    hashes = []
    for path in (root / "rgb").glob("f*_rgb.png"):
        h = sha256_file(path)
        if h:
            hashes.append(h)
    c = Counter(hashes)
    return {h for h, n in c.items() if n > 1}


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
        "- `audit_summary.json`: aggregate counts and failure distribution.",
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
    for i, name in enumerate(mask_names):
        arr = np.zeros((48, 64), dtype=np.uint8)
        arr[6 + i : 42 - i, 8 + i : 56 - i] = 255
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
            out / "debug_geometry",
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
    overlay_dir.mkdir(parents=True, exist_ok=True)
    contact_dir.mkdir(parents=True, exist_ok=True)
    failure_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

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
        )
        rows.append(row)
        masks_cache[idx] = masks
        draw_overlay(rgb_img, lab, obj, idx, row, overlay_dir / f"f{idx:04d}.png")

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
