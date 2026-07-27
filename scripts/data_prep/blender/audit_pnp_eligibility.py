"""PnP eligibility study for v2 constrained frames (bpy-free).

Separates two different questions that the v2 pipeline used to conflate:

  1. "does the frame pass the safety gates G1..G5 and the physical checks?"  (gate_valid / physical_valid)
  2. "is the frame actually USEFUL for keypoint/PnP learning?"               (pnp_eligible_* candidates)

For every frame that has a label this script measures the projected target size, the visible
keypoint configuration, solves the exact-GT PnP problem and then perturbs the 2D keypoints with
isotropic Gaussian noise (sigma = 1/2/3 px, Monte-Carlo) to see how fast the recovered 6D pose
degrades. The result is a per-frame CSV, a methodology/summary markdown and a continuous
stability PDF.

NO frame is deleted or filtered here. The manifest only ADDS fields.

Outputs (default under reports/v2_revision/):
  pnp_threshold_study.csv          per-frame raw measurements
  pnp_threshold_study.md           methodology + summary + candidate comparison
  pnp_stability_continuous.pdf     Monte-Carlo stability as continuous curves
  pnp_eligibility_manifest.csv     manifest fields only (idx + the new booleans)
  pnp_eligibility_manifest.json    run metadata + aggregate counts

Usage:
  python scripts/data_prep/blender/audit_pnp_eligibility.py --dir data/pallet/<dataset>
  python scripts/data_prep/blender/audit_pnp_eligibility.py --self-test
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
for _p in (str(_THIS_DIR), str(_REPO_ROOT / "scripts" / "self_training")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cv2  # noqa: E402  (project dependency, see requirements.txt)

from blender_math import build_view_matrix  # noqa: E402  (bpy-free helper)
from pnp_solver import PalletPnPSolver, make_pallet_keypoints_3d  # noqa: E402


def _load_audit_module():
    """Reuse the existing bpy-free audit helpers (records/label/mask loaders)."""
    path = _THIS_DIR / "audit_v2_scene_logic.py"
    spec = importlib.util.spec_from_file_location("audit_v2_scene_logic", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("audit_v2_scene_logic", module)
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit_module()


# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

# Belief-map stride, in ORIGINAL image pixels.
#   Deep_Object_Pose/common/models.py:26-40 -> VGG19 trunk keeps 3 MaxPool2d(2) and every
#   later conv has stride 1, so the map is 1/8 of the network input (config/default.yaml:13-14,
#   input 448 -> output 56).
#   Deep_Object_Pose/common/utils.py:340,356-372 -> the training loader takes a *pixel identity*
#   A.RandomCrop(400,400) of the source image and only rescales the KEYPOINTS to the belief-map
#   grid; the image tensor fed to the net is the un-resized crop (utils.py:419). There is no
#   image rescale between the source PNG and the network input, therefore
#   1 belief-map cell == 8 source-image pixels.  [확인]
BELIEF_CELL_PX = 8.0
THRESHOLD_CANDIDATES: dict[str, float] = {
    "2cell": 2 * BELIEF_CELL_PX,   # 16 px
    "3cell": 3 * BELIEF_CELL_PX,   # 24 px
    "4cell": 4 * BELIEF_CELL_PX,   # 32 px
}

# Corner is "externally occluded" at >= 0.5, matching scene_placement_v2.external_corner_gate_metrics.
OCCLUSION_VISIBLE_MAX = 0.5

# PnP configuration: identical to the real evaluation path (scripts/self_training/pnp_solver.py:133-139
# with config/stage3_selftrain.yaml:59 ransac_reproj_threshold=8.0).
PNP_RANSAC_REPROJ_PX = 8.0
PNP_RANSAC_ITERS = 100

# Monte-Carlo perturbation study.
MC_SIGMAS_PX = (1.0, 2.0, 3.0)
MC_TRIALS = 200
MC_SEED = 20260727

# Pose correctness: scripts/self_training/metrics.py:143 (5cm-5deg).
POSE_TRANS_TOL_CM = 5.0
POSE_ROT_TOL_DEG = 5.0
# "obviously diverged" (much weaker than the 5cm5deg criterion, used to separate a wrong-but-close
# solution from a numerically blown-up one).
DIVERGENCE_TRANS_M = 1.0
DIVERGENCE_ROT_DEG = 45.0

# pnp_stress / tiny_warning rules (documented in the markdown report).
STRESS_SIGMA_PX = 2.0
STRESS_POSE_FAIL_RATE = 0.5
STRESS_DIVERGED_RATE = 0.05
# A threshold would only be "sufficient" if the frames it accepts are mostly pose-recoverable
# under realistic keypoint noise. [미검증 시작값] - used ONLY to decide whether the evidence
# supports fixing a hard threshold, never to filter a frame.
STABILITY_TARGET_FAIL_RATE = 0.10
# A data-identified breakpoint requires the accepted-set failure rate to DROP at one threshold
# instead of decaying smoothly; "drop" = a step at least this many times the median step.
KNEE_STEP_RATIO = 2.0
TINY_MASK_AREA_PX = int(THRESHOLD_CANDIDATES["2cell"] ** 2)  # 256 px^2

DEFAULT_DIR = "data/pallet/_v2_scene_logic_500_seed7500"
DEFAULT_OUT = "reports/v2_revision"

# Fallback camera-distance cap when the record predates Phase 1 (v2_pipeline.MAX_CAMERA_DISTANCE_M).
FALLBACK_CAMERA_DISTANCE_LIMIT_M = 10.0


# --------------------------------------------------------------------------------------
# Small numeric helpers
# --------------------------------------------------------------------------------------

def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def rotation_geodesic_deg(r_a: np.ndarray, r_b: np.ndarray) -> float | None:
    """Geodesic angle between two rotations. None when either matrix is not a rotation."""
    for r in (r_a, r_b):
        if r is None or r.shape != (3, 3) or not np.isfinite(r).all():
            return None
        if abs(float(np.linalg.det(r)) - 1.0) > 1e-3:
            return None
    cos = (float(np.trace(r_a.T @ r_b)) - 1.0) / 2.0
    return float(math.degrees(math.acos(max(-1.0, min(1.0, cos)))))


def bbox_metrics(points: np.ndarray | None) -> dict[str, float | None]:
    out = {"w": None, "h": None, "min_side": None, "max_side": None, "diag": None, "area": None}
    if points is None or len(points) == 0:
        return out
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] < 2 or not np.isfinite(p[:, :2]).all():
        return out
    w = float(p[:, 0].max() - p[:, 0].min())
    h = float(p[:, 1].max() - p[:, 1].min())
    out.update({"w": w, "h": h, "min_side": min(w, h), "max_side": max(w, h),
                "diag": float(math.hypot(w, h)), "area": w * h})
    return out


def min_pair_distance(points: np.ndarray | None) -> float | None:
    if points is None or len(points) < 2:
        return None
    p = np.asarray(points, dtype=np.float64)[:, :2]
    d = np.linalg.norm(p[:, None, :] - p[None, :, :], axis=-1)
    iu = np.triu_indices(len(p), k=1)
    vals = d[iu]
    return float(vals.min()) if vals.size else None


def convex_hull_area(points: np.ndarray | None) -> float | None:
    """Convex-hull area in px^2 (OpenCV convexHull; 0.0 for < 3 points or degenerate sets)."""
    if points is None or len(points) < 3:
        return 0.0 if points is not None else None
    p = np.asarray(points, dtype=np.float32)[:, :2].reshape(-1, 1, 2)
    try:
        hull = cv2.convexHull(p)
        return float(abs(cv2.contourArea(hull)))
    except cv2.error:
        return None


def mask_bbox(mask_img) -> dict[str, float | None]:
    """Foreground bbox of a decoded PIL 'L' mask (>127 = foreground)."""
    out = {"w": None, "h": None, "min_side": None}
    if mask_img is None:
        return out
    arr = np.asarray(mask_img)
    fg = arr > 127
    if not fg.any():
        return {"w": 0.0, "h": 0.0, "min_side": 0.0}
    rows = np.where(fg.any(axis=1))[0]
    cols = np.where(fg.any(axis=0))[0]
    w = float(cols[-1] - cols[0] + 1)
    h = float(rows[-1] - rows[0] + 1)
    return {"w": w, "h": h, "min_side": min(w, h)}


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"q50": None, "q90": None, "q95": None}
    arr = np.asarray(values, dtype=np.float64)
    return {
        "q50": float(np.percentile(arr, 50)),
        "q90": float(np.percentile(arr, 90)),
        "q95": float(np.percentile(arr, 95)),
    }


# --------------------------------------------------------------------------------------
# Frame geometry
# --------------------------------------------------------------------------------------

def frame_geometry(lab: dict[str, Any] | None, obj: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract the exact 3D<->2D correspondence for one frame.

    The 3D points are the label's OWN world-frame cuboid re-expressed in a centroid-centred,
    world-axis-aligned object frame (X_obj = X_world - centroid_world). This is intentional:

      * label['objects'][0]['cuboid'] and ['projected_cuboid'] are written from the SAME
        camera-facing v4 permutation (v2_realize.label():3889-3891), so their index-to-index
        correspondence is exact by construction and independent of any keypoint convention.
      * pnp_solver.make_pallet_keypoints_3d() assumes a FIXED object frame; on real v2 labels the
        implied object frame changes per frame with perm_v4, so a fixed canonical point set does
        NOT reproduce the labelled pose (measured: up to 426 px reprojection error).
      * Centring on the centroid keeps PalletPnPSolver.solve()'s "object behind camera" flip
        (pnp_solver.py:154-156) meaningful and makes the recovered translation the object
        centroid in camera frame, i.e. exactly label['objects'][0]['location'].

    Returns None when the label lacks the fields needed for PnP.
    """
    if not isinstance(lab, dict) or not isinstance(obj, dict):
        return None
    cam = lab.get("camera_data")
    if not isinstance(cam, dict):
        return None
    intr = cam.get("intrinsics")
    if not isinstance(intr, dict):
        return None
    fx, fy = _f(intr.get("fx")), _f(intr.get("fy"))
    cx, cy = _f(intr.get("cx")), _f(intr.get("cy"))
    width, height = _f(cam.get("width")), _f(cam.get("height"))
    if None in (fx, fy, cx, cy, width, height):
        return None

    ok_c, corners_w = AUDIT.finite_point_list(obj.get("cuboid"), expected=8)
    ok_p, uv8 = AUDIT.finite_point_list(obj.get("projected_cuboid"), expected=8)
    if not ok_c or not ok_p or corners_w is None or uv8 is None or corners_w.shape[1] != 3:
        return None
    cam_pos = obj_pos = None
    try:
        cam_pos = np.asarray(cam["location_worldframe"], dtype=np.float64)
        obj_pos = np.asarray(cam["look_worldframe"], dtype=np.float64)
    except Exception:
        return None
    if cam_pos.shape != (3,) or obj_pos.shape != (3,):
        return None

    centroid_w = corners_w.mean(axis=0)
    r_w2c, t_w2c = build_view_matrix(cam_pos, obj_pos, up=(0, 0, 1))
    k = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)

    pts_cam = (r_w2c @ corners_w.T).T + t_w2c
    z8 = pts_cam[:, 2].copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        proj = (k @ pts_cam.T).T
        uv8_check = proj[:, :2] / proj[:, 2:3]
    consistency = float(np.abs(uv8_check - uv8[:, :2]).max()) if np.isfinite(uv8_check).all() else None

    cent_uv = obj.get("projected_cuboid_centroid")
    cent_cam = r_w2c @ centroid_w + t_w2c
    if isinstance(cent_uv, (list, tuple)) and len(cent_uv) >= 2 and all(
            _f(v) is not None for v in cent_uv[:2]):
        cent_uv = np.array([float(cent_uv[0]), float(cent_uv[1])], dtype=np.float64)
    else:
        cent_uv = np.array([k[0, 0] * cent_cam[0] / cent_cam[2] + k[0, 2],
                            k[1, 1] * cent_cam[1] / cent_cam[2] + k[1, 2]], dtype=np.float64)

    uv9 = np.vstack([uv8[:, :2], cent_uv[None, :]])
    z9 = np.concatenate([z8, [float(cent_cam[2])]])
    pts_obj9 = np.vstack([corners_w - centroid_w, np.zeros((1, 3))])

    occ = obj.get("v2_labels", {}).get("occlusion_fraction") if isinstance(obj.get("v2_labels"), dict) else None
    occ9 = np.full(9, np.nan)
    if isinstance(occ, (list, tuple)):
        for i, v in enumerate(occ[:9]):
            fv = _f(v)
            if fv is not None:
                occ9[i] = fv

    in_frame = np.array([
        bool(z9[i] > 1e-9 and 0.0 <= uv9[i, 0] <= width and 0.0 <= uv9[i, 1] <= height)
        for i in range(9)
    ])
    # unknown occlusion is treated as NOT occluded (matches the gate's tri-state elsewhere:
    # only an explicit >= 0.5 measurement kills a corner).
    not_occluded = np.array([
        bool(math.isnan(occ9[i]) or occ9[i] < OCCLUSION_VISIBLE_MAX) for i in range(9)
    ])
    visible = in_frame & not_occluded

    return {
        "K": k, "W": width, "H": height,
        "corners_world": corners_w, "centroid_world": centroid_w,
        "cam_pos": cam_pos, "R_w2c": r_w2c, "t_w2c": t_w2c,
        "uv9": uv9, "z9": z9, "pts_obj9": pts_obj9,
        "occ9": occ9, "in_frame": in_frame, "visible": visible,
        "t_obj_cam": r_w2c @ centroid_w + t_w2c,
        "label_reproj_consistency_px": consistency,
        "camera_distance_measured_m": float(np.linalg.norm(cam_pos - centroid_w)),
    }


