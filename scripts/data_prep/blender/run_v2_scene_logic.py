"""Constrained-scene runner for the Blender v2 pipeline.

This is intentionally separate from the legacy 2k driver.  It keeps the existing
camera/geometry prescriptions and opts into ``placement_mode="constrained"``.

Two completion modes:

``--completion-mode records`` (default, unchanged)
    ``--n`` is the number of PROPOSALS to realize (20-frame smoke / 500-frame
    diagnostic pilot).  Every proposal produces one record whether it renders,
    fails to realize, or fails a gate.

  blender -b "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
    --python scripts/data_prep/blender/run_v2_scene_logic.py -- \
    --out data/pallet/runs/diagnostics/_v2_scene_logic_500_seed7500 \
    --seed 7500 --n 500 --start 0 --count 100

``--completion-mode usable``
    ``--n`` is the number of USABLE frames to deliver.  Proposals keep coming
    until that many frames satisfy every usable condition (see
    ``usable_conditions``); rejected proposals are preserved in
    ``records_rejected.jsonl`` and their images are removed, so the delivered
    set is exactly ``--n`` contiguous ids 0..n-1.

  blender -b "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
    --python scripts/data_prep/blender/run_v2_scene_logic.py -- \
    --out data/pallet/_v2_usable50 --seed 7600 --n 50 \
    --completion-mode usable --render-profile dataset-quality

  NOTE: the usable set is filled up to ``gate_valid`` (Phase 1/2/3/5 physical +
  G1..G5).  The PnP eligibility threshold is NOT settled (Phase 4), so the
  manifest carries the 2/3/4-cell SIZE columns as a separate, purely
  informational axis.  The output is NOT "final training-ready".

``--mask-profile`` (see mask_profiles.py) chooses which masks survive:
``full-audit`` (default) keeps M0..M4 under ``mask/`` with exact per-source occlusion
fractions; ``public`` keeps only ``mask_amodal/`` + ``mask_visible/`` and never renders
M1..M3, so f_static/f_cargo/f_context/f_explicit are ``null`` (NOT MEASURED) while
f_total stays exact.
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

# bpy-free (like the audit helpers below), so the unit tests can import this runner.
import mask_profiles as MP  # noqa: E402


DIAGNOSTIC_MODES = (
    "clean-static",
    "cargo-only",
    "context-rich",
    "controlled-occlusion",
)

COMPLETION_MODES = ("records", "usable")
DIAGNOSTIC_N_CHOICES = (20, 500)

# --- usable-completion configuration -------------------------------------------------------
# Stratum shares for --completion-mode usable.  The 500-record diagnostic used
# 100/100/150/150; the same shares are apportioned over an arbitrary usable target
# (largest-remainder), because diagnostic_mode_for_index only knows 20 and 500.
USABLE_MODE_FRACTIONS = (0.20, 0.20, 0.30, 0.30)
# Safety stops (no unbounded loop).  Exceeding either one aborts with an explicit error.
USABLE_RENDER_ATTEMPT_FACTOR = 30      # render attempts allowed per requested usable frame
USABLE_MIN_RENDER_ATTEMPTS = 60
USABLE_PROPOSAL_STREAM_FACTOR = 20     # bpy-free draws per render attempt (generate_accepted uses n*20)
# A controlled-occlusion slot wants a plan that actually carries an explicit occluder.  Plans
# are cheap (bpy-free), so unsuitable ones are skipped -- but never forever.
CONTROLLED_MODE_MAX_SKIPS = 50
# Any magenta pixel = a missing/failed material.  0.0 mirrors audit_v2_scene_logic's
# --magenta-threshold default (fail when ratio > threshold).
DEFAULT_MAGENTA_MAX_FRACTION = 0.0

# PnP eligibility SIZE axis (Phase 4).  1 belief-map cell = 8 source px
# (audit_pnp_eligibility.BELIEF_CELL_PX).  These are reported, never used to reject:
# the hard threshold is undecided and the solve-success half needs cv2, which Blender's
# Python does not ship.
BELIEF_CELL_PX = 8.0
PNP_SIZE_THRESHOLDS_PX = {
    "2cell": 2 * BELIEF_CELL_PX,
    "3cell": 3 * BELIEF_CELL_PX,
    "4cell": 4 * BELIEF_CELL_PX,
}
TINY_MASK_AREA_PX = int(PNP_SIZE_THRESHOLDS_PX["2cell"] ** 2)
# Corner counts as externally occluded at >= 0.5 (scene_placement_v2.external_corner_gate_metrics).
OCCLUSION_VISIBLE_MAX = 0.5

# usable conditions -- evaluated INDEPENDENTLY and AND-ed (see usable_conditions).
# The first three groups reproduce audit_pnp_eligibility.physical_validity field for field.
PHYSICAL_TRUE_FIELDS = (
    "rendered",
    "realize_ok",
    "camera_clearance_pass",
    "support_pass",
    "mask_invariants_pass",
    "ground_continuity_pass",
)
PHYSICAL_NEGATED_FIELDS = ("corrupt_rgb", "corrupt_mask")
PHYSICAL_DERIVED_CONDITIONS = (
    "exact_collision_zero",
    "camera_distance_within_limit",
    "mask_m0_non_empty",
)
EXTRA_USABLE_CONDITIONS = (
    "no_magenta",
    "mask_pixel_inclusion",
    "no_stale_cross_frame_mask",
)
GATE_CONDITIONS = ("G1", "G2", "G3", "G4", "G5")
GATE_RECORD_FIELDS = {
    "G1": "G1_pass",
    "G2": "G2_pass",
    "G3": "G3_pass",
    "G4": "G4_pass",
    "G5": "G5_pass",
}
FALLBACK_CAMERA_DISTANCE_LIMIT_M = 10.0


class UsableCompletionError(RuntimeError):
    """Raised when --completion-mode usable hits a safety stop before filling --n."""


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


def apportion(n, fractions):
    """Largest-remainder apportionment of n over `fractions` (sums to n exactly)."""
    n = int(n)
    if n < 0:
        raise ValueError(f"n must be >= 0: {n}")
    raw = [n * float(f) for f in fractions]
    counts = [int(math.floor(v)) for v in raw]
    remainder = n - sum(counts)
    order = sorted(
        range(len(fractions)),
        key=lambda i: (-(raw[i] - counts[i]), i),
    )
    for i in range(remainder):
        counts[order[i % len(order)]] += 1
    return counts


def usable_diagnostic_modes(n):
    """Diagnostic stratum for every usable SLOT (0..n-1), in DIAGNOSTIC_MODES block order.

    The slot -- not the proposal -- owns the stratum, so the delivered set always has the
    prescribed composition no matter how many proposals each slot needed.
    """
    counts = apportion(n, USABLE_MODE_FRACTIONS)
    modes = []
    for mode, count in zip(DIAGNOSTIC_MODES, counts):
        modes.extend([mode] * count)
    return modes


def usable_max_render_attempts(n, override=None):
    if override is not None and int(override) > 0:
        return int(override)
    return max(USABLE_MIN_RENDER_ATTEMPTS, USABLE_RENDER_ATTEMPT_FACTOR * int(n))


def _tri_state(value):
    """True / False / None(unknown).  None NEVER counts as a pass (Phase 2 warning:
    ground_continuity_pass=None means 'not measured', not 'fine')."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return None
    return bool(value)


