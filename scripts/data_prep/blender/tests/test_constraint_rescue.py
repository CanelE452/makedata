"""G1.7 §10 — constraint-directed rescue 순수 단위 테스트 (bpy 없음)."""
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_BLENDER = os.path.dirname(_THIS)
if _BLENDER not in sys.path:
    sys.path.insert(0, _BLENDER)

import scene_placement_v2 as SP2  # noqa: E402

TARGET_BBOX = (33.0, 8.0, 210.0, 127.0)      # locked77 실제 값
COARSE = (0.15, 0.15, 0.175)


def cand(**kw):
    """acceptance 를 전부 통과하는 기본 후보 (필요한 것만 덮어쓴다)."""
    base = {
        "proposal_object": "Dist_box", "stage": "primary", "reason": None,
        "u_offset": 0.0, "v_offset": 0.0, "depth_offset": 0.0,
        "yaw_offset": 0.0, "yaw_rad": 0.0, "center": [1.0, 2.0, 3.0],
        "occluder_side_match": True, "occluder_side_target": "left",
        "object_visible_pixels": 400, "abs_error": 0.01,
        "candidate_V_vis": 6, "candidate_ext_occ_corners": 2,
        "score": -0.1, "object_visible_centroid_px": [120.0, 60.0],
    }
    base.update(kw)
    return base


# 1 ---------------------------------------------------------------- vector
def test_constraint_vector_uses_real_thresholds():
    v = SP2.candidate_constraint_vector(cand(), order=3)
    assert v["accepted"] is True
    assert v["visibility_margin_px"] == 400 - 8
    assert v["target_margin"] == pytest.approx(0.12 - 0.01)
    assert v["G1_margin"] == 6 - 4
    assert v["G2_margin"] == min(2 - 1, 4 - 2)
    assert v["acceptance_pass_count"] == 5
    assert v["original_candidate_order"] == 3


def test_constraint_vector_none_is_unknown_not_pass():
    v = SP2.candidate_constraint_vector(
        cand(occluder_side_match=None, abs_error=None))
    assert v["side_pass"] is None and v["target_pass"] is None
    assert set(v["unknown"]) == {"side", "target"}
    assert v["violation_count"] is None
    assert v["accepted"] is False


def test_g2_margin_is_two_sided():
    assert SP2.candidate_constraint_vector(
        cand(candidate_ext_occ_corners=0))["G2_margin"] == -1
    assert SP2.candidate_constraint_vector(
        cand(candidate_ext_occ_corners=5))["G2_margin"] == -1
    assert SP2.candidate_constraint_vector(
        cand(candidate_ext_occ_corners=8))["G2_margin"] == -4


# 2 ------------------------------------------------------------- dominance
def test_pareto_dominance_boolean_pass_beats_fail():
    a = SP2.candidate_constraint_vector(cand(occluder_side_match=True))
    b = SP2.candidate_constraint_vector(cand(occluder_side_match=False))
    assert SP2.constraint_vector_dominates(a, b)
    assert not SP2.constraint_vector_dominates(b, a)


def test_pareto_dominance_continuous_margin():
    a = SP2.candidate_constraint_vector(cand(candidate_V_vis=3))   # -1
    b = SP2.candidate_constraint_vector(cand(candidate_V_vis=2))   # -2
    assert SP2.constraint_vector_dominates(a, b)
    assert not SP2.constraint_vector_dominates(b, a)


def test_pareto_no_dominance_when_trading_constraints():
    a = SP2.candidate_constraint_vector(cand(candidate_V_vis=3))
    b = SP2.candidate_constraint_vector(cand(candidate_ext_occ_corners=0))
    assert not SP2.constraint_vector_dominates(a, b)
    assert not SP2.constraint_vector_dominates(b, a)


def test_passing_margins_do_not_create_dominance():
    """이미 통과한 축의 여유가 크다고 dominate 하지 않는다."""
    a = SP2.candidate_constraint_vector(cand(object_visible_pixels=4000))
    b = SP2.candidate_constraint_vector(cand(object_visible_pixels=400))
    assert not SP2.constraint_vector_dominates(a, b)


def test_unknown_axis_blocks_dominance_claim():
    a = SP2.candidate_constraint_vector(cand())
    b = SP2.candidate_constraint_vector(cand(abs_error=None))
    assert not SP2.constraint_vector_dominates(a, b)
    assert not SP2.constraint_vector_dominates(b, a)


