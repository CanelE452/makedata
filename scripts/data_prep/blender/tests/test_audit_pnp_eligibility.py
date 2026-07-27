import importlib.util
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


MODULE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "audit_pnp_eligibility.py")
)


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_pnp_eligibility", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_pnp_eligibility"] = module
    spec.loader.exec_module(module)
    return module


APE = _load_module()


def _base_args(**overrides):
    argv = ["--dir", "unused"]
    for key, value in overrides.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return APE.parse_args(argv)


def _geo_from_synthetic(**kwargs):
    lab = APE.synthetic_label(**kwargs)
    return lab, APE.frame_geometry(lab, lab["objects"][0])


class ThresholdConstantsTest(unittest.TestCase):
    def test_candidates_are_cell_multiples(self):
        self.assertEqual(APE.BELIEF_CELL_PX, 8.0)
        self.assertEqual(APE.THRESHOLD_CANDIDATES["2cell"], 16.0)
        self.assertEqual(APE.THRESHOLD_CANDIDATES["3cell"], 24.0)
        self.assertEqual(APE.THRESHOLD_CANDIDATES["4cell"], 32.0)

    def test_pnp_settings_match_evaluation_path(self):
        self.assertEqual(APE.PNP_RANSAC_REPROJ_PX, 8.0)
        self.assertEqual(APE.PNP_RANSAC_ITERS, 100)
        solver = APE.make_solver(np.eye(3), np.zeros((9, 3)))
        self.assertTrue(solver.use_ransac)
        self.assertEqual(solver.ransac_reproj_threshold, 8.0)
        self.assertEqual(solver.ransac_iterations, 100)

    def test_tiny_mask_area_matches_smallest_candidate(self):
        self.assertEqual(APE.TINY_MASK_AREA_PX, 256)


class GeometryHelpersTest(unittest.TestCase):
    def test_bbox_metrics(self):
        pts = np.array([[10.0, 20.0], [40.0, 25.0], [12.0, 60.0]])
        box = APE.bbox_metrics(pts)
        self.assertAlmostEqual(box["w"], 30.0)
        self.assertAlmostEqual(box["h"], 40.0)
        self.assertAlmostEqual(box["min_side"], 30.0)
        self.assertAlmostEqual(box["diag"], 50.0)
        self.assertAlmostEqual(box["area"], 1200.0)

    def test_bbox_metrics_rejects_non_finite(self):
        self.assertIsNone(APE.bbox_metrics(np.array([[0.0, 0.0], [np.nan, 1.0]]))["w"])
        self.assertIsNone(APE.bbox_metrics(None)["w"])

    def test_min_pair_distance(self):
        pts = np.array([[0.0, 0.0], [3.0, 4.0], [0.0, 1.0]])
        self.assertAlmostEqual(APE.min_pair_distance(pts), 1.0)
        self.assertIsNone(APE.min_pair_distance(np.array([[0.0, 0.0]])))

    def test_convex_hull_area(self):
        square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [5.0, 5.0]])
        self.assertAlmostEqual(APE.convex_hull_area(square), 100.0, places=3)
        self.assertEqual(APE.convex_hull_area(np.array([[0.0, 0.0], [1.0, 1.0]])), 0.0)

    def test_mask_bbox(self):
        arr = np.zeros((40, 60), dtype=np.uint8)
        arr[10:20, 5:35] = 255
        box = APE.mask_bbox(Image.fromarray(arr))
        self.assertEqual(box["w"], 30.0)
        self.assertEqual(box["h"], 10.0)
        self.assertEqual(box["min_side"], 10.0)

    def test_mask_bbox_empty(self):
        box = APE.mask_bbox(Image.fromarray(np.zeros((10, 10), dtype=np.uint8)))
        self.assertEqual(box["min_side"], 0.0)

    def test_rotation_geodesic(self):
        theta = math.radians(30.0)
        rz = np.array([[math.cos(theta), -math.sin(theta), 0.0],
                       [math.sin(theta), math.cos(theta), 0.0],
                       [0.0, 0.0, 1.0]])
        self.assertAlmostEqual(APE.rotation_geodesic_deg(np.eye(3), rz), 30.0, places=6)
        # -R (the pnp_solver "behind camera" flip) is not a rotation -> refuse to score it
        self.assertIsNone(APE.rotation_geodesic_deg(np.eye(3), -np.eye(3)))