def _number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def usable_conditions(record, magenta_max=DEFAULT_MAGENTA_MAX_FRACTION,
                      seen_m0_hashes=None):
    """Evaluate EVERY usable condition independently and AND them together.

    Returns a dict with the per-condition tri-state, the failed condition names, the reject
    reasons and the two Phase-4 manifest booleans (physical_valid / gate_valid).  There is no
    short-circuit: a rejected proposal reports all of its failures, not just the first.

    Condition -> source:
      rendered/realize_ok/camera_clearance_pass/support_pass/mask_invariants_pass/
      ground_continuity_pass/corrupt_rgb/corrupt_mask/exact_collision_zero/
      camera_distance_within_limit/mask_m0_non_empty   -> Phase 1/2/5 record fields, i.e. the
          exact field list of audit_pnp_eligibility.physical_validity (= physical_valid)
      no_magenta                    -> record magenta_fraction (this runner's measurement)
      mask_pixel_inclusion          -> Phase 5 pixel-level M4<=M3<=M2<=M1<=M0
      no_stale_cross_frame_mask     -> Phase 5 cross-frame duplicate M0 content hash
      G1..G5                        -> Phase 3 safety_gates (G5 on FINAL luma)
    """
    record = record or {}
    conditions = {}

    for field in PHYSICAL_TRUE_FIELDS:
        conditions[field] = _tri_state(record.get(field))
    for field in PHYSICAL_NEGATED_FIELDS:
        state = _tri_state(record.get(field))
        conditions[f"no_{field}"] = None if state is None else (not state)

    collisions = _number(record.get("exact_collision_count"))
    conditions["exact_collision_zero"] = (
        None if collisions is None else collisions == 0
    )

    limit = _number(record.get("camera_distance_limit_m"))
    if limit is None:
        limit = FALLBACK_CAMERA_DISTANCE_LIMIT_M
    distance = _number(record.get("camera_distance_actual_m"))
    conditions["camera_distance_within_limit"] = (
        None if distance is None else distance <= limit + 1e-6
    )

    m0_area = _number(record.get("mask_m0_area_px"))
    if m0_area is None:
        m0_area = _number(record.get("mask_area_target_only"))
    conditions["mask_m0_non_empty"] = None if m0_area is None else m0_area > 0

    magenta = _number(record.get("magenta_fraction"))
    conditions["no_magenta"] = (
        None if magenta is None else magenta <= float(magenta_max)
    )

    conditions["mask_pixel_inclusion"] = _tri_state(
        record.get("mask_pixel_inclusion_ok")
    )

    m0_hash = record.get("mask_m0_content_sha256")
    if m0_hash is None:
        conditions["no_stale_cross_frame_mask"] = None
    else:
        conditions["no_stale_cross_frame_mask"] = m0_hash not in (
            seen_m0_hashes or set()
        )

    for gate in GATE_CONDITIONS:
        conditions[gate] = _tri_state(record.get(GATE_RECORD_FIELDS[gate]))

    physical_names = (
        [f"no_{field}" for field in PHYSICAL_NEGATED_FIELDS]
        + list(PHYSICAL_TRUE_FIELDS)
        + list(PHYSICAL_DERIVED_CONDITIONS)
    )
    failed = [name for name, state in conditions.items() if state is not True]
    unknown = [name for name, state in conditions.items() if state is None]
    reasons = []
    for name in failed:
        suffix = ":unknown" if conditions[name] is None else ""
        if name in GATE_CONDITIONS:
            reasons.append(f"gate_fail:{name}{suffix}")
        else:
            reasons.append(f"usable_reject:{name}{suffix}")

    return {
        "usable": not failed,
        "conditions": conditions,
        "failed_conditions": failed,
        "unknown_conditions": unknown,
        "reject_reasons": reasons,
        "physical_valid": all(
            conditions[name] is True for name in physical_names
        ),
        "physical_violations": [
            name for name in physical_names if conditions[name] is not True
        ],
        "gate_valid": all(
            conditions[gate] is True for gate in GATE_CONDITIONS
        ),
    }


def primary_reject_reason(record, verdict):
    """One-line reason for a render-stage reject.

    A realize/render failure makes every later measurement `None`, so the full reason list is
    16 `:unknown` entries.  The scannable answer is the pipeline's own failure reason; only
    when the frame actually rendered do the failed conditions themselves carry the meaning.
    """
    measured = [
        reason for reason in verdict["reject_reasons"]
        if not reason.endswith(":unknown")
    ]
    if measured:
        return "|".join(measured)
    fallback = (record or {}).get("reject_reason")
    return f"realize_fail:{fallback}" if fallback else "unknown"


