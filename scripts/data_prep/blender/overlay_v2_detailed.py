"""Detailed per-frame overlay for v2 constrained frames (bpy-free, Phase 6).

Why this exists
---------------
`audit_v2_scene_logic.draw_overlay()` only draws the cuboid, the corner ids, the centroid and a
one-line header. The old generator `gen_trunc_addon.render_frame()` used to draw a much richer
overlay (pose axes, camera geometry, visibility, pose angles, an info panel and an axis legend) but
that code lived inside a bpy render loop and died with it. This module restores that overlay as a
standalone, bpy-free helper and extends it with everything Phase 1..5 added:

  Phase 1  camera_distance_actual_m vs camera_distance_limit_m  (over-limit violation)
  Phase 2  ground_continuity_pass / probes / procedural floor edge risk
  Phase 3  noise_tier / gaussian_sigma / exposure / final-RGB luma
  Phase 4  pnp_eligible_candidate_{2,3,4}cell / tiny_warning / pnp_stress
  Phase 5  mask pixel inclusion + M0/M4 hull alignment, M0/M4 contours

Missing-field policy (falsy-0 safe)
-----------------------------------
Every value goes through `pick()`, which reports THREE distinct states:

  absent  -> the key does not exist in any source        -> "N/A (field absent)"
  null    -> the key exists but the value is None/""     -> "N/A (null)"
  present -> anything else, INCLUDING 0, 0.0 and False   -> formatted normally

A legacy render (rendered before Phase 1..5) therefore shows "N/A (field absent)" instead of a
silent 0. The per-run manifest counts those so the gap is visible without opening images.

Usage
-----
  python scripts/data_prep/blender/overlay_v2_detailed.py \
      --dir data/pallet/_v2_scene_logic_500_seed7500 \
      --pnp-csv reports/v2_revision/pnp_threshold_study.csv

Outputs (default <dir>/eda_phase6, never the existing eda/ or eda_phase5/ overlays):
  overlay_detailed/fNNNN.png
  contact_sheets/detailed_NNN.png
  overlay_manifest.json
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = False

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from blender_math import build_view_matrix  # noqa: E402  (bpy-free helper)


def _load_audit_module():
    """Reuse the bpy-free audit helpers (records/label/mask loaders, hull, contact sheets)."""
    path = _THIS_DIR / "audit_v2_scene_logic.py"
    spec = importlib.util.spec_from_file_location("audit_v2_scene_logic", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("audit_v2_scene_logic", module)
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit_module()

DEFAULT_DIR = "data/pallet/_v2_scene_logic_500_seed7500"
DEFAULT_OUT_DIRNAME = "eda_phase6"
OVERLAY_DIRNAME = "overlay_detailed"
MASK_NAMES = ["m0", "m1", "m2", "m3", "m4"]

# Edge colouring kept from the current v2 audit overlay (do not switch to the old per-world-axis
# colouring: FRONT/REAR/connector is what the keypoint convention doc uses).
FRONT_EDGES = AUDIT.FRONT_EDGES
REAR_EDGES = AUDIT.REAR_EDGES
CONN_EDGES = AUDIT.CONN_EDGES
COLOR_FRONT = (255, 30, 30)
COLOR_REAR = (60, 120, 255)
COLOR_CONN = (255, 210, 0)
COLOR_CENTROID = (0, 255, 0)
COLOR_OFFSCREEN_KP = (140, 140, 140)
COLOR_HULL = (0, 230, 180)
COLOR_M0_CONTOUR = (0, 200, 255)
COLOR_M4_CONTOUR = (255, 140, 0)
AXIS_COLORS = ((255, 60, 60), (60, 220, 60), (80, 130, 255))
AXIS_LABELS = ("X", "Y", "Z")
AXIS_LEN_M = 0.5

TEXT = (235, 235, 235)
TEXT_LABEL = (170, 200, 255)
TEXT_NA = (150, 150, 150)
TEXT_PASS = (90, 230, 120)
TEXT_FAIL = (255, 90, 90)
TEXT_WARN = (255, 210, 0)
SECTION_BG = (52, 60, 78)
PANEL_BG = (16, 16, 20)

MISSING_TEXT = "N/A (field absent)"
NULL_TEXT = "N/A (null)"

PANEL_COL_W = 330
PANEL_COLS = 2
ROW_H = 14
PANEL_PAD = 6
LABEL_W = 122

FONT = AUDIT.load_font(12)
SMALL_FONT = AUDIT.load_font(11)

# Keep PIL away from absurd coordinates (cuboid corners can project thousands of px off-image).
DRAW_CLAMP_PX = 20000.0
# Phase 1 cap, used only as a labelled fallback when the record predates Phase 1.
FALLBACK_CAMERA_DISTANCE_LIMIT_M = 10.0


# --------------------------------------------------------------------------------------
# Value model: absent vs null vs present (0/False are present)
# --------------------------------------------------------------------------------------

class Val:
    """A looked-up value plus where it came from. `present` is key existence, not truthiness."""

    __slots__ = ("present", "value", "source", "key")

    def __init__(self, present: bool, value: Any = None, source: str | None = None,
                 key: str | None = None) -> None:
        self.present = bool(present)
        self.value = value
        self.source = source
        self.key = key

    @property
    def known(self) -> bool:
        """True when the field exists AND carries a usable (non-null) value."""
        return self.present and self.value is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Val(present={self.present}, value={self.value!r}, source={self.source!r})"


ABSENT = Val(False)


def pick(sources: Iterable[tuple[str, Any]], *keys: str) -> Val:
    """First source that CONTAINS one of `keys` wins, even if its value is 0/False/None."""
    for name, container in sources:
        if not isinstance(container, dict):
            continue
        for key in keys:
            if key in container:
                value = container[key]
                if isinstance(value, str) and value == "":
                    value = None
                return Val(True, value, name, key)
    return Val(False, None, None, None)


def derived(value: Any) -> Val:
    """A value we computed here (never 'absent'; may still be null when uncomputable)."""
    return Val(True, value, "derived", None)


def pair_val(sources: Iterable[tuple[str, Any]], keys_a: Iterable[str], keys_b: Iterable[str],
             digits: int = 3) -> Val:
    """'a / b' as one row. Absent only when NEITHER key exists in any source."""
    sources = list(sources)
    a = pick(sources, *keys_a)
    b = pick(sources, *keys_b)
    if not a.present and not b.present:
        return ABSENT
    return Val(True, _pair_text(a.value, b.value, digits), "pair")


def _fmt_float(v: Any, digits: int) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(f):
        return str(v)
    if f == 0.0:
        f = 0.0  # normalise -0.0 so a legitimate zero never renders as "-0.000"
    return f"{f:.{digits}f}"


def num(digits: int = 2, unit: str = "") -> Callable[[Any], str]:
    def f(v: Any) -> str:
        return f"{_fmt_float(v, digits)}{unit}"

    return f


def boolean(true: str = "PASS", false: str = "FAIL") -> Callable[[Any], str]:
    def f(v: Any) -> str:
        b = AUDIT.bool_value(v)
        if b is None:
            b = bool(v)
        return true if b else false

    return f


def text(v: Any) -> str:
    return str(v)


def render_value(val: Val, formatter: Callable[[Any], str] = text) -> tuple[str, tuple[int, int, int]]:
    """(text, colour). Absent and null are visibly different; 0 / False are NOT 'N/A'."""
    if not val.present:
        return MISSING_TEXT, TEXT_NA
    if val.value is None:
        return NULL_TEXT, TEXT_NA
    return formatter(val.value), TEXT


def status_value(val: Val, true: str = "PASS", false: str = "FAIL",
                 invert: bool = False) -> tuple[str, tuple[int, int, int]]:
    """Colour a boolean-ish field green/red. `invert` = True means True is the bad state."""
    if not val.present:
        return MISSING_TEXT, TEXT_NA
    if val.value is None:
        return NULL_TEXT, TEXT_NA
    b = AUDIT.bool_value(val.value)
    if b is None:
        b = bool(val.value)
    good = (not b) if invert else b
    return (true if b else false), (TEXT_PASS if good else TEXT_FAIL)


class Row:
    __slots__ = ("label", "text", "color", "kind", "field_key")

    def __init__(self, label: str, text: str, color: tuple[int, int, int] = TEXT,
                 kind: str = "field", field_key: str | None = None) -> None:
        self.label = label
        self.text = text
        self.color = color
        self.kind = kind
        self.field_key = field_key

    @property
    def is_na(self) -> bool:
        return self.kind == "field" and self.text in (MISSING_TEXT, NULL_TEXT)

    @property
    def is_absent(self) -> bool:
        return self.kind == "field" and self.text == MISSING_TEXT


def section(title: str) -> Row:
    return Row(title, "", TEXT, kind="section")


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------

def _coerce_csv(value: str) -> Any:
    if value == "":
        return None
    low = value.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if re.fullmatch(r"[+-]?\d+", value):
            return int(value)
        return float(value)
    except ValueError:
        return value


def load_csv_rows(path: Path | None, index_key: str = "idx") -> dict[int, dict[str, Any]]:
    """CSV -> {idx: row}. Empty cells become None (present-but-null), never 0."""
    out: dict[int, dict[str, Any]] = {}
    if path is None or not Path(path).exists():
        return out
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            idx = AUDIT.int_value(raw.get(index_key))
            if idx is None:
                continue
            out[idx] = {k: _coerce_csv(v if v is not None else "") for k, v in raw.items()}
    return out


def find_audit_csv(root: Path, explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    for rel in ("eda_phase5/audit_frames.csv", "eda/audit_frames.csv"):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def find_pnp_csv(root: Path, explicit: str | None) -> Path | None:
    """Only auto-detect INSIDE the dataset; a repo-wide report may belong to another dataset."""
    if explicit:
        return Path(explicit)
    for rel in ("eda_phase4/pnp_threshold_study.csv", "pnp_threshold_study.csv"):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


# --------------------------------------------------------------------------------------
# Geometry (label-derived; verified against the label's own projected_cuboid)
# --------------------------------------------------------------------------------------

def frame_geometry(lab: dict[str, Any] | None, obj: dict[str, Any] | None) -> dict[str, Any] | None:
    """Camera intrinsics/extrinsics + world cuboid + object->camera pose.

    `pose_transform` is the object(centroid-origin) -> CAMERA matrix: projecting its translation
    with K reproduces `projected_cuboid_centroid` exactly, and build_view_matrix(location,
    look) + K reproduces `projected_cuboid` to ~1e-14 px on real v2 labels. [확인]
    """
    if not isinstance(lab, dict) or not isinstance(obj, dict):
        return None
    cam = lab.get("camera_data")
    if not isinstance(cam, dict):
        return None
    intr = cam.get("intrinsics")
    if not isinstance(intr, dict):
        return None
    try:
        fx, fy = float(intr["fx"]), float(intr["fy"])
        cx, cy = float(intr["cx"]), float(intr["cy"])
        width, height = float(cam["width"]), float(cam["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (fx, fy, cx, cy, width, height)):
        return None

    k = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
    out: dict[str, Any] = {"K": k, "W": width, "H": height, "fx": fx, "fy": fy}

    ok_c, corners_w = AUDIT.finite_point_list(obj.get("cuboid"), expected=8)
    ok_p, uv8 = AUDIT.finite_point_list(obj.get("projected_cuboid"), expected=8)
    out["corners_w"] = corners_w if (ok_c and corners_w is not None and corners_w.shape[1] == 3) else None
    out["uv8"] = uv8[:, :2] if (ok_p and uv8 is not None) else None

    cam_pos = look = None
    try:
        cam_pos = np.asarray(cam["location_worldframe"], dtype=np.float64)
        look = np.asarray(cam["look_worldframe"], dtype=np.float64)
        if cam_pos.shape != (3,) or look.shape != (3,) or not np.isfinite(cam_pos).all():
            cam_pos = look = None
    except (KeyError, TypeError, ValueError):
        cam_pos = look = None
    out["cam_pos"] = cam_pos
    out["look"] = look

    if out["corners_w"] is not None:
        centroid_w = out["corners_w"].mean(axis=0)
        out["centroid_w"] = centroid_w
        if cam_pos is not None:
            out["camera_distance_m"] = float(np.linalg.norm(centroid_w - cam_pos))
            out["nearest_corner_distance_m"] = float(
                np.linalg.norm(out["corners_w"] - cam_pos[None, :], axis=1).min()
            )
    if cam_pos is not None and look is not None and out["corners_w"] is not None:
        r_w2c, t_w2c = build_view_matrix(cam_pos, look, up=(0, 0, 1))
        pts_cam = (r_w2c @ out["corners_w"].T).T + t_w2c
        out["R_w2c"], out["t_w2c"] = r_w2c, t_w2c
        out["corners_cam"] = pts_cam
        if out["uv8"] is not None:
            uv_check, _ = project_cam_points(k, pts_cam)
            if uv_check is not None and np.isfinite(uv_check).all():
                out["reproj_consistency_px"] = float(np.abs(uv_check - out["uv8"]).max())

    pose = obj.get("pose_transform")
    try:
        pose_arr = np.asarray(pose, dtype=np.float64)
        if pose_arr.shape == (4, 4) and np.isfinite(pose_arr).all():
            out["pose_R"] = pose_arr[:3, :3]
            out["pose_t"] = pose_arr[:3, 3]
    except (TypeError, ValueError):
        pass

    cent_uv = obj.get("projected_cuboid_centroid")
    ok_cc, cc = AUDIT.finite_point_list([cent_uv] if cent_uv is not None else None, expected=1)
    out["uv_centroid"] = cc[0, :2] if (ok_cc and cc is not None) else None
    return out


def project_cam_points(k: np.ndarray, pts_cam: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    pts = np.atleast_2d(np.asarray(pts_cam, dtype=np.float64))
    if pts.shape[1] != 3:
        return None, None
    z = pts[:, 2].copy()
    safe = np.where(np.abs(z) < 1e-9, np.nan, z)
    uv = np.stack([k[0, 0] * pts[:, 0] / safe + k[0, 2],
                   k[1, 1] * pts[:, 1] / safe + k[1, 2]], axis=1)
    return uv, z


def pose_axis_endpoints(geom: dict[str, Any], length: float = AXIS_LEN_M) -> list[dict[str, Any]] | None:
    """Object X/Y/Z axes at the centroid, in image space, using pose_transform (obj->camera)."""
    if not geom or geom.get("pose_R") is None or geom.get("pose_t") is None:
        return None
    r, t = geom["pose_R"], geom["pose_t"]
    origin_uv, origin_z = project_cam_points(geom["K"], t[None, :])
    if origin_uv is None:
        return None
    axes = []
    for i in range(3):
        direction = r[:, i]
        norm = float(np.linalg.norm(direction))
        if norm < 1e-9:
            axes.append({"label": AXIS_LABELS[i], "color": AXIS_COLORS[i], "ok": False})
            continue
        end_cam = t + direction / norm * float(length)
        end_uv, end_z = project_cam_points(geom["K"], end_cam[None, :])
        ok = bool(origin_z is not None and origin_z[0] > 0 and end_z is not None and end_z[0] > 0
                  and np.isfinite(origin_uv).all() and np.isfinite(end_uv).all())
        axes.append({
            "label": AXIS_LABELS[i],
            "color": AXIS_COLORS[i],
            "ok": ok,
            "start": tuple(origin_uv[0]) if np.isfinite(origin_uv).all() else None,
            "end": tuple(end_uv[0]) if np.isfinite(end_uv).all() else None,
        })
    return axes


def hfov_deg_from_fx(fx: float | None, width: float | None) -> float | None:
    if not fx or not width or fx <= 0:
        return None
    return math.degrees(2.0 * math.atan(float(width) / (2.0 * float(fx))))


def in_image_count(uv: np.ndarray | None, width: float | None, height: float | None) -> int | None:
    if uv is None or width is None or height is None:
        return None
    inside = ((uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height))
    return int(inside.sum())


# --------------------------------------------------------------------------------------
# Masks: contour extraction (numpy only, no cv2)
# --------------------------------------------------------------------------------------

def dilate(mask: np.ndarray | None, iterations: int = 1) -> np.ndarray | None:
    """3x3 binary dilation (numpy shifts; a 1px contour is invisible on a downscaled sheet)."""
    if mask is None:
        return None
    out = np.asarray(mask).astype(bool)
    for _ in range(max(0, int(iterations))):
        grown = out.copy()
        grown[:-1, :] |= out[1:, :]
        grown[1:, :] |= out[:-1, :]
        grown[:, :-1] |= out[:, 1:]
        grown[:, 1:] |= out[:, :-1]
        out = grown
    return out


def mask_boundary(fg: np.ndarray | None, thickness: int = 1) -> np.ndarray | None:
    """4-connected outline of a boolean foreground: foreground minus its 4-neighbour interior."""
    if fg is None:
        return None
    arr = np.asarray(fg)
    if arr.ndim != 2 or arr.size == 0:
        return None
    binary = arr.astype(bool)
    interior = binary.copy()
    shifted = np.zeros_like(binary)
    shifted[:-1, :] = binary[1:, :]
    interior &= shifted
    shifted = np.zeros_like(binary)
    shifted[1:, :] = binary[:-1, :]
    interior &= shifted
    shifted = np.zeros_like(binary)
    shifted[:, :-1] = binary[:, 1:]
    interior &= shifted
    shifted = np.zeros_like(binary)
    shifted[:, 1:] = binary[:, :-1]
    interior &= shifted
    edge = binary & ~interior
    if thickness > 1:
        edge = dilate(edge, thickness - 1)
    return edge


def load_mask_foreground(root: Path, idx: int, name: str) -> dict[str, Any]:
    """Strict-decoded mask stage: {'present','decode_ok','fg','area','error'}."""
    path = root / "mask" / f"f{idx:04d}_{name}.png"
    info = AUDIT.strict_decode_mask(path)
    return {
        "present": info.get("present"),
        "decode_ok": info.get("decode_ok"),
        "fg": info.get("fg"),
        "area": info.get("area"),
        "error": info.get("error"),
        "width": info.get("width"),
        "height": info.get("height"),
    }


def paint_contour(arr: np.ndarray, boundary: np.ndarray | None, color: tuple[int, int, int]) -> int:
    if boundary is None:
        return 0
    if boundary.shape != arr.shape[:2]:
        return 0
    arr[boundary] = np.array(color, dtype=arr.dtype)
    return int(boundary.sum())


# --------------------------------------------------------------------------------------
# Section building
# --------------------------------------------------------------------------------------

def _sources(ctx: dict[str, Any], *names: str) -> list[tuple[str, Any]]:
    return [(n, ctx.get(n)) for n in names]


def build_sections(ctx: dict[str, Any]) -> list[Row]:
    """All panel rows, in order. Every row goes through pick()/derived() so 0 is never 'N/A'."""
    idx = ctx.get("idx")
    obj = ctx.get("obj") or {}
    cam = (ctx.get("lab") or {}).get("camera_data") if isinstance(ctx.get("lab"), dict) else {}
    cam = cam if isinstance(cam, dict) else {}
    floor = cam.get("floor") if isinstance(cam.get("floor"), dict) else {}
    v2 = ctx.get("v2") or {}
    sp = ctx.get("sp") or {}
    gates = ctx.get("gates") or {}
    rec = ctx.get("rec") or {}
    audit = ctx.get("audit") or {}
    pnp = ctx.get("pnp") or {}
    geom = ctx.get("geom") or {}
    masks = ctx.get("masks") or {}

    rec_v2 = _sources(ctx, "rec", "v2")
    rec_sp = _sources(ctx, "rec", "sp")
    v2_sp = _sources(ctx, "v2", "sp")
    rows: list[Row] = []

    def field(label: str, val: Val, formatter: Callable[[Any], str] = text) -> None:
        t, c = render_value(val, formatter)
        rows.append(Row(label, t, c, field_key=label))

    def status(label: str, val: Val, true: str = "PASS", false: str = "FAIL",
               invert: bool = False) -> None:
        t, c = status_value(val, true, false, invert)
        rows.append(Row(label, t, c, field_key=label))

    # ---------------- FRAME ----------------
    rows.append(section("FRAME"))
    rows.append(Row("frame", f"f{int(idx):04d}" if idx is not None else "?"))
    field("mode", pick(rec_sp, "diagnostic_mode"))
    field("pallet", pick(rec_v2, "pallet_type"))
    field("material", pick([("v2", v2)], "material_variant_actual"))
    field("preset", pick([("cam", cam), ("rec", rec)], "scene_preset"))
    field("background", pick([("cam", cam), ("rec", rec)], "background_asset"))
    field("floor", pick([("cam", cam), ("rec", rec)], "floor_mode"))
    field("floor tex", pick([("floor", floor)], "floor_texture"))
    status("rendered", pick([("rec", rec)], "rendered"), "YES", "NO")
    field("reject", pick([("rec", rec), ("audit", audit)], "reject_reason"))

    # ---------------- STATUS ----------------
    rows.append(section("AUDIT / GATES"))
    status("audit_pass", pick([("audit", audit)], "audit_pass"))
    fail_val = pick([("audit", audit)], "failures")
    if fail_val.present and fail_val.value is None:
        # audit_frames.csv writes an empty cell for "no failures", which is a result, not a gap.
        rows.append(Row("failures", "none", TEXT_PASS, field_key="failures"))
    else:
        field("failures", fail_val)
    status("all_pass gate", pick([("rec", rec), ("audit", audit)], "all_pass", "all_pass_gate"))
    gate_bits = []
    gate_color = TEXT
    gate_keys = (("G1", "G1_pass", "G1_Vvis>=4"), ("G2", "G2_pass", "G2_extocc_1to4"),
                 ("G3", "G3_pass", "G3_visible>=0.5unocc"), ("G4", "G4_pass", "G4_center_inframe"),
                 ("G5", "G5_pass", "G5_luma_floor"))
    for short, rec_key, lab_key in gate_keys:
        val = pick([("rec", rec), ("gates", gates)], rec_key, lab_key)
        if not val.present:
            gate_bits.append(f"{short}:-")
            continue
        b = AUDIT.bool_value(val.value)
        gate_bits.append(f"{short}:{'Y' if b else 'N' if b is not None else '?'}")
        if b is False:
            gate_color = TEXT_FAIL
    rows.append(Row("G1..G5 (final luma)", " ".join(gate_bits), gate_color))
    # Phase 2 fields are read from the record/label only. audit_frames.csv mirrors the same field,
    # so including it would turn "this render predates Phase 2" into a misleading "null".
    status("ground contin.", pick(rec_sp, "ground_continuity_pass"))
    field("ground probes", pick(rec_sp, "ground_probe_count"), num(0))
    field("ground fails", pick(rec_sp, "ground_probe_fail_count"), num(0))
    field("ground step", pick(rec_sp, "ground_probe_max_step_m"), num(3, " m"))
    status("floor edge risk", pick(rec_sp, "procedural_floor_edge_risk"), "RISK", "ok", invert=True)
    status("mask incl.", pick([("audit", audit), ("computed", ctx.get("computed"))],
                              "mask_pixel_inclusion_ok"))
    field("mask incl. px", pick([("audit", audit), ("computed", ctx.get("computed"))],
                                "mask_pixel_inclusion_violation_px"), num(0, " px"))
    field("hull IoU M0/M4", pair_val([("audit", audit), ("computed", ctx.get("computed"))],
                                     ["mask_m0_hull_bbox_iou"], ["mask_m4_hull_bbox_iou"], 3))
    field("magenta", pick([("rec", rec), ("audit", audit)], "magenta_fraction", "magenta_ratio"),
          num(4))

    # ---------------- CAMERA ----------------
    rows.append(section("CAMERA"))
    field("dist centroid", derived(geom.get("camera_distance_m")), num(3, " m"))
    field("dist surface", derived(geom.get("nearest_corner_distance_m")), num(3, " m"))
    # Phase 1 fields, record only. The Phase 4 CSV carries camera_distance_used_m but that value is
    # itself label-recomputed for legacy renders, so it must not be shown as a recorded distance.
    dist_rec = pick([("rec", rec)], "camera_distance_actual_m")
    field("dist actual (rec)", dist_rec, num(3, " m"))
    field("dist target (rec)", pick([("rec", rec)], "camera_distance_target_m"), num(3, " m"))
    limit_val = pick([("rec", rec)], "camera_distance_limit_m")
    field("dist limit (rec)", limit_val, num(2, " m"))
    rows.append(_distance_violation_row(dist_rec, limit_val, geom))
    field("cam height", derived(ctx.get("camera_height_m")), num(3, " m"))
    field("ground z", pick([("sp", sp)], "support_ground_z"), num(3, " m"))
    field("elev target", pick(rec_v2, "elev_target", "elevation_deg_target"), num(2, " deg"))
    field("elev actual", pick(rec_v2, "elev_actual", "elevation_deg_actual"), num(2, " deg"))
    field("azimuth target", pick(v2_sp + [("rec", rec)], "azimuth_deg_target"), num(2, " deg"))
    field("azimuth bin", pick([("rec", rec), ("v2", v2)], "azimuth_bin"), num(0))
    field("lens", pick([("cam", cam)], "lens_mm"), num(2, " mm"))
    field("HFOV", derived(ctx.get("hfov_deg")), num(2, " deg"))
    field("fx / fy", derived(ctx.get("fxfy_text")))
    field("resolution", derived(ctx.get("resolution_text")))
    field("cam xyz", derived(ctx.get("cam_xyz_text")))

    # ---------------- TARGET / VISIBILITY ----------------
    rows.append(section("TARGET / VISIBILITY"))
    field("V target", pick([("rec", rec), ("v2", v2)], "v_target"), num(0))
    field("V_inframe", pick([("rec", rec), ("v2", v2)], "V_actual"), num(0))
    field("V_vis", pick([("rec", rec), ("v2", v2)], "V_vis", "V_vis_actual"), num(0))
    field("kp in image", derived(ctx.get("kp_in_image")), num(0))
    field("ext occ corners", pick([("v2", v2)], "ext_occ_corners_actual"), num(0))
    field("front vis", pick(v2_sp, "front_face_visibility"), num(3))
    field("open L/R", pair_val(v2_sp, ["left_opening_visibility"], ["right_opening_visibility"]))
    field("ray vis (V_vis/8)", derived(ctx.get("ray_vis_pct")), num(1, " %"))
    field("proj size target", pick([("rec", rec), ("v2", v2)],
                                   "projected_size_target", "proj_size_ratio_target"), num(4))
    field("proj size actual", pick([("rec", rec), ("v2", v2), ("pnp", pnp)],
                                   "projected_size_actual", "proj_size_ratio_actual"), num(4))
    field("proj size floor", pick([("rec", rec)], "projected_size_feasible_lower"), num(4))
    field("M0 area", derived(masks.get("m0", {}).get("area")), num(0, " px"))
    field("M4 area", derived(masks.get("m4", {}).get("area")), num(0, " px"))
    field("f static/cargo", pair_val(rec_v2, ["f_static"], ["f_cargo"]))
    field("f ctx/explicit", pair_val(rec_v2, ["f_context"], ["f_explicit"]))
    field("f total", pick(rec_v2, "f_total"), num(3))

    # ---------------- OCCLUSION CONTEXT ----------------
    rows.append(section("TRUNC / CARGO / CONTEXT / EXPLICIT"))
    field("truncation", derived(ctx.get("truncation_text")))
    field("cargo", derived(ctx.get("cargo_text")))
    field("context", derived(ctx.get("context_text")))
    field("explicit occl.", derived(ctx.get("explicit_text")))
    field("occluder asset", pick([("v2", v2), ("rec", rec)], "occluder_asset"))
    field("occl side t/a", pair_val(rec_sp, ["occluder_side_target"], ["occluder_side_actual"]))

    # ---------------- PNP ELIGIBILITY ----------------
    rows.append(section("PNP ELIGIBILITY (Phase 4)"))
    field("bbox min side", pick([("pnp", pnp)], "bbox_vis_min_side_px"), num(1, " px"))
    status("elig 2cell(16px)", pick([("pnp", pnp)], "pnp_eligible_candidate_2cell"), "YES", "NO")
    status("elig 3cell(24px)", pick([("pnp", pnp)], "pnp_eligible_candidate_3cell"), "YES", "NO")
    status("elig 4cell(32px)", pick([("pnp", pnp)], "pnp_eligible_candidate_4cell"), "YES", "NO")
    status("tiny_warning", pick([("pnp", pnp)], "tiny_warning"), "TINY", "no", invert=True)
    status("pnp_stress", pick([("pnp", pnp)], "pnp_stress"), "STRESS", "no", invert=True)
    field("pnp reproj", pick([("pnp", pnp)], "pnp_exact_reproj_mean_px"), num(3, " px"))
    field("label reproj", derived(geom.get("reproj_consistency_px")), num(4, " px"))

    # ---------------- IMAGE / SENSOR ----------------
    rows.append(section("IMAGE / SENSOR (Phase 3)"))
    field("exposure", pick([("cam", cam), ("v2", v2), ("rec", rec)], "exposure_ev"), num(3, " EV"))
    field("noise tier", pick([("rec", rec)], "noise_tier"))
    field("gaussian sigma", pick([("rec", rec)], "gaussian_sigma"), num(3))
    field("blur radius", pick([("rec", rec)], "blur_radius_px"), num(2, " px"))
    field("jpeg quality", pick([("rec", rec)], "jpeg_quality"), num(0))
    field("luma raw f/p", pair_val(rec_v2, ["luma_frame_raw", "luma_frame", "luma_actual"],
                                   ["luma_pallet_raw", "luma_pallet", "luma_pallet_actual"], 2))
    field("luma final f/p", pair_val([("rec", rec)], ["luma_frame_final"], ["luma_pallet_final"], 2))

    # ---------------- POSE ----------------
    rows.append(section("POSE"))
    field("pitch", pick([("euler", ctx.get("euler"))], "pitch"), num(2, " deg"))
    field("yaw", pick([("euler", ctx.get("euler"))], "yaw"), num(2, " deg"))
    field("roll", pick([("euler", ctx.get("euler"))], "roll"), num(2, " deg"))
    field("quat xyzw", derived(ctx.get("quat_text")))
    field("dims WxDxH", derived(ctx.get("dims_text")))
    field("loc (cam frame)", derived(ctx.get("obj_loc_text")))
    field("centroid uv", derived(ctx.get("centroid_uv_text")))
    field("kp convention", pick([("obj", obj)], "keypoint_convention"))
    return rows


def _distance_violation_row(dist: Val, limit: Val, geom: dict[str, Any]) -> Row:
    """distance > limit is the Phase 1 violation; legacy renders get an explicit fallback note."""
    limit_v = limit.value if limit.known else None
    limit_note = ""
    if limit_v is None:
        limit_v = FALLBACK_CAMERA_DISTANCE_LIMIT_M
        limit_note = f", limit {FALLBACK_CAMERA_DISTANCE_LIMIT_M:.0f}m fb"
    dist_v = dist.value if dist.known else geom.get("camera_distance_m")
    source = "record" if dist.known else "derived"
    if dist_v is None:
        return Row("dist > limit?", MISSING_TEXT, TEXT_NA, field_key="dist > limit?")
    try:
        over = float(dist_v) > float(limit_v) + 1e-6
    except (TypeError, ValueError):
        return Row("dist > limit?", NULL_TEXT, TEXT_NA, field_key="dist > limit?")
    txt = f"{'VIOLATION' if over else 'ok'} [{source}{limit_note}]"
    return Row("dist > limit?", txt, TEXT_FAIL if over else TEXT_PASS, field_key="dist > limit?")


def _pair_text(a: Any, b: Any, digits: int = 3, sep: str = " / ") -> str | None:
    """'x / y' where each side is a number, or the literal absence marker."""
    def one(v: Any) -> str | None:
        if v is None:
            return None
        return _fmt_float(v, digits)

    sa, sb = one(a), one(b)
    if sa is None and sb is None:
        return None
    return f"{sa if sa is not None else '-'}{sep}{sb if sb is not None else '-'}"


def build_context(root: Path, idx: int, lab: dict[str, Any] | None, obj: dict[str, Any] | None,
                  v2: dict[str, Any] | None, rec: dict[str, Any] | None,
                  audit: dict[str, Any] | None, pnp: dict[str, Any] | None,
                  masks: dict[str, dict[str, Any]] | None,
                  computed: dict[str, Any] | None = None,
                  geom: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the panel and the drawing need, pre-derived once per frame."""
    obj = obj if isinstance(obj, dict) else {}
    sp = obj.get("scene_placement_v2") if isinstance(obj.get("scene_placement_v2"), dict) else {}
    gates = obj.get("safety_gates") if isinstance(obj.get("safety_gates"), dict) else {}
    euler = obj.get("euler_angles") if isinstance(obj.get("euler_angles"), dict) else {}
    geom = geom if geom is not None else (frame_geometry(lab, obj) or {})
    masks = masks or {}
    rec = rec or {}
    v2 = v2 or {}
    audit = audit or {}
    pnp = pnp or {}

    ctx: dict[str, Any] = {
        "idx": idx, "root": root, "lab": lab, "obj": obj, "v2": v2, "sp": sp, "gates": gates,
        "euler": euler, "rec": rec, "audit": audit, "pnp": pnp, "geom": geom, "masks": masks,
        "computed": computed or {},
    }

    cam = (lab or {}).get("camera_data") if isinstance(lab, dict) else {}
    cam = cam if isinstance(cam, dict) else {}
    cam_pos = geom.get("cam_pos")
    ground_z = sp.get("support_ground_z")
    if cam_pos is not None and ground_z is not None:
        ctx["camera_height_m"] = float(cam_pos[2]) - float(ground_z)
    elif cam_pos is not None:
        ctx["camera_height_m"] = float(cam_pos[2])
    else:
        ctx["camera_height_m"] = None
    ctx["hfov_deg"] = hfov_deg_from_fx(geom.get("fx"), geom.get("W"))
    ctx["fxfy_text"] = _pair_text(geom.get("fx"), geom.get("fy"), 1)
    if geom.get("W") and geom.get("H"):
        ctx["resolution_text"] = f"{int(geom['W'])}x{int(geom['H'])}"
    else:
        ctx["resolution_text"] = None
    ctx["cam_xyz_text"] = (
        None if cam_pos is None else
        f"({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f})"
    )
    ctx["kp_in_image"] = in_image_count(geom.get("uv8"), geom.get("W"), geom.get("H"))

    v_vis = AUDIT.int_value(rec.get("V_vis", v2.get("V_vis_actual")))
    ctx["ray_vis_pct"] = None if v_vis is None else v_vis / 8.0 * 100.0
    f_exp = AUDIT.first_value(rec.get("f_explicit"), v2.get("f_explicit"))

    v_target = AUDIT.int_value(AUDIT.first_value(rec.get("v_target"), v2.get("v_target")))
    kp_in = ctx["kp_in_image"]
    if kp_in is None and v_target is None:
        ctx["truncation_text"] = None
    else:
        state = "unknown" if kp_in is None else ("none" if kp_in == 8 else "TRUNCATED")
        ctx["truncation_text"] = (
            f"{state} (in-img {kp_in if kp_in is not None else '-'}/8, V target "
            f"{v_target if v_target is not None else '-'})"
        )
    cargo_n = AUDIT.first_value(rec.get("n_cargo_placed"), v2.get("n_cargo_actual"))
    cargo_on = AUDIT.first_value(rec.get("cargo_on"), v2.get("cargo_on"))
    ctx["cargo_text"] = (
        None if cargo_n is None and cargo_on is None
        else f"{'ON' if AUDIT.bool_value(cargo_on) else 'off'} n={cargo_n if cargo_n is not None else '-'}"
    )
    ctx_placed = AUDIT.first_value(rec.get("n_context_placed"), sp.get("n_context_placed"))
    ctx_visible = AUDIT.first_value(rec.get("n_context_visible"), sp.get("n_context_visible"))
    ctx["context_text"] = (
        None if ctx_placed is None and ctx_visible is None
        else f"placed {ctx_placed if ctx_placed is not None else '-'} / "
             f"visible {ctx_visible if ctx_visible is not None else '-'}"
    )
    occ_placed = AUDIT.first_value(rec.get("explicit_occluder_placed"), v2.get("occluder_placed"))
    ctx["explicit_text"] = (
        None if occ_placed is None and f_exp is None
        else f"{'YES' if AUDIT.bool_value(occ_placed) else 'no'} f={_fmt_float(f_exp, 3) if f_exp is not None else '-'}"
    )
    quat = obj.get("quaternion_xyzw")
    if isinstance(quat, (list, tuple)) and len(quat) == 4:
        ctx["quat_text"] = "[" + ", ".join(_fmt_float(q, 2) for q in quat) + "]"
    else:
        ctx["quat_text"] = None
    dims = obj.get("dimensions_m") if isinstance(obj.get("dimensions_m"), dict) else None
    if dims:
        try:
            ctx["dims_text"] = (f"{float(dims['width']) * 1000:.0f}x{float(dims['depth']) * 1000:.0f}"
                                f"x{float(dims['height']) * 1000:.0f} mm")
        except (KeyError, TypeError, ValueError):
            ctx["dims_text"] = None
    else:
        ctx["dims_text"] = None
    loc = obj.get("location")
    ctx["obj_loc_text"] = (
        f"({loc[0]:.2f}, {loc[1]:.2f}, {loc[2]:.2f})"
        if isinstance(loc, (list, tuple)) and len(loc) == 3 else None
    )
    uv_c = geom.get("uv_centroid")
    ctx["centroid_uv_text"] = None if uv_c is None else f"({uv_c[0]:.1f}, {uv_c[1]:.1f})"
    ctx["cam"] = cam
    return ctx


