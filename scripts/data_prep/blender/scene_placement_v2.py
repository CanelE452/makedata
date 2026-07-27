"""Pure-Python contracts for constrained scene assembly."""

import hashlib
import math
import os
import random
from collections.abc import Mapping
from dataclasses import dataclass


ROLE_PALLET = "pallet"
ROLE_SUPPORT = "support"
ROLE_STATIC_BACKGROUND = "static_background"
ROLE_CARGO = "cargo"
ROLE_CONTEXT = "context"
ROLE_EXPLICIT_OCCLUDER = "explicit_occluder"

ROLES = (
    ROLE_PALLET,
    ROLE_SUPPORT,
    ROLE_STATIC_BACKGROUND,
    ROLE_CARGO,
    ROLE_CONTEXT,
    ROLE_EXPLICIT_OCCLUDER,
)

_CONTACT_PAIRS = {
    frozenset(("pallet", "support")),
    frozenset(("pallet", "cargo")),
    frozenset(("support", "context")),
    frozenset(("support", "explicit_occluder")),
}

CONTACT_ALLOWED = {
    left: {
        right: frozenset((left, right)) in _CONTACT_PAIRS
        for right in ROLES
    }
    for left in ROLES
}

CAMERA_CLEARANCE_BY_ROLE = {
    "pallet": 0.02,
    "support": 0.02,
    "static_background": 0.20,
    "cargo": 0.20,
    "context": 0.20,
    "explicit_occluder": 0.20,
}

# Ground-continuity audit: probes along the camera->pallet ground segment.
GROUND_PROBE_COUNT = 11
# 50 mm = 1/3 of the KS T-11 pallet height (150 mm) and >2x the 20 mm contact tolerance the
# support probes already use. Below it a step is contact noise / the 6 mm procedural-plane
# offset; above it the ground reads as a visible ledge at pallet scale.
GROUND_PROBE_STEP_TOLERANCE_M = 0.05

EXPLICIT_OCCLUDER_SIDES = frozenset(("left", "right", "bottom", "center"))
EXPLICIT_TARGET_ABS_TOLERANCE = 0.12
EXPLICIT_PRECISE_ABS_TOLERANCE = 0.05
EXPLICIT_FRONT_MIN_VISIBILITY = 0.30
EXPLICIT_OPENING_MIN_VISIBILITY = 0.20
EXPLICIT_ROI_SCORE_WEIGHT = 1.0
EXPLICIT_CANDIDATE_LIMIT_PER_PROPOSAL = 12
EXPLICIT_PROPOSAL_SEARCH_LIMIT = 3
EXPLICIT_MIN_PROPOSALS_BEFORE_TOLERANCE_STOP = 2


def external_corner_gate_metrics(
    in_frame,
    occlusion_fractions,
    threshold=0.5,
):
    """Summarize the existing G1/G2 contract for one explicit candidate."""
    in_frame = tuple(bool(value) for value in in_frame)
    occlusion_fractions = tuple(
        float(value) for value in occlusion_fractions
    )
    if len(in_frame) != 8 or len(occlusion_fractions) != 8:
        raise ValueError("in_frame and occlusion_fractions must contain 8 corners")
    threshold = float(threshold)
    if not math.isfinite(threshold) or threshold < 0.0 or threshold > 1.0:
        raise ValueError("threshold must be finite and in [0, 1]")
    if any(
        (not math.isfinite(value)) or value < 0.0 or value > 1.0
        for value in occlusion_fractions
    ):
        raise ValueError("occlusion_fractions must be finite and in [0, 1]")

    inframe_values = [
        value
        for inside, value in zip(in_frame, occlusion_fractions)
        if inside
    ]
    v_inframe = len(inframe_values)
    ext_occ = sum(value >= threshold for value in inframe_values)
    v_vis = v_inframe - ext_occ
    g1_pass = v_vis >= 4
    g2_pass = 1 <= ext_occ <= 4
    max_inframe = max(inframe_values, default=0.0)
    return {
        "V_inframe": v_inframe,
        "ext_occ_corners": ext_occ,
        "V_vis": v_vis,
        "G1_pass": g1_pass,
        "G2_pass": g2_pass,
        "joint_pass": g1_pass and g2_pass,
        "max_inframe_occlusion": max_inframe,
        "corner_threshold_gap": (
            max(0.0, threshold - max_inframe) if ext_occ == 0 else 0.0
        ),
    }


def explicit_corner_reserve_pass(
    metrics,
    min_inframe=5,
    max_preexisting_occluded=1,
    min_preexplicit_visible=5,
):
    """Keep corner capacity for a later controlled explicit occluder."""
    if not isinstance(metrics, Mapping):
        raise TypeError("metrics must be a mapping")
    v_inframe = int(metrics.get("V_inframe", 0))
    ext_occ = int(metrics.get("ext_occ_corners", 0))
    v_vis = int(metrics.get("V_vis", 0))
    return bool(
        v_inframe >= int(min_inframe)
        and ext_occ <= int(max_preexisting_occluded)
        and v_vis >= int(min_preexplicit_visible)
    )


def image_space_context_poses(
    pallet_center,
    camera_pos,
    camera_look,
    fx,
    fy,
    cx,
    cy,
    image_wh,
    ground_z,
    seed,
    attempts=18,
    min_target_distance=0.70,
    min_camera_distance=0.50,
    max_camera_distance=8.0,
):
    """Sample grounded context poses from visible left/right image bands."""
    pallet = tuple(float(value) for value in pallet_center)
    camera = tuple(float(value) for value in camera_pos)
    look = tuple(float(value) for value in camera_look)
    if len(pallet) != 3 or len(camera) != 3 or len(look) != 3:
        raise ValueError("pallet_center, camera_pos, and camera_look must be xyz")
    width, height = (int(value) for value in image_wh)
    if width <= 0 or height <= 0:
        raise ValueError("image_wh must be positive")
    fx = float(fx)
    fy = float(fy)
    if fx <= 0.0 or fy <= 0.0:
        raise ValueError("fx and fy must be positive")

    def subtract(left, right):
        return tuple(left[axis] - right[axis] for axis in range(3))

    def dot(left, right):
        return sum(left[axis] * right[axis] for axis in range(3))

    def cross(left, right):
        return (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )

    def normalized(vector):
        norm = math.sqrt(dot(vector, vector))
        if norm <= 1e-9:
            raise ValueError("camera_pos and camera_look must be distinct")
        return tuple(value / norm for value in vector)

    forward = normalized(subtract(look, camera))
    world_up = (0.0, 0.0, 1.0)
    right_raw = cross(forward, world_up)
    if math.sqrt(dot(right_raw, right_raw)) <= 1e-9:
        world_up = (0.0, 1.0, 0.0)
        right_raw = cross(forward, world_up)
    right = normalized(right_raw)
    up = normalized(cross(right, forward))

    rng = random.Random(int(seed))
    requested = max(0, int(attempts))
    poses = []
    candidate_index = 0
    max_candidates = max(32, requested * 32)
    while len(poses) < requested and candidate_index < max_candidates:
        side = -1.0 if candidate_index % 2 == 0 else 1.0
        if side < 0.0:
            u_fraction = rng.uniform(0.06, 0.28)
        else:
            u_fraction = rng.uniform(0.72, 0.94)
        v_fraction = rng.uniform(0.58, 0.92)
        pixel_x = u_fraction * float(width - 1)
        pixel_y = v_fraction * float(height - 1)
        x_camera = (pixel_x - float(cx)) / fx
        y_camera = (pixel_y - float(cy)) / fy
        direction = tuple(
            forward[axis]
            + x_camera * right[axis]
            - y_camera * up[axis]
            for axis in range(3)
        )
        candidate_index += 1
        if abs(direction[2]) <= 1e-9:
            continue
        ray_scale = (float(ground_z) - camera[2]) / direction[2]
        if ray_scale <= 0.0:
            continue
        point = tuple(
            camera[axis] + ray_scale * direction[axis]
            for axis in range(3)
        )
        target_distance = math.hypot(
            point[0] - pallet[0],
            point[1] - pallet[1],
        )
        camera_distance = math.hypot(
            point[0] - camera[0],
            point[1] - camera[1],
        )
        if target_distance < float(min_target_distance):
            continue
        if not (
            float(min_camera_distance)
            <= camera_distance
            <= float(max_camera_distance)
        ):
            continue
        poses.append(
            {
                "x": float(point[0]),
                "y": float(point[1]),
                "yaw_rad": rng.uniform(-math.pi, math.pi),
            }
        )
    return poses


