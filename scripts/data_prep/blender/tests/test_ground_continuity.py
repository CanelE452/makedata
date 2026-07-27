"""Phase-2 ground-continuity audit — bpy-free half.

The raycast itself needs Blender (see blender_probe_v2_ground_continuity.py); everything
around it — the 11-point probe interpolation, the finite procedural-plane bounds test and the
pass/fail aggregation — is pure geometry and is pinned down here.
"""

import math
import os
import sys
import unittest


BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import scene_placement_v2 as sp2


FLOOR = "FloorRandPlane"


def _sample(x, y, support=FLOOR, support_z=0.0, hit=True, ok=True, hit_object=None):
    return {
        "point": (float(x), float(y)),
        "hit": bool(hit),
        "hit_object": hit_object if hit_object is not None else (support if hit else None),
        "support": support,
        "support_z": support_z,
        "normal_z": 1.0 if hit else None,
        "ok": bool(ok),
    }


def _flat_samples(points, z=0.0):
    return [_sample(x, y, support_z=z) for x, y in points]


class ProbePointTests(unittest.TestCase):
    def test_eleven_points_include_both_endpoints(self):
        points = sp2.ground_probe_points_xy((-4.0, 0.0), (2.0, 3.0))
        self.assertEqual(11, len(points))
        self.assertEqual(11, sp2.GROUND_PROBE_COUNT)
        self.assertAlmostEqual(-4.0, points[0][0])
        self.assertAlmostEqual(0.0, points[0][1])
        self.assertAlmostEqual(2.0, points[-1][0])
        self.assertAlmostEqual(3.0, points[-1][1])

    def test_points_are_uniformly_spaced_and_collinear(self):
        points = sp2.ground_probe_points_xy((0.0, 0.0), (10.0, 5.0))
        steps = [
            math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)
        ]
        self.assertAlmostEqual(max(steps), min(steps), places=9)
        total = math.dist(points[0], points[-1])
        self.assertAlmostEqual(total, sum(steps), places=9)
        for x, y in points:
            self.assertAlmostEqual(y, x * 0.5, places=9)

    def test_camera_directly_above_target_collapses_to_one_spot(self):
        points = sp2.ground_probe_points_xy((1.5, -2.5), (1.5, -2.5))
        self.assertEqual(11, len(points))
        self.assertEqual({(1.5, -2.5)}, set(points))

    def test_custom_count_and_invalid_inputs(self):
        self.assertEqual(3, len(sp2.ground_probe_points_xy((0.0, 0.0), (1.0, 0.0), count=3)))
        with self.assertRaises(ValueError):
            sp2.ground_probe_points_xy((0.0, 0.0), (1.0, 0.0), count=1)
        with self.assertRaises(ValueError):
            sp2.ground_probe_points_xy((0.0, 0.0, 0.0), (1.0, 0.0))
        with self.assertRaises(ValueError):
            sp2.ground_probe_points_xy((float("nan"), 0.0), (1.0, 0.0))


