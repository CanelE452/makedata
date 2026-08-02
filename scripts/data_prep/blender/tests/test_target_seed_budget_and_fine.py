"""§3 target-seed bounded free allowance · §4 near-miss fine refinement (bpy-free).

배경 (2026-08-01 score-gap 감사):
  - G1.5 는 target-seed 를 후보 예산에서 **전부** 뺐다.  recall 은 30/30 이 됐지만
    실패 프레임이 후보를 더 평가하게 됐다(score_callback reject +28.8%).
  - 수락 조건은 4개 불리언의 논리곱이고 `score` 에는 임계가 없다.  따라서
    "near-miss" 는 **목표 오차 하나만** 막고 있는 후보를 뜻한다.  전체 후보의
    6.9% 뿐이며, side/코너/가시성이 함께 막고 있으면 좌표 미세 조정으로 살아나지 않는다.
"""

import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import scene_placement_v2 as SP2  # noqa: E402

TOL = SP2.EXPLICIT_TARGET_ABS_TOLERANCE


def ts(index, u, stage="target-seed", proposal=0, obj="Dist_a"):
    """target-seed 후보 하나 (geometry 는 u 로 구분)."""
    return {"proposal_index": proposal, "stage": stage, "proposal_object": obj,
            "center": [float(u), 0.0, 0.0], "yaw_rad": 0.0,
            "u_offset": float(u), "v_offset": 0.0, "depth_offset": 0.0,
            "yaw_offset": 0.0, "idx": index}


def near(u, error, side=True, visible=40, g1=True, g2=True, reason=None,
         score=-0.1, stage="primary"):
    return {"proposal_index": 0, "stage": stage, "proposal_object": "Dist_a",
            "center": [float(u), 0.0, 0.0], "yaw_rad": 0.0,
            "u_offset": float(u), "v_offset": 0.0, "depth_offset": 0.0,
            "yaw_offset": 0.0, "reason": reason, "score": score,
            "abs_error": float(error), "target_error_ok": error <= TOL,
            "occluder_side_match": side, "object_visible_pixels": visible,
            "candidate_G1_pass": g1, "candidate_G2_pass": g2}


class TargetSeedFreeAllowance(unittest.TestCase):
    def usage(self, log, cap):
        return SP2.target_seed_budget_usage(log, 0, cap)

    def test_cap_zero_makes_every_target_seed_paid(self):
        log = [ts(i, i) for i in range(6)]
        u = self.usage(log, 0)
        self.assertEqual(0, u["target_seed_free_used"])
        self.assertEqual(6, u["target_seed_paid_used"])

    def test_cap_four(self):
        log = [ts(i, i) for i in range(10)]
        u = self.usage(log, 4)
        self.assertEqual(4, u["target_seed_free_used"])
        self.assertEqual(6, u["target_seed_paid_used"])

    def test_cap_eight(self):
        log = [ts(i, i) for i in range(24)]
        u = self.usage(log, 8)
        self.assertEqual(8, u["target_seed_free_used"])
        self.assertEqual(16, u["target_seed_paid_used"])

    def test_cap_twelve(self):
        log = [ts(i, i) for i in range(24)]
        u = self.usage(log, 12)
        self.assertEqual(12, u["target_seed_free_used"])
        self.assertEqual(12, u["target_seed_paid_used"])

    def test_unlimited_matches_g1p5_behaviour(self):
        log = [ts(i, i) for i in range(24)]
        u = self.usage(log, None)
        self.assertEqual(24, u["target_seed_free_used"])
        self.assertEqual(0, u["target_seed_paid_used"])

    def test_duplicate_geometry_does_not_consume_a_new_free_slot(self):
        # 같은 geometry 를 4번 반복 -> unique 1개, cap 1 이어도 전부 free
        log = [ts(i, 0.5) for i in range(4)]
        u = self.usage(log, 1)
        self.assertEqual(1, u["target_seed_unique_count"])
        self.assertEqual(3, u["target_seed_duplicate_count"])
        self.assertEqual(4, u["target_seed_free_used"])
        self.assertEqual(0, u["target_seed_paid_used"])

    def test_duplicate_of_a_paid_key_stays_paid(self):
        log = [ts(0, 0.0), ts(1, 1.0), ts(2, 1.0)]   # unique: 0.0, 1.0
        u = self.usage(log, 1)
        self.assertEqual(1, u["target_seed_free_used"])    # 0.0
        self.assertEqual(2, u["target_seed_paid_used"])    # 1.0 x2

    def test_deterministic_for_the_same_log(self):
        log = [ts(i, i % 5) for i in range(20)]
        self.assertEqual(self.usage(log, 8), self.usage(log, 8))

    def test_general_budget_total_is_unchanged(self):
        """일반 예산이 세는 수 = 비-target-seed 시도 + target-seed 유료분."""
        log = ([ts(i, i) for i in range(10)]
               + [dict(ts(i, i, stage="primary"), reason="score_callback")
                  for i in range(5)])
        self.assertEqual(5, SP2.budgeted_attempt_count(log, 0, None))
        self.assertEqual(5 + 6, SP2.budgeted_attempt_count(log, 0, 4))
        self.assertEqual(5 + 10, SP2.budgeted_attempt_count(log, 0, 0))

    def test_fine_stage_never_consumes_the_general_budget(self):
        log = [dict(ts(i, i, stage=SP2.FINE_STAGE)) for i in range(8)]
        self.assertEqual(0, SP2.budgeted_attempt_count(log, 0, 0))

    def test_only_the_requested_proposal_is_counted(self):
        log = [ts(0, 0.0, proposal=0), ts(1, 1.0, proposal=1)]
        self.assertEqual(1, self.usage(log, None)["target_seed_candidate_count"])