def aspect_preserving_lowres_size(width, height, base_height=128):
    """Return a low-resolution render size with the native image aspect ratio.

    The constrained Blender feedback loop compares masks against proposals
    solved in the native camera coordinate system.  Rendering feedback masks as
    a square image changes the camera aspect and can move a planned side-strip
    occluder outside the target mask.
    """
    width = int(width)
    height = int(height)
    base_height = int(base_height)
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if base_height <= 0:
        raise ValueError("base_height must be positive")
    if width >= height:
        return (
            max(1, int(round(float(width) / float(height) * base_height))),
            base_height,
        )
    return (
        base_height,
        max(1, int(round(float(height) / float(width) * base_height))),
    )


def explicit_search_schedule():
    """Return the bounded deterministic camera-frame search stages."""
    primary = tuple(
        (du, 0.0, depth, 0.0)
        for du in (-0.30, 0.0, 0.30)
        for depth in (-0.35, 0.0, 0.35)
    )
    refine = (
        (0.0, 0.0, 0.0, 0.0),
        (-0.15, 0.0, 0.0, 0.0),
        (0.15, 0.0, 0.0, 0.0),
        (0.0, -0.15, 0.0, 0.0),
        (0.0, 0.15, 0.0, 0.0),
        (0.0, 0.0, -0.175, 0.0),
        (0.0, 0.0, 0.175, 0.0),
        (-0.15, 0.0, -0.175, 0.0),
        (-0.15, 0.0, 0.175, 0.0),
        (0.15, 0.0, -0.175, 0.0),
        (0.15, 0.0, 0.175, 0.0),
        (-0.15, -0.15, 0.0, 0.0),
        (0.15, 0.15, 0.0, 0.0),
    )
    rescue = (
        (-0.90, 0.0, 0.0, 0.0),
        (-0.60, 0.0, 0.0, 0.0),
        (0.60, 0.0, 0.0, 0.0),
        (0.90, 0.0, 0.0, 0.0),
        (0.0, -0.90, 0.0, 0.0),
        (0.0, -0.60, 0.0, 0.0),
        (0.0, -0.30, 0.0, 0.0),
        (0.0, 0.30, 0.0, 0.0),
        (0.0, 0.60, 0.0, 0.0),
        (0.0, 0.90, 0.0, 0.0),
        (0.0, 0.0, -1.05, 0.0),
        (0.0, 0.0, -0.70, 0.0),
        (0.0, 0.0, 0.70, 0.0),
        (0.0, 0.0, 1.05, 0.0),
        (-0.60, -0.60, 0.0, 0.0),
        (-0.60, 0.60, 0.0, 0.0),
        (0.60, -0.60, 0.0, 0.0),
        (0.60, 0.60, 0.0, 0.0),
        (-0.60, 0.0, -0.70, 0.0),
        (-0.60, 0.0, 0.70, 0.0),
        (0.60, 0.0, -0.70, 0.0),
        (0.60, 0.0, 0.70, 0.0),
        (0.0, -0.60, -0.70, 0.0),
        (0.0, -0.60, 0.70, 0.0),
        (0.0, 0.60, -0.70, 0.0),
        (0.0, 0.60, 0.70, 0.0),
    )
    return {
        "primary": {"candidates": primary},
        "refine": {"candidates": refine},
        "rescue": {"candidates": rescue},
    }


def bounded_candidate_offsets(candidates, attempted, limit):
    """Return the deterministic prefix that fits a per-proposal search budget."""
    candidates = tuple(tuple(float(value) for value in row) for row in candidates)
    if any(len(row) != 4 for row in candidates):
        raise ValueError("each explicit candidate offset must contain four values")
    attempted = int(attempted)
    limit = int(limit)
    if attempted < 0:
        raise ValueError("attempted must be non-negative")
    if limit <= 0:
        raise ValueError("limit must be positive")
    return candidates[:max(0, limit - attempted)]


def explicit_refine_plan(initial_plan, successful_record=None):
    """Return a fine-search seed from a coarse hit or the original proposal."""
    refined = dict(initial_plan)
    if successful_record is not None:
        refined["center"] = list(successful_record["center"])
        refined["yaw_rad"] = float(successful_record["yaw_rad"])
    return refined


def best_explicit_search_seed(*results):
    """Return the highest-scoring accepted or rejected search record."""
    best = None
    best_score = -math.inf
    for result in results:
        if not result:
            continue
        for key in ("best", "best_rejected"):
            record = result.get(key)
            if record is None or record.get("score") is None:
                continue
            score = float(record["score"])
            if score > best_score:
                best = record
                best_score = score
    return best


def best_explicit_accepted_seed(*results):
    """Return the highest-scoring side-matched search record."""
    best = None
    best_score = -math.inf
    for result in results:
        if not result:
            continue
        record = result.get("best")
        if record is None or record.get("score") is None:
            continue
        score = float(record["score"])
        if score > best_score:
            best = record
            best_score = score
    return best


def best_explicit_side_seed(*results):
    """Return the best visible candidate already on the requested image side."""
    best = None
    best_score = -math.inf
    for result in results:
        if not result:
            continue
        for record in result.get("candidate_log", ()):
            metrics = record.get("score_callback") or {}
            if not metrics.get("occluder_side_match"):
                continue
            if int(metrics.get("object_visible_pixels") or 0) < 8:
                continue
            if record.get("score") is None:
                continue
            score = float(record["score"])
            if score > best_score:
                best = record
                best_score = score
    return best


def best_explicit_gate_side_seed(*results):
    """Return the best visible candidate that already satisfies G1/G2 and side."""
    best = None
    best_score = -math.inf
    for result in results:
        if not result:
            continue
        for record in result.get("candidate_log", ()):
            metrics = record.get("score_callback") or {}
            if not metrics.get("occluder_side_match"):
                continue
            if int(metrics.get("object_visible_pixels") or 0) < 8:
                continue
            if not metrics.get("candidate_G1_pass"):
                continue
            if not metrics.get("candidate_G2_pass"):
                continue
            if record.get("score") is None:
                continue
            score = float(record["score"])
            if score > best_score:
                best = record
                best_score = score
    return best


def best_explicit_gate_seed(*results):
    """Return the best visible candidate that satisfies G1/G2."""
    best = None
    best_score = -math.inf
    for result in results:
        if not result:
            continue
        for record in result.get("candidate_log", ()):
            metrics = record.get("score_callback") or {}
            if int(metrics.get("object_visible_pixels") or 0) < 8:
                continue
            if not metrics.get("candidate_G1_pass"):
                continue
            if not metrics.get("candidate_G2_pass"):
                continue
            if record.get("score") is None:
                continue
            score = float(record["score"])
            if score > best_score:
                best = record
                best_score = score
    return best


def best_explicit_missing_corner_seed(*results):
    """Return an area-valid side match that only lacks G2 corner contact."""
    best = None
    best_score = -math.inf
    for result in results:
        if not result:
            continue
        for record in result.get("candidate_log", ()):
            metrics = record.get("score_callback") or {}
            if not metrics.get("occluder_side_match"):
                continue
            if int(metrics.get("object_visible_pixels") or 0) < 8:
                continue
            if not metrics.get("target_error_ok"):
                continue
            if not metrics.get("candidate_G1_pass"):
                continue
            if metrics.get("candidate_G2_pass"):
                continue
            if int(metrics.get("candidate_ext_occ_corners") or 0) != 0:
                continue
            if record.get("score") is None:
                continue
            score = float(record["score"])
            if score > best_score:
                best = record
                best_score = score
    return best


def camera_ray_point_at_z(
    camera_pos,
    target_center,
    target_z,
    epsilon=1e-9,
):
    """Move a planned center along its camera ray to one grounded height."""
    camera = tuple(float(value) for value in camera_pos)
    target = tuple(float(value) for value in target_center)
    dz = target[2] - camera[2]
    if abs(dz) <= float(epsilon):
        return None
    t = (float(target_z) - camera[2]) / dz
    if t <= float(epsilon):
        return None
    return (
        camera[0] + t * (target[0] - camera[0]),
        camera[1] + t * (target[1] - camera[1]),
        float(target_z),
    )


