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


# ---------------------------------------------------------------------------
# §3 target-seed bounded free allowance · §4 near-miss fine refinement
# ---------------------------------------------------------------------------
# G1.5 는 해석적 seed 단계(target-seed)를 후보 예산에서 **전부** 뺐다.  그래야
# accepted recall 이 30/30 이 됐지만, 대신 실패 프레임이 후보를 더 많이 평가하게 됐다
# (score_callback reject +28.8%).  여기서는 **앞 K개 unique 후보만** free 로 두고
# 나머지는 일반 예산을 쓰게 한다.  K=None 이면 G1.5 동작(무제한)과 같다.
TARGET_SEED_STAGE = "target-seed"
FINE_STAGE = "fine"
FINE_MAX_EVALS = 8
FINE_STEP_SCALE = 0.5          # coarse step 의 절반 — 새 절대 단위를 만들지 않는다

# --- G1.7 constraint-directed rescue ------------------------------------
# schedule 에 이미 "rescue" 라는 coarse sweep stage 가 있으므로 이름을 분리한다.
CONSTRAINT_RESCUE_STAGE = "constraint-rescue"
CONSTRAINT_RESCUE_MODES = ("off", "side_g1")
CONSTRAINT_RESCUE_DEFAULT_MODE = "off"      # §5 production default 는 OFF
RESCUE_BEAM_MAX = 3
RESCUE_EVAL_MAX_PER_CASE = 8
RESCUE_EVAL_MAX_PER_CATEGORY = 4
RESCUE_HARD_REASONS = ("support", "collision", "camera_clearance")
# acceptance 계약 (v2_realize.py:1838-1843 에서 읽은 값)
ACCEPTANCE_MIN_VISIBLE_PIXELS = 8
G1_MIN_V_VIS = 4
G2_MIN_EXT_OCC = 1
G2_MAX_EXT_OCC = 4
ACCEPTANCE_CONSTRAINTS = ("side", "visibility", "target", "G1", "G2")


def candidate_geometry_key(candidate):
    """같은 배치를 stage 이름만 바꿔 재평가한 것을 하나로 세기 위한 canonical key."""
    center = candidate.get("center") or ()
    parts = [str(candidate.get("proposal_object"))]
    parts += ["%.6f" % float(value) for value in center]
    for key in ("yaw_rad", "u_offset", "v_offset", "depth_offset", "yaw_offset"):
        value = candidate.get(key)
        parts.append("na" if value is None else "%.6f" % float(value))
    return "|".join(parts)


def planned_offset_key(plan, offset):
    """평가 **전에** 계산되는 dedup key: 같은 plan 에 같은 offset 이면 결과도 같다.

    `candidate_geometry_key` 는 배치 결과(center)가 있어야 하므로 이미 평가한
    후보끼리만 비교할 수 있다.  탐색 단계는 (plan, offset) 만으로 결과가 결정되므로
    그 쌍을 키로 쓰면 **평가하기 전에** 중복을 걸러낼 수 있다.  primary 격자의
    (0,0,0) 은 preprobe 와 같은 지점이라 실측 후보의 5.2% 가 재평가였다.
    """
    center = tuple(float(v) for v in (plan.get("center") or ()))
    yaw = plan.get("yaw_rad")
    values = tuple(float(v) for v in offset)
    return (
        str(plan.get("obj_name")),
        center,
        "na" if yaw is None else round(float(yaw), 9),
        tuple(round(v, 9) for v in values),
    )


def dedup_candidate_offsets(plan, offsets, evaluated_keys):
    """이미 평가한 (plan, offset) 조합을 뺀 나머지와, 그 키들을 함께 돌려준다.

    호출자는 **실제로 평가한 offset 의 키만** `evaluated_keys` 에 넣어야 한다
    (예산에 잘려 평가되지 않은 것을 넣으면 다음 단계에서 잘못 건너뛴다).
    """
    kept, keys = [], []
    seen = set()
    for offset in offsets:
        key = planned_offset_key(plan, offset)
        if key in evaluated_keys or key in seen:
            continue
        seen.add(key)
        kept.append(tuple(float(v) for v in offset))
        keys.append(key)
    return tuple(kept), tuple(keys)


def candidate_constraint_vector(candidate, order=None):
    """§6 constraint vector.  측정 안 된 값은 None 이며 절대 pass 로 세지 않는다."""
    reason = candidate.get("reason")
    visible = candidate.get("object_visible_pixels")
    error = candidate.get("abs_error")
    v_vis = candidate.get("candidate_V_vis")
    ext = candidate.get("candidate_ext_occ_corners")
    side = candidate.get("occluder_side_match")
    vector = {
        "hard_physical_pass": reason not in RESCUE_HARD_REASONS,
        "side_pass": None if side is None else bool(side),
        "visibility_margin_px": (None if visible is None
                                 else int(visible) - ACCEPTANCE_MIN_VISIBLE_PIXELS),
        "target_margin": (None if error is None
                          else EXPLICIT_TARGET_ABS_TOLERANCE - float(error)),
        "G1_margin": None if v_vis is None else int(v_vis) - G1_MIN_V_VIS,
        "G2_margin": (None if ext is None
                      else min(int(ext) - G2_MIN_EXT_OCC,
                               G2_MAX_EXT_OCC - int(ext))),
        "existing_score": candidate.get("score"),
        "original_candidate_order": order,
    }
    vector["G1_pass"] = (None if vector["G1_margin"] is None
                         else vector["G1_margin"] >= 0)
    vector["G2_pass"] = (None if vector["G2_margin"] is None
                         else vector["G2_margin"] >= 0)
    vector["visibility_pass"] = (None if vector["visibility_margin_px"] is None
                                 else vector["visibility_margin_px"] >= 0)
    vector["target_pass"] = (None if vector["target_margin"] is None
                             else vector["target_margin"] >= 0)
    violated, unknown = [], []
    for name in ACCEPTANCE_CONSTRAINTS:
        value = vector["side_pass" if name == "side" else name + "_pass"]
        if value is None:
            unknown.append(name)
        elif not value:
            violated.append(name)
    vector["violated"] = tuple(violated)
    vector["unknown"] = tuple(unknown)
    vector["violation_count"] = None if unknown else len(violated)
    vector["acceptance_pass_count"] = len(ACCEPTANCE_CONSTRAINTS) - len(
        violated) - len(unknown)
    vector["accepted"] = bool(not violated and not unknown)
    return vector