class NearMissSelection(unittest.TestCase):
    def test_far_from_threshold_is_not_selected(self):
        log = [near(0, TOL + 0.5)]
        self.assertIsNone(SP2.select_near_miss_seed(log, 0.05))

    def test_hard_reject_is_never_a_near_miss(self):
        for reason in ("support", "collision", "camera_clearance"):
            log = [near(0, TOL + 0.01, reason=reason)]
            self.assertIsNone(SP2.select_near_miss_seed(log, 0.05), reason)

    def test_side_mismatch_is_not_a_near_miss(self):
        log = [near(0, TOL + 0.01, side=False)]
        self.assertIsNone(SP2.select_near_miss_seed(log, 0.05))

    def test_corner_failure_is_not_a_near_miss(self):
        log = [near(0, TOL + 0.01, g1=False)]
        self.assertIsNone(SP2.select_near_miss_seed(log, 0.05))

    def test_too_few_visible_pixels_is_not_a_near_miss(self):
        log = [near(0, TOL + 0.01, visible=3)]
        self.assertIsNone(SP2.select_near_miss_seed(log, 0.05))

    def test_already_passing_candidate_is_not_a_near_miss(self):
        log = [near(0, TOL - 0.01)]
        self.assertIsNone(SP2.select_near_miss_seed(log, 0.05))

    def test_only_target_error_blocked_within_threshold_is_selected(self):
        log = [near(0, TOL + 0.02)]
        seed = SP2.select_near_miss_seed(log, 0.05)
        self.assertIsNotNone(seed)
        self.assertAlmostEqual(-0.02, seed["score_margin"], places=9)

    def test_one_candidate_per_case_by_score_then_order_then_name(self):
        log = [near(0, TOL + 0.01, score=-0.30),
               near(1, TOL + 0.01, score=-0.10),
               near(2, TOL + 0.01, score=-0.10)]
        seed = SP2.select_near_miss_seed(log, 0.05)
        self.assertEqual(1, seed["order"])          # score 동률이면 먼저 나온 것

    def test_threshold_none_disables_selection(self):
        self.assertIsNone(SP2.select_near_miss_seed([near(0, TOL + 0.01)], None))

    def test_deterministic(self):
        log = [near(i, TOL + 0.01 + i * 1e-6, score=-0.1) for i in range(5)]
        self.assertEqual(SP2.select_near_miss_seed(log, 0.05)["order"],
                         SP2.select_near_miss_seed(log, 0.05)["order"])


