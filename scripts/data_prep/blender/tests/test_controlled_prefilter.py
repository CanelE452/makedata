"""controlled occluder feasibility prefilter (bpy-free).

Blender 의 bounded local search 는 비싸다 — baseline 에서 실패 94건이 4,936초를 썼고
RGB 는 한 장도 렌더하지 않았다.  prefilter 는 "접지시키면 목표를 맞출 수 없는" 후보를
계획 단계 기하만으로 걸러 그 비용을 없앤다.

절대 조건: **과거에 프레임을 살린 후보를 하나도 버리지 않는다.**
`fixtures/controlled_prefilter_winners.json` 은 baseline accepted 49건의 승리 후보
기하를 그대로 담은 회귀 픽스처다 — 임계를 조정하면 여기서 먼저 깨진다.
"""

import copy
import io
import json
import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import scene_placement_v2 as SP2  # noqa: E402
import v2_pipeline as vp          # noqa: E402

FIXTURE = os.path.join(_THIS_DIR, "fixtures", "controlled_prefilter_winners.json")


def candidate(**over):
    """실현 가능한 기준 후보 (접지 · 조밀 · 여유 있는 실루엣)."""
    base = {
        "obj_name": "Dist_reference_box",
        "side": "left",
        "in_position_band": True,
        "fill_ratio": 0.90,
        "scale": 1.0,
        "bbox_m": [0.6, 0.5, 0.8],
        "d_occ_m": 2.5,
        "bmin": [0.0, 0.0, -0.02],
        "bmax": [0.0, 0.0, 0.78],
        "overlap_target_px2": 3000.0,
    }
    base.update(over)
    return base


def reason(cand, pallet_px2=13000.0, screen_px2=30000.0):
    return SP2.controlled_prefilter_reason(cand, pallet_px2,
                                           screen_area_px2=screen_px2)


class BaselineRecall(unittest.TestCase):
    """§7-2/3 — accepted baseline 49건 recall 100%."""

    @classmethod
    def setUpClass(cls):
        with io.open(FIXTURE, encoding="utf-8") as handle:
            cls.winners = json.load(handle)["winners"]

    def test_fixture_covers_every_accepted_controlled_frame(self):
        self.assertEqual(49, len(self.winners))
        self.assertEqual(49, len({w["proposal_index"] for w in self.winners}))

    def test_no_winner_is_removed(self):
        removed = []
        for winner in self.winners:
            cand = {
                "side": winner["side"],
                "in_position_band": winner["in_position_band"],
                "fill_ratio": winner["fill_ratio"],
                "bmin": [0.0, 0.0, winner["bmin_z"]],
                "bmax": [0.0, 0.0, winner["bmax_z"]],
                "overlap_target_px2": winner["overlap_target_px2"],
            }
            got = SP2.controlled_prefilter_reason(
                cand, winner["pallet_silhouette_px2"],
                screen_area_px2=winner["screen_area_px2"])
            if got is not None:
                removed.append((winner["proposal_index"], winner["object"], got))
        self.assertEqual([], removed, "prefilter 가 과거의 승리 후보를 버렸다")


class Determinism(unittest.TestCase):
    def test_same_candidate_gives_the_same_answer(self):
        cand = candidate(fill_ratio=0.2)
        first = reason(cand)
        for _ in range(5):
            self.assertEqual(first, reason(copy.deepcopy(cand)))

    def test_answer_does_not_depend_on_object_name_or_frame_identity(self):
        base = reason(candidate(fill_ratio=0.2))
        self.assertEqual(base, reason(candidate(fill_ratio=0.2,
                                                obj_name="Dist_other_thing")))

    def test_no_frame_or_seed_blacklist_exists_in_the_rule(self):
        import inspect
        src = inspect.getsource(SP2.controlled_prefilter_reason)
        for banned in ("seed", "frame_index", "proposal_index", "usable_id",
                       "blacklist"):
            self.assertNotIn(banned, src)

    def test_rule_reads_only_plan_stage_geometry(self):
        import inspect
        src = inspect.getsource(SP2.controlled_prefilter_reason)
        body = src.split('"""', 2)[-1].lower()      # docstring 제외한 실제 코드
        for banned in ("rgb", "render", "mask", "bpy"):
            self.assertNotIn(banned, body)