# 3 --------------------------------------------------- hard physical 제외
def test_hard_physical_fail_never_dominates():
    a = SP2.candidate_constraint_vector(cand(reason="support"))
    b = SP2.candidate_constraint_vector(cand(occluder_side_match=False))
    assert a["hard_physical_pass"] is False
    assert not SP2.constraint_vector_dominates(a, b)


@pytest.mark.parametrize("reason", ["support", "collision", "camera_clearance"])
def test_hard_physical_candidates_excluded_from_beam(reason):
    log = [cand(reason=reason, u_offset=0.3), cand(occluder_side_match=False)]
    beam = SP2.rescue_beam(log)
    assert all(e["hard_physical_pass"] for e in beam)
    assert len(beam) >= 1


# 4 ------------------------------------------------------------- dedup
def test_beam_removes_duplicate_geometry():
    duplicate = cand(occluder_side_match=False)
    log = [duplicate, dict(duplicate, stage="rescue"), dict(duplicate,
                                                            stage="refine")]
    beam = SP2.rescue_beam(log)
    keys = [e["geometry_key"] for e in beam]
    assert len(keys) == len(set(keys)) == 1


def test_plan_skips_already_evaluated_geometry():
    log = [cand(occluder_side_match=False, occluder_side_target="left")]
    first = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                       mode="side_g1")
    keys = [e["geometry_key"] for e in first["evaluations"]]
    assert keys
    again = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                       mode="side_g1", evaluated_keys=keys)
    assert again["evaluations"] == []
    assert again["duplicate_skips"] >= 1


# 5-7 ------------------------------------------------------------ 예산
def test_beam_width_at_most_three():
    log = [cand(occluder_side_match=False, u_offset=0.1),
           cand(candidate_V_vis=3, u_offset=0.2),
           cand(candidate_ext_occ_corners=0, u_offset=0.3),
           cand(abs_error=0.9, u_offset=0.4),
           cand(object_visible_pixels=0, u_offset=0.5)]
    assert len(SP2.rescue_beam(log)) <= SP2.RESCUE_BEAM_MAX


def test_rescue_eval_capped_per_case():
    log = [cand(occluder_side_match=False, candidate_V_vis=3, u_offset=0.1 * i,
                object_visible_centroid_px=[100.0 + i, 60.0 + i])
           for i in range(6)]
    plan = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                      mode="side_g1", eval_max=8)
    assert len(plan["evaluations"]) <= 8


def test_rescue_eval_capped_per_category():
    log = [cand(occluder_side_match=False, candidate_V_vis=3, u_offset=0.1 * i,
                object_visible_centroid_px=[100.0 + i, 60.0 + i])
           for i in range(6)]
    plan = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                      mode="side_g1", eval_max=8,
                                      category_max=4)
    for name in ("side", "G1"):
        got = [e for e in plan["evaluations"] if e["category"] == name]
        assert len(got) <= 4


# 8 --------------------------------------------------------- gate 불변
def test_rescue_does_not_change_acceptance_thresholds():
    assert SP2.ACCEPTANCE_MIN_VISIBLE_PIXELS == 8
    assert SP2.G1_MIN_V_VIS == 4
    assert (SP2.G2_MIN_EXT_OCC, SP2.G2_MAX_EXT_OCC) == (1, 4)
    assert SP2.EXPLICIT_TARGET_ABS_TOLERANCE == 0.12


# 9 ------------------------------------------------------- score tie-break
def test_score_is_only_the_last_tie_break():
    """constraint vector 가 다르면 score 가 나빠도 이긴다."""
    better_constraints = cand(occluder_side_match=False, candidate_V_vis=6,
                              score=-9.0, u_offset=0.1)
    worse_constraints = cand(occluder_side_match=False, candidate_V_vis=2,
                             score=-0.001, u_offset=0.2)
    beam = SP2.rescue_beam([worse_constraints, better_constraints])
    roles = {e["beam_role"]: e for e in beam}
    champion = roles.get("side_champion") or roles["global_best"]
    assert champion["G1_margin"] == 2


def test_score_breaks_exact_constraint_ties():
    low = cand(occluder_side_match=False, score=-0.5, u_offset=0.1)
    high = cand(occluder_side_match=False, score=-0.1, u_offset=0.2)
    beam = SP2.rescue_beam([low, high])
    assert beam[0]["existing_score"] == -0.1


# 10-11 ------------------------------------------------------ SIDE seeds
def test_side_seeds_are_discrete_and_bounded():
    entry = SP2.rescue_beam([cand(occluder_side_match=False)])[0]
    seeds = SP2.side_rescue_seeds(entry, TARGET_BBOX, "left", [entry["candidate"]],
                                  0.15, 0.15)
    assert 1 <= len(seeds) <= 4
    assert len({s[1] for s in seeds}) == len(seeds)
    assert {s[0] for s in seeds} <= {"target_side_anchor", "target_mask_centroid",
                                     "lateral_mirror", "side_specific_shift"}


