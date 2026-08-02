import builtins
import importlib
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock


MODULE_NAME = "scripts.data_prep.blender.scene_placement_v2"
scene = importlib.import_module(MODULE_NAME)


class ScenePlacementImportTests(unittest.TestCase):
    def test_module_imports_without_bpy_or_nonstdlib_dependencies(self):
        imported_names = []
        real_import = builtins.__import__

        def recording_import(name, *args, **kwargs):
            imported_names.append(name)
            return real_import(name, *args, **kwargs)

        sys.modules.pop(MODULE_NAME, None)
        with mock.patch("builtins.__import__", side_effect=recording_import):
            try:
                importlib.import_module(MODULE_NAME)
            except ModuleNotFoundError as exc:
                self.fail(f"bpy-free scene-placement contract is not importable: {exc}")

        attempted_bpy_imports = [
            name for name in imported_names if name == "bpy" or name.startswith("bpy.")
        ]
        self.assertEqual([], attempted_bpy_imports)
        nonstdlib_roots = sorted(
            {
                name.split(".", 1)[0]
                for name in imported_names
                if name.split(".", 1)[0] not in sys.stdlib_module_names
            }
        )
        self.assertEqual([], nonstdlib_roots)


class ImageSpaceContextPoseTests(unittest.TestCase):
    def test_context_poses_are_deterministic_ground_intersections_at_image_sides(self):
        make_poses = getattr(scene, "image_space_context_poses", None)
        self.assertIsNotNone(
            make_poses,
            "scene_placement_v2.image_space_context_poses is missing",
        )
        kwargs = {
            "pallet_center": (0.0, 0.0, 0.075),
            "camera_pos": (0.0, -3.0, 1.5),
            "camera_look": (0.0, 0.0, 0.075),
            "fx": 400.0,
            "fy": 400.0,
            "cx": 320.0,
            "cy": 240.0,
            "image_wh": (640, 480),
            "ground_z": 0.0,
            "seed": 7500,
            "attempts": 18,
        }

        first = make_poses(**kwargs)
        second = make_poses(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(18, len(first))
        for idx, pose in enumerate(first):
            self.assertEqual({"x", "y", "yaw_rad"}, set(pose))
            self.assertGreaterEqual(
                math.hypot(pose["x"], pose["y"]),
                0.70,
            )
            if idx % 2 == 0:
                self.assertLess(pose["x"], 0.0)
            else:
                self.assertGreater(pose["x"], 0.0)


class HdriPoolContractTests(unittest.TestCase):
    def test_constrained_hdri_paths_use_current_files_and_drop_known_bad_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = os.path.join(temp_dir, "valid_warehouse.hdr")
            known_bad = os.path.join(temp_dir, "factory_yard_2k.hdr")
            duplicate = os.path.join(temp_dir, ".", "valid_warehouse.hdr")
            wrong_suffix = os.path.join(temp_dir, "preview.png")
            for path in (valid, known_bad, wrong_suffix):
                with open(path, "wb") as handle:
                    handle.write(b"fixture")

            paths = scene.constrained_hdri_paths(
                [duplicate, known_bad, wrong_suffix, valid],
                excluded_names={"factory_yard_2k.hdr"},
            )

        self.assertEqual([os.path.abspath(valid)], paths)


class ExplicitOccluderSideContractTests(unittest.TestCase):
    def test_candidate_must_match_the_requested_image_side(self):
        match = getattr(scene, "explicit_side_matches", None)

        self.assertIsNotNone(match)
        self.assertTrue(match("left", "left"))
        self.assertTrue(match(None, "center"))
        self.assertFalse(match("left", "center"))
        self.assertFalse(match("bottom", None))
        with self.assertRaises(ValueError):
            match("diagonal", "left")

    def test_positive_explicit_target_fails_closed_without_a_valid_object(self):
        failure = getattr(scene, "explicit_requirement_failure", None)

        self.assertIsNotNone(failure)
        self.assertIsNone(failure(False, True, 0.25, False, "ignored"))
        self.assertIsNone(failure(True, True, 0.0, False, None))
        self.assertIsNone(failure(True, True, 0.25, True, None))
        self.assertEqual(
            "explicit_occluder_missing",
            failure(True, True, 0.25, False, None),
        )
        self.assertEqual(
            "bounded_local_search_exhausted",
            failure(
                True,
                True,
                0.25,
                False,
                "bounded_local_search_exhausted",
            ),
        )
        self.assertEqual(
            "explicit_target_mismatch",
            failure(
                True,
                True,
                0.25,
                True,
                None,
                explicit_actual=0.05,
            ),
        )
        self.assertEqual(
            "explicit_side_mismatch",
            failure(
                True,
                True,
                0.25,
                True,
                None,
                explicit_actual=0.24,
                side_target="right",
                side_actual="left",
            ),
        )
        self.assertIsNone(
            failure(
                True,
                True,
                0.25,
                True,
                None,
                explicit_actual=0.18,
                side_target="right",
                side_actual="right",
                visible_pixels=12,
            )
        )

    def test_explicit_search_stages_are_deterministic_and_bounded(self):
        schedule = getattr(scene, "explicit_search_schedule", None)

        self.assertIsNotNone(schedule)
        first = schedule()
        second = schedule()
        self.assertEqual(first, second)
        self.assertEqual(("primary", "refine", "rescue"), tuple(first))
        self.assertEqual(
            {
                "primary": 9,
                "refine": 13,
                "rescue": 26,
            },
            {
                name: len(stage["candidates"])
                for name, stage in first.items()
            },
        )
        self.assertLessEqual(sum(
            len(stage["candidates"])
            for stage in first.values()
        ), 50)
        for stage in first.values():
            self.assertTrue(all(len(candidate) == 4 for candidate in stage["candidates"]))

    def test_explicit_candidate_budget_is_deterministic_and_fail_closed(self):
        bounded = getattr(scene, "bounded_candidate_offsets", None)

        self.assertIsNotNone(bounded)
        candidates = tuple((float(i), 0.0, 0.0, 0.0) for i in range(8))
        self.assertEqual(
            candidates[:2],
            bounded(candidates, attempted=3, limit=5),
        )
        self.assertEqual(
            (),
            bounded(candidates, attempted=5, limit=5),
        )
        with self.assertRaises(ValueError):
            bounded(candidates, attempted=-1, limit=5)
        with self.assertRaises(ValueError):
            bounded(candidates, attempted=0, limit=0)

    def test_explicit_refine_plan_falls_back_to_the_original_proposal(self):
        refine_plan = getattr(scene, "explicit_refine_plan", None)

        self.assertIsNotNone(refine_plan)
        original = {
            "center": [1.0, 2.0, 3.0],
            "yaw_rad": 0.25,
            "obj_name": "Dist_example",
        }
        self.assertEqual(original, refine_plan(original, None))
        self.assertIsNot(original, refine_plan(original, None))
        self.assertEqual(
            {
                "center": [4.0, 5.0, 6.0],
                "yaw_rad": 0.75,
                "obj_name": "Dist_example",
            },
            refine_plan(
                original,
                {"center": [4.0, 5.0, 6.0], "yaw_rad": 0.75},
            ),
        )
        self.assertEqual([1.0, 2.0, 3.0], original["center"])

    def test_explicit_search_seed_prefers_the_highest_scoring_rejected_candidate(self):
        select_seed = getattr(scene, "best_explicit_search_seed", None)
        select_accepted = getattr(scene, "best_explicit_accepted_seed", None)
        select_side = getattr(scene, "best_explicit_side_seed", None)

        self.assertIsNotNone(select_seed)
        self.assertIsNotNone(select_accepted)
        self.assertIsNotNone(select_side)
        accepted = {
            "best": {
                "score": -0.29,
                "center": [1.0, 2.0, 3.0],
                "yaw_rad": 0.0,
            },
            "best_rejected": {
                "score": -0.17,
                "center": [4.0, 5.0, 6.0],
                "yaw_rad": 0.25,
            },
        }
        failed = {
            "best": None,
            "best_rejected": {
                "score": -0.31,
                "center": [7.0, 8.0, 9.0],
                "yaw_rad": 0.5,
            },
        }
        self.assertIs(
            accepted["best_rejected"],
            select_seed(accepted, failed),
        )
        self.assertIs(
            accepted["best"],
            select_accepted(accepted, failed),
        )
        self.assertIsNone(select_seed({}, {"best": None}))
        self.assertIsNone(select_accepted({}, {"best": None}))
        side_result = {
            "candidate_log": [
                {
                    "score": -0.17,
                    "score_callback": {
                        "occluder_side_match": False,
                        "object_visible_pixels": 100,
                    },
                },
                {
                    "score": -0.29,
                    "score_callback": {
                        "occluder_side_match": True,
                        "object_visible_pixels": 831,
                    },
                },
            ]
        }
        self.assertIs(
            side_result["candidate_log"][1],
            select_side(side_result),
        )
        self.assertIsNone(select_side({"candidate_log": []}))

    def test_grounded_center_stays_on_the_planned_camera_ray(self):
        point_at_height = getattr(scene, "camera_ray_point_at_z", None)

        self.assertIsNotNone(point_at_height)
        self.assertEqual(
            (1.0, 2.0, 5.0),
            point_at_height(
                camera_pos=(0.0, 0.0, 10.0),
                target_center=(2.0, 4.0, 0.0),
                target_z=5.0,
            ),
        )
        self.assertIsNone(
            point_at_height(
                camera_pos=(0.0, 0.0, 1.0),
                target_center=(2.0, 4.0, 1.0),
                target_z=0.0,
            )
        )
        self.assertIsNone(
            point_at_height(
                camera_pos=(0.0, 0.0, 1.0),
                target_center=(2.0, 4.0, 0.0),
                target_z=2.0,
            )
        )

    def test_optical_depth_step_preserves_ground_plane_motion(self):
        depth_step = getattr(scene, "optical_depth_step_for_ground", None)

        self.assertIsNotNone(depth_step)
        self.assertAlmostEqual(
            0.1,
            depth_step(
                camera_pos=(0.0, 0.0, 1.0),
                camera_look=(1.0, 0.0, 1.0),
                ground_step=0.1,
            ),
        )
        self.assertAlmostEqual(
            0.2,
            depth_step(
                camera_pos=(0.0, 0.0, 0.0),
                camera_look=(1.0, 0.0, math.sqrt(3.0)),
                ground_step=0.1,
            ),
        )
        self.assertAlmostEqual(
            1.0,
            depth_step(
                camera_pos=(0.0, 0.0, 0.0),
                camera_look=(0.0, 0.0, 1.0),
                ground_step=0.1,
            ),
        )
        with self.assertRaises(ValueError):
            depth_step(
                camera_pos=(0.0, 0.0, 0.0),
                camera_look=(0.0, 0.0, 0.0),
                ground_step=0.1,
            )

    def test_occluder_dimensions_match_manifest_y_up_to_blender_z_up(self):
        validate = getattr(scene, "validate_occluder_dimensions", None)
        convert = getattr(scene, "manifest_bbox_to_blender_dimensions", None)

        self.assertIsNotNone(validate)
        self.assertIsNotNone(convert)
        self.assertEqual(
            (0.52, 0.432, 1.12),
            convert((0.52, 1.12, 0.432)),
        )
        matching = validate(
            manifest_bbox=(0.52, 1.12, 0.432),
            blender_dimensions=(0.52, 0.432, 1.12),
        )
        self.assertTrue(matching["valid"])
        self.assertEqual([0.52, 0.432, 1.12], matching["expected_xyz"])
        self.assertEqual([1.0, 1.0, 1.0], matching["axis_ratio_xyz"])

        stale = validate(
            manifest_bbox=(0.325, 1.1, 0.414),
            blender_dimensions=(0.1225, 0.15625, 0.415),
        )
        self.assertFalse(stale["valid"])
        self.assertTrue(stale["uniformly_rescalable"])
        self.assertAlmostEqual(
            1.0,
            sum(stale["normalized_axis_ratio_xyz"]) / 3.0,
        )
        self.assertAlmostEqual(
            2.6511,
            stale["normalization_scale"],
            places=3,
        )
        self.assertLess(stale["axis_ratio_xyz"][0], 0.5)
        self.assertLess(stale["axis_ratio_xyz"][2], 0.5)

        rotated_or_stale = validate(
            manifest_bbox=(0.5, 1.0, 0.25),
            blender_dimensions=(1.0, 0.25, 1.0),
        )
        self.assertFalse(rotated_or_stale["valid"])
        self.assertFalse(rotated_or_stale["uniformly_rescalable"])
        self.assertIsNone(rotated_or_stale["normalization_scale"])
        with self.assertRaises(ValueError):
            validate((1.0, 2.0), (1.0, 2.0, 3.0))

    def test_explicit_reservation_plan_applies_rigid_anchor_shift(self):
        translate = getattr(scene, "translated_explicit_proposal", None)

        self.assertIsNotNone(translate)
        proposal = {
            "obj_name": "thin_panel",
            "center": [1.0, 2.0, 3.0],
            "scale": 0.75,
        }
        translated = translate(proposal, (-4.0, 5.0, 0.25))

        self.assertEqual([-3.0, 7.0, 3.25], translated["center"])
        self.assertEqual("thin_panel", translated["obj_name"])
        self.assertEqual(0.75, translated["scale"])
        self.assertEqual([1.0, 2.0, 3.0], proposal["center"])
        with self.assertRaises(ValueError):
            translate(proposal, (1.0, 2.0))

    def test_mask_index_stats_reports_pixel_extent_without_numpy_dependency(self):
        summarize = getattr(scene, "mask_index_stats", None)

        self.assertIsNotNone(summarize)
        self.assertEqual(
            {
                "visible_pixels": 3,
                "bbox_px": [2, 1, 6, 4],
                "centroid_px": [4.0, 8.0 / 3.0],
                "centroid_norm": [4.0 / 7.0, (8.0 / 3.0) / 5.0],
            },
            summarize(
                rows=[1, 3, 4],
                cols=[2, 4, 6],
                height=6,
                width=8,
            ),
        )
        self.assertEqual(
            {
                "visible_pixels": 0,
                "bbox_px": None,
                "centroid_px": None,
                "centroid_norm": None,
            },
            summarize(rows=[], cols=[], height=6, width=8),
        )
        with self.assertRaises(ValueError):
            summarize(rows=[1], cols=[], height=6, width=8)

    def test_bbox_gap_px_is_zero_for_touching_or_overlapping_masks(self):
        gap = getattr(scene, "bbox_gap_px", None)

        self.assertIsNotNone(gap)
        self.assertEqual(0.0, gap([0, 0, 5, 5], [5, 2, 8, 4]))
        self.assertEqual(0.0, gap([0, 0, 5, 5], [2, 2, 3, 3]))
        self.assertEqual(5.0, gap([0, 0, 5, 5], [8, 9, 10, 12]))
        self.assertIsNone(gap([0, 0, 5, 5], None))

    def test_explicit_feedback_offsets_move_a_visible_object_toward_target_side(self):
        feedback = getattr(scene, "explicit_feedback_offsets", None)

        self.assertIsNotNone(feedback)
        target = {
            "bbox_px": [10, 20, 70, 80],
            "centroid_px": [40.0, 50.0],
        }
        candidate = {
            "object_visible_centroid_px": [90.0, 100.0],
        }
        first = feedback(target, candidate, "right")
        second = feedback(target, candidate, "right")
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 25)
        self.assertIn((-0.05, 0.0, 0.0, 0.0), first)
        self.assertIn((0.0, 0.05, 0.0, 0.0), first)
        self.assertIn((-0.1, 0.1, 0.0, 0.0), first)
        self.assertIn((-0.05, 0.05, -0.1, 0.0), first)
        self.assertIn((-0.05, 0.05, -0.2, 0.0), first)
        self.assertIn((-0.05, 0.05, 0.1, 0.0), first)
        self.assertIn((-0.05, 0.05, 0.2, 0.0), first)
        self.assertIn((-0.3, 0.0, 0.0, 0.0), first)
        self.assertIn((0.0, 0.5, 0.0, 0.0), first)
        self.assertIn((-0.15, 0.0, 0.1, 0.0), first)
        self.assertIn((-0.3, 0.0, 0.1, 0.0), first)
        yaw_offsets = [candidate[3] for candidate in first if candidate[3]]
        self.assertTrue(
            any(math.isclose(math.radians(15.0), value) for value in yaw_offsets)
        )
        self.assertTrue(
            any(math.isclose(-math.radians(15.0), value) for value in yaw_offsets)
        )
        self.assertTrue(all(
            math.isclose(abs(value), math.radians(15.0))
            for value in yaw_offsets
        ))
        expanded = feedback(
            target,
            candidate,
            "right",
            yaw_step_degrees=(15.0, 45.0, 90.0),
        )
        expanded_yaw_offsets = {
            round(math.degrees(candidate[3]), 6)
            for candidate in expanded
            if candidate[3]
        }
        self.assertEqual(
            {-90.0, -45.0, -15.0, 15.0, 45.0, 90.0},
            expanded_yaw_offsets,
        )
        self.assertEqual(
            (),
            feedback(target, {}, "right"),
        )

    def test_explicit_bbox_alignment_offsets_pull_right_occluder_to_target_edge(self):
        align = getattr(scene, "explicit_bbox_alignment_offsets", None)

        self.assertIsNotNone(align)
        target = {
            "bbox_px": [0, 64, 24, 82],
            "centroid_px": [10.94, 71.95],
        }
        candidate = {
            "object_visible_bbox_px": [63, 48, 127, 127],
            "object_visible_centroid_px": [95.0, 87.0],
        }
        offsets = align(
            target,
            candidate,
            "right",
            meters_per_pixel_u=0.02,
            meters_per_pixel_v=0.02,
        )

        self.assertGreaterEqual(len(offsets), 3)
        du, dv, depth, yaw = offsets[0]
        self.assertAlmostEqual(-0.905, du)
        self.assertAlmostEqual(0.0, dv)
        self.assertAlmostEqual(0.0, depth)
        self.assertAlmostEqual(0.0, yaw)
        self.assertTrue(all(abs(candidate[0]) <= 1.5 for candidate in align(
            target,
            candidate,
            "right",
            meters_per_pixel_u=1.0,
            meters_per_pixel_v=1.0,
            max_abs_shift_m=1.5,
        )))

    def test_explicit_bbox_alignment_offsets_handle_left_bottom_and_missing_masks(self):
        align = getattr(scene, "explicit_bbox_alignment_offsets", None)

        self.assertIsNotNone(align)
        target = {"bbox_px": [20, 30, 80, 90], "centroid_px": [50.0, 60.0]}
        left_candidate = {
            "object_visible_bbox_px": [0, 30, 10, 90],
            "object_visible_centroid_px": [5.0, 60.0],
        }
        bottom_candidate = {
            "object_visible_bbox_px": [20, 0, 80, 20],
            "object_visible_centroid_px": [50.0, 10.0],
        }

        self.assertGreater(
            align(
                target,
                left_candidate,
                "left",
                meters_per_pixel_u=0.01,
                meters_per_pixel_v=0.01,
            )[0][0],
            0.10,
        )
        bottom_offsets = align(
            target,
            bottom_candidate,
            "bottom",
            meters_per_pixel_u=0.01,
            meters_per_pixel_v=0.01,
        )
        self.assertLess(bottom_offsets[0][1], -0.40)
        self.assertIn(
            (0.0, round(0.5 * bottom_offsets[0][1], 12), 0.0, 0.0),
            bottom_offsets,
        )
        self.assertEqual(
            (),
            align(
                target,
                {},
                "right",
                meters_per_pixel_u=0.01,
                meters_per_pixel_v=0.01,
            ),
        )
        with self.assertRaises(ValueError):
            align(
                target,
                left_candidate,
                "diagonal",
                meters_per_pixel_u=0.01,
                meters_per_pixel_v=0.01,
            )

    def test_projected_bbox_stats_preserve_offscreen_points(self):
        stats = getattr(scene, "projected_bbox_stats", None)

        self.assertIsNotNone(stats)
        self.assertEqual(
            {
                "visible_points": 2,
                "bbox_px": [-16.0, 16.0, 8.0, 32.0],
                "centroid_px": [-4.0, 24.0],
            },
            stats(
                uv=[[-64.0, 64.0], [32.0, 128.0], [999.0, 999.0]],
                depths=[1.0, 2.0, -1.0],
                source_size=(640, 480),
                target_size=(160, 120),
            ),
        )
        self.assertEqual(
            {
                "visible_points": 0,
                "bbox_px": None,
                "centroid_px": None,
            },
            stats(
                uv=[[1.0, 2.0]],
                depths=[-1.0],
                source_size=(640, 480),
                target_size=(160, 120),
            ),
        )

    def test_explicit_search_order_prefers_compact_dense_asset_over_oversized_primary(self):
        order = getattr(scene, "order_explicit_proposals_for_search", None)

        self.assertIsNotNone(order)
        oversized_primary = {
            "obj_name": "Dist_covered_car",
            "bbox_m": [1.789, 1.411, 4.38],
            "fill_ratio": 0.7299,
            "scale": 1.0446,
            "diagnostic_proposal_nonce": 0,
        }
        compact_dense = {
            "obj_name": "Dist_utility_box_01",
            "bbox_m": [0.52, 1.12, 0.432],
            "fill_ratio": 0.9166,
            "scale": 1.0703,
            "diagnostic_proposal_nonce": 87,
        }
        sparse_sign = {
            "obj_name": "Dist_construction_sign_01",
            "bbox_m": [1.068, 1.2, 0.059],
            "fill_ratio": 0.4797,
            "scale": 1.0032,
            "diagnostic_proposal_nonce": 8,
        }
        proposals = [oversized_primary, sparse_sign, compact_dense]

        ordered = order(proposals)

        self.assertEqual(
            ["Dist_utility_box_01", "Dist_construction_sign_01", "Dist_covered_car"],
            [proposal["obj_name"] for proposal in ordered],
        )
        self.assertEqual(
            ["Dist_covered_car", "Dist_construction_sign_01", "Dist_utility_box_01"],
            [proposal["obj_name"] for proposal in proposals],
        )
        self.assertEqual(ordered, order(proposals))

    def test_explicit_search_order_keeps_a_compact_dense_primary_first(self):
        order = getattr(scene, "order_explicit_proposals_for_search", None)

        primary = {
            "obj_name": "Dist_barrel_stove",
            "bbox_m": [0.593, 0.856, 0.593],
            "fill_ratio": 0.9707,
            "scale": 0.9221,
            "diagnostic_proposal_nonce": 0,
        }
        smaller_fallback = {
            "obj_name": "Dist_utility_box_01",
            "bbox_m": [0.52, 1.12, 0.432],
            "fill_ratio": 0.9166,
            "scale": 1.0173,
            "diagnostic_proposal_nonce": 87,
        }

        self.assertEqual(
            ["Dist_barrel_stove", "Dist_utility_box_01"],
            [proposal["obj_name"] for proposal in order(
                [primary, smaller_fallback]
            )],
        )

    def test_high_lateral_target_prefers_dense_upright_area(self):
        order = getattr(scene, "order_explicit_proposals_for_search", None)

        barrel_primary = {
            "obj_name": "Dist_barrel_stove",
            "bbox_m": [0.547, 0.789, 0.547],
            "fill_ratio": 0.9707,
            "scale": 1.0,
            "diagnostic_proposal_nonce": 0,
        }
        utility = {
            "obj_name": "Dist_utility_box_01",
            "bbox_m": [0.529, 1.139, 0.439],
            "fill_ratio": 0.9166,
            "scale": 1.0,
            "diagnostic_proposal_nonce": 278,
        }
        screen = {
            "obj_name": "Dist_chinese_screen_panels",
            "bbox_m": [1.254, 1.553, 0.365],
            "fill_ratio": 0.921,
            "scale": 1.0,
            "diagnostic_proposal_nonce": 68,
        }

        ordered = order(
            [barrel_primary, utility, screen],
            target_fraction=0.41,
            target_side="right",
        )

        self.assertEqual(
            ["Dist_chinese_screen_panels", "Dist_utility_box_01", "Dist_barrel_stove"],
            [proposal["obj_name"] for proposal in ordered],
        )

    def test_high_bottom_target_keeps_pure_solver_primary(self):
        order = getattr(scene, "order_explicit_proposals_for_search", None)

        forklift_primary = {
            "obj_name": "Dist_forklift_01",
            "bbox_m": [0.83, 1.539, 2.5],
            "fill_ratio": 0.5646,
            "scale": 1.0,
            "diagnostic_proposal_nonce": 0,
        }
        narrow_tall = {
            "obj_name": "Dist_utility_box_01",
            "bbox_m": [0.529, 1.139, 0.439],
            "fill_ratio": 0.9166,
            "scale": 1.0,
            "diagnostic_proposal_nonce": 278,
        }

        ordered = order(
            [forklift_primary, narrow_tall],
            target_fraction=0.32,
            target_side="bottom",
        )

        self.assertEqual(
            ["Dist_forklift_01", "Dist_utility_box_01"],
            [proposal["obj_name"] for proposal in ordered],
        )

    def test_high_bottom_target_reorders_when_original_primary_was_filtered(self):
        order = getattr(scene, "order_explicit_proposals_for_search", None)

        sparse_fallback = {
            "obj_name": "Dist_construction_sign_01",
            "bbox_m": [1.068, 1.2, 0.059],
            "fill_ratio": 0.4797,
            "scale": 0.7034,
            "diagnostic_proposal_nonce": 8,
            "diagnostic_proposal_index": 1,
        }
        compact_dense = {
            "obj_name": "Dist_utility_box_01",
            "bbox_m": [0.529, 1.139, 0.439],
            "fill_ratio": 0.9166,
            "scale": 0.8099,
            "diagnostic_proposal_nonce": 278,
            "diagnostic_proposal_index": 2,
        }
        wide_dense = {
            "obj_name": "Dist_chinese_screen_panels",
            "bbox_m": [1.254, 1.553, 0.365],
            "fill_ratio": 0.921,
            "scale": 1.0,
            "diagnostic_proposal_nonce": 68,
            "diagnostic_proposal_index": 3,
        }

        ordered = order(
            [sparse_fallback, compact_dense, wide_dense],
            target_fraction=0.41,
            target_side="bottom",
        )

        self.assertEqual(
            [
                "Dist_chinese_screen_panels",
                "Dist_utility_box_01",
                "Dist_construction_sign_01",
            ],
            [proposal["obj_name"] for proposal in ordered],
        )

    def test_external_corner_gate_metrics_match_g1_and_g2_contract(self):
        metrics = getattr(scene, "external_corner_gate_metrics", None)

        self.assertIsNotNone(metrics)
        passing = metrics(
            [True, True, True, True, True, True, False, False],
            [0.0, 0.6, 0.8, 0.1, 0.2, 0.0, 0.0, 0.0],
        )
        self.assertEqual(6, passing["V_inframe"])
        self.assertEqual(2, passing["ext_occ_corners"])
        self.assertEqual(4, passing["V_vis"])
        self.assertTrue(passing["G1_pass"])
        self.assertTrue(passing["G2_pass"])
        self.assertTrue(passing["joint_pass"])

        no_corner = metrics(
            [True] * 6 + [False, False],
            [0.0, 0.49, 0.2, 0.0, 0.0, 0.0, 1.0, 1.0],
        )
        self.assertFalse(no_corner["G2_pass"])
        self.assertAlmostEqual(0.01, no_corner["corner_threshold_gap"])

        impossible = metrics(
            [True, True, True, True, False, False, False, False],
            [0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        self.assertTrue(impossible["G2_pass"])
        self.assertFalse(impossible["G1_pass"])
        self.assertFalse(impossible["joint_pass"])

    def test_explicit_corner_reserve_leaves_room_for_controlled_occluder(self):
        reserve = getattr(scene, "explicit_corner_reserve_pass", None)

        self.assertIsNotNone(reserve)
        self.assertTrue(
            reserve(
                {
                    "V_inframe": 8,
                    "ext_occ_corners": 1,
                    "V_vis": 7,
                }
            )
        )
        self.assertFalse(
            reserve(
                {
                    "V_inframe": 8,
                    "ext_occ_corners": 2,
                    "V_vis": 6,
                }
            )
        )
        self.assertFalse(
            reserve(
                {
                    "V_inframe": 4,
                    "ext_occ_corners": 0,
                    "V_vis": 4,
                }
            )
        )

    def test_explicit_overlap_refinement_moves_inward_from_valid_side(self):
        refine = getattr(scene, "explicit_overlap_refinement_offsets", None)

        self.assertIsNotNone(refine)
        bottom = refine("bottom", actual_fraction=0.26, target_fraction=0.41)
        self.assertEqual((0.0, -0.05, 0.05, 0.0), bottom[0])
        self.assertIn((0.0, 0.05, 0.0, 0.0), bottom)
        self.assertIn((0.0, 0.0, 0.05, 0.0), bottom)
        self.assertLessEqual(len(bottom), 12)
        self.assertEqual(
            (0.0, 0.0, 0.05, 0.0),
            refine("right", actual_fraction=0.20, target_fraction=0.40)[0],
        )
        self.assertIn(
            (-0.05, 0.0, 0.0, 0.0),
            refine("right", actual_fraction=0.20, target_fraction=0.40),
        )
        self.assertEqual(
            (0.0, 0.0, 0.05, 0.0),
            refine("left", actual_fraction=0.20, target_fraction=0.40)[0],
        )
        self.assertIn(
            (0.05, 0.0, 0.0, 0.0),
            refine("left", actual_fraction=0.20, target_fraction=0.40),
        )
        self.assertEqual(
            (0.0, 0.05, -0.05, 0.0),
            refine("bottom", actual_fraction=0.45, target_fraction=0.30)[0],
        )
        self.assertEqual(
            (0.0, 0.0, 0.05, 0.0),
            refine("center", actual_fraction=0.20, target_fraction=0.40)[0],
        )
        self.assertEqual(
            (),
            refine("center", actual_fraction=0.30, target_fraction=0.30),
        )

    def test_best_explicit_gate_side_seed_requires_both_corner_gates(self):
        select = getattr(scene, "best_explicit_gate_side_seed", None)
        select_any = getattr(scene, "best_explicit_gate_seed", None)

        self.assertIsNotNone(select)
        self.assertIsNotNone(select_any)
        candidates = {
            "candidate_log": [
                {
                    "score": -0.01,
                    "score_callback": {
                        "occluder_side_match": True,
                        "object_visible_pixels": 100,
                        "candidate_G1_pass": True,
                        "candidate_G2_pass": False,
                    },
                },
                {
                    "score": -0.20,
                    "score_callback": {
                        "occluder_side_match": True,
                        "object_visible_pixels": 100,
                        "candidate_G1_pass": True,
                        "candidate_G2_pass": True,
                    },
                },
                {
                    "score": -0.05,
                    "score_callback": {
                        "occluder_side_match": False,
                        "object_visible_pixels": 100,
                        "candidate_G1_pass": True,
                        "candidate_G2_pass": True,
                    },
                },
            ]
        }
        self.assertIs(candidates["candidate_log"][1], select(candidates))
        self.assertIs(candidates["candidate_log"][2], select_any(candidates))
        self.assertIsNone(select({"candidate_log": []}))
        self.assertIsNone(select_any({"candidate_log": []}))

    def test_missing_corner_seed_requires_target_side_area_and_g1(self):
        select = getattr(scene, "best_explicit_missing_corner_seed", None)

        self.assertIsNotNone(select)
        candidates = {
            "candidate_log": [
                {
                    "score": -0.01,
                    "score_callback": {
                        "occluder_side_match": True,
                        "object_visible_pixels": 100,
                        "target_error_ok": True,
                        "candidate_G1_pass": True,
                        "candidate_G2_pass": False,
                        "candidate_ext_occ_corners": 0,
                    },
                },
                {
                    "score": -0.02,
                    "score_callback": {
                        "occluder_side_match": False,
                        "object_visible_pixels": 100,
                        "target_error_ok": True,
                        "candidate_G1_pass": True,
                        "candidate_G2_pass": False,
                        "candidate_ext_occ_corners": 0,
                    },
                },
                {
                    "score": -0.03,
                    "score_callback": {
                        "occluder_side_match": True,
                        "object_visible_pixels": 100,
                        "target_error_ok": True,
                        "candidate_G1_pass": True,
                        "candidate_G2_pass": True,
                        "candidate_ext_occ_corners": 1,
                    },
                },
            ]
        }
        self.assertIs(candidates["candidate_log"][0], select(candidates))
        self.assertIsNone(select({"candidate_log": []}))

    def test_corner_contact_refinement_moves_along_target_boundary(self):
        refine = getattr(
            scene,
            "explicit_corner_contact_refinement_offsets",
            None,
        )

        self.assertIsNotNone(refine)
        bottom = refine("bottom")
        self.assertEqual((0.05, 0.0, 0.0, 0.0), bottom[0])
        self.assertEqual((-0.05, 0.0, 0.0, 0.0), bottom[1])
        self.assertLessEqual(len(bottom), 10)
        left = refine("left")
        self.assertEqual((0.0, 0.05, 0.0, 0.0), left[0])
        self.assertEqual((0.0, -0.05, 0.0, 0.0), left[1])
        center = refine("center")
        self.assertIn((0.05, 0.0, 0.0, 0.0), center)
        self.assertIn((0.0, 0.05, 0.0, 0.0), center)
        self.assertLessEqual(len(center), 12)

    def test_explicit_swept_reservation_expands_xy_but_not_support_height(self):
        reserve = getattr(scene, "explicit_swept_reservation_aabb", None)

        self.assertIsNotNone(reserve)
        self.assertEqual(
            {
                "aabb_min": [-1.5, -1.0, 0.0],
                "aabb_max": [2.5, 3.0, 1.0],
                "horizontal_margin_m": 1.5,
            },
            reserve(
                aabb_min=[0.0, 0.5, 0.0],
                aabb_max=[1.0, 1.5, 1.0],
                horizontal_margin_m=1.5,
            ),
        )

    def test_procedural_plane_tracks_the_accepted_anchor_in_xy_only(self):
        shift = getattr(scene, "procedural_support_shift", None)

        self.assertIsNotNone(shift)
        self.assertEqual(
            (2.5, -3.0, 0.0),
            shift("plane", (2.5, -3.0, 0.25)),
        )
        self.assertEqual(
            (0.0, 0.0, 0.0),
            shift("native", (2.5, -3.0, 0.25)),
        )

    def test_support_hit_objects_are_sorted_and_deduplicated(self):
        summarize = getattr(scene, "support_hit_objects", None)

        self.assertIsNotNone(summarize)
        report = {
            "samples": [
                {"hit_object": "Pallet_1"},
                {"hit_object": None},
                {"hit_object": "FloorRandPlane"},
                {"hit_object": "Pallet_1"},
            ]
        }
        self.assertEqual(
            ("FloorRandPlane", "Pallet_1"),
            summarize(report),
        )
        self.assertEqual((), summarize(None))


class LowresMaskContractTests(unittest.TestCase):
    def test_lowres_masks_preserve_the_native_render_aspect_ratio(self):
        lowres_size = getattr(scene, "aspect_preserving_lowres_size", None)

        self.assertIsNotNone(lowres_size)
        self.assertEqual((192, 128), lowres_size(720, 480, base_height=128))
        self.assertEqual((228, 128), lowres_size(960, 540, base_height=128))
        self.assertEqual((171, 128), lowres_size(640, 480, base_height=128))
        self.assertEqual((128, 128), lowres_size(560, 560, base_height=128))
        self.assertEqual((128, 192), lowres_size(480, 720, base_height=128))
        with self.assertRaises(ValueError):
            lowres_size(0, 480)


class RoleContractTests(unittest.TestCase):
    def test_roles_name_every_constrained_assembly_part(self):
        self.assertEqual(
            (
                "pallet",
                "support",
                "static_background",
                "cargo",
                "context",
                "explicit_occluder",
            ),
            getattr(scene, "ROLES", None),
        )

    def test_contact_matrix_is_total_symmetric_and_json_serializable(self):
        matrix = getattr(scene, "CONTACT_ALLOWED", None)

        self.assertIsInstance(matrix, dict)
        self.assertEqual(set(scene.ROLES), set(matrix))
        for left in scene.ROLES:
            self.assertEqual(set(scene.ROLES), set(matrix[left]))
            for right in scene.ROLES:
                self.assertIsInstance(matrix[left][right], bool)
                self.assertEqual(matrix[left][right], matrix[right][left])
        self.assertTrue(matrix["pallet"]["support"])
        self.assertTrue(matrix["pallet"]["cargo"])
        self.assertTrue(matrix["context"]["support"])
        self.assertTrue(matrix["explicit_occluder"]["support"])
        self.assertFalse(matrix["pallet"]["context"])
        self.assertFalse(matrix["context"]["explicit_occluder"])
        self.assertFalse(matrix["cargo"]["support"])
        self.assertFalse(matrix["cargo"]["cargo"])
        self.assertFalse(matrix["static_background"]["support"])
        json.dumps(matrix)

    def test_collision_action_distinguishes_legal_contact_from_overlap_rejection(self):
        action = getattr(scene, "collision_action", None)

        self.assertTrue(callable(action))
        self.assertEqual("allow_contact", action("support", "context"))
        self.assertEqual("allow_contact", action("cargo", "pallet"))
        self.assertEqual("reject_overlap", action("context", "pallet"))
        self.assertEqual(
            action("pallet", "context"),
            action("context", "pallet"),
        )
        with self.assertRaises(ValueError):
            action("camera", "pallet")

    def test_camera_clearance_policy_keeps_target_closeups_separate_from_obstacles(self):
        clearance_for = getattr(scene, "camera_clearance_for_role", None)

        self.assertTrue(callable(clearance_for))
        self.assertAlmostEqual(0.02, clearance_for("pallet"))
        self.assertAlmostEqual(0.02, clearance_for("support"))
        for role in (
            "static_background",
            "cargo",
            "context",
            "explicit_occluder",
        ):
            with self.subTest(role=role):
                self.assertAlmostEqual(0.20, clearance_for(role))
        with self.assertRaises(ValueError):
            clearance_for("camera")

    def test_runtime_collision_pairs_are_derived_from_contact_matrix(self):
        build_pairs = getattr(scene, "forbidden_collision_pairs", None)

        self.assertTrue(callable(build_pairs))
        pallet = object()
        support = object()
        static = object()
        cargo_a = object()
        cargo_b = object()
        context_a = object()
        context_b = object()
        explicit = object()
        pairs = build_pairs(
            {
                scene.ROLE_PALLET: [pallet],
                scene.ROLE_SUPPORT: [support],
                scene.ROLE_STATIC_BACKGROUND: [static],
                scene.ROLE_CARGO: [cargo_a, cargo_b],
                scene.ROLE_CONTEXT: [context_a, context_b],
                scene.ROLE_EXPLICIT_OCCLUDER: [explicit],
            }
        )
        pair_ids = {frozenset((id(left), id(right))) for left, right in pairs}

        def present(left, right):
            return frozenset((id(left), id(right))) in pair_ids

        self.assertFalse(present(pallet, support))
        self.assertFalse(present(pallet, cargo_a))
        self.assertFalse(present(context_a, support))
        self.assertFalse(present(explicit, support))
        self.assertTrue(present(pallet, static))
        self.assertTrue(present(pallet, context_a))
        self.assertTrue(present(pallet, explicit))
        self.assertTrue(present(cargo_a, cargo_b))
        self.assertTrue(present(cargo_a, support))
        self.assertTrue(present(cargo_a, static))
        self.assertTrue(present(context_a, context_b))
        self.assertTrue(present(context_a, static))
        self.assertTrue(present(context_a, explicit))
        self.assertFalse(present(support, static))


class StageSeedTests(unittest.TestCase):
    def test_frame_seed_derives_stable_independent_stage_seeds(self):
        derive = getattr(scene, "derive_stage_seeds", None)

        self.assertTrue(callable(derive))
        first = derive(7123)
        second = derive(7123)
        changed = derive(7124)
        self.assertEqual(
            {"background", "anchor", "cargo", "context", "occluder"},
            set(first),
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertEqual(len(first), len(set(first.values())))
        for value in first.values():
            self.assertIsInstance(value, int)
            self.assertGreaterEqual(value, 0)
            self.assertLess(value, 2**64)
        json.dumps(first)

    def test_stage_seed_rejects_non_integer_and_boolean_frame_seeds(self):
        derive = getattr(scene, "derive_stage_seeds", None)

        self.assertTrue(callable(derive))
        for invalid in (True, 1.5, "7"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    derive(invalid)


class AabbBroadPhaseTests(unittest.TestCase):
    def test_aabb_overlap_is_inclusive_and_honors_clearance_margin(self):
        overlaps = getattr(scene, "aabb_overlap", None)

        self.assertTrue(callable(overlaps))
        unit_min, unit_max = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
        self.assertTrue(overlaps(unit_min, unit_max, (0.5, 0.5, 0.5), (2, 2, 2)))
        self.assertTrue(overlaps(unit_min, unit_max, (1.0, 0.2, 0.2), (2, 0.8, 0.8)))
        self.assertFalse(overlaps(unit_min, unit_max, (1.05, 0.2, 0.2), (2, 0.8, 0.8)))
        self.assertTrue(
            overlaps(
                unit_min,
                unit_max,
                (1.05, 0.2, 0.2),
                (2, 0.8, 0.8),
                margin=0.05,
            )
        )
        self.assertFalse(
            overlaps(
                unit_min,
                unit_max,
                (1.05, 0.2, 0.2),
                (2, 0.8, 0.8),
                margin=0.049,
            )
        )

    def test_aabb_overlap_rejects_malformed_boxes_and_margin(self):
        overlaps = getattr(scene, "aabb_overlap", None)

        self.assertTrue(callable(overlaps))
        valid_min, valid_max = (0, 0, 0), (1, 1, 1)
        invalid_calls = (
            ((0, 0), (1, 1), valid_min, valid_max, 0),
            ((1, 0, 0), (0, 1, 1), valid_min, valid_max, 0),
            (valid_min, valid_max, valid_min, valid_max, -0.1),
            ((0, 0, float("nan")), valid_max, valid_min, valid_max, 0),
        )
        for a_min, a_max, b_min, b_max, margin in invalid_calls:
            with self.subTest(
                a_min=a_min,
                a_max=a_max,
                b_min=b_min,
                b_max=b_max,
                margin=margin,
            ):
                with self.assertRaises(ValueError):
                    overlaps(a_min, a_max, b_min, b_max, margin=margin)


class SupportSnapTests(unittest.TestCase):
    def test_support_snap_accepts_inverted_horizontal_mesh_normals(self):
        compute = getattr(scene, "compute_support_snap", None)

        self.assertTrue(callable(compute))
        result = compute(
            sample_zs=[0.0, 0.0, 0.0, 0.0, 0.0],
            support_zs=[-0.0421734] * 5,
            normal_zs=[-1.0] * 5,
            height_tolerance=0.01,
        )
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(-0.0421734, result["vertical_offset"], places=7)
        self.assertEqual(None, result["reason"])

    def test_support_snap_rejects_tilted_or_nonplanar_hits(self):
        compute = getattr(scene, "compute_support_snap", None)

        tilted = compute(
            sample_zs=[0.0] * 5,
            support_zs=[0.0] * 5,
            normal_zs=[1.0, 1.0, 0.2, 1.0, 1.0],
            height_tolerance=0.01,
        )
        self.assertFalse(tilted["ok"])
        self.assertEqual("support_normal", tilted["reason"])

        nonplanar = compute(
            sample_zs=[0.0] * 5,
            support_zs=[0.0, 0.0, 0.0, 0.0, 0.05],
            normal_zs=[1.0] * 5,
            height_tolerance=0.01,
        )
        self.assertFalse(nonplanar["ok"])
        self.assertEqual("support_height_variation", nonplanar["reason"])


class MaskDecompositionTests(unittest.TestCase):
    def test_mask_areas_decompose_into_additive_occlusion_fractions(self):
        decompose = getattr(scene, "decompose_mask_areas", None)

        self.assertTrue(callable(decompose))
        result = decompose(100, 90, 75, 65, 50)
        self.assertEqual(
            {
                "mask_area_target_only": 100.0,
                "mask_area_after_static": 90.0,
                "mask_area_after_cargo": 75.0,
                "mask_area_after_context": 65.0,
                "mask_area_visible": 50.0,
            },
            {key: value for key, value in result.items() if key.startswith("mask_area_")},
        )
        self.assertAlmostEqual(0.10, result["f_static"])
        self.assertAlmostEqual(0.15, result["f_cargo"])
        self.assertAlmostEqual(0.10, result["f_context"])
        self.assertAlmostEqual(0.15, result["f_explicit"])
        self.assertAlmostEqual(0.50, result["f_total"])
        self.assertEqual(
            result["f_total"],
            sum(
                result[key]
                for key in ("f_static", "f_cargo", "f_context", "f_explicit")
            ),
        )
        self.assertEqual(
            ["M0", "M1", "M2", "M3", "M4"],
            result["occlusion_decomposition_order"],
        )
        json.dumps(result)

    def test_mask_validator_reports_negative_nonmonotonic_and_nonadditive_data(self):
        validate = getattr(scene, "validate_mask_decomposition", None)
        decompose = getattr(scene, "decompose_mask_areas", None)

        self.assertTrue(callable(validate))
        self.assertTrue(callable(decompose))
        report = validate(100, 90, 95, 70, 60)
        self.assertFalse(report["valid"])
        self.assertTrue(any("monotonic" in error for error in report["errors"]))

        report = validate(100, 90, 80, -1, -2)
        self.assertFalse(report["valid"])
        self.assertTrue(any("nonnegative" in error for error in report["errors"]))

        corrupted = decompose(100, 90, 80, 70, 60)
        corrupted["f_total"] = 0.9
        report = validate(corrupted)
        self.assertFalse(report["valid"])
        self.assertTrue(any("sum" in error for error in report["errors"]))

        with self.assertRaises(ValueError):
            decompose(0, 0, 0, 0, 0)
        json.dumps(report)

    def test_mask_validator_reports_a_malformed_order_instead_of_crashing(self):
        validate = getattr(scene, "validate_mask_decomposition", None)
        decompose = getattr(scene, "decompose_mask_areas", None)

        self.assertTrue(callable(validate))
        self.assertTrue(callable(decompose))
        malformed = decompose(100, 90, 80, 70, 60)
        malformed["occlusion_decomposition_order"] = 123
        try:
            report = validate(malformed)
        except TypeError as exc:
            self.fail(f"malformed decomposition escaped validation: {exc}")
        self.assertFalse(report["valid"])
        self.assertTrue(any("order" in error for error in report["errors"]))


class DiagnosticPolicyTests(unittest.TestCase):
    def test_each_diagnostic_mode_isolates_its_intended_dynamic_roles(self):
        policy_for = getattr(scene, "diagnostic_policy", None)
        policy_type = getattr(scene, "DiagnosticPolicy", None)

        self.assertTrue(callable(policy_for))
        self.assertTrue(isinstance(policy_type, type))
        expected = {
            "clean-static": ("off", False, False),
            "cargo-only": ("force_on", False, False),
            "context-rich": ("spec", True, False),
            "controlled-occlusion": ("spec", True, True),
        }
        for mode, flags in expected.items():
            with self.subTest(mode=mode):
                policy = policy_for(mode)
                self.assertIsInstance(policy, policy_type)
                self.assertEqual(mode, policy.mode)
                self.assertEqual(
                    flags,
                    (
                        getattr(policy, "cargo_mode", None),
                        policy.include_context,
                        policy.include_explicit_occluder,
                    ),
                )
                as_dict = policy.as_dict()
                self.assertNotIn("frame_count", as_dict)
                self.assertNotIn("count", as_dict)
                json.dumps(as_dict)

    def test_unknown_diagnostic_mode_is_rejected(self):
        policy_for = getattr(scene, "diagnostic_policy", None)

        self.assertTrue(callable(policy_for))
        with self.assertRaises(ValueError):
            policy_for("everything-random")


class AssetSelectionTests(unittest.TestCase):
    def test_context_selection_is_deterministic_and_disjoint_from_explicit_asset(self):
        choose = getattr(scene, "choose_disjoint_assets", None)

        self.assertTrue(callable(choose))
        context_candidates = [
            {"asset_id": "shared", "path": "context/shared.glb"},
            {"asset_id": "crate", "path": "context/crate.glb"},
            {"asset_id": "barrel", "path": "context/barrel.glb"},
            {"asset_id": "crate", "path": "duplicates/crate.glb"},
        ]
        explicit_candidates = [
            {"asset_id": "shared", "path": "occluders/shared.glb"},
            {"asset_id": "forklift", "path": "occluders/forklift.glb"},
        ]

        first = choose(
            context_candidates,
            explicit_candidates,
            context_count=2,
            seed=812,
        )
        second = choose(
            context_candidates,
            explicit_candidates,
            context_count=2,
            seed=812,
        )
        self.assertEqual(first, second)
        self.assertEqual(2, len(first["context"]))
        context_ids = [asset["asset_id"] for asset in first["context"]]
        self.assertEqual(len(context_ids), len(set(context_ids)))
        self.assertNotIn(first["explicit_occluder"]["asset_id"], context_ids)
        json.dumps(first)

    def test_asset_selection_rejects_an_impossible_disjoint_request(self):
        choose = getattr(scene, "choose_disjoint_assets", None)

        self.assertTrue(callable(choose))
        shared_context = [{"asset_id": "shared"}]
        shared_explicit = [{"asset_id": "shared"}]
        with self.assertRaises(ValueError):
            choose(
                shared_context,
                shared_explicit,
                context_count=1,
                seed=1,
            )

    def test_asset_selection_tries_another_explicit_asset_when_first_blocks_context(self):
        choose = getattr(scene, "choose_disjoint_assets", None)

        self.assertTrue(callable(choose))
        try:
            result = choose(
                [{"asset_id": "a"}, {"asset_id": "b"}],
                [{"asset_id": "a"}, {"asset_id": "c"}],
                context_count=2,
                seed=1,
            )
        except ValueError as exc:
            self.fail(f"feasible joint asset selection was rejected: {exc}")
        self.assertEqual("c", result["explicit_occluder"]["asset_id"])
        self.assertEqual(
            {"a", "b"},
            {asset["asset_id"] for asset in result["context"]},
        )

    def test_asset_selection_tracks_transitive_aliases_across_duplicate_records(self):
        choose = getattr(scene, "choose_disjoint_assets", None)

        self.assertTrue(callable(choose))
        context_candidates = [
            {"asset_id": "a", "path": "shared.glb"},
            {"asset_id": "b", "path": "shared.glb"},
        ]
        explicit_candidates = [{"asset_id": "b"}]
        with self.assertRaises(ValueError):
            choose(
                context_candidates,
                explicit_candidates,
                context_count=1,
                seed=4,
            )

    def test_asset_selection_tracks_alias_chains_across_both_role_pools(self):
        choose = getattr(scene, "choose_disjoint_assets", None)

        self.assertTrue(callable(choose))
        context_candidates = [
            {"asset_id": "a", "path": "x"},
            {"asset_id": "y", "path": "b"},
        ]
        explicit_candidates = [
            {"asset_id": "x", "path": "y"},
            {"asset_id": "b", "path": "c"},
        ]
        with self.assertRaises(ValueError):
            choose(
                context_candidates,
                explicit_candidates,
                context_count=1,
                seed=0,
            )


class MetadataValidationTests(unittest.TestCase):
    @staticmethod
    def valid_metadata():
        return {
            "anchor_translation": [0.2, -0.1, 0.0],
            "anchor_attempts": 3,
            "anchor_reject_counts_by_reason": {"static_collision": 2},
            "support_surface_name": "warehouse_floor",
            "min_camera_clearance": 0.7,
            "static_collision_pass": True,
            "static_los_pass": True,
            "tested_collision_pairs": 14,
            "broad_phase_hits": 4,
            "exact_collision_hits": 0,
            "collision_reject_reason": None,
            "context_context_collision_count": 0,
            "cargo_collision_count": 0,
            "pallet_obstacle_collision_count": 0,
            "n_context_placed": 4,
            "n_context_visible": 3,
            "context_visible_pixel_ratio": 0.03,
            "context_screen_area_ratio": 0.08,
            "f_context": 0.10,
            "context_placement_attempts": 7,
            "context_reject_counts_by_reason": {"overlap": 3},
            "n_cargo_requested": 2,
            "n_cargo_placed": 2,
            "cargo_placement_attempts": 3,
            "cargo_support_pass": True,
            "cargo_collision_pass": True,
            "f_cargo": 0.10,
            "front_visibility_after_cargo": 0.82,
            "left_opening_visibility_after_cargo": 0.76,
            "right_opening_visibility_after_cargo": 0.79,
            "f_explicit_target": 0.10,
            "f_explicit_actual": 0.10,
            "explicit_abs_error": 0.0,
            "occluder_feedback_iterations": 2,
            "occluder_side_target": "left",
            "occluder_side_actual": "left",
            "explicit_occluder_visible_pixels": 3200,
            "explicit_collision_pass": True,
            "explicit_solver_fail_reason": None,
            "mask_area_target_only": 100.0,
            "mask_area_after_static": 90.0,
            "mask_area_after_cargo": 80.0,
            "mask_area_after_context": 70.0,
            "mask_area_visible": 60.0,
            "f_static": 0.10,
            "f_explicit": 0.10,
            "f_total": 0.40,
            "occlusion_decomposition_order": ["M0", "M1", "M2", "M3", "M4"],
            "front_face_visibility": 0.60,
            "left_opening_visibility": 0.54,
            "right_opening_visibility": 0.57,
        }

    def test_metadata_validation_can_be_scoped_to_the_completed_stage(self):
        validate = getattr(scene, "validate_constrained_metadata", None)

        self.assertTrue(callable(validate))
        metadata = self.valid_metadata()
        anchor_keys = (
            "anchor_translation",
            "anchor_attempts",
            "anchor_reject_counts_by_reason",
            "support_surface_name",
            "min_camera_clearance",
            "static_collision_pass",
            "static_los_pass",
        )
        anchor_only = {key: metadata[key] for key in anchor_keys}
        self.assertTrue(validate(anchor_only, groups=("anchor",))["valid"])

        del anchor_only["support_surface_name"]
        report = validate(anchor_only, groups=("anchor",))
        self.assertFalse(report["valid"])
        self.assertIn("support_surface_name", report["missing"])

        anchor_only["support_surface_name"] = None
        report = validate(anchor_only, groups=("anchor",))
        self.assertFalse(report["valid"])
        self.assertIn("support_surface_name", report["none"])

    def test_full_metadata_requires_every_core_field_but_allows_empty_fail_reasons(self):
        validate = getattr(scene, "validate_constrained_metadata", None)

        self.assertTrue(callable(validate))
        metadata = self.valid_metadata()
        report = validate(metadata)
        self.assertTrue(report["valid"], report["errors"])

        missing = dict(metadata)
        del missing["broad_phase_hits"]
        report = validate(missing)
        self.assertFalse(report["valid"])
        self.assertIn("broad_phase_hits", report["missing"])

        none_value = dict(metadata)
        none_value["cargo_support_pass"] = None
        report = validate(none_value)
        self.assertFalse(report["valid"])
        self.assertIn("cargo_support_pass", report["none"])
        json.dumps(report)

    def test_none_opening_visibility_requires_a_nonempty_reason(self):
        validate = getattr(scene, "validate_constrained_metadata", None)

        self.assertTrue(callable(validate))
        metadata = self.valid_metadata()
        metadata["left_opening_visibility"] = None
        report = validate(metadata)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any("opening_visibility_reason" in error for error in report["errors"])
        )

        metadata["opening_visibility_reason"] = "kp12_invalid_at_high_angle"
        report = validate(metadata)
        self.assertTrue(report["valid"], report["errors"])

        metadata["opening_visibility_reason"] = ""
        report = validate(metadata)
        self.assertFalse(report["valid"])

    def test_metadata_validator_contains_a_malformed_decomposition_order(self):
        validate = getattr(scene, "validate_constrained_metadata", None)

        self.assertTrue(callable(validate))
        metadata = self.valid_metadata()
        metadata["occlusion_decomposition_order"] = 123
        try:
            report = validate(metadata)
        except TypeError as exc:
            self.fail(f"malformed metadata escaped validation: {exc}")
        self.assertFalse(report["valid"])
        self.assertTrue(any("order" in error for error in report["errors"]))


class ContextPoseSamplerCoversLowElevation(unittest.TestCase):
    """image_space_context_poses 가 저앙각에서 빈 목록을 돌려주던 결함 (2026-08-01).

    baseline 에서 context-rich 600장 중 39장이 `context_placement_attempts=0` 이었다.
    이미지 좌우 띠의 광선이 지평선 위로 가거나 지면 교점이 max_camera_distance 를
    넘어 후보가 전멸했기 때문이다 (기각 사유 64% camera_distance_out_of_band).
    """

    # v2_pilot_2k_seed7000_public 의 proposal 1062 (elevation 0.83도, 절단 조준으로
    # 시선이 위를 향한다) — baseline 에서 context 배치를 시도조차 못 한 실제 배치다.
    LOW_ELEV = dict(
        pallet_center=(0.0, 0.0, 0.075),
        camera_pos=(1.586164, -2.729825, 0.120476),
        camera_look=(0.0, 0.0, 1.456415),
        fx=605.9065, fy=605.9065, cx=480.0, cy=270.0,
        image_wh=(960, 540), ground_z=0.0, seed=1234,
    )
    NORMAL = dict(
        pallet_center=(0.0, 0.0, 0.075),
        camera_pos=(0.0, -3.0, 2.5),
        camera_look=(0.0, 0.0, 0.075),
        fx=600.0, fy=600.0, cx=320.0, cy=240.0,
        image_wh=(640, 480), ground_z=0.0, seed=1234,
    )

    def test_normal_elevation_still_uses_the_image_band_sampler(self):
        poses = scene.image_space_context_poses(**self.NORMAL)
        self.assertTrue(poses)
        self.assertTrue(all("fallback" not in pose for pose in poses))

    def test_low_elevation_no_longer_returns_an_empty_list(self):
        poses = scene.image_space_context_poses(**self.LOW_ELEV)
        self.assertTrue(poses, "저앙각에서 후보가 하나도 나오지 않았다")

    def test_low_elevation_is_served_by_the_fallback(self):
        poses = scene.image_space_context_poses(**self.LOW_ELEV)
        self.assertTrue(all(pose.get("fallback") == "ground_ring"
                            for pose in poses))

    def test_fallback_respects_the_pallet_clearance(self):
        for pose in scene.image_space_context_poses(**self.LOW_ELEV):
            self.assertGreaterEqual(math.hypot(pose["x"], pose["y"]),
                                    0.70 - 1e-9)

    def test_fallback_respects_the_camera_distance_band(self):
        cam = self.LOW_ELEV["camera_pos"]
        for pose in scene.image_space_context_poses(**self.LOW_ELEV):
            distance = math.hypot(pose["x"] - cam[0], pose["y"] - cam[1])
            self.assertGreaterEqual(distance, 0.50 - 1e-9)
            self.assertLessEqual(distance, 8.0 + 1e-9)

    def test_fallback_is_deterministic(self):
        self.assertEqual(scene.image_space_context_poses(**self.LOW_ELEV),
                         scene.image_space_context_poses(**self.LOW_ELEV))


if __name__ == "__main__":
    unittest.main()