def make_solver(k: np.ndarray, pts_obj9: np.ndarray) -> PalletPnPSolver:
    """PalletPnPSolver with the exact evaluation settings, driven by this frame's 3D points."""
    solver = PalletPnPSolver(
        k,
        use_ransac=True,
        ransac_reproj_threshold=PNP_RANSAC_REPROJ_PX,
        ransac_iterations=PNP_RANSAC_ITERS,
    )
    solver.keypoints_3d = np.asarray(pts_obj9, dtype=np.float64)
    return solver


def _kp_list(uv9: np.ndarray, visible: np.ndarray) -> list[Any]:
    return [(float(uv9[i, 0]), float(uv9[i, 1])) if visible[i] else None for i in range(9)]


def solve_pose(solver: PalletPnPSolver, uv9: np.ndarray, visible: np.ndarray) -> dict[str, Any]:
    """Run the evaluation PnP on the visible keypoints only."""
    out: dict[str, Any] = {"success": False, "R": None, "t": None, "n_inliers": None,
                           "reproj_mean_px": None, "reproj_max_px": None}
    if int(visible.sum()) < 4:
        return out
    ok, r, t, inliers = solver.solve(_kp_list(uv9, visible))
    if not ok or r is None or t is None:
        return out
    out.update({"success": True, "R": r, "t": t,
                "n_inliers": int(len(inliers)) if inliers is not None else None})
    try:
        rep = solver.reproject(r, t)
        err = np.linalg.norm(rep[:9][visible] - uv9[visible], axis=1)
        if np.isfinite(err).all():
            out["reproj_mean_px"] = float(err.mean())
            out["reproj_max_px"] = float(err.max())
    except cv2.error:
        pass
    return out


def pose_error(sol: dict[str, Any], geo: dict[str, Any]) -> dict[str, float | None]:
    if not sol.get("success"):
        return {"trans_cm": None, "rot_deg": None}
    t_err = float(np.linalg.norm(np.asarray(sol["t"]) - geo["t_obj_cam"]) * 100.0)
    r_err = rotation_geodesic_deg(np.asarray(sol["R"]), geo["R_w2c"])
    return {"trans_cm": t_err if math.isfinite(t_err) else None, "rot_deg": r_err}