def pnp_size_fields(bbox_min_side_px, m0_area_px):
    """SIZE half of the Phase-4 eligibility columns (informational only).

    The other half -- pnp_exact_success -- needs cv2.solvePnPRansac, which is not available
    inside Blender, so audit_pnp_eligibility.py must be run on the delivered set to complete
    the manifest.  Naming is deliberately `pnp_size_eligible_*`, NOT
    `pnp_eligible_candidate_*`, so the two are never confused.
    """
    min_side = _number(bbox_min_side_px)
    area = _number(m0_area_px)
    out = {}
    for name, threshold in PNP_SIZE_THRESHOLDS_PX.items():
        out[f"pnp_size_eligible_{name}"] = (
            None if min_side is None else bool(min_side >= threshold)
        )
    out["tiny_warning"] = bool(
        (min_side is not None and min_side < PNP_SIZE_THRESHOLDS_PX["2cell"])
        or (area is not None and area < TINY_MASK_AREA_PX)
    )
    return out


def chunk_indices(n, start, count):
    n = max(0, int(n))
    start = max(0, int(start))
    count = max(0, int(count))
    return list(range(start, min(n, start + count)))


def _args():
    # imported here (not at module import time) so the bpy-free unit tests can load this
    # module: v2_realize needs bpy, and this function only ever runs inside Blender.
    import camera_effects as CE
    import v2_realize as vr

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="data/pallet/runs/diagnostics/_v2_scene_logic_500_seed7500",
    )
    parser.add_argument("--seed", type=int, default=7500)
    parser.add_argument(
        "--n",
        type=int,
        default=500,
        help="records mode: number of proposals (20 or 500). "
             "usable mode: number of USABLE frames to deliver (any n >= 1)",
    )
    parser.add_argument(
        "--completion-mode",
        choices=COMPLETION_MODES,
        default="records",
        help="records = --n proposals, one record each (unchanged 20/500 diagnostics); "
             "usable = keep proposing until --n frames pass every usable condition",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="usable mode safety stop: max RENDER attempts before aborting "
             f"(default max({USABLE_MIN_RENDER_ATTEMPTS}, {USABLE_RENDER_ATTEMPT_FACTOR}*n))",
    )
    parser.add_argument(
        "--magenta-max-fraction",
        type=float,
        default=DEFAULT_MAGENTA_MAX_FRACTION,
        help="usable mode: reject a frame whose magenta pixel fraction exceeds this "
             "(default 0.0 = any magenta pixel rejects, same as audit_v2_scene_logic)",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="number of global frame indices handled by this Blender process",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="Cycles samples; default = the render profile's value",
    )
    parser.add_argument(
        "--render-profile",
        choices=tuple(vr.RENDER_PROFILES),
        default=vr.DEFAULT_RENDER_PROFILE,
        help="diagnostic-exact = byte-reproducible CPU path (500-record diagnostics); "
             "dataset-quality = GPU + denoise for training frames",
    )
    parser.add_argument(
        "--noise-tier",
        default="auto",
        choices=("auto", *CE.NOISE_TIER_LABELS),
        help="sensor degradation tier; 'auto' draws per frame from NOISE_TIER_FRAC",
    )
    parser.add_argument(
        "--mask-profile",
        choices=MP.MASK_PROFILES,
        default=MP.DEFAULT_MASK_PROFILE,
        help="full-audit = keep M0..M4 with exact per-source occlusion fractions "
             "(500-record diagnostics); public = keep only mask_amodal/ + mask_visible/ "
             "(M1..M3 are never rendered, so f_static/f_cargo/f_context/f_explicit are None)",
    )
    parser.add_argument(
        "--rerun-failures",
        action="store_true",
        help="retry indices whose latest record did not render successfully",
    )
    args = parser.parse_args(argv)
    validate_args(args, parser.error)
    return args


def validate_args(args, fail):
    """Mode-dependent argument validation (`fail` = parser.error / raising callable)."""
    if args.completion_mode == "records":
        if args.n not in DIAGNOSTIC_N_CHOICES:
            fail(
                "--completion-mode records requires --n in "
                f"{DIAGNOSTIC_N_CHOICES} (got {args.n})"
            )
    else:
        if args.n < 1:
            fail(f"--completion-mode usable requires --n >= 1 (got {args.n})")
        if args.rerun_failures:
            fail("--rerun-failures is meaningless with --completion-mode usable")
        if args.max_attempts is not None and args.max_attempts < args.n:
            fail(
                f"--max-attempts ({args.max_attempts}) must be >= --n ({args.n})"
            )
    return args


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
    import v2_pipeline as vp

    return vp.projected_size_actual(meas.get("uv8_v4"), width)


def _camera_distance_actual(rs, meas):
    """REALIZED camera->pallet-centroid distance (m), recomputed from the final scene rather
    than copied from plan.cam_distance_m (realize re-seats the camera on the centroid and the
    constrained placer translates the anchor, so the two can differ)."""
    import numpy as np

    cam = rs.get("cam_pos")
    centroid = meas.get("centroid_world")
    if cam is None or centroid is None:
        return None
    delta = np.asarray(cam, dtype=float) - np.asarray(centroid, dtype=float)
    return float(np.linalg.norm(delta))


def _mask_integrity_fields(mask_paths, mask_profile=None):
    """Phase 5 pixel-level mask integrity for ONE frame.

    Reuses audit_v2_scene_logic (bpy-free, numpy+PIL only) so the runner gate and the offline
    audit answer the same question with the same code: strict decode, M4<=M3<=M2<=M1<=M0 on the
    boolean arrays, and the M0 CONTENT hash used for the cross-frame stale-mask check.

    The stage list follows the run's mask profile, so a `public` frame is checked on the two
    masks it actually has (visible subset-of amodal) instead of being failed for the three it
    was never supposed to render.
    """
    from pathlib import Path

    import audit_v2_scene_logic as audit

    names = list(MP.mask_stages(mask_profile))
    masks = {}
    for name in names:
        path = (mask_paths or {}).get(name)
        if path:
            masks[name] = audit.strict_decode_mask(Path(path))
        else:
            masks[name] = {"present": False, "decode_ok": False, "fg": None,
                           "area": None, "content_sha256": None, "error": "missing"}
    inclusion = audit.mask_pixel_inclusion(masks, names)
    decode_ok = all(masks[name]["decode_ok"] for name in names)
    violations = ";".join(
        f"{pair['inner']}!<={pair['outer']}:{pair.get('violation_px')}"
        for pair in inclusion["pairs"]
        if pair.get("shape_mismatch") or (pair.get("violation_px") or 0) > 0
    )
    m0 = masks[names[0]]
    fields = {
        "mask_strict_decode_ok": bool(decode_ok),
        "mask_decode_errors": {
            name: masks[name]["error"]
            for name in names
            if masks[name].get("error")
        },
        "mask_shape_consistent": inclusion["shape_consistent"],
        "mask_pixel_inclusion_ok": inclusion["ok"],
        "mask_pixel_inclusion_violation_px": (
            inclusion["violation_px_total"] if inclusion["checked"] else None
        ),
        "mask_pixel_inclusion_violations": violations,
        "mask_pixel_inclusion_reason": inclusion["reason"],
        "mask_m0_area_px": m0.get("area"),
        "mask_m0_content_sha256": m0.get("content_sha256"),
    }
    for name in names:
        masks[name]["fg"] = None
        masks[name]["image"] = None
    return fields


