"""Paper-oriented continuous EDA for the v2 constrained Blender pipeline.

This module is deliberately separate from ``analyze_v2_scene_logic.py`` (which stays
the bin/bar diagnostic report).  Here every genuinely continuous control variable is
described with an ECDF (primary) plus a bandwidth-documented KDE (secondary), and
pass-rates are shown as kernel-smoothed Bernoulli probability curves with bootstrap
confidence bands instead of hand-picked bins.

Design rules that are enforced in code, not just documented:

* Variables that are intrinsically discrete (``V``, ``G1..G5``, ``cargo_on``,
  ``scene_preset``, ``noise_tier``, ...) are listed in :data:`DISCRETE_FIELDS` and the
  KDE entry points raise :class:`DiscreteVariableError` when handed one.  Discrete
  variables get bar/dot/table appendix output only.
* ``azimuth`` is circular: a von Mises KDE on the circle is used, never a linear one,
  so the density is continuous across the 0/360 deg seam (verified numerically and
  reported in ``continuous_summary.json``).
* Zero-inflated occlusion fractions are split into an explicit point mass ``P(X = 0)``
  and a conditional ECDF/KDE over ``X > 0``.  The zero spike is never smoothed.
* Missing values are ``None`` only.  ``0``, ``0.0`` and ``False`` are real
  observations; every fallback uses ``value if value is not None else default`` and
  never ``value or default``.
* Bounded variables keep their support: no density mass is drawn outside
  ``[0, camera_distance_limit]``, the elevation prescription range, or ``[0, 1]``.

Outputs (under ``<dataset>/eda/paper_continuous`` by default)::

    figures_png/*.png   300 dpi
    figures_pdf/*.pdf   vector twins of the same figures
    continuous_metrics.csv
    continuous_summary.json
    discrete_counts.csv
    paper_continuous_summary.md

All axis and legend text is English.  Every figure carries a caption stating the
denominator and the missing count that produced it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tempfile
import warnings
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


DEFAULT_DIR = "data/pallet/_v2_scene_logic_500_seed7500"
DEFAULT_OUT_SUBDIR = "eda/paper_continuous"
DEFAULT_PNP_MANIFEST = "reports/v2_revision/pnp_eligibility_manifest.csv"
DEFAULT_PNP_STUDY = "reports/v2_revision/pnp_threshold_study.csv"

FIGURE_DPI = 300
GRID_POINTS = 200
BOOTSTRAP_DEFAULT = 1000
BOOTSTRAP_SEED_DEFAULT = 1000
MIN_N_EFF = 20.0
MIN_KDE_SAMPLES = 8

# Prescription supports (v2_pipeline.py: ELEV_BIN_EDGES, PROJ_SIZE_EDGES,
# EXPOSURE_EV_RANGE, MAX_CAMERA_DISTANCE_M).  Density is clipped to these ranges.
DOMAIN_CAMERA_DISTANCE = (0.0, 10.0)
DOMAIN_ELEVATION = (0.5, 80.0)
DOMAIN_PROJ_SIZE = (0.0, 1.0)
DOMAIN_UNIT = (0.0, 1.0)
DOMAIN_EXPOSURE = (-3.0, 0.2)
DOMAIN_LUMA = (0.0, 255.0)

QUANTILE_LEVELS = (0.05, 0.25, 0.50, 0.75, 0.95)

COLORS = {
    "target": "#4C72B0",
    "actual": "#DD8452",
    "third": "#55A868",
    "fourth": "#C44E52",
    "grey": "#7F7F7F",
}


# --------------------------------------------------------------------------------------
# Field schema
# --------------------------------------------------------------------------------------
# ``FIELD_SOURCES[out_key] = [(container, key), ...]``; the first container that holds a
# non-missing value wins.  Containers: rec (records.jsonl row), cam (label camera_data),
# intr (camera_data.intrinsics), v2 (objects[0].v2_labels),
# sp (objects[0].scene_placement_v2), gates (objects[0].safety_gates),
# spec (records_rejected.jsonl proposal spec), pnp (PnP eligibility manifest row).
FIELD_SOURCES: dict[str, list[tuple[str, str]]] = {
    # ---- Phase 1: camera distance / projected size ----
    "camera_distance_limit_m": [("rec", "camera_distance_limit_m"), ("v2", "camera_distance_limit_m"), ("pnp", "camera_distance_limit_m")],
    "camera_distance_target_m": [("rec", "camera_distance_target_m"), ("v2", "camera_distance_target_m")],
    "camera_distance_actual_m": [("rec", "camera_distance_actual_m"), ("v2", "camera_distance_actual_m"), ("pnp", "camera_distance_measured_m")],
    "camera_distance_error_m": [("rec", "camera_distance_error_m"), ("v2", "camera_distance_error_m")],
    "projected_size_feasible_lower": [("rec", "projected_size_feasible_lower"), ("v2", "projected_size_feasible_lower"), ("spec", "proj_size_feasible_lower")],
    "projected_size_target": [("rec", "projected_size_target"), ("v2", "proj_size_ratio_target"), ("v2", "projected_size_target"), ("spec", "proj_size_ratio")],
    "projected_size_actual": [("rec", "projected_size_actual"), ("v2", "projected_size_actual"), ("pnp", "projected_size_actual")],
    # ---- camera geometry ----
    "elevation_deg_target": [("rec", "elev_target"), ("v2", "elevation_deg_target"), ("spec", "elevation_deg")],
    "elevation_deg_actual": [("rec", "elev_actual"), ("v2", "elevation_deg_actual"), ("pnp", "elevation_deg_actual")],
    "azimuth_deg_target": [("v2", "azimuth_deg_target"), ("rec", "azimuth_deg_target"), ("rec", "azimuth_deg"), ("spec", "azimuth_deg")],
    "fx": [("rec", "fx"), ("intr", "fx"), ("spec", "fx"), ("pnp", "fx")],
    "exposure_ev": [("rec", "exposure_ev"), ("cam", "exposure_ev"), ("v2", "exposure_ev"), ("spec", "exposure_ev")],
    # ---- Phase 3: final-RGB quality ----
    "luma_frame_raw": [("rec", "luma_frame_raw"), ("v2", "luma_frame_raw")],
    "luma_pallet_raw": [("rec", "luma_pallet_raw"), ("v2", "luma_pallet_raw")],
    "luma_frame_final": [("rec", "luma_frame_final"), ("v2", "luma_frame_final")],
    "luma_pallet_final": [("rec", "luma_pallet_final"), ("v2", "luma_pallet_final")],
    "gaussian_sigma": [("rec", "gaussian_sigma")],
    "blur_radius_px": [("rec", "blur_radius_px")],
    "jpeg_quality": [("rec", "jpeg_quality")],
    "vignette_strength": [("rec", "vignette_strength")],
    # ---- occlusion decomposition ----
    "f_static": [("rec", "f_static"), ("v2", "f_static")],
    "f_cargo": [("rec", "f_cargo"), ("v2", "f_cargo")],
    "f_context": [("rec", "f_context"), ("v2", "f_context")],
    "f_explicit": [("rec", "f_explicit"), ("v2", "f_explicit")],
    "f_total": [("rec", "f_total"), ("v2", "f_total")],
    "f_target": [("rec", "f_target"), ("v2", "f_target"), ("spec", "f_target")],
    "f_explicit_target": [("rec", "f_explicit_target"), ("sp", "f_explicit_target")],
    "f_explicit_actual": [("rec", "f_explicit_actual"), ("sp", "f_explicit_actual")],
    "explicit_abs_error": [("rec", "explicit_abs_error"), ("sp", "explicit_abs_error")],
    # ---- misc continuous ----
    "runtime_s": [("rec", "runtime_s")],
    "mask_area_m0_px": [("rec", "mask_area_target_only"), ("v2", "mask_area_target_only"), ("rec", "mask_m0_area_px"), ("pnp", "mask_m0_area")],
    "mask_area_visible_px": [("rec", "mask_area_visible"), ("v2", "mask_area_visible")],
    "bbox_vis_min_side_px": [("pnp", "bbox_vis_min_side_px")],
    "visible_kp_count": [("pnp", "visible_kp_count")],
    # ---- discrete / categorical ----
    "diagnostic_mode": [("rec", "diagnostic_mode"), ("v2", "diagnostic_mode"), ("sp", "diagnostic_mode"), ("spec", "diagnostic_mode")],
    "scene_preset": [("rec", "scene_preset"), ("cam", "scene_preset"), ("spec", "scene_preset")],
    "pallet_type": [("rec", "pallet_type"), ("v2", "pallet_type"), ("spec", "pallet_type")],
    "background_asset": [("rec", "background_asset"), ("cam", "background_asset"), ("spec", "background_asset")],
    "aspect": [("rec", "aspect"), ("cam", "aspect_label"), ("spec", "aspect")],
    "resolution": [("rec", "resolution"), ("cam", "resolution"), ("spec", "resolution")],
    "fx_mode": [("rec", "fx_mode"), ("cam", "fx_mode"), ("spec", "fx_mode")],
    "noise_tier": [("rec", "noise_tier")],
    "cargo_on": [("rec", "cargo_on"), ("v2", "cargo_on"), ("spec", "cargo_on")],
    "occluder_side_target": [("rec", "occluder_side_target"), ("sp", "occluder_side_target")],
    "occluder_side_actual": [("rec", "occluder_side_actual"), ("sp", "occluder_side_actual")],
    "v_target": [("rec", "v_target"), ("v2", "v_target"), ("spec", "v_target")],
    "V_actual": [("rec", "V_actual"), ("v2", "V_actual")],
    "V_vis": [("rec", "V_vis"), ("v2", "V_vis_actual")],
    "elev_bin_target": [("rec", "elev_bin"), ("v2", "elev_bin_target"), ("spec", "elev_bin")],
    "azimuth_bin": [("rec", "azimuth_bin"), ("v2", "azimuth_bin"), ("spec", "azimuth_bin")],
    "proj_size_bin_target": [("rec", "proj_size_bin"), ("v2", "proj_size_bin_target"), ("spec", "proj_size_bin")],
    "reject_reason": [("rec", "reject_reason")],
    # ---- gates / outcomes ----
    "G1_pass": [("rec", "G1_pass"), ("gates", "G1_Vvis>=4")],
    "G2_pass": [("rec", "G2_pass"), ("gates", "G2_extocc_1to4")],
    "G3_pass": [("rec", "G3_pass"), ("gates", "G3_visible>=0.5unocc")],
    "G4_pass": [("rec", "G4_pass"), ("gates", "G4_center_inframe")],
    "G5_pass": [("rec", "G5_pass"), ("gates", "G5_luma_floor")],
    "all_pass": [("rec", "all_pass"), ("gates", "all_pass")],
    "rendered": [("rec", "rendered")],
    "realize_ok": [("rec", "realize_ok")],
    "usable": [("rec", "usable")],
    # ---- Phase 2 / 4 / 5 / 7 audit outcomes ----
    "ground_continuity_pass": [("rec", "ground_continuity_pass")],
    "mask_pixel_inclusion_ok": [("rec", "mask_pixel_inclusion_ok")],
    "physical_valid": [("pnp", "physical_valid"), ("rec", "physical_valid")],
    "gate_valid": [("pnp", "gate_valid"), ("rec", "gate_valid")],
    "tiny_warning": [("pnp", "tiny_warning"), ("rec", "tiny_warning")],
    "pnp_stress": [("pnp", "pnp_stress"), ("rec", "pnp_stress")],
    "pnp_exact_success": [("pnp", "pnp_exact_success")],
    "pnp_eligible_candidate_2cell": [("pnp", "pnp_eligible_candidate_2cell")],
    "pnp_eligible_candidate_3cell": [("pnp", "pnp_eligible_candidate_3cell")],
    "pnp_eligible_candidate_4cell": [("pnp", "pnp_eligible_candidate_4cell")],
    "pnp_size_eligible_2cell": [("rec", "pnp_size_eligible_2cell")],
    "pnp_size_eligible_3cell": [("rec", "pnp_size_eligible_3cell")],
    "pnp_size_eligible_4cell": [("rec", "pnp_size_eligible_4cell")],
}

BOOL_FIELDS = {
    "cargo_on", "G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass", "all_pass",
    "rendered", "realize_ok", "usable", "ground_continuity_pass",
    "mask_pixel_inclusion_ok", "physical_valid", "gate_valid", "tiny_warning",
    "pnp_stress", "pnp_exact_success", "pnp_eligible_candidate_2cell",
    "pnp_eligible_candidate_3cell", "pnp_eligible_candidate_4cell",
    "pnp_size_eligible_2cell", "pnp_size_eligible_3cell", "pnp_size_eligible_4cell",
}

# Discrete by construction.  KDE on any of these is a bug, so it is blocked in code.
DISCRETE_FIELDS = frozenset({
    "pallet_type", "scene_preset", "background_asset", "aspect", "resolution",
    "fx_mode", "cargo_on", "diagnostic_mode", "noise_tier", "occluder_side_target",
    "occluder_side_actual", "reject_reason", "v_target", "V_actual", "V_vis",
    "visible_kp_count", "elev_bin_target", "azimuth_bin", "proj_size_bin_target",
    "G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass", "all_pass", "rendered",
    "realize_ok", "usable", "ground_continuity_pass", "mask_pixel_inclusion_ok",
    "physical_valid", "gate_valid", "tiny_warning", "pnp_stress", "pnp_exact_success",
    "pnp_eligible_candidate_2cell", "pnp_eligible_candidate_3cell",
    "pnp_eligible_candidate_4cell", "pnp_size_eligible_2cell",
    "pnp_size_eligible_3cell", "pnp_size_eligible_4cell", "jpeg_quality",
})

CATEGORICAL_APPENDIX_FIELDS = [
    "pallet_type", "scene_preset", "background_asset", "aspect", "resolution",
    "fx_mode", "cargo_on", "diagnostic_mode", "noise_tier", "v_target", "V_actual",
    "V_vis", "occluder_side_target", "occluder_side_actual", "reject_reason",
    "G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass", "all_pass",
]

MISSING_LABEL = "(missing)"


class DiscreteVariableError(ValueError):
    """Raised when a KDE is requested for an intrinsically discrete variable."""


# --------------------------------------------------------------------------------------
# Small typed accessors (never truthiness-based)
# --------------------------------------------------------------------------------------
def is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, float) and not math.isfinite(v):
        return True
    return False


def pick(*values: Any) -> Any:
    """First non-missing value.  ``0``/``0.0``/``False`` count as present."""
    for v in values:
        if not is_missing(v):
            return v
    return None


def group_label(v: Any, missing_value: str = MISSING_LABEL) -> str:
    """String group key that keeps ``0``/``0.0``/``False`` out of the missing bucket."""
    if is_missing(v):
        return missing_value
    return str(v)


def float_value(v: Any) -> float | None:
    if is_missing(v):
        return None
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def bool_value(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y"):
            return True
        if s in ("false", "0", "no", "n"):
            return False
    return None


def finite_array(values: Iterable[Any]) -> np.ndarray:
    out = [f for v in values if (f := float_value(v)) is not None]
    return np.asarray(out, dtype=np.float64)


def paired_finite(xs: Iterable[Any], ys: Iterable[Any]) -> tuple[np.ndarray, np.ndarray]:
    ax: list[float] = []
    ay: list[float] = []
    for xv, yv in zip(xs, ys):
        fx = float_value(xv)
        fy = float_value(yv)
        if fx is not None and fy is not None:
            ax.append(fx)
            ay.append(fy)
    return np.asarray(ax, dtype=np.float64), np.asarray(ay, dtype=np.float64)


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [dict(r) for r in csv.DictReader(stream)]


def _label_containers(label: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cam = label.get("camera_data") if isinstance(label.get("camera_data"), dict) else {}
    objects = label.get("objects") if isinstance(label.get("objects"), list) else []
    obj = objects[0] if objects and isinstance(objects[0], dict) else {}
    return {
        "cam": cam,
        "intr": cam.get("intrinsics") if isinstance(cam.get("intrinsics"), dict) else {},
        "v2": obj.get("v2_labels") if isinstance(obj.get("v2_labels"), dict) else {},
        "sp": obj.get("scene_placement_v2") if isinstance(obj.get("scene_placement_v2"), dict) else {},
        "gates": obj.get("safety_gates") if isinstance(obj.get("safety_gates"), dict) else {},
    }


def _idx_of(stem: str) -> int | None:
    digits = "".join(ch for ch in stem.split("_")[0] if ch.isdigit())
    return int(digits) if digits else None


def build_row(containers: dict[str, dict[str, Any]], level: str) -> dict[str, Any]:
    row: dict[str, Any] = {"level": level}
    for out_key, sources in FIELD_SOURCES.items():
        value = None
        for container, key in sources:
            candidate = containers.get(container, {}).get(key)
            if not is_missing(candidate):
                value = candidate
                break
        if out_key in BOOL_FIELDS:
            value = bool_value(value)
        row[out_key] = value
    if isinstance(row.get("resolution"), (list, tuple)):
        row["resolution"] = "x".join(str(int(v)) for v in row["resolution"])
    return row


def _audit_source_dataset(csv_path: Path) -> str | None:
    """Read the dataset this audit CSV was produced from, if its sibling JSON says so."""
    for sibling in (csv_path.with_suffix(".json"),
                    csv_path.parent / f"{csv_path.stem}.json"):
        if not sibling.exists():
            continue
        try:
            blob = json.loads(sibling.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(blob, dict) and isinstance(blob.get("dataset"), str):
            return blob["dataset"]
    return None


def _load_audit_csv(csv_path: Path | None, root: Path) -> tuple[dict[int, dict[str, Any]], str | None]:
    if csv_path is None or not csv_path.exists():
        return {}, None
    source = _audit_source_dataset(csv_path)
    if source is not None:
        try:
            same = Path(source).resolve() == root.resolve()
        except OSError:
            same = False
        if not same:
            return {}, (f"{csv_path.name} was generated from '{source}', not from "
                        f"'{root}'; it was not joined (frame ids repeat across datasets)")
    rows: dict[int, dict[str, Any]] = {}
    for r in _read_csv(csv_path):
        try:
            rows[int(r["idx"])] = r
        except (KeyError, TypeError, ValueError):
            continue
    return rows, (None if source is not None else
                  f"{csv_path.name} has no sibling JSON declaring its source dataset; "
                  f"joined on idx without a provenance check")


def load_dataset(
    root: Path,
    pnp_manifest_path: Path | None = None,
    pnp_study_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge records / labels / audit manifests into flat proposal-level rows."""
    records: dict[int, dict[str, Any]] = {}
    record_rows = _read_jsonl(root / "records.jsonl")
    if not record_rows and (root / "records.json").exists():
        blob = json.loads((root / "records.json").read_text(encoding="utf-8"))
        if isinstance(blob, list):
            record_rows = [r for r in blob if isinstance(r, dict)]
        elif isinstance(blob, dict) and isinstance(blob.get("records"), list):
            record_rows = [r for r in blob["records"] if isinstance(r, dict)]
    for r in record_rows:
        idx = r.get("idx")
        if isinstance(idx, int):
            records[idx] = r

    labels: dict[int, dict[str, Any]] = {}
    label_dir = root / "labels"
    if label_dir.is_dir():
        for path in sorted(label_dir.glob("*.json")):
            idx = _idx_of(path.stem)
            if idx is None:
                continue
            try:
                labels[idx] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue

    # Audit manifests are keyed by idx and their frame ids (f0000...) repeat across
    # datasets, so an idx join alone would silently mix two renders.  Only accept a
    # manifest whose sibling JSON declares this dataset as its source.
    pnp, pnp_rejected = _load_audit_csv(pnp_manifest_path, root)
    study, study_rejected = _load_audit_csv(pnp_study_path, root)

    schema_keys: set[str] = set()
    rows: list[dict[str, Any]] = []
    # Rows come from this dataset's own records/labels only; audit manifests are joined
    # onto them and never create rows of their own.
    for idx in sorted(set(records) | set(labels)):
        rec = records.get(idx, {})
        label = labels.get(idx, {})
        containers = {"rec": rec, "spec": {}, "pnp": pnp.get(idx, {})}
        containers.update(_label_containers(label))
        for name, blob in containers.items():
            schema_keys.update(f"{name}.{k}" for k in blob)
        row = build_row(containers, level="frame")
        row["idx"] = idx
        row["label_present"] = bool(label)
        row["record_present"] = bool(rec)
        row["pnp_present"] = idx in pnp
        row["study"] = study.get(idx, {})
        if row.get("rendered") is None:
            row["rendered"] = bool(label)
        rows.append(row)

    # Rejected proposals (Phase 7 usable runner) carry only the sampled spec.
    for rej in _read_jsonl(root / "records_rejected.jsonl"):
        spec = rej.get("spec") if isinstance(rej.get("spec"), dict) else {}
        rec = rej.get("record") if isinstance(rej.get("record"), dict) else {}
        containers = {"rec": rec, "spec": spec, "pnp": {}, "cam": {}, "intr": {}, "v2": {}, "sp": {}, "gates": {}}
        for name, blob in containers.items():
            schema_keys.update(f"{name}.{k}" for k in blob)
        row = build_row(containers, level="proposal_rejected")
        row["idx"] = rej.get("proposal_index")
        row["label_present"] = False
        row["record_present"] = bool(rec)
        row["pnp_present"] = False
        row["study"] = {}
        row["rendered"] = False
        row["reject_reason"] = pick(rej.get("reject_reason"), row.get("reject_reason"))
        row["stage"] = rej.get("stage")
        rows.append(row)

    meta = {
        "root": str(root),
        "n_rows": len(rows),
        "n_records": len(records),
        "n_labels": len(labels),
        "n_pnp_manifest": len(pnp),
        "n_pnp_study": len(study),
        "n_rejected_proposals": sum(1 for r in rows if r["level"] == "proposal_rejected"),
        "pnp_manifest_path": str(pnp_manifest_path) if pnp_manifest_path else None,
        "pnp_study_path": str(pnp_study_path) if pnp_study_path else None,
        "pnp_manifest_join_note": pnp_rejected,
        "pnp_study_join_note": study_rejected,
        "n_pnp_manifest_joined": sum(1 for r in rows if r.get("pnp_present")),
        "schema_keys": sorted(schema_keys),
    }
    return rows, meta