class PlaneBoundsTests(unittest.TestCase):
    def test_bounds_are_centred_squares(self):
        bounds = sp2.procedural_plane_bounds((2.0, -1.0), 50.0)
        self.assertEqual((-23.0, -26.0, 27.0, 24.0), bounds)

    def test_margin_is_positive_inside_and_negative_outside(self):
        bounds = sp2.procedural_plane_bounds((0.0, 0.0), 50.0)
        self.assertAlmostEqual(25.0, sp2.plane_bounds_margin_m((0.0, 0.0), bounds))
        self.assertAlmostEqual(5.0, sp2.plane_bounds_margin_m((20.0, 0.0), bounds))
        self.assertAlmostEqual(-1.0, sp2.plane_bounds_margin_m((26.0, 0.0), bounds))
        self.assertIsNone(sp2.plane_bounds_margin_m((0.0, 0.0), None))

    def test_invalid_plane_size(self):
        with self.assertRaises(ValueError):
            sp2.procedural_plane_bounds((0.0, 0.0), 0.0)


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.bounds = sp2.procedural_plane_bounds((0.0, 0.0), 50.0)

    def test_flat_floor_inside_bounds_passes(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        verdict = sp2.ground_continuity_verdict(
            _flat_samples(points, z=-0.006),
            floor_object_name=FLOOR,
            plane_bounds=self.bounds,
        )
        self.assertTrue(verdict["ground_continuity_pass"])
        self.assertEqual(11, verdict["ground_probe_count"])
        self.assertEqual(0, verdict["ground_probe_fail_count"])
        self.assertFalse(verdict["procedural_floor_edge_risk"])
        self.assertIsNone(verdict["ground_continuity_reason"])
        self.assertEqual(0.0, verdict["ground_probe_max_step_m"])
        self.assertEqual(
            ["floor"] * 11,
            [row["kind"] for row in verdict["ground_probe_hit_objects"]],
        )

    def test_missing_ground_under_one_probe_fails(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        samples = _flat_samples(points)
        samples[0] = _sample(*points[0], support=None, support_z=None, hit=False, ok=False)
        verdict = sp2.ground_continuity_verdict(
            samples, floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertFalse(verdict["ground_continuity_pass"])
        self.assertEqual(1, verdict["ground_probe_fail_count"])
        self.assertEqual("miss", verdict["ground_probe_hit_objects"][0]["kind"])
        self.assertIn("probe0_miss", verdict["ground_continuity_reason"])

    def test_non_support_first_hit_is_a_failure_and_is_named(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        samples = _flat_samples(points)
        samples[5] = _sample(
            *points[5], support=None, support_z=None, ok=False, hit_object="CrateStack"
        )
        verdict = sp2.ground_continuity_verdict(
            samples, floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertFalse(verdict["ground_continuity_pass"])
        row = verdict["ground_probe_hit_objects"][5]
        self.assertEqual("other", row["kind"])
        self.assertEqual("CrateStack", row["hit_object"])

    def test_steep_support_normal_is_rejected(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        samples = _flat_samples(points)
        samples[3] = _sample(*points[3], support_z=0.0, ok=False)
        verdict = sp2.ground_continuity_verdict(
            samples, floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertFalse(verdict["ground_continuity_pass"])
        self.assertEqual("steep", verdict["ground_probe_hit_objects"][3]["kind"])

    def test_non_floor_support_still_passes_but_is_labelled(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        samples = _flat_samples(points)
        samples[2] = _sample(*points[2], support="Warehouse_Ground", support_z=0.0)
        verdict = sp2.ground_continuity_verdict(
            samples, floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertTrue(verdict["ground_continuity_pass"])
        self.assertEqual("support", verdict["ground_probe_hit_objects"][2]["kind"])

    def test_height_step_beyond_tolerance_fails(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        samples = _flat_samples(points)
        for idx in range(5, 11):
            samples[idx] = _sample(*points[idx], support_z=0.30)
        verdict = sp2.ground_continuity_verdict(
            samples, floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertFalse(verdict["ground_continuity_pass"])
        self.assertEqual(0, verdict["ground_probe_fail_count"])
        self.assertAlmostEqual(0.30, verdict["ground_probe_max_step_m"])
        self.assertIn("support_z_discontinuity", verdict["ground_continuity_reason"])

    def test_step_just_inside_tolerance_passes(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        samples = _flat_samples(points)
        for idx in range(5, 11):
            samples[idx] = _sample(*points[idx], support_z=0.049)
        verdict = sp2.ground_continuity_verdict(
            samples, floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertTrue(verdict["ground_continuity_pass"])
        self.assertEqual(0.05, sp2.GROUND_PROBE_STEP_TOLERANCE_M)

    def test_probe_outside_finite_plane_raises_edge_risk(self):
        points = sp2.ground_probe_points_xy((-40.0, 0.0), (0.0, 0.0))
        verdict = sp2.ground_continuity_verdict(
            _flat_samples(points), floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertFalse(verdict["ground_continuity_pass"])
        self.assertTrue(verdict["procedural_floor_edge_risk"])
        self.assertAlmostEqual(-15.0, verdict["procedural_floor_edge_margin_m"])
        self.assertIn("procedural_floor_edge", verdict["ground_continuity_reason"])

    def test_ten_metre_camera_keeps_headroom_on_the_fifty_metre_plane(self):
        points = sp2.ground_probe_points_xy((10.0, 0.0), (0.0, 0.0))
        verdict = sp2.ground_continuity_verdict(
            _flat_samples(points), floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        self.assertTrue(verdict["ground_continuity_pass"])
        self.assertFalse(verdict["procedural_floor_edge_risk"])
        self.assertAlmostEqual(15.0, verdict["procedural_floor_edge_margin_m"])

    def test_native_floor_mode_skips_the_bounds_test(self):
        points = sp2.ground_probe_points_xy((-40.0, 0.0), (0.0, 0.0))
        samples = [_sample(x, y, support="Warehouse_Ground") for x, y in points]
        verdict = sp2.ground_continuity_verdict(samples, plane_bounds=None)
        self.assertTrue(verdict["ground_continuity_pass"])
        self.assertFalse(verdict["procedural_floor_edge_risk"])
        self.assertIsNone(verdict["procedural_floor_edge_margin_m"])

    def test_probe_count_mismatch_and_empty_input(self):
        points = sp2.ground_probe_points_xy((-4.0, 0.0), (0.0, 0.0), count=5)
        verdict = sp2.ground_continuity_verdict(
            _flat_samples(points), floor_object_name=FLOOR
        )
        self.assertFalse(verdict["ground_continuity_pass"])
        self.assertIn("probe_count_mismatch", verdict["ground_continuity_reason"])
        empty = sp2.ground_continuity_verdict([])
        self.assertFalse(empty["ground_continuity_pass"])
        self.assertEqual(0, empty["ground_probe_count"])

    def test_metric_names_match_the_phase2_contract(self):
        points = sp2.ground_probe_points_xy((-8.0, 0.0), (0.0, 0.0))
        verdict = sp2.ground_continuity_verdict(
            _flat_samples(points), floor_object_name=FLOOR, plane_bounds=self.bounds
        )
        for key in (
            "ground_continuity_pass",
            "ground_probe_count",
            "ground_probe_fail_count",
            "ground_probe_hit_objects",
            "procedural_floor_edge_risk",
        ):
            self.assertIn(key, verdict)


class AuditWiringTests(unittest.TestCase):
    def test_audit_columns_carry_the_ground_metrics(self):
        import importlib.util

        path = os.path.join(BLENDER_DIR, "audit_v2_scene_logic.py")
        spec = importlib.util.spec_from_file_location("audit_v2_scene_logic", path)
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        columns = audit.audit_columns(["m0", "m4"])
        for name in (
            "ground_continuity_pass",
            "ground_probe_fail_count",
            "procedural_floor_edge_risk",
        ):
            self.assertIn(name, columns)

        rows = [
            {"idx": 0, "ground_continuity_pass": True, "ground_probe_fail_count": 0,
             "procedural_floor_edge_margin_m": 15.0, "ground_probe_max_step_m": 0.0,
             "procedural_floor_edge_risk": False, "ground_continuity_reason": None},
            {"idx": 1, "ground_continuity_pass": False, "ground_probe_fail_count": 2,
             "procedural_floor_edge_margin_m": -1.0, "ground_probe_max_step_m": 0.4,
             "procedural_floor_edge_risk": True,
             "ground_continuity_reason": "probe0_miss;procedural_floor_edge"},
            {"idx": 2, "ground_continuity_pass": None},
        ]
        summary = audit.ground_continuity_summary(rows)
        self.assertEqual(2, summary["measured_frame_count"])
        self.assertEqual(1, summary["unmeasured_frame_count"])
        self.assertEqual(0.5, summary["pass_rate"])
        self.assertEqual([1], summary["fail_indices"])
        self.assertEqual([1], summary["floor_edge_risk_indices"])
        self.assertEqual(-1.0, summary["min_floor_edge_margin_m"])
        self.assertEqual(0.4, summary["max_probe_step_m"])
        self.assertEqual(1, summary["reason_counts"]["probe0_miss"])


if __name__ == "__main__":
    unittest.main()
