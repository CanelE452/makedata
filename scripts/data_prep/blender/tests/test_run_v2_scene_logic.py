import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace


RUNNER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "run_v2_scene_logic.py",
    )
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_v2_scene_logic", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plans(specs):
    plans = []
    for index, values in enumerate(specs):
        f_target, elevation_deg, *rest = values
        projected_size = rest[1] if len(rest) > 1 else None
        has_occluder = bool(rest[2]) if len(rest) > 2 else False
        plans.append(
            SimpleNamespace(
                spec=SimpleNamespace(
                    frame_index=index,
                    f_target=f_target,
                    elevation_deg=elevation_deg,
                    proj_size_ratio=projected_size,
                ),
                v_probe=rest[0] if rest else 6,
                occluder={"side": "right"} if has_occluder else None,
            )
        )
    return plans


class SceneLogicRunnerScheduleTests(unittest.TestCase):
    def test_smoke_schedule_has_five_frames_per_mode(self):
        runner = _load_runner()
        modes = [runner.diagnostic_mode_for_index(i, 20) for i in range(20)]
        self.assertEqual(
            {
                "clean-static": 5,
                "cargo-only": 5,
                "context-rich": 5,
                "controlled-occlusion": 5,
            },
            {mode: modes.count(mode) for mode in set(modes)},
        )

    def test_pilot_schedule_has_requested_100_100_150_150_strata(self):
        runner = _load_runner()
        modes = [runner.diagnostic_mode_for_index(i, 500) for i in range(500)]
        self.assertEqual(100, modes.count("clean-static"))
        self.assertEqual(100, modes.count("cargo-only"))
        self.assertEqual(150, modes.count("context-rich"))
        self.assertEqual(150, modes.count("controlled-occlusion"))

    def test_plan_aware_smoke_schedule_prefers_feasible_controlled_plans(self):
        runner = _load_runner()
        plans = _plans(
            [(0.20, 20.0)] * 5
            + [(0.0, 20.0)] * 10
            + [(0.20, 70.0)] * 5
        )
        original_order = [id(plan) for plan in plans]
        original_specs = [
            (
                plan.spec.frame_index,
                plan.spec.f_target,
                plan.spec.elevation_deg,
            )
            for plan in plans
        ]

        modes = runner.allocate_diagnostic_modes_for_plans(
            plans,
            n=20,
            seed=7500,
        )

        self.assertEqual(20, len(modes))
        self.assertEqual(5, modes.count("clean-static"))
        self.assertEqual(5, modes.count("cargo-only"))
        self.assertEqual(5, modes.count("context-rich"))
        self.assertEqual(5, modes.count("controlled-occlusion"))
        controlled = [index for index, mode in enumerate(modes)
                      if mode == "controlled-occlusion"]
        self.assertEqual(set(range(5)), set(controlled))
        self.assertTrue(
            all(
                plans[index].spec.f_target > 0
                and plans[index].spec.elevation_deg < 60
                for index in controlled
            )
        )
        self.assertEqual(original_order, [id(plan) for plan in plans])
        self.assertEqual(
            original_specs,
            [
                (
                    plan.spec.frame_index,
                    plan.spec.f_target,
                    plan.spec.elevation_deg,
                )
                for plan in plans
            ],
        )

    def test_plan_aware_schedule_is_deterministic_and_keeps_pilot_counts(self):
        runner = _load_runner()
        specs = [
            (0.20, 20.0) if index < 200
            else (0.20, 70.0) if index < 350
            else (0.0, 20.0)
            for index in range(500)
        ]
        plans = _plans(specs)

        first = runner.allocate_diagnostic_modes_for_plans(
            plans,
            n=500,
            seed=7500,
        )
        second = runner.allocate_diagnostic_modes_for_plans(
            plans,
            n=500,
            seed=7500,
        )

        self.assertEqual(first, second)
        self.assertEqual(100, first.count("clean-static"))
        self.assertEqual(100, first.count("cargo-only"))
        self.assertEqual(150, first.count("context-rich"))
        self.assertEqual(150, first.count("controlled-occlusion"))
        controlled = [index for index, mode in enumerate(first)
                      if mode == "controlled-occlusion"]
        self.assertTrue(
            all(
                plans[index].spec.f_target > 0
                and plans[index].spec.elevation_deg < 60
                for index in controlled
            )
        )

    def test_plan_aware_schedule_prefers_robust_corner_capacity(self):
        runner = _load_runner()
        plans = _plans(
            [(0.20, 20.0, 5)] * 5
            + [(0.20, 20.0, 6)] * 5
            + [(0.0, 20.0, 8)] * 10
        )

        modes = runner.allocate_diagnostic_modes_for_plans(
            plans,
            n=20,
            seed=7500,
        )

        controlled = {
            index
            for index, mode in enumerate(modes)
            if mode == "controlled-occlusion"
        }
        self.assertEqual(set(range(5, 10)), controlled)
        self.assertTrue(all(plans[index].v_probe >= 6 for index in controlled))

    def test_plan_aware_schedule_breaks_feasibility_ties_with_robust_geometry(self):
        runner = _load_runner()
        plans = _plans(
            [
                (0.20, 20.0, 6, 0.20, True),
                (0.20, 35.0, 8, 0.10, False),
                (0.20, 25.0, 6, 0.20, False),
                (0.20, 2.0, 6, 0.09, False),
                (0.20, 5.0, 8, 0.02, False),
                (0.20, 15.0, 7, 0.60, True),
                (0.20, 22.0, 6, 0.20, True),
            ]
            + [(0.0, 20.0, 8, 0.20, False)] * 13
        )

        modes = runner.allocate_diagnostic_modes_for_plans(
            plans,
            n=20,
            seed=7500,
        )

        controlled = {
            index
            for index, mode in enumerate(modes)
            if mode == "controlled-occlusion"
        }
        self.assertEqual({0, 1, 2, 5, 6}, controlled)

    def test_chunk_indices_are_bounded_and_non_overlapping(self):
        runner = _load_runner()
        chunks = [runner.chunk_indices(500, start, 100) for start in range(0, 500, 100)]
        flattened = [idx for chunk in chunks for idx in chunk]
        self.assertEqual(list(range(500)), flattened)
        self.assertEqual([], runner.chunk_indices(500, 500, 100))
        self.assertEqual([498, 499], runner.chunk_indices(500, 498, 100))

    def test_unsupported_diagnostic_size_is_rejected(self):
        runner = _load_runner()
        with self.assertRaisesRegex(ValueError, "20 or 500"):
            runner.diagnostic_mode_for_index(0, 100)

    def test_label_json_serialization_preserves_none_and_numpy_values(self):
        import numpy as np

        runner = _load_runner()
        payload = {
            "optional_visibility": None,
            "point": np.asarray([1.25, 2.5], dtype=np.float32),
            "count": np.int64(3),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "label.json")
            runner._write_json(path, payload)
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)

        self.assertIsNone(loaded["optional_visibility"])
        self.assertEqual([1.25, 2.5], loaded["point"])
        self.assertEqual(3, loaded["count"])

    def test_frame_seed_is_repeatable_and_frame_specific(self):
        runner = _load_runner()
        first = runner._frame_seed(7500, 18, 19)
        self.assertEqual(first, runner._frame_seed(7500, 18, 19))
        self.assertNotEqual(first, runner._frame_seed(7500, 19, 19))
        self.assertNotEqual(first, runner._frame_seed(7501, 18, 19))

    def test_records_snapshot_is_atomically_refreshed_in_index_order(self):
        runner = _load_runner()
        write_snapshot = getattr(runner, "_write_records_snapshot", None)

        self.assertTrue(callable(write_snapshot))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            write_snapshot(
                path,
                {
                    7: {"idx": 7, "rendered": True},
                    2: {"idx": 2, "rendered": False},
                },
            )
            with open(path, encoding="utf-8") as handle:
                first = json.load(handle)
            write_snapshot(
                path,
                {
                    7: {"idx": 7, "rendered": True},
                    2: {"idx": 2, "rendered": False},
                    5: {"idx": 5, "rendered": True},
                },
            )
            with open(path, encoding="utf-8") as handle:
                second = json.load(handle)

        self.assertEqual([2, 7], [record["idx"] for record in first])
        self.assertEqual([2, 5, 7], [record["idx"] for record in second])

    def test_realize_failure_preserves_explicit_search_diagnostics(self):
        runner = _load_runner()

        class Spec:
            frame_index = 12
            pallet_type = "P1"
            scene_preset = "indoor"
            elevation_deg = 15.0
            azimuth_bin = 2
            v_target = 8
            proj_size_ratio = 0.25
            proj_size_feasible_lower = 0.11
            f_target = 0.20

        class Plan:
            spec = Spec()
            cam_distance_m = 2.64
            camera_distance_limit_m = 10.0

        candidate_log = [
            {
                "idx": 0,
                "reason": "score_callback",
                "score_callback": {
                    "occluder_side_target": "left",
                    "occluder_side_actual": "center",
                    "occluder_side_match": False,
                },
            }
        ]
        record = runner._record_realize_failure(
            16,
            7500,
            "controlled-occlusion",
            Plan(),
            1.5,
            {
                "failure_reason": "bounded_local_search_exhausted",
                "f_explicit_target": 0.20,
                "f_explicit_actual": 0.0,
                "explicit_abs_error": 0.20,
                "explicit_feedback_depth_step_m": 0.42,
                "occluder_feedback_iterations": 9,
                "occluder_side_target": "left",
                "occluder_side_actual": None,
                "explicit_solver_fail_reason": "bounded_local_search_exhausted",
                "explicit_reject_counts_by_reason": {
                    "collision": 3,
                    "score_callback": 6,
                },
                "explicit_candidate_log": candidate_log,
                "explicit_proposal_dimension_rejects": [
                    {"proposal_object": "bad_shape"}
                ],
                "explicit_proposal_dimension_normalizations": [
                    {
                        "proposal_object": "uniform_scale",
                        "normalization_scale": 0.6,
                    }
                ],
            },
        )

        self.assertEqual(0.20, record["f_explicit_target"])
        self.assertEqual(0.0, record["f_explicit_actual"])
        self.assertEqual(0.20, record["explicit_abs_error"])
        self.assertEqual(0.42, record["explicit_feedback_depth_step_m"])
        self.assertEqual(9, record["occluder_feedback_iterations"])
        self.assertEqual("left", record["occluder_side_target"])
        self.assertIsNone(record["occluder_side_actual"])
        self.assertEqual(
            "bounded_local_search_exhausted",
            record["explicit_solver_fail_reason"],
        )
        self.assertEqual(
            {"collision": 3, "score_callback": 6},
            record["explicit_reject_counts_by_reason"],
        )
        self.assertEqual(candidate_log, record["explicit_candidate_log"])
        self.assertEqual(
            [{"proposal_object": "bad_shape"}],
            record["explicit_proposal_dimension_rejects"],
        )
        self.assertEqual(
            [
                {
                    "proposal_object": "uniform_scale",
                    "normalization_scale": 0.6,
                }
            ],
            record["explicit_proposal_dimension_normalizations"],
        )

    def test_realize_failure_preserves_scene_assembly_diagnostics_for_eda(self):
        runner = _load_runner()

        class Spec:
            frame_index = 12
            pallet_type = "P1"
            scene_preset = "indoor"
            elevation_deg = 15.0
            azimuth_bin = 2
            v_target = 8
            proj_size_ratio = 0.25
            proj_size_feasible_lower = 0.11
            f_target = 0.20

        class Plan:
            spec = Spec()
            cam_distance_m = 2.64
            camera_distance_limit_m = 10.0

        expected = {
            "anchor_translation": [-8.5, -3.0, 0.0],
            "n_context_requested": 4,
            "n_context_placed": 3,
            "n_context_visible": 2,
            "context_visible_pixel_ratio": 0.18,
            "context_screen_area_ratio": 0.22,
            "context_placement_attempts": 31,
            "context_reject_counts_by_reason": {
                "collision": 9,
                "visibility": 4,
            },
            "n_cargo_requested": 2,
            "n_cargo_placed": 1,
            "cargo_placement_attempts": 7,
            "cargo_support_pass": True,
            "cargo_collision_pass": True,
            "front_visibility_after_cargo": 0.81,
            "left_opening_visibility_after_cargo": 0.74,
            "right_opening_visibility_after_cargo": 0.76,
            "camera_clearance_pass": True,
            "pallet_support_pass": True,
            "context_support_pass": True,
            "tested_collision_pairs": 12,
            "broad_phase_hits": 3,
            "exact_collision_hits": [],
            "collision_reject_reason": None,
            "pallet_obstacle_collision_count": 0,
            "cargo_collision_count": 0,
            "context_context_collision_count": 0,
            "explicit_reservation_count": 2,
            "explicit_reservations": [
                {
                    "proposal_object": "screen",
                    "center": [-8.2, -3.4, 0.8],
                },
                {
                    "proposal_object": "sign",
                    "center": [-8.0, -3.1, 0.6],
                },
            ],
            "stage_runtime_s": {
                "anchor": 0.4,
                "cargo": 0.2,
                "context": 1.3,
                "explicit": 8.6,
            },
        }
        record = runner._record_realize_failure(
            16,
            7500,
            "controlled-occlusion",
            Plan(),
            10.75,
            {
                "failure_reason": "bounded_local_search_exhausted",
                **expected,
            },
        )

        for key, value in expected.items():
            self.assertEqual(value, record.get(key), key)
        self.assertEqual(10.75, record["runtime_s"])


if __name__ == "__main__":
    unittest.main()