def field_in_schema(field: str, schema_keys: set[str]) -> bool:
    for container, key in FIELD_SOURCES.get(field, []):
        if f"{container}.{key}" in schema_keys:
            return True
    return False


# --------------------------------------------------------------------------------------
# Statistics (numpy only)
# --------------------------------------------------------------------------------------
def ecdf(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Empirical CDF points; ``y[i] = (i + 1) / n`` at the sorted ``x[i]``."""
    xs = np.sort(np.asarray(x, dtype=np.float64))
    n = xs.size
    if n == 0:
        return xs, xs
    ys = np.arange(1, n + 1, dtype=np.float64) / n
    return xs, ys


def quantiles(x: np.ndarray, levels: Sequence[float] = QUANTILE_LEVELS) -> dict[str, float]:
    if x.size == 0:
        return {f"q{int(round(q * 100)):02d}": float("nan") for q in levels}
    qs = np.quantile(x, list(levels))
    return {f"q{int(round(q * 100)):02d}": float(v) for q, v in zip(levels, qs)}


def silverman_bandwidth(x: np.ndarray) -> float:
    """Silverman's rule of thumb with the IQR-robust scale."""
    n = x.size
    if n < 2:
        return 1.0
    std = float(np.std(x, ddof=1))
    iqr = float(np.subtract(*np.percentile(x, [75, 25])))
    scale = min(s for s in (std, iqr / 1.349) if s > 0) if (std > 0 or iqr > 0) else 0.0
    if not (scale > 0):
        scale = max(float(np.max(x) - np.min(x)), 1e-6) / 6.0
    h = float(0.9 * scale * n ** (-0.2))
    # Heavy ties (e.g. a rounded fraction repeated many times) collapse the IQR and give a
    # degenerate spike.  Floor the bandwidth at 2% of the observed range so the secondary
    # KDE stays readable; the floor is reported alongside the bandwidth.
    span = float(np.max(x) - np.min(x))
    if span > 0:
        h = max(h, 0.02 * span)
    return h


def gaussian_kde_1d(
    x: np.ndarray,
    grid: np.ndarray,
    bandwidth: float,
    domain: tuple[float, float] | None = None,
    *,
    name: str,
) -> np.ndarray:
    """Gaussian KDE with reflection boundary correction on a bounded domain.

    ``name`` is required so that discrete variables can be rejected outright.
    """
    if name in DISCRETE_FIELDS:
        raise DiscreteVariableError(
            f"{name!r} is discrete (see DISCRETE_FIELDS); use a bar/dot/table instead of a KDE"
        )
    if x.size == 0 or bandwidth <= 0:
        return np.zeros_like(grid)
    h = float(bandwidth)
    samples = [x]
    if domain is not None:
        lo, hi = domain
        if math.isfinite(lo):
            samples.append(2.0 * lo - x)
        if math.isfinite(hi):
            samples.append(2.0 * hi - x)
    dens = np.zeros_like(grid, dtype=np.float64)
    for s in samples:
        u = (grid[:, None] - s[None, :]) / h
        dens += np.exp(-0.5 * u * u).sum(axis=1)
    dens /= (x.size * h * math.sqrt(2.0 * math.pi))
    if domain is not None:
        lo, hi = domain
        dens = np.where((grid < lo) | (grid > hi), 0.0, dens)
    return dens


def von_mises_kde(theta_rad: np.ndarray, grid_rad: np.ndarray, kappa: float) -> np.ndarray:
    """Circular KDE.  Periodic by construction, so no 0/2pi seam discontinuity."""
    if theta_rad.size == 0:
        return np.zeros_like(grid_rad)
    norm = 2.0 * math.pi * float(np.i0(kappa))
    diff = grid_rad[:, None] - theta_rad[None, :]
    return np.exp(kappa * np.cos(diff)).sum(axis=1) / (theta_rad.size * norm)


def select_kappa_loo(theta_rad: np.ndarray, kappa_grid: Sequence[float]) -> tuple[float, list[dict[str, float]]]:
    """Leave-one-out likelihood cross-validation for the von Mises concentration."""
    n = theta_rad.size
    trace: list[dict[str, float]] = []
    if n < 3:
        return float(kappa_grid[0]), trace
    diff = theta_rad[:, None] - theta_rad[None, :]
    cosd = np.cos(diff)
    best_kappa = float(kappa_grid[0])
    best_score = -np.inf
    for kappa in kappa_grid:
        w = np.exp(kappa * cosd)
        np.fill_diagonal(w, 0.0)
        dens = w.sum(axis=1) / ((n - 1) * 2.0 * math.pi * float(np.i0(kappa)))
        dens = np.maximum(dens, 1e-300)
        score = float(np.mean(np.log(dens)))
        trace.append({"kappa": float(kappa), "loo_log_likelihood": score})
        if score > best_score:
            best_score = score
            best_kappa = float(kappa)
    return best_kappa, trace


def rankdata(x: np.ndarray) -> np.ndarray:
    """Average-tie ranks (scipy-free)."""
    n = x.size
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1, dtype=np.float64)
    xs = x[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2:
        return float("nan")
    return pearson(rankdata(x), rankdata(y))


def agreement_stats(target: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    err = np.abs(actual - target)
    if err.size == 0:
        nan = float("nan")
        return {"mae": nan, "median_ae": nan, "q90_ae": nan, "q95_ae": nan,
                "pearson_r": nan, "spearman_rho": nan, "bias_mean": nan}
    return {
        "mae": float(np.mean(err)),
        "median_ae": float(np.median(err)),
        "q90_ae": float(np.quantile(err, 0.90)),
        "q95_ae": float(np.quantile(err, 0.95)),
        "pearson_r": pearson(target, actual),
        "spearman_rho": spearman(target, actual),
        "bias_mean": float(np.mean(actual - target)),
    }


def _nw_weights(z_grid: np.ndarray, z_train: np.ndarray, h: float) -> np.ndarray:
    u = (z_grid[:, None] - z_train[None, :]) / h
    return np.exp(-0.5 * u * u)


def nadaraya_watson(z_grid: np.ndarray, z_train: np.ndarray, y_train: np.ndarray, h: float
                    ) -> tuple[np.ndarray, np.ndarray]:
    w = _nw_weights(z_grid, z_train, h)
    den = w.sum(axis=1)
    num = w @ y_train
    sq = (w * w).sum(axis=1)
    n_eff = np.where(sq > 0, den * den / np.maximum(sq, 1e-300), 0.0)
    est = np.where(den > 1e-12, num / np.maximum(den, 1e-300), np.nan)
    return est, n_eff


def loo_squared_error(z: np.ndarray, y: np.ndarray, h: float) -> float:
    """Leave-one-out mean squared error.  For y in {0,1} this is the LOO Brier score."""
    w = _nw_weights(z, z, h)
    np.fill_diagonal(w, 0.0)
    den = w.sum(axis=1)
    num = w @ y
    fallback = float(np.mean(y))
    pred = np.where(den > 1e-12, num / np.maximum(den, 1e-300), fallback)
    return float(np.mean((pred - y) ** 2))


def kernel_probability_curve(
    x: Sequence[Any],
    y: Sequence[Any],
    *,
    n_grid: int = GRID_POINTS,
    n_bootstrap: int = BOOTSTRAP_DEFAULT,
    seed: int = BOOTSTRAP_SEED_DEFAULT,
    min_n_eff: float = MIN_N_EFF,
    bandwidth_grid: Sequence[float] | None = None,
    x_domain: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Kernel-smoothed Bernoulli mean with LOO-Brier bandwidth and bootstrap CI.

    Purely descriptive: the curve is an association between ``x`` and ``P(y = 1)``,
    not a causal or interventional statement.
    """
    xs: list[float] = []
    ys: list[float] = []
    n_total = 0
    n_out_of_domain = 0
    x_out_max: float | None = None
    for xv, yv in zip(x, y):
        n_total += 1
        fx = float_value(xv)
        by = bool_value(yv)
        if fx is None or by is None:
            continue
        if x_domain is not None and not (x_domain[0] <= fx <= x_domain[1]):
            n_out_of_domain += 1
            x_out_max = fx if x_out_max is None else max(x_out_max, fx)
            continue
        xs.append(fx)
        ys.append(1.0 if by else 0.0)
    xa = np.asarray(xs, dtype=np.float64)
    ya = np.asarray(ys, dtype=np.float64)
    result: dict[str, Any] = {
        "n_total": n_total,
        "n_valid": int(xa.size),
        "n_missing": int(n_total - xa.size - n_out_of_domain),
        "n_out_of_domain": n_out_of_domain,
        "x_domain": list(x_domain) if x_domain is not None else None,
        "x_out_of_domain_max": x_out_max,
        "n_positive": int(ya.sum()) if ya.size else 0,
        "method": "Nadaraya-Watson Gaussian kernel on Bernoulli outcome",
        "bandwidth_selection": "leave-one-out Brier score (= LOO MSE) grid search",
        "bootstrap_seed": int(seed),
        "n_bootstrap": int(n_bootstrap),
        "min_n_eff": float(min_n_eff),
        "note": "descriptive association only (not causal)",
    }
    if xa.size < 10 or float(np.std(xa)) <= 0:
        result["status"] = "insufficient_data"
        return result

    centre = float(np.mean(xa))
    scale = float(np.std(xa))
    z = (xa - centre) / scale
    grid_h = list(bandwidth_grid) if bandwidth_grid is not None else list(np.geomspace(0.05, 2.0, 25))
    scores = [(float(h), loo_squared_error(z, ya, float(h))) for h in grid_h]
    best_h, best_score = min(scores, key=lambda t: t[1])

    x_grid = np.linspace(float(np.min(xa)), float(np.max(xa)), n_grid)
    z_grid = (x_grid - centre) / scale
    est, n_eff = nadaraya_watson(z_grid, z, ya, best_h)

    rng = np.random.default_rng(seed)
    boot = np.empty((n_bootstrap, n_grid), dtype=np.float64)
    n = z.size
    for b in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        boot[b], _ = nadaraya_watson(z_grid, z[idx], ya[idx], best_h)
    with warnings.catch_warnings():
        # A grid point that no bootstrap resample can reach yields an all-NaN column;
        # its CI stays NaN and is counted below rather than silently filled in.
        warnings.simplefilter("ignore", RuntimeWarning)
        lo = np.nanpercentile(boot, 2.5, axis=0)
        hi = np.nanpercentile(boot, 97.5, axis=0)
    n_ci_undefined = int(np.count_nonzero(~np.isfinite(lo) | ~np.isfinite(hi)))

    result.update({
        "status": "ok",
        "bandwidth_normalized": float(best_h),
        "bandwidth_data_units": float(best_h * scale),
        "loo_brier": float(best_score),
        "loo_brier_grid": [{"bandwidth_normalized": h, "loo_brier": s} for h, s in scores],
        "x_centre": centre,
        "x_scale": scale,
        "x_grid": x_grid,
        "p_hat": est,
        "ci_lo": lo,
        "ci_hi": hi,
        "n_eff": n_eff,
        "reliable_mask": n_eff >= min_n_eff,
        "n_ci_undefined": n_ci_undefined,
        "x_raw": xa,
        "y_raw": ya,
        "base_rate": float(np.mean(ya)),
    })
    return result


def zero_inflated_summary(values: Sequence[Any], *, name: str, domain: tuple[float, float]
                          ) -> dict[str, Any]:
    """Split a zero-inflated variable into a point mass at 0 and a positive part."""
    n_total = len(values)
    arr = finite_array(values)
    n_valid = int(arr.size)
    zero_mask = arr == 0.0
    positives = arr[~zero_mask]
    out: dict[str, Any] = {
        "variable": name,
        "n_total": n_total,
        "n_valid": n_valid,
        "n_missing": int(n_total - n_valid),
        "n_zero": int(zero_mask.sum()),
        "n_positive": int(positives.size),
        "p_zero": float(zero_mask.mean()) if n_valid else float("nan"),
        "positive_quantiles": quantiles(positives),
        "positive_mean": float(np.mean(positives)) if positives.size else float("nan"),
        "positive_values": positives,
        "kde_applied_to_zero_spike": False,
    }
    return out


# --------------------------------------------------------------------------------------
# Figure plumbing
# --------------------------------------------------------------------------------------
class FigureWriter:
    def __init__(self, out_dir: Path):
        self.png_dir = out_dir / "figures_png"
        self.pdf_dir = out_dir / "figures_pdf"
        self.png_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, Any]] = []

    def save(self, fig: plt.Figure, stem: str, caption: str, status: str = "ok") -> None:
        fig.text(0.005, 0.005, caption, fontsize=6.5, va="bottom", ha="left", wrap=True)
        png = self.png_dir / f"{stem}.png"
        pdf = self.pdf_dir / f"{stem}.pdf"
        fig.savefig(png, dpi=FIGURE_DPI)
        fig.savefig(pdf)
        plt.close(fig)
        self.records.append({"stem": stem, "png": str(png), "pdf": str(pdf),
                             "caption": caption, "status": status})

    def na(self, stem: str, title: str, reason: str) -> None:
        fig, ax = plt.subplots(figsize=(10, 6.5))
        ax.axis("off")
        ax.text(0.5, 0.55, "N/A: field not present in this dataset",
                ha="center", va="center", fontsize=16, color=COLORS["fourth"])
        ax.text(0.5, 0.40, reason, ha="center", va="center", fontsize=9, wrap=True)
        ax.set_title(title)
        fig.tight_layout(rect=(0, 0.05, 1, 1))
        self.save(fig, stem, f"N/A. {reason}", status="na")


def caption_for(n_total: int, parts: Sequence[tuple[str, int, int]], extra: str = "") -> str:
    """``parts`` = [(series name, n_valid, n_missing), ...]."""
    chunks = [f"denominator: {n_total} rows"]
    for name, n_valid, n_missing in parts:
        chunks.append(f"{name}: n={n_valid}, missing={n_missing}")
    if extra:
        chunks.append(extra)
    return "; ".join(chunks) + "."


def draw_ecdf(ax: plt.Axes, x: np.ndarray, label: str, color: str) -> None:
    xs, ys = ecdf(x)
    if xs.size == 0:
        return
    ax.step(np.concatenate([[xs[0]], xs]), np.concatenate([[0.0], ys]),
            where="post", color=color, lw=1.6, label=label)


def draw_rug(ax: plt.Axes, x: np.ndarray, color: str, y0: float = 0.0, height: float = 0.02) -> None:
    if x.size == 0:
        return
    ax.plot(np.repeat(x, 3), np.tile([y0, y0 + height, np.nan], x.size),
            color=color, lw=0.4, alpha=0.5)


def annotate_quantiles(ax: plt.Axes, x: np.ndarray, color: str) -> None:
    if x.size == 0:
        return
    for q in QUANTILE_LEVELS:
        v = float(np.quantile(x, q))
        ax.axvline(v, color=color, lw=0.6, ls=":", alpha=0.55)


# --------------------------------------------------------------------------------------
# Figure builders
# --------------------------------------------------------------------------------------
def _series(rows: Sequence[dict[str, Any]], field: str) -> tuple[np.ndarray, int, int]:
    raw = [r.get(field) for r in rows]
    arr = finite_array(raw)
    return arr, int(arr.size), int(len(raw) - arr.size)


def figure_univariate(
    writer: FigureWriter,
    stem: str,
    title: str,
    xlabel: str,
    rows: Sequence[dict[str, Any]],
    fields: Sequence[tuple[str, str, str]],
    domain: tuple[float, float] | None,
    schema_keys: set[str],
    metrics: list[dict[str, Any]],
    summary: dict[str, Any],
    domain_note: str = "",
) -> None:
    """ECDF (primary) + bounded KDE (secondary) for one or more continuous series."""
    absent = [f for f, _, _ in fields if not field_in_schema(f, schema_keys)]
    available = [(f, lab, col) for f, lab, col in fields if f not in absent]
    series = [(f, lab, col, *_series(rows, f)) for f, lab, col in available]
    series = [s for s in series if s[4] > 0]
    if not series:
        reason = (
            f"Fields {', '.join(f for f, _, _ in fields)} are not present in this dataset "
            f"(schema has no such key); rendered rows = {len(rows)}."
        )
        writer.na(stem, title, reason)
        for f, _, _ in fields:
            summary.setdefault("na_variables", []).append({"figure": stem, "variable": f, "reason": reason})
        return

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6))
    ax_e, ax_k = axes
    kde_info: list[dict[str, Any]] = []
    lo_all = min(float(np.min(s[3])) for s in series)
    hi_all = max(float(np.max(s[3])) for s in series)
    if domain is not None:
        lo_all = max(lo_all, domain[0])
        hi_all = min(hi_all, domain[1])
    if hi_all <= lo_all:
        hi_all = lo_all + 1e-6
    pad = 0.02 * (hi_all - lo_all)
    g_lo = lo_all - pad if domain is None else max(domain[0], lo_all - pad)
    g_hi = hi_all + pad if domain is None else min(domain[1], hi_all + pad)
    grid = np.linspace(g_lo, g_hi, 512)

    caption_parts: list[tuple[str, int, int]] = []
    outside_notes: list[str] = []
    for field, label, color, arr, n_valid, n_missing in series:
        # The ECDF keeps every observation; only the density is restricted to the
        # nominal support, and any excursion is counted and reported.
        if domain is None:
            inside = arr
            n_outside = 0
        else:
            in_mask = (arr >= domain[0]) & (arr <= domain[1])
            inside = arr[in_mask]
            n_outside = int(arr.size - inside.size)
        if n_outside:
            outside_notes.append(
                f"{label}: {n_outside}/{n_valid} observation(s) outside the nominal support "
                f"[{domain[0]:g}, {domain[1]:g}] (max {float(np.max(arr)):.4g}); they are kept in "
                f"the ECDF but excluded from the density and from the plotted x-range")
        draw_ecdf(ax_e, arr, f"{label} (n={n_valid})", color)
        draw_rug(ax_e, arr, color)
        annotate_quantiles(ax_e, arr, color)
        h = silverman_bandwidth(inside) if inside.size else float("nan")
        if inside.size >= MIN_KDE_SAMPLES:
            dens = gaussian_kde_1d(inside, grid, h, domain, name=field)
            ax_k.plot(grid, dens, color=color, lw=1.6, label=f"{label} (h={h:.4g})")
            ax_k.fill_between(grid, dens, color=color, alpha=0.12)
        draw_rug(ax_k, inside, color)
        q = quantiles(arr)
        kde_info.append({
            "variable": field, "n_valid": n_valid, "n_missing": n_missing,
            "n_outside_domain": n_outside, "n_used_for_density": int(inside.size),
            "observed_max": float(np.max(arr)), "observed_min": float(np.min(arr)),
            "bandwidth": float(h), "bandwidth_rule": "Silverman (robust IQR scale)",
            "boundary_correction": "reflection" if domain is not None else "none",
            "domain": list(domain) if domain is not None else None,
            "quantiles": q, "mean": float(np.mean(arr)),
        })
        caption_parts.append((label, n_valid, n_missing))
        for key, value in q.items():
            metrics.append({"figure": stem, "variable": field, "group": "all",
                            "statistic": key, "value": value, "n_total": len(rows),
                            "n_valid": n_valid, "n_missing": n_missing, "note": ""})
        metrics.append({"figure": stem, "variable": field, "group": "all",
                        "statistic": "mean", "value": float(np.mean(arr)),
                        "n_total": len(rows), "n_valid": n_valid,
                        "n_missing": n_missing, "note": ""})
        metrics.append({"figure": stem, "variable": field, "group": "all",
                        "statistic": "kde_bandwidth", "value": float(h),
                        "n_total": len(rows), "n_valid": n_valid,
                        "n_missing": n_missing, "note": "Silverman robust"})

    ax_e.set_xlabel(xlabel)
    ax_e.set_ylabel("Empirical CDF")
    ax_e.set_ylim(-0.03, 1.03)
    ax_e.grid(alpha=0.25)
    ax_e.legend(fontsize=8)
    ax_e.set_title("ECDF (primary) with rug and q05/25/50/75/95")
    ax_k.set_xlabel(xlabel)
    ax_k.set_ylabel("Density")
    ax_k.grid(alpha=0.25)
    ax_k.legend(fontsize=8)
    ax_k.set_title("KDE (secondary)")
    if domain is not None:
        ax_e.set_xlim(g_lo, g_hi)
        ax_k.set_xlim(g_lo, g_hi)
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0.055, 1, 0.96))

    extra = domain_note
    for note in outside_notes:
        extra = (extra + " " if extra else "") + note + "."
    if absent:
        extra = (extra + " " if extra else "") + f"N/A in this dataset: {', '.join(absent)}."
    writer.save(fig, stem, caption_for(len(rows), caption_parts, extra))
    summary.setdefault("univariate", {})[stem] = {
        "title": title, "series": kde_info,
        "domain": list(domain) if domain is not None else None,
        "absent_fields": absent,
    }
    for f in absent:
        summary.setdefault("na_variables", []).append(
            {"figure": stem, "variable": f, "reason": "field not present in this dataset"})


def figure_azimuth_circular(
    writer: FigureWriter,
    rows: Sequence[dict[str, Any]],
    schema_keys: set[str],
    metrics: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    stem = "04_azimuth_circular_kde"
    title = "Azimuth prescription: von Mises circular KDE"
    field = "azimuth_deg_target"
    if not field_in_schema(field, schema_keys):
        writer.na(stem, title, f"{field} is not present in this dataset.")
        summary.setdefault("na_variables", []).append(
            {"figure": stem, "variable": field, "reason": "field not present in this dataset"})
        return
    arr, n_valid, n_missing = _series(rows, field)
    if n_valid < MIN_KDE_SAMPLES:
        writer.na(stem, title, f"{field} present but only {n_valid} finite values.")
        return

    theta = np.deg2rad(np.mod(arr, 360.0))
    kappa_grid = np.geomspace(0.2, 200.0, 30)
    kappa, trace = select_kappa_loo(theta, kappa_grid)
    grid_deg = np.linspace(0.0, 360.0, 721)
    dens = von_mises_kde(theta, np.deg2rad(grid_deg), kappa)
    uniform = 1.0 / (2.0 * math.pi)

    # Seam continuity: the kernel is periodic, so f(0) must equal f(360) exactly and
    # the local slope must not jump.  Both are measured, not assumed.
    d0 = float(dens[0])
    d360 = float(dens[-1])
    seam_abs = abs(d0 - d360)
    # grid[-1] == grid[0] modulo 360, so one grid step across the seam is dens[0] - dens[-2].
    # The reference must be local: for a peaked distribution most of the circle is flat, so
    # a global median step would make any seam look enormous.
    step_across = abs(d0 - float(dens[-2]))
    local = np.abs(np.diff(np.concatenate([dens[-21:-1], dens[0:21]])))
    typical_step = float(np.median(local)) if local.size else 0.0
    seam_rel = step_across / typical_step if typical_step > 0 else 0.0

    fig = plt.figure(figsize=(13, 6.0))
    ax_p = fig.add_subplot(1, 2, 1, projection="polar")
    ax_l = fig.add_subplot(1, 2, 2)
    ax_p.plot(np.deg2rad(grid_deg), dens, color=COLORS["target"], lw=1.8, label="von Mises KDE")
    ax_p.fill(np.deg2rad(grid_deg), dens, color=COLORS["target"], alpha=0.15)
    ax_p.plot(np.deg2rad(grid_deg), np.full_like(grid_deg, uniform),
              color=COLORS["grey"], lw=1.1, ls="--", label="uniform reference")
    ax_p.scatter(theta, np.full_like(theta, ax_p.get_ylim()[1] * 0.02),
                 s=3, color=COLORS["actual"], alpha=0.5)
    ax_p.set_title(f"Polar density (kappa={kappa:.3g})")
    ax_p.legend(loc="upper right", bbox_to_anchor=(1.25, 1.12), fontsize=8)

    ax_l.plot(grid_deg, dens, color=COLORS["target"], lw=1.6, label="von Mises KDE")
    ax_l.axhline(uniform, color=COLORS["grey"], ls="--", lw=1.1, label="uniform reference")
    draw_rug(ax_l, np.mod(arr, 360.0), COLORS["actual"], y0=0.0, height=float(np.max(dens)) * 0.05)
    ax_l.set_xlim(0, 360)
    ax_l.set_xticks(np.arange(0, 361, 45))
    ax_l.set_xlabel("Azimuth [deg] (0 and 360 are the same point)")
    ax_l.set_ylabel("Circular density [1/rad]")
    ax_l.grid(alpha=0.25)
    ax_l.legend(fontsize=8)
    ax_l.set_title("Unrolled view: seam at 0/360 is continuous")
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))

    caption = caption_for(
        len(rows), [("azimuth_deg_target", n_valid, n_missing)],
        f"kappa={kappa:.4g} by leave-one-out likelihood CV; equivalent angular sd "
        f"~{math.degrees(1.0 / math.sqrt(kappa)):.2f} deg; seam |f(0)-f(360)|={seam_abs:.3e}; "
        f"seam step / local median step = {seam_rel:.3f}.",
    )
    writer.save(fig, stem, caption)
    summary["azimuth_circular"] = {
        "n_valid": n_valid, "n_missing": n_missing, "kappa": float(kappa),
        "kappa_selection": "leave-one-out likelihood cross-validation",
        "kappa_grid": [float(k) for k in kappa_grid],
        "equivalent_angular_sd_deg": float(math.degrees(1.0 / math.sqrt(kappa))),
        "uniform_reference_density": float(uniform),
        "seam_density_at_0": d0, "seam_density_at_360": d360,
        "seam_abs_difference": float(seam_abs),
        "seam_step_over_local_median_step": float(seam_rel),
        "kappa_at_grid_boundary": bool(
            math.isclose(kappa, float(kappa_grid[0])) or math.isclose(kappa, float(kappa_grid[-1]))),
        "density_min": float(np.min(dens)), "density_max": float(np.max(dens)),
        "loo_trace_best": max(trace, key=lambda t: t["loo_log_likelihood"]) if trace else None,
    }
    metrics.append({"figure": stem, "variable": field, "group": "all",
                    "statistic": "vonmises_kappa", "value": float(kappa),
                    "n_total": len(rows), "n_valid": n_valid, "n_missing": n_missing,
                    "note": "LOO likelihood CV"})
    metrics.append({"figure": stem, "variable": field, "group": "all",
                    "statistic": "seam_abs_difference", "value": float(seam_abs),
                    "n_total": len(rows), "n_valid": n_valid, "n_missing": n_missing,
                    "note": "|f(0 deg) - f(360 deg)|"})


def figure_luma_by_scene(
    writer: FigureWriter,
    rows: Sequence[dict[str, Any]],
    schema_keys: set[str],
    metrics: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    stem = "05_final_luma_ecdf_by_scene"
    title = "Final-RGB luma ECDF by scene preset"
    fields = ["luma_pallet_final", "luma_frame_final"]
    absent = [f for f in fields if not field_in_schema(f, schema_keys)]
    if len(absent) == len(fields):
        raw_note = ""
        if field_in_schema("luma_pallet_raw", schema_keys) or field_in_schema("luma_frame_raw", schema_keys):
            raw_note = (" Only pre-post-effect (raw) luma exists here; it is deliberately NOT "
                        "substituted because the gate/label semantics differ.")
        reason = (f"Fields {', '.join(fields)} are not present in this dataset "
                  f"(Phase 3 final-RGB measurement post-dates this render).{raw_note}")
        writer.na(stem, title, reason)
        for f in fields:
            summary.setdefault("na_variables", []).append({"figure": stem, "variable": f, "reason": reason})
        return

    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(group_label(r.get("scene_preset")), []).append(r)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6), sharey=True)
    palette = plt.get_cmap("tab10")
    caption_parts: list[tuple[str, int, int]] = []
    per_group: dict[str, Any] = {}
    for ax, field in zip(axes, fields):
        if field in absent:
            ax.axis("off")
            ax.set_title(f"{field}: N/A (not in this dataset)")
            continue
        for i, (name, grp) in enumerate(ordered):
            arr, n_valid, n_missing = _series(grp, field)
            if n_valid == 0:
                continue
            draw_ecdf(ax, arr, f"{name} (n={n_valid})", palette(i % 10))
            per_group.setdefault(field, {})[name] = {
                "n_valid": n_valid, "n_missing": n_missing, "quantiles": quantiles(arr)}
            for key, value in quantiles(arr).items():
                metrics.append({"figure": stem, "variable": field, "group": name,
                                "statistic": key, "value": value, "n_total": len(grp),
                                "n_valid": n_valid, "n_missing": n_missing, "note": ""})
        arr_all, n_valid, n_missing = _series(rows, field)
        caption_parts.append((field, n_valid, n_missing))
        ax.set_xlabel(f"{field} [0-255]")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7)
        ax.set_title(field)
    axes[0].set_ylabel("Empirical CDF")
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    extra = f"grouped by scene_preset ({len(ordered)} groups)."
    if absent:
        extra += f" N/A in this dataset: {', '.join(absent)}."
    writer.save(fig, stem, caption_for(len(rows), caption_parts, extra))
    summary["final_luma_by_scene"] = {"groups": per_group, "absent_fields": absent}


def figure_zero_inflated(
    writer: FigureWriter,
    rows: Sequence[dict[str, Any]],
    schema_keys: set[str],
    metrics: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    stem = "06_occlusion_source_zero_mass_and_positive_ecdf"
    title = "Occlusion sources: zero point mass and conditional ECDF over X > 0"
    fields = ["f_static", "f_cargo", "f_context", "f_explicit", "f_total"]
    present = [f for f in fields if field_in_schema(f, schema_keys)]
    if not present:
        writer.na(stem, title, f"None of {', '.join(fields)} is present in this dataset.")
        return
    fig, axes = plt.subplots(len(present), 2, figsize=(12, 2.6 * len(present) + 1.2))
    if len(present) == 1:
        axes = np.asarray([axes])
    caption_parts: list[tuple[str, int, int]] = []
    per_field: dict[str, Any] = {}
    grid = np.linspace(0.0, 1.0, 512)
    for row_i, field in enumerate(present):
        info = zero_inflated_summary([r.get(field) for r in rows], name=field, domain=DOMAIN_UNIT)
        positives = info.pop("positive_values")
        ax_bar, ax_ecdf = axes[row_i, 0], axes[row_i, 1]
        p0 = info["p_zero"]
        ax_bar.bar([0, 1], [p0, 1.0 - p0 if math.isfinite(p0) else float("nan")],
                   color=[COLORS["grey"], COLORS["target"]], width=0.55)
        ax_bar.set_xticks([0, 1])
        ax_bar.set_xticklabels([f"X = 0\nn={info['n_zero']}", f"X > 0\nn={info['n_positive']}"])
        ax_bar.set_ylim(0, 1.05)
        ax_bar.set_ylabel("Probability")
        ax_bar.set_title(f"{field}: P(X=0) = {p0:.4f}" if math.isfinite(p0) else f"{field}: no data")
        ax_bar.grid(alpha=0.2, axis="y")
        if positives.size:
            draw_ecdf(ax_ecdf, positives, f"X>0 (n={positives.size})", COLORS["actual"])
            draw_rug(ax_ecdf, positives, COLORS["actual"])
            if positives.size >= MIN_KDE_SAMPLES:
                h = silverman_bandwidth(positives)
                dens = gaussian_kde_1d(positives, grid, h, DOMAIN_UNIT, name=field)
                scaled = dens / max(float(np.max(dens)), 1e-12)
                ax_ecdf.plot(grid, scaled, color=COLORS["third"], lw=1.0, alpha=0.75,
                             label=f"KDE of X>0 (h={h:.3g}, scaled)")
                info["positive_kde_bandwidth"] = float(h)
            ax_ecdf.legend(fontsize=7)
        else:
            ax_ecdf.text(0.5, 0.5, "no positive observations", ha="center", va="center")
        # Anchor at 0 (meaningful lower bound) but zoom to the positive support so a
        # narrow conditional distribution is still legible.
        x_hi = float(np.max(positives)) * 1.05 if positives.size else 1.0
        ax_ecdf.set_xlim(0.0, max(x_hi, 1e-6))
        ax_ecdf.set_ylim(-0.03, 1.08)
        ax_ecdf.set_ylabel("Conditional ECDF")
        ax_ecdf.set_xlabel(f"{field} | X > 0")
        ax_ecdf.grid(alpha=0.25)
        caption_parts.append((field, info["n_valid"], info["n_missing"]))
        per_field[field] = info
        for stat, key in (("p_zero", "p_zero"), ("n_zero", "n_zero"), ("n_positive", "n_positive")):
            metrics.append({"figure": stem, "variable": field, "group": "all",
                            "statistic": stat, "value": float(info[key]),
                            "n_total": info["n_total"], "n_valid": info["n_valid"],
                            "n_missing": info["n_missing"], "note": ""})
        for key, value in info["positive_quantiles"].items():
            metrics.append({"figure": stem, "variable": field, "group": "X>0",
                            "statistic": key, "value": value, "n_total": info["n_total"],
                            "n_valid": info["n_positive"], "n_missing": info["n_missing"],
                            "note": "conditional on X>0"})
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0.045, 1, 0.965))
    writer.save(fig, stem, caption_for(
        len(rows), caption_parts,
        "zero mass is shown as an explicit point mass; the KDE is fitted only to X > 0 "
        "with reflection boundary correction on [0,1] and is never used to smooth the zero spike."))
    summary["zero_inflated"] = per_field


def figure_target_vs_actual(
    writer: FigureWriter,
    stem: str,
    title: str,
    rows: Sequence[dict[str, Any]],
    target_field: str,
    actual_field: str,
    xlabel: str,
    ylabel: str,
    domain: tuple[float, float] | None,
    schema_keys: set[str],
    metrics: list[dict[str, Any]],
    summary: dict[str, Any],
    proposal_rows: Sequence[dict[str, Any]] | None = None,
    delivery_note: str = "",
) -> None:
    missing_fields = [f for f in (target_field, actual_field) if not field_in_schema(f, schema_keys)]
    if missing_fields:
        reason = (f"Fields {', '.join(missing_fields)} are not present in this dataset; "
                  f"rendered rows = {len(rows)}.")
        writer.na(stem, title, reason)
        for f in missing_fields:
            summary.setdefault("na_variables", []).append({"figure": stem, "variable": f, "reason": reason})
        return
    t, a = paired_finite([r.get(target_field) for r in rows], [r.get(actual_field) for r in rows])
    n_total = len(rows)
    n_valid = int(t.size)
    n_missing = n_total - n_valid
    if n_valid == 0:
        writer.na(stem, title, f"No row has both {target_field} and {actual_field} finite (n={n_total}).")
        return

    n_outside = 0
    outside_max = None
    if domain is not None:
        out_mask = (t < domain[0]) | (t > domain[1]) | (a < domain[0]) | (a > domain[1])
        n_outside = int(out_mask.sum())
        if n_outside:
            outside_max = float(np.max(np.concatenate([t[out_mask], a[out_mask]])))

    ncols = 3 if proposal_rows is not None else 2
    fig, axes = plt.subplots(1, ncols, figsize=(5.2 * ncols, 5.4))
    ax_s, ax_r = axes[0], axes[1]
    ax_s.scatter(t, a, s=16, alpha=0.35, color=COLORS["target"], edgecolors="none",
                 label=f"rendered frames (n={n_valid})")
    lo = min(float(np.min(t)), float(np.min(a)))
    hi = max(float(np.max(t)), float(np.max(a)))
    if domain is not None:
        lo = max(lo, domain[0])
        hi = min(hi, domain[1])
    span = hi - lo if hi > lo else 1.0
    line = np.array([lo - 0.03 * span, hi + 0.03 * span])
    ax_s.plot(line, line, color=COLORS["fourth"], lw=1.2, ls="--", label="y = x (identity)")
    ax_s.set_xlabel(xlabel)
    ax_s.set_ylabel(ylabel)
    ax_s.grid(alpha=0.25)
    ax_s.legend(fontsize=8)
    ax_s.set_aspect("equal", adjustable="box")
    if n_outside:
        # Statistics below use all pairs; only the view is clipped so the bulk stays legible.
        ax_s.set_xlim(line[0], line[1])
        ax_s.set_ylim(line[0], line[1])

    stats = agreement_stats(t, a)
    residual = a - t
    draw_ecdf(ax_r, np.abs(residual), f"|actual - target| (n={n_valid})", COLORS["actual"])
    draw_ecdf(ax_r, residual, "signed residual", COLORS["third"])
    ax_r.set_xlabel("Residual (actual - target)")
    ax_r.set_ylabel("Empirical CDF")
    ax_r.grid(alpha=0.25)
    ax_r.legend(fontsize=8)
    ax_r.set_title("Residual ECDF")
    box = (
        f"MAE = {stats['mae']:.4g}\nmedian AE = {stats['median_ae']:.4g}\n"
        f"q90 AE = {stats['q90_ae']:.4g}\nq95 AE = {stats['q95_ae']:.4g}\n"
        f"Pearson r = {stats['pearson_r']:.4f} (linear)\n"
        f"Spearman rho = {stats['spearman_rho']:.4f} (monotone rank)"
    )
    ax_s.text(0.02, 0.98, box, transform=ax_s.transAxes, va="top", ha="left", fontsize=7.5,
              bbox={"boxstyle": "round", "fc": "white", "ec": "0.7", "alpha": 0.9})

    delivery: dict[str, Any] | None = None
    if proposal_rows is not None:
        ax_d = axes[2]
        n_prop = len(proposal_rows)
        n_rendered = sum(1 for r in proposal_rows if bool_value(r.get("rendered")) is True)
        n_paired = n_valid
        n_failed = n_prop - n_rendered
        labels = ["proposals", "rendered", "target/actual pair"]
        vals = [n_prop, n_rendered, n_paired]
        ax_d.bar(labels, vals, color=[COLORS["grey"], COLORS["target"], COLORS["third"]])
        for i, v in enumerate(vals):
            ax_d.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
        ax_d.set_ylabel("Count")
        ax_d.set_title("Proposal-level delivery (not precision)")
        ax_d.grid(alpha=0.2, axis="y")
        delivery = {
            "n_proposals": n_prop, "n_rendered": n_rendered, "n_failed_proposals": n_failed,
            "n_target_actual_pairs": n_paired,
            "delivery_rate_rendered": n_rendered / n_prop if n_prop else None,
            "delivery_rate_paired": n_paired / n_prop if n_prop else None,
        }

    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    extra = ("scatter and statistics are rendered-only (precision); proposal-level delivery is "
             "reported separately and never mixed into the same numbers.")
    if delivery is not None:
        extra += (f" proposals={delivery['n_proposals']}, rendered={delivery['n_rendered']}, "
                  f"failed proposals={delivery['n_failed_proposals']}.")
    if n_outside:
        extra += (f" {n_outside}/{n_valid} pair(s) fall outside the nominal support "
                  f"[{domain[0]:g}, {domain[1]:g}] (max {outside_max:.4g}); the scatter view is "
                  f"clipped to the support but all statistics use every pair.")
    if delivery_note:
        extra += " " + delivery_note
    writer.save(fig, stem, caption_for(
        n_total, [(f"{target_field} vs {actual_field}", n_valid, n_missing)], extra))
    entry = {"target": target_field, "actual": actual_field, "n_total": n_total,
             "n_valid": n_valid, "n_missing": n_missing, "rendered_only": True,
             "n_pairs_outside_domain": n_outside, "outside_domain_max": outside_max,
             "domain": list(domain) if domain is not None else None, **stats}
    if delivery is not None:
        entry["proposal_delivery"] = delivery
    summary.setdefault("target_vs_actual", {})[stem] = entry
    for key, value in stats.items():
        metrics.append({"figure": stem, "variable": f"{actual_field}_vs_{target_field}",
                        "group": "rendered_only", "statistic": key, "value": value,
                        "n_total": n_total, "n_valid": n_valid, "n_missing": n_missing,
                        "note": ""})


def figure_pass_probability(
    writer: FigureWriter,
    stem: str,
    title: str,
    rows: Sequence[dict[str, Any]],
    x_field: str,
    y_fields: Sequence[tuple[str, str, str]],
    xlabel: str,
    schema_keys: set[str],
    metrics: list[dict[str, Any]],
    summary: dict[str, Any],
    n_bootstrap: int,
    seed: int,
    domain: tuple[float, float] | None = None,
    x_domain: tuple[float, float] | None = None,
    x_domain_note: str = "",
) -> None:
    if not field_in_schema(x_field, schema_keys):
        reason = f"x variable {x_field} is not present in this dataset (n rows = {len(rows)})."
        writer.na(stem, title, reason)
        summary.setdefault("na_variables", []).append(
            {"figure": stem, "variable": x_field, "reason": reason})
        return
    usable = [(f, lab, col) for f, lab, col in y_fields if field_in_schema(f, schema_keys)]
    absent = [f for f, _, _ in y_fields if f not in {u[0] for u in usable}]
    if not usable:
        reason = (f"None of the outcome fields {', '.join(f for f, _, _ in y_fields)} "
                  f"is present in this dataset.")
        writer.na(stem, title, reason)
        for f, _, _ in y_fields:
            summary.setdefault("na_variables", []).append({"figure": stem, "variable": f, "reason": reason})
        return

    fig, ax = plt.subplots(figsize=(11, 6.4))
    caption_parts: list[tuple[str, int, int]] = []
    curves: dict[str, Any] = {}
    any_ok = False
    n_out_of_domain = 0
    x_out_max: float | None = None
    for field, label, color in usable:
        res = kernel_probability_curve(
            [r.get(x_field) for r in rows], [r.get(field) for r in rows],
            n_bootstrap=n_bootstrap, seed=seed, x_domain=x_domain)
        caption_parts.append((label, res["n_valid"], res["n_missing"]))
        n_out_of_domain = res["n_out_of_domain"]
        x_out_max = res["x_out_of_domain_max"]
        if res.get("status") != "ok":
            curves[field] = {k: v for k, v in res.items() if not isinstance(v, np.ndarray)}
            continue
        any_ok = True
        xg = res["x_grid"]
        p = res["p_hat"]
        mask = res["reliable_mask"]
        ax.fill_between(xg, res["ci_lo"], res["ci_hi"], color=color, alpha=0.14, lw=0)
        ax.plot(xg, np.where(mask, p, np.nan), color=color, lw=2.0,
                label=f"{label} (h={res['bandwidth_data_units']:.4g}, base={res['base_rate']:.3f})")
        ax.plot(xg, np.where(mask, np.nan, p), color=color, lw=1.2, alpha=0.28, ls=":")
        curves[field] = {
            "n_total": res["n_total"], "n_valid": res["n_valid"], "n_missing": res["n_missing"],
            "n_positive": res["n_positive"], "base_rate": res["base_rate"],
            "bandwidth_normalized": res["bandwidth_normalized"],
            "bandwidth_data_units": res["bandwidth_data_units"],
            "loo_brier": res["loo_brier"], "bootstrap_seed": res["bootstrap_seed"],
            "n_bootstrap": res["n_bootstrap"], "min_n_eff": res["min_n_eff"],
            "n_grid_points_reliable": int(np.count_nonzero(mask)),
            "n_grid_points": int(xg.size),
            "n_ci_undefined": res.get("n_ci_undefined", 0),
            "n_out_of_domain_excluded": res["n_out_of_domain"],
            "x_domain": res["x_domain"],
            "x_out_of_domain_max": res["x_out_of_domain_max"],
            "x_min": float(np.min(res["x_raw"])), "x_max": float(np.max(res["x_raw"])),
            "p_hat_min_reliable": float(np.nanmin(p[mask])) if np.any(mask) else None,
            "p_hat_max_reliable": float(np.nanmax(p[mask])) if np.any(mask) else None,
            "mean_ci_width_reliable": float(np.nanmean((res["ci_hi"] - res["ci_lo"])[mask])) if np.any(mask) else None,
            "method": res["method"], "bandwidth_selection": res["bandwidth_selection"],
            "note": res["note"],
        }
        for stat in ("bandwidth_data_units", "loo_brier", "base_rate",
                     "p_hat_min_reliable", "p_hat_max_reliable", "mean_ci_width_reliable"):
            value = curves[field].get(stat)
            if value is None:
                continue
            metrics.append({"figure": stem, "variable": f"P({field}) vs {x_field}",
                            "group": "all", "statistic": stat, "value": float(value),
                            "n_total": res["n_total"], "n_valid": res["n_valid"],
                            "n_missing": res["n_missing"], "note": "descriptive association"})
        if field == usable[0][0]:
            xr, yr = res["x_raw"], res["y_raw"]
            ax.plot(np.repeat(xr[yr > 0.5], 3),
                    np.tile([-0.055, -0.025, np.nan], int((yr > 0.5).sum())),
                    color=COLORS["third"], lw=0.5, alpha=0.55)
            ax.plot(np.repeat(xr[yr <= 0.5], 3),
                    np.tile([-0.095, -0.065, np.nan], int((yr <= 0.5).sum())),
                    color=COLORS["fourth"], lw=0.5, alpha=0.55)
            ax.text(float(np.min(xr)), -0.040, " positive", fontsize=7, color=COLORS["third"], va="center")
            ax.text(float(np.min(xr)), -0.080, " negative", fontsize=7, color=COLORS["fourth"], va="center")

    if not any_ok:
        plt.close(fig)
        writer.na(stem, title, "Not enough joint observations to fit a kernel probability curve.")
        return
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Estimated P(outcome = pass)")
    ax.set_ylim(-0.12, 1.05)
    if domain is not None:
        ax.set_xlim(domain)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_title(title)
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    extra = (f"Nadaraya-Watson Gaussian kernel; bandwidth by LOO Brier score; "
             f"{n_bootstrap} bootstrap resamples (seed {seed}) for the pointwise 95% band; "
             f"dotted segments have effective n < {MIN_N_EFF:g}; rug shows raw x by outcome. "
             f"Continuous descriptive association only, not a causal effect.")
    if x_domain is not None:
        extra += (f" Fit restricted to {x_field} in [{x_domain[0]:g}, {x_domain[1]:g}]: "
                  f"{n_out_of_domain} row(s) outside were excluded"
                  + (f" (max observed {x_out_max:.4g})" if x_out_max is not None else "") + ".")
        if x_domain_note:
            extra += " " + x_domain_note
    if absent:
        extra += f" N/A in this dataset: {', '.join(absent)}."
    writer.save(fig, stem, caption_for(len(rows), caption_parts, extra))
    summary.setdefault("pass_probability", {})[stem] = {
        "x_field": x_field, "curves": curves, "absent_outcomes": absent}
    for f in absent:
        summary.setdefault("na_variables", []).append(
            {"figure": stem, "variable": f, "reason": "field not present in this dataset"})


def figure_discrete_appendix(
    writer: FigureWriter,
    rows: Sequence[dict[str, Any]],
    schema_keys: set[str],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    """Bar/dot appendix for discrete variables.  No KDE, no numeric interpolation."""
    table_rows: list[dict[str, Any]] = []
    present = [f for f in CATEGORICAL_APPENDIX_FIELDS if field_in_schema(f, schema_keys)]
    counts: dict[str, Counter] = {}
    for field in present:
        c = Counter(group_label(r.get(field)) for r in rows)
        counts[field] = c
        for value, n in sorted(c.items()):
            table_rows.append({"variable": field, "value": value, "count": n,
                               "fraction": n / len(rows) if rows else 0.0,
                               "is_missing_bucket": value == MISSING_LABEL})
    plotted = [f for f in present if counts[f]]
    if not plotted:
        writer.na("A01_discrete_variable_counts", "Discrete variables (appendix)",
                  "No discrete variable is present in this dataset.")
        return table_rows
    ncols = 4
    nrows = math.ceil(len(plotted) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 3.0 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, field in zip(axes, plotted):
        c = counts[field]
        labels = sorted(c.keys())
        vals = [c[k] for k in labels]
        colors = [COLORS["grey"] if k == MISSING_LABEL else COLORS["target"] for k in labels]
        ax.bar(range(len(labels)), vals, color=colors)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=6.5)
        ax.set_title(f"{field} (n={len(rows)})", fontsize=8.5)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(alpha=0.2, axis="y")
    for ax in axes[len(plotted):]:
        ax.axis("off")
    fig.suptitle("Appendix: discrete variable counts (bar only; KDE is not applicable)")
    fig.tight_layout(rect=(0, 0.035, 1, 0.97))
    writer.save(fig, "A01_discrete_variable_counts",
                caption_for(len(rows), [], "discrete variables are shown as counts; the "
                                          "'(missing)' bucket is drawn separately in grey and is "
                                          "never merged with 0 or False."))
    summary["discrete"] = {f: dict(sorted(counts[f].items())) for f in plotted}
    return table_rows


# --------------------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------------------
REQUIRED_FIGURES = [
    "01_camera_distance_ecdf",
    "02_projected_size_target_actual_ecdf",
    "03_elevation_target_actual_density",
    "04_azimuth_circular_kde",
    "05_final_luma_ecdf_by_scene",
    "06_occlusion_source_zero_mass_and_positive_ecdf",
    "07_elevation_target_vs_actual",
    "08_projected_size_target_vs_actual",
    "09_f_target_vs_f_explicit_actual",
    "10_allpass_probability_vs_distance",
    "11_allpass_probability_vs_projected_size",
    "12_allpass_probability_vs_f_total",
    "13_pnp_stability_vs_projected_size",
]


def write_metrics_csv(path: Path, metrics: list[dict[str, Any]]) -> None:
    columns = ["figure", "variable", "group", "statistic", "value",
               "n_total", "n_valid", "n_missing", "note"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in metrics:
            writer.writerow({c: row.get(c, "") for c in columns})


def write_discrete_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = ["variable", "value", "count", "fraction", "is_missing_bucket"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.floating, np.integer)):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def write_summary_md(path: Path, summary: dict[str, Any], figures: list[dict[str, Any]]) -> None:
    meta = summary["dataset"]
    lines: list[str] = []
    lines.append("# Paper-oriented continuous EDA (v2 constrained pipeline)")
    lines.append("")
    lines.append(f"- dataset root: `{meta['root']}`")
    lines.append(f"- rows analysed: {meta['n_rows']} "
                 f"(records {meta['n_records']}, labels {meta['n_labels']}, "
                 f"rejected proposals {meta['n_rejected_proposals']})")
    lines.append(f"- rendered rows used for frame-level figures: {summary['n_rendered_rows']}")
    lines.append(f"- PnP eligibility manifest: `{meta['pnp_manifest_path']}` "
                 f"({meta['n_pnp_manifest']} rows)")
    lines.append(f"- bootstrap: {summary['bootstrap']['n_bootstrap']} resamples, "
                 f"seed {summary['bootstrap']['seed']} (deterministic)")
    lines.append("")
    lines.append("## Figures")
    lines.append("")
    lines.append("```")
    lines.append(f"{'figure':<52}{'status':<8}caption head")
    lines.append("-" * 110)
    for rec in figures:
        head = rec["caption"][:46].replace("\n", " ")
        lines.append(f"{rec['stem']:<52}{rec['status']:<8}{head}")
    lines.append("```")
    lines.append("")
    az = summary.get("azimuth_circular")
    if az:
        lines.append("## Circular KDE (azimuth)")
        lines.append("")
        lines.append(f"- kappa = {az['kappa']:.4g} (leave-one-out likelihood CV over "
                     f"{len(az['kappa_grid'])} candidates)")
        lines.append(f"- equivalent angular sd ~ {az['equivalent_angular_sd_deg']:.3f} deg")
        lines.append(f"- density at 0 deg = {az['seam_density_at_0']:.6f}, "
                     f"at 360 deg = {az['seam_density_at_360']:.6f}, "
                     f"|difference| = {az['seam_abs_difference']:.3e}")
        lines.append(f"- seam step / local median grid step = "
                     f"{az['seam_step_over_local_median_step']:.4f} "
                     f"(~1.0 means the seam is as smooth as its neighbouring grid points)")
        lines.append(f"- uniform reference density = {az['uniform_reference_density']:.6f}, "
                     f"observed density range [{az['density_min']:.6f}, {az['density_max']:.6f}]")
        lines.append("")
    if summary.get("pass_probability"):
        lines.append("## Pass-probability curves (descriptive association, not causal)")
        lines.append("")
        lines.append("```")
        lines.append(f"{'figure':<44}{'outcome':<32}{'h(data)':>10}{'LOO Brier':>11}{'base':>8}{'n':>6}")
        lines.append("-" * 111)
        for stem, blob in summary["pass_probability"].items():
            for field, c in blob["curves"].items():
                if "bandwidth_data_units" not in c:
                    lines.append(f"{stem:<44}{field:<32}{'-':>10}{'-':>11}{'-':>8}"
                                 f"{c.get('n_valid', 0):>6}  ({c.get('status', 'n/a')})")
                    continue
                lines.append(f"{stem:<44}{field:<32}{c['bandwidth_data_units']:>10.4g}"
                             f"{c['loo_brier']:>11.5f}{c['base_rate']:>8.3f}{c['n_valid']:>6}")
        lines.append("```")
        lines.append("")
    if summary.get("zero_inflated"):
        lines.append("## Zero-inflated occlusion sources")
        lines.append("")
        lines.append("```")
        lines.append(f"{'variable':<14}{'n_valid':>9}{'n_zero':>8}{'n_pos':>7}{'P(X=0)':>9}"
                     f"{'q50|X>0':>10}{'q95|X>0':>10}")
        lines.append("-" * 67)
        for field, info in summary["zero_inflated"].items():
            q = info["positive_quantiles"]
            lines.append(f"{field:<14}{info['n_valid']:>9}{info['n_zero']:>8}"
                         f"{info['n_positive']:>7}{info['p_zero']:>9.4f}"
                         f"{q['q50']:>10.4f}{q['q95']:>10.4f}")
        lines.append("```")
        lines.append("")
    na = summary.get("na_variables") or []
    lines.append("## Variables reported as N/A in this dataset")
    lines.append("")
    if na:
        seen = set()
        for entry in na:
            key = (entry["figure"], entry["variable"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- `{entry['variable']}` ({entry['figure']}): {entry['reason']}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Method notes")
    lines.append("")
    lines.append("- ECDF is the primary description; KDE is secondary and always reports its "
                 "bandwidth and boundary treatment.")
    lines.append("- Bounded variables use reflection boundary correction and no density is drawn "
                 "outside the prescription support.")
    lines.append("- Azimuth uses a von Mises circular KDE; a linear KDE is never applied to it.")
    lines.append("- Zero-inflated variables report P(X = 0) as a point mass and fit density only "
                 "to X > 0.")
    lines.append("- Discrete variables (V, G1-G5, cargo_on, scene preset, noise tier, ...) are "
                 "listed in `DISCRETE_FIELDS`; the KDE entry points raise "
                 "`DiscreteVariableError` if handed one.")
    lines.append("- Missing is `None` only: `0`, `0.0` and `False` are observations, never merged "
                 "into the missing bucket.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------
def analyze(
    root: Path,
    out_dir: Path,
    pnp_manifest: Path | None,
    pnp_study: Path | None,
    n_bootstrap: int,
    seed: int,
) -> dict[str, Any]:
    rows, meta = load_dataset(root, pnp_manifest, pnp_study)
    schema_keys = set(meta["schema_keys"])
    frame_rows = [r for r in rows if r["level"] == "frame"]
    rendered_rows = [r for r in frame_rows if bool_value(r.get("rendered")) is True]
    if not rendered_rows:
        rendered_rows = frame_rows

    out_dir.mkdir(parents=True, exist_ok=True)
    writer = FigureWriter(out_dir)
    metrics: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset": {k: v for k, v in meta.items() if k != "schema_keys"},
        "n_frame_rows": len(frame_rows),
        "n_rendered_rows": len(rendered_rows),
        "n_proposal_rows": len(rows),
        "bootstrap": {"n_bootstrap": n_bootstrap, "seed": seed,
                      "generator": "numpy.random.default_rng"},
        "discrete_fields_blocked_from_kde": sorted(DISCRETE_FIELDS),
    }

    # --- 8.1 univariate continuous -----------------------------------------------------
    figure_univariate(
        writer, "01_camera_distance_ecdf",
        "Camera distance: target vs actual", "Camera distance [m]", rendered_rows,
        [("camera_distance_target_m", "target", COLORS["target"]),
         ("camera_distance_actual_m", "actual", COLORS["actual"])],
        DOMAIN_CAMERA_DISTANCE, schema_keys, metrics, summary,
        domain_note=f"density clipped to {DOMAIN_CAMERA_DISTANCE} m (MAX_CAMERA_DISTANCE_M cap).")
    figure_univariate(
        writer, "02_projected_size_target_actual_ecdf",
        "Projected size ratio: target vs actual", "Projected size (image-width ratio)",
        rendered_rows,
        [("projected_size_target", "target", COLORS["target"]),
         ("projected_size_actual", "actual", COLORS["actual"])],
        DOMAIN_PROJ_SIZE, schema_keys, metrics, summary,
        domain_note="bounded on [0,1] with reflection boundary correction.")
    figure_univariate(
        writer, "03_elevation_target_actual_density",
        "Camera elevation: target vs actual", "Elevation [deg]", rendered_rows,
        [("elevation_deg_target", "target", COLORS["target"]),
         ("elevation_deg_actual", "actual", COLORS["actual"])],
        DOMAIN_ELEVATION, schema_keys, metrics, summary,
        domain_note=f"density clipped to the prescription range {DOMAIN_ELEVATION} deg.")
    figure_azimuth_circular(writer, rendered_rows, schema_keys, metrics, summary)
    figure_luma_by_scene(writer, rendered_rows, schema_keys, metrics, summary)
    figure_zero_inflated(writer, rendered_rows, schema_keys, metrics, summary)

    # --- 8.2 target vs actual ----------------------------------------------------------
    figure_target_vs_actual(
        writer, "07_elevation_target_vs_actual", "Elevation: target vs actual",
        rendered_rows, "elevation_deg_target", "elevation_deg_actual",
        "Target elevation [deg]", "Actual elevation [deg]", DOMAIN_ELEVATION,
        schema_keys, metrics, summary)
    figure_target_vs_actual(
        writer, "08_projected_size_target_vs_actual", "Projected size: target vs actual",
        rendered_rows, "projected_size_target", "projected_size_actual",
        "Target projected size", "Actual projected size", DOMAIN_PROJ_SIZE,
        schema_keys, metrics, summary)
    controlled_rendered = [r for r in rendered_rows
                           if group_label(r.get("diagnostic_mode")) == "controlled-occlusion"]
    controlled_proposals = [r for r in rows
                            if group_label(r.get("diagnostic_mode")) == "controlled-occlusion"]
    figure_target_vs_actual(
        writer, "09_f_target_vs_f_explicit_actual",
        "Controlled occlusion: f_target vs delivered f_explicit_actual",
        controlled_rendered, "f_target", "f_explicit_actual",
        "f_target (prescribed)", "f_explicit_actual (delivered)", DOMAIN_UNIT,
        schema_keys, metrics, summary, proposal_rows=controlled_proposals,
        delivery_note="controlled-occlusion rows only.")

    # --- 8.3 pass-probability curves ---------------------------------------------------
    figure_pass_probability(
        writer, "10_allpass_probability_vs_distance",
        "P(all_pass) vs camera distance (actual)", rendered_rows,
        "camera_distance_actual_m",
        [("all_pass", "all_pass", COLORS["target"]),
         ("physical_valid", "physical_valid", COLORS["third"]),
         ("pnp_eligible_candidate_3cell", "pnp_eligible_3cell", COLORS["fourth"])],
        "Camera distance (actual) [m]", schema_keys, metrics, summary, n_bootstrap, seed)
    figure_pass_probability(
        writer, "11_allpass_probability_vs_projected_size",
        "P(all_pass) vs projected size (actual)", rendered_rows,
        "projected_size_actual",
        [("all_pass", "all_pass", COLORS["target"]),
         ("physical_valid", "physical_valid", COLORS["third"]),
         ("pnp_eligible_candidate_3cell", "pnp_eligible_3cell", COLORS["fourth"])],
        "Projected size (actual, image-width ratio)", schema_keys, metrics, summary,
        n_bootstrap, seed, x_domain=DOMAIN_PROJ_SIZE,
        x_domain_note="projected_size_actual over-reads when cuboid corners leave the frame "
                      "or fall behind the camera (documented v2_realize limitation), so the fit "
                      "is confined to the physically meaningful [0,1] image-width ratio.")
    figure_pass_probability(
        writer, "12_allpass_probability_vs_f_total",
        "P(all_pass) vs total occlusion fraction", rendered_rows, "f_total",
        [("all_pass", "all_pass", COLORS["target"]),
         ("G1_pass", "G1_pass", COLORS["third"]),
         ("G3_pass", "G3_pass", COLORS["fourth"])],
        "f_total (visible-area occlusion fraction)", schema_keys, metrics, summary,
        n_bootstrap, seed, domain=DOMAIN_UNIT)
    pnp_outcomes = [("pnp_eligible_candidate_2cell", "eligible 2-cell (16px)", COLORS["target"]),
                    ("pnp_eligible_candidate_3cell", "eligible 3-cell (24px)", COLORS["third"]),
                    ("pnp_eligible_candidate_4cell", "eligible 4-cell (32px)", COLORS["fourth"])]
    if not any(field_in_schema(f, schema_keys) for f, _, _ in pnp_outcomes):
        pnp_outcomes = [("pnp_size_eligible_2cell", "size-eligible 2-cell (Phase 7)", COLORS["target"]),
                        ("pnp_size_eligible_3cell", "size-eligible 3-cell (Phase 7)", COLORS["third"]),
                        ("pnp_size_eligible_4cell", "size-eligible 4-cell (Phase 7)", COLORS["fourth"])]
    figure_pass_probability(
        writer, "13_pnp_stability_vs_projected_size",
        "PnP eligibility probability vs projected size (actual)", rendered_rows,
        "projected_size_actual", pnp_outcomes,
        "Projected size (actual, image-width ratio)", schema_keys, metrics, summary,
        n_bootstrap, seed, x_domain=DOMAIN_PROJ_SIZE,
        x_domain_note="same over-read caveat as figure 11.")

    # --- supplementary + appendix ------------------------------------------------------
    figure_univariate(
        writer, "14_fx_ecdf", "Supplementary: focal length fx", "fx [px]", rendered_rows,
        [("fx", "fx", COLORS["target"])], None, schema_keys, metrics, summary)
    figure_univariate(
        writer, "15_exposure_ev_ecdf", "Supplementary: exposure EV", "Exposure [EV]",
        rendered_rows, [("exposure_ev", "exposure_ev", COLORS["third"])],
        DOMAIN_EXPOSURE, schema_keys, metrics, summary,
        domain_note=f"prescription range {DOMAIN_EXPOSURE} EV.")
    figure_univariate(
        writer, "16_runtime_ecdf", "Supplementary: per-frame runtime", "Runtime [s]",
        rendered_rows, [("runtime_s", "runtime_s", COLORS["fourth"])], (0.0, math.inf),
        schema_keys, metrics, summary, domain_note="non-negative support.")
    discrete_rows = figure_discrete_appendix(writer, rendered_rows, schema_keys, summary)

    # --- outputs -----------------------------------------------------------------------
    summary["figures"] = writer.records
    produced = {rec["stem"] for rec in writer.records}
    summary["required_figures"] = REQUIRED_FIGURES
    summary["required_figures_present"] = sorted(produced & set(REQUIRED_FIGURES))
    summary["required_figures_missing"] = sorted(set(REQUIRED_FIGURES) - produced)
    write_metrics_csv(out_dir / "continuous_metrics.csv", metrics)
    write_discrete_csv(out_dir / "discrete_counts.csv", discrete_rows)
    (out_dir / "continuous_summary.json").write_text(
        json.dumps(_jsonable(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary_md(out_dir / "paper_continuous_summary.md", summary, writer.records)
    return summary


def _write_self_test_fixture(root: Path) -> None:
    """Tiny synthetic dataset exercising bins 0, False, zero-inflation and the seam."""
    rng = np.random.default_rng(7)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(60):
        az = float((i * 37) % 360)
        elev_t = float(0.5 + (i % 7) * 11.0)
        rec = {
            "idx": i, "rendered": True, "diagnostic_mode": ["clean-static", "cargo-only",
                                                            "context-rich", "controlled-occlusion"][i % 4],
            "cargo_on": bool(i % 2), "scene_preset": "random-mix",
            "camera_distance_limit_m": 10.0,
            "camera_distance_target_m": float(1.0 + (i % 9) * 0.9),
            "camera_distance_actual_m": float(1.0 + (i % 9) * 0.9 + rng.normal(0, 0.02)),
            "projected_size_target": float(0.05 + (i % 10) * 0.09),
            "projected_size_actual": float(0.05 + (i % 10) * 0.09 + rng.normal(0, 0.004)),
            "elev_target": elev_t, "elev_actual": elev_t + float(rng.normal(0, 0.4)),
            "azimuth_bin": i % 12, "elev_bin": i % 7, "proj_size_bin": i % 5,
            "v_target": 4 + (i % 5), "V_actual": 4 + (i % 5), "V_vis": (i % 9),
            "fx": 600.0 + (i % 5) * 20.0, "exposure_ev": -3.0 + (i % 8) * 0.4,
            "luma_frame_final": 20.0 + (i % 30), "luma_pallet_final": 8.0 + (i % 25),
            "noise_tier": ["clean", "low", "medium", "high"][i % 4],
            "f_static": 0.0 if i % 3 else float(rng.uniform(0.05, 0.5)),
            "f_cargo": 0.0 if i % 2 else float(rng.uniform(0.05, 0.4)),
            "f_context": 0.0, "f_explicit": 0.0 if i % 4 else float(rng.uniform(0.1, 0.6)),
            "f_total": float(rng.uniform(0.0, 0.6)) if i % 2 else 0.0,
            "f_target": float((i % 5) * 0.1),
            "f_explicit_actual": float((i % 5) * 0.1 + rng.normal(0, 0.01)),
            "runtime_s": float(2.0 + rng.gamma(2.0, 0.7)),
            "all_pass": bool(i % 5), "G1_pass": True, "G2_pass": True,
            "G3_pass": bool(i % 3), "G4_pass": True, "G5_pass": bool(i % 4),
            "physical_valid": bool(i % 3), "reject_reason": None,
        }
        records.append(rec)
        label = {
            "camera_data": {"width": 640, "height": 480, "resolution": [640, 480],
                            "aspect_label": "4:3", "fx_mode": "anchor",
                            "intrinsics": {"fx": rec["fx"], "fy": rec["fx"], "cx": 320.0, "cy": 240.0},
                            "scene_preset": "random-mix", "exposure_ev": rec["exposure_ev"],
                            "background_asset": "industrial"},
            "objects": [{"class": "pallet", "v2_labels": {"azimuth_deg_target": az,
                                                          "elevation_deg_target": elev_t,
                                                          "proj_size_ratio_target": rec["projected_size_target"]},
                         "scene_placement_v2": {"f_explicit_actual": rec["f_explicit_actual"]},
                         "safety_gates": {"all_pass": rec["all_pass"], "G1_Vvis>=4": True,
                                          "G2_extocc_1to4": True,
                                          "G3_visible>=0.5unocc": rec["G3_pass"],
                                          "G4_center_inframe": True,
                                          "G5_luma_floor": rec["G5_pass"]}}],
        }
        (root / "labels" / f"f{i:04d}_label.json").write_text(
            json.dumps(label), encoding="utf-8")
    with (root / "records.jsonl").open("w", encoding="utf-8") as stream:
        for rec in records:
            stream.write(json.dumps(rec) + "\n")


def run_self_test(n_bootstrap: int, seed: int) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "fixture"
        _write_self_test_fixture(root)
        summary = analyze(root, root / "eda" / "paper_continuous", None, None,
                          n_bootstrap=min(n_bootstrap, 200), seed=seed)
        missing = summary["required_figures_missing"]
        if missing:
            print(f"[self-test] FAIL missing figures: {missing}", file=sys.stderr)
            return 1
        az = summary.get("azimuth_circular") or {}
        if az.get("seam_abs_difference", 1.0) > 1e-9:
            print(f"[self-test] FAIL azimuth seam discontinuity: {az}", file=sys.stderr)
            return 1
        zi = summary.get("zero_inflated") or {}
        if "f_cargo" not in zi or not (0.0 <= zi["f_cargo"]["p_zero"] <= 1.0):
            print("[self-test] FAIL zero-inflated handling", file=sys.stderr)
            return 1
        print(f"[self-test] OK: {len(summary['figures'])} figures, "
              f"seam |df| = {az.get('seam_abs_difference'):.3e}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dir", default=DEFAULT_DIR, help="dataset root")
    p.add_argument("--out", default=None, help=f"output dir (default <dir>/{DEFAULT_OUT_SUBDIR})")
    p.add_argument("--pnp-manifest", default=DEFAULT_PNP_MANIFEST,
                   help="PnP eligibility manifest CSV (Phase 4); ignored when absent")
    p.add_argument("--pnp-study", default=DEFAULT_PNP_STUDY,
                   help="PnP threshold study CSV (Phase 4); ignored when absent")
    p.add_argument("--bootstrap", type=int, default=BOOTSTRAP_DEFAULT)
    p.add_argument("--seed", type=int, default=BOOTSTRAP_SEED_DEFAULT)
    p.add_argument("--self-test", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test(args.bootstrap, args.seed)
    root = Path(args.dir)
    if not root.is_dir():
        print(f"dataset dir not found: {root}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else root / DEFAULT_OUT_SUBDIR
    manifest = Path(args.pnp_manifest) if args.pnp_manifest else None
    if manifest is not None and not manifest.exists():
        manifest = None
    study = Path(args.pnp_study) if args.pnp_study else None
    if study is not None and not study.exists():
        study = None
    summary = analyze(root, out_dir, manifest, study, args.bootstrap, args.seed)
    print(f"rows: {summary['n_proposal_rows']} (rendered {summary['n_rendered_rows']})")
    print(f"figures written: {len(summary['figures'])} -> {out_dir}")
    if summary["required_figures_missing"]:
        print(f"MISSING required figures: {summary['required_figures_missing']}", file=sys.stderr)
        return 1
    na = {(e['variable']) for e in (summary.get('na_variables') or [])}
    if na:
        print(f"N/A variables in this dataset: {sorted(na)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