# --------------------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------------------

def _clamped(pt: Iterable[float]) -> tuple[float, float]:
    x, y = float(pt[0]), float(pt[1])
    if not math.isfinite(x):
        x = 0.0
    if not math.isfinite(y):
        y = 0.0
    return (max(-DRAW_CLAMP_PX, min(DRAW_CLAMP_PX, x)), max(-DRAW_CLAMP_PX, min(DRAW_CLAMP_PX, y)))


def draw_scene_layer(im: Image.Image, ctx: dict[str, Any], draw_contours: bool = True) -> dict[str, Any]:
    """Contours + hull + cuboid edges + keypoints + pose axes, drawn on `im` in place."""
    stats: dict[str, Any] = {"contour_m0_px": 0, "contour_m4_px": 0, "axes_drawn": 0,
                             "cuboid_drawn": False}
    geom = ctx.get("geom") or {}
    masks = ctx.get("masks") or {}

    if draw_contours:
        arr = np.asarray(im).copy()
        # M0 (unoccluded target) drawn thicker underneath, M4 (visible target) thinner on top, so a
        # frame where occluders removed pixels shows a cyan halo outside the orange outline.
        stats["contour_m0_px"] = paint_contour(
            arr, mask_boundary(masks.get("m0", {}).get("fg"), thickness=3), COLOR_M0_CONTOUR)
        stats["contour_m4_px"] = paint_contour(
            arr, mask_boundary(masks.get("m4", {}).get("fg"), thickness=1), COLOR_M4_CONTOUR)
        im.paste(Image.fromarray(arr))

    dr = ImageDraw.Draw(im)
    uv8 = geom.get("uv8")
    if uv8 is not None and uv8.shape[0] == 8:
        hull = AUDIT.convex_hull_points(uv8)
        if hull is not None and len(hull) >= 3:
            pts = [_clamped(p) for p in hull]
            dr.line(pts + [pts[0]], fill=COLOR_HULL, width=1)
        for edge, color, width in ((REAR_EDGES, COLOR_REAR, 2), (CONN_EDGES, COLOR_CONN, 2),
                                   (FRONT_EDGES, COLOR_FRONT, 4)):
            for a, b in edge:
                dr.line([_clamped(uv8[a]), _clamped(uv8[b])], fill=color, width=width)
        w, h = geom.get("W") or im.width, geom.get("H") or im.height
        for k, pt in enumerate(uv8):
            x, y = _clamped(pt)
            inside = (0 <= pt[0] < w) and (0 <= pt[1] < h)
            color = (COLOR_FRONT if k < 4 else COLOR_REAR) if inside else COLOR_OFFSCREEN_KP
            dr.ellipse([x - 5, y - 5, x + 5, y + 5], fill=color, outline=(255, 255, 255))
            dr.text((x + 6, y - 6), str(k), fill=(255, 255, 0), font=SMALL_FONT)
        stats["cuboid_drawn"] = True
    uv_c = geom.get("uv_centroid")
    if uv_c is not None:
        x, y = _clamped(uv_c)
        dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=COLOR_CENTROID)

    axes = pose_axis_endpoints(geom)
    for axis in axes or []:
        if not axis.get("ok"):
            continue
        start, end = _clamped(axis["start"]), _clamped(axis["end"])
        dr.line([start, end], fill=axis["color"], width=3)
        dr.ellipse([end[0] - 4, end[1] - 4, end[0] + 4, end[1] + 4], fill=axis["color"],
                   outline=(0, 0, 0))
        dr.text((end[0] + 5, end[1] + 4), axis["label"], fill=axis["color"], font=SMALL_FONT)
        stats["axes_drawn"] += 1
    return stats