def optical_depth_step_for_ground(
    camera_pos,
    camera_look,
    ground_step,
    min_horizontal_fraction=0.1,
):
    """Convert a desired ground-plane displacement to an optical-axis step."""
    camera = tuple(float(value) for value in camera_pos)
    look = tuple(float(value) for value in camera_look)
    if len(camera) != 3 or len(look) != 3:
        raise ValueError("camera_pos and camera_look must contain xyz")
    if not all(math.isfinite(value) for value in camera + look):
        raise ValueError("camera_pos and camera_look must be finite")
    ground_step = abs(float(ground_step))
    minimum = float(min_horizontal_fraction)
    if not math.isfinite(ground_step) or ground_step <= 0.0:
        raise ValueError("ground_step must be finite and positive")
    if not math.isfinite(minimum) or minimum <= 0.0 or minimum > 1.0:
        raise ValueError("min_horizontal_fraction must be in (0, 1]")

    dx = look[0] - camera[0]
    dy = look[1] - camera[1]
    dz = look[2] - camera[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    if distance <= 1e-12:
        raise ValueError("camera_pos and camera_look must be distinct")
    horizontal_fraction = math.hypot(dx, dy) / distance
    return ground_step / max(horizontal_fraction, minimum)


def manifest_bbox_to_blender_dimensions(manifest_bbox):
    """Convert manifest (X, Y-up height, Z-depth) to Blender XYZ dimensions."""
    values = tuple(float(value) for value in manifest_bbox)
    if len(values) != 3:
        raise ValueError("manifest_bbox must contain three values")
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        raise ValueError("manifest_bbox values must be finite and positive")
    return values[0], values[2], values[1]


def validate_occluder_dimensions(
    manifest_bbox,
    blender_dimensions,
    relative_tolerance=0.25,
):
    """Compare manifest Y-up dimensions with a Blender Z-up hierarchy AABB."""
    manifest = tuple(float(value) for value in manifest_bbox)
    actual = tuple(float(value) for value in blender_dimensions)
    tolerance = float(relative_tolerance)
    if len(manifest) != 3 or len(actual) != 3:
        raise ValueError("occluder dimensions must contain three values")
    if not all(
        math.isfinite(value) and value > 0.0
        for value in manifest + actual
    ):
        raise ValueError("occluder dimensions must be finite and positive")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("relative_tolerance must be finite and nonnegative")

    expected = manifest_bbox_to_blender_dimensions(manifest)
    ratios = tuple(
        measured / wanted
        for measured, wanted in zip(actual, expected)
    )
    valid = all(abs(ratio - 1.0) <= tolerance for ratio in ratios)
    mean_ratio = sum(ratios) / 3.0
    uniform_relative_spread = max(
        abs(ratio / mean_ratio - 1.0)
        for ratio in ratios
    )
    normalization_candidate = 1.0 / mean_ratio
    uniformly_rescalable = bool(
        not valid
        and uniform_relative_spread <= 0.05
        and 0.25 <= normalization_candidate <= 4.0
    )
    normalization_scale = (
        1.0
        if valid
        else normalization_candidate if uniformly_rescalable else None
    )
    normalized_ratios = (
        None
        if normalization_scale is None
        else [ratio * normalization_scale for ratio in ratios]
    )
    return {
        "valid": valid,
        "uniformly_rescalable": uniformly_rescalable,
        "manifest_y_up": list(manifest),
        "expected_xyz": list(expected),
        "actual_xyz": list(actual),
        "axis_ratio_xyz": list(ratios),
        "uniform_relative_spread": uniform_relative_spread,
        "normalization_scale": normalization_scale,
        "normalized_axis_ratio_xyz": normalized_ratios,
        "relative_tolerance": tolerance,
    }


def translated_explicit_proposal(proposal, rigid_translation):
    """Return a copied explicit plan translated with the target-camera assembly."""
    translated = dict(proposal)
    center = tuple(float(value) for value in proposal["center"])
    shift = tuple(float(value) for value in rigid_translation)
    if len(center) != 3 or len(shift) != 3:
        raise ValueError("explicit center and rigid_translation must contain xyz")
    if not all(math.isfinite(value) for value in center + shift):
        raise ValueError("explicit center and rigid_translation must be finite")
    translated["center"] = [
        center[axis] + shift[axis]
        for axis in range(3)
    ]
    return translated


def mask_index_stats(rows, cols, height, width):
    """Summarize nonzero mask indices without importing an array library."""
    rows = [int(value) for value in rows]
    cols = [int(value) for value in cols]
    if len(rows) != len(cols):
        raise ValueError("rows and cols must contain the same number of indices")
    height = int(height)
    width = int(width)
    if height <= 0 or width <= 0:
        raise ValueError("height and width must be positive")
    if not rows:
        return {
            "visible_pixels": 0,
            "bbox_px": None,
            "centroid_px": None,
            "centroid_norm": None,
        }

    count = len(rows)
    center_x = float(sum(cols)) / float(count)
    center_y = float(sum(rows)) / float(count)
    return {
        "visible_pixels": count,
        "bbox_px": [min(cols), min(rows), max(cols), max(rows)],
        "centroid_px": [center_x, center_y],
        "centroid_norm": [
            center_x / float(max(1, width - 1)),
            center_y / float(max(1, height - 1)),
        ],
    }


def projected_bbox_stats(uv, depths, source_size, target_size):
    """Scale positive-depth projected points, retaining offscreen coordinates."""
    points = [tuple(float(value) for value in point) for point in uv]
    depths = [float(value) for value in depths]
    if len(points) != len(depths):
        raise ValueError("uv and depths must contain the same number of points")
    if any(len(point) != 2 for point in points):
        raise ValueError("each uv point must contain xy")
    source_width, source_height = (int(value) for value in source_size)
    target_width, target_height = (int(value) for value in target_size)
    if min(
        source_width,
        source_height,
        target_width,
        target_height,
    ) <= 0:
        raise ValueError("source_size and target_size must be positive")

    scale_x = float(target_width) / float(source_width)
    scale_y = float(target_height) / float(source_height)
    visible = [
        (point[0] * scale_x, point[1] * scale_y)
        for point, depth in zip(points, depths)
        if depth > 0.0
        and math.isfinite(depth)
        and all(math.isfinite(value) for value in point)
    ]
    if not visible:
        return {
            "visible_points": 0,
            "bbox_px": None,
            "centroid_px": None,
        }
    xs = [point[0] for point in visible]
    ys = [point[1] for point in visible]
    return {
        "visible_points": len(visible),
        "bbox_px": [min(xs), min(ys), max(xs), max(ys)],
        "centroid_px": [
            sum(xs) / float(len(xs)),
            sum(ys) / float(len(ys)),
        ],
    }


def bbox_gap_px(left, right):
    """Return Euclidean pixel separation between two inclusive xyxy boxes."""
    if left is None or right is None:
        return None
    if len(left) != 4 or len(right) != 4:
        raise ValueError("bounding boxes must be [xmin, ymin, xmax, ymax]")
    ax0, ay0, ax1, ay1 = (float(value) for value in left)
    bx0, by0, bx1, by1 = (float(value) for value in right)
    dx = max(0.0, ax0 - bx1, bx0 - ax1)
    dy = max(0.0, ay0 - by1, by0 - ay1)
    return math.hypot(dx, dy)


def support_hit_objects(report):
    """Return the unique object names hit by a support probe."""
    if not report:
        return ()
    return tuple(
        sorted(
            {
                str(sample["hit_object"])
                for sample in report.get("samples", ())
                if sample.get("hit_object")
            }
        )
    )


def ground_probe_points_xy(camera_xy, target_xy, count=GROUND_PROBE_COUNT):
    """Return `count` evenly spaced XY probes from the camera ground-projection to the target.

    Both endpoints are included, so index 0 sits under the camera and index -1 under the
    target (pallet centroid). Degenerate input (camera directly above the target) collapses
    to repeated points, which is valid: every probe then samples the same ground spot."""
    count = int(count)
    if count < 2:
        raise ValueError("ground probe count must be >= 2")
    cam = tuple(float(value) for value in camera_xy)
    tgt = tuple(float(value) for value in target_xy)
    if len(cam) != 2 or len(tgt) != 2:
        raise ValueError("ground probe endpoints must contain xy")
    if not all(math.isfinite(value) for value in cam + tgt):
        raise ValueError("ground probe endpoints must be finite")
    last = count - 1
    return [
        (
            cam[0] + (tgt[0] - cam[0]) * (idx / last),
            cam[1] + (tgt[1] - cam[1]) * (idx / last),
        )
        for idx in range(count)
    ]


def procedural_plane_bounds(center_xy, plane_size):
    """Return the (min_x, min_y, max_x, max_y) world bounds of a square procedural floor."""
    center = tuple(float(value) for value in center_xy)
    if len(center) != 2:
        raise ValueError("plane center must contain xy")
    size = float(plane_size)
    if not math.isfinite(size) or size <= 0.0:
        raise ValueError("plane size must be finite and positive")
    half = size / 2.0
    return (center[0] - half, center[1] - half, center[0] + half, center[1] + half)


def plane_bounds_margin_m(point_xy, bounds):
    """Signed distance from one XY point to a rectangle border (positive = inside)."""
    if bounds is None:
        return None
    x, y = (float(value) for value in point_xy)
    min_x, min_y, max_x, max_y = (float(value) for value in bounds)
    return min(x - min_x, max_x - x, y - min_y, max_y - y)


def _ground_probe_kind(sample, floor_object_name=None):
    """Classify one probe hit: the procedural floor, another support, a non-support, or a miss."""
    if not sample.get("hit"):
        return "miss"
    support = sample.get("support")
    if support is None:
        return "other"
    if sample.get("ok", True) is False:
        return "steep"
    if floor_object_name is not None and str(support) == str(floor_object_name):
        return "floor"
    return "support"


def ground_continuity_verdict(
    samples,
    *,
    floor_object_name=None,
    plane_bounds=None,
    step_tolerance_m=GROUND_PROBE_STEP_TOLERANCE_M,
    expected_count=GROUND_PROBE_COUNT,
):
    """Aggregate downward ground probes into the ground-continuity audit metrics.

    `samples` are ordered camera-side -> target-side rows shaped like
    `scene_visibility_v2.support_surface_at_xy` output plus a `point` (x, y) key.

    A frame passes when (1) every probe lands on a support-role surface, (2) the support
    height step between adjacent probes stays within `step_tolerance_m`, and (3) no probe
    leaves the finite procedural floor rectangle."""
    rows = list(samples or ())
    tolerance = float(step_tolerance_m)
    hit_objects = []
    fail_count = 0
    reasons = []
    edge_margin = None
    edge_risk = False
    for idx, sample in enumerate(rows):
        point = tuple(float(value) for value in sample.get("point", (float("nan"),) * 2))
        kind = _ground_probe_kind(sample, floor_object_name=floor_object_name)
        support_z = sample.get("support_z")
        margin = plane_bounds_margin_m(point, plane_bounds)
        if margin is not None:
            edge_margin = margin if edge_margin is None else min(edge_margin, margin)
            if margin < 0.0:
                edge_risk = True
        ok = kind in {"floor", "support"}
        if not ok:
            fail_count += 1
            reasons.append(f"probe{idx}_{kind}")
        # The probe XY and its plane margin are deliberately NOT stored per row: both are
        # derivable from the labelled camera/centroid pair, and 11 extra rows per frame is
        # real cost at 40k frames. Only the non-derivable raycast outcome is kept.
        hit_objects.append(
            {
                "idx": idx,
                "kind": kind,
                "hit_object": sample.get("hit_object"),
                "support": sample.get("support"),
                "support_z": (
                    None if support_z is None else round(float(support_z), 5)
                ),
                "ok": bool(ok),
            }
        )

    z_values = [
        float(sample["support_z"])
        for sample in rows
        if sample.get("support_z") is not None
    ]
    max_step = None
    step_pass = True
    consecutive = [
        row.get("support_z")
        for row in rows
    ]
    for left, right in zip(consecutive, consecutive[1:]):
        if left is None or right is None:
            continue
        step = abs(float(right) - float(left))
        max_step = step if max_step is None else max(max_step, step)
        if step > tolerance:
            step_pass = False
    if not step_pass:
        reasons.append("support_z_discontinuity")
    if edge_risk:
        reasons.append("procedural_floor_edge")
    count_ok = len(rows) == int(expected_count)
    if not count_ok:
        reasons.append("probe_count_mismatch")

    passed = bool(count_ok and rows and fail_count == 0 and step_pass and not edge_risk)
    return {
        "ground_continuity_pass": passed,
        "ground_probe_count": len(rows),
        "ground_probe_fail_count": int(fail_count),
        "ground_probe_hit_objects": hit_objects,
        "procedural_floor_edge_risk": bool(edge_risk),
        "procedural_floor_edge_margin_m": (
            None if edge_margin is None else round(float(edge_margin), 4)
        ),
        "ground_probe_max_step_m": (
            None if max_step is None else round(float(max_step), 5)
        ),
        "ground_probe_z_range_m": (
            None if not z_values else round(float(max(z_values) - min(z_values)), 5)
        ),
        "ground_probe_step_tolerance_m": tolerance,
        "ground_continuity_reason": ";".join(reasons) if reasons else None,
    }


def explicit_feedback_offsets(
    target_stats,
    candidate_metrics,
    target_side,
    step_m=0.05,
    depth_step_m=0.10,
    yaw_step_degrees=(15.0,),
):
    """Return bounded camera-frame corrections from measured mask centroids."""
    if target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder target side: {target_side!r}")
    target_bbox = target_stats.get("bbox_px")
    target_centroid = target_stats.get("centroid_px")
    object_centroid = (
        candidate_metrics.get("object_visible_centroid_px")
        or candidate_metrics.get("object_amodal_centroid_px")
    )
    if (
        target_bbox is None
        or target_centroid is None
        or object_centroid is None
    ):
        return ()

    x0, y0, x1, y1 = (float(value) for value in target_bbox)
    target_x = float(target_centroid[0])
    target_y = float(target_centroid[1])
    if target_side == "left":
        target_x = x0 + (x1 - x0) / 6.0
    elif target_side == "right":
        target_x = x0 + 5.0 * (x1 - x0) / 6.0
    elif target_side == "bottom":
        target_y = y0 + 5.0 * (y1 - y0) / 6.0

    dx = target_x - float(object_centroid[0])
    dy = target_y - float(object_centroid[1])
    step = abs(float(step_m))
    if step <= 0.0:
        raise ValueError("step_m must be positive")
    depth_step = abs(float(depth_step_m))
    if depth_step <= 0.0:
        raise ValueError("depth_step_m must be positive")
    yaw_steps = tuple(
        abs(math.radians(float(value)))
        for value in yaw_step_degrees
    )
    if not yaw_steps or any(value <= 0.0 for value in yaw_steps):
        raise ValueError("yaw_step_degrees must contain positive values")
    du = 0.0 if abs(dx) <= 1.0 else math.copysign(step, dx)
    # Camera-frame +v projects upward, opposite the image-row direction.
    dv = 0.0 if abs(dy) <= 1.0 else -math.copysign(step, dy)
    target_width = max(1.0, x1 - x0)
    target_height = max(1.0, y1 - y0)
    u_gain = min(6, max(1, int(math.ceil(abs(dx) / (target_width / 6.0)))))
    v_gain = min(6, max(1, int(math.ceil(abs(dy) / (target_height / 6.0)))))
    guided_du = float(u_gain) * du
    guided_dv = float(v_gain) * dv
    raw = [
        (du, 0.0, 0.0, 0.0),
        (2.0 * du, 0.0, 0.0, 0.0),
        (0.0, dv, 0.0, 0.0),
        (0.0, 2.0 * dv, 0.0, 0.0),
        (du, dv, 0.0, 0.0),
        (2.0 * du, dv, 0.0, 0.0),
        (du, 2.0 * dv, 0.0, 0.0),
        (2.0 * du, 2.0 * dv, 0.0, 0.0),
        (du, dv, -depth_step, 0.0),
        (du, dv, -2.0 * depth_step, 0.0),
        (2.0 * du, 2.0 * dv, -depth_step, 0.0),
        (2.0 * du, 2.0 * dv, -2.0 * depth_step, 0.0),
        (du, dv, depth_step, 0.0),
        (du, dv, 2.0 * depth_step, 0.0),
        (2.0 * du, 2.0 * dv, depth_step, 0.0),
        (2.0 * du, 2.0 * dv, 2.0 * depth_step, 0.0),
        (guided_du, guided_dv, 0.0, 0.0),
        (guided_du, 0.0, 0.0, 0.0),
        (2.0 * guided_du, 0.0, 0.0, 0.0),
        (0.0, guided_dv, 0.0, 0.0),
        (0.0, 2.0 * guided_dv, 0.0, 0.0),
        (guided_du, 0.0, depth_step, 0.0),
        (2.0 * guided_du, 0.0, depth_step, 0.0),
    ]
    for yaw_step in yaw_steps:
        raw.extend(
            (
                (0.0, 0.0, 0.0, yaw_step),
                (0.0, 0.0, 0.0, -yaw_step),
            )
        )
    result = []
    for candidate in raw:
        candidate = tuple(round(float(value), 12) for value in candidate)
        if candidate == (0.0, 0.0, 0.0, 0.0) or candidate in result:
            continue
        result.append(candidate)
    return tuple(result)


def explicit_overlap_refinement_offsets(
    target_side,
    actual_fraction,
    target_fraction,
    steps_m=(0.05, 0.10, 0.15, 0.20, 0.25, 0.30),
):
    """Move a side-valid candidate inward or outward to correct overlap area."""
    if target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder target side: {target_side!r}")
    actual = float(actual_fraction)
    target = float(target_fraction)
    if not all(math.isfinite(value) for value in (actual, target)):
        raise ValueError("actual_fraction and target_fraction must be finite")
    if not all(0.0 <= value <= 1.0 for value in (actual, target)):
        raise ValueError("actual_fraction and target_fraction must be in [0, 1]")
    delta = target - actual
    if abs(delta) <= 1e-12:
        return ()
    direction = 1.0 if delta > 0.0 else -1.0
    steps = tuple(abs(float(value)) for value in steps_m)
    if not steps or any(
        (not math.isfinite(value)) or value <= 0.0 for value in steps
    ):
        raise ValueError("steps_m must contain positive finite values")

    if target_side == "bottom":
        paired = []
        for step in steps:
            signed = round(direction * step, 12)
            paired.append(
                (
                    0.0,
                    round(-signed, 12),
                    signed,
                    0.0,
                )
            )
        vertical = [
            (0.0, round(direction * step, 12), 0.0, 0.0)
            for step in steps[:3]
        ]
        depth = [
            (0.0, 0.0, round(direction * step, 12), 0.0)
            for step in steps[:3]
        ]
        return tuple(paired + vertical + depth)

    depth = [
        (0.0, 0.0, round(direction * step, 12), 0.0)
        for step in steps
    ]
    if target_side == "center":
        return tuple(depth)

    lateral_direction = direction if target_side == "left" else -direction
    lateral = [
        (round(lateral_direction * step, 12), 0.0, 0.0, 0.0)
        for step in steps
    ]
    return tuple(depth + lateral)


def explicit_corner_contact_refinement_offsets(
    target_side,
    steps_m=(0.05, 0.10, 0.15, 0.20, 0.25),
):
    """Slide an area-valid occluder along its side to contact one corner."""
    if target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder target side: {target_side!r}")
    steps = tuple(abs(float(value)) for value in steps_m)
    if not steps or any(
        (not math.isfinite(value)) or value <= 0.0 for value in steps
    ):
        raise ValueError("steps_m must contain positive finite values")

    if target_side in {"bottom", "center"}:
        horizontal = []
        for step in steps:
            horizontal.extend(
                (
                    (round(step, 12), 0.0, 0.0, 0.0),
                    (round(-step, 12), 0.0, 0.0, 0.0),
                )
            )
        if target_side == "bottom":
            return tuple(horizontal)

    vertical = []
    vertical_steps = steps[:3] if target_side == "center" else steps
    for step in vertical_steps:
        vertical.extend(
            (
                (0.0, round(step, 12), 0.0, 0.0),
                (0.0, round(-step, 12), 0.0, 0.0),
            )
        )
    if target_side == "center":
        return tuple(horizontal[:6] + vertical)
    return tuple(vertical)


def _bbox_xyxy(stats, keys):
    for key in keys:
        bbox = stats.get(key)
        if bbox is None:
            continue
        if len(bbox) != 4:
            raise ValueError(f"{key} must be [xmin, ymin, xmax, ymax]")
        values = tuple(float(value) for value in bbox)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{key} must contain finite values")
        x0, y0, x1, y1 = values
        if x0 > x1 or y0 > y1:
            raise ValueError(f"{key} has inverted bounds")
        return values
    return None


def _centroid_xy(stats, keys):
    for key in keys:
        centroid = stats.get(key)
        if centroid is None:
            continue
        if len(centroid) != 2:
            raise ValueError(f"{key} must be [x, y]")
        values = tuple(float(value) for value in centroid)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{key} must contain finite values")
        return values
    return None


def explicit_bbox_alignment_offsets(
    target_stats,
    candidate_metrics,
    target_side,
    *,
    meters_per_pixel_u,
    meters_per_pixel_v,
    overlap_fraction=0.25,
    max_abs_shift_m=1.5,
    depth_step_m=None,
    yaw_step_degrees=(),
):
    """Return camera-frame offsets that make a visible occluder touch a target side.

    The analytic proposal stage estimates an asset's image footprint from a
    manifest bbox.  Real Blender masks can differ substantially after hierarchy
    transforms and yaw.  This helper uses one measured low-res object bbox to
    seed a short guided search before the expensive broad local search.
    """
    if target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder target side: {target_side!r}")

    target_bbox = _bbox_xyxy(target_stats, ("bbox_px",))
    object_bbox = _bbox_xyxy(
        candidate_metrics,
        (
            "object_visible_bbox_px",
            "object_amodal_bbox_px",
            "object_projected_bbox_px",
        ),
    )
    if target_bbox is None or object_bbox is None:
        return ()

    m_per_u = float(meters_per_pixel_u)
    m_per_v = float(meters_per_pixel_v)
    if (
        not math.isfinite(m_per_u)
        or not math.isfinite(m_per_v)
        or m_per_u <= 0.0
        or m_per_v <= 0.0
    ):
        raise ValueError("meters_per_pixel_u/v must be finite positive values")
    overlap_fraction = float(overlap_fraction)
    max_abs_shift_m = abs(float(max_abs_shift_m))
    if (
        not math.isfinite(overlap_fraction)
        or overlap_fraction <= 0.0
        or overlap_fraction > 1.0
    ):
        raise ValueError("overlap_fraction must be in (0, 1]")
    if not math.isfinite(max_abs_shift_m) or max_abs_shift_m <= 0.0:
        raise ValueError("max_abs_shift_m must be finite and positive")

    tx0, ty0, tx1, ty1 = target_bbox
    ox0, oy0, ox1, oy1 = object_bbox
    target_w = max(1.0, tx1 - tx0 + 1.0)
    target_h = max(1.0, ty1 - ty0 + 1.0)
    overlap_x = max(2.0, min(0.5 * target_w, target_w * overlap_fraction))
    overlap_y = max(2.0, min(0.5 * target_h, target_h * overlap_fraction))
    dx_px = 0.0
    dy_px = 0.0

    if target_side == "left":
        dx_px = (tx0 + overlap_x) - ox1
    elif target_side == "right":
        dx_px = (tx1 - overlap_x) - ox0
    elif target_side == "bottom":
        dy_px = (ty1 - overlap_y) - oy0
    else:
        target_centroid = _centroid_xy(target_stats, ("centroid_px",))
        object_centroid = _centroid_xy(
            candidate_metrics,
            (
                "object_visible_centroid_px",
                "object_amodal_centroid_px",
                "object_projected_centroid_px",
            ),
        )
        if target_centroid is None or object_centroid is None:
            return ()
        dx_px = target_centroid[0] - object_centroid[0]
        dy_px = target_centroid[1] - object_centroid[1]

    du = max(-max_abs_shift_m, min(max_abs_shift_m, dx_px * m_per_u))
    # Camera-frame +v projects upward, opposite the image-row direction.
    dv = max(-max_abs_shift_m, min(max_abs_shift_m, -dy_px * m_per_v))

    depth_step = 0.0
    if depth_step_m is not None:
        depth_step = abs(float(depth_step_m))
        if not math.isfinite(depth_step):
            raise ValueError("depth_step_m must be finite")
    yaw_steps = tuple(
        abs(math.radians(float(value)))
        for value in yaw_step_degrees
    )
    if any((not math.isfinite(value)) or value <= 0.0 for value in yaw_steps):
        raise ValueError("yaw_step_degrees must contain positive finite values")

    def bounded(value):
        return max(-max_abs_shift_m, min(max_abs_shift_m, float(value)))

    raw = [
        (du, dv, 0.0, 0.0),
        (bounded(0.5 * du), bounded(0.5 * dv), 0.0, 0.0),
        (bounded(0.75 * du), bounded(0.75 * dv), 0.0, 0.0),
        (bounded(1.25 * du), bounded(1.25 * dv), 0.0, 0.0),
    ]
    if depth_step > 0.0:
        raw.extend(
            (
                (du, dv, -depth_step, 0.0),
                (du, dv, depth_step, 0.0),
            )
        )
    for yaw_step in yaw_steps:
        raw.extend(
            (
                (du, dv, 0.0, yaw_step),
                (du, dv, 0.0, -yaw_step),
            )
        )

    result = []
    for candidate in raw:
        candidate = tuple(round(float(value), 12) for value in candidate)
        if candidate == (0.0, 0.0, 0.0, 0.0) or candidate in result:
            continue
        result.append(candidate)
    return tuple(result)


def order_explicit_proposals_for_search(
    proposals,
    target_fraction=None,
    target_side=None,
):
    """Order assets for a bounded mask search without changing the proposals."""
    proposals = list(proposals)
    if not proposals:
        return []
    target = (
        None if target_fraction is None else float(target_fraction)
    )
    if target is not None and (
        not math.isfinite(target) or target < 0.0 or target > 1.0
    ):
        raise ValueError("target_fraction must be finite and in [0, 1]")
    if target_side is not None and target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder target side: {target_side!r}")

    def properties(proposal):
        dimensions = tuple(
            abs(float(value)) * abs(float(proposal.get("scale", 1.0)))
            for value in proposal["bbox_m"]
        )
        if len(dimensions) != 3 or not all(
            math.isfinite(value) and value > 0.0
            for value in dimensions
        ):
            raise ValueError("proposal bbox_m and scale must define positive dimensions")
        width, height, depth = dimensions
        fill = float(proposal.get("fill_ratio", 0.0))
        if not math.isfinite(fill) or fill < 0.0:
            raise ValueError("proposal fill_ratio must be finite and non-negative")
        footprint = width * depth
        suitable = bool(
            fill >= 0.70
            and 0.25 <= height <= 2.50
            and max(width, depth) <= 1.80
            and footprint <= 1.00
        )
        frontage = width * height * fill
        return suitable, footprint, fill, max(width, depth), frontage

    primary_suitable = properties(proposals[0])[0]
    high_lateral_target = bool(
        target is not None
        and target >= 0.25
        and target_side in {"left", "right", "center"}
    )
    high_bottom_target = bool(
        target is not None
        and target >= 0.25
        and target_side == "bottom"
    )

    def key(proposal):
        (
            suitable,
            footprint,
            fill,
            largest_ground_axis,
            frontage,
        ) = properties(proposal)
        if high_lateral_target or high_bottom_target:
            return (
                0 if suitable else 1,
                -frontage,
                footprint,
                largest_ground_axis,
                -fill,
                int(proposal.get("diagnostic_proposal_nonce", 0)),
                str(proposal.get("obj_name", "")),
            )
        return (
            0 if suitable else 1,
            footprint,
            largest_ground_axis,
            -fill,
            int(proposal.get("diagnostic_proposal_nonce", 0)),
            str(proposal.get("obj_name", "")),
        )

    original_primary_available = (
        int(proposals[0].get("diagnostic_proposal_index", 0)) == 0
    )
    if (
        high_bottom_target
        and original_primary_available
    ) or (
        primary_suitable and not high_lateral_target
    ):
        return [proposals[0], *sorted(proposals[1:], key=key)]
    return sorted(proposals, key=key)


def explicit_swept_reservation_aabb(
    aabb_min,
    aabb_max,
    horizontal_margin_m=1.5,
):
    """Return a conservative XY reservation for mask-guided occluder motion."""
    minimum = tuple(float(value) for value in aabb_min)
    maximum = tuple(float(value) for value in aabb_max)
    margin = float(horizontal_margin_m)
    if len(minimum) != 3 or len(maximum) != 3:
        raise ValueError("aabb_min and aabb_max must contain xyz")
    if not all(math.isfinite(value) for value in minimum + maximum):
        raise ValueError("reservation AABB values must be finite")
    if any(lo > hi for lo, hi in zip(minimum, maximum)):
        raise ValueError("reservation AABB minimum must not exceed maximum")
    if not math.isfinite(margin) or margin < 0.0:
        raise ValueError("horizontal_margin_m must be finite and non-negative")
    return {
        "aabb_min": [
            minimum[0] - margin,
            minimum[1] - margin,
            minimum[2],
        ],
        "aabb_max": [
            maximum[0] + margin,
            maximum[1] + margin,
            maximum[2],
        ],
        "horizontal_margin_m": margin,
    }


def procedural_support_shift(floor_mode, anchor_translation):
    """Keep a generated plane centered under the accepted anchor assembly."""
    if floor_mode != "plane":
        return (0.0, 0.0, 0.0)
    translation = tuple(float(value) for value in anchor_translation)
    if len(translation) != 3:
        raise ValueError("anchor_translation must contain xyz")
    return (translation[0], translation[1], 0.0)


def explicit_side_matches(target_side, actual_side):
    """Return whether a measured overlap belongs to the requested image side."""
    if target_side is not None and target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder target side: {target_side!r}")
    if actual_side is not None and actual_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError(f"unknown explicit occluder actual side: {actual_side!r}")
    if target_side is None:
        return True
    return actual_side == target_side


def explicit_requirement_failure(
    include_explicit,
    place_occluder,
    explicit_target,
    occluder_present,
    solver_failure,
    explicit_actual=None,
    side_target=None,
    side_actual=None,
    visible_pixels=None,
    abs_tolerance=EXPLICIT_TARGET_ABS_TOLERANCE,
):
    """Return a fail-closed reason for a required explicit occluder."""
    required = (
        bool(include_explicit)
        and bool(place_occluder)
        and float(explicit_target) > 1e-6
    )
    if not required:
        return None
    if solver_failure is not None:
        return solver_failure
    if not bool(occluder_present):
        return "explicit_occluder_missing"
    if visible_pixels is not None and int(visible_pixels) <= 0:
        return "explicit_occluder_not_visible"
    if explicit_actual is not None:
        tolerance = abs(float(abs_tolerance))
        if abs(float(explicit_actual) - float(explicit_target)) > tolerance:
            return "explicit_target_mismatch"
    if side_target is not None and not explicit_side_matches(
        side_target,
        side_actual,
    ):
        return "explicit_side_mismatch"
    return None


def constrained_hdri_paths(paths, excluded_names=()):
    """Return deterministic on-disk HDRI paths for the constrained renderer."""
    excluded = {str(name).casefold() for name in excluded_names}
    selected = {}
    for raw_path in paths:
        path = os.path.abspath(os.fspath(raw_path))
        name = os.path.basename(path)
        if name.casefold() in excluded:
            continue
        if os.path.splitext(name)[1].casefold() not in {".hdr", ".exr"}:
            continue
        if not os.path.isfile(path):
            continue
        selected.setdefault(os.path.normcase(path), path)
    return sorted(selected.values(), key=lambda path: (os.path.basename(path).casefold(), path))


def collision_action(left_role, right_role):
    """Return the broad-phase disposition for a pair of semantic roles."""
    unknown = [role for role in (left_role, right_role) if role not in CONTACT_ALLOWED]
    if unknown:
        raise ValueError(f"unknown scene role: {unknown[0]!r}")
    if CONTACT_ALLOWED[left_role][right_role]:
        return "allow_contact"
    return "reject_overlap"


def forbidden_collision_pairs(
    role_objects,
    preassembled_roles=(ROLE_SUPPORT, ROLE_STATIC_BACKGROUND),
):
    """Build dynamic-scene collision pairs from ``CONTACT_ALLOWED``.

    Intersections internal to the imported static environment are outside the
    dynamic assembler's ownership, so pairs where both roles are preassembled
    are omitted. Every other pair is governed by the declared contact matrix.
    """
    unknown = [role for role in role_objects if role not in CONTACT_ALLOWED]
    if unknown:
        raise ValueError(f"unknown scene role: {unknown[0]!r}")

    entries = []
    seen_objects = set()
    for role in ROLES:
        for obj in role_objects.get(role, ()) or ():
            if obj is None:
                continue
            object_id = id(obj)
            if object_id in seen_objects:
                raise ValueError("one object cannot have multiple scene roles")
            seen_objects.add(object_id)
            entries.append((role, obj))

    preassembled = set(preassembled_roles)
    pairs = []
    for left_index, (left_role, left_obj) in enumerate(entries):
        for right_role, right_obj in entries[left_index + 1:]:
            if left_role in preassembled and right_role in preassembled:
                continue
            if collision_action(left_role, right_role) == "reject_overlap":
                pairs.append((left_obj, right_obj))
    return pairs


def camera_clearance_for_role(role):
    """Return the constrained-scene camera clearance for one semantic role."""
    try:
        return CAMERA_CLEARANCE_BY_ROLE[role]
    except KeyError as exc:
        raise ValueError(f"unknown scene role: {role!r}") from exc


_STAGES = ("background", "anchor", "cargo", "context", "occluder")


def derive_stage_seeds(frame_seed):
    """Derive deterministic, domain-separated 64-bit seeds for frame stages."""
    if isinstance(frame_seed, bool) or not isinstance(frame_seed, int):
        raise TypeError("frame_seed must be an integer")
    encoded_seed = str(frame_seed).encode("ascii")
    return {
        stage: int.from_bytes(
            hashlib.blake2b(
                encoded_seed + b":" + stage.encode("ascii"),
                digest_size=8,
                person=b"scene-place-v2",
            ).digest(),
            "big",
        )
        for stage in _STAGES
    }


def _validated_bounds(minimum, maximum, label):
    try:
        lower = tuple(float(value) for value in minimum)
        upper = tuple(float(value) for value in maximum)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} bounds must contain three finite numbers") from exc
    if len(lower) != 3 or len(upper) != 3:
        raise ValueError(f"{label} bounds must be three-dimensional")
    if not all(math.isfinite(value) for value in lower + upper):
        raise ValueError(f"{label} bounds must be finite")
    if any(lo > hi for lo, hi in zip(lower, upper)):
        raise ValueError(f"{label} minimum exceeds maximum")
    return lower, upper


