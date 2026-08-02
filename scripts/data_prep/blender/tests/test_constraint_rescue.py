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
