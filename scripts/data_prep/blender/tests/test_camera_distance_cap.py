"""Phase-1 camera-distance cap (MAX_CAMERA_DISTANCE_M) — bpy-free.

The v2 sampler draws a projected-size ratio and solve_placement inverts it into a camera
distance d = fx*PALLET_W/(ratio*image_width). Without a cap the open lower edge of the first
ratio bin puts the camera hundreds of metres away. These tests pin the cap down at the
SAMPLING stage (feasible-interval narrowing, no clamping), keep determinism, and check that
the unrelated stratification axes are untouched.

Set V2_CAP_BULK_N to override the bulk sample size (default 100000):
    V2_CAP_BULK_N=10000 python -m pytest tests/test_camera_distance_cap.py
"""

import math
import os
import sys
import unittest


BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import v2_pipeline as vp


BULK_N = int(os.environ.get("V2_CAP_BULK_N", "100000"))
BULK_SEED = 7000
MARGINAL_TOL = 0.01


def _target_distance(spec):
    """Reproduce solve_placement step (1) from a FrameSpec alone."""
    ratio = max(float(spec.proj_size_ratio), 1e-3)
    return float(spec.fx) * vp.PALLET_W / (ratio * float(spec.resolution[0]))


def _fracs(values, keys):
    n = len(values)
    tally = {k: 0 for k in keys}
    for v in values:
        tally[v] = tally.get(v, 0) + 1
    return {k: tally[k] / n for k in keys}


class BulkSampleMixin:
    """One shared bulk sample-only draw (the cap lives in sample_frame, so the sample-only
    path is the one under test; the accepted path is covered separately)."""

    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()
        cls.specs, _ = vp.generate_specs(BULK_N, BULK_SEED, cls.assets)


class CameraDistanceCapTests(BulkSampleMixin, unittest.TestCase):
    def test_bulk_target_distance_never_exceeds_cap(self):
        distances = [_target_distance(s) for s in self.specs]
        self.assertLessEqual(max(distances), vp.MAX_CAMERA_DISTANCE_M + 1e-6)

    def test_bulk_has_no_nan_or_inf(self):
        bad = [
            s.frame_index
            for s in self.specs
            if not (
                math.isfinite(s.proj_size_ratio)
                and math.isfinite(s.proj_size_feasible_lower)
                and math.isfinite(s.fx)
                and math.isfinite(_target_distance(s))
            )
        ]
        self.assertEqual([], bad)

    def test_sampled_ratio_stays_inside_its_feasible_interval(self):
        for spec in self.specs:
            lo, hi = vp.PROJ_SIZE_EDGES[spec.proj_size_bin]
            feasible_lo = max(lo, spec.proj_size_feasible_lower)
            self.assertLess(feasible_lo, hi)
            self.assertGreaterEqual(spec.proj_size_ratio, feasible_lo)
            self.assertLess(spec.proj_size_ratio, hi)

    def test_no_point_mass_at_the_feasible_floor(self):
        """A clamp would pile probability exactly on proj_size_feasible_lower."""
        floored = [
            s for s in self.specs
            if abs(s.proj_size_ratio - s.proj_size_feasible_lower) < 1e-12
        ]
        self.assertEqual([], floored)

    def test_first_bin_is_kept_where_it_is_feasible(self):
        """The fix must NOT delete PROJ_SIZE_EDGES[0]; wide/short-focal frames reach it."""
        bin0 = [s for s in self.specs if s.proj_size_bin == 0]
        self.assertGreater(len(bin0), 0)
        self.assertTrue(all(s.proj_size_feasible_lower < 0.10 for s in bin0))


class CameraDistanceCapDeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()

    def test_same_seed_gives_identical_ratio_and_distance_sequences(self):
        a, _ = vp.generate_specs(3000, 7000, self.assets)
        b, _ = vp.generate_specs(3000, 7000, self.assets)
        self.assertEqual(
            [(s.proj_size_ratio, s.proj_size_feasible_lower) for s in a],
            [(s.proj_size_ratio, s.proj_size_feasible_lower) for s in b],
        )
        self.assertEqual(
            [_target_distance(s) for s in a],
            [_target_distance(s) for s in b],
        )

    def test_accepted_path_target_distance_sequence_is_deterministic(self):
        a = vp.generate_accepted(400, 7500, self.assets, placement_mode="constrained")[0]
        b = vp.generate_accepted(400, 7500, self.assets, placement_mode="constrained")[0]
        self.assertEqual(
            [p.camera_distance_target_m for p in a],
            [p.camera_distance_target_m for p in b],
        )

    def test_different_seed_gives_a_different_sequence(self):
        a, _ = vp.generate_specs(500, 7000, self.assets)
        b, _ = vp.generate_specs(500, 7001, self.assets)
        self.assertNotEqual(
            [s.proj_size_ratio for s in a],
            [s.proj_size_ratio for s in b],
        )


class CameraDistanceCapAcceptedPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()
        cls.accepted, cls.rejects, _, _ = vp.generate_accepted(
            5000, BULK_SEED, cls.assets, placement_mode="constrained"
        )

    def test_accepted_plans_respect_the_cap(self):
        distances = [p.camera_distance_target_m for p in self.accepted]
        self.assertLessEqual(max(distances), vp.MAX_CAMERA_DISTANCE_M + 1e-6)
        self.assertTrue(all(math.isfinite(d) for d in distances))

    def test_defensive_reject_never_fires_for_a_sampled_spec(self):
        reasons = [r.reason for r in self.rejects]
        self.assertEqual(0, reasons.count("camera_distance_out_of_range"))

    def test_plan_exposes_limit_and_target(self):
        plan = self.accepted[0]
        self.assertEqual(vp.MAX_CAMERA_DISTANCE_M, plan.camera_distance_limit_m)
        self.assertEqual(plan.cam_distance_m, plan.camera_distance_target_m)
        self.assertIn("camera_distance_target_m", plan.to_dict())
        self.assertIn("proj_size_feasible_lower", plan.to_dict()["spec"])


class CameraDistanceDefensiveRejectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()

    def test_hand_built_over_cap_spec_is_rejected_not_clamped(self):
        spec = vp.generate_specs(1, 7000, self.assets)[0][0]
        # ratio far below the frame's feasible floor => d well past the cap.
        over = vp.replace(spec, proj_size_ratio=0.001, proj_size_feasible_lower=0.0)
        result = vp.solve_placement(over, self.assets, placement_mode="constrained")
        self.assertIsInstance(result, vp.Reject)
        self.assertEqual("camera_distance_out_of_range", result.reason)


class CameraDistanceInfeasibleCapTests(unittest.TestCase):
    """Drive the cap so low that NO ratio bin is reachable -> explicit error, no hang."""

    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()

    def setUp(self):
        self._saved = vp.MAX_CAMERA_DISTANCE_M

    def tearDown(self):
        vp.MAX_CAMERA_DISTANCE_M = self._saved

    def test_all_bins_infeasible_raises_runtime_error(self):
        # min over the prescription of fx*PALLET_W/image_width is 300*1.1/960 = 0.34375, so a
        # 0.30 m cap forces feasible_lower > 1.0 = the top bin edge for EVERY (fx, width).
        vp.MAX_CAMERA_DISTANCE_M = 0.30
        with self.assertRaises(RuntimeError) as ctx:
            vp.generate_specs(50, 7000, self.assets)
        self.assertIn("no feasible proj_size bin", str(ctx.exception))

    def test_accepted_path_also_raises_instead_of_looping(self):
        vp.MAX_CAMERA_DISTANCE_M = 0.30
        with self.assertRaises(RuntimeError):
            vp.generate_accepted(10, 7000, self.assets, placement_mode="constrained")

    def test_tight_but_survivable_cap_keeps_only_the_reachable_bins(self):
        vp.MAX_CAMERA_DISTANCE_M = 3.0
        specs, _ = vp.generate_specs(2000, 7000, self.assets)
        distances = [_target_distance(s) for s in specs]
        self.assertLessEqual(max(distances), 3.0 + 1e-6)
        self.assertEqual(
            [],
            [s.frame_index for s in specs
             if s.proj_size_ratio < s.proj_size_feasible_lower],
        )


