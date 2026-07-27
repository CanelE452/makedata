"""Phase 3: sensor post-effect tiers + the final-RGB measurement order.

The bug being guarded here: the G5 gate and the label used to report the luma of the RAW
render while the PNG on disk had already been degraded (vignette/noise/JPEG). The tiered
`camera_effects.apply()` must therefore (a) report exactly what it applied, (b) keep a
majority of frames untouched by sensor noise, and (c) be consumed AFTER the post-effects
run. (a)+(b) are unit-testable here; (c) is a source-order regression guard because the
call site needs bpy.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from collections import Counter

import numpy as np
from PIL import Image

BLENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import camera_effects as CE  # noqa: E402


EFFECT_KEYS = (
    "noise_tier",
    "wb_gain_rgb",
    "vignette_applied",
    "vignette_strength",
    "blur_applied",
    "blur_radius_px",
    "gaussian_noise_applied",
    "gaussian_sigma",
    "jpeg_applied",
    "jpeg_quality",
)


def _write_image(path, value=(120, 120, 120), size=(64, 48)):
    Image.new("RGB", size, value).save(path)
    return path


class TierSelectionTests(unittest.TestCase):
    def test_probabilities_sum_to_one(self):
        self.assertEqual(len(CE.NOISE_TIER_LABELS), len(CE.NOISE_TIER_FRAC))
        self.assertAlmostEqual(1.0, sum(CE.NOISE_TIER_FRAC), places=9)

    def test_empirical_mixture_matches_config(self):
        n = 1000
        counts = Counter(CE.choose_tier(seed) for seed in range(n))
        for label, frac in zip(CE.NOISE_TIER_LABELS, CE.NOISE_TIER_FRAC):
            observed = counts[label] / n
            # 4 sigma of a Binomial(n, frac) proportion, floored for the rare 'high' tier.
            tol = max(0.01, 4.0 * (frac * (1.0 - frac) / n) ** 0.5)
            self.assertAlmostEqual(frac, observed, delta=tol, msg=f"tier={label}")

    def test_tier_choice_is_deterministic(self):
        self.assertEqual(
            [CE.choose_tier(s) for s in range(50)],
            [CE.choose_tier(s) for s in range(50)],
        )

    def test_unknown_tier_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_image(os.path.join(tmp, "f.png"))
            with self.assertRaises(ValueError):
                CE.apply(path, 1, tier="ultra")


class TierApplicationTests(unittest.TestCase):
    def test_effect_dict_reports_every_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            for tier in CE.NOISE_TIER_LABELS:
                path = _write_image(os.path.join(tmp, f"{tier}.png"))
                effects = CE.apply(path, 11, tier=tier)
                self.assertEqual(set(EFFECT_KEYS), set(effects))
                self.assertEqual(tier, effects["noise_tier"])
                self.assertEqual(3, len(effects["wb_gain_rgb"]))

    def test_clean_tier_never_adds_noise_blur_or_jpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clean.png")
            for seed in range(200):
                _write_image(path)
                effects = CE.apply(path, seed, tier="clean", dark_factor=1.0)
                self.assertFalse(effects["gaussian_noise_applied"])
                self.assertFalse(effects["blur_applied"])
                self.assertFalse(effects["jpeg_applied"])
                self.assertIsNone(effects["gaussian_sigma"])
                self.assertIsNone(effects["blur_radius_px"])
                self.assertIsNone(effects["jpeg_quality"])

    def test_sigma_bands_do_not_overlap(self):
        bands = [
            CE.NOISE_TIER_PARAMS[tier]["sigma"]
            for tier in ("low", "medium", "high")
        ]
        for (_, hi), (lo_next, _) in zip(bands, bands[1:]):
            self.assertLessEqual(hi, lo_next)

    def test_applied_sigma_stays_inside_its_tier_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.png")
            for tier in ("low", "medium", "high"):
                lo, hi = CE.NOISE_TIER_PARAMS[tier]["sigma"]
                for seed in range(120):
                    for dark in (0.0, 0.5, 1.0):
                        _write_image(path)
                        effects = CE.apply(path, seed, tier=tier, dark_factor=dark)
                        sigma = effects["gaussian_sigma"]
                        self.assertIsNotNone(sigma)
                        self.assertGreaterEqual(sigma, lo)
                        self.assertLessEqual(sigma, hi)

    def test_dark_factor_raises_sigma_within_the_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.png")
            bright, dark = [], []
            for seed in range(200):
                _write_image(path)
                bright.append(CE.apply(path, seed, tier="low")["gaussian_sigma"])
                _write_image(path)
                dark.append(
                    CE.apply(path, seed, tier="low", dark_factor=1.0)["gaussian_sigma"]
                )
            self.assertTrue(all(d >= b for b, d in zip(bright, dark)))
            self.assertGreater(float(np.mean(dark)), float(np.mean(bright)))

    def test_blur_and_jpeg_ranges_are_reported_within_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.png")
            for tier in ("low", "medium", "high"):
                params = CE.NOISE_TIER_PARAMS[tier]
                for seed in range(80):
                    _write_image(path)
                    effects = CE.apply(path, seed, tier=tier)
                    if effects["blur_applied"]:
                        self.assertGreaterEqual(effects["blur_radius_px"], params["blur"][0])
                        self.assertLessEqual(effects["blur_radius_px"], params["blur"][1])
                    if effects["jpeg_applied"]:
                        self.assertGreaterEqual(effects["jpeg_quality"], params["jpeg"][0])
                        self.assertLessEqual(effects["jpeg_quality"], params["jpeg"][1])

    def test_same_seed_reproduces_pixels_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
            base = (np.random.default_rng(3).random((48, 64, 3)) * 255).astype(np.uint8)
            Image.fromarray(base).save(first)
            Image.fromarray(base).save(second)
            e1 = CE.apply(first, 42, tier="medium", dark_factor=0.3)
            e2 = CE.apply(second, 42, tier="medium", dark_factor=0.3)
            self.assertEqual(e1, e2)
            self.assertTrue(
                np.array_equal(
                    np.asarray(Image.open(first).convert("RGB")),
                    np.asarray(Image.open(second).convert("RGB")),
                )
            )

    def test_auto_tier_matches_choose_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.png")
            for seed in range(40):
                _write_image(path)
                self.assertEqual(
                    CE.choose_tier(seed),
                    CE.apply(path, seed, tier="auto")["noise_tier"],
                )

    def test_legacy_mode_is_still_available_and_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_image(os.path.join(tmp, "f.png"))
            effects = CE.apply(path, 5)          # 2-arg call: gen_trunc_addon / gen_4pallet_mask
            self.assertEqual("legacy", effects["noise_tier"])

    def test_noisy_tier_actually_changes_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.png")
            base = np.full((48, 64, 3), 120, dtype=np.uint8)
            Image.fromarray(base).save(path)
            CE.apply(path, 9, tier="high", dark_factor=1.0)
            after = np.asarray(Image.open(path).convert("RGB"))
            self.assertFalse(np.array_equal(base, after))


class MeasurementOrderRegressionTests(unittest.TestCase):
    """The runner must measure geometry, THEN degrade the PNG, THEN re-measure luma."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(BLENDER_DIR, "run_v2_scene_logic.py"), encoding="utf-8") as fh:
            cls.source = fh.read()

    def test_final_luma_is_measured_after_the_post_effects(self):
        geometry = self.source.index("vr.measure_geometry_and_masks(")
        post = self.source.index("vr.render_post(")
        final = self.source.index("vr.measure_final_rgb_quality(")
        gates = self.source.index("vr.safety_gates(")
        self.assertLess(geometry, post)
        self.assertLess(post, final)
        self.assertLess(final, gates)

    def test_zero_luma_is_not_treated_as_missing(self):
        # `meas.get("luma_frame") or 128.0` silently rewrote a pitch-black frame (luma 0.0)
        # into a mid-grey one.
        self.assertNotIn(" or 128.0", self.source)
        self.assertIn("raw_luma if raw_luma is not None else 128.0", self.source)


if __name__ == "__main__":
    unittest.main()