def aabb_overlap(a_min, a_max, b_min, b_max, margin=0.0):
    """Return whether two 3-D AABBs overlap within a broad-phase margin."""
    try:
        margin = float(margin)
    except (TypeError, ValueError) as exc:
        raise ValueError("margin must be a finite nonnegative number") from exc
    if not math.isfinite(margin) or margin < 0.0:
        raise ValueError("margin must be a finite nonnegative number")
    a_min, a_max = _validated_bounds(a_min, a_max, "first AABB")
    b_min, b_max = _validated_bounds(b_min, b_max, "second AABB")
    return all(
        left_max + margin >= right_min and right_max + margin >= left_min
        for left_min, left_max, right_min, right_max in zip(
            a_min, a_max, b_min, b_max
        )
    )


def compute_support_snap(
    sample_zs,
    support_zs,
    normal_zs,
    *,
    height_tolerance=0.02,
    min_abs_normal_z=0.5,
):
    """Compute a deterministic vertical snap from five support-ray hits."""
    try:
        samples = tuple(float(value) for value in sample_zs)
        supports = tuple(float(value) for value in support_zs)
        normals = tuple(float(value) for value in normal_zs)
        tolerance = float(height_tolerance)
        min_normal = float(min_abs_normal_z)
    except (TypeError, ValueError) as exc:
        raise ValueError("support snap inputs must be finite numbers") from exc
    if not samples or len(samples) != len(supports) or len(samples) != len(normals):
        raise ValueError("support snap inputs must have the same nonzero length")
    if not all(math.isfinite(value) for value in samples + supports + normals):
        raise ValueError("support snap inputs must be finite numbers")
    if tolerance < 0.0 or not math.isfinite(tolerance):
        raise ValueError("height_tolerance must be finite and nonnegative")
    if min_normal < 0.0 or min_normal > 1.0 or not math.isfinite(min_normal):
        raise ValueError("min_abs_normal_z must be in [0, 1]")
    if any(abs(normal) < min_normal for normal in normals):
        return {
            "ok": False,
            "vertical_offset": None,
            "max_height_residual": None,
            "reason": "support_normal",
        }

    offsets = sorted(support - sample for sample, support in zip(samples, supports))
    middle = len(offsets) // 2
    if len(offsets) % 2:
        vertical_offset = offsets[middle]
    else:
        vertical_offset = 0.5 * (offsets[middle - 1] + offsets[middle])
    max_residual = max(abs(offset - vertical_offset) for offset in offsets)
    if max_residual > tolerance:
        return {
            "ok": False,
            "vertical_offset": vertical_offset,
            "max_height_residual": max_residual,
            "reason": "support_height_variation",
        }
    return {
        "ok": True,
        "vertical_offset": vertical_offset,
        "max_height_residual": max_residual,
        "reason": None,
    }


