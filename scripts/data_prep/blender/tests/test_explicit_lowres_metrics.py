"""explicit 저해상도 품질 지표 + 탐색 계측 + 단계 순서 (bpy-free).

배경: public 프로필은 M1~M3 를 저장하지 않아 마스크 분해로 `f_explicit` 을 얻을 수
없다.  이전 단계에서 controlled 품질 게이트가 그 이유로 BLOCKED 였고, 그때
`f_total`(= cargo/context/static 이 섞인 전체 가림률)로 대체하는 것은 금지됐다.
여기서는 탐색이 이미 찍은 저해상도 holdout 두 장의 차집합에서 **숫자만** 뽑아
품질을 계산할 수 있게 한 계약을 고정한다.
"""

import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import scene_placement_v2 as SP2  # noqa: E402

TARGET = {"visible_pixels": 1200, "bbox_px": [3, 4, 40, 50],
          "centroid_px": [20.5, 30.25], "centroid_norm": [0.2, 0.3]}
ACTUAL = {"visible_pixels": 300, "bbox_px": [5, 6, 20, 30],
          "centroid_px": [12.0, 18.0], "centroid_norm": [0.1, 0.2]}


class LowresMetrics(unittest.TestCase):
    def test_available_when_both_mask_stats_exist(self):
        m = SP2.explicit_lowres_metrics(TARGET, ACTUAL, 0.25, 0.24)
        self.assertTrue(m["explicit_metrics_available"])
        self.assertEqual(1200, m["explicit_target_pixels"])
        self.assertEqual(300, m["explicit_actual_pixels_lowres"])
        self.assertAlmostEqual(0.24, m["f_explicit_actual_lowres"])
        self.assertAlmostEqual(0.01, m["explicit_abs_error_lowres"], places=9)

    def test_centroids_and_bboxes_are_reported_separately(self):
        m = SP2.explicit_lowres_metrics(TARGET, ACTUAL, 0.25, 0.24)
        self.assertEqual(20.5, m["explicit_target_centroid_u"])
        self.assertEqual(30.25, m["explicit_target_centroid_v"])
        self.assertEqual(12.0, m["explicit_actual_centroid_u_lowres"])
        self.assertEqual(18.0, m["explicit_actual_centroid_v_lowres"])
        self.assertEqual([3, 4, 40, 50], m["explicit_target_bbox_u0v0u1v1"])
        self.assertEqual([5, 6, 20, 30],
                         m["explicit_actual_bbox_u0v0u1v1_lowres"])

    def test_unmeasured_is_none_not_zero(self):
        m = SP2.explicit_lowres_metrics(None, None, 0.25, 0.0)
        self.assertFalse(m["explicit_metrics_available"])
        for key, value in m.items():
            if key == "explicit_metrics_available":
                continue
            self.assertIsNone(value, key)

    def test_zero_actual_is_a_real_zero_when_measured(self):
        empty = {"visible_pixels": 0, "bbox_px": None, "centroid_px": None,
                 "centroid_norm": None}
        m = SP2.explicit_lowres_metrics(TARGET, empty, 0.25, 0.0)
        self.assertTrue(m["explicit_metrics_available"])
        self.assertEqual(0, m["explicit_actual_pixels_lowres"])
        self.assertEqual(0.0, m["f_explicit_actual_lowres"])
        self.assertAlmostEqual(0.25, m["explicit_abs_error_lowres"])

    def test_half_measured_is_not_available(self):
        self.assertFalse(SP2.explicit_lowres_metrics(
            TARGET, None, 0.25, 0.2)["explicit_metrics_available"])
        self.assertFalse(SP2.explicit_lowres_metrics(
            None, ACTUAL, 0.25, 0.2)["explicit_metrics_available"])

    def test_field_set_is_exactly_the_declared_contract(self):
        self.assertEqual({
            "explicit_metrics_available", "explicit_target_pixels",
            "explicit_actual_pixels_lowres", "f_explicit_actual_lowres",
            "explicit_abs_error_lowres", "explicit_target_centroid_u",
            "explicit_target_centroid_v", "explicit_actual_centroid_u_lowres",
            "explicit_actual_centroid_v_lowres",
            "explicit_target_bbox_u0v0u1v1",
            "explicit_actual_bbox_u0v0u1v1_lowres",
        }, set(SP2.explicit_lowres_metrics(TARGET, ACTUAL, 0.2, 0.2)))

    def test_f_total_is_never_used_as_a_substitute(self):
        """f_total 은 이 함수의 코드에도, 출력 필드에도 없다 (docstring 의 금지 문구 제외)."""
        import inspect
        src = inspect.getsource(SP2.explicit_lowres_metrics)
        body = src.split('"""', 2)[-1]
        self.assertNotIn("f_total", body)
        self.assertNotIn("mask_area_visible", body)
        self.assertFalse([k for k in SP2.explicit_lowres_metrics(
            TARGET, ACTUAL, 0.2, 0.2) if "total" in k])


