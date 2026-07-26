"""Distractor placement and camera sampling helpers for Isaac Sim synthetic data."""

import numpy as np

from sdg_config import (
    CAMERA_CONSTRAINTS,
    CAMERA_MODE_B,
    CAMERA_MODE_PROBS,
    CARGO_OCCLUSION_TIERS,
    CARGO_ON_PALLET_PROBABILITY,
    CARGO_Z_CLEARANCE,
    DISTRACTOR_ACTIVE_COUNT_MIN,
    DISTRACTOR_CARGO_LOCAL_FRACTION,
    DISTRACTOR_CARGO_PRIMITIVE_Z_SCALE_RANGE,
    DISTRACTOR_CARGO_ROTATION_RANGE,
    DISTRACTOR_DEFAULT_HALF_EXTENTS,
    DISTRACTOR_FLOOR_ROTATION_RANGE,
    DISTRACTOR_FLOOR_SAMPLING,
    DISTRACTOR_PRIMITIVE_COLOR_RANGES,
    DISTRACTOR_PRIMITIVE_SCALE_RANGES,
    DISTRACTOR_PROP_SCALE_RANGE,
    FRONT_VIEW_CONSTRAINTS,
    LOOK_AT_JITTER,
    MAX_DISTRACTORS_PER_FRAME,
)
from sdg_usd_xform import _apply_distractor_color, _set_pose_usd_rep


def _select_camera_mode(rng):
    """Pick one of the configured camera modes."""
    r = rng.random()
    if r < CAMERA_MODE_PROBS[0]:
        return "A"
    if r < CAMERA_MODE_PROBS[0] + CAMERA_MODE_PROBS[1]:
        return "B"
    return "C"


def _sample_camera_pose(rng, pallet_pos=(0, 0, 0), front_view=False):
    """Sample camera position around the pallet using configured mode constraints."""
    if front_view:
        cc = FRONT_VIEW_CONSTRAINTS
    else:
        mode = _select_camera_mode(rng)
        if mode == "A":
            cc = CAMERA_CONSTRAINTS
        elif mode == "B":
            cc = CAMERA_MODE_B
        else:
            cc = FRONT_VIEW_CONSTRAINTS

    distance = float(rng.uniform(cc["distance_min"], cc["distance_max"]))
    height = float(rng.uniform(cc["height_min"], cc["height_max"]))
    yaw_deg = float(rng.uniform(cc["yaw_min"], cc["yaw_max"]))
    yaw_rad = np.radians(yaw_deg)

    cam_x = float(pallet_pos[0]) + distance * np.cos(yaw_rad)
    cam_y = float(pallet_pos[1]) + distance * np.sin(yaw_rad)
    cam_z = height
    return (cam_x, cam_y, cam_z)


def _jitter_look_at(rng, base_target):
    return (
        base_target[0] + float(rng.uniform(-LOOK_AT_JITTER, LOOK_AT_JITTER)),
        base_target[1] + float(rng.uniform(-LOOK_AT_JITTER, LOOK_AT_JITTER)),
        base_target[2] + float(rng.uniform(-LOOK_AT_JITTER * 0.5, LOOK_AT_JITTER * 0.5)),
    )