_MASK_AREA_KEYS = (
    "mask_area_target_only",
    "mask_area_after_static",
    "mask_area_after_cargo",
    "mask_area_after_context",
    "mask_area_visible",
)
_MASK_FRACTION_KEYS = ("f_static", "f_cargo", "f_context", "f_explicit")
OCCLUSION_DECOMPOSITION_ORDER = ("M0", "M1", "M2", "M3", "M4")


def _finite_number(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _mask_decomposition_from_areas(areas):
    values = dict(zip(_MASK_AREA_KEYS, areas))
    base = areas[0]
    if base > 0.0:
        deltas = [max(0.0, before - after) for before, after in zip(areas, areas[1:])]
        fractions = [delta / base for delta in deltas]
    else:
        fractions = [0.0] * 4
    values.update(dict(zip(_MASK_FRACTION_KEYS, fractions)))
    values["f_total"] = sum(fractions)
    values["occlusion_decomposition_order"] = list(OCCLUSION_DECOMPOSITION_ORDER)
    return values


def validate_mask_decomposition(
    decomposition_or_m0,
    m1=None,
    m2=None,
    m3=None,
    m4=None,
    *,
    tol=1e-9,
):
    """Validate mask-area monotonicity and additive occlusion fractions."""
    try:
        tol = _finite_number(tol, "tol")
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)]}
    if tol < 0.0:
        return {"valid": False, "errors": ["tol must be nonnegative"]}

    if isinstance(decomposition_or_m0, Mapping):
        if any(value is not None for value in (m1, m2, m3, m4)):
            return {
                "valid": False,
                "errors": ["pass either a decomposition mapping or five mask areas"],
            }
        decomposition = dict(decomposition_or_m0)
    else:
        raw_areas = (decomposition_or_m0, m1, m2, m3, m4)
        try:
            areas = tuple(
                _finite_number(value, key)
                for key, value in zip(_MASK_AREA_KEYS, raw_areas)
            )
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)]}
        decomposition = _mask_decomposition_from_areas(areas)

    errors = []
    required = _MASK_AREA_KEYS + _MASK_FRACTION_KEYS + (
        "f_total",
        "occlusion_decomposition_order",
    )
    for key in required:
        if key not in decomposition:
            errors.append(f"missing required decomposition field: {key}")
        elif decomposition[key] is None:
            errors.append(f"required decomposition field is None: {key}")
    if errors:
        return {"valid": False, "errors": errors}

    try:
        areas = tuple(
            _finite_number(decomposition[key], key) for key in _MASK_AREA_KEYS
        )
        fractions = tuple(
            _finite_number(decomposition[key], key)
            for key in _MASK_FRACTION_KEYS
        )
        f_total = _finite_number(decomposition["f_total"], "f_total")
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)]}

    if areas[0] <= tol:
        errors.append("mask_area_target_only must be greater than tol")
    if any(area < -tol for area in areas):
        errors.append("mask areas must be nonnegative")
    if any(after > before + tol for before, after in zip(areas, areas[1:])):
        errors.append("mask areas must be monotonic M0 >= M1 >= M2 >= M3 >= M4")
    if any(fraction < -tol for fraction in fractions) or f_total < -tol:
        errors.append("occlusion fractions must be nonnegative")

    if areas[0] > tol:
        expected = tuple(
            max(0.0, before - after) / areas[0]
            for before, after in zip(areas, areas[1:])
        )
        for key, actual, wanted in zip(_MASK_FRACTION_KEYS, fractions, expected):
            if not math.isclose(actual, wanted, rel_tol=0.0, abs_tol=tol):
                errors.append(f"{key} does not match its adjacent mask areas")
        direct_total = max(0.0, areas[0] - areas[-1]) / areas[0]
        if not math.isclose(f_total, direct_total, rel_tol=0.0, abs_tol=tol):
            errors.append("f_total does not match M0-to-M4 area loss")

    if not math.isclose(sum(fractions), f_total, rel_tol=0.0, abs_tol=tol):
        errors.append("occlusion component sum does not equal f_total")
    order = decomposition["occlusion_decomposition_order"]
    try:
        order = list(order)
    except TypeError:
        order = None
    if order != list(OCCLUSION_DECOMPOSITION_ORDER):
        errors.append("occlusion_decomposition_order must be M0 through M4")
    return {"valid": not errors, "errors": errors}