class UnrelatedAxisMarginalTests(BulkSampleMixin, unittest.TestCase):
    """The cap touches only the projected-size axis. Every other stratified axis must still
    land on its prescribed marginal (tolerance 0.01)."""

    def _assert_marginal(self, values, keys, prescribed):
        emp = _fracs(values, keys)
        for key, want in zip(keys, prescribed):
            self.assertLessEqual(
                abs(emp[key] - want), MARGINAL_TOL,
                f"{key}: empirical={emp[key]:.4f} prescribed={want:.4f}",
            )

    def test_elevation_bin_marginal(self):
        self._assert_marginal(
            [s.elev_bin for s in self.specs],
            list(range(len(vp.ELEV_BIN_FRAC))),
            vp.ELEV_BIN_FRAC,
        )

    def test_v_target_marginal(self):
        self._assert_marginal(
            [s.v_target for s in self.specs], vp.V_VALUES, vp.V_FRAC
        )

    def test_azimuth_bin_marginal(self):
        self._assert_marginal(
            [s.azimuth_bin for s in self.specs],
            list(range(vp.AZIMUTH_NBINS)),
            vp.AZIMUTH_FRAC,
        )

    def test_scene_preset_marginal(self):
        self._assert_marginal(
            [s.scene_preset for s in self.specs],
            vp.SCENE_PRESETS,
            vp.SCENE_PRESET_FRAC,
        )

    def test_aspect_and_fx_marginals(self):
        self._assert_marginal(
            [s.aspect for s in self.specs],
            [a for a, _ in vp.ASPECTS],
            vp.ASPECT_FRAC,
        )
        self._assert_marginal(
            [s.fx_mode for s in self.specs], vp.FX_MODES, vp.FX_FRAC
        )

    def test_f_target_and_cargo_marginals(self):
        self._assert_marginal(
            [s.f_target_bin for s in self.specs],
            list(range(len(vp.F_TARGET_FRAC))),
            vp.F_TARGET_FRAC,
        )
        self._assert_marginal(
            [s.cargo_on for s in self.specs], [False, True], vp.CARGO_FRAC
        )

    def test_projected_size_bin_marginal_survives_the_cap(self):
        """Masking infeasible bins must NOT distort the prescribed 0.20/bin: the quota
        deficit re-targets a masked bin on the next frame whose intrinsics allow it."""
        self._assert_marginal(
            [s.proj_size_bin for s in self.specs],
            list(range(len(vp.PROJ_SIZE_FRAC))),
            vp.PROJ_SIZE_FRAC,
        )


class RecordWiringTests(unittest.TestCase):
    """The 500-record runner must EXPOSE the cap fields, and camera_distance_actual_m must be
    RE-MEASURED from the realized scene rather than copied from the plan target."""

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def test_record_rendered_exposes_camera_distance_fields(self):
        import tempfile

        from PIL import Image

        plan = _one_plan()
        cam = [3.0, 0.0, 1.0]
        # deliberately NOT the plan's centroid: actual must differ from target here.
        centroid = [0.0, 0.0, 0.075]
        rs = {
            "cam_pos": cam,
            "W": 640,
            "pallet_name": plan.spec.pallet_type,
            "background": None,
            "floor_mode": None,
            "elevation_deg_actual": 18.0,
            "occluder": None,
            "n_cargo": 0,
            "constrained_metrics": {},
        }
        meas = {
            "mask_paths": {},
            "V_inframe": 8,
            "V_vis": 8,
            "uv8_v4": [[100.0, 10.0]] * 4 + [[420.0, 300.0]] * 4,
            "centroid_world": centroid,
        }
        gates = {"G1_Vvis>=4": True, "all_pass": True}

        with tempfile.TemporaryDirectory() as tmp:
            rgb_path = os.path.join(tmp, "f0000_rgb.png")
            Image.new("RGB", (8, 8), (30, 30, 30)).save(rgb_path)
            record = self.runner._record_rendered(
                0, 1, "clean-static", plan, rs, meas, gates,
                1.0, {"noise_tier": "clean"}, rgb_path,
                os.path.join(tmp, "f0000_label.json"),
            )

        expected_actual = math.dist(cam, centroid)
        self.assertEqual(vp.MAX_CAMERA_DISTANCE_M, record["camera_distance_limit_m"])
        self.assertAlmostEqual(plan.cam_distance_m, record["camera_distance_target_m"])
        self.assertAlmostEqual(expected_actual, record["camera_distance_actual_m"])
        self.assertAlmostEqual(
            expected_actual - plan.cam_distance_m, record["camera_distance_error_m"]
        )
        self.assertNotAlmostEqual(
            record["camera_distance_actual_m"], record["camera_distance_target_m"]
        )
        self.assertAlmostEqual(
            plan.spec.proj_size_feasible_lower,
            record["projected_size_feasible_lower"],
        )
        self.assertAlmostEqual(320.0 / 640.0, record["projected_size_actual"])

    def test_realize_failure_record_still_carries_target_and_limit(self):
        plan = _one_plan()
        record = self.runner._record_realize_failure(
            0, 1, "clean-static", plan, 1.0, {"failure_reason": "x"}
        )
        self.assertEqual(vp.MAX_CAMERA_DISTANCE_M, record["camera_distance_limit_m"])
        self.assertAlmostEqual(plan.cam_distance_m, record["camera_distance_target_m"])
        self.assertAlmostEqual(
            plan.spec.proj_size_feasible_lower,
            record["projected_size_feasible_lower"],
        )