def test_vertical_seed_is_omitted_without_measured_sensitivity():
    """부호를 지어내지 않는다 — v 감도가 없으면 세로 seed 자체를 만들지 않는다."""
    single = [cand(occluder_side_match=False)]          # 쌍이 없어 감도 없음
    entry = SP2.rescue_beam(single)[0]
    seeds = SP2.side_rescue_seeds(entry, TARGET_BBOX, "bottom", single, 0.15, 0.15)
    assert all(s[0] != "side_specific_shift" for s in seeds)
    assert all(s[1][1] == 0.0 for s in seeds), "v 를 임의 부호로 움직이면 안 된다"


@pytest.mark.parametrize("side", ["bottom", "left", "right"])
def test_vertical_seed_direction_comes_from_measurement(side):
    """감도가 있으면 모든 side 에서 같은 실측 공식으로 방향을 정한다."""
    log = [cand(occluder_side_match=False, v_offset=0.0,
                object_visible_centroid_px=[120.0, 60.0]),
           cand(occluder_side_match=False, v_offset=0.20,
                object_visible_centroid_px=[120.0, 40.0])]
    dv = SP2.screen_axis_sensitivity(log, "v_offset", 1)
    assert dv == pytest.approx((60.0 - 40.0) / (0.0 - 0.20))
    entry = SP2.rescue_beam(log)[0]
    seeds = SP2.side_rescue_seeds(entry, TARGET_BBOX, side, log, 0.15, 0.15)
    shift = [s for s in seeds if s[0] == "side_specific_shift"]
    assert shift, "감도가 있으면 세로 seed 가 있어야 한다"
    _tx, ty = SP2.side_target_point(TARGET_BBOX, side)
    src = entry["candidate"]
    expected = float(src["v_offset"]) + (
        ty - float(src["object_visible_centroid_px"][1])) / dv
    assert shift[0][1][1] == pytest.approx(expected, abs=0.6)


def test_side_region_bounds_match_the_classifier():
    """v2_realize._occlusion_side_from_masks 와 같은 삼등분이어야 한다."""
    b = SP2.side_region_bounds(TARGET_BBOX)
    x0, y0, x1, y1 = TARGET_BBOX
    assert b["left_max"] == pytest.approx(x0 + (1.0 / 3.0) * (x1 - x0))
    assert b["right_min"] == pytest.approx(x0 + (2.0 / 3.0) * (x1 - x0))
    assert b["bottom_min"] == pytest.approx(y0 + (2.0 / 3.0) * (y1 - y0))


def test_left_right_targets_stay_above_the_bottom_band():
    """bottom 이 먼저 판정되므로 left/right 목표점은 bottom 밴드 위여야 한다."""
    b = SP2.side_region_bounds(TARGET_BBOX)
    for side in ("left", "right", "center"):
        _tx, ty = SP2.side_target_point(TARGET_BBOX, side)
        assert ty < b["bottom_min"]
    _bx, by = SP2.side_target_point(TARGET_BBOX, "bottom")
    assert by >= b["bottom_min"]


def test_side_success_requires_all_five_conditions():
    """side 만 통과한 후보는 accepted 가 아니다."""
    v = SP2.candidate_constraint_vector(
        cand(occluder_side_match=True, candidate_ext_occ_corners=0))
    assert v["side_pass"] is True
    assert v["accepted"] is False
    assert v["violated"] == ("G2",)


# 12-13 --------------------------------------------------------- G1 rescue
def test_g1_raw_margin_drives_axis_choice():
    log = [cand(candidate_V_vis=3, u_offset=0.0),
           cand(candidate_V_vis=5, u_offset=0.30)]
    sens = SP2.g1_axis_sensitivity(log)
    assert sens["u_offset"] == pytest.approx((3 - 5) / (0.0 - 0.30))
    entry = SP2.rescue_beam(log)[0]
    seeds = SP2.g1_rescue_seeds(entry, log, 0.15, 0.15, 0.175)
    assert seeds and seeds[0][0].startswith("g1_sensitivity")


def test_g1_boolean_only_fallback_makes_no_fake_gradient():
    log = [cand(candidate_V_vis=3, u_offset=0.0)]      # 쌍이 없어 감도 없음
    assert SP2.g1_axis_sensitivity(log) == {}
    entry = SP2.rescue_beam(log)[0]
    seeds = SP2.g1_rescue_seeds(entry, log, 0.15, 0.15, 0.175)
    assert [s[0] for s in seeds] == ["g1_depth_backoff"]