def decompose_mask_areas(m0, m1, m2, m3, m4, tol=1e-9):
    """Return the additive M0..M4 occlusion decomposition as flat metadata."""
    areas = tuple(
        _finite_number(value, key)
        for key, value in zip(_MASK_AREA_KEYS, (m0, m1, m2, m3, m4))
    )
    result = _mask_decomposition_from_areas(areas)
    report = validate_mask_decomposition(result, tol=tol)
    if not report["valid"]:
        raise ValueError("; ".join(report["errors"]))
    return result


@dataclass(frozen=True)
class DiagnosticPolicy:
    """Role switches for one diagnostic scene mode."""

    mode: str
    cargo_mode: str
    include_context: bool
    include_explicit_occluder: bool

    @property
    def include_cargo(self):
        return {"off": False, "force_on": True, "spec": None}[self.cargo_mode]

    @property
    def allowed_roles(self):
        roles = ["pallet", "support", "static_background"]
        if self.cargo_mode != "off":
            roles.append("cargo")
        if self.include_context:
            roles.append("context")
        if self.include_explicit_occluder:
            roles.append("explicit_occluder")
        return tuple(roles)

    def as_dict(self):
        return {
            "mode": self.mode,
            "cargo_mode": self.cargo_mode,
            "include_cargo": self.include_cargo,
            "include_context": self.include_context,
            "include_explicit_occluder": self.include_explicit_occluder,
            "allowed_roles": list(self.allowed_roles),
        }