def monte_carlo(geo: dict[str, Any], solver: PalletPnPSolver, sigma_px: float,
                trials: int, seed: int) -> dict[str, Any]:
    """Isotropic Gaussian keypoint perturbation -> pose error distribution.

    Deterministic: numpy Generator(seed) for the noise, cv2.setRNGSeed for RANSAC.
    """
    visible = geo["visible"]
    res: dict[str, Any] = {
        "n_trials": 0, "solve_fail_rate": None, "diverged_rate": None, "pose_fail_rate": None,
        "trans_cm": {"q50": None, "q90": None, "q95": None},
        "rot_deg": {"q50": None, "q90": None, "q95": None},
        "reproj_px": {"q50": None, "q90": None, "q95": None},
    }
    if int(visible.sum()) < 4:
        return res

    rng = np.random.default_rng(seed)
    cv2.setRNGSeed(int(seed % (2 ** 31 - 1)))
    uv9 = geo["uv9"]
    n_solve_fail = 0
    n_diverged = 0
    n_pose_fail = 0
    trans, rots, reps = [], [], []
    for _ in range(int(trials)):
        noisy = uv9 + rng.normal(0.0, sigma_px, uv9.shape)
        sol = solve_pose(solver, noisy, visible)
        if not sol["success"]:
            n_solve_fail += 1
            n_pose_fail += 1
            n_diverged += 1
            continue
        err = pose_error(sol, geo)
        t_cm, r_deg = err["trans_cm"], err["rot_deg"]
        if t_cm is None or r_deg is None:
            n_diverged += 1
            n_pose_fail += 1
            continue
        trans.append(t_cm)
        rots.append(r_deg)
        if sol["reproj_mean_px"] is not None:
            reps.append(sol["reproj_mean_px"])
        if t_cm > DIVERGENCE_TRANS_M * 100.0 or r_deg > DIVERGENCE_ROT_DEG:
            n_diverged += 1
        if not (t_cm < POSE_TRANS_TOL_CM and r_deg < POSE_ROT_TOL_DEG):
            n_pose_fail += 1

    n = int(trials)
    res.update({
        "n_trials": n,
        "solve_fail_rate": n_solve_fail / n,
        "diverged_rate": n_diverged / n,
        "pose_fail_rate": n_pose_fail / n,
        "trans_cm": quantiles(trans),
        "rot_deg": quantiles(rots),
        "reproj_px": quantiles(reps),
    })
    return res


# --------------------------------------------------------------------------------------
# Validity / eligibility
# --------------------------------------------------------------------------------------

PHYSICAL_BOOL_FIELDS = (
    "rendered", "realize_ok", "camera_clearance_pass", "support_pass",
    "mask_invariants_pass", "ground_continuity_pass",
)
PHYSICAL_NEGATED_FIELDS = ("corrupt_rgb", "corrupt_mask")
GATE_BOOL_FIELDS = ("G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass")


def physical_validity(rec: dict[str, Any] | None, geo: dict[str, Any] | None,
                      m0_area: int | None) -> dict[str, Any]:
    """physical_valid = no KNOWN physical violation.

    Composed from the fields audit_v2_scene_logic already trusts (collision / clearance /
    support / mask invariants / corrupt decode) plus Phase 1 (camera distance cap) and Phase 2
    (ground continuity). Fields that a pre-Phase dataset does not carry are reported as
    'unknown' instead of silently passing or failing.
    """
    violations: list[str] = []
    unknown: list[str] = []
    rec = rec or {}

    for key in PHYSICAL_BOOL_FIELDS:
        val = AUDIT.bool_value(rec.get(key))
        if val is None:
            unknown.append(key)
        elif not val:
            violations.append(key)
    for key in PHYSICAL_NEGATED_FIELDS:
        val = AUDIT.bool_value(rec.get(key))
        if val is None:
            unknown.append(key)
        elif val:
            violations.append(key)

    coll = AUDIT.int_value(rec.get("exact_collision_count"))
    if coll is None:
        unknown.append("exact_collision_count")
    elif coll > 0:
        violations.append("exact_collision_count")

    limit = _f(rec.get("camera_distance_limit_m")) or FALLBACK_CAMERA_DISTANCE_LIMIT_M
    dist = _f(rec.get("camera_distance_actual_m"))
    dist_source = "record"
    if dist is None and geo is not None:
        dist = geo["camera_distance_measured_m"]
        dist_source = "label_recomputed"
    if dist is None:
        unknown.append("camera_distance_actual_m")
    elif dist > limit + 1e-6:
        violations.append("camera_distance_over_limit")

    if m0_area is None:
        unknown.append("mask_m0_area")
    elif m0_area <= 0:
        violations.append("empty_target_mask")

    return {
        "physical_valid": not violations,
        "physical_violations": violations,
        "physical_unknown": unknown,
        "camera_distance_used_m": dist,
        "camera_distance_source": dist_source if dist is not None else None,
        "camera_distance_limit_m": limit,
    }


def gate_validity(rec: dict[str, Any] | None, obj: dict[str, Any] | None) -> dict[str, Any]:
    """gate_valid = G1..G5 all pass (record first, label safety_gates as fallback)."""
    rec = rec or {}
    gates = obj.get("safety_gates") if isinstance(obj, dict) else None
    gates = gates if isinstance(gates, dict) else {}
    label_keys = ["G1_Vvis>=4", "G2_extocc_1to4", "G3_visible>=0.5unocc", "G4_center_inframe",
                  "G5_luma_floor"]
    values: dict[str, bool | None] = {}
    unknown: list[str] = []
    for key, lkey in zip(GATE_BOOL_FIELDS, label_keys):
        val = AUDIT.bool_value(rec.get(key))
        if val is None:
            val = AUDIT.bool_value(gates.get(lkey))
        values[key] = val
        if val is None:
            unknown.append(key)
    all_pass = AUDIT.bool_value(rec.get("all_pass"))
    if all_pass is None:
        all_pass = AUDIT.bool_value(gates.get("all_pass"))
    known = [v for v in values.values() if v is not None]
    derived = bool(known) and all(known) and not unknown
    return {
        "gate_valid": bool(all_pass) if all_pass is not None else derived,
        "gate_valid_unknown": bool(unknown),
        "gate_unknown_fields": unknown,
        **values,
    }


def eligibility(row: dict[str, Any]) -> dict[str, Any]:
    """Threshold candidates + tiny/stress warnings.

    Size measure = min(bbox_w, bbox_h) of the VISIBLE keypoints (see markdown 'Why min side').
    """
    min_side = row.get("bbox_vis_min_side_px")
    success = bool(row.get("pnp_exact_success"))
    out: dict[str, Any] = {}
    for name, thr in THRESHOLD_CANDIDATES.items():
        out[f"pnp_eligible_candidate_{name}"] = bool(
            success and min_side is not None and min_side >= thr
        )
    m0 = row.get("mask_m0_area")
    out["tiny_warning"] = bool(
        (min_side is not None and min_side < THRESHOLD_CANDIDATES["2cell"])
        or (m0 is not None and m0 < TINY_MASK_AREA_PX)
    )
    key = f"mc{int(STRESS_SIGMA_PX)}px"
    pose_fail = row.get(f"{key}_pose_fail_rate")
    diverged = row.get(f"{key}_diverged_rate")
    out["pnp_stress"] = bool(
        (not success)
        or (pose_fail is not None and pose_fail > STRESS_POSE_FAIL_RATE)
        or (diverged is not None and diverged > STRESS_DIVERGED_RATE)
    )
    return out


# --------------------------------------------------------------------------------------
# Per-frame evaluation
# --------------------------------------------------------------------------------------