# 14 ------------------------------------------- 통과 제약 회귀 후보 거부
def test_regressing_a_passing_constraint_is_not_dominant():
    passing = SP2.candidate_constraint_vector(cand(candidate_V_vis=3))
    regressed = SP2.candidate_constraint_vector(
        cand(candidate_V_vis=5, occluder_side_match=False))
    assert not SP2.constraint_vector_dominates(regressed, passing)


# 15 ------------------------------------------------------------ 결정성
def test_plan_is_deterministic():
    log = [cand(occluder_side_match=False, u_offset=0.1 * i,
                object_visible_centroid_px=[100.0 + i, 60.0])
           for i in range(4)]
    a = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                   mode="side_g1")
    b = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                   mode="side_g1")
    assert a["evaluations"] == b["evaluations"]
    assert a["axis_sequence"] == b["axis_sequence"]


# 16 -------------------------------------------- fine/rescue 중복 평가 0
def test_shared_evaluated_set_prevents_fine_rescue_overlap():
    base = cand(occluder_side_match=False)
    fine_key = SP2.candidate_geometry_key(
        dict(base, u_offset=0.075, stage=SP2.FINE_STAGE))
    plan = SP2.constraint_rescue_plan([base], TARGET_BBOX, "left", COARSE,
                                      mode="side_g1",
                                      evaluated_keys=[fine_key])
    assert all(e["geometry_key"] != fine_key for e in plan["evaluations"])


# 17 ---------------------------------------------------- global budget 불변
def test_rescue_does_not_touch_the_global_candidate_budget():
    assert SP2.EXPLICIT_CANDIDATE_LIMIT_PER_PROPOSAL == 12
    log = [cand(occluder_side_match=False, stage=SP2.CONSTRAINT_RESCUE_STAGE)]
    # constraint-rescue 는 일반 예산 카운터에 잡히지 않아야 한다.
    assert SP2.budgeted_attempt_count(
        [dict(c, proposal_index=0) for c in log], 0, None) == 1


# 18 ---------------------------------------------------- blacklist 없음
def test_rescue_plan_takes_no_frame_or_seed_identity():
    """계획이 frame id / seed 를 아예 받지 않으므로 blacklist 가 불가능하다."""
    import inspect

    params = set(inspect.signature(SP2.constraint_rescue_plan).parameters)
    assert not (params & {"frame_id", "frame_index", "seed", "usable_id",
                          "proposal_index", "case_id"})
    for fn in (SP2.rescue_beam, SP2.side_rescue_seeds, SP2.g1_rescue_seeds):
        got = set(inspect.signature(fn).parameters)
        assert not (got & {"frame_id", "seed", "usable_id", "case_id"})


def test_same_plan_for_different_frames_with_identical_inputs():
    """입력이 같으면 어느 frame 이든 계획이 같다 (frame 별 특례 없음)."""
    log = [cand(occluder_side_match=False)]
    plans = [SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                        mode="side_g1") for _ in range(3)]
    assert plans[0] == plans[1] == plans[2]


# 19 ------------------------------------------------------ resume 결정성
def test_plan_identical_after_simulated_resume():
    log = [cand(occluder_side_match=False, u_offset=0.1 * i,
                object_visible_centroid_px=[100.0 + i, 60.0])
           for i in range(3)]
    first = SP2.constraint_rescue_plan(log, TARGET_BBOX, "left", COARSE,
                                       mode="side_g1")
    reloaded = SP2.constraint_rescue_plan(list(log), tuple(TARGET_BBOX), "left",
                                          tuple(COARSE), mode="side_g1")
    assert first == reloaded


# 20 ------------------------------------------------------- default OFF
def test_feature_defaults_to_off():
    assert SP2.CONSTRAINT_RESCUE_DEFAULT_MODE == "off"
    plan = SP2.constraint_rescue_plan([cand(occluder_side_match=False)],
                                      TARGET_BBOX, "left", COARSE)
    assert plan["evaluations"] == [] and plan["beam"] == []


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        SP2.constraint_rescue_plan([], TARGET_BBOX, "left", COARSE,
                                   mode="everything")