class DistancePreference(unittest.TestCase):
    """2026-08-04 — 거리 분포를 2~6m 봉우리로 옮긴 장치."""

    def test_lognorm_roundtrip_is_exact(self):
        for d in (1.5, 2.0, 3.5, 6.0, 10.0):
            self.assertAlmostEqual(vp._lognorm_icdf(vp._lognorm_cdf(d)), d, places=9)

    def test_erfinv_matches_erf(self):
        import math
        for y in (-0.999, -0.5, 0.0, 0.3, 0.9, 0.9999):
            self.assertAlmostEqual(math.erf(vp._erfinv(y)), y, places=12)

    def test_median_is_the_configured_median(self):
        self.assertAlmostEqual(vp._lognorm_cdf(vp.DIST_PREF_MEDIAN_M), 0.5, places=12)

    def test_spans_respect_the_distance_window(self):
        """구간이 [MIN, MAX] 를 넘어서면 안 된다 — 넘으면 solve 방어 reject 를 맞는다."""
        for fx in (300.0, 450.0, 615.0, 700.0):
            for width in (560, 640, 720, 960):
                for span in vp.proj_size_bin_distance_spans(fx, width):
                    if span is None:
                        continue
                    d_lo, d_hi = span
                    self.assertGreaterEqual(d_lo, vp.MIN_CAMERA_DISTANCE_M - 1e-9)
                    self.assertLessEqual(d_hi, vp.MAX_CAMERA_DISTANCE_M + 1e-9)
                    self.assertLess(d_lo, d_hi)

    def test_infeasible_bins_get_zero_weight(self):
        spans = vp.proj_size_bin_distance_spans(300.0, 640)
        weights = vp.distance_pref_weights(spans)
        self.assertEqual(len(weights), len(vp.PROJ_SIZE_EDGES))
        for span, w in zip(spans, weights):
            if span is None:
                self.assertEqual(w, 0.0)
            else:
                self.assertGreater(w, 0.0)   # 실현 가능하면 deficit 이 살아 있어야 한다

    def test_weight_prefers_the_target_band(self):
        """목표 대역을 덮는 구간이 극단 구간보다 무겁게 나와야 의미가 있다."""
        spans = vp.proj_size_bin_distance_spans(615.0, 640)
        weights = vp.distance_pref_weights(spans)
        best = max(range(len(spans)), key=lambda i: weights[i])
        d_lo, d_hi = spans[best]
        self.assertLess(d_lo, 6.0)
        self.assertGreater(d_hi, 2.0)

    def test_deficit_pick_weight_steers_without_removing_bins(self):
        """weight 는 soft steer 다 — 눌린 구간도 결국 뽑혀야(deficit 소진) 한다."""
        import random
        frac = [0.5, 0.5]
        counts = [0, 0]
        rng = random.Random(4)
        picks = [vp._deficit_pick(frac, counts, rng, weight=[1.0, 0.01])
                 for _ in range(400)]
        self.assertGreater(picks.count(0), picks.count(1))
        self.assertGreater(picks.count(1), 0)

    def test_deficit_pick_weight_length_is_checked(self):
        import random
        with self.assertRaises(ValueError):
            vp._deficit_pick([0.5, 0.5], [0, 0], random.Random(1), weight=[1.0])

    def test_realised_distance_peaks_in_the_target_band(self):
        """★이 변경의 목적 자체 — 실제 sample_frame 이 2~6m 를 최다로 만드는가."""
        import random
        assets = vp.load_assets()
        rng = random.Random(4242)
        quota = vp.QuotaState.new(assets)
        distances = []
        for i in range(3000):
            spec, picks = vp.sample_frame(rng, quota, assets, frame_index=i, seed=4242)
            vp.advance_quota(quota, picks)
            distances.append(spec.fx * vp.PALLET_W
                             / (spec.proj_size_ratio * spec.resolution[0]))
        n = len(distances)
        in_band = sum(1 for d in distances if 2.0 <= d < 6.0) / n
        too_near = sum(1 for d in distances if d < 2.0) / n
        self.assertGreater(in_band, 0.55)     # 구 균등 실측 0.429
        self.assertLess(too_near, 0.20)       # 구 균등 실측 0.340
        # 꼬리도 살아 있어야 한다 — 분산을 잃으면 목적의 절반만 이룬 것이다
        self.assertGreater(sum(1 for d in distances if d >= 6.0) / n, 0.15)
        for d in distances:
            self.assertGreaterEqual(d, vp.MIN_CAMERA_DISTANCE_M - 1e-6)
            self.assertLessEqual(d, vp.MAX_CAMERA_DISTANCE_M + 1e-6)


def _load_runner():
    import importlib.util

    path = os.path.join(BLENDER_DIR, "run_v2_scene_logic.py")
    spec = importlib.util.spec_from_file_location("run_v2_scene_logic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _one_plan():
    assets = vp.load_assets()
    plans, _, _, _ = vp.generate_accepted(
        5, BULK_SEED, assets, placement_mode="constrained"
    )
    return plans[0]


if __name__ == "__main__":
    unittest.main()