def evaluate_frame(root: Path, idx: int, rec: dict[str, Any] | None, args) -> dict[str, Any]:
    frame_id = f"f{idx:04d}"
    row: dict[str, Any] = {"idx": idx, "frame_id": frame_id}
    lab, obj, v2 = AUDIT.load_label(root, idx)
    row["label_present"] = lab is not None
    rec = rec or {}
    row["rendered"] = AUDIT.bool_value(rec.get("rendered"))
    row["pallet_type"] = rec.get("pallet_type") or (v2 or {}).get("pallet_type")
    row["diagnostic_mode"] = rec.get("diagnostic_mode") or (
        AUDIT.nested(obj, ["scene_placement_v2", "diagnostic_mode"]) if obj else None)
    row["noise_tier"] = rec.get("noise_tier")

    m0 = AUDIT.mask_area(root / "mask" / f"{frame_id}_m0.png")
    row["mask_m0_area"] = m0.get("area")
    mb = mask_bbox(m0.get("image"))
    row["mask_m0_bbox_w_px"] = mb["w"]
    row["mask_m0_bbox_h_px"] = mb["h"]
    row["mask_m0_min_side_px"] = mb["min_side"]

    geo = frame_geometry(lab, obj)
    row["geometry_ok"] = geo is not None
    if geo is None:
        row.update(physical_validity(rec, None, row["mask_m0_area"]))
        row.update(gate_validity(rec, obj))
        row["pnp_exact_success"] = False
        row.update(eligibility(row))
        return row

    row["image_w"] = geo["W"]
    row["image_h"] = geo["H"]
    row["fx"] = float(geo["K"][0, 0])
    row["fy"] = float(geo["K"][1, 1])
    row["cx"] = float(geo["K"][0, 2])
    row["cy"] = float(geo["K"][1, 2])
    row["label_reproj_consistency_px"] = geo["label_reproj_consistency_px"]
    row["camera_distance_measured_m"] = geo["camera_distance_measured_m"]
    row["elevation_deg_actual"] = _f((v2 or {}).get("elevation_deg_actual"))
    row["projected_size_actual"] = _f((v2 or {}).get("projected_size_actual"))
    row["object_depth_z_m"] = float(geo["t_obj_cam"][2])

    uv9, visible, in_frame = geo["uv9"], geo["visible"], geo["in_frame"]
    row["visible_kp_count"] = int(visible.sum())
    row["visible_corner_count"] = int(visible[:8].sum())
    row["inframe_corner_count"] = int(in_frame[:8].sum())
    row["V_vis_label"] = AUDIT.int_value((v2 or {}).get("V_vis_actual"))
    row["visible_corner_count_matches_label"] = (
        None if row["V_vis_label"] is None else bool(row["V_vis_label"] == row["visible_corner_count"])
    )

    all_bbox = bbox_metrics(uv9[:8])
    row["bbox_all_w_px"] = all_bbox["w"]
    row["bbox_all_h_px"] = all_bbox["h"]
    row["bbox_all_min_side_px"] = all_bbox["min_side"]
    row["bbox_all_diag_px"] = all_bbox["diag"]

    vis_pts = uv9[visible]
    vis_bbox = bbox_metrics(vis_pts if len(vis_pts) else None)
    row["bbox_vis_w_px"] = vis_bbox["w"]
    row["bbox_vis_h_px"] = vis_bbox["h"]
    row["bbox_vis_min_side_px"] = vis_bbox["min_side"]
    row["bbox_vis_diag_px"] = vis_bbox["diag"]
    row["bbox_vis_area_px2"] = vis_bbox["area"]
    row["visible_kp_min_pair_dist_px"] = min_pair_distance(vis_pts if len(vis_pts) else None)
    row["visible_kp_hull_area_px2"] = convex_hull_area(vis_pts if len(vis_pts) else None)

    solver = make_solver(geo["K"], geo["pts_obj9"])
    cv2.setRNGSeed(int(args.seed % (2 ** 31 - 1)))
    sol = solve_pose(solver, uv9, visible)
    row["pnp_exact_success"] = bool(sol["success"])
    row["pnp_exact_inliers"] = sol["n_inliers"]
    row["pnp_exact_reproj_mean_px"] = sol["reproj_mean_px"]
    row["pnp_exact_reproj_max_px"] = sol["reproj_max_px"]
    err = pose_error(sol, geo)
    row["pnp_exact_trans_err_cm"] = err["trans_cm"]
    row["pnp_exact_rot_err_deg"] = err["rot_deg"]

    # Cross-check: does a FIXED canonical object frame (pnp_solver.make_pallet_keypoints_3d with
    # this frame's dimensions_m) explain the same 2D points? Reported, never used for the study.
    row["canonical3d_exact_reproj_mean_px"] = _canonical_check(obj, geo, visible)

    for sigma in args.sigmas:
        key = f"mc{int(sigma)}px"
        mc = monte_carlo(geo, solver, sigma, args.mc_trials,
                         seed=args.seed + idx * 1000 + int(sigma))
        row[f"{key}_solve_fail_rate"] = mc["solve_fail_rate"]
        row[f"{key}_diverged_rate"] = mc["diverged_rate"]
        row[f"{key}_pose_fail_rate"] = mc["pose_fail_rate"]
        for metric in ("trans_cm", "rot_deg", "reproj_px"):
            for q in ("q50", "q90", "q95"):
                row[f"{key}_{metric}_{q}"] = mc[metric][q]

    row.update(physical_validity(rec, geo, row["mask_m0_area"]))
    row.update(gate_validity(rec, obj))
    row.update(eligibility(row))
    return row


def _canonical_check(obj: dict[str, Any] | None, geo: dict[str, Any],
                     visible: np.ndarray) -> float | None:
    """Exact-GT reprojection error when the canonical (fixed) object frame is assumed."""
    if not isinstance(obj, dict):
        return None
    dims = obj.get("dimensions_m")
    if not isinstance(dims, dict):
        return None
    w, h, d = _f(dims.get("width")), _f(dims.get("height")), _f(dims.get("depth"))
    if None in (w, h, d):
        return None
    pts = make_pallet_keypoints_3d(w, d, h)
    solver = make_solver(geo["K"], pts)
    sol = solve_pose(solver, geo["uv9"], visible)
    return sol["reproj_mean_px"] if sol["success"] else None


# --------------------------------------------------------------------------------------
# Output columns
# --------------------------------------------------------------------------------------

def study_columns(sigmas) -> list[str]:
    cols = [
        "idx", "frame_id", "label_present", "geometry_ok", "rendered", "pallet_type",
        "diagnostic_mode", "noise_tier", "image_w", "image_h", "fx", "fy", "cx", "cy",
        "label_reproj_consistency_px", "camera_distance_measured_m", "camera_distance_used_m",
        "camera_distance_source", "camera_distance_limit_m", "elevation_deg_actual",
        "projected_size_actual", "object_depth_z_m",
        "mask_m0_area", "mask_m0_bbox_w_px", "mask_m0_bbox_h_px", "mask_m0_min_side_px",
        "bbox_all_w_px", "bbox_all_h_px", "bbox_all_min_side_px", "bbox_all_diag_px",
        "bbox_vis_w_px", "bbox_vis_h_px", "bbox_vis_min_side_px", "bbox_vis_diag_px",
        "bbox_vis_area_px2", "visible_kp_min_pair_dist_px", "visible_kp_hull_area_px2",
        "inframe_corner_count", "visible_corner_count", "visible_kp_count", "V_vis_label",
        "visible_corner_count_matches_label",
        "pnp_exact_success", "pnp_exact_inliers", "pnp_exact_reproj_mean_px",
        "pnp_exact_reproj_max_px", "pnp_exact_trans_err_cm", "pnp_exact_rot_err_deg",
        "canonical3d_exact_reproj_mean_px",
    ]
    for sigma in sigmas:
        key = f"mc{int(sigma)}px"
        cols += [f"{key}_solve_fail_rate", f"{key}_diverged_rate", f"{key}_pose_fail_rate"]
        for metric in ("trans_cm", "rot_deg", "reproj_px"):
            cols += [f"{key}_{metric}_{q}" for q in ("q50", "q90", "q95")]
    cols += [
        "physical_valid", "physical_violations", "physical_unknown",
        "gate_valid", "gate_valid_unknown", "gate_unknown_fields",
        "G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass",
    ]
    cols += [f"pnp_eligible_candidate_{name}" for name in THRESHOLD_CANDIDATES]
    cols += ["tiny_warning", "pnp_stress"]
    return cols


MANIFEST_COLUMNS = [
    "idx", "frame_id", "rendered", "physical_valid", "gate_valid",
    *[f"pnp_eligible_candidate_{name}" for name in THRESHOLD_CANDIDATES],
    "tiny_warning", "pnp_stress",
    "bbox_vis_min_side_px", "mask_m0_area", "visible_kp_count", "pnp_exact_success",
    "physical_unknown", "gate_unknown_fields",
]