# 21 --------------------------------------------------- public mask 불변
def test_public_mask_profile_unchanged():
    import mask_profiles as MP

    assert MP.MASK_PROFILES == ("full-audit", "public")
    assert tuple(MP.mask_stages("public")) == ("m0", "m4")
    paths = MP.frame_mask_paths("out", 0, "public")
    assert sorted(paths) == ["m0", "m4"]
    assert sorted(os.path.basename(os.path.dirname(p))
                  for p in paths.values()) == ["mask_amodal", "mask_visible"]


# ---------------------------------------------------------------------------
# 평가 前 (plan, offset) dedup — primary 격자의 (0,0,0) 재평가 제거
# ---------------------------------------------------------------------------
DEDUP_PLAN = {"obj_name": "Dist_box", "center": [1.0, 2.0, 0.5], "yaw_rad": 0.25}
ORIGIN = (0.0, 0.0, 0.0, 0.0)


def test_planned_offset_key_is_stable_for_the_same_plan_and_offset():
    assert (SP2.planned_offset_key(DEDUP_PLAN, ORIGIN)
            == SP2.planned_offset_key(dict(DEDUP_PLAN), ORIGIN))


def test_planned_offset_key_separates_different_offsets():
    assert (SP2.planned_offset_key(DEDUP_PLAN, ORIGIN)
            != SP2.planned_offset_key(DEDUP_PLAN, (0.30, 0.0, 0.0, 0.0)))


def test_planned_offset_key_separates_different_plan_centers():
    moved = dict(DEDUP_PLAN, center=[1.0, 2.0, 0.6])
    assert (SP2.planned_offset_key(DEDUP_PLAN, ORIGIN)
            != SP2.planned_offset_key(moved, ORIGIN))


def test_planned_offset_key_separates_different_plan_yaw():
    turned = dict(DEDUP_PLAN, yaw_rad=0.75)
    assert (SP2.planned_offset_key(DEDUP_PLAN, ORIGIN)
            != SP2.planned_offset_key(turned, ORIGIN))


def test_dedup_drops_an_already_evaluated_offset():
    seen = {SP2.planned_offset_key(DEDUP_PLAN, ORIGIN)}
    kept, keys = SP2.dedup_candidate_offsets(
        DEDUP_PLAN, (ORIGIN, (0.30, 0.0, 0.0, 0.0)), seen)
    assert kept == ((0.30, 0.0, 0.0, 0.0),)
    assert len(keys) == 1


def test_dedup_drops_repeats_inside_one_stage():
    kept, _ = SP2.dedup_candidate_offsets(
        DEDUP_PLAN, ((0.1, 0.0, 0.0, 0.0), (0.1, 0.0, 0.0, 0.0)), set())
    assert kept == ((0.1, 0.0, 0.0, 0.0),)


def test_dedup_keeps_everything_when_nothing_was_evaluated():
    offsets = (ORIGIN, (0.30, 0.0, 0.35, 0.0))
    kept, keys = SP2.dedup_candidate_offsets(DEDUP_PLAN, offsets, set())
    assert kept == offsets
    assert len(keys) == 2


def test_primary_grid_after_preprobe_loses_exactly_the_origin():
    """실측 근거: primary 후보의 11.1% 가 preprobe 와 같은 (0,0,0) 재평가였다."""
    primary = SP2.explicit_search_schedule()["primary"]["candidates"]
    assert ORIGIN in primary
    seen = {SP2.planned_offset_key(DEDUP_PLAN, ORIGIN)}
    kept, _ = SP2.dedup_candidate_offsets(DEDUP_PLAN, primary, seen)
    assert len(kept) == len(primary) - 1
    assert ORIGIN not in kept


def test_dedup_returns_keys_that_match_planned_offset_key():
    offsets = (ORIGIN, (0.30, 0.0, 0.0, 0.0))
    kept, keys = SP2.dedup_candidate_offsets(DEDUP_PLAN, offsets, set())
    assert list(keys) == [SP2.planned_offset_key(DEDUP_PLAN, o) for o in kept]

# ---------------------------------------------------------------------------
# 팔레트 치수 랜덤화 — KS 근처가 많고 벗어날수록 드문 종 모양, 균등 스케일
# ---------------------------------------------------------------------------
import random as _random


def test_scale_ratio_is_deterministic_for_a_given_seed():
    a = SP2.sample_pallet_scale_ratio(_random.Random(1234))
    b = SP2.sample_pallet_scale_ratio(_random.Random(1234))
    assert a == b


def test_scale_ratio_stays_inside_the_truncation_bound():
    rng = _random.Random(7)
    for _ in range(2000):
        r = SP2.sample_pallet_scale_ratio(rng)
        assert abs(r - 1.0) <= SP2.PALLET_SCALE_JITTER_MAX + 1e-12