def _constraint_axis_values(vector):
    """dominance 비교에 쓰는 (boolean, continuous) 축.  None 은 비교 불가."""
    return (
        ("side", "boolean", vector["side_pass"]),
        ("visibility", "continuous", vector["visibility_margin_px"]),
        ("target", "continuous", vector["target_margin"]),
        ("G1", "continuous", vector["G1_margin"]),
        ("G2", "continuous", vector["G2_margin"]),
    )


def constraint_vector_dominates(a, b):
    """A 가 B 를 Pareto dominate 하는가 (§6).

    - 모든 acceptance 축에서 같거나 낫고, 최소 하나에서 더 나아야 한다.
    - boolean 은 pass 가 fail 을 dominate 한다.
    - 어느 한쪽이라도 축이 미측정(None)이면 그 축은 비교할 수 없으므로
      dominance 를 주장하지 않는다 (보수적).
    - hard physical fail 은 어떤 후보도 dominate 하지 못한다.
    """
    if not a.get("hard_physical_pass"):
        return False
    strictly_better = False
    for (_name, kind, va), (_n2, _k2, vb) in zip(_constraint_axis_values(a),
                                                 _constraint_axis_values(b)):
        if va is None or vb is None:
            return False
        if kind == "boolean":
            if int(bool(va)) < int(bool(vb)):
                return False
            if int(bool(va)) > int(bool(vb)):
                strictly_better = True
        else:
            # margin 은 0 이상이면 이미 통과다.  통과분끼리는 더 큰 margin 을
            # "더 낫다"로 세지 않는다 — 그러면 통과한 축을 계속 밀어붙여
            # 다른 축을 희생하는 후보가 선택된다.
            ca, cb = min(float(va), 0.0), min(float(vb), 0.0)
            if ca < cb:
                return False
            if ca > cb:
                strictly_better = True
    return strictly_better


def pareto_non_dominated(vectors):
    """hard physical pass 후보 중 non-dominated 집합 (입력 순서 보존)."""
    live = [v for v in vectors if v.get("hard_physical_pass")]
    keep = []
    for i, cand in enumerate(live):
        if any(constraint_vector_dominates(other, cand)
               for j, other in enumerate(live) if j != i):
            continue
        keep.append(cand)
    return keep


def _rescue_tie_key(vector):
    """§6 동률 순서: pass 수 → binding margin → score → 원래 순서 → asset."""
    margins = [m for m in (vector["visibility_margin_px"], vector["target_margin"],
                           vector["G1_margin"], vector["G2_margin"])
               if m is not None]
    binding = min((min(float(m), 0.0) for m in margins), default=-99.0)
    return (
        -int(vector["acceptance_pass_count"]),
        -float(binding),
        -float(vector["existing_score"] if vector["existing_score"] is not None
               else -99.0),
        int(vector["original_candidate_order"]
            if vector["original_candidate_order"] is not None else 1 << 30),
        str(vector.get("asset") or ""),
    )


def rescue_beam(candidate_log, categories=("side", "G1"),
                beam_max=RESCUE_BEAM_MAX):
    """§6 beam: global best 1 + category champion 각 1, 중복 geometry 제거 후 <=3.

    champion = 그 category 만 위반하고 나머지는 통과한 후보 중 최선.
    없으면 그 category 를 위반하되 위반 수가 가장 적은 후보.
    """
    vectors, seen = [], set()
    for order, candidate in enumerate(candidate_log):
        key = candidate_geometry_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        vector = candidate_constraint_vector(candidate, order=order)
        if not vector["hard_physical_pass"]:
            continue
        vector["geometry_key"] = key
        vector["candidate"] = candidate
        vector["asset"] = candidate.get("proposal_object")
        vectors.append(vector)
    if not vectors:
        return []
    frontier = pareto_non_dominated(vectors)
    pool = frontier or vectors

    beam, used = [], set()

    def take(vector, role):
        if vector is None or vector["geometry_key"] in used:
            return
        used.add(vector["geometry_key"])
        entry = dict(vector)
        entry["beam_role"] = role
        beam.append(entry)

    scored = [v for v in pool if v["existing_score"] is not None]
    take(min(scored or pool, key=_rescue_tie_key) if (scored or pool) else None,
         "global_best")
    for name in categories:
        solo = [v for v in pool
                if v["violation_count"] is not None
                and v["violated"] == (name,)]
        champions = solo or [v for v in pool
                             if v["violation_count"] is not None
                             and name in v["violated"]]
        if champions:
            take(min(champions, key=_rescue_tie_key), "%s_champion" % name)
    return beam[:int(beam_max)]


def side_region_bounds(target_bbox_px):
    """`_occlusion_side_from_masks` 와 **같은** 삼등분 경계 (v2_realize.py:3530)."""
    x0, y0, x1, y1 = (float(v) for v in target_bbox_px)
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "left_max": x0 + width / 3.0,
            "right_min": x0 + 2.0 * width / 3.0,
            "bottom_min": y0 + 2.0 * height / 3.0,
            "width": width, "height": height}