def _csv_ready(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = {}
        for col in columns:
            val = row.get(col)
            if isinstance(val, list):
                val = "|".join(str(v) for v in val)
            item[col] = val
        out.append(item)
    return out


# --------------------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------------------

def _vals(rows, key, where=None) -> list[float]:
    out = []
    for row in rows:
        if where is not None and not where(row):
            continue
        v = row.get(key)
        fv = _f(v)
        if fv is not None:
            out.append(fv)
    return out


def summarize(rows: list[dict[str, Any]], sigmas) -> dict[str, Any]:
    solved = [r for r in rows if r.get("pnp_exact_success")]
    summary: dict[str, Any] = {
        "n_frames": len(rows),
        "n_label_present": sum(1 for r in rows if r.get("label_present")),
        "n_geometry_ok": sum(1 for r in rows if r.get("geometry_ok")),
        "n_pnp_exact_success": len(solved),
        "n_physical_valid": sum(1 for r in rows if r.get("physical_valid")),
        "n_gate_valid": sum(1 for r in rows if r.get("gate_valid")),
        "n_tiny_warning": sum(1 for r in rows if r.get("tiny_warning")),
        "n_pnp_stress": sum(1 for r in rows if r.get("pnp_stress")),
        "belief_cell_px": BELIEF_CELL_PX,
        "thresholds_px": dict(THRESHOLD_CANDIDATES),
        "candidates": {},
        "stress_by_candidate": {},
        "sigmas": list(sigmas),
    }
    cons = _vals(rows, "label_reproj_consistency_px")
    summary["label_reproj_consistency_px_max"] = max(cons) if cons else None
    canon = _vals(rows, "canonical3d_exact_reproj_mean_px")
    summary["canonical3d_exact_reproj_mean_px_max"] = max(canon) if canon else None
    mismatch = [r["idx"] for r in rows if r.get("visible_corner_count_matches_label") is False]
    summary["visible_corner_count_mismatch_idx"] = mismatch

    for name, thr in THRESHOLD_CANDIDATES.items():
        col = f"pnp_eligible_candidate_{name}"
        passed = [r for r in rows if r.get(col)]
        failed = [r for r in rows if not r.get(col)]
        entry = {"threshold_px": thr, "n_pass": len(passed), "n_fail": len(failed)}
        for sigma in sigmas:
            key = f"mc{int(sigma)}px"
            for grp_name, grp in (("pass", passed), ("fail", failed)):
                pf = _vals(grp, f"{key}_pose_fail_rate")
                tr = _vals(grp, f"{key}_trans_cm_q90")
                ro = _vals(grp, f"{key}_rot_deg_q90")
                entry[f"{key}_{grp_name}_pose_fail_rate_mean"] = float(np.mean(pf)) if pf else None
                entry[f"{key}_{grp_name}_trans_q90_median"] = float(np.median(tr)) if tr else None
                entry[f"{key}_{grp_name}_rot_q90_median"] = float(np.median(ro)) if ro else None
        entry["n_pass_with_stress"] = sum(1 for r in passed if r.get("pnp_stress"))
        entry["stress_rate_in_pass"] = (entry["n_pass_with_stress"] / len(passed)) if passed else None
        entry["n_fail_without_stress"] = sum(1 for r in failed if not r.get("pnp_stress"))
        summary["candidates"][name] = entry

    summary["threshold_sweep"] = threshold_sweep(rows)
    summary["knee"] = knee_analysis(summary["threshold_sweep"])
    summary["stability_target_fail_rate"] = STABILITY_TARGET_FAIL_RATE
    return summary


def _fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    fv = _f(v)
    if fv is None:
        return str(v)
    return f"{fv:.{digits}f}"


def size_strata(rows: list[dict[str, Any]], key: str, edges: list[float]) -> list[dict[str, Any]]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        grp = [r for r in rows
               if _f(r.get(key)) is not None and lo <= _f(r.get(key)) < hi]
        entry = {"lo": lo, "hi": hi, "n": len(grp)}
        entry["n_pnp_success"] = sum(1 for r in grp if r.get("pnp_exact_success"))
        for sigma in (1.0, 2.0, 3.0):
            k = f"mc{int(sigma)}px"
            pf = _vals(grp, f"{k}_pose_fail_rate")
            tr = _vals(grp, f"{k}_trans_cm_q90")
            ro = _vals(grp, f"{k}_rot_deg_q90")
            entry[f"{k}_pose_fail_rate_mean"] = float(np.mean(pf)) if pf else None
            entry[f"{k}_trans_q90_median"] = float(np.median(tr)) if tr else None
            entry[f"{k}_rot_q90_median"] = float(np.median(ro)) if ro else None
        out.append(entry)
    return out


def threshold_sweep(rows: list[dict[str, Any]], max_cells: int = 8) -> list[dict[str, Any]]:
    """Accepted-set size and stability for every k-cell threshold, k = 1..max_cells.

    Used to test whether one of the three candidates sits on a data-identified breakpoint or
    whether the quality/yield trade-off is simply monotone (no knee -> no evidence for a
    particular threshold).
    """
    out = []
    total = len(rows)
    key = f"mc{int(STRESS_SIGMA_PX)}px_pose_fail_rate"
    for cells in range(1, max_cells + 1):
        thr = cells * BELIEF_CELL_PX
        acc = [r for r in rows
               if r.get("pnp_exact_success")
               and _f(r.get("bbox_vis_min_side_px")) is not None
               and _f(r["bbox_vis_min_side_px"]) >= thr]
        pf = _vals(acc, key)
        out.append({
            "cells": cells, "threshold_px": thr, "n_accept": len(acc),
            "accept_frac": (len(acc) / total) if total else None,
            "fail_rate_mean": float(np.mean(pf)) if pf else None,
            "n_stress_accepted": sum(1 for r in acc if r.get("pnp_stress")),
        })
    return out


def knee_analysis(sweep: list[dict[str, Any]]) -> dict[str, Any]:
    steps = []
    for a, b in zip(sweep[:-1], sweep[1:]):
        if a["fail_rate_mean"] is None or b["fail_rate_mean"] is None:
            continue
        steps.append({"from_cells": a["cells"], "to_cells": b["cells"],
                      "drop": a["fail_rate_mean"] - b["fail_rate_mean"]})
    if not steps:
        return {"has_knee": False, "reason": "no measurable steps", "steps": steps}
    drops = [s["drop"] for s in steps]
    med = float(np.median(drops))
    best = max(steps, key=lambda s: s["drop"])
    ratio = (best["drop"] / med) if med > 1e-9 else float("inf")
    return {
        "has_knee": bool(ratio >= KNEE_STEP_RATIO and best["drop"] > 0.0),
        "median_step": med, "max_step": best["drop"], "max_step_ratio": ratio,
        "max_step_at_cells": best["to_cells"], "steps": steps,
    }


def write_markdown(path: Path, root: Path, rows: list[dict[str, Any]], summary: dict[str, Any],
                   args, strata: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    a = lines.append
    a("# PnP eligibility / threshold study (v2 revision, Phase 4)")
    a("")
    a(f"- dataset: `{root}`")
    a(f"- frames evaluated: {summary['n_frames']} (labels present: {summary['n_label_present']}, "
      f"geometry usable: {summary['n_geometry_ok']})")
    a(f"- Monte-Carlo: sigma = {', '.join(str(s) for s in summary['sigmas'])} px, "
      f"{args.mc_trials} trials/frame/sigma, base seed {args.seed} (deterministic)")
    a(f"- solver: `cv2.solvePnPRansac` + `SOLVEPNP_EPNP`, reprojectionError="
      f"{PNP_RANSAC_REPROJ_PX}px, iterationsCount={PNP_RANSAC_ITERS} "
      f"(`scripts/self_training/pnp_solver.py:133-139`, identical to the evaluation path)")
    a(f"- pose correctness: {POSE_TRANS_TOL_CM}cm / {POSE_ROT_TOL_DEG}deg "
      f"(`scripts/self_training/metrics.py:143`)")
    a("- **no frame is deleted or filtered by this script** - it only measures and adds manifest fields.")
    a("")

    a("## 1. Threshold candidates: where 16 / 24 / 32 px come from")
    a("")
    a("`Deep_Object_Pose/common/models.py:26-40` - the VGG19 trunk keeps 3 `MaxPool2d(2)` and every")
    a("later conv has stride 1, so the belief map is 1/8 of the network input "
      "(`config/default.yaml:13-14`: 448 -> 56). [확인]")
    a("")
    a("`Deep_Object_Pose/common/utils.py:340,356-372,419` - the training loader takes a **pixel-identity**")
    a("`A.RandomCrop(400,400)` of the source PNG and feeds that crop to the network unscaled; only the")
    a("keypoints are rescaled into the belief-map grid. There is no image resize between the source")
    a("image and the network input, so **1 belief-map cell = 8 source-image pixels**. [확인]")
    a("")
    a("```")
    a("candidate   cells   px (source image)")
    a("─────────────────────────────────────")
    for name, thr in THRESHOLD_CANDIDATES.items():
        a(f"{name:<11} {int(thr / BELIEF_CELL_PX):<7} {thr:.0f}")
    a("```")
    a("")

    a("### Why min(bbox_w, bbox_h) and not the diagonal or the area")
    a("")
    a("A pallet is a flat slab: its short projected side (usually the 0.11-0.15 m height) collapses")
    a("first. If that side spans fewer than k belief-map cells, the top and the bottom corner rows")
    a("fall into the same cells and their Gaussian peaks merge - the network cannot express them as")
    a("separate maxima regardless of how long the pallet looks. The diagonal and the area are both")
    a("dominated by the LONG side, so they happily accept a line-like target whose short side is")
    a("sub-cell; that is exactly the degenerate case this study is meant to catch. The measurement is")
    a("taken over the **visible** keypoints (in-frame AND external occlusion < "
      f"{OCCLUSION_VISIBLE_MAX}), because")
    a("those are the only points the network can be supervised on. `mask_m0_min_side_px` and")
    a("`bbox_all_min_side_px` are reported next to it as cross-checks.")
    a("")

    a("## 2. Correspondence source (important deviation)")
    a("")
    a("The 3D<->2D correspondence is taken from the label's own `cuboid` (world) and")
    a("`projected_cuboid`, which `v2_realize.label()` writes from the SAME `perm_v4` permutation, and")
    a("re-expressed in a centroid-centred object frame. A FIXED canonical object frame")
    a("(`pnp_solver.make_pallet_keypoints_3d`) does **not** describe these labels: the")
    a("`camera_dynamic_0123_v4` convention re-assigns which physical corner is index 0 per frame.")
    canon_max = summary.get("canonical3d_exact_reproj_mean_px_max")
    a(f"Measured on this dataset: projecting the canonical point set through the labelled")
    a(f"`pose_transform` is off by hundreds of px; solving PnP with it reaches a mean reprojection")
    a(f"error of up to {_fmt(canon_max)} px (`canonical3d_exact_reproj_mean_px`). [확인]")
    a("")
    a(f"Self-check: max |K[R|t]cuboid - projected_cuboid| over all frames = "
      f"{_fmt(summary.get('label_reproj_consistency_px_max'), 6)} px, i.e. the world-frame")
    a("correspondence reproduces the label exactly.")
    a("")

    a("## 3. Frame-level results")
    a("")
    a("```")
    a("quantity                       value")
    a("────────────────────────────────────")
    a(f"frames                         {summary['n_frames']}")
    a(f"geometry usable                {summary['n_geometry_ok']}")
    a(f"exact-GT PnP success           {summary['n_pnp_exact_success']}")
    a(f"physical_valid                 {summary['n_physical_valid']}")
    a(f"gate_valid (G1..G5)            {summary['n_gate_valid']}")
    a(f"tiny_warning                   {summary['n_tiny_warning']}")
    a(f"pnp_stress                     {summary['n_pnp_stress']}")
    a("```")
    a("")

    a("### Monte-Carlo stability by projected size (visible-keypoint bbox min side)")
    a("")
    a("```")
    a("bbox_min_side_px    n    PnP ok   fail@1px  fail@2px  fail@3px  trans_q90@2px  rot_q90@2px")
    a("───────────────────────────────────────────────────────────────────────────────────────────")
    for s in strata:
        hi = "inf" if math.isinf(s["hi"]) else f"{s['hi']:.0f}"
        a(f"[{s['lo']:>5.0f},{hi:>6})  {s['n']:>4}   {s['n_pnp_success']:>4}    "
          f"{_fmt(s['mc1px_pose_fail_rate_mean']):>8}  {_fmt(s['mc2px_pose_fail_rate_mean']):>8}  "
          f"{_fmt(s['mc3px_pose_fail_rate_mean']):>8}  {_fmt(s['mc2px_trans_q90_median']):>13}  "
          f"{_fmt(s['mc2px_rot_q90_median']):>11}")
    a("```")
    a("")
    a("`fail@Npx` = mean fraction of the 200 perturbed solves that miss 5cm-5deg. "
      "`trans_q90`/`rot_q90` are medians over frames of the per-frame q90.")
    a("")

    a("## 4. Threshold candidate comparison")
    a("")
    a("```")
    a("candidate  thr_px  n_pass  n_fail  fail@2px(pass)  fail@2px(fail)  stress_in_pass  clean_in_fail")
    a("──────────────────────────────────────────────────────────────────────────────────────────────")
    for name, entry in summary["candidates"].items():
        a(f"{name:<10} {entry['threshold_px']:>6.0f}  {entry['n_pass']:>6}  {entry['n_fail']:>6}  "
          f"{_fmt(entry['mc2px_pass_pose_fail_rate_mean']):>14}  "
          f"{_fmt(entry['mc2px_fail_pose_fail_rate_mean']):>14}  "
          f"{entry['n_pass_with_stress']:>14}  {entry['n_fail_without_stress']:>13}")
    a("```")
    a("")
    a("- `fail@2px(pass)` = mean 5cm-5deg failure rate among the frames the candidate ACCEPTS "
      "(lower is better).")
    a("- `stress_in_pass` = accepted frames that are nevertheless flagged `pnp_stress` "
      "(the candidate lets an unstable frame through).")
    a("- `clean_in_fail` = rejected frames that are NOT `pnp_stress` (the candidate throws away a "
      "usable frame).")
    a("")
    a("### Is one of them a data-identified breakpoint? (1..8 cell sweep)")
    a("")
    sweep = summary["threshold_sweep"]
    knee = summary["knee"]
    a("```")
    a("cells  thr_px  n_accept  accept_frac  fail@2px(accepted)  step_drop  stress_accepted")
    a("──────────────────────────────────────────────────────────────────────────────────────")
    prev = None
    for s in sweep:
        drop = "-" if (prev is None or s["fail_rate_mean"] is None) else _fmt(prev - s["fail_rate_mean"])
        mark = " *" if s["cells"] * BELIEF_CELL_PX in THRESHOLD_CANDIDATES.values() else "  "
        a(f"{s['cells']:>5}{mark}{s['threshold_px']:>6.0f}  {s['n_accept']:>8}  "
          f"{_fmt(s['accept_frac']):>11}  {_fmt(s['fail_rate_mean']):>18}  {drop:>9}  "
          f"{s['n_stress_accepted']:>15}")
        prev = s["fail_rate_mean"]
    a("```")
    a("")
    a("`*` marks the three candidates. A threshold is only *identified by the data* if the")
    a("accepted-set failure rate DROPS at it; a smooth decay means the choice is a pure")
    a("yield-vs-quality trade-off with no breakpoint.")
    a("")
    a(f"median step = {_fmt(knee.get('median_step'))}, largest step = {_fmt(knee.get('max_step'))} "
      f"(at {knee.get('max_step_at_cells')} cells, {_fmt(knee.get('max_step_ratio'), 2)}x the median) "
      f"-> knee detected: **{knee.get('has_knee')}**")
    a("")

    a("## 5. Manifest fields added")
    a("")
    a("```")
    a("field                          definition")
    a("──────────────────────────────────────────────────────────────────────────────────────")
    a("physical_valid                 no KNOWN physical violation: rendered, realize_ok,")
    a("                               exact_collision_count==0, camera_clearance_pass,")
    a("                               support_pass, mask_invariants_pass, ground_continuity_pass,")
    a("                               not corrupt_rgb/mask, M0 area>0, camera distance <= limit")
    a("                               (Phase 1; recomputed from the label when the record predates")
    a("                               Phase 1). Missing inputs are listed in physical_unknown")
    a("                               instead of silently passing.")
    a("gate_valid                     G1..G5 all_pass (record first, label safety_gates fallback).")
    a("pnp_eligible_candidate_Ncell   pnp_exact_success AND bbox_vis_min_side_px >= N*8 px.")
    a(f"tiny_warning                   bbox_vis_min_side_px < {THRESHOLD_CANDIDATES['2cell']:.0f} px "
      f"OR mask_m0_area < {TINY_MASK_AREA_PX} px^2.")
    a(f"pnp_stress                     exact PnP failed OR sigma={STRESS_SIGMA_PX:.0f}px 5cm-5deg "
      f"failure rate > {STRESS_POSE_FAIL_RATE}")
    a(f"                               OR divergence rate > {STRESS_DIVERGED_RATE}.")
    a("```")
    a("")

    a("## 6. Decision")
    a("")
    a(decision_text(summary, strata, rows))
    a("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def decision_text(summary: dict[str, Any], strata: list[dict[str, Any]],
                  rows: list[dict[str, Any]]) -> str:
    """State whether the evidence supports fixing ONE hard threshold. Never guesses."""
    reasons: list[str] = []
    entries = summary["candidates"]
    n_eval = summary["n_geometry_ok"]
    knee = summary["knee"]

    fail_rates = {name: e.get("mc2px_pass_pose_fail_rate_mean") for name, e in entries.items()}
    known = {k: v for k, v in fail_rates.items() if v is not None}

    if n_eval < 30:
        reasons.append(f"only {n_eval} frames carry usable geometry (n < 30, statistically thin).")
    if len(known) < len(entries):
        reasons.append("at least one candidate has no measurable accepted-frame statistics.")
    empty = [n for n, e in entries.items() if e["n_pass"] == 0 or e["n_fail"] == 0]
    if empty:
        reasons.append(
            "candidate(s) " + ", ".join(empty) + " put every frame on one side, so this dataset "
            "cannot discriminate them.")
    if not knee.get("has_knee"):
        reasons.append(
            f"no breakpoint: over the 1..8 cell sweep the accepted-set 5cm-5deg failure rate decays "
            f"smoothly (largest step {_fmt(knee.get('max_step'))} = "
            f"{_fmt(knee.get('max_step_ratio'), 2)}x the median step {_fmt(knee.get('median_step'))}, "
            f"below the {KNEE_STEP_RATIO}x knee criterion). Raising the threshold monotonically "
            "improves stability and monotonically lowers yield, so the data identifies a trade-off "
            "curve, not a particular threshold.")
    best_name = min(known, key=known.get) if known else None
    if best_name is not None and known[best_name] > STABILITY_TARGET_FAIL_RATE:
        reasons.append(
            f"no candidate delivers a stable accepted set in absolute terms: the best of the three "
            f"({best_name}) still leaves {known[best_name]:.3f} mean 5cm-5deg failure rate at "
            f"sigma={STRESS_SIGMA_PX:.0f}px, far above the {STABILITY_TARGET_FAIL_RATE:.2f} target "
            "[미검증 시작값]. Passing a size threshold therefore does NOT imply the frame is "
            "PnP-reliable, so a size threshold alone cannot be the training-ready criterion.")

    if reasons:
        return ("**확정 불가, 근거 부족.** No hard threshold is fixed by this study. Reasons:\n\n"
                + "\n".join(f"- {r}" for r in reasons)
                + "\n\nThe three candidates stay side by side in the manifest "
                  "(`pnp_eligible_candidate_2cell/3cell/4cell`) and `pnp_stress` is reported "
                  "independently; Phase 7 must keep treating them as candidates, not as a "
                  "delivered filter.")
    return ("The sweep shows a breakpoint at "
            f"{knee.get('max_step_at_cells')} cells and the accepted set meets the absolute "
            "stability target, but fixing the final hard threshold is a downstream decision "
            "(Phase 7) and is deliberately left open here.")


def write_manifest(csv_path: Path, json_path: Path, rows: list[dict[str, Any]],
                   summary: dict[str, Any], root: Path, args) -> None:
    AUDIT.write_csv(csv_path, _csv_ready(rows, MANIFEST_COLUMNS), MANIFEST_COLUMNS)
    payload = {
        "dataset": str(root),
        "generated_by": "scripts/data_prep/blender/audit_pnp_eligibility.py",
        "frames_deleted": 0,
        "note": "manifest only ADDS fields; no frame is filtered or removed by this phase",
        "belief_cell_px": BELIEF_CELL_PX,
        "thresholds_px": dict(THRESHOLD_CANDIDATES),
        "pnp": {"solver": "cv2.solvePnPRansac", "flag": "SOLVEPNP_EPNP",
                "reprojectionError": PNP_RANSAC_REPROJ_PX, "iterationsCount": PNP_RANSAC_ITERS},
        "monte_carlo": {"sigmas_px": list(args.sigmas), "trials": args.mc_trials,
                        "base_seed": args.seed},
        "pose_tolerance": {"trans_cm": POSE_TRANS_TOL_CM, "rot_deg": POSE_ROT_TOL_DEG},
        "summary": summary,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------

def kernel_smooth(x: np.ndarray, y: np.ndarray, grid: np.ndarray,
                  bandwidth: float) -> tuple[np.ndarray, np.ndarray]:
    """Nadaraya-Watson smoother (Gaussian kernel). Returns (curve, effective n)."""
    curve = np.full(grid.shape, np.nan)
    n_eff = np.zeros(grid.shape)
    if len(x) == 0:
        return curve, n_eff
    for i, g in enumerate(grid):
        w = np.exp(-0.5 * ((x - g) / bandwidth) ** 2)
        s = w.sum()
        n_eff[i] = s
        if s > 1e-9:
            curve[i] = float((w * y).sum() / s)
    return curve, n_eff


def write_pdf(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any], args) -> bool:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    size_key = "bbox_vis_min_side_px"
    usable = [r for r in rows if _f(r.get(size_key)) is not None and _f(r.get(size_key)) > 0]
    if not usable:
        return False

    x_raw = np.array([_f(r[size_key]) for r in usable])
    logx = np.log10(x_raw)
    grid = np.linspace(logx.min(), logx.max(), 200)
    bandwidth = max(0.06, (logx.max() - logx.min()) / 25.0)
    colors = {1: "#1b6ca8", 2: "#c0392b", 3: "#2e7d32"}

    def _panel(ax, ykey, ylabel, logy=False):
        for sigma in args.sigmas:
            key = f"mc{int(sigma)}px_{ykey}"
            pairs = [(lx, _f(r.get(key))) for lx, r in zip(logx, usable) if _f(r.get(key)) is not None]
            if not pairs:
                continue
            xs = np.array([p[0] for p in pairs])
            ys = np.array([p[1] for p in pairs])
            col = colors.get(int(sigma), "#555555")
            ax.scatter(10 ** xs, ys, s=6, alpha=0.25, color=col, linewidths=0)
            curve, n_eff = kernel_smooth(xs, ys, grid, bandwidth)
            solid = n_eff >= 5.0
            ax.plot(10 ** grid, np.where(solid, curve, np.nan), color=col, lw=2.0,
                    label=f"sigma={sigma:.0f}px")
            ax.plot(10 ** grid, np.where(solid, np.nan, curve), color=col, lw=1.0, alpha=0.35)
        for name, thr in THRESHOLD_CANDIDATES.items():
            ax.axvline(thr, color="#666666", ls="--", lw=1.0)
            ax.annotate(name, xy=(thr, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(2, -10), textcoords="offset points", fontsize=7, color="#666666")
        ax.set_xscale("log")
        if logy:
            ax.set_yscale("log")
        ax.set_xlabel("visible-keypoint bbox min side [px]  (log)")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25, which="both")
        ax.legend(fontsize=7, loc="best")

    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        fig, axes = plt.subplots(2, 1, figsize=(8.5, 9.5))
        fig.suptitle("PnP stability vs projected size - keypoint perturbation Monte-Carlo\n"
                     f"{summary['n_frames']} frames, {args.mc_trials} trials/frame/sigma",
                     fontsize=11)
        _panel(axes[0], "pose_fail_rate", "P(miss 5cm-5deg)")
        axes[0].set_ylim(-0.03, 1.03)
        _panel(axes[1], "diverged_rate", "P(diverged: >1m or >45deg)")
        axes[1].set_ylim(-0.03, 1.03)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        pdf.savefig(fig)
        plt.close(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8.5, 9.5))
        fig.suptitle("Pose error quantiles vs projected size", fontsize=11)
        _panel(axes[0], "trans_cm_q90", "translation error q90 [cm]", logy=True)
        axes[0].axhline(POSE_TRANS_TOL_CM, color="k", lw=0.8, ls=":")
        _panel(axes[1], "rot_deg_q90", "rotation error q90 [deg]", logy=True)
        axes[1].axhline(POSE_ROT_TOL_DEG, color="k", lw=0.8, ls=":")
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        pdf.savefig(fig)
        plt.close(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8.5, 9.5))
        fig.suptitle("Supporting geometry", fontsize=11)
        ax = axes[0]
        m0 = np.array([_f(r.get("mask_m0_area")) or 0.0 for r in usable])
        ok = np.array([bool(r.get("pnp_exact_success")) for r in usable])
        ax.scatter(x_raw[ok], np.maximum(m0[ok], 0.5), s=8, alpha=0.5, color="#1b6ca8",
                   label="exact PnP ok")
        ax.scatter(x_raw[~ok], np.maximum(m0[~ok], 0.5), s=12, alpha=0.8, color="#c0392b",
                   marker="x", label="exact PnP fail")
        for thr in THRESHOLD_CANDIDATES.values():
            ax.axvline(thr, color="#666666", ls="--", lw=1.0)
        ax.axhline(TINY_MASK_AREA_PX, color="#666666", ls=":", lw=1.0)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("visible-keypoint bbox min side [px]  (log)")
        ax.set_ylabel("M0 mask area [px^2]  (log)")
        ax.grid(alpha=0.25, which="both")
        ax.legend(fontsize=7)

        ax = axes[1]
        mp = np.array([_f(r.get("visible_kp_min_pair_dist_px")) or np.nan for r in usable])
        ax.scatter(x_raw, mp, s=8, alpha=0.5, color="#2e7d32")
        for thr in THRESHOLD_CANDIDATES.values():
            ax.axvline(thr, color="#666666", ls="--", lw=1.0)
            ax.axhline(thr, color="#cccccc", ls="--", lw=0.8)
        ax.axhline(BELIEF_CELL_PX, color="k", ls=":", lw=0.8)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("visible-keypoint bbox min side [px]  (log)")
        ax.set_ylabel("min pairwise keypoint distance [px]  (log)")
        ax.grid(alpha=0.25, which="both")
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        pdf.savefig(fig)
        plt.close(fig)
    return True


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PnP eligibility / threshold study for v2 frames.")
    p.add_argument("--dir", default=DEFAULT_DIR, help="Dataset root (labels/, mask/, records.jsonl).")
    p.add_argument("--out", default=DEFAULT_OUT, help="Output directory for the study artifacts.")
    p.add_argument("--max-frames", type=int, default=None, help="Evaluate at most N frames.")
    p.add_argument("--mc-trials", type=int, default=MC_TRIALS, help="Monte-Carlo trials per sigma.")
    p.add_argument("--sigmas", default=",".join(str(s) for s in MC_SIGMAS_PX),
                   help="Comma-separated Gaussian keypoint sigmas in px.")
    p.add_argument("--seed", type=int, default=MC_SEED, help="Base seed (deterministic).")
    p.add_argument("--no-pdf", action="store_true", help="Skip the PDF figure.")
    p.add_argument("--self-test", action="store_true", help="Run the built-in synthetic self test.")
    args = p.parse_args(argv)
    args.sigmas = tuple(float(s) for s in str(args.sigmas).split(",") if str(s).strip())
    return args


