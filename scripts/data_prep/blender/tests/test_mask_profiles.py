"""Mask OUTPUT profile tests (bpy-free).

`--mask-profile public` must deliver exactly two permanent masks per image (amodal + visible)
and report the per-source occlusion fractions as `None` = NOT MEASURED, while `full-audit`
keeps the existing M0..M4 diagnostic behaviour byte for byte.

No Blender here: the holdout renderer is faked, but the STAGE LIST, the PATHS and the
DECOMPOSITION all come from the same mask_profiles functions the real runner uses, so the
"public renders two passes, not five" claim is checked on the production code path.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import mask_profiles as MP  # noqa: E402

RUNNER_PATH = os.path.join(BLENDER_DIR, "run_v2_scene_logic.py")
AUDIT_PATH = os.path.join(BLENDER_DIR, "audit_v2_scene_logic.py")
REALIZE_PATH = os.path.join(BLENDER_DIR, "v2_realize.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_mask(path, top, bottom, left, right, size=(48, 64)):
    """White rectangle on black, so nesting = pixel-level inclusion."""
    arr = np.zeros(size, dtype=np.uint8)
    arr[top:bottom, left:right] = 255
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(arr, mode="L").save(path)
    return int((arr > 127).sum())


EMPTY_GROUPS = {"all_nonpallet": [], "cargo": [], "context": [], "explicit": []}


def fake_render_frame(out_dir, idx, profile, rects=None):
    """Simulate ONE frame of measure_geometry_and_masks without bpy.

    Renders exactly the passes of `MP.holdout_passes(profile, ...)` to exactly the paths of
    `MP.frame_mask_paths`, then decomposes with `MP.decompose` - i.e. the same three calls
    v2_realize makes.  Returns (decomposition, invariant, rendered stage list).
    """
    rects = rects or {}
    paths = MP.frame_mask_paths(out_dir, idx, profile)
    areas = {}
    rendered = []
    for stage, _hide in MP.holdout_passes(profile, EMPTY_GROUPS):
        top, bottom, left, right = rects.get(stage, (16, 32, 21, 43))
        areas[stage] = _write_mask(paths[stage], top, bottom, left, right)
        rendered.append(stage)
    decomposition, invariant = MP.decompose(areas, profile)
    return decomposition, invariant, rendered


class PublicProfileOutputTests(unittest.TestCase):
    def test_public_keeps_exactly_two_masks_per_image_and_no_m1_m2_m3(self):
        with tempfile.TemporaryDirectory() as tmp:
            for idx in range(3):
                _, _, rendered = fake_render_frame(tmp, idx, MP.PUBLIC)
                self.assertEqual(["m0", "m4"], rendered)

            files = sorted(
                str(p.relative_to(tmp)).replace(os.sep, "/")
                for p in Path(tmp).rglob("*.png")
            )
            self.assertEqual(6, len(files))          # 3 images x 2 masks
            self.assertEqual(
                [
                    "mask_amodal/f0000.png", "mask_amodal/f0001.png",
                    "mask_amodal/f0002.png", "mask_visible/f0000.png",
                    "mask_visible/f0001.png", "mask_visible/f0002.png",
                ],
                files,
            )
            for stage in ("m1", "m2", "m3"):
                self.assertEqual(
                    [], [name for name in files if stage in name],
                    f"{stage} must not exist in a public set",
                )
            # no cryptic m0/m4 duplicates next to the readable names
            self.assertFalse(os.path.isdir(os.path.join(tmp, "mask")))

    def test_only_the_profile_mask_directories_are_created(self):
        """A public set must not be shipped with an empty `mask/` next to the real two."""
        self.assertEqual(("mask_amodal", "mask_visible"), MP.mask_dirnames(MP.PUBLIC))
        self.assertEqual(("mask",), MP.mask_dirnames(MP.FULL_AUDIT))
        source = Path(RUNNER_PATH).read_text(encoding="utf-8")
        self.assertIn("MP.mask_dirnames(args.mask_profile)", source)
        self.assertIn("for path in (out, rgb_dir, *profile_mask_dirs, label_dir, log_dir):",
                      source)
        self.assertNotIn("os.makedirs(mask_dir", source)

    def test_public_renders_two_passes_not_five(self):
        plan = MP.holdout_passes(MP.PUBLIC, EMPTY_GROUPS)
        self.assertEqual(2, len(plan))
        self.assertEqual(("m0", "m4"), tuple(stage for stage, _ in plan))
        self.assertEqual(5, len(MP.holdout_passes(MP.FULL_AUDIT, EMPTY_GROUPS)))

    def test_public_source_fractions_are_none_and_f_total_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            decomposition, invariant, _ = fake_render_frame(
                tmp, 0, MP.PUBLIC,
                rects={"m0": (16, 32, 20, 44), "m4": (16, 24, 20, 44)},
            )
        self.assertTrue(invariant["valid"], invariant["errors"])
        for key in MP.SOURCE_FRACTION_KEYS:
            self.assertIsNone(decomposition[key], key)
        self.assertEqual(16 * 24, decomposition["mask_area_amodal"])
        self.assertEqual(8 * 24, decomposition["mask_area_visible"])
        self.assertIsNotNone(decomposition["f_total"])
        self.assertAlmostEqual(0.5, decomposition["f_total"])
        self.assertEqual(["M0", "M4"], decomposition["occlusion_decomposition_order"])

    def test_public_reports_missing_stages_instead_of_silently_zeroing(self):
        with self.assertRaises(KeyError):
            MP.decompose({"m0": 100.0}, MP.PUBLIC)
        with self.assertRaises(KeyError):
            MP.decompose({"m0": 100.0, "m4": 50.0}, MP.FULL_AUDIT)

    def test_unoccluded_public_frame_reports_zero_not_none(self):
        """0.0 is a MEASUREMENT; None is 'not measured'.  They must not be confused."""
        decomposition, invariant = MP.decompose({"m0": 4000.0, "m4": 4000.0}, MP.PUBLIC)
        self.assertTrue(invariant["valid"], invariant["errors"])
        self.assertIsNotNone(decomposition["f_total"])
        self.assertEqual(0.0, decomposition["f_total"])
        self.assertIsNone(decomposition["f_static"])

    def test_empty_amodal_mask_is_unmeasurable_not_zero(self):
        decomposition, invariant = MP.decompose({"m0": 0.0, "m4": 0.0}, MP.PUBLIC)
        self.assertFalse(invariant["valid"])
        self.assertIsNone(decomposition["f_total"])

    def test_visible_larger_than_amodal_fails_the_invariant(self):
        _, invariant = MP.decompose({"m0": 100.0, "m4": 120.0}, MP.PUBLIC)
        self.assertFalse(invariant["valid"])
        self.assertIn(
            "monotonic", " ".join(invariant["errors"])
        )


class FullAuditBackwardCompatibilityTests(unittest.TestCase):
    def test_full_audit_keeps_five_masks_at_the_historical_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, rendered = fake_render_frame(
                tmp, 7, MP.FULL_AUDIT,
                rects={
                    "m0": (16, 32, 20, 44), "m1": (16, 31, 20, 44),
                    "m2": (16, 30, 20, 44), "m3": (16, 29, 20, 44),
                    "m4": (16, 28, 20, 44),
                },
            )
            self.assertEqual(["m0", "m1", "m2", "m3", "m4"], rendered)
            files = sorted(p.name for p in Path(tmp, "mask").glob("*.png"))
        self.assertEqual(
            ["f0007_m0.png", "f0007_m1.png", "f0007_m2.png", "f0007_m3.png",
             "f0007_m4.png"],
            files,
        )

    def test_full_audit_source_fractions_stay_exact(self):
        # areas chosen so every source removes a different, exactly representable share
        areas = {"m0": 1000.0, "m1": 900.0, "m2": 700.0, "m3": 650.0, "m4": 500.0}
        decomposition, invariant = MP.decompose(areas, MP.FULL_AUDIT)
        self.assertTrue(invariant["valid"], invariant["errors"])
        self.assertAlmostEqual(0.10, decomposition["f_static"])
        self.assertAlmostEqual(0.20, decomposition["f_cargo"])
        self.assertAlmostEqual(0.05, decomposition["f_context"])
        self.assertAlmostEqual(0.15, decomposition["f_explicit"])
        self.assertAlmostEqual(0.50, decomposition["f_total"])
        self.assertEqual(
            ["M0", "M1", "M2", "M3", "M4"],
            decomposition["occlusion_decomposition_order"],
        )
        self.assertTrue(MP.occlusion_decomposition_available(MP.FULL_AUDIT))
        self.assertFalse(MP.occlusion_decomposition_available(MP.PUBLIC))

    def test_full_audit_zero_occlusion_stays_zero(self):
        areas = {name: 4000.0 for name in ("m0", "m1", "m2", "m3", "m4")}
        decomposition, invariant = MP.decompose(areas, MP.FULL_AUDIT)
        self.assertTrue(invariant["valid"], invariant["errors"])
        for key in MP.SOURCE_FRACTION_KEYS:
            self.assertIsNotNone(decomposition[key], key)
            self.assertEqual(0.0, decomposition[key])
        self.assertEqual(0.0, decomposition["f_total"])

    def test_broken_full_audit_decomposition_keeps_observed_areas(self):
        # M2 > M1 breaks monotonicity: the invariant must fail, the areas must survive
        areas = {"m0": 1000.0, "m1": 700.0, "m2": 900.0, "m3": 650.0, "m4": 500.0}
        decomposition, invariant = MP.decompose(areas, MP.FULL_AUDIT)
        self.assertFalse(invariant["valid"])
        self.assertEqual(700.0, decomposition["mask_area_after_static"])
        self.assertEqual(900.0, decomposition["mask_area_after_cargo"])
        self.assertAlmostEqual(-0.20, decomposition["f_cargo"])

    def test_hidden_object_sets_match_the_pre_refactor_holdout_calls(self):
        """M0=all non-pallet, M1=cargo+context+explicit, M2=context+explicit, M3=explicit,
        M4=nothing - the exact extra_hide lists v2_realize passed before this change."""
        groups = {
            "all_nonpallet": ["bg", "floor", "box", "shelf", "crate"],
            "cargo": ["box"],
            "context": ["shelf"],
            "explicit": ["crate"],
        }
        hidden = dict(MP.holdout_passes(MP.FULL_AUDIT, groups))
        self.assertEqual(["bg", "floor", "box", "shelf", "crate"], hidden["m0"])
        self.assertEqual(["box", "shelf", "crate"], hidden["m1"])
        self.assertEqual(["shelf", "crate"], hidden["m2"])
        self.assertEqual(["crate"], hidden["m3"])
        self.assertEqual([], hidden["m4"])

        public = dict(MP.holdout_passes(MP.PUBLIC, groups))
        self.assertEqual(["m0", "m4"], list(public))
        self.assertEqual(hidden["m0"], public["m0"])
        self.assertEqual(hidden["m4"], public["m4"])

    def test_no_explicit_occluder_means_nothing_extra_is_hidden(self):
        groups = {"all_nonpallet": ["bg"], "cargo": [], "context": [], "explicit": []}
        hidden = dict(MP.holdout_passes(MP.FULL_AUDIT, groups))
        self.assertEqual([], hidden["m3"])
        self.assertEqual([], hidden["m1"])

    def test_realize_supplies_every_hide_group_the_plan_needs(self):
        source = Path(REALIZE_PATH).read_text(encoding="utf-8")
        needed = {
            name
            for groups in MP.STAGE_HIDDEN_GROUPS.values()
            for name in groups
        }
        for name in needed:
            self.assertIn(f'"{name}": ', source, f"hide group {name} missing in v2_realize")
        self.assertIn("MP.holdout_passes(profile, hide_groups)", source)

    def test_default_profile_is_full_audit(self):
        self.assertEqual(MP.FULL_AUDIT, MP.DEFAULT_MASK_PROFILE)
        self.assertEqual(MP.FULL_AUDIT, MP.normalize_profile(None))
        self.assertEqual(("m0", "m1", "m2", "m3", "m4"), MP.mask_stages(None))
        with self.assertRaises(ValueError):
            MP.normalize_profile("amodal-only")

    def test_legacy_prefix_paths_are_unchanged_for_full_audit(self):
        prefix = os.path.join("run", "mask", "f0042")
        paths = MP.mask_paths_from_prefix(prefix, MP.FULL_AUDIT)
        self.assertEqual(prefix + "_m0.png", paths["m0"])
        self.assertEqual(prefix + "_m4.png", paths["m4"])
        public = MP.mask_paths_from_prefix(prefix, MP.PUBLIC)
        self.assertEqual(
            os.path.join("run", "mask_amodal", "f0042.png"), public["m0"]
        )
        self.assertEqual(
            os.path.join("run", "mask_visible", "f0042.png"), public["m4"]
        )


class CompatibilityLookupTests(unittest.TestCase):
    def test_detect_profile_and_resolve_path_find_either_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = os.path.join(tmp, "legacy")
            public = os.path.join(tmp, "public")
            fake_render_frame(legacy, 0, MP.FULL_AUDIT)
            fake_render_frame(public, 0, MP.PUBLIC)

            self.assertEqual(MP.FULL_AUDIT, MP.detect_profile(legacy))
            self.assertEqual(MP.PUBLIC, MP.detect_profile(public))
            self.assertEqual(
                os.path.join(legacy, "mask", "f0000_m0.png"),
                MP.resolve_frame_mask_path(legacy, 0, MP.AMODAL_STAGE),
            )
            self.assertEqual(
                os.path.join(public, "mask_visible", "f0000.png"),
                MP.resolve_frame_mask_path(public, 0, MP.VISIBLE_STAGE),
            )

    def test_resolve_falls_back_to_the_detected_layout_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                os.path.join(tmp, "mask", "f0003_m0.png"),
                MP.resolve_frame_mask_path(tmp, 3, MP.AMODAL_STAGE),
            )


class RunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.runner = _load("run_v2_scene_logic", RUNNER_PATH)

    def test_mask_integrity_checks_visible_subset_of_amodal_for_public(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = MP.frame_mask_paths(tmp, 0, MP.PUBLIC)
            _write_mask(paths["m0"], 16, 32, 20, 44)
            _write_mask(paths["m4"], 18, 30, 22, 42)     # strictly inside M0

            fields = self.runner._mask_integrity_fields(paths, MP.PUBLIC)

        self.assertTrue(fields["mask_strict_decode_ok"])
        self.assertTrue(fields["mask_pixel_inclusion_ok"])
        self.assertEqual(0, fields["mask_pixel_inclusion_violation_px"])
        self.assertEqual(16 * 24, fields["mask_m0_area_px"])
        self.assertTrue(fields["mask_shape_consistent"])

    def test_mask_integrity_catches_visible_pixels_outside_amodal(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = MP.frame_mask_paths(tmp, 0, MP.PUBLIC)
            _write_mask(paths["m0"], 16, 32, 20, 44)
            _write_mask(paths["m4"], 33, 40, 20, 44)     # disjoint from M0

            fields = self.runner._mask_integrity_fields(paths, MP.PUBLIC)

        self.assertFalse(fields["mask_pixel_inclusion_ok"])
        self.assertEqual(7 * 24, fields["mask_pixel_inclusion_violation_px"])
        self.assertIn("m4!<=m0", fields["mask_pixel_inclusion_violations"])

    def test_public_frame_is_not_failed_for_the_masks_it_never_rendered(self):
        """The 5-stage integrity check must not report m1/m2/m3 as missing."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = MP.frame_mask_paths(tmp, 0, MP.PUBLIC)
            _write_mask(paths["m0"], 16, 32, 20, 44)
            _write_mask(paths["m4"], 18, 30, 22, 42)

            public_fields = self.runner._mask_integrity_fields(paths, MP.PUBLIC)
            as_full_audit = self.runner._mask_integrity_fields(paths, MP.FULL_AUDIT)

        self.assertEqual({}, public_fields["mask_decode_errors"])
        self.assertTrue(public_fields["mask_strict_decode_ok"])
        # the same two files judged with the full-audit stage list DO fail -> the profile is
        # what fixes it, not a loosened check
        self.assertFalse(as_full_audit["mask_strict_decode_ok"])

    def test_full_audit_integrity_still_uses_all_five_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = MP.frame_mask_paths(tmp, 0, MP.FULL_AUDIT)
            for i, stage in enumerate(("m0", "m1", "m2", "m3", "m4")):
                _write_mask(paths[stage], 16 + i, 32 - i, 21 + i, 43 - i)

            fields = self.runner._mask_integrity_fields(paths, None)

        self.assertTrue(fields["mask_strict_decode_ok"])
        self.assertTrue(fields["mask_pixel_inclusion_ok"])

    def test_runner_exposes_the_mask_profile_flag_with_full_audit_default(self):
        source = Path(RUNNER_PATH).read_text(encoding="utf-8")
        self.assertIn('"--mask-profile"', source)
        self.assertIn("choices=MP.MASK_PROFILES", source)
        self.assertIn("default=MP.DEFAULT_MASK_PROFILE", source)