def side_target_point(target_bbox_px, target_side):
    """target side 로 판정되려면 가림 centroid 가 있어야 할 대표 지점.

    판정 순서가 bottom -> left -> right -> center 이므로, left/right 를 얻으려면
    bottom 경계보다 **위**에 있어야 한다 (그 조건을 먼저 만족시킨다).
    """
    if target_side not in EXPLICIT_OCCLUDER_SIDES:
        raise ValueError("unknown target side: %r" % (target_side,))
    b = side_region_bounds(target_bbox_px)
    mid_y = 0.5 * (b["y0"] + b["bottom_min"])       # bottom 밴드 위쪽 중앙
    if target_side == "bottom":
        return (0.5 * (b["x0"] + b["x1"]),
                0.5 * (b["bottom_min"] + b["y1"]))
    if target_side == "left":
        return (0.5 * (b["x0"] + b["left_max"]), mid_y)
    if target_side == "right":
        return (0.5 * (b["right_min"] + b["x1"]), mid_y)
    return (0.5 * (b["x0"] + b["x1"]), mid_y)       # center


def screen_axis_sensitivity(candidate_log, offset_key, screen_index):
    """이미 평가된 후보들로부터 d(screen px)/d(offset) 을 실측한다.

    이름이나 부호 규약을 추측하지 않는다 (§16).  같은 proposal 안에서 해당 축만
    다른 후보 쌍의 유한차분 중앙값을 쓴다.  쌍이 없으면 None.
    """
    others = ("u_offset", "v_offset", "depth_offset", "yaw_offset")
    points = []
    for candidate in candidate_log:
        centroid = candidate.get("object_visible_centroid_px")
        if not centroid or candidate.get(offset_key) is None:
            continue
        rest = tuple((k, candidate.get(k)) for k in others if k != offset_key)
        points.append((rest, float(candidate[offset_key]),
                       float(centroid[int(screen_index)]),
                       candidate.get("proposal_object")))
    slopes = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            rest_a, xa, ya, asset_a = points[i]
            rest_b, xb, yb, asset_b = points[j]
            if rest_a != rest_b or asset_a != asset_b:
                continue
            if abs(xa - xb) < 1e-9:
                continue
            slopes.append((ya - yb) / (xa - xb))
    if not slopes:
        return None
    slopes.sort()
    mid = len(slopes) // 2
    return (slopes[mid] if len(slopes) % 2
            else 0.5 * (slopes[mid - 1] + slopes[mid]))


def side_rescue_seeds(beam_entry, target_bbox_px, target_side, candidate_log,
                      coarse_u_step, coarse_v_step, max_seeds=4):
    """§7 SIDE discrete reseed — 최대 4개, 전부 실측 기하에서 결정적으로 만든다.

    임의 연속 margin 을 만들지 않는다.  seed 는 출발점일 뿐이고 성공 판정은
    항상 5개 acceptance 조건 실측으로 한다.
    """
    candidate = beam_entry["candidate"]
    centroid = candidate.get("object_visible_centroid_px")
    if not centroid or target_bbox_px is None:
        return ()
    u0 = float(candidate.get("u_offset") or 0.0)
    v0 = float(candidate.get("v_offset") or 0.0)
    d0 = float(candidate.get("depth_offset") or 0.0)
    y0 = float(candidate.get("yaw_offset") or 0.0)
    tx, ty = side_target_point(target_bbox_px, target_side)
    bounds = side_region_bounds(target_bbox_px)
    du_dx = screen_axis_sensitivity(candidate_log, "u_offset", 0)
    dv_dy = screen_axis_sensitivity(candidate_log, "v_offset", 1)
    step_u = abs(float(coarse_u_step)) or 0.15
    step_v = abs(float(coarse_v_step)) or 0.15

    def clamp(delta, step):
        limit = 4.0 * step
        return max(-limit, min(limit, delta))

    seeds = []

    def add(seed_type, u, v, depth, yaw):
        offset = (round(float(u), 12), round(float(v), 12),
                  round(float(depth), 12), round(float(yaw), 12))
        for existing in seeds:
            if existing[1] == offset:
                return
        seeds.append((seed_type, offset))

    # 1. target-side anchor — 측정된 감도로 centroid 를 목표 지점까지 민다.
    if du_dx and abs(du_dx) > 1e-9:
        add("target_side_anchor",
            u0 + clamp((tx - float(centroid[0])) / du_dx, step_u), v0, d0, y0)
    else:
        direction = 1.0 if tx >= float(centroid[0]) else -1.0
        add("target_side_anchor", u0 + direction * 2.0 * step_u, v0, d0, y0)

    # 2. target-mask centroid 방향 — 목표 지점과 팔레트 중심의 중간을 겨눈다.
    mid_x = 0.5 * (tx + 0.5 * (bounds["x0"] + bounds["x1"]))
    if du_dx and abs(du_dx) > 1e-9:
        add("target_mask_centroid",
            u0 + clamp((mid_x - float(centroid[0])) / du_dx, step_u), v0, d0, y0)

    # 3. lateral mirror — 팔레트 중심을 기준으로 u 를 반사한다.
    add("lateral_mirror", -u0 if abs(u0) > 1e-9 else u0 + 2.0 * step_u,
        v0, d0, y0)

    # 4. side-specific 세로 이동 — bottom 판정이 **먼저** 걸리므로 left/right 는
    #    가림 centroid 를 bottom 밴드 위로, bottom 목표는 밴드 안으로 옮겨야 한다.
    #    방향은 **실측 감도로만** 정한다 (§16: 이름·규약으로 추측 금지).
    #    감도가 없으면 세로 seed 를 만들지 않는다 — 부호를 지어내지 않는다.
    if dv_dy and abs(dv_dy) > 1e-9:
        shift = clamp((ty - float(centroid[1])) / dv_dy, step_v)
        seed_u = seeds[0][1][0] if (seeds and target_side != "bottom") else u0
        add("side_specific_shift", seed_u, v0 + shift, d0, y0)
    return tuple(seeds[:int(max_seeds)])