def _sample_floor_distractor_pos(rng, pallet_pos, cam_pos, max_attempts=None):
    """Sample floor distractors while avoiding the camera-to-pallet sight corridor."""
    if max_attempts is None:
        max_attempts = DISTRACTOR_FLOOR_SAMPLING["max_attempts"]
    corridor_half_width = DISTRACTOR_FLOOR_SAMPLING["corridor_half_width"]
    xy_min, xy_max = DISTRACTOR_FLOOR_SAMPLING["xy_range"]
    z_min, z_max = DISTRACTOR_FLOOR_SAMPLING["z_range"]

    for _ in range(max_attempts):
        x = float(rng.uniform(xy_min, xy_max))
        y = float(rng.uniform(xy_min, xy_max))
        if cam_pos is not None and pallet_pos is not None:
            cx, cy = cam_pos[0], cam_pos[1]
            px, py = pallet_pos[0], pallet_pos[1]
            dx, dy = px - cx, py - cy
            seg_len = np.sqrt(dx * dx + dy * dy)
            if seg_len > 0.01:
                tx = x - cx
                ty = y - cy
                t_proj = (tx * dx + ty * dy) / (seg_len * seg_len)
                if 0.0 < t_proj < 1.0:
                    perp_x = tx - t_proj * dx
                    perp_y = ty - t_proj * dy
                    perp_dist = np.sqrt(perp_x * perp_x + perp_y * perp_y)
                    if perp_dist < corridor_half_width:
                        continue
        return (x, y, float(rng.uniform(z_min, z_max)))

    if cam_pos is not None and pallet_pos is not None:
        cx, cy = cam_pos[0], cam_pos[1]
        px, py = pallet_pos[0], pallet_pos[1]
        away_mul = DISTRACTOR_FLOOR_SAMPLING["fallback_away_multiplier"]
        jitter_min, jitter_max = DISTRACTOR_FLOOR_SAMPLING["fallback_jitter_xy"]
        away_x = px + (px - cx) * away_mul + float(rng.uniform(jitter_min, jitter_max))
        away_y = py + (py - cy) * away_mul + float(rng.uniform(jitter_min, jitter_max))
        return (away_x, away_y, float(rng.uniform(z_min, z_max)))

    return (
        float(rng.uniform(xy_min, xy_max)),
        float(rng.uniform(xy_min, xy_max)),
        float(rng.uniform(z_min, z_max)),
    )