class LabelConventionRegressionTests(unittest.TestCase):
    """This change is mask OUTPUT POLICY only: pose/keypoint label contracts must not move."""

    def test_keypoint_convention_and_pose_fields_are_untouched(self):
        source = Path(REALIZE_PATH).read_text(encoding="utf-8")
        for contract in (
            '"keypoint_convention": "camera_dynamic_0123_v4"',
            '"projected_cuboid": [[float(uv8_v4[k, 0]), float(uv8_v4[k, 1])] for k in range(8)]',
            '"projected_cuboid_centroid": [float(cent_uv[0]), float(cent_uv[1])]',
            '"perm_v4": meas["perm"]',
            '"pose_transform": pose.tolist()',
            '"quaternion_xyzw": rotation_matrix_to_quat_xyzw(R_obj_cam)',
        ):
            self.assertIn(contract, source)

    def test_orientation_overrides_are_still_imported_unmodified(self):
        source = Path(REALIZE_PATH).read_text(encoding="utf-8")
        self.assertIn(
            "from blender_config import ORIENTATION_OVERRIDES, SENSOR_WIDTH, "
            "PALLET_SOURCE_ASSETS",
            source,
        )
        self.assertNotIn("ORIENTATION_OVERRIDES[", source)

    def test_label_records_the_mask_profile_and_availability_flag(self):
        source = Path(REALIZE_PATH).read_text(encoding="utf-8")
        self.assertIn('"mask_profile": meas.get("mask_profile")', source)
        self.assertIn('"mask_area_amodal": meas.get("mask_area_amodal")', source)
        self.assertIn('"occlusion_decomposition_available"', source)