def g1_rescue_seeds(beam_entry, candidate_log, coarse_u_step, coarse_v_step,
                    coarse_depth_step, max_seeds=4):
    """§8 G1 rescue — raw margin(V_vis-4) 이 있으므로 실측 축 감도로 움직인다.

    이미 통과한 다른 제약을 깨지 않는 방향만 고른다.  boolean 만 있는 경우의
    fallback 은 `g1_pass_champion_seed` 가 담당한다.
    """
    candidate = beam_entry["candidate"]
    u0 = float(candidate.get("u_offset") or 0.0)
    v0 = float(candidate.get("v_offset") or 0.0)
    d0 = float(candidate.get("depth_offset") or 0.0)
    y0 = float(candidate.get("yaw_offset") or 0.0)
    steps = {"u_offset": abs(float(coarse_u_step)) or 0.15,
             "v_offset": abs(float(coarse_v_step)) or 0.15,
             "depth_offset": abs(float(coarse_depth_step)) or 0.175}
    sens = g1_axis_sensitivity(candidate_log)
    seeds = []

    def add(seed_type, u, v, depth, yaw):
        offset = (round(float(u), 12), round(float(v), 12),
                  round(float(depth), 12), round(float(yaw), 12))
        for existing in seeds:
            if existing[1] == offset:
                return
        seeds.append((seed_type, offset))

    ranked = sorted(
        (axis for axis in ("u_offset", "v_offset", "depth_offset")
         if sens.get(axis)),
        key=lambda axis: -abs(sens[axis]))
    for axis in ranked:
        step = steps[axis] * FINE_STEP_SCALE
        direction = 1.0 if sens[axis] > 0 else -1.0
        delta = direction * step
        add("g1_sensitivity_%s" % axis[0],
            u0 + (delta if axis == "u_offset" else 0.0),
            v0 + (delta if axis == "v_offset" else 0.0),
            d0 + (delta if axis == "depth_offset" else 0.0), y0)
    if not ranked:
        # 감도 정보가 없으면 임의 gradient 를 만들지 않고 depth 후퇴만 시도한다
        # (occluder 를 카메라에서 멀리 두면 팔레트 코너를 덜 가린다).
        add("g1_depth_backoff", u0, v0, d0 + steps["depth_offset"], y0)
    return tuple(seeds[:int(max_seeds)])


def g1_axis_sensitivity(candidate_log):
    """축별 d(V_vis)/d(offset) 실측값.  쌍이 없으면 그 축은 없다."""
    others = ("u_offset", "v_offset", "depth_offset", "yaw_offset")
    result = {}
    for axis in ("u_offset", "v_offset", "depth_offset"):
        points = []
        for candidate in candidate_log:
            v_vis = candidate.get("candidate_V_vis")
            if v_vis is None or candidate.get(axis) is None:
                continue
            rest = tuple((k, candidate.get(k)) for k in others if k != axis)
            points.append((rest, float(candidate[axis]), float(v_vis),
                           candidate.get("proposal_object")))
        slopes = []
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                rest_a, xa, ya, asset_a = points[i]
                rest_b, xb, yb, asset_b = points[j]
                if rest_a != rest_b or asset_a != asset_b or abs(xa - xb) < 1e-9:
                    continue
                slopes.append((ya - yb) / (xa - xb))
        if slopes:
            slopes.sort()
            mid = len(slopes) // 2
            result[axis] = (slopes[mid] if len(slopes) % 2
                            else 0.5 * (slopes[mid - 1] + slopes[mid]))
    return result


def constraint_rescue_plan(candidate_log, target_bbox_px, target_side,
                           coarse_steps, mode=CONSTRAINT_RESCUE_DEFAULT_MODE,
                           beam_max=RESCUE_BEAM_MAX,
                           eval_max=RESCUE_EVAL_MAX_PER_CASE,
                           category_max=RESCUE_EVAL_MAX_PER_CATEGORY,
                           evaluated_keys=()):
    """§7-§9 를 합친 결정적 rescue 계획.

    반환: {"beam": [...], "evaluations": [{category, seed_type, offset, ...}],
           "duplicate_skips": int, "axis_sequence": [...]}
    """
    if mode not in CONSTRAINT_RESCUE_MODES:
        raise ValueError("unknown constraint_rescue_mode: %r" % (mode,))
    empty = {"beam": [], "evaluations": [], "duplicate_skips": 0,
             "axis_sequence": [], "categories": []}
    if mode == "off":
        return empty
    beam = rescue_beam(candidate_log, categories=("side", "G1"),
                       beam_max=beam_max)
    if not beam:
        return empty
    u_step, v_step, d_step = coarse_steps
    seen = set(evaluated_keys)
    evaluations, duplicates, axes = [], 0, []
    per_category = {"side": 0, "G1": 0}

    def emit(category, seed_type, offset, entry):
        nonlocal duplicates
        if len(evaluations) >= int(eval_max):
            return
        if per_category[category] >= int(category_max):
            return
        probe = dict(entry["candidate"])
        probe.update({"u_offset": offset[0], "v_offset": offset[1],
                      "depth_offset": offset[2], "yaw_offset": offset[3]})
        key = candidate_geometry_key(probe)
        if key in seen:
            duplicates += 1
            return
        seen.add(key)
        per_category[category] += 1
        evaluations.append({
            "category": category, "seed_type": seed_type, "offset": offset,
            "geometry_key": key, "beam_role": entry.get("beam_role"),
            "source_order": entry.get("original_candidate_order"),
            "asset": entry.get("asset"),
            "constraint_before": {k: entry[k] for k in
                                  ("side_pass", "visibility_margin_px",
                                   "target_margin", "G1_margin", "G2_margin",
                                   "acceptance_pass_count")}})
        axes.append("%s:%s" % (category, seed_type))

    # side 를 먼저 — 위반 wall time 이 가장 큰 category 다 (§14 상위 우선).
    for entry in beam:
        if entry["side_pass"] is False:
            for seed_type, offset in side_rescue_seeds(
                    entry, target_bbox_px, target_side, candidate_log,
                    u_step, v_step, max_seeds=category_max):
                emit("side", seed_type, offset, entry)
    for entry in beam:
        if entry["G1_margin"] is not None and entry["G1_margin"] < 0:
            for seed_type, offset in g1_rescue_seeds(
                    entry, candidate_log, u_step, v_step, d_step,
                    max_seeds=category_max):
                emit("G1", seed_type, offset, entry)
    return {"beam": [{k: v for k, v in e.items() if k != "candidate"}
                     for e in beam],
            "evaluations": evaluations, "duplicate_skips": duplicates,
            "axis_sequence": axes,
            "categories": sorted({e["category"] for e in evaluations})}


