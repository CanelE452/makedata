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


AUDIT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "audit_v2_scene_logic.py",
    )
)


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_v2_scene_logic", AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_clean_fixture(audit, root: Path, *, all_pass: bool = True) -> None:
    audit.write_self_test_fixture(root, ["m0", "m1", "m2", "m3", "m4"])
    record = {
        "idx": 0,
        "scene_preset": "self_test_scene",
        "all_pass": all_pass,
        "anchor_reject_reason": None,
        "rendered": True,
        "realize_ok": True,
        "exact_collision_count": 0,
        "camera_clearance_pass": True,
        "support_pass": True,
    }
    (root / "records.json").write_text(
        json.dumps({"records": [record]}, indent=2),
        encoding="utf-8",
    )
    (root / "records.jsonl").write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )
    label_path = root / "labels" / "f0000_label.json"
    label = json.loads(label_path.read_text(encoding="utf-8"))
    label["objects"][0]["safety_gates"]["all_pass"] = all_pass
    label_path.write_text(json.dumps(label, indent=2), encoding="utf-8")


def _run_audit(root: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            AUDIT_PATH,
            "--dir",
            str(root),
            "--out",
            str(root / "eda"),
            "--max-sheet-frames",
            "2",
            *extra_args,
        ],
        text=True,
        capture_output=True,
    )