class SearchMetrics(unittest.TestCase):
    STATS = {"search_stats": {"search_seed_count": 2, "coarse_eval_count": 11,
                              "fine_eval_count": 4, "best_seed_score": -0.02,
                              "final_seed_score": -0.01,
                              "winning_stage": "target-seed"}}

    def test_reports_every_declared_counter(self):
        m = SP2.explicit_search_metrics(self.STATS)
        self.assertEqual(SP2.EXPLICIT_SEARCH_INIT_STRATEGY,
                         m["search_init_strategy"])
        self.assertEqual(2, m["search_seed_count"])
        self.assertEqual(11, m["coarse_eval_count"])
        # G1.6: refine/feedback/fine 합계는 이름이 바뀌었다 (§4 의 fine 단계 전용
        # `fine_eval_count` 와 충돌하지 않도록).
        self.assertEqual(4, m["refine_feedback_eval_count"])
        self.assertEqual(-0.02, m["best_seed_score"])
        self.assertEqual(-0.01, m["final_seed_score"])
        self.assertEqual("target-seed", m["search_winning_stage"])

    def test_absent_search_reports_none(self):
        m = SP2.explicit_search_metrics(None)
        self.assertTrue(all(value is None for value in m.values()))

    def test_missing_stats_do_not_crash(self):
        m = SP2.explicit_search_metrics({})
        self.assertEqual(SP2.EXPLICIT_SEARCH_INIT_STRATEGY,
                         m["search_init_strategy"])
        self.assertIsNone(m["coarse_eval_count"])


class ContextCornerAfterExplicit(unittest.TestCase):
    """explicit 을 앞으로 옮긴 뒤 코너 기준을 바꿔야 하는 이유를 고정한다."""

    POST = {"V_inframe": 8, "ext_occ_corners": 3, "V_vis": 5}

    def test_reserve_contract_rejects_a_placed_occluder(self):
        """예약 계약은 ext_occ<=1 을 요구한다 — 배치 후에는 성립하지 않는다."""
        self.assertFalse(SP2.explicit_corner_reserve_pass(self.POST))

    def test_no_regression_accepts_the_unchanged_scene(self):
        self.assertTrue(SP2.context_corner_no_regression(dict(self.POST),
                                                         self.POST))

    def test_extra_occluded_corner_is_a_regression(self):
        worse = dict(self.POST, ext_occ_corners=4, V_vis=4)
        self.assertFalse(SP2.context_corner_no_regression(worse, self.POST))

    def test_fewer_visible_corners_is_a_regression(self):
        self.assertFalse(SP2.context_corner_no_regression(
            dict(self.POST, V_vis=4), self.POST))

    def test_improvement_is_allowed(self):
        better = dict(self.POST, ext_occ_corners=2, V_vis=6)
        self.assertTrue(SP2.context_corner_no_regression(better, self.POST))

    def test_realize_uses_the_post_explicit_baseline_when_available(self):
        import importlib.util
        spec = importlib.util.find_spec("v2_realize")
        src = open(spec.origin, encoding="utf-8").read()
        self.assertIn("post_explicit_corner_reserve", src)
        self.assertIn("SP2.context_corner_no_regression(", src)


class StageOrderContract(unittest.TestCase):
    """§3/§4 — 소스에서 계약을 고정한다 (v2_realize 는 bpy 를 import 해 직접 못 부른다)."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.find_spec("v2_realize")
        cls.src = open(spec.origin, encoding="utf-8").read()

    def index(self, needle):
        self.assertIn(needle, self.src, needle)
        return self.src.index(needle)

    def test_explicit_search_runs_before_context_placement(self):
        explicit = self.index('stage_runtime["explicit"] = ')
        context = self.index("context_result = SV2.place_context_objects(")
        self.assertLess(explicit, context,
                        "explicit 탐색이 context 배치보다 먼저 끝나야 한다")

    def test_context_is_skipped_when_explicit_failed(self):
        self.assertIn("if context_requested and not explicit_blocked:", self.src)
        self.assertIn("explicit_blocked = bool(", self.src)

    def test_explicit_baseline_no_longer_includes_context(self):
        start = self.index("explicit_baseline = _lowres_stage_areas(")
        block = self.src[start:start + 400]
        self.assertNotIn("context_objs", block)

    def test_context_budget_hides_the_placed_occluder(self):
        self.assertIn("extra_hide=explicit_placed_objects,", self.src)

    def test_target_seed_stage_runs_immediately_after_preprobe(self):
        preprobe = self.index('"preprobe",')
        target_seed = self.index('"target-seed",')
        gate = self.index('"gate-overlap-refine",')
        primary = self.index('"primary",')
        self.assertLess(preprobe, target_seed)
        self.assertLess(target_seed, gate)
        self.assertLess(target_seed, primary)

    def test_stage_runtime_separates_explicit_prep_from_context(self):
        self.assertIn('stage_runtime["explicit_prep"]', self.src)
        self.assertIn('stage_runtime["context"] = time.perf_counter() - context_t0',
                      self.src)

    def test_no_temporary_explicit_mask_is_written_to_the_output(self):
        start = self.index("explicit_lost_mask = (")
        block = self.src[start:start + 700]
        for banned in ("mask_prefix", "mask_paths", ".save(", "imwrite"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