def target_seed_budget_usage(candidate_log, proposal_index, free_cap):
    """target-seed 후보의 free / paid 사용량.

    free_cap=None 이면 전부 free(G1.5 동작), 0 이면 전부 paid.
    중복 geometry 는 free 슬롯을 **새로 소비하지 않는다** — 이미 free 인 key 의
    중복은 free, paid 인 key 의 중복은 paid.
    """
    ranks, free_used, paid_used, total, duplicates = {}, 0, 0, 0, 0
    for candidate in candidate_log:
        if candidate.get("proposal_index") != proposal_index:
            continue
        if candidate.get("stage") != TARGET_SEED_STAGE:
            continue
        total += 1
        key = candidate_geometry_key(candidate)
        if key in ranks:
            duplicates += 1
        else:
            ranks[key] = len(ranks)
        if free_cap is None or ranks[key] < int(free_cap):
            free_used += 1
        else:
            paid_used += 1
    return {"target_seed_candidate_count": total,
            "target_seed_unique_count": len(ranks),
            "target_seed_duplicate_count": duplicates,
            "target_seed_free_used": free_used,
            "target_seed_paid_used": paid_used}


def budgeted_attempt_count(candidate_log, proposal_index, free_cap):
    """일반 후보 예산이 세는 시도 수 (target-seed 의 free 분과 fine 단계는 제외)."""
    counted = 0
    for candidate in candidate_log:
        if candidate.get("proposal_index") != proposal_index:
            continue
        stage = candidate.get("stage")
        if stage in (TARGET_SEED_STAGE, FINE_STAGE):
            continue
        counted += 1
    usage = target_seed_budget_usage(candidate_log, proposal_index, free_cap)
    return counted + usage["target_seed_paid_used"]


def near_miss_candidates(candidate_log, tolerance=None, hard_reasons=(
        "support", "collision", "camera_clearance")):
    """목표 오차 **하나만** 막고 있는 후보만 돌려준다 (margin 작은 순).

    side / 코너 / 가시성이 함께 막고 있으면 좌표 미세 조정으로 살아나지 않는다.
    support·collision·camera_clearance 같은 hard 실패도 대상이 아니다.
    """
    tolerance = EXPLICIT_TARGET_ABS_TOLERANCE if tolerance is None else tolerance
    out = []
    for order, candidate in enumerate(candidate_log):
        if candidate.get("reason") in hard_reasons:
            continue
        error = candidate.get("abs_error")
        if error is None:
            continue
        if candidate.get("target_error_ok"):
            continue
        if not candidate.get("occluder_side_match"):
            continue
        visible = candidate.get("object_visible_pixels")
        if visible is None or int(visible) < 8:
            continue
        g1, g2 = candidate.get("candidate_G1_pass"), candidate.get("candidate_G2_pass")
        if not (g1 and g2):
            continue
        margin = float(tolerance) - float(error)
        out.append({"order": order, "candidate": candidate,
                    "abs_gap": abs(margin), "score_margin": margin,
                    "score": candidate.get("score"),
                    "stage": candidate.get("stage"),
                    "object": candidate.get("proposal_object")})
    return out


def select_near_miss_seed(candidate_log, gap_threshold, tolerance=None):
    """case 당 1개.  score 높은 순 -> 후보 순서 -> asset 이름 순으로 deterministic."""
    if gap_threshold is None:
        return None
    pool = [c for c in near_miss_candidates(candidate_log, tolerance=tolerance)
            if c["abs_gap"] <= float(gap_threshold)]
    if not pool:
        return None
    pool.sort(key=lambda c: (-(c["score"] if c["score"] is not None else -1e9),
                             c["order"], str(c["object"])))
    return pool[0]


def fine_refinement_offsets(coarse_u_step, coarse_v_step, coarse_depth_step,
                            scale=FINE_STEP_SCALE):
    """coarse step 의 ±scale 배로 만든 축별 이웃 — 전체 grid 를 만들지 않는다.

    ((u,v,depth,yaw) 오프셋 목록, 축 경계) 를 돌려준다.  호출자는 offset 이웃을
    먼저 평가하고 그중 best 를 기준으로 depth 이웃을 평가한다.
    """
    du = abs(float(coarse_u_step)) * float(scale)
    dv = abs(float(coarse_v_step)) * float(scale)
    dd = abs(float(coarse_depth_step)) * float(scale)
    offsets = [(-du, 0.0, 0.0, 0.0), (du, 0.0, 0.0, 0.0),
               (0.0, -dv, 0.0, 0.0), (0.0, dv, 0.0, 0.0)]
    depth = [(0.0, 0.0, -dd, 0.0), (0.0, 0.0, dd, 0.0)]
    return tuple(offsets), tuple(depth)


