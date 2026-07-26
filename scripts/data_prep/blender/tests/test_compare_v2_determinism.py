import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


COMPARATOR_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "compare_v2_determinism.py",
    )
)


def _load_comparator():
    spec = importlib.util.spec_from_file_location(
        "compare_v2_determinism",
        COMPARATOR_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture(
    root,
    *,
    rgb_pixel=(11, 22, 33),
    f_static=0.125,
    runtime_s=1.0,
    session_elapsed_s=2.0,
):
    root = Path(root)
    for name in ("rgb", "mask", "labels"):
        (root / name).mkdir(parents=True, exist_ok=True)

    idx = 3
    frame = f"f{idx:04d}"
    rgb = np.full((3, 4, 3), rgb_pixel, dtype=np.uint8)
    Image.fromarray(rgb, mode="RGB").save(root / "rgb" / f"{frame}_rgb.png")
    for mask_index, mask_name in enumerate(("m0", "m1", "m2", "m3", "m4")):
        mask = np.full((3, 4), 255 - mask_index * 31, dtype=np.uint8)
        Image.fromarray(mask, mode="L").save(
            root / "mask" / f"{frame}_{mask_name}.png"
        )

    label = {
        "camera_data": {"resolution": [4, 3]},
        "objects": [
            {
                "class": "pallet",
                "scene_placement_v2": {
                    "stage_runtime_s": {"render": runtime_s},
                    "f_static": f_static,
                },
            }
        ],
        "rgb_path": str(root / "rgb" / f"{frame}_rgb.png"),
    }
    (root / "labels" / f"{frame}_label.json").write_text(
        json.dumps(label),
        encoding="utf-8",
    )

    record = {
        "idx": idx,
        "seed": 7500,
        "rendered": True,
        "f_static": f_static,
        "runtime_s": runtime_s,
        "stage_runtime_s": {"render": runtime_s},
        "session_elapsed_s": session_elapsed_s,
        "rgb_path": str(root / "rgb" / f"{frame}_rgb.png"),
        "label_path": str(root / "labels" / f"{frame}_label.json"),
        "mask_paths": {
            name: str(root / "mask" / f"{frame}_{name}.png")
            for name in ("m0", "m1", "m2", "m3", "m4")
        },
    }
    (root / "records.json").write_text(
        json.dumps([record]),
        encoding="utf-8",
    )


class DeterminismComparatorTests(unittest.TestCase):
    def test_equal_decoded_artifacts_and_semantics_are_deterministic(self):
        comparator = _load_comparator()
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left"
            right = Path(tmp) / "right"
            _write_fixture(left)
            _write_fixture(right)

            report = comparator.compare_output_roots(left, right)

        self.assertTrue(report["deterministic"])
        self.assertEqual([], report["mismatches"])
        self.assertEqual([], report["errors"])
        self.assertEqual(
            {"records": 1, "labels": 1, "rgb": 1, "masks": 5},
            report["compared"],
        )

    def test_decoded_rgb_pixel_mismatch_is_reported(self):
        comparator = _load_comparator()
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left"
            right = Path(tmp) / "right"
            _write_fixture(left, rgb_pixel=(11, 22, 33))
            _write_fixture(right, rgb_pixel=(11, 22, 34))

            report = comparator.compare_output_roots(left, right)

        self.assertFalse(report["deterministic"])
        self.assertEqual(
            ["rgb_pixels"],
            [item["category"] for item in report["mismatches"]],
        )
        self.assertEqual(3, report["mismatches"][0]["idx"])
        self.assertEqual(12, report["mismatches"][0]["differing_values"])

    def test_semantic_record_mismatch_is_reported(self):
        comparator = _load_comparator()
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left"
            right = Path(tmp) / "right"
            _write_fixture(left, f_static=0.125)
            _write_fixture(right, f_static=0.25)

            report = comparator.compare_output_roots(left, right)

        self.assertFalse(report["deterministic"])
        record_mismatch = next(
            item
            for item in report["mismatches"]
            if item["category"] == "record_semantics"
        )
        self.assertEqual(3, record_mismatch["idx"])
        self.assertEqual("$.f_static", record_mismatch["path"])
        self.assertEqual(0.125, record_mismatch["left"])
        self.assertEqual(0.25, record_mismatch["right"])

    def test_explicit_runtime_path_and_session_only_differences_are_excluded(self):
        comparator = _load_comparator()
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left"
            right = Path(tmp) / "right"
            _write_fixture(
                left,
                runtime_s=1.25,
                session_elapsed_s=10.0,
            )
            _write_fixture(
                right,
                runtime_s=9.75,
                session_elapsed_s=99.0,
            )

            report = comparator.compare_output_roots(left, right)

        self.assertTrue(report["deterministic"])
        self.assertEqual([], report["mismatches"])
        self.assertIn("runtime_s", report["excluded_json_fields"])
        self.assertIn("session_elapsed_s", report["excluded_json_fields"])
        self.assertIn("rgb_path", report["excluded_json_fields"])


if __name__ == "__main__":
    unittest.main()