def _visible_keypoint_metrics(meas):
    """Visible-keypoint bbox of the 9 keypoints, using the Phase-4 visibility rule.

    visible = in-frame AND (occlusion unknown OR occlusion < 0.5); the unknown case matches
    audit_pnp_eligibility (only an explicit >=0.5 measurement kills a corner).
    """
    import numpy as np

    out = {
        "visible_kp_count": None,
        "bbox_vis_w_px": None,
        "bbox_vis_h_px": None,
        "bbox_vis_min_side_px": None,
    }
    uv8 = meas.get("uv8_v4")
    cent = meas.get("cent_uv")
    in_frame8 = meas.get("in_frame8")
    if uv8 is None or cent is None or in_frame8 is None:
        return out
    uv9 = np.vstack([np.asarray(uv8, dtype=float)[:, :2],
                     np.asarray(cent, dtype=float).reshape(1, 2)])
    in_frame9 = [bool(v) for v in in_frame8] + [bool(meas.get("center_in_frame"))]
    occ = meas.get("occlusion_fraction") or []
    visible = []
    for i in range(9):
        occ_i = _number(occ[i]) if i < len(occ) else None
        visible.append(
            in_frame9[i] and (occ_i is None or occ_i < OCCLUSION_VISIBLE_MAX)
        )
    pts = uv9[np.asarray(visible, dtype=bool)]
    out["visible_kp_count"] = int(sum(visible))
    if len(pts) == 0 or not np.isfinite(pts).all():
        return out
    w = float(pts[:, 0].max() - pts[:, 0].min())
    h = float(pts[:, 1].max() - pts[:, 1].min())
    out["bbox_vis_w_px"] = w
    out["bbox_vis_h_px"] = h
    out["bbox_vis_min_side_px"] = min(w, h)
    return out


def _gate_reason(gates):
    failed = [
        key.split("_", 1)[0]
        for key, passed in gates.items()
        if key != "all_pass" and not passed
    ]
    return "accepted" if not failed else "|".join(failed)


def _record_rendered(idx, frame_seed, mode, plan, rs, meas, gates, runtime_s,
                     effects, rgb_path, label_path):
    """`effects` is the dict render_post returned (what the sensor post-effects actually did)."""
    effects = effects if isinstance(effects, dict) else {}
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
    cam_dist_target = float(plan.cam_distance_m)
    cam_dist_actual = _camera_distance_actual(rs, meas)

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
        # smallest projected-size ratio this frame's intrinsics allow under the distance cap
        "projected_size_feasible_lower": float(spec.proj_size_feasible_lower),
        "camera_distance_limit_m": float(plan.camera_distance_limit_m),
        "camera_distance_target_m": cam_dist_target,
        "camera_distance_actual_m": cam_dist_actual,
        "camera_distance_error_m": (
            None if cam_dist_actual is None else cam_dist_actual - cam_dist_target
        ),
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
        # raw = the Cycles render, final = after the sensor post-effects (the PNG on disk,
        # which is what G5 judges and what training sees).
        "luma_frame": meas.get("luma_frame_raw", meas.get("luma_frame")),
        "luma_pallet": meas.get("luma_pallet_raw", meas.get("luma_pallet")),
        "luma_frame_raw": meas.get("luma_frame_raw", meas.get("luma_frame")),
        "luma_pallet_raw": meas.get("luma_pallet_raw", meas.get("luma_pallet")),
        "luma_frame_final": meas.get("luma_frame_final"),
        "luma_pallet_final": meas.get("luma_pallet_final"),
        "noise_tier": effects.get("noise_tier"),
        "dark_factor": effects.get("dark_factor"),
        "wb_gain_rgb": effects.get("wb_gain_rgb"),
        "vignette_applied": effects.get("vignette_applied"),
        "vignette_strength": effects.get("vignette_strength"),
        "blur_applied": effects.get("blur_applied"),
        "blur_radius_px": effects.get("blur_radius_px"),
        "gaussian_noise_applied": effects.get("gaussian_noise_applied"),
        "gaussian_sigma": effects.get("gaussian_sigma"),
        "jpeg_applied": effects.get("jpeg_applied"),
        "jpeg_quality": effects.get("jpeg_quality"),
        "magenta_fraction": magenta,
        "corrupt_rgb": not rgb_ok,
        "corrupt_rgb_reason": rgb_error,
        "corrupt_mask": bool(corrupt_masks),
        "corrupt_mask_reasons": corrupt_masks,
        "mask_invariants_pass": meas.get("mask_invariants_pass"),
        "ground_continuity_pass": meas.get("ground_continuity_pass"),
        "ground_probe_count": meas.get("ground_probe_count"),
        "ground_probe_fail_count": meas.get("ground_probe_fail_count"),
        "ground_probe_hit_objects": meas.get("ground_probe_hit_objects"),
        "ground_probe_max_step_m": meas.get("ground_probe_max_step_m"),
        "ground_continuity_reason": meas.get("ground_continuity_reason"),
        "procedural_floor_edge_risk": meas.get("procedural_floor_edge_risk"),
        "procedural_floor_edge_margin_m": meas.get(
            "procedural_floor_edge_margin_m"
        ),
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
        "projected_size_feasible_lower": float(plan.spec.proj_size_feasible_lower),
        "camera_distance_limit_m": float(plan.camera_distance_limit_m),
        "camera_distance_target_m": float(plan.cam_distance_m),
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