class AuditPublicDatasetTests(unittest.TestCase):
    """audit_v2_scene_logic must audit a 2-mask public set instead of failing it."""

    def setUp(self):
        self.audit = _load("audit_v2_scene_logic", AUDIT_PATH)

    def _fixture(self, root: Path, profile: str):
        names = list(MP.mask_stages(profile))
        self.audit.write_self_test_fixture(root, names, profile)
        record = json.loads((root / "records.jsonl").read_text(encoding="utf-8"))
        record["mask_profile"] = profile
        (root / "records.jsonl").write_text(
            json.dumps(record) + "\n", encoding="utf-8"
        )
        (root / "records.json").write_text(
            json.dumps({"records": [record]}, indent=2), encoding="utf-8"
        )

    def test_auto_detects_public_layout_and_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "public_set"
            self._fixture(root, MP.PUBLIC)
            proc = subprocess.run(
                [sys.executable, AUDIT_PATH, "--dir", str(root),
                 "--out", str(root / "eda"), "--max-sheet-frames", "2"],
                text=True, capture_output=True,
            )
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )
            frames = (root / "eda" / "audit_frames.csv").read_text(encoding="utf-8")

        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("PASS", summary["status"])
        self.assertEqual("public", summary["mask_profile"])
        self.assertEqual(["m0", "m4"], summary["mask_names"])
        self.assertEqual(2, summary["file_count_by_kind"]["mask_files"])
        self.assertNotIn("missing_mask", frames)
        self.assertNotIn("mask_m1_present", frames.splitlines()[0])

    def test_full_audit_dataset_is_unaffected_by_the_new_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "diag_set"
            self._fixture(root, MP.FULL_AUDIT)
            proc = subprocess.run(
                [sys.executable, AUDIT_PATH, "--dir", str(root),
                 "--out", str(root / "eda"), "--max-sheet-frames", "2"],
                text=True, capture_output=True,
            )
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )

        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("PASS", summary["status"])
        self.assertEqual("full-audit", summary["mask_profile"])
        self.assertEqual(["m0", "m1", "m2", "m3", "m4"], summary["mask_names"])
        self.assertEqual(5, summary["file_count_by_kind"]["mask_files"])

    def test_public_inclusion_violation_is_still_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "broken_public"
            self._fixture(root, MP.PUBLIC)
            # push M4 outside M0 -> visible pixels that were never in the amodal silhouette
            _write_mask(
                MP.frame_mask_paths(root, 0, MP.PUBLIC)["m4"], 34, 44, 20, 44
            )
            proc = subprocess.run(
                [sys.executable, AUDIT_PATH, "--dir", str(root),
                 "--out", str(root / "eda"), "--max-sheet-frames", "2"],
                text=True, capture_output=True,
            )
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, proc.returncode)
        self.assertEqual("FAIL", summary["status"])
        self.assertIn(
            "mask_pixel_inclusion", summary["fatal_failure_count_by_type"]
        )


if __name__ == "__main__":
    unittest.main()
