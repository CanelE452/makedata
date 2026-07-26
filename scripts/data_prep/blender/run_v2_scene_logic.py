"""Constrained-scene diagnostic runner for the Blender v2 pipeline.

This is intentionally separate from the legacy 2k driver.  It accepts only the
task-authorized 20-frame smoke or 500-frame diagnostic pilot, keeps the existing
camera/geometry prescriptions, and opts into ``placement_mode="constrained"``.

Run one 100-frame pilot chunk with a fresh Blender process:

  blender -b data/pallet/blender_scene/synth_data_scene.blend \
    --python scripts/data_prep/blender/run_v2_scene_logic.py -- \
    --out data/pallet/_v2_scene_logic_500_seed7500 \
    --seed 7500 --n 500 --start 0 --count 100
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter


_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)


DIAGNOSTIC_MODES = (
    "clean-static",
    "cargo-only",
    "context-rich",
    "controlled-occlusion",
)


def diagnostic_mode_for_index(idx, n):
    """Return the task-fixed diagnostic stratum for a global frame index."""
    idx = int(idx)
    n = int(n)
    if n == 20:
        cuts = (5, 10, 15, 20)
    elif n == 500:
        cuts = (100, 200, 350, 500)
    else:
        raise ValueError("diagnostic n must be 20 or 500")
    if idx < 0 or idx >= n:
        raise IndexError(idx)
    for mode, stop in zip(DIAGNOSTIC_MODES, cuts):
        if idx < stop:
            return mode
    raise IndexError(idx)


def _diagnostic_controlled_priority(plan, idx, seed):
    """Rank controlled-occlusion candidates without mutating plan order."""
    spec = plan.spec
    elevation_deg = None
    v_probe = None
    try:
        f_target = float(spec.f_target)
        elevation_deg = float(spec.elevation_deg)
    except (AttributeError, TypeError, ValueError):
        category = 3
    else:
        positive_target = math.isfinite(f_target) and f_target > 1e-6
        low_enough = math.isfinite(elevation_deg) and elevation_deg < 60.0
        try:
            v_probe = int(plan.v_probe)
        except (AttributeError, TypeError, ValueError):
            robust_corner_capacity = True
        else:
            robust_corner_capacity = v_probe >= 6
        if positive_target and low_enough and robust_corner_capacity:
            category = 0
        elif positive_target and low_enough:
            category = 1
        elif positive_target:
            category = 2
        elif low_enough:
            category = 3
        else:
            category = 4

    try:
        projected_size = float(spec.proj_size_ratio)
    except (AttributeError, TypeError, ValueError):
        projected_size_penalty = 0
    else:
        projected_size_penalty = int(
            not math.isfinite(projected_size)
            or projected_size < 0.05
            or projected_size > 0.75
        )
    solved_occluder_penalty = int(
        getattr(plan, "occluder", None) is None
    )
    corner_capacity_rank = (
        0 if v_probe is None else -int(v_probe)
    )
    elevation_extreme_rank = (
        0.0
        if elevation_deg is None or not math.isfinite(elevation_deg)
        else abs(float(elevation_deg) - 30.0)
    )

    frame_index = getattr(spec, "frame_index", idx)
    payload = (
        f"diagnostic-mode:{int(seed)}:{int(idx)}:{int(frame_index)}"
    ).encode("ascii")
    rank = int.from_bytes(
        hashlib.blake2b(payload, digest_size=8).digest(),
        "little",
    )
    return (
        category,
        projected_size_penalty,
        corner_capacity_rank,
        elevation_extreme_rank,
        solved_occluder_penalty,
        rank,
        int(idx),
    )


def allocate_diagnostic_modes_for_plans(plans, n, seed):
    """Assign fixed-count strata while preferring feasible controlled plans.

    The accepted plan list is only inspected, never reordered or modified.
    Existing index-only assignments are retained except for the minimum swaps
    required to move the controlled stratum onto better candidate plans.
    """
    n = int(n)
    if len(plans) != n:
        raise ValueError(
            f"diagnostic plan count must equal n: len(plans)={len(plans)} n={n}"
        )

    base_modes = [diagnostic_mode_for_index(idx, n) for idx in range(n)]
    controlled_mode = "controlled-occlusion"
    controlled_count = base_modes.count(controlled_mode)
    ranked_indices = sorted(
        range(n),
        key=lambda idx: _diagnostic_controlled_priority(
            plans[idx],
            idx,
            seed,
        ),
    )
    selected = set(ranked_indices[:controlled_count])
    original = {
        idx for idx, mode in enumerate(base_modes)
        if mode == controlled_mode
    }

    incoming = sorted(selected - original)
    outgoing = sorted(original - selected)
    modes = list(base_modes)
    for old_controlled_idx, new_controlled_idx in zip(outgoing, incoming):
        modes[old_controlled_idx] = base_modes[new_controlled_idx]
    for idx in selected:
        modes[idx] = controlled_mode
    return modes


def chunk_indices(n, start, count):
    n = max(0, int(n))
    start = max(0, int(start))
    count = max(0, int(count))
    return list(range(start, min(n, start + count)))


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="data/pallet/_v2_scene_logic_500_seed7500",
    )
    parser.add_argument("--seed", type=int, default=7500)
    parser.add_argument("--n", type=int, choices=(20, 500), default=500)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="number of global frame indices handled by this Blender process",
    )
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument(
        "--rerun-failures",
        action="store_true",
        help="retry indices whose latest record did not render successfully",
    )
    return parser.parse_args(argv)


def _abspath(path):
    if os.path.isabs(path):
        return os.path.abspath(path)
    project_root = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
    return os.path.abspath(os.path.join(project_root, path))


def _json_default(value):
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    return None


def _write_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, default=_json_default)
    os.replace(tmp, path)


def _load_latest_records(jsonl_path):
    latest = {}
    if not os.path.isfile(jsonl_path):
        return latest
    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                latest[int(record["idx"])] = record
            except (ValueError, KeyError, TypeError):
                continue
    return latest


def _append_record(jsonl_path, record):
    with open(jsonl_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=_json_default) + "\n")
        handle.flush()


def _write_records_snapshot(path, latest):
    ordered = [latest[key] for key in sorted(latest)]
    _write_json(path, ordered)
    return ordered


def _frame_seed(master_seed, idx, attempt_frame_index):
    payload = f"{int(master_seed)}:{int(idx)}:{int(attempt_frame_index)}".encode("ascii")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "little")


def _strict_image_check(path):
    from PIL import Image

    if not os.path.isfile(path):
        return False, "missing"
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _magenta_fraction(path):
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (red > 140) & (blue > 140) & (green < 90)
    return float(mask.mean())


def _projected_size_actual(meas, width):
    points = meas.get("uv8_v4")
    if points is None or not width:
        return None
    xs = [float(point[0]) for point in points if math.isfinite(float(point[0]))]
    return (max(xs) - min(xs)) / float(width) if xs else None


def _gate_reason(gates):
    failed = [
        key.split("_", 1)[0]
        for key, passed in gates.items()
        if key != "all_pass" and not passed
    ]
    return "accepted" if not failed else "|".join(failed)


def _record_rendered(idx, frame_seed, mode, plan, rs, meas, gates, runtime_s,
                     noise_scale, rgb_path, label_path):
    placement = rs.get("constrained_metrics") or {}
    mask_paths = meas.get("mask_paths") or {}
    rgb_ok, rgb_error = _strict_image_check(rgb_path)
    corrupt_masks = {}
    for stage, path in mask_paths.items():
        ok, error = _strict_image_check(path)
        if not ok:
            corrupt_masks[stage] = error
    magenta = _magenta_fraction(rgb_path) if rgb_ok else None
    spec = plan.spec

    return {
        "idx": int(idx),
        "seed": int(frame_seed),
        "attempt_frame_index": int(spec.frame_index),
        "diagnostic_mode": mode,
        "placement_mode": "constrained",
        "rendered": bool(rgb_ok),
        "realize_ok": True,
        "pallet_type": rs.get("pallet_name"),
        "scene_preset": spec.scene_preset,
        "background_asset": rs.get("background"),
        "floor_mode": rs.get("floor_mode"),
        "elev_target": float(spec.elevation_deg),
        "elev_actual": (
            float(rs["elevation_deg_actual"])
            if rs.get("elevation_deg_actual") is not None
            else None
        ),
        "azimuth_bin": int(spec.azimuth_bin),
        "v_target": int(spec.v_target),
        "V_actual": int(meas["V_inframe"]),
        "V_vis": int(meas["V_vis"]),
        "projected_size_target": float(spec.proj_size_ratio),
        "projected_size_actual": _projected_size_actual(meas, rs.get("W")),
        "anchor_translation": placement.get("anchor_translation"),
        "procedural_support_shift": placement.get(
            "procedural_support_shift"
        ),
        "anchor_attempts": placement.get("anchor_attempts"),
        "anchor_reject_reason": placement.get("anchor_reject_reason"),
        "anchor_reject_counts_by_reason": placement.get(
            "anchor_reject_counts_by_reason"
        ),
        "support_surface_name": placement.get("support_surface_name"),
        "n_context_requested": placement.get("n_context_requested", 0),
        "n_context_placed": placement.get("n_context_placed", 0),
        "n_context_visible": placement.get("n_context_visible", 0),
        "context_visible_pixel_ratio": placement.get(
            "context_visible_pixel_ratio"
        ),
        "context_screen_area_ratio": placement.get("context_screen_area_ratio"),
        "context_placement_attempts": placement.get(
            "context_placement_attempts", 0
        ),
        "context_reject_counts_by_reason": placement.get(
            "context_reject_counts_by_reason"
        ),
        "n_cargo_requested": placement.get("n_cargo_requested", 0),
        "n_cargo_placed": placement.get("n_cargo_placed", rs.get("n_cargo", 0)),
        "cargo_on": bool(placement.get("n_cargo_requested", 0)),
        "cargo_placement_attempts": placement.get("cargo_placement_attempts", 0),
        "cargo_support_pass": placement.get("cargo_support_pass"),
        "context_support_pass": placement.get("context_support_pass"),
        "explicit_support_pass": placement.get("explicit_support_pass"),
        "pallet_support_pass": placement.get("pallet_support_pass"),
        "cargo_collision_pass": placement.get("cargo_collision_pass"),
        "front_visibility_after_cargo": placement.get(
            "front_visibility_after_cargo"
        ),
        "left_opening_visibility_after_cargo": placement.get(
            "left_opening_visibility_after_cargo"
        ),
        "right_opening_visibility_after_cargo": placement.get(
            "right_opening_visibility_after_cargo"
        ),
        "explicit_occluder_placed": bool(rs.get("occluder") is not None),
        "exact_collision_count": placement.get("exact_collision_count", 0),
        "tested_collision_pairs": placement.get("tested_collision_pairs"),
        "broad_phase_hits": placement.get("broad_phase_hits"),
        "exact_collision_hits": placement.get("exact_collision_hits"),
        "collision_reject_reason": placement.get("collision_reject_reason"),
        "pallet_obstacle_collision_count": placement.get(
            "pallet_obstacle_collision_count", 0
        ),
        "cargo_collision_count": placement.get("cargo_collision_count", 0),
        "context_context_collision_count": placement.get(
            "context_context_collision_count", 0
        ),
        "min_camera_clearance": placement.get("min_camera_clearance"),
        "camera_clearance_pass": placement.get("camera_clearance_pass"),
        "support_pass": placement.get("support_pass"),
        "static_collision_pass": placement.get("static_collision_pass"),
        "static_los_pass": placement.get("static_los_pass"),
        "f_target": float(spec.f_target),
        "f_static": meas.get("f_static"),
        "f_cargo": meas.get("f_cargo"),
        "f_context": meas.get("f_context"),
        "f_explicit": meas.get("f_explicit"),
        "f_total": meas.get("f_total"),
        "mask_area_target_only": meas.get("mask_area_target_only"),
        "mask_area_after_static": meas.get("mask_area_after_static"),
        "mask_area_after_cargo": meas.get("mask_area_after_cargo"),
        "mask_area_after_context": meas.get("mask_area_after_context"),
        "mask_area_visible": meas.get("mask_area_visible"),
        "occlusion_decomposition_order": meas.get(
            "occlusion_decomposition_order"
        ),
        "explicit_abs_error": meas.get("explicit_abs_error"),
        "f_explicit_target": meas.get("f_explicit_target"),
        "f_explicit_actual": meas.get("f_explicit_actual"),
        "explicit_feedback_depth_step_m": placement.get(
            "explicit_feedback_depth_step_m"
        ),
        "occluder_feedback_iterations": placement.get(
            "occluder_feedback_iterations", 0
        ),
        "occluder_side_target": placement.get("occluder_side_target"),
        "occluder_side_actual": placement.get("occluder_side_actual"),
        "occluder_side_match": placement.get("occluder_side_match"),
        "explicit_occluder_visible_pixels": placement.get(
            "explicit_occluder_visible_pixels", 0
        ),
        "explicit_collision_pass": placement.get("explicit_collision_pass"),
        "explicit_solver_fail_reason": placement.get(
            "explicit_solver_fail_reason"
        ),
        "explicit_reject_counts_by_reason": placement.get(
            "explicit_reject_counts_by_reason", {}
        ),
        "explicit_candidate_log": placement.get("explicit_candidate_log", []),
        "explicit_target_mask_stats": placement.get(
            "explicit_target_mask_stats"
        ),
        "explicit_initial_proposal": placement.get("explicit_initial_proposal"),
        "explicit_proposal_count": placement.get("explicit_proposal_count", 0),
        "explicit_proposal_names": placement.get("explicit_proposal_names", []),
        "explicit_proposal_dimension_rejects": placement.get(
            "explicit_proposal_dimension_rejects", []
        ),
        "explicit_proposal_dimension_normalizations": placement.get(
            "explicit_proposal_dimension_normalizations", []
        ),
        "explicit_reservation_count": placement.get(
            "explicit_reservation_count", 0
        ),
        "explicit_reservations": placement.get("explicit_reservations", []),
        "explicit_search_runs": placement.get("explicit_search_runs", []),
        "explicit_selected_object": placement.get("explicit_selected_object"),
        "explicit_selected_stage": placement.get("explicit_selected_stage"),
        "front_face_visibility": meas.get("front_face_visibility"),
        "left_opening_visibility": meas.get("left_opening_visibility"),
        "right_opening_visibility": meas.get("right_opening_visibility"),
        "opening_visibility_reason": meas.get("opening_visibility_reason"),
        "luma_frame": meas.get("luma_frame"),
        "luma_pallet": meas.get("luma_pallet"),
        "noise_scale": noise_scale,
        "magenta_fraction": magenta,
        "corrupt_rgb": not rgb_ok,
        "corrupt_rgb_reason": rgb_error,
        "corrupt_mask": bool(corrupt_masks),
        "corrupt_mask_reasons": corrupt_masks,
        "mask_invariants_pass": meas.get("mask_invariants_pass"),
        "G1_pass": gates.get("G1_Vvis>=4"),
        "G2_pass": gates.get("G2_extocc_1to4"),
        "G3_pass": gates.get("G3_visible>=0.5unocc"),
        "G4_pass": gates.get("G4_center_inframe"),
        "G5_pass": gates.get("G5_luma_floor"),
        "all_pass": gates.get("all_pass"),
        "reject_reason": _gate_reason(gates),
        "runtime_s": float(runtime_s),
        "stage_runtime_s": placement.get("stage_runtime_s"),
        "rgb_path": os.path.abspath(rgb_path),
        "label_path": os.path.abspath(label_path),
        "mask_paths": {key: os.path.abspath(path) for key, path in mask_paths.items()},
    }


def _record_realize_failure(idx, frame_seed, mode, plan, runtime_s, detail):
    metrics = detail if isinstance(detail, dict) else {}
    return {
        "idx": int(idx),
        "seed": int(frame_seed),
        "attempt_frame_index": int(plan.spec.frame_index),
        "diagnostic_mode": mode,
        "placement_mode": "constrained",
        "rendered": False,
        "realize_ok": False,
        "pallet_type": plan.spec.pallet_type,
        "scene_preset": plan.spec.scene_preset,
        "background_asset": metrics.get("background_asset"),
        "floor_mode": metrics.get("floor_mode_actual"),
        "elev_target": float(plan.spec.elevation_deg),
        "azimuth_bin": int(plan.spec.azimuth_bin),
        "v_target": int(plan.spec.v_target),
        "projected_size_target": float(plan.spec.proj_size_ratio),
        "f_target": float(plan.spec.f_target),
        "reject_reason": metrics.get("failure_reason", "realize_fail"),
        "anchor_translation": metrics.get("anchor_translation"),
        "anchor_attempts": metrics.get("anchor_attempts"),
        "anchor_reject_reason": metrics.get("anchor_reject_reason"),
        "anchor_reject_counts_by_reason": metrics.get(
            "anchor_reject_counts_by_reason"
        ),
        "anchor_last_failure": metrics.get("anchor_last_failure"),
        "procedural_support_shift": metrics.get(
            "procedural_support_shift"
        ),
        "support_surface_name": metrics.get("support_surface_name"),
        "min_camera_clearance": metrics.get("min_camera_clearance"),
        "camera_clearance_pass": metrics.get("camera_clearance_pass"),
        "support_pass": metrics.get("support_pass"),
        "pallet_support_pass": metrics.get("pallet_support_pass"),
        "cargo_support_pass": metrics.get("cargo_support_pass"),
        "context_support_pass": metrics.get("context_support_pass"),
        "static_collision_pass": metrics.get("static_collision_pass"),
        "static_los_pass": metrics.get("static_los_pass"),
        "n_context_requested": metrics.get("n_context_requested", 0),
        "n_context_placed": metrics.get("n_context_placed", 0),
        "n_context_visible": metrics.get("n_context_visible", 0),
        "context_visible_pixel_ratio": metrics.get(
            "context_visible_pixel_ratio"
        ),
        "context_screen_area_ratio": metrics.get("context_screen_area_ratio"),
        "context_placement_attempts": metrics.get(
            "context_placement_attempts", 0
        ),
        "context_reject_counts_by_reason": metrics.get(
            "context_reject_counts_by_reason"
        ),
        "n_cargo_requested": metrics.get("n_cargo_requested", 0),
        "n_cargo_placed": metrics.get("n_cargo_placed", 0),
        "cargo_placement_attempts": metrics.get("cargo_placement_attempts", 0),
        "cargo_collision_pass": metrics.get("cargo_collision_pass"),
        "front_visibility_after_cargo": metrics.get(
            "front_visibility_after_cargo"
        ),
        "left_opening_visibility_after_cargo": metrics.get(
            "left_opening_visibility_after_cargo"
        ),
        "right_opening_visibility_after_cargo": metrics.get(
            "right_opening_visibility_after_cargo"
        ),
        "exact_collision_count": metrics.get("exact_collision_count"),
        "tested_collision_pairs": metrics.get("tested_collision_pairs"),
        "broad_phase_hits": metrics.get("broad_phase_hits"),
        "exact_collision_hits": metrics.get("exact_collision_hits"),
        "collision_reject_reason": metrics.get("collision_reject_reason"),
        "pallet_obstacle_collision_count": metrics.get(
            "pallet_obstacle_collision_count", 0
        ),
        "cargo_collision_count": metrics.get("cargo_collision_count", 0),
        "context_context_collision_count": metrics.get(
            "context_context_collision_count", 0
        ),
        "f_explicit_target": metrics.get("f_explicit_target"),
        "f_explicit_actual": metrics.get("f_explicit_actual"),
        "explicit_abs_error": metrics.get("explicit_abs_error"),
        "explicit_feedback_depth_step_m": metrics.get(
            "explicit_feedback_depth_step_m"
        ),
        "occluder_feedback_iterations": metrics.get(
            "occluder_feedback_iterations", 0
        ),
        "occluder_side_target": metrics.get("occluder_side_target"),
        "occluder_side_actual": metrics.get("occluder_side_actual"),
        "occluder_side_match": metrics.get("occluder_side_match"),
        "explicit_occluder_visible_pixels": metrics.get(
            "explicit_occluder_visible_pixels", 0
        ),
        "explicit_collision_pass": metrics.get("explicit_collision_pass"),
        "explicit_support_pass": metrics.get("explicit_support_pass"),
        "explicit_solver_fail_reason": metrics.get(
            "explicit_solver_fail_reason"
        ),
        "explicit_reject_counts_by_reason": metrics.get(
            "explicit_reject_counts_by_reason", {}
        ),
        "explicit_candidate_log": metrics.get("explicit_candidate_log", []),
        "explicit_target_mask_stats": metrics.get(
            "explicit_target_mask_stats"
        ),
        "explicit_initial_proposal": metrics.get("explicit_initial_proposal"),
        "explicit_proposal_count": metrics.get("explicit_proposal_count", 0),
        "explicit_proposal_names": metrics.get("explicit_proposal_names", []),
        "explicit_proposal_dimension_rejects": metrics.get(
            "explicit_proposal_dimension_rejects", []
        ),
        "explicit_proposal_dimension_normalizations": metrics.get(
            "explicit_proposal_dimension_normalizations", []
        ),
        "explicit_reservation_count": metrics.get(
            "explicit_reservation_count", 0
        ),
        "explicit_reservations": metrics.get("explicit_reservations", []),
        "explicit_swept_reservations": metrics.get(
            "explicit_swept_reservations", []
        ),
        "explicit_search_runs": metrics.get("explicit_search_runs", []),
        "explicit_selected_object": metrics.get("explicit_selected_object"),
        "explicit_selected_stage": metrics.get("explicit_selected_stage"),
        "stage_runtime_s": metrics.get("stage_runtime_s"),
        "runtime_s": float(runtime_s),
    }


def _summarize(records, seed, n, solve_rejects, solve_attempts, gpu):
    rendered = [record for record in records if record.get("rendered")]
    return {
        "seed": int(seed),
        "n_target": int(n),
        "records": len(records),
        "rendered": len(rendered),
        "realize_fail": sum(
            1 for record in records if record.get("realize_ok") is False
        ),
        "all_pass": sum(1 for record in rendered if record.get("all_pass")),
        "gate_fail": {
            key: sum(1 for record in rendered if record.get(key) is False)
            for key in ("G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass")
        },
        "diagnostic_mode_counts": dict(
            Counter(record.get("diagnostic_mode") for record in records)
        ),
        "solve_rejects": int(solve_rejects),
        "solve_attempts": int(solve_attempts),
        "gpu": gpu,
        "complete": len(records) >= n,
    }


def run():
    args = _args()
    out = _abspath(args.out)
    rgb_dir = os.path.join(out, "rgb")
    mask_dir = os.path.join(out, "mask")
    label_dir = os.path.join(out, "labels")
    log_dir = os.path.join(out, "logs")
    for path in (out, rgb_dir, mask_dir, label_dir, log_dir):
        os.makedirs(path, exist_ok=True)

    import numpy as np
    import v2_pipeline as vp
    import v2_realize as vr

    jsonl_path = os.path.join(out, "records.jsonl")
    latest = _load_latest_records(jsonl_path)
    indices = chunk_indices(args.n, args.start, args.count)
    pending = []
    for idx in indices:
        prior = latest.get(idx)
        if prior is None:
            pending.append(idx)
        elif args.rerun_failures and not prior.get("rendered"):
            pending.append(idx)

    gpu = vr.enable_gpu()
    assets = vp.load_assets()
    generated_at = time.time()
    plans, solve_rejects, _, solve_attempts = vp.generate_accepted(
        args.n,
        args.seed,
        assets,
        placement_mode="constrained",
    )
    diagnostic_modes = allocate_diagnostic_modes_for_plans(
        plans,
        args.n,
        args.seed,
    )
    print(
        f"[SCENE500] gpu={gpu} out={out} n={args.n} start={args.start} "
        f"count={args.count} pending={len(pending)} plans={len(plans)} "
        f"solve_rejects={len(solve_rejects)} attempts={solve_attempts} "
        f"diagnostic_modes={dict(Counter(diagnostic_modes))} "
        f"plan_s={time.time() - generated_at:.2f}",
        flush=True,
    )

    session_start = time.time()
    for session_number, idx in enumerate(pending, 1):
        plan = plans[idx]
        mode = diagnostic_modes[idx]
        proposal_failure = None
        if (
            mode == "controlled-occlusion"
            and float(plan.spec.f_target) > 1e-6
        ):
            adjusted_plan = vp.prepare_diagnostic_explicit_occluders(
                plan,
                assets,
            )
            if isinstance(adjusted_plan, vp.Reject):
                proposal_failure = {
                    "failure_reason": adjusted_plan.reason,
                    "failure_detail": adjusted_plan.detail,
                    "explicit_solver_fail_reason": adjusted_plan.reason,
                }
            else:
                plan = adjusted_plan
        frame_seed = _frame_seed(args.seed, idx, plan.spec.frame_index)
        random.seed(frame_seed)
        np.random.seed(frame_seed & 0xFFFFFFFF)
        frame_start = time.time()
        rs = None
        failure_detail = proposal_failure
        if failure_detail is None:
            try:
                rs = vr.realize(
                    plan,
                    placement_mode="constrained",
                    diagnostic_mode=mode,
                    frame_seed=frame_seed,
                    floor_mode=None,
                    place_occluder=True,
                )
                if rs is not None and rs.get("realize_ok") is False:
                    failure_detail = rs.get("constrained_metrics") or rs
                    rs = None
            except Exception as exc:
                failure_detail = {
                    "failure_reason": f"realize_exception:{type(exc).__name__}",
                    "failure_detail": str(exc),
                }
                print(
                    f"[SCENE500] idx={idx} realize exception: {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if rs is None:
            record = _record_realize_failure(
                idx,
                frame_seed,
                mode,
                plan,
                time.time() - frame_start,
                failure_detail,
            )
            _append_record(jsonl_path, record)
            latest[idx] = record
        else:
            rgb_path = os.path.join(rgb_dir, f"f{idx:04d}_rgb.png")
            label_path = os.path.join(label_dir, f"f{idx:04d}_label.json")
            rs["rgb_path"] = rgb_path
            rs["mask_prefix"] = os.path.join(mask_dir, f"f{idx:04d}")
            try:
                vr.render(
                    rs,
                    rgb_path,
                    samples=args.samples,
                    deterministic_cpu=True,
                )
                meas = vr.measure(rs)
                noise_scale = vr.render_post(
                    rgb_path,
                    frame_seed,
                    meas.get("luma_frame") or 128.0,
                )
                gates = vr.safety_gates(meas, plan)
                label = vr.label(plan.spec, plan, meas, rs)
                _write_json(label_path, label)
                record = _record_rendered(
                    idx,
                    frame_seed,
                    mode,
                    plan,
                    rs,
                    meas,
                    gates,
                    time.time() - frame_start,
                    noise_scale,
                    rgb_path,
                    label_path,
                )
            except Exception as exc:
                record = _record_realize_failure(
                    idx,
                    frame_seed,
                    mode,
                    plan,
                    time.time() - frame_start,
                    {
                        **(rs.get("constrained_metrics") or {}),
                        "failure_reason": f"render_measure_exception:{type(exc).__name__}",
                        "failure_detail": str(exc),
                    },
                )
                print(
                    f"[SCENE500] idx={idx} render/measure exception: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
            _append_record(jsonl_path, record)
            latest[idx] = record

        ordered = _write_records_snapshot(
            os.path.join(out, "records.json"),
            latest,
        )
        summary = _summarize(
            ordered,
            args.seed,
            args.n,
            len(solve_rejects),
            solve_attempts,
            gpu,
        )
        summary.update(
            {
                "session_start": args.start,
                "session_count": args.count,
                "session_completed": session_number,
                "session_pending": len(pending) - session_number,
                "session_elapsed_s": round(time.time() - session_start, 2),
                "last_idx": idx,
            }
        )
        _write_json(os.path.join(out, "progress.json"), summary)
        print(
            f"[SCENE500] {session_number}/{len(pending)} idx={idx} mode={mode} "
            f"rendered={record.get('rendered')} all_pass={record.get('all_pass')} "
            f"reason={record.get('reject_reason')} "
            f"frame_s={record.get('runtime_s', 0.0):.2f}",
            flush=True,
        )

    latest = _load_latest_records(jsonl_path)
    ordered = _write_records_snapshot(
        os.path.join(out, "records.json"),
        latest,
    )
    final_summary = _summarize(
        ordered,
        args.seed,
        args.n,
        len(solve_rejects),
        solve_attempts,
        gpu,
    )
    final_summary.update(
        {
            "session_start": args.start,
            "session_count": args.count,
            "processed_this_session": len(pending),
            "rendered_this_session": sum(
                1 for idx in pending if latest.get(idx, {}).get("rendered")
            ),
            "session_elapsed_s": round(time.time() - session_start, 2),
        }
    )
    _write_json(os.path.join(out, "driver_summary.json"), final_summary)
    print(f"[SCENE500] SESSION DONE {final_summary}", flush=True)


if __name__ == "__main__":
    run()