def run(args) -> dict[str, Any]:
    root = AUDIT.as_path(args.dir)
    out_dir = AUDIT.as_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    records, _rec_info = AUDIT.load_records(root)
    indices = AUDIT.discover_indices(root, records, ["m0"])
    indices = [i for i in indices if (root / "labels" / f"f{i:04d}_label.json").exists()]
    if args.max_frames is not None:
        indices = indices[: args.max_frames]

    rows = []
    for n, idx in enumerate(indices, 1):
        rows.append(evaluate_frame(root, idx, records.get(idx), args))
        if n % 50 == 0 or n == len(indices):
            print(f"  [{n}/{len(indices)}] frames evaluated", flush=True)

    summary = summarize(rows, args.sigmas)
    edges = [0.0, 8.0, 16.0, 24.0, 32.0, 64.0, 128.0, 256.0, float("inf")]
    strata = size_strata(rows, "bbox_vis_min_side_px", edges)

    columns = study_columns(args.sigmas)
    csv_path = out_dir / "pnp_threshold_study.csv"
    AUDIT.write_csv(csv_path, _csv_ready(rows, columns), columns)
    write_markdown(out_dir / "pnp_threshold_study.md", root, rows, summary, args, strata)
    write_manifest(out_dir / "pnp_eligibility_manifest.csv",
                   out_dir / "pnp_eligibility_manifest.json", rows, summary, root, args)
    pdf_ok = False
    if not args.no_pdf:
        pdf_ok = write_pdf(out_dir / "pnp_stability_continuous.pdf", rows, summary, args)

    summary["outputs"] = {
        "csv": str(csv_path),
        "md": str(out_dir / "pnp_threshold_study.md"),
        "pdf": str(out_dir / "pnp_stability_continuous.pdf") if pdf_ok else None,
        "manifest_csv": str(out_dir / "pnp_eligibility_manifest.csv"),
        "manifest_json": str(out_dir / "pnp_eligibility_manifest.json"),
    }
    summary["rows"] = rows
    return summary