class FrameGeometryTest(unittest.TestCase):
    def test_label_projection_is_reproduced_exactly(self):
        _lab, geo = _geo_from_synthetic(dist_m=3.0)
        self.assertIsNotNone(geo)
        self.assertLess(geo["label_reproj_consistency_px"], 1e-9)

    def test_translation_matches_label_location(self):
        lab, geo = _geo_from_synthetic(dist_m=4.0)
        expected = np.asarray(lab["objects"][0]["location"], dtype=np.float64)
        np.testing.assert_allclose(geo["t_obj_cam"], expected, atol=1e-9)

    def test_camera_distance_measured(self):
        _lab, geo = _geo_from_synthetic(dist_m=7.5)
        self.assertAlmostEqual(geo["camera_distance_measured_m"], 7.5, places=6)

    def test_exact_pnp_recovers_gt(self):
        _lab, geo = _geo_from_synthetic(dist_m=3.0)
        solver = APE.make_solver(geo["K"], geo["pts_obj9"])
        sol = APE.solve_pose(solver, geo["uv9"], geo["visible"])
        self.assertTrue(sol["success"])
        err = APE.pose_error(sol, geo)
        self.assertLess(err["trans_cm"], 0.01)
        self.assertLess(err["rot_deg"], 0.01)
        self.assertLess(sol["reproj_mean_px"], 0.01)

    def test_occluded_and_offscreen_keypoints_are_invisible(self):
        lab = APE.synthetic_label(dist_m=3.0)
        lab["objects"][0]["v2_labels"]["occlusion_fraction"] = [0.0, 0.6, 0.49, 0.5, 0, 0, 0, 0, 0]
        geo = APE.frame_geometry(lab, lab["objects"][0])
        self.assertTrue(geo["visible"][0])
        self.assertFalse(geo["visible"][1])   # 0.6 >= 0.5
        self.assertTrue(geo["visible"][2])    # 0.49 < 0.5
        self.assertFalse(geo["visible"][3])   # 0.5 is the exclusive bound
        # push the projection off-screen -> in_frame false
        lab2 = APE.synthetic_label(dist_m=3.0)
        lab2["objects"][0]["projected_cuboid"][0] = [-50.0, -50.0]
        geo2 = APE.frame_geometry(lab2, lab2["objects"][0])
        self.assertFalse(geo2["in_frame"][0])
        self.assertFalse(geo2["visible"][0])

    def test_pnp_needs_four_visible_keypoints(self):
        lab = APE.synthetic_label(dist_m=3.0)
        lab["objects"][0]["v2_labels"]["occlusion_fraction"] = [0.0, 0.0, 0.0, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
        geo = APE.frame_geometry(lab, lab["objects"][0])
        self.assertEqual(int(geo["visible"].sum()), 3)
        solver = APE.make_solver(geo["K"], geo["pts_obj9"])
        self.assertFalse(APE.solve_pose(solver, geo["uv9"], geo["visible"])["success"])

    def test_canonical_object_frame_is_not_assumed(self):
        """A frame whose cuboid order is permuted must still solve exactly."""
        lab = APE.synthetic_label(dist_m=3.0)
        obj = lab["objects"][0]
        perm = [5, 4, 7, 6, 1, 0, 3, 2]
        obj["cuboid"] = [obj["cuboid"][i] for i in perm]
        obj["projected_cuboid"] = [obj["projected_cuboid"][i] for i in perm]
        geo = APE.frame_geometry(lab, obj)
        self.assertLess(geo["label_reproj_consistency_px"], 1e-9)
        solver = APE.make_solver(geo["K"], geo["pts_obj9"])
        sol = APE.solve_pose(solver, geo["uv9"], geo["visible"])
        self.assertTrue(sol["success"])
        self.assertLess(APE.pose_error(sol, geo)["trans_cm"], 0.01)

    def test_missing_fields_return_none(self):
        lab = APE.synthetic_label()
        del lab["camera_data"]["intrinsics"]
        self.assertIsNone(APE.frame_geometry(lab, lab["objects"][0]))
        lab2 = APE.synthetic_label()
        lab2["objects"][0]["cuboid"] = lab2["objects"][0]["cuboid"][:5]
        self.assertIsNone(APE.frame_geometry(lab2, lab2["objects"][0]))


class MonteCarloTest(unittest.TestCase):
    def setUp(self):
        _lab, self.geo = _geo_from_synthetic(dist_m=3.0)
        self.solver = APE.make_solver(self.geo["K"], self.geo["pts_obj9"])

    def test_deterministic_for_same_seed(self):
        a = APE.monte_carlo(self.geo, self.solver, 2.0, 40, seed=1234)
        b = APE.monte_carlo(self.geo, self.solver, 2.0, 40, seed=1234)
        self.assertEqual(a["pose_fail_rate"], b["pose_fail_rate"])
        self.assertEqual(a["trans_cm"]["q90"], b["trans_cm"]["q90"])
        self.assertEqual(a["rot_deg"]["q95"], b["rot_deg"]["q95"])

    def test_different_seed_changes_draw(self):
        a = APE.monte_carlo(self.geo, self.solver, 2.0, 40, seed=1)
        b = APE.monte_carlo(self.geo, self.solver, 2.0, 40, seed=2)
        self.assertNotEqual(a["trans_cm"]["q50"], b["trans_cm"]["q50"])

    def test_error_grows_with_sigma(self):
        e1 = APE.monte_carlo(self.geo, self.solver, 1.0, 60, seed=7)
        e3 = APE.monte_carlo(self.geo, self.solver, 3.0, 60, seed=7)
        self.assertLess(e1["trans_cm"]["q50"], e3["trans_cm"]["q50"])
        self.assertLessEqual(e1["pose_fail_rate"], e3["pose_fail_rate"])

    def test_skips_when_too_few_visible(self):
        geo = dict(self.geo)
        geo["visible"] = np.array([True, True, True] + [False] * 6)
        res = APE.monte_carlo(geo, self.solver, 2.0, 10, seed=3)
        self.assertEqual(res["n_trials"], 0)
        self.assertIsNone(res["pose_fail_rate"])

    def test_rates_are_fractions(self):
        res = APE.monte_carlo(self.geo, self.solver, 2.0, 25, seed=11)
        self.assertEqual(res["n_trials"], 25)
        for key in ("solve_fail_rate", "diverged_rate", "pose_fail_rate"):
            self.assertGreaterEqual(res[key], 0.0)
            self.assertLessEqual(res[key], 1.0)


class EligibilityTest(unittest.TestCase):
    def test_candidate_thresholds(self):
        for min_side, expect in ((15.9, (False, False, False)),
                                 (16.0, (True, False, False)),
                                 (24.0, (True, True, False)),
                                 (32.0, (True, True, True))):
            out = APE.eligibility({"bbox_vis_min_side_px": min_side, "pnp_exact_success": True,
                                   "mask_m0_area": 100000})
            got = tuple(out[f"pnp_eligible_candidate_{n}"] for n in ("2cell", "3cell", "4cell"))
            self.assertEqual(got, expect, msg=f"min_side={min_side}")

    def test_failed_pnp_is_never_eligible(self):
        out = APE.eligibility({"bbox_vis_min_side_px": 500.0, "pnp_exact_success": False,
                               "mask_m0_area": 100000})
        for name in APE.THRESHOLD_CANDIDATES:
            self.assertFalse(out[f"pnp_eligible_candidate_{name}"])
        self.assertTrue(out["pnp_stress"])

    def test_tiny_warning(self):
        self.assertTrue(APE.eligibility({"bbox_vis_min_side_px": 10.0, "pnp_exact_success": True,
                                         "mask_m0_area": 100000})["tiny_warning"])
        self.assertTrue(APE.eligibility({"bbox_vis_min_side_px": 300.0, "pnp_exact_success": True,
                                         "mask_m0_area": 255})["tiny_warning"])
        self.assertFalse(APE.eligibility({"bbox_vis_min_side_px": 300.0, "pnp_exact_success": True,
                                          "mask_m0_area": 256})["tiny_warning"])

    def test_pnp_stress_rules(self):
        base = {"bbox_vis_min_side_px": 300.0, "pnp_exact_success": True, "mask_m0_area": 100000}
        self.assertFalse(APE.eligibility({**base, "mc2px_pose_fail_rate": 0.5,
                                          "mc2px_diverged_rate": 0.05})["pnp_stress"])
        self.assertTrue(APE.eligibility({**base, "mc2px_pose_fail_rate": 0.51,
                                         "mc2px_diverged_rate": 0.0})["pnp_stress"])
        self.assertTrue(APE.eligibility({**base, "mc2px_pose_fail_rate": 0.0,
                                         "mc2px_diverged_rate": 0.06})["pnp_stress"])


class ValidityTest(unittest.TestCase):
    def _record(self, **over):
        rec = {"rendered": True, "realize_ok": True, "camera_clearance_pass": True,
               "support_pass": True, "mask_invariants_pass": True,
               "ground_continuity_pass": True, "corrupt_rgb": False, "corrupt_mask": False,
               "exact_collision_count": 0, "camera_distance_limit_m": 10.0,
               "camera_distance_actual_m": 3.0}
        rec.update(over)
        return rec

    def test_clean_record_is_physical_valid(self):
        out = APE.physical_validity(self._record(), None, 5000)
        self.assertTrue(out["physical_valid"])
        self.assertEqual(out["physical_violations"], [])
        self.assertEqual(out["physical_unknown"], [])

    def test_violations_are_named(self):
        out = APE.physical_validity(self._record(exact_collision_count=2, support_pass=False),
                                    None, 5000)
        self.assertFalse(out["physical_valid"])
        self.assertIn("exact_collision_count", out["physical_violations"])
        self.assertIn("support_pass", out["physical_violations"])

    def test_distance_cap(self):
        out = APE.physical_validity(self._record(camera_distance_actual_m=10.5), None, 5000)
        self.assertIn("camera_distance_over_limit", out["physical_violations"])

    def test_distance_recomputed_when_record_predates_phase1(self):
        rec = self._record()
        rec.pop("camera_distance_actual_m")
        rec.pop("camera_distance_limit_m")
        _lab, geo = _geo_from_synthetic(dist_m=42.0)
        out = APE.physical_validity(rec, geo, 5000)
        self.assertEqual(out["camera_distance_source"], "label_recomputed")
        self.assertAlmostEqual(out["camera_distance_used_m"], 42.0, places=5)
        self.assertIn("camera_distance_over_limit", out["physical_violations"])

    def test_missing_field_is_unknown_not_violation(self):
        rec = self._record()
        rec.pop("ground_continuity_pass")
        out = APE.physical_validity(rec, None, 5000)
        self.assertIn("ground_continuity_pass", out["physical_unknown"])
        self.assertNotIn("ground_continuity_pass", out["physical_violations"])
        self.assertTrue(out["physical_valid"])

    def test_empty_mask_is_violation(self):
        out = APE.physical_validity(self._record(), None, 0)
        self.assertIn("empty_target_mask", out["physical_violations"])

    def test_gate_valid_from_record(self):
        rec = {"all_pass": False, "G1_pass": True, "G2_pass": True, "G3_pass": True,
               "G4_pass": True, "G5_pass": False}
        out = APE.gate_validity(rec, None)
        self.assertFalse(out["gate_valid"])
        self.assertFalse(out["gate_valid_unknown"])

    def test_gate_valid_falls_back_to_label(self):
        obj = {"safety_gates": {"G1_Vvis>=4": True, "G2_extocc_1to4": True,
                                "G3_visible>=0.5unocc": True, "G4_center_inframe": True,
                                "G5_luma_floor": True, "all_pass": True}}
        out = APE.gate_validity({}, obj)
        self.assertTrue(out["gate_valid"])
        self.assertFalse(out["gate_valid_unknown"])

    def test_gate_unknown_when_nothing_present(self):
        out = APE.gate_validity({}, None)
        self.assertTrue(out["gate_valid_unknown"])
        self.assertFalse(out["gate_valid"])


class KneeTest(unittest.TestCase):
    def test_smooth_decay_has_no_knee(self):
        sweep = [{"cells": c, "fail_rate_mean": 0.5 - 0.04 * c} for c in range(1, 9)]
        self.assertFalse(APE.knee_analysis(sweep)["has_knee"])

    def test_sharp_drop_is_a_knee(self):
        vals = [0.90, 0.89, 0.88, 0.20, 0.19, 0.18, 0.17, 0.16]
        sweep = [{"cells": c, "fail_rate_mean": v} for c, v in enumerate(vals, 1)]
        knee = APE.knee_analysis(sweep)
        self.assertTrue(knee["has_knee"])
        self.assertEqual(knee["max_step_at_cells"], 4)

    def test_decision_reports_insufficient_evidence(self):
        summary = {
            "n_geometry_ok": 400,
            "candidates": {n: {"n_pass": 10, "n_fail": 10,
                               "mc2px_pass_pose_fail_rate_mean": 0.3}
                           for n in APE.THRESHOLD_CANDIDATES},
            "knee": {"has_knee": False, "median_step": 0.03, "max_step": 0.04,
                     "max_step_ratio": 1.2, "max_step_at_cells": 4},
        }
        text = APE.decision_text(summary, [], [])
        self.assertIn("확정 불가", text)


class EndToEndTest(unittest.TestCase):
    def _build_dataset(self, root: Path, distances) -> None:
        (root / "labels").mkdir(parents=True)
        (root / "mask").mkdir(parents=True)
        recs = []
        for idx, dist in enumerate(distances):
            lab = APE.synthetic_label(dist_m=dist)
            (root / "labels" / f"f{idx:04d}_label.json").write_text(json.dumps(lab), encoding="utf-8")
            arr = np.zeros((480, 640), dtype=np.uint8)
            arr[100:160, 100:260] = 255
            Image.fromarray(arr).save(root / "mask" / f"f{idx:04d}_m0.png")
            recs.append({"idx": idx, "rendered": True, "realize_ok": True,
                         "exact_collision_count": 0, "camera_clearance_pass": True,
                         "support_pass": True, "mask_invariants_pass": True,
                         "ground_continuity_pass": True, "corrupt_rgb": False,
                         "corrupt_mask": False, "camera_distance_limit_m": 10.0,
                         "camera_distance_actual_m": dist, "all_pass": True,
                         "G1_pass": True, "G2_pass": True, "G3_pass": True,
                         "G4_pass": True, "G5_pass": True})
        with (root / "records.jsonl").open("w", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec) + "\n")

    def test_run_writes_all_artifacts_and_keeps_every_frame(self):
        distances = [1.5, 3.0, 6.0, 12.0, 40.0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            out = Path(tmp) / "out"
            self._build_dataset(root, distances)
            args = APE.parse_args(["--dir", str(root), "--out", str(out), "--mc-trials", "15"])
            summary = APE.run(args)

            for name in ("pnp_threshold_study.csv", "pnp_threshold_study.md",
                         "pnp_stability_continuous.pdf", "pnp_eligibility_manifest.csv",
                         "pnp_eligibility_manifest.json"):
                self.assertTrue((out / name).exists(), msg=name)

            self.assertEqual(summary["n_frames"], len(distances))
            self.assertEqual(summary["n_pnp_exact_success"], len(distances))
            self.assertLess(summary["label_reproj_consistency_px_max"], 1e-6)

            import csv as _csv
            with (out / "pnp_eligibility_manifest.csv").open(encoding="utf-8") as f:
                manifest = list(_csv.DictReader(f))
            # no frame is dropped by this phase
            self.assertEqual(len(manifest), len(distances))
            for col in ("physical_valid", "gate_valid", "tiny_warning", "pnp_stress",
                        "pnp_eligible_candidate_2cell", "pnp_eligible_candidate_3cell",
                        "pnp_eligible_candidate_4cell"):
                self.assertIn(col, manifest[0])
            # the 40 m frame violates the 10 m cap, the near ones do not
            self.assertEqual(manifest[-1]["physical_valid"], "False")
            self.assertEqual(manifest[0]["physical_valid"], "True")

            payload = json.loads((out / "pnp_eligibility_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["frames_deleted"], 0)
            self.assertEqual(payload["pnp"]["flag"], "SOLVEPNP_EPNP")
            self.assertEqual(payload["pnp"]["reprojectionError"], 8.0)

            md = (out / "pnp_threshold_study.md").read_text(encoding="utf-8")
            self.assertIn("1 belief-map cell = 8 source-image pixels", md)
            self.assertIn("## 6. Decision", md)

    def test_run_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            self._build_dataset(root, [2.0, 5.0])
            results = []
            for run_id in range(2):
                out = Path(tmp) / f"out{run_id}"
                args = APE.parse_args(["--dir", str(root), "--out", str(out),
                                       "--mc-trials", "15", "--no-pdf"])
                summary = APE.run(args)
                results.append([r["mc2px_trans_cm_q90"] for r in summary["rows"]])
            self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
