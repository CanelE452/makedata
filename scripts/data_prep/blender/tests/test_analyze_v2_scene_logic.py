import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ANALYZER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "analyze_v2_scene_logic.py",
    )
)


def _load_analyzer():
    spec = importlib.util.spec_from_file_location(
        "analyze_v2_scene_logic",
        ANALYZER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_analyzer(
    root: Path,
    baseline: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            ANALYZER_PATH,
            "--dir",
            str(root),
            "--out",
            str(root / "eda"),
            "--baseline",
            str(baseline),
        ],
        text=True,
        capture_output=True,
    )


class RecordSourceErrorTests(unittest.TestCase):
    def test_malformed_records_jsonl_makes_cli_and_summary_fail(self):
        analyzer = _load_analyzer()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "fixture"
            baseline = Path(temp_dir) / "baseline" / "pilot_frames.csv"
            analyzer.write_self_test_fixture(root, baseline, analyzer.MASK_NAMES)
            with (root / "records.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("{malformed json\n")

            proc = _run_analyzer(root, baseline)

            self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
            summary = json.loads(
                (root / "eda" / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("FAIL", summary["status"])
            self.assertTrue(
                any(
                    error.startswith("records.jsonl:2:")
                    for error in summary["record_meta"]["errors"]
                )
            )


class SceneLogicAnalyzerNormalizationTests(unittest.TestCase):
    def test_summarize_numeric_adds_upper_quantiles_without_dropping_existing_keys(self):
        analyzer = _load_analyzer()

        summary = analyzer.summarize_numeric([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(4, summary["n"])
        self.assertEqual(2.5, summary["mean"])
        self.assertEqual(1.0, summary["min"])
        self.assertEqual(2.5, summary["p50"])
        self.assertAlmostEqual(3.7, summary["p90"])
        self.assertAlmostEqual(3.85, summary["p95"])
        self.assertEqual(4.0, summary["max"])

    def test_summary_separates_overall_clean_and_controlled_metrics(self):
        analyzer = _load_analyzer()
        rows = [
            {
                "idx": 0,
                "diagnostic_mode": "clean-static",
                "rendered": True,
                "realize_ok": True,
                "all_pass": True,
                "G1_pass": True,
                "G3_pass": True,
                "f_static": 0.10,
                "f_cargo": 0.0,
                "f_context": 0.0,
                "f_explicit": 0.0,
                "explicit_abs_error": 0.0,
                "placement_attempts": 1,
                "runtime_s": 1.0,
            },
            {
                "idx": 1,
                "diagnostic_mode": "clean-static",
                "rendered": True,
                "realize_ok": True,
                "all_pass": False,
                "G1_pass": False,
                "G3_pass": True,
                "f_static": 0.40,
                "f_cargo": 0.0,
                "f_context": 0.0,
                "f_explicit": 0.0,
                "explicit_abs_error": 0.0,
                "placement_attempts": 2,
                "runtime_s": 2.0,
            },
            {
                "idx": 2,
                "diagnostic_mode": "cargo-only",
                "rendered": True,
                "realize_ok": True,
                "all_pass": False,
                "G1_pass": True,
                "G3_pass": False,
                "f_static": 0.02,
                "f_cargo": 0.20,
                "f_context": 0.0,
                "f_explicit": 0.0,
                # This zero must not enter controlled-occlusion statistics.
                "explicit_abs_error": 0.0,
                "placement_attempts": 3,
                "runtime_s": 3.0,
            },
        ]
        sides = ("left", "right", "bottom", "center")
        for offset, (side, error, visible) in enumerate(
            zip(sides, (0.10, 0.20, 0.30, 0.40), (10, 10, 10, 0)),
            start=3,
        ):
            rows.append(
                {
                    "idx": offset,
                    "diagnostic_mode": "controlled-occlusion",
                    "rendered": True,
                    "realize_ok": True,
                    "all_pass": True,
                    "G1_pass": True,
                    "G3_pass": True,
                    "f_static": 0.01,
                    "f_cargo": 0.02,
                    "f_context": 0.03,
                    "f_explicit": 0.10 * (offset - 2),
                    "explicit_abs_error": error,
                    "explicit_occluder_visible_pixels": visible,
                    "occluder_side_actual": side,
                    "placement_attempts": offset + 1,
                    "runtime_s": float(offset + 1),
                }
            )
        rows.append(
            {
                "idx": 7,
                "diagnostic_mode": "controlled-occlusion",
                "rendered": False,
                "realize_ok": False,
                "all_pass": None,
                "G1_pass": None,
                "G3_pass": None,
                "explicit_occluder_visible_pixels": 0,
                "explicit_abs_error": 99.0,
                "placement_attempts": 8,
                "runtime_s": 8.0,
            }
        )

        summary = analyzer.summarize_new(rows, Path("fixture"), {})

        self.assertEqual(8, summary["overall"]["frame_count"])
        self.assertEqual(7, summary["overall"]["rendered_count"])
        self.assertEqual(1, summary["overall"]["realize_fail_count"])
        self.assertEqual(5, summary["overall"]["all_pass_count"])
        self.assertAlmostEqual(5 / 7, summary["overall"]["all_pass_rate"])
        self.assertEqual(1, summary["overall"]["G1_fail_count"])
        self.assertEqual(1, summary["overall"]["G3_fail_count"])

        clean = summary["clean_static"]
        self.assertEqual(1, clean["f_static_ge_0_35_count"])
        self.assertAlmostEqual(0.385, clean["f_static"]["p95"])
        self.assertAlmostEqual(0.385, clean["f_static_q95"])

        controlled = summary["controlled_occlusion"]
        self.assertEqual(5, controlled["frame_count"])
        self.assertEqual(4, controlled["rendered_count"])
        self.assertEqual(4, controlled["explicit_abs_error"]["n"])
        self.assertAlmostEqual(0.25, controlled["explicit_abs_error_q50"])
        self.assertAlmostEqual(0.37, controlled["explicit_abs_error_q90"])
        self.assertAlmostEqual(0.385, controlled["explicit_abs_error_q95"])
        self.assertEqual(3, controlled["explicit_visible_count"])
        self.assertAlmostEqual(3 / 5, controlled["explicit_visible_ratio"])
        self.assertAlmostEqual(3 / 4, controlled["explicit_visible_ratio_rendered"])
        self.assertEqual(4, controlled["actual_side_coverage_count"])
        self.assertTrue(controlled["all_four_actual_sides_present"])
        self.assertAlmostEqual(0.25, controlled["actual_center_share"])

        for source in ("f_static", "f_cargo", "f_context", "f_explicit", "f_total"):
            self.assertIn(source, summary["numeric"])
            self.assertIn("p90", summary["numeric"][source])
            self.assertIn("p95", summary["numeric"][source])
        self.assertEqual(8, summary["attempt_runtime"]["runtime_s"]["n"])
        self.assertEqual(8.0, summary["attempt_runtime"]["runtime_s"]["max"])

    def test_frame_columns_keep_source_mask_area_fields(self):
        analyzer = _load_analyzer()

        columns = analyzer.frame_columns(analyzer.MASK_NAMES)

        for name in (
            "mask_area_target_only",
            "mask_area_after_static",
            "mask_area_after_cargo",
            "mask_area_after_context",
            "mask_area_visible",
        ):
            self.assertIn(name, columns)
            self.assertEqual(1, columns.count(name))

    def test_unmeasured_projected_size_is_not_filled_from_target(self):
        analyzer = _load_analyzer()
        record = {
            "idx": 103,
            "seed": 7500,
            "diagnostic_mode": "cargo-only",
            "rendered": False,
            "realize_ok": False,
            "projected_size_target": 0.0510808,
            "projected_size_actual": None,
            "reject_reason": "anchor_fail",
        }
        with tempfile.TemporaryDirectory() as tmp:
            row = analyzer.build_frame_row(
                Path(tmp),
                103,
                record,
                analyzer.MASK_NAMES,
            )

        self.assertAlmostEqual(0.0510808, row["projected_size_target"])
        self.assertIsNone(row["projected_size_actual"])

    def test_explicit_actual_bin_is_separate_from_total_actual_bin(self):
        analyzer = _load_analyzer()
        record = {
            "idx": 1,
            "seed": 7500,
            "diagnostic_mode": "controlled-occlusion",
            "rendered": False,
            "realize_ok": False,
            "f_actual_bin": "legacy-total-bin",
            "f_explicit_actual": 0.15,
            "reject_reason": "fixture",
        }
        with tempfile.TemporaryDirectory() as tmp:
            row = analyzer.build_frame_row(
                Path(tmp),
                1,
                record,
                analyzer.MASK_NAMES,
            )

        self.assertEqual("legacy-total-bin", row["f_actual_bin"])
        self.assertEqual("1", row["f_explicit_actual_bin"])

    def test_frame_row_preserves_render_and_realize_status(self):
        analyzer = _load_analyzer()
        record = {
            "idx": 5,
            "rendered": False,
            "realize_ok": False,
            "reject_reason": "realize_fail",
        }
        with tempfile.TemporaryDirectory() as tmp:
            row = analyzer.build_frame_row(
                Path(tmp),
                5,
                record,
                analyzer.MASK_NAMES,
            )

        self.assertIs(False, row["rendered"])
        self.assertIs(False, row["realize_ok"])

    def test_realize_failure_is_counted_without_render_completeness_warning(self):
        analyzer = _load_analyzer()
        record = {
            "idx": 14,
            "seed": 7500,
            "diagnostic_mode": "controlled-occlusion",
            "rendered": False,
            "realize_ok": False,
            "reject_reason": "bounded_local_search_exhausted",
        }
        with tempfile.TemporaryDirectory() as tmp:
            row = analyzer.build_frame_row(
                Path(tmp),
                14,
                record,
                analyzer.MASK_NAMES,
            )

        summary = analyzer.summarize_new([row], Path("fixture"), {})

        self.assertEqual(0, row["missing_field_count"])
        self.assertEqual("", row["missing_fields"])
        self.assertEqual(1, summary["overall"]["frame_count"])
        self.assertEqual(0, summary["overall"]["rendered_count"])
        self.assertEqual(1, summary["overall"]["realize_fail_count"])
        self.assertEqual({}, summary["missing_field_count_by_name"])
        self.assertEqual(
            {},
            summary["required_scene_logic_missing_count_by_name"],
        )

    def test_successful_render_still_requires_render_measurement_fields(self):
        analyzer = _load_analyzer()
        record = {
            "idx": 15,
            "seed": 7500,
            "diagnostic_mode": "clean-static",
            "rendered": True,
            "realize_ok": True,
            "reject_reason": "accepted",
        }
        with tempfile.TemporaryDirectory() as tmp:
            row = analyzer.build_frame_row(
                Path(tmp),
                15,
                record,
                analyzer.MASK_NAMES,
            )

        summary = analyzer.summarize_new([row], Path("fixture"), {})

        self.assertGreater(row["missing_field_count"], 0)
        self.assertIn("f_static", row["missing_fields"].split(";"))
        self.assertEqual(
            1,
            summary["required_scene_logic_missing_count_by_name"]["f_static"],
        )

    def test_decoded_rgb_strict_magenta_overrides_historical_record_value(self):
        analyzer = _load_analyzer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rgb").mkdir()
            analyzer.Image.new("RGB", (2, 1), (200, 80, 170)).save(
                root / "rgb" / "f0016_rgb.png"
            )
            record = {
                "idx": 16,
                "rendered": True,
                "realize_ok": True,
                "magenta_fraction": 0.5,
                "magenta_ratio": 0.5,
            }

            row = analyzer.build_frame_row(
                root,
                16,
                record,
                analyzer.MASK_NAMES,
            )

        self.assertEqual(0.0, row["magenta_fraction"])
        self.assertEqual(0.0, row["magenta_ratio"])
        self.assertEqual(
            0,
            analyzer.magenta_corrupt_empty_counts([row])[
                "magenta_fraction_gt_0"
            ],
        )

    def test_decoded_rgb_strict_magenta_pixel_is_detected(self):
        analyzer = _load_analyzer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rgb").mkdir()
            image = analyzer.Image.new("RGB", (2, 1), (0, 0, 0))
            image.putpixel((0, 0), (181, 89, 181))
            image.save(root / "rgb" / "f0017_rgb.png")
            record = {
                "idx": 17,
                "rendered": True,
                "realize_ok": True,
                "magenta_fraction": 0.0,
                "magenta_ratio": 0.0,
            }

            row = analyzer.build_frame_row(
                root,
                17,
                record,
                analyzer.MASK_NAMES,
            )

        self.assertEqual(0.5, row["magenta_fraction"])
        self.assertEqual(0.5, row["magenta_ratio"])
        self.assertEqual(
            1,
            analyzer.magenta_corrupt_empty_counts([row])[
                "magenta_fraction_gt_0"
            ],
        )

    def test_failed_or_missing_rgb_uses_record_magenta_fallback(self):
        analyzer = _load_analyzer()
        for idx, corrupt_file in ((18, False), (19, True)):
            with self.subTest(corrupt_file=corrupt_file):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if corrupt_file:
                        (root / "rgb").mkdir()
                        (root / "rgb" / f"f{idx:04d}_rgb.png").write_bytes(
                            b"not a png"
                        )
                    record = {
                        "idx": idx,
                        "rendered": False,
                        "realize_ok": False,
                        "magenta_fraction": 0.125,
                        "reject_reason": "realize_fail",
                    }

                    row = analyzer.build_frame_row(
                        root,
                        idx,
                        record,
                        analyzer.MASK_NAMES,
                    )

                self.assertEqual(0.125, row["magenta_fraction"])
                self.assertEqual(0.125, row["magenta_ratio"])
                self.assertEqual(0, row["missing_field_count"])


if __name__ == "__main__":
    unittest.main()