LEGEND_ITEMS = (
    ("X axis", AXIS_COLORS[0]),
    ("Y axis", AXIS_COLORS[1]),
    ("Z axis", AXIS_COLORS[2]),
    ("FRONT 0-3", COLOR_FRONT),
    ("REAR 4-7", COLOR_REAR),
    ("connector", COLOR_CONN),
    ("cuboid hull", COLOR_HULL),
    ("M0 contour", COLOR_M0_CONTOUR),
    ("M4 contour", COLOR_M4_CONTOUR),
)


def draw_legend(dr: ImageDraw.ImageDraw, x: int, y: int) -> tuple[int, int]:
    w, h = 92, 12 * len(LEGEND_ITEMS) + 8
    dr.rectangle([x, y, x + w, y + h], fill=(0, 0, 0))
    for i, (name, color) in enumerate(LEGEND_ITEMS):
        yy = y + 4 + i * 12
        dr.rectangle([x + 4, yy + 2, x + 12, yy + 9], fill=color)
        dr.text((x + 16, yy), name, fill=(235, 235, 235), font=SMALL_FONT)
    return w, h


def layout_rows(rows: list[Row], rows_per_col: int) -> list[dict[str, Any]]:
    """Split rows into columns at section boundaries and assign (col, y_index) per row."""
    rows_per_col = max(1, int(rows_per_col))
    placed: list[dict[str, Any]] = []
    col, y = 0, 0
    for i, row in enumerate(rows):
        if y >= rows_per_col:
            col += 1
            y = 0
        elif row.kind == "section" and y > 0 and y + 2 > rows_per_col:
            col += 1
            y = 0
        placed.append({"row": row, "col": col, "line": y, "index": i})
        y += 1
    return placed


