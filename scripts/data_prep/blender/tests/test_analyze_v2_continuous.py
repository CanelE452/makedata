"""Tests for the paper-oriented continuous EDA module and the falsy-0 regression fixes.

These are bpy-free.  They cover the five behaviours that are easy to break silently:
falsy-0 grouping, circular KDE seam continuity, zero-inflated splitting, bootstrap
determinism, and the code-level ban on KDE for discrete variables.
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONTINUOUS_PATH = os.path.join(BLENDER_DIR, "analyze_v2_continuous.py")
SCENE_LOGIC_PATH = os.path.join(BLENDER_DIR, "analyze_v2_scene_logic.py")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AC = _load("analyze_v2_continuous", CONTINUOUS_PATH)
ASL = _load("analyze_v2_scene_logic", SCENE_LOGIC_PATH)


# ---------------------------------------------------------------------------------
# falsy-0 regression: 0 / 0.0 / False must never land in the "(missing)" bucket
# ---------------------------------------------------------------------------------
class FalsyZeroGroupingTests(unittest.TestCase):
    def test_group_label_keeps_zero_and_false_out_of_missing(self):
        for module in (AC, ASL):
            with self.subTest(module=module.__name__):
                self.assertEqual(module.group_label(0), "0")
                self.assertEqual(module.group_label(0.0), "0.0")
                self.assertEqual(module.group_label(False), "False")
                self.assertEqual(module.group_label(None), "(missing)")
                self.assertEqual(module.group_label(""), "(missing)")
                self.assertEqual(module.group_label("   "), "(missing)")

    def test_old_truthiness_pattern_would_have_collapsed_them(self):
        # Documents exactly what the fix replaced.
        for value in (0, 0.0, False):
            self.assertEqual(str(value or "(missing)"), "(missing)")
            self.assertNotEqual(ASL.group_label(value), "(missing)")

    def test_all_pass_rate_by_separates_cargo_on_false_from_missing(self):
        rows = [
            {"cargo_on": False, "all_pass": True},
            {"cargo_on": False, "all_pass": False},
            {"cargo_on": True, "all_pass": True},
            {"cargo_on": None, "all_pass": False},
        ]
        rates = ASL.all_pass_rate_by(rows, "cargo_on")
        self.assertEqual(sorted(rates), ["(missing)", "False", "True"])
        self.assertAlmostEqual(rates["False"], 0.5)
        self.assertAlmostEqual(rates["True"], 1.0)
        self.assertAlmostEqual(rates["(missing)"], 0.0)

    def test_bin_zero_is_not_replaced_by_the_numeric_fallback(self):
        # Fig.16/17: elev_bin_target == 0 is a real bin, not a missing value.
        zero_bin = ASL.bin_or_numeric_fallback(0, 3.5, [10, 20, 30, 40, 50], "elev")
        self.assertEqual(zero_bin, "0")
        missing_bin = ASL.bin_or_numeric_fallback(None, 3.5, [10, 20, 30, 40, 50], "elev")
        self.assertEqual(missing_bin, "elev [-inf,10)")
        empty_bin = ASL.bin_or_numeric_fallback("", 3.5, [10, 20, 30, 40, 50], "elev")
        self.assertEqual(empty_bin, "elev [-inf,10)")

    def test_bin_zero_group_counts_match_expected_split(self):
        rows = [{"elev_bin_target": 0, "elev_target": 1.0, "all_pass": True} for _ in range(3)]
        rows += [{"elev_bin_target": 2, "elev_target": 12.0, "all_pass": False} for _ in range(2)]
        rows += [{"elev_bin_target": None, "elev_target": 12.0, "all_pass": True}]
        rates = ASL.all_pass_rate_by_derived(
            rows,
            lambda r: ASL.bin_or_numeric_fallback(
                r.get("elev_bin_target"), r.get("elev_target"), [10, 20, 30, 40, 50], "elev"),
        )
        self.assertIn("0", rates)
        self.assertIn("2", rates)
        self.assertAlmostEqual(rates["0"], 1.0)
        self.assertAlmostEqual(rates["2"], 0.0)

    def test_cross_tab_and_counters_keep_zero(self):
        rows = [{"a": 0, "b": False}, {"a": None, "b": None}]
        table = {}
        for r in rows:
            table.setdefault(ASL.group_label(r.get("a")), {})
            key = ASL.group_label(r.get("b"))
            table[ASL.group_label(r.get("a"))][key] = table[ASL.group_label(r.get("a"))].get(key, 0) + 1
        self.assertEqual(set(table), {"0", "(missing)"})
        self.assertEqual(set(table["0"]), {"False"})

    def test_summarize_baseline_counts_v_and_azimuth_zero(self):
        rows = [
            {"stage": "rendered", "V_actual": 0, "V_vis": 0, "azimuth_bin": 0, "v_target": 4,
             "scene_preset": "indoor", "resolution": "640x480", "all_pass": True,
             "reject_reason": None},
            {"stage": "rendered", "V_actual": 8, "V_vis": 8, "azimuth_bin": 3, "v_target": 4,
             "scene_preset": "indoor", "resolution": "640x480", "all_pass": True,
             "reject_reason": None},
        ]
        s = ASL.summarize_baseline(rows, {})
        self.assertEqual(s["V_actual_count"].get("0"), 1)
        self.assertEqual(s["V_vis_count"].get("0"), 1)
        self.assertEqual(s["azimuth_bin_count"].get("0"), 1)
        self.assertNotIn("(missing)", s["V_actual_count"])
        self.assertNotIn("(missing)", s["azimuth_bin_count"])


# ---------------------------------------------------------------------------------
# Circular KDE
# ---------------------------------------------------------------------------------
class CircularKdeTests(unittest.TestCase):
    def test_density_is_exactly_periodic_across_the_seam(self):
        rng = np.random.default_rng(3)
        theta = np.mod(rng.uniform(0, 2 * math.pi, 300), 2 * math.pi)
        grid = np.linspace(0.0, 2 * math.pi, 721)
        dens = AC.von_mises_kde(theta, grid, kappa=4.0)
        self.assertLess(abs(float(dens[0]) - float(dens[-1])), 1e-12)

    def test_no_jump_at_the_seam_for_data_concentrated_at_zero(self):
        # Data straddling 0 deg is the case a linear KDE gets wrong.
        theta = np.deg2rad(np.concatenate([
            np.linspace(350.0, 359.9, 60), np.linspace(0.1, 10.0, 60)]))
        grid = np.linspace(0.0, 2 * math.pi, 721)
        dens = AC.von_mises_kde(theta, grid, kappa=30.0)
        # grid[-1] and grid[0] are the same angle, so one step across the seam is
        # dens[0] - dens[-2].  The reference must be local: most of the circle is flat
        # here, so a global median step would be ~0 and make any seam look enormous.
        step_across_seam = abs(float(dens[0]) - float(dens[-2]))
        local = np.abs(np.diff(np.concatenate([dens[-21:-1], dens[0:21]])))
        local_median = float(np.median(local))
        self.assertGreater(local_median, 0.0)
        # A seam discontinuity would show up as a step far larger than its neighbours.
        self.assertLess(step_across_seam, 3.0 * local_median)
        # And the peak must sit at 0 deg, not be split into two edge peaks.
        self.assertGreater(float(dens[0]), float(np.quantile(dens, 0.9)))

    def test_uniform_data_gives_density_close_to_the_uniform_reference(self):
        theta = np.linspace(0.0, 2 * math.pi, 721)[:-1]
        grid = np.linspace(0.0, 2 * math.pi, 361)
        dens = AC.von_mises_kde(theta, grid, kappa=1.0)
        uniform = 1.0 / (2 * math.pi)
        self.assertLess(float(np.max(np.abs(dens - uniform))), 1e-3)

    def test_kappa_selection_prefers_concentration_for_peaked_data(self):
        rng = np.random.default_rng(11)
        peaked = np.mod(rng.normal(0.0, 0.15, 200), 2 * math.pi)
        spread = rng.uniform(0.0, 2 * math.pi, 200)
        grid = np.geomspace(0.2, 200.0, 20)
        k_peaked, _ = AC.select_kappa_loo(peaked, grid)
        k_spread, _ = AC.select_kappa_loo(spread, grid)
        self.assertGreater(k_peaked, k_spread)


# ---------------------------------------------------------------------------------
# Zero-inflated handling
# ---------------------------------------------------------------------------------
class ZeroInflatedTests(unittest.TestCase):
    def test_zero_mass_and_conditional_part_are_separated(self):
        values = [0.0] * 7 + [0.1, 0.2, 0.3] + [None, ""]
        info = AC.zero_inflated_summary(values, name="f_cargo", domain=(0.0, 1.0))
        self.assertEqual(info["n_total"], 12)
        self.assertEqual(info["n_valid"], 10)
        self.assertEqual(info["n_missing"], 2)
        self.assertEqual(info["n_zero"], 7)
        self.assertEqual(info["n_positive"], 3)
        self.assertAlmostEqual(info["p_zero"], 0.7)
        self.assertFalse(info["kde_applied_to_zero_spike"])
        # The conditional summary must describe only X > 0.
        np.testing.assert_allclose(np.sort(info["positive_values"]), [0.1, 0.2, 0.3])
        self.assertAlmostEqual(info["positive_quantiles"]["q50"], 0.2)

    def test_zeros_are_not_treated_as_missing(self):
        info = AC.zero_inflated_summary([0.0, 0.0, 0.0], name="f_static", domain=(0.0, 1.0))
        self.assertEqual(info["n_missing"], 0)
        self.assertEqual(info["n_valid"], 3)
        self.assertAlmostEqual(info["p_zero"], 1.0)

    def test_all_zero_variable_has_no_positive_kde(self):
        info = AC.zero_inflated_summary([0.0] * 20, name="f_context", domain=(0.0, 1.0))
        self.assertEqual(info["n_positive"], 0)
        self.assertNotIn("positive_kde_bandwidth", info)


# ---------------------------------------------------------------------------------
# Discrete variables must never reach a KDE
# ---------------------------------------------------------------------------------
class DiscreteGuardTests(unittest.TestCase):
    def test_kde_rejects_discrete_variables(self):
        grid = np.linspace(0.0, 10.0, 32)
        x = np.asarray([4.0, 5.0, 6.0, 7.0, 8.0])
        for field in ("V_vis", "V_actual", "cargo_on", "scene_preset", "noise_tier",
                      "G1_pass", "all_pass", "v_target"):
            with self.subTest(field=field):
                with self.assertRaises(AC.DiscreteVariableError):
                    AC.gaussian_kde_1d(x, grid, 1.0, (0.0, 10.0), name=field)

    def test_kde_accepts_a_continuous_variable(self):
        grid = np.linspace(0.0, 10.0, 32)
        x = np.asarray([1.0, 2.0, 3.0, 4.5, 6.0])
        dens = AC.gaussian_kde_1d(x, grid, 0.8, (0.0, 10.0), name="camera_distance_actual_m")
        self.assertEqual(dens.shape, grid.shape)
        self.assertTrue(np.all(dens >= 0.0))

    def test_every_discrete_appendix_field_is_registered_as_discrete(self):
        for field in AC.CATEGORICAL_APPENDIX_FIELDS:
            self.assertIn(field, AC.DISCRETE_FIELDS, msg=f"{field} must be blocked from KDE")

    def test_no_continuous_figure_variable_is_in_the_discrete_set(self):
        continuous = {
            "camera_distance_target_m", "camera_distance_actual_m", "projected_size_target",
            "projected_size_actual", "elevation_deg_target", "elevation_deg_actual",
            "azimuth_deg_target", "fx", "exposure_ev", "luma_frame_final",
            "luma_pallet_final", "f_static", "f_cargo", "f_context", "f_explicit",
            "f_total", "runtime_s",
        }
        self.assertEqual(continuous & AC.DISCRETE_FIELDS, set())

    def test_bounded_kde_puts_no_mass_outside_the_domain(self):
        x = np.asarray([0.01, 0.02, 0.03, 0.5, 0.99])
        grid = np.linspace(-0.5, 1.5, 201)
        dens = AC.gaussian_kde_1d(x, grid, 0.05, (0.0, 1.0), name="f_total")
        outside = (grid < 0.0) | (grid > 1.0)
        self.assertTrue(np.all(dens[outside] == 0.0))
        self.assertGreater(float(np.max(dens[~outside])), 0.0)


# ---------------------------------------------------------------------------------
# Pass-probability curve
# ---------------------------------------------------------------------------------
class PassProbabilityTests(unittest.TestCase):
    @staticmethod
    def _sample(n=400, seed=5):
        rng = np.random.default_rng(seed)
        x = rng.uniform(0.0, 1.0, n)
        p = 1.0 / (1.0 + np.exp(-(x - 0.5) * 10.0))
        y = rng.uniform(0.0, 1.0, n) < p
        return list(x), [bool(v) for v in y]

    def test_bootstrap_ci_is_reproducible_with_a_fixed_seed(self):
        x, y = self._sample()
        a = AC.kernel_probability_curve(x, y, n_bootstrap=64, seed=1000)
        b = AC.kernel_probability_curve(x, y, n_bootstrap=64, seed=1000)
        np.testing.assert_array_equal(a["ci_lo"], b["ci_lo"])
        np.testing.assert_array_equal(a["ci_hi"], b["ci_hi"])
        self.assertEqual(a["bootstrap_seed"], 1000)

    def test_a_different_seed_changes_the_band(self):
        x, y = self._sample()
        a = AC.kernel_probability_curve(x, y, n_bootstrap=64, seed=1000)
        c = AC.kernel_probability_curve(x, y, n_bootstrap=64, seed=2000)
        self.assertFalse(np.array_equal(a["ci_lo"], c["ci_lo"]))

    def test_bandwidth_is_chosen_by_minimum_loo_brier(self):
        x, y = self._sample()
        res = AC.kernel_probability_curve(x, y, n_bootstrap=16, seed=1000)
        scores = res["loo_brier_grid"]
        best = min(scores, key=lambda s: s["loo_brier"])
        self.assertAlmostEqual(res["bandwidth_normalized"], best["bandwidth_normalized"])
        self.assertAlmostEqual(res["loo_brier"], best["loo_brier"])
        self.assertLessEqual(res["loo_brier"], 0.25)

    def test_curve_recovers_a_monotone_relationship(self):
        x, y = self._sample(n=600, seed=9)
        res = AC.kernel_probability_curve(x, y, n_bootstrap=16, seed=1000)
        p = res["p_hat"][res["reliable_mask"]]
        self.assertGreater(p.size, 20)
        self.assertLess(float(np.mean(p[:5])), float(np.mean(p[-5:])))

    def test_ci_brackets_the_point_estimate_where_reliable(self):
        x, y = self._sample()
        res = AC.kernel_probability_curve(x, y, n_bootstrap=200, seed=1000)
        m = res["reliable_mask"]
        self.assertTrue(np.all(res["ci_lo"][m] <= res["p_hat"][m] + 1e-9))
        self.assertTrue(np.all(res["p_hat"][m] <= res["ci_hi"][m] + 1e-9))

    def test_false_outcomes_are_negatives_not_missing(self):
        res = AC.kernel_probability_curve(
            list(np.linspace(0, 1, 40)), [False] * 20 + [True] * 20,
            n_bootstrap=8, seed=1000)
        self.assertEqual(res["n_valid"], 40)
        self.assertEqual(res["n_missing"], 0)
        self.assertEqual(res["n_positive"], 20)

    def test_out_of_domain_x_is_excluded_and_counted(self):
        x = list(np.linspace(0.0, 1.0, 40)) + [39.0]
        y = [True] * 41
        res = AC.kernel_probability_curve(x, y, n_bootstrap=8, seed=1000, x_domain=(0.0, 1.0))
        self.assertEqual(res["n_out_of_domain"], 1)
        self.assertEqual(res["n_valid"], 40)
        self.assertEqual(res["n_missing"], 0)
        self.assertAlmostEqual(res["x_out_of_domain_max"], 39.0)


# ---------------------------------------------------------------------------------
# Loader / schema plumbing
# ---------------------------------------------------------------------------------
class LoaderTests(unittest.TestCase):
    def test_pick_keeps_zero_and_false(self):
        self.assertEqual(AC.pick(None, 0), 0)
        self.assertEqual(AC.pick(None, False), False)
        self.assertEqual(AC.pick("", 0.0), 0.0)
        self.assertIsNone(AC.pick(None, "", "   "))

    def test_float_value_and_bool_value_reject_missing_only(self):
        self.assertEqual(AC.float_value(0), 0.0)
        self.assertEqual(AC.float_value("0"), 0.0)
        self.assertIsNone(AC.float_value(None))
        self.assertIsNone(AC.float_value(float("nan")))
        self.assertIs(AC.bool_value(False), False)
        self.assertIs(AC.bool_value("False"), False)
        self.assertIs(AC.bool_value(0), False)
        self.assertIsNone(AC.bool_value(None))

    def test_field_in_schema_detects_absent_phase1_fields(self):
        schema = {"rec.f_total", "v2.elevation_deg_target"}
        self.assertTrue(AC.field_in_schema("f_total", schema))
        self.assertTrue(AC.field_in_schema("elevation_deg_target", schema))
        self.assertFalse(AC.field_in_schema("camera_distance_actual_m", schema))

    def test_audit_manifest_from_another_dataset_is_not_joined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds_a"
            other = Path(tmp) / "ds_b"
            root.mkdir()
            other.mkdir()
            (root / "records.jsonl").write_text(
                json.dumps({"idx": 0, "rendered": True, "f_total": 0.0}) + "\n", encoding="utf-8")
            manifest = Path(tmp) / "m.csv"
            manifest.write_text("idx,frame_id,physical_valid\n0,f0000,True\n", encoding="utf-8")
            (Path(tmp) / "m.json").write_text(
                json.dumps({"dataset": str(other)}), encoding="utf-8")
            rows, meta = AC.load_dataset(root, manifest, None)
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(meta["pnp_manifest_join_note"])
            self.assertEqual(meta["n_pnp_manifest_joined"], 0)

    def test_matching_manifest_is_joined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            root.mkdir()
            (root / "records.jsonl").write_text(
                json.dumps({"idx": 0, "rendered": True}) + "\n", encoding="utf-8")
            manifest = Path(tmp) / "m.csv"
            manifest.write_text("idx,frame_id,physical_valid\n0,f0000,True\n", encoding="utf-8")
            (Path(tmp) / "m.json").write_text(
                json.dumps({"dataset": str(root)}), encoding="utf-8")
            rows, meta = AC.load_dataset(root, manifest, None)
            self.assertIsNone(meta["pnp_manifest_join_note"])
            self.assertEqual(meta["n_pnp_manifest_joined"], 1)
            self.assertIs(rows[0]["physical_valid"], True)


# ---------------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------------
class EndToEndTests(unittest.TestCase):
    def test_self_test_produces_all_required_figures(self):
        self.assertEqual(AC.run_self_test(n_bootstrap=32, seed=1000), 0)

    def test_analyze_writes_every_required_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            AC._write_self_test_fixture(root)
            out = root / "eda" / "paper_continuous"
            summary = AC.analyze(root, out, None, None, n_bootstrap=32, seed=1000)
            self.assertEqual(summary["required_figures_missing"], [])
            for stem in AC.REQUIRED_FIGURES:
                self.assertTrue((out / "figures_png" / f"{stem}.png").exists(), stem)
                self.assertTrue((out / "figures_pdf" / f"{stem}.pdf").exists(), stem)
            for name in ("continuous_metrics.csv", "continuous_summary.json",
                         "discrete_counts.csv", "paper_continuous_summary.md"):
                self.assertTrue((out / name).exists(), name)
            blob = json.loads((out / "continuous_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(blob["bootstrap"]["seed"], 1000)
            self.assertLess(abs(blob["azimuth_circular"]["seam_abs_difference"]), 1e-9)

    def test_every_figure_caption_states_a_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            AC._write_self_test_fixture(root)
            summary = AC.analyze(root, root / "out", None, None, n_bootstrap=16, seed=1000)
            for rec in summary["figures"]:
                caption = rec["caption"]
                self.assertTrue(
                    "denominator" in caption or caption.startswith("N/A"),
                    msg=f"{rec['stem']} caption lacks a denominator: {caption[:80]}")

    def test_missing_phase1_fields_are_reported_as_na_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "legacy"
            (root / "labels").mkdir(parents=True)
            for i in range(12):
                rec = {"idx": i, "rendered": True, "f_total": 0.0, "all_pass": True,
                       "elev_target": 10.0 + i, "elev_actual": 10.0 + i}
                (root / "records.jsonl").open("a", encoding="utf-8").write(json.dumps(rec) + "\n")
            summary = AC.analyze(root, root / "out", None, None, n_bootstrap=8, seed=1000)
            na_vars = {e["variable"] for e in summary.get("na_variables", [])}
            self.assertIn("camera_distance_target_m", na_vars)
            self.assertIn("camera_distance_actual_m", na_vars)
            fig = next(f for f in summary["figures"] if f["stem"] == "01_camera_distance_ecdf")
            self.assertEqual(fig["status"], "na")
            self.assertIn("not present in this dataset", fig["caption"])


if __name__ == "__main__":
    unittest.main()