_DIAGNOSTIC_POLICIES = {
    "clean-static": DiagnosticPolicy("clean-static", "off", False, False),
    "cargo-only": DiagnosticPolicy("cargo-only", "force_on", False, False),
    "context-rich": DiagnosticPolicy("context-rich", "spec", True, False),
    "controlled-occlusion": DiagnosticPolicy(
        "controlled-occlusion", "spec", True, True
    ),
}


def diagnostic_policy(mode):
    """Return the role policy for a diagnostic mode, without runner quotas."""
    try:
        return _DIAGNOSTIC_POLICIES[mode]
    except (KeyError, TypeError) as exc:
        choices = ", ".join(_DIAGNOSTIC_POLICIES)
        raise ValueError(f"unknown diagnostic mode {mode!r}; expected one of {choices}") from exc


_ASSET_ID_FIELDS = ("asset_id", "id", "name", "path", "source_asset")


def _asset_aliases(asset):
    if isinstance(asset, Mapping):
        aliases = {
            str(asset[key])
            for key in _ASSET_ID_FIELDS
            if key in asset and asset[key] is not None
        }
    elif isinstance(asset, (str, bytes)):
        aliases = {asset.decode() if isinstance(asset, bytes) else asset}
    else:
        aliases = set()
    if not aliases:
        raise ValueError(
            "each asset must be a string or mapping with an identity field"
        )
    return frozenset(aliases)