def panel_size(rows: list[Row], cols: int = PANEL_COLS,
               min_height: int = 0) -> tuple[int, int, int]:
    """(width, height, rows_per_col) for `len(rows)` rows over `cols` columns."""
    cols = max(1, int(cols))
    rows_per_col = int(math.ceil(len(rows) / cols)) if rows else 1
    height_needed = rows_per_col * ROW_H + 2 * PANEL_PAD
    height = max(min_height, height_needed)
    rows_per_col = max(rows_per_col, (height - 2 * PANEL_PAD) // ROW_H)
    return cols * PANEL_COL_W, height, int(rows_per_col)


def fit_text(dr: ImageDraw.ImageDraw, s: str, max_w: float) -> str:
    """Hard-clip a value so it can never bleed into the next panel column."""
    if not s:
        return s
    try:
        if dr.textlength(s, font=SMALL_FONT) <= max_w:
            return s
    except Exception:  # pragma: no cover - very old PIL
        return s
    out = s
    while out and dr.textlength(out + "~", font=SMALL_FONT) > max_w:
        out = out[:-1]
    return out + "~"


def draw_panel(im: Image.Image, rows: list[Row], origin_x: int, cols: int, rows_per_col: int) -> None:
    dr = ImageDraw.Draw(im)
    dr.rectangle([origin_x, 0, im.width, im.height], fill=PANEL_BG)
    value_w = PANEL_COL_W - LABEL_W - 10
    for placed in layout_rows(rows, rows_per_col):
        row = placed["row"]
        x = origin_x + PANEL_PAD + placed["col"] * PANEL_COL_W
        y = PANEL_PAD + placed["line"] * ROW_H
        if row.kind == "section":
            dr.rectangle([x - 2, y, x + PANEL_COL_W - 10, y + ROW_H - 2], fill=SECTION_BG)
            dr.text((x + 2, y + 1), row.label, fill=(255, 255, 255), font=SMALL_FONT)
            continue
        dr.text((x, y + 1), fit_text(dr, f"{row.label}:", LABEL_W - 4), fill=TEXT_LABEL,
                font=SMALL_FONT)
        dr.text((x + LABEL_W, y + 1), fit_text(dr, row.text, value_w), fill=row.color,
                font=SMALL_FONT)


def render_overlay(base: Image.Image | None, ctx: dict[str, Any], out_path: Path | None = None,
                   cols: int = PANEL_COLS) -> tuple[Image.Image, dict[str, Any]]:
    """Compose the full detailed overlay: RGB + scene layer on the left, info panel on the right."""
    rows = build_sections(ctx)
    geom = ctx.get("geom") or {}
    if base is None:
        w = int(geom.get("W") or 640)
        h = int(geom.get("H") or 480)
        base = Image.new("RGB", (w, h), (35, 35, 35))
        missing_rgb = True
    else:
        base = base.convert("RGB").copy()
        missing_rgb = False
    stats = draw_scene_layer(base, ctx)

    panel_w, panel_h, rows_per_col = panel_size(rows, cols, min_height=base.height)
    canvas = Image.new("RGB", (base.width + panel_w, max(base.height, panel_h)), (12, 12, 12))
    canvas.paste(base, (0, 0))
    draw_panel(canvas, rows, base.width, cols, rows_per_col)

    dr = ImageDraw.Draw(canvas)
    idx = ctx.get("idx")
    header = (f"f{int(idx):04d}" if idx is not None else "f????")
    audit = ctx.get("audit") or {}
    rec = ctx.get("rec") or {}
    header += (f"  mode={rec.get('diagnostic_mode') or (ctx.get('sp') or {}).get('diagnostic_mode') or '-'}"
               f"  audit={audit.get('audit_pass')}  gate={AUDIT.first_value(rec.get('all_pass'), audit.get('all_pass_gate'))}")
    if missing_rgb:
        header += "  [RGB MISSING/UNREADABLE]"
    dr.rectangle([0, 0, base.width, 18], fill=(0, 0, 0))
    dr.text((4, 3), header, fill=(255, 255, 255), font=SMALL_FONT)
    lw, lh = draw_legend(dr, 4, base.height - (12 * len(LEGEND_ITEMS) + 8) - 4)

    stats.update({
        "rows": len(rows),
        "rows_per_col": rows_per_col,
        "canvas": [canvas.width, canvas.height],
        "na_absent": [r.label for r in rows if r.is_absent],
        "na_null": [r.label for r in rows if r.kind == "field" and r.text == NULL_TEXT],
        "rgb_present": not missing_rgb,
    })
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path)
    return canvas, stats