def test_scale_ratio_concentrates_near_one():
    """종 모양이므로 ±1 sigma 안이 과반이어야 한다."""
    rng = _random.Random(11)
    vals = [SP2.sample_pallet_scale_ratio(rng) for _ in range(4000)]
    near = sum(1 for v in vals
               if abs(v - 1.0) <= SP2.PALLET_SCALE_JITTER_SIGMA)
    assert near / len(vals) > 0.60
    far = sum(1 for v in vals
              if abs(v - 1.0) > SP2.PALLET_SCALE_JITTER_SIGMA * 1.5)
    assert far / len(vals) < 0.20


def test_scale_ratio_mean_is_centred_on_the_spec():
    rng = _random.Random(99)
    vals = [SP2.sample_pallet_scale_ratio(rng) for _ in range(4000)]
    assert abs(sum(vals) / len(vals) - 1.0) < 0.01


def test_zero_sigma_disables_the_jitter():
    assert SP2.sample_pallet_scale_ratio(_random.Random(3), sigma=0.0) == 1.0


def test_scaled_target_dims_is_uniform():
    """균등 배율이라 종횡비가 보존돼야 한다 — 비균등이면 형상이 왜곡된다."""
    base = (1.1, 0.15, 1.1)
    out = SP2.scaled_target_dims(base, 1.2)
    assert out == pytest.approx((1.32, 0.18, 1.32))
    assert out[0] / out[2] == pytest.approx(base[0] / base[2])
    assert out[0] / out[1] == pytest.approx(base[0] / base[1])


def test_scaled_target_dims_rejects_non_positive_ratio():
    with pytest.raises(ValueError):
        SP2.scaled_target_dims((1.1, 0.15, 1.1), 0.0)


# --- 형상 지터 (축별 배율) --------------------------------------------------

def test_shape_ratios_are_deterministic_for_a_seed():
    a = SP2.sample_pallet_shape_ratios(_random.Random(99))
    b = SP2.sample_pallet_shape_ratios(_random.Random(99))
    assert a == b
    assert len(a) == 3


def test_shape_ratios_preserve_size():
    """기하평균이 1 이어야 크기는 그대로고 비율만 바뀐다.

    크기는 sample_pallet_scale_ratio 가 따로 담당한다 — 여기서 크기까지 흔들면
    어느 쪽이 무엇을 바꿨는지 사후에 분리할 수 없다.
    """
    rng = _random.Random(2026)
    for _ in range(500):
        sx, sy, sz = SP2.sample_pallet_shape_ratios(rng)
        assert (sx * sy * sz) ** (1.0 / 3.0) == pytest.approx(1.0, abs=0.02)


def test_shape_ratios_respect_the_truncation_bound():
    rng = _random.Random(7)
    for _ in range(2000):
        for v in SP2.sample_pallet_shape_ratios(rng):
            assert 1.0 - SP2.PALLET_SHAPE_JITTER_MAX - 1e-9 <= v
            assert v <= 1.0 + SP2.PALLET_SHAPE_JITTER_MAX + 1e-9


def test_shape_ratios_actually_change_the_aspect():
    """이 지터의 존재 이유 — 균등 배율만으로는 종횡비가 에셋 고유값에 고정된다."""
    rng = _random.Random(31337)
    base_long, base_short = 1.32, 1.10          # 종횡비 1.20 인 에셋
    aspects = set()
    for _ in range(400):
        sx, _sy, sz = SP2.sample_pallet_shape_ratios(rng)
        aspects.add(round((base_long * sx) / (base_short * sz), 3))
    # 균등 배율만 쓰던 시절 실측 300장의 종횡비 고유값은 정확히 3개였다(1.18/1.20/1.50).
    # 소수 3자리 반올림 때문에 값이 겹치므로 400 표본 전부가 달라지지는 않지만,
    # 3개와 100개 이상은 이산/연속을 가르기에 충분하다.
    assert len(aspects) > 100
    assert max(aspects) - min(aspects) > 0.3     # 1.18~1.50 이산 간격보다 넓게 퍼진다


def test_shape_jitter_disabled_by_zero_sigma():
    assert SP2.sample_pallet_shape_ratios(_random.Random(3), sigma=0.0) == (1.0, 1.0, 1.0)


# --- 정준축 -> 오브젝트축 치환 ------------------------------------------------

def _rot_z90():
    return [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]


def test_axis_permutation_identity():
    eye = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert SP2.axis_permutation_from_matrix(eye) == [0, 1, 2]