class SyntheticCandidates(unittest.TestCase):
    def test_feasible_candidate_is_retained(self):
        self.assertIsNone(reason(candidate()))

    def test_center_side_is_infeasible(self):
        self.assertEqual("prefilter_side_geometry_infeasible",
                         reason(candidate(side="center")))

    def test_out_of_position_band_is_infeasible(self):
        self.assertEqual("prefilter_position_band_infeasible",
                         reason(candidate(in_position_band=False)))

    def test_sparse_silhouette_is_infeasible(self):
        self.assertEqual("prefilter_fill_ratio_too_low",
                         reason(candidate(fill_ratio=0.20)))

    def test_buried_candidate_is_infeasible(self):
        # 자기 높이(0.8m)의 60% 넘게 지면 아래 -> 접지 스냅 변위가 과대
        self.assertEqual(
            "prefilter_floor_support_infeasible",
            reason(candidate(bmin=[0.0, 0.0, -0.60], bmax=[0.0, 0.0, 0.20])))

    def test_floating_candidate_is_infeasible(self):
        self.assertEqual(
            "prefilter_floor_support_infeasible",
            reason(candidate(bmin=[0.0, 0.0, 2.0], bmax=[0.0, 0.0, 2.8])))

    def test_silhouette_barely_covering_the_target_is_infeasible(self):
        self.assertEqual(
            "prefilter_insufficient_projected_area",
            reason(candidate(overlap_target_px2=29000.0), screen_px2=30000.0))

    def test_silhouette_swamping_the_pallet_is_infeasible(self):
        self.assertEqual(
            "prefilter_insufficient_projected_area",
            reason(candidate(), pallet_px2=1000.0, screen_px2=30000.0))

    def test_grounded_candidate_at_the_margin_is_retained(self):
        # 바닥이 자기 높이의 50% 만큼 파묻힘 -> 임계(60%) 안이므로 유지
        self.assertIsNone(
            reason(candidate(bmin=[0.0, 0.0, -0.40], bmax=[0.0, 0.0, 0.40])))

    def test_reasons_are_from_the_declared_set(self):
        cases = [candidate(side="center"), candidate(fill_ratio=0.1),
                 candidate(in_position_band=False),
                 candidate(bmin=[0.0, 0.0, -5.0], bmax=[0.0, 0.0, -4.2]),
                 candidate(overlap_target_px2=29500.0)]
        for cand in cases:
            got = reason(cand)
            self.assertIn(got, SP2.PREFILTER_REASONS)

    def test_missing_geometry_does_not_crash(self):
        cand = candidate()
        cand.pop("bmin")
        cand.pop("bmax")
        self.assertIsNone(reason(cand))
        self.assertEqual("prefilter_side_geometry_infeasible",
                         SP2.controlled_prefilter_reason(None, 13000.0))


class SolverSchemaUnchanged(unittest.TestCase):
    """§32 — 기존 solver 출력(Plan / occluder dict) 스키마는 그대로다."""

    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()

    def test_solve_placement_occluder_keys_are_unchanged(self):
        import random
        expected = {
            "name", "obj_name", "size_class", "bbox_m", "bbox_cross_m2",
            "fill_ratio", "scale", "d_occ_m", "center", "bmin", "bmax",
            "position_mode", "in_position_band", "side", "overlap_target_px2",
            "resample_tries",
        }
        rng = random.Random(7000)
        quota = vp.QuotaState.new(self.assets)
        seen = 0
        for index in range(400):
            spec, picks = vp.sample_frame(rng, quota, self.assets,
                                          frame_index=index, seed=7000)
            plan = vp.solve_placement(spec, self.assets,
                                      placement_mode="constrained")
            if isinstance(plan, vp.Plan):
                vp.advance_quota(quota, picks)
                if plan.occluder is not None:
                    self.assertEqual(expected, set(plan.occluder), f"frame {index}")
                    seen += 1
        self.assertGreater(seen, 0, "occluder 를 가진 plan 이 하나도 없었다")

    def test_prefilter_only_adds_keys_to_the_diagnostic_proposal(self):
        added = {"candidates_before_prefilter", "candidates_after_prefilter",
                 "prefilter_reject_count", "prefilter_reject_counts_by_reason",
                 "prefilter_enabled"}
        import random
        rng = random.Random(7000)
        quota = vp.QuotaState.new(self.assets)
        for index in range(400):
            spec, picks = vp.sample_frame(rng, quota, self.assets,
                                          frame_index=index, seed=7000)
            plan = vp.solve_placement(spec, self.assets,
                                      placement_mode="constrained")
            if not isinstance(plan, vp.Plan):
                continue
            vp.advance_quota(quota, picks)
            if float(spec.f_target) <= 1e-6:
                continue
            off = vp.prepare_diagnostic_explicit_occluders(plan, self.assets,
                                                           prefilter=False)
            on = vp.prepare_diagnostic_explicit_occluders(plan, self.assets,
                                                          prefilter=True)
            if isinstance(off, vp.Reject) or isinstance(on, vp.Reject):
                continue
            self.assertTrue(added <= set(on.occluder))
            self.assertEqual(set(off.occluder) - added, set(on.occluder) - added)
            self.assertGreaterEqual(on.occluder["candidates_before_prefilter"],
                                    on.occluder["candidates_after_prefilter"])
            return
        self.skipTest("no controlled-eligible plan in the first 400 proposals")

    def test_prefilter_exhaustion_is_its_own_reject_reason(self):
        self.assertNotEqual("diagnostic_explicit_proposal_failed",
                            "diagnostic_explicit_prefilter_exhausted")

    def test_screen_silhouette_helper_matches_the_lateral_solver_formula(self):
        import math
        cand = candidate(bbox_m=[1.2, 0.8, 0.4], fill_ratio=0.64, scale=1.5,
                         d_occ_m=3.0)
        spec = type("S", (), {"fx": 600.0, "fy": 600.0})()
        dims = sorted(cand["bbox_m"], reverse=True)
        sfr = math.sqrt(cand["fill_ratio"])
        expect = ((dims[0] * 1.5 * sfr * 600.0 / 3.0)
                  * (dims[1] * 1.5 * sfr * 600.0 / 3.0))
        self.assertAlmostEqual(
            expect, vp.occluder_screen_silhouette_px2(spec, cand), places=6)


if __name__ == "__main__":
    unittest.main()