class FineOffsets(unittest.TestCase):
    def test_offsets_are_half_the_coarse_step(self):
        plane, depth = SP2.fine_refinement_offsets(0.15, 0.15, 0.175)
        self.assertEqual(4, len(plane))
        self.assertEqual(2, len(depth))
        self.assertAlmostEqual(-0.075, plane[0][0])
        self.assertAlmostEqual(0.075, plane[1][0])
        self.assertAlmostEqual(-0.075, plane[2][1])
        self.assertAlmostEqual(-0.0875, depth[0][2])

    def test_total_stays_within_the_fine_cap(self):
        plane, depth = SP2.fine_refinement_offsets(0.15, 0.15, 0.175)
        self.assertLessEqual(len(plane) + len(depth), SP2.FINE_MAX_EVALS)

    def test_no_full_grid_is_produced(self):
        """축별 이웃만 — u 와 v 를 동시에 흔든 조합이 없다."""
        plane, _ = SP2.fine_refinement_offsets(0.15, 0.15, 0.175)
        for u, v, d, yaw in plane:
            self.assertTrue((u == 0.0) or (v == 0.0))
            self.assertEqual(0.0, d)
            self.assertEqual(0.0, yaw)

    def test_deterministic(self):
        self.assertEqual(SP2.fine_refinement_offsets(0.15, 0.15, 0.175),
                         SP2.fine_refinement_offsets(0.15, 0.15, 0.175))


class RealizeWiring(unittest.TestCase):
    """v2_realize 는 bpy 를 import 하므로 소스로 계약을 고정한다."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.find_spec("v2_realize")
        cls.src = open(spec.origin, encoding="utf-8").read()

    def test_budget_uses_the_bounded_allowance(self):
        self.assertIn("SP2.budgeted_attempt_count(", self.src)
        self.assertIn('SEARCH_TUNING["target_seed_free_cap"]', self.src)

    def test_fine_stage_is_capped_and_off_budget(self):
        self.assertIn("SP2.FINE_MAX_EVALS - fine_state", self.src)
        self.assertIn("SP2.select_near_miss_seed(", self.src)

    def test_fine_stage_skips_the_general_budget_check(self):
        """일반 예산 검사를 같이 태우면 예산 소진 프레임에서 fine 이 0개를 평가한다."""
        # 고정 창 길이로 자르지 않는다 — 분기 본문이 길어지면 창을 벗어나 오탐한다.
        # 검사할 것은 "fine 분기 본문 안에는 예산 호출이 없다" 하나다.
        start = self.src.index("if stage_name == SP2.FINE_STAGE:")
        else_branch = self.src.index("                else:", start)
        fine_body = self.src[start:else_branch]
        self.assertNotIn(
            "SP2.bounded_candidate_offsets(", fine_body,
            "bounded_candidate_offsets 는 fine 이 아닌 분기에서만 불려야 한다")
        self.assertIn("SP2.bounded_candidate_offsets(", self.src[else_branch:])

    def test_fine_only_runs_when_no_winner_yet(self):
        start = self.src.index("SP2.select_near_miss_seed(")
        head = self.src[max(0, start - 400):start]
        self.assertIn("global_best is None", head)

    def test_tuning_is_recorded_on_every_frame(self):
        self.assertIn('"tuning": dict(SEARCH_TUNING)', self.src)
        self.assertIn("def set_search_tuning(", self.src)

    def test_default_tuning_reproduces_g1p5(self):
        import re
        block = re.search(r"SEARCH_TUNING = \{(.*?)\}", self.src, re.S).group(1)
        self.assertIn('"target_seed_free_cap": None', block)
        self.assertIn('"near_miss_gap_threshold": None', block)


if __name__ == "__main__":
    unittest.main()