def test_axis_permutation_swaps_and_ignores_sign():
    """부호는 배율에 영향이 없다 — 축 대응만 맞으면 된다."""
    assert SP2.axis_permutation_from_matrix(_rot_z90()) == [1, 0, 2]


def test_axis_permutation_rejects_non_permutation():
    """임의 각도 회전은 scale 벡터로 표현 불가 -> None (호출자가 균등으로 되돌아간다)."""
    c = s = 0.7071067811865476           # 45도
    tilted = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
    assert SP2.axis_permutation_from_matrix(tilted) is None


def test_object_shape_scale_moves_ratios_onto_object_axes():
    obj = SP2.object_shape_scale((1.1, 0.9, 1.0), _rot_z90())
    # 정준 X(=1.1) -> 오브젝트 축 1,  정준 Y(=0.9) -> 오브젝트 축 0
    assert obj == pytest.approx((0.9, 1.1, 1.0))


def test_object_shape_scale_returns_none_for_non_permutation():
    c = s = 0.7071067811865476
    tilted = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
    assert SP2.object_shape_scale((1.1, 0.9, 1.0), tilted) is None


def test_real_pallet_rotations_are_all_permutations():
    """ORIENTATION_OVERRIDES 가 전부 90도 배수여야 축별 배율이 성립한다.

    하나라도 임의 각도면 그 팔레트만 조용히 균등으로 되돌아가 형상 지터가
    적용되지 않는다 — 그래서 여기서 못 박는다.
    """
    import numpy as np
    from blender_math import euler_to_rotation_matrix
    r_yz_swap = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float)
    for rot_deg in ((90, 0, 90), (0, 0, 0), (0, 0, 90)):
        canon = r_yz_swap @ euler_to_rotation_matrix(rot_deg)
        assert SP2.axis_permutation_from_matrix(canon) is not None, rot_deg


def test_pallet_stage_seed_exists_and_others_are_unchanged():
    """stage 를 추가해도 기존 stage seed 는 그대로여야 한다 (재현성)."""
    seeds = SP2.derive_stage_seeds(4242)
    assert "pallet" in seeds
    for stage in ("background", "anchor", "cargo", "context", "occluder"):
        assert seeds[stage] == SP2.derive_stage_seeds(4242)[stage]
    assert seeds["pallet"] != seeds["cargo"]

# ---------------------------------------------------------------------------
# 자체가림 — 육면체 코너 8점 (중앙점 제외)
# ---------------------------------------------------------------------------
def _unit_box():
    """canonical_corners_yup 과 같은 부호 배치의 단위 상자."""
    return [(-1, 1, 1), (1, 1, 1), (1, -1, 1), (-1, -1, 1),
            (-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)]


def test_all_eight_corners_are_never_visible():
    """★핵심: 육면체는 한 시점에서 8개가 다 보일 수 없다."""
    box = _unit_box()
    rng = _random.Random(0)
    for _ in range(500):
        cam = (rng.uniform(-30, 30), rng.uniform(-30, 30), rng.uniform(-30, 30))
        if max(abs(c) for c in cam) < 1.5:
            continue                      # 상자 내부는 제외
        m = SP2.self_visible_corner_mask(box, cam)
        assert sum(m) <= 7


def test_corner_view_sees_seven():
    """세 면이 보이는 코너 방향 -> 7개."""
    assert sum(SP2.self_visible_corner_mask(_unit_box(), (10, 10, 10))) == 7


def test_face_on_view_sees_four():
    """한 면만 정면으로 보는 방향 -> 4개."""
    assert sum(SP2.self_visible_corner_mask(_unit_box(), (0, 0, 10))) == 4


def test_edge_view_sees_six():
    """두 면이 보이는 모서리 방향 -> 6개."""
    assert sum(SP2.self_visible_corner_mask(_unit_box(), (10, 0, 10))) == 6


def test_face_on_view_returns_that_faces_corners():
    """+z 정면 -> +z 면의 코너 0,1,2,3 만."""
    m = SP2.self_visible_corner_mask(_unit_box(), (0, 0, 10))
    assert [i for i, v in enumerate(m) if v] == [0, 1, 2, 3]


def test_opposite_views_are_complementary_on_the_far_face():
    """앞뒤에서 보면 각각 반대쪽 면 코너가 빠진다."""
    front = SP2.self_visible_corner_mask(_unit_box(), (0, 0, 10))
    back = SP2.self_visible_corner_mask(_unit_box(), (0, 0, -10))
    assert [i for i, v in enumerate(front) if v] == [0, 1, 2, 3]
    assert [i for i, v in enumerate(back) if v] == [4, 5, 6, 7]