# --------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------

def compute_mask_fallback(masks: dict[str, dict[str, Any]], mask_names: list[str],
                          geom: dict[str, Any] | None = None) -> dict[str, Any]:
    """Phase 5 numbers computed here when no audit CSV is available (audit helpers reused)."""
    out: dict[str, Any] = {}
    payload = {name: {"fg": m.get("fg"), "decode_ok": m.get("decode_ok"),
                      "present": m.get("present"), "area": m.get("area")}
               for name, m in masks.items()}
    if len([m for m in payload.values() if m.get("fg") is not None]) >= 2:
        result = AUDIT.mask_pixel_inclusion(payload, mask_names)
        out["mask_pixel_inclusion_ok"] = result.get("ok")
        out["mask_pixel_inclusion_violation_px"] = result.get("violation_px_total")
    geom = geom or {}
    hull = AUDIT.convex_hull_points(geom.get("uv8")) if geom.get("uv8") is not None else None
    if hull is not None:
        for name, key in (("m0", "mask_m0_hull_bbox_iou"), ("m4", "mask_m4_hull_bbox_iou")):
            fg = masks.get(name, {}).get("fg")
            if fg is None:
                continue
            out[key] = AUDIT.hull_alignment(fg, hull, geom.get("W"), geom.get("H")).get("bbox_iou")
    return out