def _asset_candidates(values):
    if isinstance(values, (Mapping, str, bytes)):
        return [values]
    try:
        return list(values)
    except TypeError as exc:
        raise ValueError("asset candidates must be iterable") from exc


def _asset_role_pools(context_candidates, explicit_candidates):
    components = []
    tagged_assets = [
        ("context", asset) for asset in _asset_candidates(context_candidates)
    ]
    tagged_assets.extend(
        ("explicit_occluder", asset)
        for asset in _asset_candidates(explicit_candidates)
    )
    for role, asset in tagged_assets:
        aliases = set(_asset_aliases(asset))
        matching = [
            index
            for index, component in enumerate(components)
            if not aliases.isdisjoint(component["aliases"])
        ]
        if not matching:
            components.append(
                {"aliases": aliases, "records": [(role, asset)]}
            )
            continue
        first = matching[0]
        records = []
        for index in matching:
            aliases.update(components[index]["aliases"])
            records.extend(components[index]["records"])
        records.append((role, asset))
        components[first] = {"aliases": aliases, "records": records}
        for index in reversed(matching[1:]):
            del components[index]

    pools = {"context": [], "explicit_occluder": []}
    for component in components:
        aliases = frozenset(component["aliases"])
        represented_roles = set()
        for role, asset in component["records"]:
            if role not in represented_roles:
                pools[role].append((asset, aliases))
                represented_roles.add(role)
    return pools


def _asset_rank(seed, role, aliases):
    payload = f"{seed}:{role}:{'|'.join(sorted(aliases))}".encode("utf-8")
    return hashlib.sha256(payload).digest()


def choose_disjoint_assets(
    context_candidates,
    explicit_candidates,
    context_count,
    seed,
):
    """Choose deterministic context and explicit assets with no shared identity."""
    if isinstance(context_count, bool) or not isinstance(context_count, int):
        raise TypeError("context_count must be an integer")
    if context_count < 0:
        raise ValueError("context_count must be nonnegative")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")

    pools = _asset_role_pools(context_candidates, explicit_candidates)
    explicit_pool = pools["explicit_occluder"]
    if not explicit_pool:
        raise ValueError("at least one explicit occluder candidate is required")
    explicit_pool.sort(
        key=lambda item: _asset_rank(seed, "explicit_occluder", item[1])
    )
    all_context = pools["context"]
    selection = None
    for explicit_asset, explicit_aliases in explicit_pool:
        context_pool = [
            item for item in all_context if item[1].isdisjoint(explicit_aliases)
        ]
        if len(context_pool) >= context_count:
            selection = explicit_asset, context_pool
            break
    if selection is None:
        raise ValueError(
            "not enough context candidates remain after excluding the explicit occluder"
        )
    explicit_asset, context_pool = selection
    context_pool.sort(key=lambda item: _asset_rank(seed, "context", item[1]))
    return {
        "context": [asset for asset, _ in context_pool[:context_count]],
        "explicit_occluder": explicit_asset,
    }


REQUIRED_METADATA_FIELDS = {
    "anchor": (
        "anchor_translation",
        "anchor_attempts",
        "anchor_reject_counts_by_reason",
        "support_surface_name",
        "min_camera_clearance",
        "static_collision_pass",
        "static_los_pass",
    ),
    "collision": (
        "tested_collision_pairs",
        "broad_phase_hits",
        "exact_collision_hits",
        "collision_reject_reason",
        "context_context_collision_count",
        "cargo_collision_count",
        "pallet_obstacle_collision_count",
    ),
    "context": (
        "n_context_placed",
        "n_context_visible",
        "context_visible_pixel_ratio",
        "context_screen_area_ratio",
        "f_context",
        "context_placement_attempts",
        "context_reject_counts_by_reason",
    ),
    "cargo": (
        "n_cargo_requested",
        "n_cargo_placed",
        "cargo_placement_attempts",
        "cargo_support_pass",
        "cargo_collision_pass",
        "f_cargo",
        "front_visibility_after_cargo",
        "left_opening_visibility_after_cargo",
        "right_opening_visibility_after_cargo",
    ),
    "explicit": (
        "f_explicit_target",
        "f_explicit_actual",
        "explicit_abs_error",
        "occluder_feedback_iterations",
        "occluder_side_target",
        "occluder_side_actual",
        "explicit_occluder_visible_pixels",
        "explicit_collision_pass",
        "explicit_solver_fail_reason",
    ),
    "mask": (
        "mask_area_target_only",
        "mask_area_after_static",
        "mask_area_after_cargo",
        "mask_area_after_context",
        "mask_area_visible",
        "f_static",
        "f_cargo",
        "f_context",
        "f_explicit",
        "f_total",
        "occlusion_decomposition_order",
        "front_face_visibility",
        "left_opening_visibility",
        "right_opening_visibility",
    ),
}

_NULLABLE_METADATA_FIELDS = {
    "collision_reject_reason",
    "explicit_solver_fail_reason",
}
_OPENING_VISIBILITY_FIELDS = {
    "front_visibility_after_cargo",
    "left_opening_visibility_after_cargo",
    "right_opening_visibility_after_cargo",
    "front_face_visibility",
    "left_opening_visibility",
    "right_opening_visibility",
}
_GROUP_ALIASES = {"explicit_occluder": "explicit", "masks": "mask"}


def validate_constrained_metadata(metadata, groups=None):
    """Validate required additive fields for completed assembly stages."""
    if groups is None:
        groups = tuple(REQUIRED_METADATA_FIELDS)
    elif isinstance(groups, str):
        groups = (groups,)
    else:
        groups = tuple(groups)
    groups = tuple(_GROUP_ALIASES.get(group, group) for group in groups)
    unknown = [group for group in groups if group not in REQUIRED_METADATA_FIELDS]
    if unknown:
        raise ValueError(f"unknown metadata group: {unknown[0]!r}")

    if not isinstance(metadata, Mapping):
        return {
            "valid": False,
            "errors": ["metadata must be a mapping"],
            "missing": [],
            "none": [],
            "groups": list(groups),
        }

    required = []
    for group in groups:
        for field in REQUIRED_METADATA_FIELDS[group]:
            if field not in required:
                required.append(field)

    missing = [field for field in required if field not in metadata]
    none_fields = [
        field
        for field in required
        if field in metadata
        and metadata[field] is None
        and field not in _NULLABLE_METADATA_FIELDS
        and field not in _OPENING_VISIBILITY_FIELDS
    ]
    errors = [f"missing required metadata field: {field}" for field in missing]
    errors.extend(
        f"required metadata field is None: {field}" for field in none_fields
    )

    unavailable_visibility = [
        field
        for field in required
        if field in _OPENING_VISIBILITY_FIELDS
        and field in metadata
        and metadata[field] is None
    ]
    if unavailable_visibility:
        reason = metadata.get("opening_visibility_reason")
        if not isinstance(reason, str) or not reason.strip():
            names = ", ".join(unavailable_visibility)
            errors.append(
                "opening_visibility_reason is required when visibility is None: "
                + names
            )

    if "mask" in groups:
        decomposition_fields = (
            _MASK_AREA_KEYS
            + _MASK_FRACTION_KEYS
            + ("f_total", "occlusion_decomposition_order")
        )
        if all(
            field in metadata and metadata[field] is not None
            for field in decomposition_fields
        ):
            decomposition_report = validate_mask_decomposition(metadata)
            errors.extend(
                f"mask decomposition: {error}"
                for error in decomposition_report["errors"]
            )

    return {
        "valid": not errors,
        "errors": errors,
        "missing": missing,
        "none": none_fields,
        "groups": list(groups),
    }