def test_flat_box_like_a_pallet_still_obeys_the_bound():
    """팔레트는 납작하다(1.1 x 1.1 x 0.15) — 그래도 8개는 안 된다."""
    flat = [(-0.55, 0.075, 0.55), (0.55, 0.075, 0.55),
            (0.55, -0.075, 0.55), (-0.55, -0.075, 0.55),
            (-0.55, 0.075, -0.55), (0.55, 0.075, -0.55),
            (0.55, -0.075, -0.55), (-0.55, -0.075, -0.55)]
    rng = _random.Random(7)
    for _ in range(300):
        cam = (rng.uniform(-8, 8), rng.uniform(0.2, 8), rng.uniform(-8, 8))
        m = SP2.self_visible_corner_mask(flat, cam)
        assert 4 <= sum(m) <= 7


def test_wrong_corner_count_is_rejected():
    with pytest.raises(ValueError):
        SP2.self_visible_corner_mask(_unit_box()[:7], (10, 10, 10))


def test_self_occlusion_is_independent_of_corner_order():
    """★이 파이프라인에는 canonical 순서와 perm_v4 순열이 함께 돈다.
    어떤 순서로 넣어도 '보이는 코너 집합'은 같아야 한다."""
    box = _unit_box()
    cam = (7.0, 3.0, 5.0)
    base = SP2.self_visible_corner_mask(box, cam)
    base_pts = {box[i] for i, v in enumerate(base) if v}
    perm = [1, 5, 6, 2, 0, 4, 7, 3]                  # 실제 label 의 perm_v4
    shuffled = [box[i] for i in perm]
    got = SP2.self_visible_corner_mask(shuffled, cam)
    assert {shuffled[i] for i, v in enumerate(got) if v} == base_pts
    assert sum(got) == sum(base)


# ---------------------------------------------------------------------------
# G1/G2 에 자체가림 반영 — 탐색기와 라벨의 코너 계산을 일치시킨다
# ---------------------------------------------------------------------------
def test_gate_without_self_visible_keeps_old_behaviour():
    """인자를 안 주면 예전과 동일해야 한다 (기존 경로 보호)."""
    m = SP2.external_corner_gate_metrics([True] * 8, [0.0] * 8)
    assert m["V_inframe"] == 8 and m["V_vis"] == 8 and m["G1_pass"] is True


def test_gate_with_self_visible_counts_only_front_corners():
    """뒷면 코너 4개를 빼면 V_inframe 이 8 -> 4 로 준다."""
    self_vis = [True, True, True, True, False, False, False, False]
    m = SP2.external_corner_gate_metrics([True] * 8, [0.0] * 8,
                                         self_visible=self_vis)
    assert m["V_inframe"] == 4
    assert m["V_vis"] == 4
    assert m["G1_pass"] is True          # 4 는 PnP 하한이라 여전히 통과


def test_gate_fails_when_occlusion_eats_a_front_corner():
    """자체가림으로 4개만 남았는데 그중 하나를 외부 가림이 먹으면 G1 탈락."""
    self_vis = [True, True, True, True, False, False, False, False]
    occ = [0.9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    m = SP2.external_corner_gate_metrics([True] * 8, occ, self_visible=self_vis)
    assert m["V_vis"] == 3
    assert m["G1_pass"] is False


def test_gate_ignores_occlusion_on_self_hidden_corners():
    """뒷면 코너가 가려지는 것은 의미가 없다 — ext_occ 에 세면 안 된다."""
    self_vis = [True, True, True, True, False, False, False, False]
    occ = [0.0, 0.0, 0.0, 0.0, 0.9, 0.9, 0.9, 0.9]
    m = SP2.external_corner_gate_metrics([True] * 8, occ, self_visible=self_vis)
    assert m["ext_occ_corners"] == 0
    assert m["V_vis"] == 4


def test_gate_rejects_wrong_self_visible_length():
    with pytest.raises(ValueError):
        SP2.external_corner_gate_metrics([True] * 8, [0.0] * 8,
                                         self_visible=[True] * 7)


def test_centre_occlusion_preserves_corners_and_passes_g1():
    """★사용자 지적: 가운데만 가리면 꼭짓점은 살아 추론 가능해야 한다."""
    self_vis = [True, True, True, True, False, False, False, False]
    occ = [0.1, 0.1, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0]   # 중앙 가림 -> 코너는 낮은 값
    m = SP2.external_corner_gate_metrics([True] * 8, occ, self_visible=self_vis)
    assert m["V_vis"] == 4 and m["G1_pass"] is True