def render_dataset(root: Path, out_dir: Path, args) -> dict[str, Any]:
    mask_names = [n.strip() for n in args.mask_names.split(",") if n.strip()]
    records, _ = AUDIT.load_records(root)
    indices = AUDIT.discover_indices(root, records, mask_names)
    if args.indices:
        wanted = {int(i) for i in args.indices.split(",") if i.strip()}
        indices = [i for i in indices if i in wanted]
    if args.max_frames is not None:
        indices = indices[: args.max_frames]

    audit_csv = find_audit_csv(root, args.audit_csv)
    pnp_csv = find_pnp_csv(root, args.pnp_csv)
    audit_rows = load_csv_rows(audit_csv)
    pnp_rows = load_csv_rows(pnp_csv)

    overlay_dir = out_dir / OVERLAY_DIRNAME
    overlay_dir.mkdir(parents=True, exist_ok=True)
    na_absent: dict[str, int] = {}
    na_null: dict[str, int] = {}
    written: list[Path] = []
    per_frame: list[dict[str, Any]] = []

    for idx in indices:
        lab, obj, v2 = AUDIT.load_label(root, idx)
        rgb, rgb_info = AUDIT.strict_open_rgb(root / "rgb" / f"f{idx:04d}_rgb.png")
        masks = {name: load_mask_foreground(root, idx, name) for name in mask_names}
        geom = frame_geometry(lab, obj) or {}
        computed = {} if audit_rows else compute_mask_fallback(masks, mask_names, geom)
        ctx = build_context(root, idx, lab, obj, v2, records.get(idx), audit_rows.get(idx),
                            pnp_rows.get(idx), masks, computed, geom)
        out_path = overlay_dir / f"f{idx:04d}.png"
        _, stats = render_overlay(rgb, ctx, out_path, cols=args.panel_cols)
        written.append(out_path)
        for label in stats["na_absent"]:
            na_absent[label] = na_absent.get(label, 0) + 1
        for label in stats["na_null"]:
            na_null[label] = na_null.get(label, 0) + 1
        per_frame.append({
            "idx": idx, "rgb_decode_ok": rgb_info.get("decode_ok"),
            "contour_m0_px": stats["contour_m0_px"], "contour_m4_px": stats["contour_m4_px"],
            "axes_drawn": stats["axes_drawn"], "cuboid_drawn": stats["cuboid_drawn"],
            "canvas": stats["canvas"], "n_absent": len(stats["na_absent"]),
        })

    sheets = make_detailed_sheets(written, out_dir / "contact_sheets", args.sheet_frames,
                                  args.sheet_cell_w)
    manifest = {
        "dataset": str(root),
        "out": str(out_dir),
        "frames": len(written),
        "overlay_dir": str(overlay_dir),
        "audit_csv": str(audit_csv) if audit_csv else None,
        "pnp_csv": str(pnp_csv) if pnp_csv else None,
        "mask_names": mask_names,
        "contact_sheets": sheets,
        "na_field_absent_counts": dict(sorted(na_absent.items(), key=lambda kv: -kv[1])),
        "na_field_null_counts": dict(sorted(na_null.items(), key=lambda kv: -kv[1])),
        "per_frame": per_frame,
    }
    (out_dir / "overlay_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def make_detailed_sheets(paths: list[Path], out_dir: Path, per_page: int,
                         cell_w: int) -> list[dict[str, Any]]:
    """Contact sheets sized for WIDE detailed overlays (the audit default cell is too small)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [p for p in paths if p.exists()]
    pages: list[dict[str, Any]] = []
    if not paths:
        return pages
    chunks = [paths[i:i + per_page] for i in range(0, len(paths), per_page)]
    for page_no, chunk in enumerate(chunks, 1):
        with Image.open(chunk[0]) as first:
            aspect = first.height / first.width
        cell = (cell_w, max(1, int(cell_w * aspect)))
        cols = min(3, len(chunk))
        rows_n = int(math.ceil(len(chunk) / cols))
        header = 26
        sheet = Image.new("RGB", (cols * cell[0], header + rows_n * (cell[1] + 14)), (18, 18, 18))
        dr = ImageDraw.Draw(sheet)
        dr.text((8, 5), f"Detailed overlays page {page_no}/{len(chunks)}", fill=(255, 255, 255),
                font=FONT)
        for i, path in enumerate(chunk):
            try:
                with Image.open(path) as im:
                    thumb = AUDIT.resize_fit(im, cell)
            except Exception:
                thumb = Image.new("RGB", cell, (60, 0, 0))
            x = (i % cols) * cell[0]
            y = header + (i // cols) * (cell[1] + 14)
            sheet.paste(thumb, (x, y))
            ImageDraw.Draw(sheet).text((x + 4, y + cell[1]), path.stem, fill=(255, 255, 0),
                                       font=SMALL_FONT)
        name = f"detailed_{page_no:03d}.png"
        sheet.save(out_dir / name)
        pages.append({"file": name, "frames": len(chunk)})
    return pages


PROTECTED_OVERLAY_DIRS = ("eda/overlay_all", "eda_phase5/overlay_all")


def guard_output_dir(root: Path, out_dir: Path) -> None:
    """Never write into the pre-existing audit overlay directories."""
    resolved = out_dir.resolve()
    for rel in PROTECTED_OVERLAY_DIRS:
        if resolved == (root / rel).resolve() or (resolved / OVERLAY_DIRNAME).resolve() == (root / rel).resolve():
            raise SystemExit(f"refusing to write into the existing audit overlay dir: {root / rel}")
    if (resolved / OVERLAY_DIRNAME).exists() and any((resolved / OVERLAY_DIRNAME).glob("*.png")):
        if not getattr(guard_output_dir, "allow_overwrite", False):
            print(f"[overlay] note: {resolved / OVERLAY_DIRNAME} already has PNGs; they will be replaced")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detailed per-frame overlays for v2 frames (Phase 6).")
    p.add_argument("--dir", default=DEFAULT_DIR, help="Dataset root (rgb/, labels/, mask/).")
    p.add_argument("--out", default=None, help=f"Output dir. Default: <dir>/{DEFAULT_OUT_DIRNAME}")
    p.add_argument("--audit-csv", default=None, help="audit_frames.csv (auto: eda_phase5 then eda).")
    p.add_argument("--pnp-csv", default=None, help="pnp_threshold_study.csv from Phase 4.")
    p.add_argument("--mask-names", default=",".join(MASK_NAMES))
    p.add_argument("--indices", default=None, help="Comma separated frame indices.")
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--panel-cols", type=int, default=PANEL_COLS)
    p.add_argument("--sheet-frames", type=int, default=12, help="Overlays per contact sheet page.")
    p.add_argument("--sheet-cell-w", type=int, default=480, help="Contact sheet cell width (px).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.dir).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve() if args.out else root / DEFAULT_OUT_DIRNAME
    if not root.exists():
        print(f"[overlay] dataset not found: {root}")
        return 2
    guard_output_dir(root, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = render_dataset(root, out_dir, args)
    print(f"[overlay] frames={manifest['frames']} -> {manifest['overlay_dir']}")
    print(f"[overlay] audit_csv={manifest['audit_csv']} pnp_csv={manifest['pnp_csv']}")
    print(f"[overlay] sheets={len(manifest['contact_sheets'])} manifest={out_dir / 'overlay_manifest.json'}")
    absent = manifest["na_field_absent_counts"]
    if absent:
        top = ", ".join(f"{k}={v}" for k, v in list(absent.items())[:8])
        print(f"[overlay] fields absent in this render ({len(absent)} distinct): {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