class RecordSourceErrorTests(unittest.TestCase):
    def test_malformed_records_jsonl_makes_cli_and_summary_fail(self):
        audit = _load_audit()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_clean_fixture(audit, root)
            with (root / "records.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("{malformed json\n")

            proc = _run_audit(root)

            self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("FAIL", summary["status"])
            self.assertTrue(
                any(
                    error.startswith("records.jsonl:2:")
                    for error in summary["record_meta"]["errors"]
                )
            )


class FailureRecordTests(unittest.TestCase):
    def test_realize_failure_record_counts_without_requiring_render_artifacts(self):
        audit = _load_audit()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_clean_fixture(audit, root)
            rendered_record = json.loads(
                (root / "records.jsonl").read_text(encoding="utf-8")
            )
            failure_record = {
                "idx": 1,
                "scene_preset": "self_test_scene",
                "rendered": False,
                "realize_ok": False,
                "reject_reason": "realize_fail",
            }
            (root / "records.jsonl").write_text(
                "\n".join(
                    (json.dumps(rendered_record), json.dumps(failure_record), "")
                ),
                encoding="utf-8",
            )

            proc = _run_audit(
                root,
                "--expected-frame-count",
                "2",
                "--expected-start-index",
                "0",
            )

            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("PASS", summary["status"])
            self.assertEqual(2, summary["frame_count"])
            self.assertEqual(2, summary["file_count_by_kind"]["records"])
            self.assertEqual([], summary["missing_expected_indices"])
            self.assertEqual([], summary["fatal_failure_indices"])
            self.assertEqual({}, summary["fatal_failure_count_by_type"])
            self.assertEqual([], summary["missing_rgb_indices"])
            self.assertEqual([], summary["missing_label_indices"])
            self.assertEqual([], summary["file_count_mismatch_indices"])


class MissingTextureLogTests(unittest.TestCase):
    def test_cycles_missing_image_is_a_dataset_level_error(self):
        audit = _load_audit()
        with tempfile.TemporaryDirectory() as temp_dir:
            logs = Path(temp_dir) / "logs"
            logs.mkdir()
            (logs / "blender_chunk.log").write_text(
                "cycles | ERROR Image file C:\\stale\\factory.hdr does not exist.\n",
                encoding="utf-8",
            )

            findings = audit.scan_missing_texture_logs(Path(temp_dir))

        self.assertEqual(1, findings["count"])
        self.assertIn("factory.hdr", findings["matches"][0]["line"])


class GateContactSheetTests(unittest.TestCase):
    def test_all_pass_and_all_fail_sheets_use_g1_to_g5_gate(self):
        audit = _load_audit()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_clean_fixture(audit, root, all_pass=False)

            proc = _run_audit(root)

            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )
            manifest = summary["contact_sheets"]
            self.assertEqual(1, summary["audit_pass_count"])
            self.assertEqual(0, manifest["all_pass"]["frames"])
            self.assertEqual(1, manifest["all_fail"]["frames"])


class FatalAuditTests(unittest.TestCase):
    def test_fatal_frame_integrity_conditions_exit_nonzero(self):
        audit = _load_audit()

        def missing_rgb(root: Path) -> None:
            (root / "rgb" / "f0000_rgb.png").unlink()

        def corrupt_rgb(root: Path) -> None:
            (root / "rgb" / "f0000_rgb.png").write_bytes(b"not a png")

        def missing_mask(root: Path) -> None:
            (root / "mask" / "f0000_m4.png").unlink()

        def corrupt_mask(root: Path) -> None:
            (root / "mask" / "f0000_m4.png").write_bytes(b"not a png")

        def nonmonotonic_mask(root: Path) -> None:
            arr = np.full((48, 64), 255, dtype=np.uint8)
            Image.fromarray(arr, mode="L").save(root / "mask" / "f0000_m4.png")

        def missing_required_label(root: Path) -> None:
            path = root / "labels" / "f0000_label.json"
            label = json.loads(path.read_text(encoding="utf-8"))
            del label["objects"][0]["projected_cuboid"]
            path.write_text(json.dumps(label), encoding="utf-8")

        def accepted_collision(root: Path) -> None:
            record = json.loads(
                (root / "records.jsonl").read_text(encoding="utf-8")
            )
            record["exact_collision_count"] = 1
            (root / "records.jsonl").write_text(
                json.dumps(record) + "\n",
                encoding="utf-8",
            )

        def missing_camera_clearance(root: Path) -> None:
            record = json.loads(
                (root / "records.jsonl").read_text(encoding="utf-8")
            )
            record["camera_clearance_pass"] = None
            (root / "records.jsonl").write_text(
                json.dumps(record) + "\n",
                encoding="utf-8",
            )

        def missing_required_support(root: Path) -> None:
            record = json.loads(
                (root / "records.jsonl").read_text(encoding="utf-8")
            )
            record["support_pass"] = None
            (root / "records.jsonl").write_text(
                json.dumps(record) + "\n",
                encoding="utf-8",
            )

        cases = {
            "missing_rgb": missing_rgb,
            "corrupt_rgb": corrupt_rgb,
            "missing_mask": missing_mask,
            "corrupt_mask": corrupt_mask,
            "mask_nonmonotonic": nonmonotonic_mask,
            "required_label_missing": missing_required_label,
            "accepted_exact_collision": accepted_collision,
            "camera_clearance_unknown": missing_camera_clearance,
            "support_unknown": missing_required_support,
        }
        for expected_failure, mutate in cases.items():
            with self.subTest(expected_failure=expected_failure):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    _write_clean_fixture(audit, root)
                    mutate(root)

                    proc = _run_audit(root)

                    self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
                    summary = json.loads(
                        (root / "eda" / "audit_summary.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual("FAIL", summary["status"])
                    self.assertIn(
                        expected_failure,
                        summary["fatal_failure_count_by_type"],
                    )

    def test_default_threshold_rejects_any_magenta_pixel(self):
        audit = _load_audit()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_clean_fixture(audit, root)
            rgb_path = root / "rgb" / "f0000_rgb.png"
            with Image.open(rgb_path) as image:
                arr = np.asarray(image.convert("RGB")).copy()
            arr[0, 0] = [255, 0, 255]
            Image.fromarray(arr, mode="RGB").save(rgb_path)

            proc = _run_audit(root)

            self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual([0], summary["magenta_fail_indices"])
            self.assertEqual(1, summary["fatal_failure_count_by_type"]["magenta"])


class ExpectedFrameRangeTests(unittest.TestCase):
    def test_expected_frame_range_mismatch_exits_nonzero(self):
        audit = _load_audit()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_clean_fixture(audit, root)

            proc = _run_audit(
                root,
                "--expected-frame-count",
                "20",
                "--expected-start-index",
                "0",
            )

            self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
            summary = json.loads(
                (root / "eda" / "audit_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(list(range(1, 20)), summary["missing_expected_indices"])
            self.assertEqual([], summary["unexpected_indices"])


if __name__ == "__main__":
    unittest.main()