def self_test() -> int:
    """Synthetic end-to-end check (no dataset needed)."""
    import tempfile
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "ds"
        (root / "labels").mkdir(parents=True)
        (root / "mask").mkdir(parents=True)
        recs = []
        for idx, dist in enumerate((2.0, 6.0, 30.0)):
            lab = synthetic_label(dist_m=dist)
            (root / "labels" / f"f{idx:04d}_label.json").write_text(json.dumps(lab), encoding="utf-8")
            arr = np.zeros((480, 640), dtype=np.uint8)
            arr[100:140, 100:200] = 255
            Image.fromarray(arr).save(root / "mask" / f"f{idx:04d}_m0.png")
            recs.append({"idx": idx, "rendered": True, "realize_ok": True,
                         "exact_collision_count": 0, "camera_clearance_pass": True,
                         "support_pass": True, "mask_invariants_pass": True,
                         "ground_continuity_pass": True, "corrupt_rgb": False,
                         "corrupt_mask": False, "camera_distance_limit_m": 10.0,
                         "camera_distance_actual_m": dist, "all_pass": True,
                         "G1_pass": True, "G2_pass": True, "G3_pass": True,
                         "G4_pass": True, "G5_pass": True})
        with (root / "records.jsonl").open("w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        out = Path(tmp) / "out"
        args = parse_args(["--dir", str(root), "--out", str(out), "--mc-trials", "20"])
        summary = run(args)
        ok = True
        for name in ("pnp_threshold_study.csv", "pnp_threshold_study.md",
                     "pnp_eligibility_manifest.csv", "pnp_eligibility_manifest.json",
                     "pnp_stability_continuous.pdf"):
            exists = (out / name).exists()
            print(f"  {name}: {'OK' if exists else 'MISSING'}")
            ok = ok and exists
        cons = summary.get("label_reproj_consistency_px_max")
        print(f"  label reproj consistency max: {cons}")
        ok = ok and cons is not None and cons < 1e-6
        print(f"  exact PnP success: {summary['n_pnp_exact_success']}/{summary['n_frames']}")
        ok = ok and summary["n_pnp_exact_success"] == summary["n_frames"]
        print("SELF-TEST", "PASS" if ok else "FAIL")
        return 0 if ok else 1


def synthetic_label(dist_m: float = 3.0, width: float = 1.1, depth: float = 1.1,
                    height: float = 0.15, fx: float = 605.9065, img_w: int = 640,
                    img_h: int = 480, yaw_deg: float = 20.0,
                    elev_deg: float = 25.0) -> dict[str, Any]:
    """Build a v2-shaped label from scratch (used by the self test and the unit tests)."""
    hw, hd, hh = width / 2.0, depth / 2.0, height / 2.0
    corners = np.array([
        [+hw, +hd, +hh], [-hw, +hd, +hh], [-hw, +hd, -hh], [+hw, +hd, -hh],
        [+hw, -hd, +hh], [-hw, -hd, +hh], [-hw, -hd, -hh], [+hw, -hd, -hh],
    ], dtype=np.float64)
    centroid = corners.mean(axis=0)
    az = math.radians(yaw_deg)
    el = math.radians(elev_deg)
    cam_pos = centroid + dist_m * np.array([
        math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    r_w2c, t_w2c = build_view_matrix(cam_pos, centroid, up=(0, 0, 1))
    k = np.array([[fx, 0, img_w / 2.0], [0, fx, img_h / 2.0], [0, 0, 1.0]])
    cam_pts = (r_w2c @ corners.T).T + t_w2c
    proj = (k @ cam_pts.T).T
    uv = proj[:, :2] / proj[:, 2:3]
    cent_cam = r_w2c @ centroid + t_w2c
    cent_uv = (k @ cent_cam)[:2] / cent_cam[2]
    return {
        "camera_data": {
            "width": img_w, "height": img_h,
            "intrinsics": {"fx": fx, "fy": fx, "cx": img_w / 2.0, "cy": img_h / 2.0},
            "location_worldframe": [float(v) for v in cam_pos],
            "look_worldframe": [float(v) for v in centroid],
        },
        "objects": [{
            "class": "pallet", "name": "Pallet_0",
            "keypoint_convention": "camera_dynamic_0123_v4",
            "location": [float(v) for v in cent_cam],
            "cuboid": [[float(c) for c in row] for row in corners],
            "projected_cuboid": [[float(p[0]), float(p[1])] for p in uv],
            "projected_cuboid_centroid": [float(cent_uv[0]), float(cent_uv[1])],
            "dimensions_m": {"width": width, "height": height, "depth": depth},
            "v2_labels": {"occlusion_fraction": [0.0] * 9, "V_vis_actual": 8,
                          "elevation_deg_actual": elev_deg},
            "safety_gates": {"G1_Vvis>=4": True, "G2_extocc_1to4": True,
                             "G3_visible>=0.5unocc": True, "G4_center_inframe": True,
                             "G5_luma_floor": True, "all_pass": True},
        }],
    }


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    summary = run(args)
    keys = ("n_frames", "n_geometry_ok", "n_pnp_exact_success", "n_physical_valid",
            "n_gate_valid", "n_tiny_warning", "n_pnp_stress",
            "label_reproj_consistency_px_max", "canonical3d_exact_reproj_mean_px_max")
    for key in keys:
        print(f"{key:<38} {summary.get(key)}")
    for name, entry in summary["candidates"].items():
        print(f"candidate {name:<8} thr={entry['threshold_px']:.0f}px  n_pass={entry['n_pass']}  "
              f"n_fail={entry['n_fail']}  fail@2px(pass)={_fmt(entry['mc2px_pass_pose_fail_rate_mean'])}")
    print(f"knee detected                          {summary['knee'].get('has_knee')}")
    for name, path in summary["outputs"].items():
        print(f"out.{name:<34} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