def context_corner_no_regression(metrics, post_explicit_metrics):
    """explicit 이 이미 놓인 뒤 context 가 코너를 더 나쁘게 만들지 않았는가.

    `explicit_corner_reserve_pass` 는 **explicit 을 놓기 전** 코너 여유를 남겨 두는
    계약이라 `ext_occ <= 1` 을 요구한다.  explicit 배치를 context 앞으로 옮긴 뒤
    그 계약을 그대로 쓰면, 가리는 것이 본업인 occluder 때문에 거의 모든 context
    후보가 탈락한다 (2026-08-01 replay: context 단계 14초 -> 225초).  배치 후에는
    "explicit 만 있던 상태보다 나빠지지 않았는가"가 올바른 기준이다.
    """
    if not isinstance(metrics, Mapping):
        raise TypeError("metrics must be a mapping")
    if not isinstance(post_explicit_metrics, Mapping):
        raise TypeError("post_explicit_metrics must be a mapping")
    return bool(
        int(metrics.get("V_inframe", 0))
        >= int(post_explicit_metrics.get("V_inframe", 0))
        and int(metrics.get("ext_occ_corners", 0))
        <= int(post_explicit_metrics.get("ext_occ_corners", 0))
        and int(metrics.get("V_vis", 0))
        >= int(post_explicit_metrics.get("V_vis", 0))
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
    if poses:
        return poses

    # ★ 저앙각 구제 (2026-08-01).  위 sampler 는 "이미지 좌우 띠의 픽셀 -> 지면 교점"
    # 방향으로 푼다.  카메라가 지면에 가까우면 그 띠의 광선이 지평선 위로 가거나 아주
    # 멀리 떨어져 max_camera_distance 를 넘고, 32*attempts 후보가 전부 탈락해 빈 목록이
    # 된다 -- baseline 에서 context-rich 600장 중 39장이 "배치를 시도조차 못 한" 원인이
    # 바로 이것이다 (기각 사유 64% camera_distance_out_of_band, 22% ray_up).
    # 같은 물리 제약(카메라 거리 밴드 · 팔레트 최소 이격)을 유지한 채 순서만 뒤집어,
    # 지면 위 점을 먼저 고르고 그것이 화면 좌우 띠에 맺히는지 확인한다.  위 sampler 가
    # 하나라도 성공하면 이 경로는 돌지 않으므로 기존 프레임의 배치는 변하지 않는다.
    horizontal_forward = (forward[0], forward[1], 0.0)
    if math.sqrt(dot(horizontal_forward, horizontal_forward)) <= 1e-9:
        return poses
    horizontal_forward = normalized(horizontal_forward)
    base_yaw = math.atan2(horizontal_forward[1], horizontal_forward[0])
    lo = max(float(min_camera_distance), float(min_target_distance))
    hi = float(max_camera_distance)
    if lo >= hi:
        return poses
    for index in range(max_candidates):
        radius = lo + (hi - lo) * rng.random()
        # 화면 좌우 띠에 대응하는 시야각 근처만 본다 (중앙 정면은 팔레트 자리다).
        side = -1.0 if index % 2 == 0 else 1.0
        offset = side * (0.25 + 0.55 * rng.random()) * (
            math.atan2(0.5 * float(width), fx)
        )
        yaw = base_yaw + offset
        point = (
            camera[0] + radius * math.cos(yaw),
            camera[1] + radius * math.sin(yaw),
            float(ground_z),
        )
        if math.hypot(point[0] - pallet[0],
                      point[1] - pallet[1]) < float(min_target_distance):
            continue
        to_point = subtract(point, camera)
        if dot(to_point, forward) <= 1e-6:      # 카메라 뒤
            continue
        pixel_u = fx * dot(to_point, right) / dot(to_point, forward) + float(cx)
        if not (0.0 <= pixel_u <= float(width - 1)):
            continue
        poses.append(
            {
                "x": float(point[0]),
                "y": float(point[1]),
                "yaw_rad": rng.uniform(-math.pi, math.pi),
                "fallback": "ground_ring",
            }
        )
        if len(poses) >= requested:
            break
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


# ---------------------------------------------------------------------------
# MODE SEMANTICS — "이 프레임이 정말 그 mode 의 내용을 담고 있는가"
# ---------------------------------------------------------------------------
# 지금까지 usable gate 는 물리·마스크 무결성만 봤다.  그래서 cargo-only 인데 cargo 가
# 하나도 놓이지 않은 프레임, context-rich 인데 context 를 시도조차 안 한 프레임이
# usable 로 통과했다 (2026-08-01 pilot 감사).  아래 조건은 mode 별로 "그 물체가 실제로
# 화면에 있는가"를 판정한다.
#
# tri-state 규약:  True = 통과 · False = 실제 실패 · None = 측정 안 됨(=통과 아님).
MODE_SEMANTICS_CONDITIONS = {
    "clean-static": (
        "no_explicit_occluder", "no_visible_cargo", "no_visible_context",
    ),
    "cargo-only": ("cargo_placed", "cargo_visible"),
    "context-rich": ("context_requested", "context_placed", "context_visible"),
    "controlled-occlusion": (
        "explicit_target_positive", "explicit_occluder_placed",
        "explicit_occluder_visible", "occluder_side_match",
    ),
}
MODE_SEMANTICS_REASONS = {
    "no_explicit_occluder": "clean_has_explicit_occluder",
    "no_visible_cargo": "clean_has_visible_cargo",
    "no_visible_context": "clean_has_visible_context",
    "cargo_placed": "cargo_not_placed",
    "cargo_visible": "cargo_not_visible",
    "context_requested": "context_not_requested",
    "context_placed": "context_not_placed",
    "context_visible": "context_not_visible",
    "explicit_target_positive": "explicit_target_not_positive",
    "explicit_occluder_placed": "explicit_occluder_missing",
    "explicit_occluder_visible": "explicit_occluder_not_visible",
    "occluder_side_match": "occluder_side_mismatch",
}


def _semantics_number(value):
    """숫자로 읽되, 없으면 None(=측정 안 됨).  0 은 진짜 0 이다."""
    if value is None or isinstance(value, bool):
        return None if value is None else float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _semantics_ge(value, threshold):
    n = _semantics_number(value)
    return None if n is None else bool(n >= threshold)


def _semantics_gt(value, threshold):
    n = _semantics_number(value)
    return None if n is None else bool(n > threshold)


def mode_semantics_conditions(diagnostic_mode, record):
    """mode 별 내용 조건을 tri-state dict 로 평가한다 (bpy 없음).

    record 는 realize 의 constrained_metrics 또는 runner 의 최종 record — 둘 다
    같은 필드 이름을 쓴다.  short-circuit 하지 않고 전부 평가한다.
    """
    if diagnostic_mode not in MODE_SEMANTICS_CONDITIONS:
        raise ValueError(f"unknown diagnostic mode: {diagnostic_mode!r}")
    get = record.get
    if diagnostic_mode == "clean-static":
        placed = get("explicit_occluder_placed")
        cargo_px = _semantics_number(get("cargo_visible_pixels"))
        context_n = _semantics_number(get("n_context_visible"))
        return {
            "no_explicit_occluder": (None if placed is None else not bool(placed)),
            "no_visible_cargo": (None if cargo_px is None else cargo_px == 0.0),
            "no_visible_context": (None if context_n is None else context_n == 0.0),
        }
    if diagnostic_mode == "cargo-only":
        return {
            "cargo_placed": _semantics_ge(get("n_cargo_placed"), 1),
            "cargo_visible": _semantics_gt(get("cargo_visible_pixels"), 0),
        }
    if diagnostic_mode == "context-rich":
        return {
            "context_requested": _semantics_ge(get("n_context_requested"), 1),
            "context_placed": _semantics_ge(get("n_context_placed"), 1),
            "context_visible": (
                _semantics_ge(get("n_context_visible"), 1)
                and _semantics_gt(get("context_visible_pixel_ratio"), 0.0)
            ),
        }
    side_match = get("occluder_side_match")
    return {
        "explicit_target_positive": _semantics_gt(get("f_explicit_target"), 0.0),
        "explicit_occluder_placed": (
            None if get("explicit_occluder_placed") is None
            else bool(get("explicit_occluder_placed"))
        ),
        "explicit_occluder_visible": _semantics_gt(
            get("explicit_occluder_visible_pixels"), 0),
        "occluder_side_match": (None if side_match is None else bool(side_match)),
    }


def mode_semantics_verdict(diagnostic_mode, record):
    """{pass, conditions, failed, unknown, reason} — None 은 통과가 아니다."""
    conditions = mode_semantics_conditions(diagnostic_mode, record)
    failed = [name for name in MODE_SEMANTICS_CONDITIONS[diagnostic_mode]
              if conditions.get(name) is False]
    unknown = [name for name in MODE_SEMANTICS_CONDITIONS[diagnostic_mode]
               if conditions.get(name) is None]
    ordered = failed + unknown
    return {
        "pass": not ordered,
        "conditions": conditions,
        "failed_conditions": failed,
        "unknown_conditions": unknown,
        "reason": (f"mode_semantics:{MODE_SEMANTICS_REASONS[ordered[0]]}"
                   if ordered else None),
        "reasons": [f"mode_semantics:{MODE_SEMANTICS_REASONS[name]}"
                    for name in ordered],
    }


# ---------------------------------------------------------------------------
# CONTROLLED OCCLUDER FEASIBILITY PREFILTER (bpy-free, 결정적)
# ---------------------------------------------------------------------------
# Blender 의 bounded local search 는 비싸다 (baseline: 실패 94건에 4,936초, 그중
# explicit 단계 3,118초 + 그 앞 context 배치 1,424초 — RGB 는 한 장도 렌더하지 않았다).
# 아래 규칙은 상세 탐색에 넘기기 전에 "이 후보는 접지시키면 목표를 맞출 수 없다"를
# 계획 단계 기하만으로 판정한다.  ML 아님 · frame-ID blacklist 아님 · seed 무관.
#
# 임계는 baseline 의 winner 49건(=프레임을 살린 후보)이 전부 통과하도록 잡고, 물리적
# 여유를 더했다.  근거는 reports/v2_generator_fix_g1_g3/g1/controlled_failure_matrix.md.
# ---------------------------------------------------------------------------
# 팔레트 치수 랜덤화 — KS T-11 근처가 많고, 벗어날수록 드물게 (종 모양)
#
# 에셋이 4종뿐이라 치수 값이 이산이었다(고유값 3~4개).  현장에는 규격 외 팔레트가
# 흔하므로 프레임마다 크기를 흔들어 커버리지를 넓힌다.  **균등 스케일만** 쓴다 —
# 가로/세로/높이를 따로 흔들면 존재하지 않는 형상을 학습시키게 된다.
# sigma=0.10 이므로 68% 가 ±10% 안에 들어오고(높이 135~165mm), 절단 상한이 ±20%다.
PALLET_SCALE_JITTER_SIGMA = 0.10
PALLET_SCALE_JITTER_MAX = 0.20
PALLET_SCALE_JITTER_TRIES = 16      # 절단 구간 밖이면 다시 뽑는 횟수


def sample_pallet_scale_ratio(rng, sigma=None, max_dev=None):
    """1.0 을 중심으로 한 절단 정규분포 배율을 돌려준다.

    `rng` 는 `random.Random` 호환 객체여야 하고, 호출자가 frame seed 로 고정한다
    (재현성).  절단은 rejection 으로 하되 시도 횟수를 묶고, 끝내 못 뽑으면 clamp 한다
    — 무한 루프가 생기면 렌더가 통째로 멈춘다.
    """
    s = PALLET_SCALE_JITTER_SIGMA if sigma is None else float(sigma)
    m = PALLET_SCALE_JITTER_MAX if max_dev is None else float(max_dev)
    if s <= 0.0 or m <= 0.0:
        return 1.0
    for _ in range(PALLET_SCALE_JITTER_TRIES):
        dev = rng.gauss(0.0, s)
        if abs(dev) <= m:
            return 1.0 + dev
    return 1.0 + max(-m, min(m, rng.gauss(0.0, s)))


def scaled_target_dims(base_dims, ratio):
    """정본 치수에 균등 배율을 곱한다 (형상 유지)."""
    r = float(ratio)
    if not (r > 0.0):
        raise ValueError("scale ratio must be positive: %r" % (ratio,))
    return tuple(float(v) * r for v in base_dims)


PREFILTER_BURIED_MAX = -0.60      # 계획 바닥이 자기 높이의 60% 넘게 지면 아래 (winner 최소 -0.535)
PREFILTER_FLOAT_MAX = 1.90        # 계획 바닥이 자기 높이의 1.9배 넘게 공중 (winner 최대 1.751)
PREFILTER_SILHOUETTE_MIN = 1.15   # 실루엣/요구 겹침면적 (winner 최소 1.192)
PREFILTER_FILL_MIN = 0.45         # 성긴 실루엣은 조밀한 겹침을 못 만든다 (winner 최소 0.480)
PREFILTER_SCREEN_OVER_PALLET_MAX = 22.0   # 팔레트 실루엣 대비 상한 (winner 최대 19.92)

PREFILTER_REASONS = (
    "prefilter_insufficient_projected_area",
    "prefilter_fill_ratio_too_low",
    "prefilter_side_geometry_infeasible",
    "prefilter_floor_support_infeasible",
    "prefilter_position_band_infeasible",
)


def controlled_prefilter_reason(candidate, pallet_silhouette_px2,
                                screen_area_px2=None):
    """계획된 explicit occluder 후보가 접지 상태로 목표를 맞출 수 있는가.

    통과면 None, 아니면 PREFILTER_REASONS 중 하나.  입력은 전부 solve 단계에서 이미
    알려진 값이다 (최종 RGB 를 보지 않는다).
    """
    if candidate is None:
        return "prefilter_side_geometry_infeasible"
    side = candidate.get("side")
    if side == "center":
        # center 는 실루엣 전체가 팔레트 안에 들어가야 하는데, 접지된 occluder 로는
        # 깊이가 고정돼 탐색 여유가 없다.  baseline 에서 30번 시도해 0번 성공.
        return "prefilter_side_geometry_infeasible"
    if candidate.get("in_position_band") is False:
        return "prefilter_position_band_infeasible"

    fill = candidate.get("fill_ratio")
    if fill is not None and float(fill) < PREFILTER_FILL_MIN:
        return "prefilter_fill_ratio_too_low"

    bmin = candidate.get("bmin")
    bmax = candidate.get("bmax")
    if bmin is not None and bmax is not None:
        bottom = float(bmin[2])
        height = float(bmax[2]) - bottom
        if height > 1e-9:
            ratio = bottom / height
            if ratio < PREFILTER_BURIED_MAX or ratio > PREFILTER_FLOAT_MAX:
                # 접지 스냅이 만들 변위가 bounded search 의 u/v/depth 범위를 넘는다.
                return "prefilter_floor_support_infeasible"

    target_px2 = candidate.get("overlap_target_px2")
    if screen_area_px2 is not None and target_px2:
        if float(screen_area_px2) / float(target_px2) < PREFILTER_SILHOUETTE_MIN:
            return "prefilter_insufficient_projected_area"
    if screen_area_px2 is not None and pallet_silhouette_px2:
        over = float(screen_area_px2) / float(pallet_silhouette_px2)
        if over > PREFILTER_SCREEN_OVER_PALLET_MAX:
            return "prefilter_insufficient_projected_area"
    return None


def explicit_lowres_metrics(target_stats, actual_stats, f_target, f_actual):
    """§2 explicit 저해상도 품질 지표 — 숫자만 돌려준다 (마스크 저장 없음).

    측정 안 됨은 None 이고 0 과 구분된다.  `explicit_metrics_available` 이 False 면
    나머지 값을 품질 판정에 쓰면 안 된다 (f_total 로 대체하는 것도 금지).
    """
    available = bool(target_stats is not None and actual_stats is not None)
    target_stats = target_stats or {}
    actual_stats = actual_stats or {}
    target_centroid = target_stats.get("centroid_px") or [None, None]
    actual_centroid = actual_stats.get("centroid_px") or [None, None]
    error = (abs(float(f_actual) - float(f_target))
             if available and f_actual is not None and f_target is not None
             else None)
    return {
        "explicit_metrics_available": available,
        "explicit_target_pixels": (target_stats.get("visible_pixels")
                                   if available else None),
        "explicit_actual_pixels_lowres": (actual_stats.get("visible_pixels")
                                          if available else None),
        "f_explicit_actual_lowres": float(f_actual) if available else None,
        "explicit_abs_error_lowres": error,
        "explicit_target_centroid_u": target_centroid[0] if available else None,
        "explicit_target_centroid_v": target_centroid[1] if available else None,
        "explicit_actual_centroid_u_lowres": (actual_centroid[0]
                                              if available else None),
        "explicit_actual_centroid_v_lowres": (actual_centroid[1]
                                              if available else None),
        "explicit_target_bbox_u0v0u1v1": (target_stats.get("bbox_px")
                                          if available else None),
        "explicit_actual_bbox_u0v0u1v1_lowres": (actual_stats.get("bbox_px")
                                                 if available else None),
    }


EXPLICIT_SEARCH_INIT_STRATEGY = "target_mask_conditioned_prealign_first"


def explicit_search_metrics(explicit_search):
    """§4 탐색 계측 — 어떤 초기화 전략으로 몇 번 평가했고 어디서 이겼는가."""
    stats = (explicit_search or {}).get("search_stats") or {}
    return {
        "search_init_strategy": (EXPLICIT_SEARCH_INIT_STRATEGY
                                 if explicit_search is not None else None),
        "search_seed_count": stats.get("search_seed_count"),
        "coarse_eval_count": stats.get("coarse_eval_count"),
        # refine/feedback/fine 을 합친 수.  §4 의 fine 단계만 센 값은 record 의
        # `fine_eval_count` 로 따로 나간다 (이름 충돌을 피한다).
        "refine_feedback_eval_count": stats.get("fine_eval_count"),
        "best_seed_score": stats.get("best_seed_score"),
        "final_seed_score": stats.get("final_seed_score"),
        "search_winning_stage": stats.get("winning_stage"),
    }


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


# "pallet" 은 나중에 추가됐다.  각 stage seed 가 stage 이름으로 독립 해시되므로
# 항목을 늘려도 기존 stage 의 seed 값은 변하지 않는다.
_STAGES = ("background", "anchor", "cargo", "context", "occluder", "pallet")


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
