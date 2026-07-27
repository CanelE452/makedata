"""Phase 5 mask-integrity tests for audit_v2_scene_logic.py (bpy-free).

Covers the checks that scalar area monotonicity cannot see: strict decode, SHA256/content
hashing, pixel-level M4 subset-of ... subset-of M0 inclusion, within-frame and cross-frame
duplicates, and projected-cuboid hull alignment.
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


AUDIT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "audit_v2_scene_logic.py")
)
MASK_NAMES = ["m0", "m1", "m2", "m3", "m4"]


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_v2_scene_logic", AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit()


# ------------------------------------------------------------------------------------------
# Fixture helpers
# ------------------------------------------------------------------------------------------

# Matches the projected_cuboid written by _label(): a 24x18 box centred on (32, 24).
CUBOID_2D = [
    [20, 15], [44, 15], [44, 33], [20, 33],
    [24, 18], [40, 18], [40, 30], [24, 30],
]


def nested_masks(size=(64, 48), count=5):
    """Strictly nested rectangles: areas decrease AND pixels are properly included."""
    w, h = size
    out = []
    for i in range(count):
        arr = np.zeros((h, w), dtype=np.uint8)
        arr[16 + i : 32 - i, 21 + i : 43 - i] = 255
        out.append(arr)
    return out


def drifting_masks(size=(64, 48), count=5):
    """Areas stay non-increasing while the rectangle drifts up-right out of the previous stage.

    This is exactly the defect scalar-area monotonicity cannot see.
    """
    w, h = size
    out = []
    for i in range(count):
        arr = np.zeros((h, w), dtype=np.uint8)
        arr[16 - 2 * i : 30 - i, 21 + 2 * i : 43] = 255
        out.append(arr)
    return out


def identical_masks(size=(64, 48), count=5):
    arr = np.zeros((size[1], size[0]), dtype=np.uint8)
    arr[16:32, 21:43] = 255
    return [arr.copy() for _ in range(count)]


def _label(size=(64, 48), camera=(0.0, -5.0, 1.0), pose_shift=0.0):
    w, h = size
    return {
        "camera_data": {
            "width": w,
            "height": h,
            "intrinsics": {"fx": 600.0, "fy": 600.0, "cx": w / 2.0, "cy": h / 2.0},
            "location_worldframe": list(camera),
            "look_worldframe": [0.0, 0.0, 0.0],
            "scene_preset": "fixture_scene",
        },
        "objects": [
            {
                "name": "pallet_test",
                "source_asset": "Pallet_0",
                "pose_transform": [
                    [1.0, 0.0, 0.0, pose_shift],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                "cuboid": [
                    [-0.5, -1.0, 0.0], [0.5, -1.0, 0.0], [0.5, -1.0, 0.2], [-0.5, -1.0, 0.2],
                    [-0.5, 1.0, 0.0], [0.5, 1.0, 0.0], [0.5, 1.0, 0.2], [-0.5, 1.0, 0.2],
                ],
                "projected_cuboid": [list(p) for p in CUBOID_2D],
                "projected_cuboid_centroid": [32, 24],
                "safety_gates": {"all_pass": True},
                "v2_labels": {"scene_preset": "fixture_scene"},
            }
        ],
    }


def _record(idx, **overrides):
    rec = {
        "idx": idx,
        "scene_preset": "fixture_scene",
        "diagnostic_mode": "clean-static",
        "all_pass": True,
        "anchor_reject_reason": None,
        "rendered": True,
        "realize_ok": True,
        "exact_collision_count": 0,
        "camera_clearance_pass": True,
        "support_pass": True,
        "f_static": 0.0,
        "f_cargo": 0.0,
        "f_context": 0.0,
        "f_explicit": 0.0,
        "n_cargo_placed": 0,
        "n_context_placed": 0,
        "explicit_occluder_placed": False,
    }
    rec.update(overrides)
    return rec


def write_dataset(root: Path, frames: list[dict]) -> None:
    """frames: [{'masks': [np arrays], 'label': dict, 'record': dict, 'size': (w, h)}]"""
    for sub in ("rgb", "labels", "mask"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    records = []
    for i, frame in enumerate(frames):
        idx = frame.get("idx", i)
        size = frame.get("size", (64, 48))
        rgb_size = frame.get("rgb_size", size)
        # Distinct per frame so the pre-existing duplicate_rgb_hash check stays quiet.
        Image.new("RGB", rgb_size, (70 + idx, 70, 65)).save(root / "rgb" / f"f{idx:04d}_rgb.png")
        for name, arr in zip(MASK_NAMES, frame["masks"]):
            Image.fromarray(arr, mode="L").save(root / "mask" / f"f{idx:04d}_{name}.png")
        (root / "labels" / f"f{idx:04d}_label.json").write_text(
            json.dumps(frame.get("label") or _label(size), indent=2), encoding="utf-8"
        )
        records.append(frame.get("record") or _record(idx))
    (root / "records.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


def run_audit(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, AUDIT_PATH,
            "--dir", str(root),
            "--out", str(root / "eda"),
            "--mask-report-out", str(root / "eda" / "mask_integrity"),
            "--max-sheet-frames", "4",
            *extra,
        ],
        text=True,
        capture_output=True,
    )


def read_summary(root: Path) -> dict:
    return json.loads((root / "eda" / "audit_summary.json").read_text(encoding="utf-8"))


def read_groups(root: Path) -> dict:
    return json.loads(
        (root / "eda" / "mask_integrity" / "mask_duplicate_groups.json").read_text(encoding="utf-8")
    )


def read_inclusion_failures(root: Path) -> list[str]:
    return (
        (root / "eda" / "mask_integrity" / "mask_pixel_inclusion_failures.csv")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )


# ------------------------------------------------------------------------------------------
# Unit-level geometry / decode helpers
# ------------------------------------------------------------------------------------------

class MaskPrimitiveTests(unittest.TestCase):
    def test_foreground_bbox_accepts_bool_array_and_pil_image(self):
        arr = np.zeros((40, 60), dtype=np.uint8)
        arr[10:20, 5:35] = 255
        from_bool = AUDIT.foreground_bbox(arr > 127)
        from_image = AUDIT.foreground_bbox(Image.fromarray(arr))
        self.assertEqual(from_bool, from_image)
        self.assertEqual(30.0, from_bool["w"])
        self.assertEqual(10.0, from_bool["h"])
        self.assertEqual(10.0, from_bool["min_side"])

    def test_foreground_bbox_of_empty_mask_is_zero_sized(self):
        box = AUDIT.foreground_bbox(np.zeros((10, 10), dtype=bool))
        self.assertEqual(0.0, box["min_side"])
        self.assertIsNone(box["x0"])

    def test_bbox_iou_of_identical_boxes_is_one(self):
        box = {"x0": 0.0, "y0": 0.0, "x1": 9.0, "y1": 9.0}
        self.assertAlmostEqual(1.0, AUDIT.bbox_iou(box, box))

    def test_bbox_iou_of_disjoint_boxes_is_zero(self):
        a = {"x0": 0.0, "y0": 0.0, "x1": 4.0, "y1": 4.0}
        b = {"x0": 10.0, "y0": 10.0, "x1": 14.0, "y1": 14.0}
        self.assertEqual(0.0, AUDIT.bbox_iou(a, b))

    def test_convex_hull_drops_interior_points(self):
        pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [5.0, 5.0]])
        hull = AUDIT.convex_hull_points(pts)
        self.assertEqual(4, len(hull))
        self.assertNotIn([5.0, 5.0], hull.tolist())

    def test_convex_hull_rejects_nonfinite_points(self):
        pts = np.array([[0.0, 0.0], [float("nan"), 1.0], [2.0, 2.0]])
        self.assertIsNone(AUDIT.convex_hull_points(pts))

    def test_clip_polygon_keeps_only_the_in_image_part(self):
        poly = np.array([[-1000.0, -1000.0], [1000.0, -1000.0], [1000.0, 1000.0], [-1000.0, 1000.0]])
        clipped = AUDIT.clip_polygon_to_rect(poly, 64.0, 48.0)
        self.assertIsNotNone(clipped)
        self.assertLessEqual(float(clipped[:, 0].max()), 64.0)
        self.assertLessEqual(float(clipped[:, 1].max()), 48.0)
        self.assertGreaterEqual(float(clipped[:, 0].min()), 0.0)

    def test_clip_polygon_returns_none_when_fully_outside(self):
        poly = np.array([[200.0, 200.0], [220.0, 200.0], [220.0, 220.0]])
        self.assertIsNone(AUDIT.clip_polygon_to_rect(poly, 64.0, 48.0))

    def test_hull_alignment_matches_a_mask_inside_the_cuboid(self):
        fg = np.zeros((48, 64), dtype=bool)
        fg[16:32, 21:43] = True
        hull = AUDIT.convex_hull_points(np.asarray(CUBOID_2D, dtype=float))
        out = AUDIT.hull_alignment(fg, hull, 64, 48)
        self.assertEqual(0, out["outside_px"])
        self.assertGreater(out["bbox_iou"], 0.7)

    def test_hull_alignment_reports_foreground_outside_the_cuboid(self):
        fg = np.zeros((48, 64), dtype=bool)
        fg[0:10, 0:10] = True
        hull = AUDIT.convex_hull_points(np.asarray(CUBOID_2D, dtype=float))
        out = AUDIT.hull_alignment(fg, hull, 64, 48)
        self.assertEqual(1.0, out["outside_ratio"])
        self.assertEqual(0.0, out["bbox_iou"])

    def test_hull_alignment_reports_shape_mismatch(self):
        hull = AUDIT.convex_hull_points(np.asarray(CUBOID_2D, dtype=float))
        out = AUDIT.hull_alignment(np.zeros((10, 10), dtype=bool), hull, 64, 48)
        self.assertEqual("mask_shape_mismatch", out["reason"])

    def test_strict_decode_computes_byte_and_content_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m0.png"
            arr = np.zeros((48, 64), dtype=np.uint8)
            arr[10:20, 10:20] = 255
            Image.fromarray(arr, mode="L").save(path)
            out = AUDIT.strict_decode_mask(path)
        self.assertTrue(out["decode_ok"])
        self.assertEqual(100, out["area"])
        self.assertEqual(64, out["width"])
        self.assertEqual(48, out["height"])
        self.assertEqual(64, len(out["sha256"]))
        self.assertEqual(64, len(out["content_sha256"]))
        self.assertFalse(out["all_black"])

    def test_content_hash_ignores_sub_threshold_noise_that_changes_the_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = np.zeros((48, 64), dtype=np.uint8)
            base[10:20, 10:20] = 255
            noisy = base.copy()
            noisy[0, 0] = 90  # below the >127 foreground threshold
            paths = []
            for name, arr in (("a.png", base), ("b.png", noisy)):
                p = Path(tmp) / name
                Image.fromarray(arr, mode="L").save(p)
                paths.append(AUDIT.strict_decode_mask(p))
        self.assertNotEqual(paths[0]["sha256"], paths[1]["sha256"])
        self.assertEqual(paths[0]["content_sha256"], paths[1]["content_sha256"])

    def test_strict_decode_rejects_a_truncated_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m0.png"
            arr = np.zeros((48, 64), dtype=np.uint8)
            arr[10:40, 10:50] = 255
            Image.fromarray(arr, mode="L").save(path)
            data = path.read_bytes()
            path.write_bytes(data[: len(data) // 2])
            out = AUDIT.strict_decode_mask(path)
        self.assertFalse(out["decode_ok"])
        self.assertIsNotNone(out["error"])
        self.assertIsNone(out["fg"])


class PixelInclusionUnitTests(unittest.TestCase):
    @staticmethod
    def _masks(arrays):
        return {
            name: {"decode_ok": True, "fg": arr, "area": int(arr.sum()), "sha256": str(i)}
            for i, (name, arr) in enumerate(zip(MASK_NAMES, arrays))
        }

    def test_nested_masks_pass(self):
        arrays = [a > 127 for a in nested_masks()]
        out = AUDIT.mask_pixel_inclusion(self._masks(arrays), MASK_NAMES)
        self.assertTrue(out["ok"])
        self.assertEqual(0, out["violation_px_total"])

    def test_monotonic_areas_with_shifted_pixels_are_caught(self):
        """The exact case scalar-area auditing misses: area shrinks, pixels move outside."""
        arrays = [a > 127 for a in drifting_masks()]
        areas = [int(a.sum()) for a in arrays]
        self.assertTrue(all(areas[i] >= areas[i + 1] for i in range(4)), areas)
        out = AUDIT.mask_pixel_inclusion(self._masks(arrays), MASK_NAMES)
        self.assertFalse(out["ok"])
        self.assertEqual(4, out["violation_pair_count"])
        self.assertGreater(out["violation_px_total"], 0)

    def test_shape_mismatch_between_stages_is_a_violation(self):
        arrays = [a > 127 for a in nested_masks()]
        arrays[3] = np.zeros((24, 32), dtype=bool)
        out = AUDIT.mask_pixel_inclusion(self._masks(arrays), MASK_NAMES)
        self.assertFalse(out["shape_consistent"])
        self.assertFalse(out["ok"])

    def test_single_decoded_mask_is_not_checked(self):
        masks = {"m0": {"decode_ok": True, "fg": np.zeros((4, 4), dtype=bool), "area": 0, "sha256": "x"}}
        out = AUDIT.mask_pixel_inclusion(masks, MASK_NAMES)
        self.assertFalse(out["checked"])
        self.assertIsNone(out["ok"])
        self.assertEqual("insufficient_decoded_masks", out["reason"])


class StageSpanClassificationTests(unittest.TestCase):
    def test_absent_sources_make_identical_stages_expected(self):
        states = {"static": "absent", "cargo": "absent", "context": "absent", "explicit": "absent"}
        out = AUDIT.classify_stage_span(MASK_NAMES, MASK_NAMES, states)
        self.assertEqual("expected_no_op", out["classification"])

    def test_placed_but_not_occluding_is_not_a_defect(self):
        states = {"static": "absent", "cargo": "absent", "context": "placed_no_occlusion", "explicit": "absent"}
        out = AUDIT.classify_stage_span(["m2", "m3"], MASK_NAMES, states)
        self.assertEqual("no_op_placed_but_not_occluding", out["classification"])

    def test_recorded_occlusion_with_identical_mask_is_a_contradiction(self):
        states = {"static": "absent", "cargo": "absent", "context": "contradiction", "explicit": "absent"}
        out = AUDIT.classify_stage_span(["m2", "m3"], MASK_NAMES, states)
        self.assertEqual("unexpected_identical_stage", out["classification"])

    def test_missing_record_fields_stay_unverified(self):
        states = {"static": "unknown", "cargo": "absent", "context": "absent", "explicit": "absent"}
        out = AUDIT.classify_stage_span(MASK_NAMES, MASK_NAMES, states)
        self.assertEqual("unverified_no_op", out["classification"])

    def test_occluder_states_read_counters_and_fractions(self):
        rec = _record(0, n_context_placed=2, f_context=0.0, n_cargo_placed=1, f_cargo=0.3)
        states = AUDIT.occluder_source_states(rec, None)
        self.assertEqual("absent", states["static"])
        self.assertEqual("contradiction", states["cargo"])
        self.assertEqual("placed_no_occlusion", states["context"])
        self.assertEqual("absent", states["explicit"])

    def test_occluder_states_without_fractions_are_unknown(self):
        states = AUDIT.occluder_source_states({"idx": 0}, None)
        self.assertEqual({"unknown"}, set(states.values()))


class GeometryCrossCheckTests(unittest.TestCase):
    def test_identical_signatures_compare_equal(self):
        sig = {"label_present": True, "K": [1, 2, 3, 4], "pose_transform": [[1.0]]}
        out = AUDIT.compare_geometry_signatures([dict(sig), dict(sig)])
        self.assertTrue(out["geometry_identical"])
        self.assertEqual([], out["differing_fields"])

    def test_differing_pose_is_reported(self):
        a = {"label_present": True, "K": [1, 2, 3, 4], "pose_transform": [[1.0]]}
        b = dict(a, pose_transform=[[2.0]])
        out = AUDIT.compare_geometry_signatures([a, b])
        self.assertFalse(out["geometry_identical"])
        self.assertIn("pose_transform", out["differing_fields"])

    def test_missing_label_makes_the_comparison_unverifiable(self):
        a = {"label_present": True, "K": [1, 2, 3, 4]}
        b = {"label_present": False}
        out = AUDIT.compare_geometry_signatures([a, b])
        self.assertIsNone(out["geometry_identical"])
        self.assertFalse(out["comparable"])


# ------------------------------------------------------------------------------------------
# End-to-end fixtures through the CLI
# ------------------------------------------------------------------------------------------

class MaskIntegrityEndToEndTests(unittest.TestCase):
    def test_pixel_inclusion_violation_with_monotonic_areas_fails_the_audit(self):
        """Artificial fixture: areas stay non-increasing, pixels escape the previous stage."""
        arrays = drifting_masks()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": arrays}])
            proc = run_audit(root)
            summary = read_summary(root)
            failures = read_inclusion_failures(root)

        self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("FAIL", summary["status"])
        self.assertTrue(summary["mask_monotonic_fail_indices"] == [], "areas must stay monotonic")
        self.assertEqual([0], summary["mask_integrity"]["pixel_inclusion_fail_indices"])
        self.assertIn("mask_pixel_inclusion", summary["fatal_failure_count_by_type"])
        self.assertEqual(5, len(failures))  # header + 4 violating stage pairs

    def test_clean_static_identical_masks_are_not_a_false_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": identical_masks()}])
            proc = run_audit(root)
            summary = read_summary(root)
            groups = read_groups(root)

        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("PASS", summary["status"])
        self.assertEqual(1, summary["audit_pass_count"])
        within = groups["within_frame"]
        self.assertEqual(1, len(within))
        self.assertEqual(MASK_NAMES, within[0]["stages"])
        self.assertEqual("expected_no_op", within[0]["classification"])
        self.assertTrue(within[0]["byte_identical"])
        self.assertEqual(
            {"expected_no_op": 1},
            summary["mask_integrity"]["within_frame_duplicate_class_counts"],
        )

    def test_placed_context_that_occludes_nothing_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _record(0, diagnostic_mode="context-rich", n_context_placed=3, f_context=0.0)
            write_dataset(root, [{"masks": identical_masks(), "record": record}])
            proc = run_audit(root)
            summary = read_summary(root)
            groups = read_groups(root)

        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("PASS", summary["status"])
        self.assertEqual(
            "no_op_placed_but_not_occluding", groups["within_frame"][0]["classification"]
        )

    def test_recorded_occlusion_with_identical_stage_masks_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _record(0, diagnostic_mode="context-rich", n_context_placed=1, f_context=0.25)
            write_dataset(root, [{"masks": identical_masks(), "record": record}])
            proc = run_audit(root)
            summary = read_summary(root)

        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)  # non-fatal
        self.assertEqual("WARN", summary["status"])
        self.assertIn("mask_within_frame_duplicate_unexpected", summary["failure_count_by_type"])
        self.assertEqual(
            1,
            summary["mask_integrity"]["within_frame_duplicate_class_counts"][
                "unexpected_identical_stage"
            ],
        )

    def test_all_black_m0_in_two_frames_is_an_empty_target_defect(self):
        """Different resolutions and different bytes, same emptiness -> still one defect group."""
        black_small = [np.zeros((48, 64), dtype=np.uint8) for _ in range(5)]
        black_large = []
        for i in range(5):
            arr = np.zeros((54, 96), dtype=np.uint8)
            arr[0, i] = 90  # sub-threshold, so every file hashes differently
            black_large.append(arr)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(
                root,
                [
                    {"idx": 0, "masks": black_small},
                    {"idx": 1, "masks": black_large, "size": (96, 54), "label": _label((96, 54)),
                     "record": _record(1)},
                ],
            )
            run_audit(root)
            summary = read_summary(root)
            groups = read_groups(root)

        m0_groups = [g for g in groups["cross_frame_same_stage"] if g["stage"] == "m0"]
        self.assertEqual(1, len(m0_groups))
        self.assertEqual("empty_target_defect", m0_groups[0]["classification"])
        self.assertEqual([0, 1], m0_groups[0]["indices"])
        self.assertFalse(m0_groups[0]["byte_identical"])
        self.assertEqual("content_all_black", m0_groups[0]["grouped_by"])
        self.assertEqual([0, 1], summary["mask_integrity"]["cross_frame_empty_target_indices"])
        self.assertEqual(
            0, summary["mask_integrity"]["cross_frame_duplicate_class_counts"].get(
                "duplicate_with_identical_geometry", 0
            )
        )

    def test_identical_masks_across_frames_with_different_geometry_are_stale(self):
        masks = nested_masks()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(
                root,
                [
                    {"idx": 0, "masks": masks},
                    {"idx": 1, "masks": masks, "label": _label(pose_shift=3.0), "record": _record(1)},
                ],
            )
            proc = run_audit(root)
            summary = read_summary(root)
            groups = read_groups(root)

        stale = [g for g in groups["cross_frame_same_stage"] if g["classification"] == "stale_or_mismatched_mask"]
        self.assertEqual(5, len(stale))
        self.assertIn("pose_transform", stale[0]["geometry_cross_check"]["differing_fields"])
        self.assertTrue(stale[0]["byte_identical"])
        self.assertEqual([0, 1], summary["mask_integrity"]["cross_frame_stale_indices"])
        self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("mask_stale_cross_frame_duplicate", summary["fatal_failure_count_by_type"])

    def test_identical_masks_across_frames_with_identical_geometry_are_not_called_stale(self):
        masks = nested_masks()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(
                root,
                [
                    {"idx": 0, "masks": masks},
                    {"idx": 1, "masks": masks, "record": _record(1)},
                ],
            )
            proc = run_audit(root)
            summary = read_summary(root)
            groups = read_groups(root)

        classes = {g["classification"] for g in groups["cross_frame_same_stage"]}
        self.assertEqual({"duplicate_with_identical_geometry"}, classes)
        self.assertEqual([], summary["mask_integrity"]["cross_frame_stale_indices"])
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("PASS", summary["status"])

    def test_truncated_mask_file_is_reported_as_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": nested_masks()}])
            path = root / "mask" / "f0000_m2.png"
            data = path.read_bytes()
            path.write_bytes(data[: len(data) // 2])
            proc = run_audit(root)
            summary = read_summary(root)

        self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("corrupt_mask", summary["fatal_failure_count_by_type"])
        self.assertEqual([0], summary["mask_integrity"]["strict_decode_fail_indices"])

    def test_rgb_and_mask_resolution_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": nested_masks(), "rgb_size": (96, 54)}])
            proc = run_audit(root)
            summary = read_summary(root)

        self.assertNotEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual([0], summary["mask_integrity"]["rgb_shape_mismatch_indices"])
        self.assertIn("mask_rgb_shape_mismatch", summary["fatal_failure_count_by_type"])

    def test_mask_hashes_csv_has_one_row_per_stage_and_no_duplicate_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"idx": 0, "masks": nested_masks()}, {"idx": 1, "masks": nested_masks(), "record": _record(1)}])
            run_audit(root)
            lines = (root / "eda" / "mask_integrity" / "mask_hashes.csv").read_text(
                encoding="utf-8"
            ).strip().splitlines()

        header = lines[0].split(",")
        self.assertEqual(len(header), len(set(header)))
        self.assertIn("sha256", header)
        self.assertIn("content_sha256", header)
        self.assertEqual(1 + 2 * len(MASK_NAMES), len(lines))

    def test_hull_alignment_warns_when_the_mask_sits_off_the_cuboid(self):
        arrays = []
        for i in range(5):
            arr = np.zeros((48, 64), dtype=np.uint8)
            arr[2 : 12 - i, 2 : 14 - i] = 255  # far from the 20..44 x 15..33 cuboid
            arrays.append(arr)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": arrays}])
            proc = run_audit(root)
            summary = read_summary(root)

        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)  # metric, not a gate
        self.assertEqual([0], summary["mask_integrity"]["hull_align_warn_indices"])
        self.assertEqual(1.0, summary["mask_integrity"]["hull_outside_ratio_max"])

    def test_aligned_mask_does_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": nested_masks()}])
            run_audit(root)
            summary = read_summary(root)

        self.assertEqual([], summary["mask_integrity"]["hull_align_warn_indices"])
        self.assertGreater(summary["mask_integrity"]["hull_bbox_iou_median_m0"], 0.7)

    def test_all_four_phase5_artifacts_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, [{"masks": nested_masks()}])
            run_audit(root)
            report_dir = root / "eda" / "mask_integrity"
            for name in (
                "mask_hashes.csv",
                "mask_duplicate_groups.json",
                "mask_pixel_inclusion_failures.csv",
                "mask_integrity_source_masks.png",
            ):
                self.assertTrue((report_dir / name).exists(), name)
            self.assertTrue(
                (root / "eda" / "contact_sheets" / "mask_integrity_source_masks.png").exists()
            )


if __name__ == "__main__":
    unittest.main()