def _process_frame(idx, plan, mode, args, assets, dirs, vp, vr, np,
                   write_label=True):
    """Realize + render + measure + gate ONE proposal into a record.

    Extracted verbatim from the records loop so both completion modes run the identical
    pipeline.  `write_label=False` defers the label write to the caller (usable mode only
    keeps the labels of frames it actually delivers).
    """
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

    result = {
        "record": None,
        "rs": rs,
        "meas": None,
        "gates": None,
        "label": None,
        "effects": None,
        "frame_seed": frame_seed,
        "plan": plan,
        "rgb_path": None,
        "label_path": None,
    }
    if rs is None:
        result["record"] = _record_realize_failure(
            idx,
            frame_seed,
            mode,
            plan,
            time.time() - frame_start,
            failure_detail,
        )
        return result

    rgb_path = os.path.join(dirs["rgb"], f"f{idx:04d}_rgb.png")
    label_path = os.path.join(dirs["labels"], f"f{idx:04d}_label.json")
    result["rgb_path"] = rgb_path
    result["label_path"] = label_path
    rs["rgb_path"] = rgb_path
    rs["mask_prefix"] = os.path.join(dirs["mask"], f"f{idx:04d}")
    rs["mask_profile"] = args.mask_profile
    rs["mask_paths"] = MP.frame_mask_paths(dirs["out"], idx, args.mask_profile)
    try:
        vr.render(
            rs,
            rgb_path,
            samples=args.samples,
            profile=args.render_profile,
        )
        # Order matters: geometry/masks first (post-effect independent), THEN the
        # sensor post-effects overwrite the PNG, THEN the final image is re-measured
        # so the gates and the label describe the pixels training actually sees.
        meas = vr.measure_geometry_and_masks(rs)
        raw_luma = meas.get("luma_frame_raw")
        effects = vr.render_post(
            rgb_path,
            frame_seed,
            raw_luma if raw_luma is not None else 128.0,
            tier=args.noise_tier,
        )
        meas.update(effects)
        meas.update(vr.measure_final_rgb_quality(rs, meas))
        gates = vr.safety_gates(meas, plan)
        label = vr.label(plan.spec, plan, meas, rs)
        if write_label:
            _write_json(label_path, label)
        result["meas"] = meas
        result["gates"] = gates
        result["label"] = label
        result["effects"] = effects
        result["record"] = _record_rendered(
            idx,
            frame_seed,
            mode,
            plan,
            rs,
            meas,
            gates,
            time.time() - frame_start,
            effects,
            rgb_path,
            label_path,
        )
    except Exception as exc:
        result["record"] = _record_realize_failure(
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
    return result


def run():
    args = _args()
    out = _abspath(args.out)
    rgb_dir = os.path.join(out, "rgb")
    mask_dir = os.path.join(out, "mask")
    label_dir = os.path.join(out, "labels")
    log_dir = os.path.join(out, "logs")
    # Only the mask directories this profile actually writes are created (public leaves no
    # empty `mask/` behind); mask_dir stays the legacy prefix root.
    profile_mask_dirs = [
        os.path.join(out, name) for name in MP.mask_dirnames(args.mask_profile)
    ]
    for path in (out, rgb_dir, *profile_mask_dirs, label_dir, log_dir):
        os.makedirs(path, exist_ok=True)

    import numpy as np
    import v2_pipeline as vp
    import v2_realize as vr

    dirs = {"out": out, "rgb": rgb_dir, "mask": mask_dir, "labels": label_dir,
            "logs": log_dir}
    if args.completion_mode == "usable":
        return run_usable(args, dirs, vp, vr, np)

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
        processed = _process_frame(
            idx,
            plans[idx],
            diagnostic_modes[idx],
            args,
            assets,
            dirs,
            vp,
            vr,
            np,
        )
        mode = diagnostic_modes[idx]
        record = processed["record"]
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
            "mask_profile": args.mask_profile,
            "mask_dirs": list(MP.mask_dirnames(args.mask_profile)),
            "occlusion_decomposition_available": (
                MP.occlusion_decomposition_available(args.mask_profile)
            ),
        }
    )
    _write_json(os.path.join(out, "driver_summary.json"), final_summary)
    print(f"[SCENE500] SESSION DONE {final_summary}", flush=True)


USABLE_MANIFEST_COLUMNS = (
    "usable_id",
    "frame_id",
    "proposal_index",
    "attempt_seed",
    "diagnostic_mode",
    "pallet_type",
    "scene_preset",
    "physical_valid",
    "gate_valid",
    "camera_distance_actual_m",
    "camera_distance_limit_m",
    "projected_size_actual",
    "elev_actual",
    "V_vis",
    "luma_pallet_final",
    "luma_frame_final",
    "noise_tier",
    "gaussian_sigma",
    "magenta_fraction",
    "mask_m0_area_px",
    "mask_pixel_inclusion_ok",
    "visible_kp_count",
    "bbox_vis_min_side_px",
    "pnp_size_eligible_2cell",
    "pnp_size_eligible_3cell",
    "pnp_size_eligible_4cell",
    "tiny_warning",
    "rgb_path",
    "label_path",
)


def iter_proposals(seed, assets, vp, placement_mode="constrained", max_proposals=None):
    """Stream (proposal_index, Plan|None, Reject|None) forever (or until max_proposals).

    Same draw order and same accept-time quota rule as vp.generate_accepted, so the plan
    sequence of `usable` mode with seed S is identical to the first plans of `records` mode
    with seed S.  The stream owns a private random.Random, so the per-frame global
    random.seed()/np.random.seed() calls made by realize() cannot disturb it.
    """
    rng = random.Random(seed)
    quota = vp.QuotaState.new(assets)
    attempts = 0
    while max_proposals is None or attempts < max_proposals:
        spec, picks = vp.sample_frame(
            rng, quota, assets, frame_index=attempts, seed=seed
        )
        plan = vp.solve_placement(
            spec,
            assets,
            placement_mode=placement_mode,
        )
        proposal_index = attempts
        attempts += 1
        if isinstance(plan, vp.Plan):
            vp.advance_quota(quota, picks)     # commit ONLY on accept
            yield proposal_index, plan, None
        else:
            yield proposal_index, None, plan