def _randomize_distractors(
    rng,
    distractor_prims,
    stage,
    use_props=False,
    pallet_pos=None,
    pallet_yaw_deg=0.0,
    pallet_half_extents=DISTRACTOR_DEFAULT_HALF_EXTENTS,
    distractor_sizes=None,
    cam_pos=None,
    distractor_shader_cache=None,
):
    """Randomize distractors on the floor and optionally on top of the pallet."""
    pool_size = len(distractor_prims)
    num_active = int(
        rng.integers(
            DISTRACTOR_ACTIVE_COUNT_MIN,
            min(MAX_DISTRACTORS_PER_FRAME, pool_size) + 1,
        )
    )
    active_indices = list(rng.choice(pool_size, size=num_active, replace=False))

    on_pallet_indices = set()
    cargo_scale_range = (0.15, 0.30)
    if pallet_pos and float(rng.random()) < CARGO_ON_PALLET_PROBABILITY:
        r = float(rng.random())
        cumul = 0.0
        num_on_pallet = 1
        for prob, max_count, scale_range in CARGO_OCCLUSION_TIERS:
            cumul += prob
            if r < cumul:
                num_on_pallet = int(rng.integers(1, max_count + 1))
                cargo_scale_range = scale_range
                break
        num_on_pallet = min(num_on_pallet, len(active_indices))
        on_pallet_indices = set(active_indices[:num_on_pallet])
    active_indices = set(active_indices)

    for i, distractor in enumerate(distractor_prims):
        if i not in active_indices:
            _set_pose_usd_rep(stage, distractor, position=(0, 0, -200))
            continue

        if i in on_pallet_indices and pallet_pos:
            cargo_z = pallet_pos[2] + CARGO_Z_CLEARANCE
            hx, hz = pallet_half_extents
            local_dx = float(
                rng.uniform(
                    -hx * DISTRACTOR_CARGO_LOCAL_FRACTION,
                    hx * DISTRACTOR_CARGO_LOCAL_FRACTION,
                )
            )
            local_dy = float(
                rng.uniform(
                    -hz * DISTRACTOR_CARGO_LOCAL_FRACTION,
                    hz * DISTRACTOR_CARGO_LOCAL_FRACTION,
                )
            )
            yaw_rad = np.radians(pallet_yaw_deg)
            cos_y, sin_y = np.cos(yaw_rad), np.sin(yaw_rad)
            world_dx = cos_y * local_dx - sin_y * local_dy
            world_dy = sin_y * local_dx + cos_y * local_dy
            pos = (
                pallet_pos[0] + world_dx,
                pallet_pos[1] + world_dy,
                cargo_z,
            )

            target_min, target_max = cargo_scale_range
            target_size = float(rng.uniform(target_min, target_max))
            orig_dim = distractor_sizes[i] if distractor_sizes and i < len(distractor_sizes) else 0.5
            cargo_sc = np.clip(target_size / orig_dim, 0.05, 3.0)
            cargo_rot = (
                float(rng.uniform(*DISTRACTOR_CARGO_ROTATION_RANGE["x"])),
                float(rng.uniform(*DISTRACTOR_CARGO_ROTATION_RANGE["y"])),
                float(rng.uniform(*DISTRACTOR_CARGO_ROTATION_RANGE["z"])),
            )
            if use_props:
                _set_pose_usd_rep(
                    stage,
                    distractor,
                    position=pos,
                    rotation_deg=cargo_rot,
                    scale=(cargo_sc, cargo_sc, cargo_sc),
                )
            else:
                sc_var = float(rng.uniform(*DISTRACTOR_CARGO_PRIMITIVE_Z_SCALE_RANGE))
                _set_pose_usd_rep(
                    stage,
                    distractor,
                    position=pos,
                    rotation_deg=cargo_rot,
                    scale=(cargo_sc, cargo_sc, cargo_sc * sc_var),
                )
            print(
                f"    [CARGO] distractor {i} ON pallet target={target_size:.2f}m "
                f"orig={orig_dim:.2f}m sc={cargo_sc:.2f} z={cargo_z:.2f}"
            )
            continue

        pos = _sample_floor_distractor_pos(rng, pallet_pos, cam_pos)
        floor_rot = (
            float(rng.uniform(*DISTRACTOR_FLOOR_ROTATION_RANGE["x"])),
            float(rng.uniform(*DISTRACTOR_FLOOR_ROTATION_RANGE["y"])),
            float(rng.uniform(*DISTRACTOR_FLOOR_ROTATION_RANGE["z"])),
        )
        if use_props:
            sc = float(rng.uniform(*DISTRACTOR_PROP_SCALE_RANGE))
            _set_pose_usd_rep(stage, distractor, position=pos, rotation_deg=floor_rot, scale=(sc, sc, sc))
            continue

        sx = float(rng.uniform(*DISTRACTOR_PRIMITIVE_SCALE_RANGES["x"]))
        sy = float(rng.uniform(*DISTRACTOR_PRIMITIVE_SCALE_RANGES["y"]))
        sz = float(rng.uniform(*DISTRACTOR_PRIMITIVE_SCALE_RANGES["z"]))
        _set_pose_usd_rep(stage, distractor, position=pos, rotation_deg=floor_rot, scale=(sx, sy, sz))

        palette_type = rng.choice(["cardboard", "plastic", "concrete", "metal"])
        if palette_type == "cardboard":
            spec = DISTRACTOR_PRIMITIVE_COLOR_RANGES["cardboard"]
            color = tuple(float(rng.uniform(spec["min"][axis], spec["max"][axis])) for axis in range(3))
        elif palette_type == "plastic":
            spec = DISTRACTOR_PRIMITIVE_COLOR_RANGES["plastic"]
            color = tuple(float(rng.uniform(spec["min"][axis], spec["max"][axis])) for axis in range(3))
        elif palette_type == "concrete":
            spec = DISTRACTOR_PRIMITIVE_COLOR_RANGES["concrete"]
            base = float(rng.uniform(*spec["base"]))
            color = (
                base,
                base * float(rng.uniform(*spec["g_multiplier"])),
                base * float(rng.uniform(*spec["b_multiplier"])),
            )
        else:
            spec = DISTRACTOR_PRIMITIVE_COLOR_RANGES["metal"]
            base = float(rng.uniform(*spec["base"]))
            color = (base, base, base * float(rng.uniform(*spec["b_multiplier"])))
        _apply_distractor_color(stage, i, color, distractor_shader_cache, rng=rng)