def _remove_attempt_files(record):
    """Delete the images of a rejected attempt so the delivered set stays exactly --n."""
    removed = []
    paths = [record.get("rgb_path"), record.get("label_path")]
    paths.extend((record.get("mask_paths") or {}).values())
    for path in paths:
        if not path:
            continue
        try:
            os.remove(path)
            removed.append(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"[USABLE] could not remove {path}: {exc}", flush=True)
    return removed


def _count_jsonl_lines(path):
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _resume_state(records_path, rejected_path):
    """Resume: (accepted records by usable id, next proposal index to actually run)."""
    latest = _load_latest_records(records_path)
    highest = -1
    for record in latest.values():
        index = record.get("proposal_index")
        if isinstance(index, int):
            highest = max(highest, index)
    if os.path.isfile(rejected_path):
        with open(rejected_path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                index = entry.get("proposal_index")
                if isinstance(index, int):
                    highest = max(highest, index)
    return latest, highest + 1


def _usable_summary(args, state, gpu, out, elapsed_s, complete, rejected_log_entries=0):
    return {
        "rejected_log_entries_total": int(rejected_log_entries),
        "completion_mode": "usable",
        "seed": int(args.seed),
        "usable_target": int(args.n),
        "usable_delivered": int(state["delivered"]),
        "complete": bool(complete),
        "render_attempts": int(state["render_attempts"]),
        "max_render_attempts": int(state["max_render_attempts"]),
        "proposals_drawn": int(state["proposals_drawn"]),
        "solve_rejects": int(state["solve_rejects"]),
        "mode_filter_skips": int(state["mode_filter_skips"]),
        "render_rejects": int(state["render_rejects"]),
        "reject_reason_counts": dict(state["reason_counts"]),
        "solve_reject_reason_counts": dict(state["solve_reason_counts"]),
        "condition_fail_counts": dict(state["condition_fail_counts"]),
        "primary_reject_reason_counts": dict(state["primary_reason_counts"]),
        "diagnostic_mode_counts": dict(state["mode_counts"]),
        "render_profile": args.render_profile,
        "noise_tier": args.noise_tier,
        "mask_profile": args.mask_profile,
        "mask_dirs": list(MP.mask_dirnames(args.mask_profile)),
        "occlusion_decomposition_available": MP.occlusion_decomposition_available(
            args.mask_profile
        ),
        "magenta_max_fraction": float(args.magenta_max_fraction),
        "gpu": gpu,
        "out": out,
        "elapsed_s": round(elapsed_s, 2),
        "pnp_threshold_status": "undecided (Phase 4) - size columns are informational only",
        "delivery_level": "gate_valid (physical + G1..G5); NOT final training-ready",
    }


def _write_usable_manifest(out, records, args):
    rows = []
    for record in records:
        row = {key: record.get(key) for key in USABLE_MANIFEST_COLUMNS}
        row["usable_id"] = record.get("usable_id", record.get("idx"))
        row["frame_id"] = f"f{int(row['usable_id']):04d}"
        rows.append(row)
    csv_path = os.path.join(out, "usable_manifest.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(USABLE_MANIFEST_COLUMNS) + "\n")
        for row in rows:
            values = []
            for key in USABLE_MANIFEST_COLUMNS:
                value = row.get(key)
                if value is None:
                    values.append("")
                elif isinstance(value, str) and ("," in value or '"' in value):
                    values.append('"' + value.replace('"', '""') + '"')
                else:
                    values.append(str(value))
            handle.write(",".join(values) + "\n")
    _write_json(
        os.path.join(out, "usable_manifest.json"),
        {
            "delivery_level": (
                "gate_valid: rendered + physical checks (Phase 1/2/5) + G1..G5 on the FINAL "
                "RGB (Phase 3). The PnP eligibility threshold is UNDECIDED (Phase 4), so this "
                "set is NOT 'final training-ready'."
            ),
            "usable_conditions": {
                "physical_true_fields": list(PHYSICAL_TRUE_FIELDS),
                "physical_negated_fields": list(PHYSICAL_NEGATED_FIELDS),
                "physical_derived": list(PHYSICAL_DERIVED_CONDITIONS),
                "extra": list(EXTRA_USABLE_CONDITIONS),
                "gates": list(GATE_CONDITIONS),
                "evaluation": "all conditions computed independently, then AND-ed",
                "magenta_max_fraction": float(args.magenta_max_fraction),
                "camera_distance_limit_m": FALLBACK_CAMERA_DISTANCE_LIMIT_M,
            },
            "pnp_size_axis": {
                "thresholds_px": PNP_SIZE_THRESHOLDS_PX,
                "belief_cell_px": BELIEF_CELL_PX,
                "column_meaning": (
                    "pnp_size_eligible_Ncell = visible-keypoint bbox min side >= N*8 px. "
                    "This is only the SIZE half of Phase 4's pnp_eligible_candidate_Ncell; "
                    "the solve half (pnp_exact_success) needs cv2 and must be filled by "
                    "audit_pnp_eligibility.py on this directory."
                ),
                "not_a_filter": True,
            },
            "columns": list(USABLE_MANIFEST_COLUMNS),
            "rows": rows,
        },
    )
    return csv_path


def _cumulative_primary_reasons(rejected_path):
    """Primary reason of every proposal ever logged for this output dir (all sessions)."""
    counts = Counter()
    if not os.path.isfile(rejected_path):
        return dict(counts)
    with open(rejected_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            counts[
                entry.get("primary_reject_reason")
                or (entry.get("reject_reason") or "unknown").split("|")[0]
            ] += 1
    return dict(counts)


def _write_usable_readme(out, summary):
    cumulative = _cumulative_primary_reasons(
        os.path.join(out, "records_rejected.jsonl")
    )
    mask_profile = summary.get("mask_profile", MP.DEFAULT_MASK_PROFILE)
    mask_stages = MP.mask_stages(mask_profile)
    inclusion_chain = " <= ".join(stage.upper() for stage in reversed(mask_stages))
    mask_dirs_text = ", ".join(f"`{name}/`" for name in MP.mask_dirnames(mask_profile))
    if MP.occlusion_decomposition_available(mask_profile):
        decomposition_text = (
            "`f_static` / `f_cargo` / `f_context` / `f_explicit` are EXACT "
            "(M0..M4 all rendered)."
        )
    else:
        decomposition_text = (
            "`f_static` / `f_cargo` / `f_context` / `f_explicit` are `null` = NOT MEASURED "
            "(M1..M3 were never rendered). `f_total` is still exact, from M0 and M4."
        )
    text = f"""# usable-completion output

`run_v2_scene_logic.py --completion-mode usable --n {summary['usable_target']}`
delivered **{summary['usable_delivered']}** frames with contiguous ids
`f0000`..`f{max(summary['usable_delivered'] - 1, 0):04d}`.

## What this set IS

Every delivered frame satisfies ALL of the following, each evaluated independently and
AND-ed (`run_v2_scene_logic.usable_conditions`):

- `rendered`, `realize_ok`, no corrupt RGB, no corrupt mask
- `exact_collision_count == 0`
- `support_pass`, `camera_clearance_pass`, `ground_continuity_pass` (Phase 2; `None`
  counts as FAIL, never as pass)
- `mask_invariants_pass`, pixel-level `{inclusion_chain}` (Phase 5), non-empty M0,
  no cross-frame duplicate M0 content hash
- magenta pixel fraction <= {summary['magenta_max_fraction']}
- `camera_distance_actual_m <= camera_distance_limit_m` (Phase 1, 10 m)
- G1..G5 on the FINAL post-effect RGB (Phase 3)

## What this set IS NOT

**NOT "final training-ready".** The PnP eligibility threshold (2/3/4 belief-map cells) was
NOT settled in Phase 4 - the evidence did not support fixing one - so no PnP condition was
applied here. `usable_manifest.csv` carries `pnp_size_eligible_2cell/3cell/4cell` as a
separate, purely informational axis (visible-keypoint bbox min side >= 16/24/32 px). Those
columns are the SIZE half only; run `audit_pnp_eligibility.py --dir <this dir>` to add the
solve half (`pnp_exact_success`) once cv2 is available outside Blender.

## Files

- `rgb/`, {mask_dirs_text}, `labels/` - exactly the delivered frames
  (mask profile `{mask_profile}`: {decomposition_text})
- `records.jsonl` / `records.json` - one record per DELIVERED frame (id 0..n-1), each
  carrying `proposal_index` and `attempt_seed` of the attempt that produced it
- `records_rejected.jsonl` - every rejected proposal (solve-level, mode-filter and
  render/gate/usable-level) with its reasons; images of rejected attempts are deleted
- `usable_manifest.csv` / `.json`, `driver_summary.json`, `progress.json`

## Run statistics

`records_rejected.jsonl` holds **{summary['rejected_log_entries_total']}** rejected proposals in
total (all sessions).  The counters below cover THIS session only - a resumed session that
finds the target already filled legitimately reports zeros.

```
usable delivered       {summary['usable_delivered']:>6} / {summary['usable_target']}
render attempts        {summary['render_attempts']:>6}   (cap {summary['max_render_attempts']}, this session)
proposals drawn        {summary['proposals_drawn']:>6}   (this session)
solve rejects          {summary['solve_rejects']:>6}   (this session)
mode-filter skips      {summary['mode_filter_skips']:>6}   (this session)
render/gate rejects    {summary['render_rejects']:>6}   (this session)
elapsed                {summary['elapsed_s']:>6} s
```

Primary reject reason of every logged proposal (cumulative, one per rejected proposal):
{json.dumps(cumulative, ensure_ascii=False, indent=2)}

All reject reasons of THIS session (a rejected proposal reports EVERY failed condition, so a
frame that never rendered contributes one `:unknown` entry per unmeasurable condition):
{json.dumps(summary['reject_reason_counts'], ensure_ascii=False, indent=2)}
"""
    path = os.path.join(out, "README_usable.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def run_usable(args, dirs, vp, vr, np):
    """--completion-mode usable: keep proposing until --n frames pass every usable condition."""
    out = dirs["out"]
    records_path = os.path.join(out, "records.jsonl")
    rejected_path = os.path.join(out, "records_rejected.jsonl")
    latest, resume_from = _resume_state(records_path, rejected_path)

    delivered = sorted(latest)
    if delivered and delivered != list(range(len(delivered))):
        raise UsableCompletionError(
            f"existing records.jsonl has non-contiguous usable ids: {delivered[:10]}..."
        )
    seen_m0 = {
        latest[key].get("mask_m0_content_sha256")
        for key in delivered
        if latest[key].get("mask_m0_content_sha256")
    }

    gpu = vr.enable_gpu()
    assets = vp.load_assets()
    slot_modes = usable_diagnostic_modes(args.n)
    max_render_attempts = usable_max_render_attempts(args.n, args.max_attempts)
    max_proposals = max_render_attempts * USABLE_PROPOSAL_STREAM_FACTOR
    stream = iter_proposals(
        args.seed,
        assets,
        vp,
        placement_mode="constrained",
        max_proposals=max_proposals,
    )
    state = {
        "delivered": len(delivered),
        "render_attempts": 0,
        "max_render_attempts": max_render_attempts,
        "proposals_drawn": 0,
        "solve_rejects": 0,
        "mode_filter_skips": 0,
        "render_rejects": 0,
        "reason_counts": Counter(),
        "solve_reason_counts": Counter(),
        "condition_fail_counts": Counter(),
        "primary_reason_counts": Counter(),
        "mode_counts": Counter(
            latest[key].get("diagnostic_mode") for key in delivered
        ),
    }
    print(
        f"[USABLE] gpu={gpu} out={out} target={args.n} resume_from_proposal={resume_from} "
        f"already_delivered={state['delivered']} max_render_attempts={max_render_attempts} "
        f"slot_modes={dict(Counter(slot_modes))}",
        flush=True,
    )

    session_start = time.time()
    consecutive_mode_skips = 0
    stop_reason = None
    while state["delivered"] < args.n:
        try:
            proposal_index, plan, reject = next(stream)
        except StopIteration:
            stop_reason = (
                f"proposal stream exhausted after {max_proposals} draws "
                f"({state['delivered']}/{args.n} usable)"
            )
            break
        if proposal_index < resume_from:
            continue          # replaying a previous session's stream; do not re-log
        state["proposals_drawn"] += 1

        slot = state["delivered"]
        mode = slot_modes[slot]

        if reject is not None:
            state["solve_rejects"] += 1
            reason = f"solve_reject:{reject.reason}"
            state["reason_counts"][reason] += 1
            state["solve_reason_counts"][reject.reason] += 1
            state["primary_reason_counts"][reason] += 1
            _append_record(rejected_path, {
                "proposal_index": int(proposal_index),
                "usable_slot": int(slot),
                "diagnostic_mode": mode,
                "stage": "solve",
                "primary_reject_reason": reason,
                "reject_reason": reason,
                "reject_reasons": [reason],
                "solve_reject_detail": reject.detail,
                "spec": reject.spec.to_dict(),
            })
            continue

        if (
            mode == "controlled-occlusion"
            and float(plan.spec.f_target) <= 1e-6
            and consecutive_mode_skips < CONTROLLED_MODE_MAX_SKIPS
        ):
            # A controlled-occlusion slot wants a plan that carries an explicit occluder;
            # plans are free, renders are not.  Bounded so the slot can always be filled.
            consecutive_mode_skips += 1
            state["mode_filter_skips"] += 1
            reason = "proposal_skip:mode_requires_explicit_occluder"
            state["reason_counts"][reason] += 1
            state["primary_reason_counts"][reason] += 1
            _append_record(rejected_path, {
                "proposal_index": int(proposal_index),
                "usable_slot": int(slot),
                "diagnostic_mode": mode,
                "stage": "mode_filter",
                "primary_reject_reason": reason,
                "reject_reason": reason,
                "reject_reasons": [reason],
                "f_target": float(plan.spec.f_target),
            })
            continue
        consecutive_mode_skips = 0

        if state["render_attempts"] >= max_render_attempts:
            stop_reason = (
                f"render attempt cap reached ({max_render_attempts}); "
                f"{state['delivered']}/{args.n} usable"
            )
            break
        state["render_attempts"] += 1

        processed = _process_frame(
            slot,
            plan,
            mode,
            args,
            assets,
            dirs,
            vp,
            vr,
            np,
            write_label=False,
        )
        record = processed["record"]
        record["completion_mode"] = "usable"
        record["proposal_index"] = int(proposal_index)
        record["attempt_seed"] = int(processed["frame_seed"])
        record["usable_slot"] = int(slot)

        meas = processed["meas"]
        if meas is not None:
            record.update(
                _mask_integrity_fields(
                    meas.get("mask_paths"), meas.get("mask_profile")
                )
            )
            keypoints = _visible_keypoint_metrics(meas)
            record.update(keypoints)
            record.update(
                pnp_size_fields(
                    keypoints.get("bbox_vis_min_side_px"),
                    record.get("mask_m0_area_px"),
                )
            )

        verdict = usable_conditions(
            record,
            magenta_max=args.magenta_max_fraction,
            seen_m0_hashes=seen_m0,
        )
        record["usable"] = verdict["usable"]
        record["usable_failed_conditions"] = verdict["failed_conditions"]
        record["usable_unknown_conditions"] = verdict["unknown_conditions"]
        record["usable_reject_reasons"] = verdict["reject_reasons"]
        record["physical_valid"] = verdict["physical_valid"]
        record["physical_violations"] = verdict["physical_violations"]
        record["gate_valid"] = verdict["gate_valid"]

        if verdict["usable"]:
            record["usable_id"] = int(slot)
            record["idx"] = int(slot)
            _write_json(processed["label_path"], processed["label"])
            _append_record(records_path, record)
            latest[slot] = record
            if record.get("mask_m0_content_sha256"):
                seen_m0.add(record["mask_m0_content_sha256"])
            state["delivered"] += 1
            state["mode_counts"][mode] += 1
        else:
            state["render_rejects"] += 1
            for reason in verdict["reject_reasons"]:
                state["reason_counts"][reason] += 1
            for name in verdict["failed_conditions"]:
                state["condition_fail_counts"][name] += 1
            primary = primary_reject_reason(record, verdict)
            state["primary_reason_counts"][primary] += 1
            removed = _remove_attempt_files(record)
            _append_record(rejected_path, {
                "proposal_index": int(proposal_index),
                "usable_slot": int(slot),
                "attempt_seed": int(processed["frame_seed"]),
                "diagnostic_mode": mode,
                "stage": "render",
                "primary_reject_reason": primary,
                "reject_reason": "|".join(verdict["reject_reasons"]),
                "reject_reasons": verdict["reject_reasons"],
                "failed_conditions": verdict["failed_conditions"],
                "unknown_conditions": verdict["unknown_conditions"],
                "removed_files": removed,
                "record": record,
            })

        _write_json(
            os.path.join(out, "progress.json"),
            _usable_summary(
                args,
                state,
                gpu,
                out,
                time.time() - session_start,
                state["delivered"] >= args.n,
                _count_jsonl_lines(rejected_path),
            ),
        )
        print(
            f"[USABLE] delivered={state['delivered']}/{args.n} "
            f"proposal={proposal_index} slot={slot} mode={mode} "
            f"usable={record.get('usable')} "
            f"reasons={record.get('usable_reject_reasons')} "
            f"frame_s={record.get('runtime_s', 0.0):.2f}",
            flush=True,
        )

    complete = state["delivered"] >= args.n
    ordered = _write_records_snapshot(os.path.join(out, "records.json"), latest)
    summary = _usable_summary(
        args,
        state,
        gpu,
        out,
        time.time() - session_start,
        complete,
        _count_jsonl_lines(rejected_path),
    )
    manifest_path = _write_usable_manifest(out, ordered, args)
    summary["usable_manifest"] = manifest_path
    _write_json(os.path.join(out, "driver_summary.json"), summary)
    _write_usable_readme(out, summary)
    print(f"[USABLE] SESSION DONE {summary}", flush=True)
    if not complete:
        raise UsableCompletionError(
            f"usable completion aborted: {stop_reason or 'unknown stop'}. "
            f"delivered={state['delivered']}/{args.n} "
            f"render_attempts={state['render_attempts']} "
            f"reasons={dict(state['reason_counts'])}"
        )
    return summary


if __name__ == "__main__":
    run()
