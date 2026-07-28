"""public / full-audit mask 레이아웃 호환 테스트 (analyze + determinism).

임시 fixture 만 사용한다. Blender 렌더도, 실제 dataset 접근도 없다.

핵심 회귀 대상
  - public 셋에서 M1~M3 를 "결측"으로 세지 않을 것 (없는 게 정상이다)
  - public 에서 source 별 분해(f_static/f_cargo/...)를 0.0 으로 채우지 않을 것
    (None = 미측정 / 0.0 = 측정된 가림 없음 — 둘은 다르다)
  - determinism 비교가 좌/우 profile 을 각각 감지하고, 다르면 조용히 통과시키지 않을 것
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import mask_profiles as MP  # noqa: E402
import compare_v2_determinism as CD  # noqa: E402


def _load_analyze():
    spec = importlib.util.spec_from_file_location(
        "analyze_v2_scene_logic", os.path.join(_BLENDER_DIR, "analyze_v2_scene_logic.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("analyze_v2_scene_logic", module)
    spec.loader.exec_module(module)
    return module


AN = _load_analyze()

W, H = 8, 6


def _mask(area):
    arr = np.zeros((H, W), dtype=np.uint8)
    flat = arr.reshape(-1)
    flat[:area] = 255
    return Image.fromarray(arr, mode="L")


def _rgb():
    return Image.fromarray(np.full((H, W, 3), 40, dtype=np.uint8), mode="RGB")


def _label(idx):
    return {
        "frame": idx,
        "camera_data": {"resolution": [W, H]},
        "objects": [{"class": "pallet"}],
    }


def _record(idx, profile):
    return {
        "idx": idx,
        "mask_profile": profile,
        "occlusion_decomposition_available": MP.occlusion_decomposition_available(profile),
    }


class MaskFixture(object):
    """public 또는 full-audit 레이아웃의 최소 run 디렉토리."""

    def __init__(self, profile, n=2, areas=None):
        self.profile = profile
        self.n = n
        self.areas = areas or {"m0": 20, "m1": 18, "m2": 16, "m3": 14, "m4": 12}

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="masklayout_"))
        os.makedirs(os.path.join(self.root, "rgb"))
        os.makedirs(os.path.join(self.root, "labels"))
        for dirname in MP.mask_dirnames(self.profile):
            os.makedirs(os.path.join(self.root, dirname), exist_ok=True)
        records = []
        for idx in range(self.n):
            stem = MP.frame_stem(idx)
            _rgb().save(os.path.join(self.root, "rgb", stem + "_rgb.png"))
            with open(os.path.join(self.root, "labels", stem + "_label.json"),
                      "w", encoding="utf-8") as fh:
                json.dump(_label(idx), fh)
            for stage, path in MP.frame_mask_paths(self.root, idx, self.profile).items():
                _mask(self.areas[stage]).save(path)
            records.append(_record(idx, self.profile))
        # analyze 는 records.jsonl 을, determinism 비교기는 records.json 을 읽는다.
        with open(os.path.join(self.root, "records.jsonl"), "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        with open(os.path.join(self.root, "records.json"), "w", encoding="utf-8") as fh:
            json.dump(records, fh)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False


# ---------------------------------------------------------------------------
# mask_profiles 자체
# ---------------------------------------------------------------------------
class ProfileDefinitions(unittest.TestCase):
    def test_public_has_two_stages_full_audit_has_five(self):
        self.assertEqual(MP.mask_stages(MP.PUBLIC), ("m0", "m4"))
        self.assertEqual(MP.mask_stages(MP.FULL_AUDIT), ("m0", "m1", "m2", "m3", "m4"))

    def test_public_writes_two_directories_full_audit_one(self):
        self.assertEqual(MP.mask_dirnames(MP.PUBLIC), ("mask_amodal", "mask_visible"))
        self.assertEqual(MP.mask_dirnames(MP.FULL_AUDIT), ("mask",))

    def test_only_full_audit_can_decompose_by_source(self):
        self.assertTrue(MP.occlusion_decomposition_available(MP.FULL_AUDIT))
        self.assertFalse(MP.occlusion_decomposition_available(MP.PUBLIC))

    def test_detect_profile_reads_the_directories_on_disk(self):
        with MaskFixture(MP.PUBLIC) as fx:
            self.assertEqual(MP.detect_profile(fx.root), MP.PUBLIC)
        with MaskFixture(MP.FULL_AUDIT) as fx:
            self.assertEqual(MP.detect_profile(fx.root), MP.FULL_AUDIT)

    def test_public_decomposition_leaves_source_fractions_unmeasured(self):
        out, invariant = MP.decompose({"m0": 20, "m4": 12}, MP.PUBLIC)
        for key in MP.SOURCE_FRACTION_KEYS:
            self.assertIsNone(out[key], key)          # None = 미측정 (0.0 아님)
        for key in ("mask_area_after_static", "mask_area_after_cargo",
                    "mask_area_after_context"):
            self.assertIsNone(out[key], key)
        self.assertAlmostEqual(out["f_total"], 1 - 12 / 20)
        self.assertTrue(invariant["valid"], invariant["errors"])

    def test_zero_occlusion_is_zero_not_none(self):
        out, _ = MP.decompose({"m0": 20, "m4": 20}, MP.PUBLIC)
        self.assertEqual(out["f_total"], 0.0)         # 0.0 = 측정됐고 가림 없음
        self.assertIsNotNone(out["f_total"])

    def test_full_audit_decomposition_reports_every_source(self):
        out, _ = MP.decompose({"m0": 20, "m1": 18, "m2": 16, "m3": 14, "m4": 12},
                              MP.FULL_AUDIT)
        for key in MP.SOURCE_FRACTION_KEYS:
            self.assertIsNotNone(out[key], key)
        self.assertAlmostEqual(out["f_total"], 1 - 12 / 20)

    def test_public_decompose_rejects_full_audit_areas_as_incomplete(self):
        with self.assertRaises(KeyError):
            MP.decompose({"m0": 20}, MP.FULL_AUDIT)


# ---------------------------------------------------------------------------
# analyze_v2_scene_logic
# ---------------------------------------------------------------------------
class AnalyzeProfileResolution(unittest.TestCase):
    def test_auto_detects_public_from_the_directories(self):
        with MaskFixture(MP.PUBLIC) as fx:
            info = AN.resolve_mask_profile(AN.Path(fx.root), AN.MASK_PROFILE_AUTO, False)
            self.assertEqual(info["profile"], MP.PUBLIC)
            self.assertEqual(info["stages"], ["m0", "m4"])
            self.assertFalse(info["occlusion_decomposition_available"])
            self.assertIn("mask_amodal", info["detected_by"])

    def test_auto_detects_full_audit_from_the_directories(self):
        with MaskFixture(MP.FULL_AUDIT) as fx:
            info = AN.resolve_mask_profile(AN.Path(fx.root), AN.MASK_PROFILE_AUTO, False)
            self.assertEqual(info["profile"], MP.FULL_AUDIT)
            self.assertEqual(info["stages"], ["m0", "m1", "m2", "m3", "m4"])
            self.assertTrue(info["occlusion_decomposition_available"])

    def test_explicit_profile_overrides_detection(self):
        with MaskFixture(MP.FULL_AUDIT) as fx:
            info = AN.resolve_mask_profile(AN.Path(fx.root), MP.PUBLIC, False)
            self.assertEqual(info["profile"], MP.PUBLIC)
            self.assertEqual(info["detected_by"], "--mask-profile")

    def test_legacy_mask_names_override_keeps_the_old_layout(self):
        with MaskFixture(MP.FULL_AUDIT) as fx:
            info = AN.resolve_mask_profile(AN.Path(fx.root), AN.MASK_PROFILE_AUTO, True)
            self.assertEqual(info["profile"], "legacy-explicit")
            path = AN.mask_path_for(AN.Path(fx.root), 0, "m2", info)
            self.assertEqual(path.parent.name, "mask")
            self.assertTrue(path.is_file())

    def test_a_run_without_any_mask_directory_is_reported_as_unknown(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="nomask_"))
        try:
            info = AN.resolve_mask_profile(AN.Path(tmp), AN.MASK_PROFILE_AUTO, False)
            self.assertIn("unknown", info["detected_by"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class AnalyzePublicLayout(unittest.TestCase):
    def setUp(self):
        self.fx = MaskFixture(MP.PUBLIC, n=3).__enter__()
        self.root = AN.Path(self.fx.root)
        self.info = AN.resolve_mask_profile(self.root, AN.MASK_PROFILE_AUTO, False)
        self.names = list(self.info["stages"])

    def tearDown(self):
        self.fx.__exit__(None, None, None)

    def test_indices_are_discovered_from_the_public_mask_dirs(self):
        idx = AN.discover_indices(self.root, {}, self.names, self.info)
        self.assertEqual(idx, [0, 1, 2])

    def test_mask_paths_resolve_into_the_public_directories(self):
        p0 = AN.mask_path_for(self.root, 0, "m0", self.info)
        p4 = AN.mask_path_for(self.root, 0, "m4", self.info)
        self.assertEqual(p0.parent.name, "mask_amodal")
        self.assertEqual(p4.parent.name, "mask_visible")
        self.assertTrue(p0.is_file() and p4.is_file())

    def test_no_mask_is_reported_missing_for_a_complete_public_run(self):
        for idx in range(3):
            row = AN.build_frame_row(self.root, idx, None, self.names, self.info)
            self.assertNotIn("mask_", row["source_files_missing"],
                             "public 셋인데 mask 결측으로 셌습니다: " + row["source_files_missing"])
            self.assertTrue(row["mask_m0_present"])
            self.assertTrue(row["mask_m4_present"])

    def test_m1_to_m3_are_absent_by_design_not_counted_as_missing(self):
        row = AN.build_frame_row(self.root, 0, None, self.names, self.info)
        for stage in ("m1", "m2", "m3"):
            self.assertNotIn("mask_%s" % stage, row)

    def test_areas_are_measured_for_both_public_stages(self):
        row = AN.build_frame_row(self.root, 0, None, self.names, self.info)
        self.assertEqual(row["mask_m0_area"], 20)
        self.assertEqual(row["mask_m4_area"], 12)

    def test_csv_columns_do_not_carry_empty_m1_to_m3_placeholders(self):
        # 빈 m1~m3 컬럼이 남으면 CSV 소비자에게 "결측"으로 읽힌다.
        cols = AN.frame_columns(self.names)
        for stage in ("m1", "m2", "m3"):
            self.assertNotIn("mask_%s_area" % stage, cols)
        for stage in ("m0", "m4"):
            self.assertIn("mask_%s_area" % stage, cols)

    def test_full_audit_columns_still_carry_all_five_stages(self):
        cols = AN.frame_columns(["m0", "m1", "m2", "m3", "m4"])
        for stage in ("m0", "m1", "m2", "m3", "m4"):
            self.assertIn("mask_%s_area" % stage, cols)


class AnalyzeFullAuditLayout(unittest.TestCase):
    def setUp(self):
        self.fx = MaskFixture(MP.FULL_AUDIT, n=2).__enter__()
        self.root = AN.Path(self.fx.root)
        self.info = AN.resolve_mask_profile(self.root, AN.MASK_PROFILE_AUTO, False)
        self.names = list(self.info["stages"])

    def tearDown(self):
        self.fx.__exit__(None, None, None)

    def test_indices_are_discovered_from_the_legacy_mask_dir(self):
        self.assertEqual(AN.discover_indices(self.root, {}, self.names, self.info), [0, 1])

    def test_all_five_stages_are_present_and_measured(self):
        row = AN.build_frame_row(self.root, 0, None, self.names, self.info)
        for stage, area in (("m0", 20), ("m1", 18), ("m2", 16), ("m3", 14), ("m4", 12)):
            self.assertTrue(row["mask_%s_present" % stage], stage)
            self.assertEqual(row["mask_%s_area" % stage], area, stage)
        self.assertNotIn("mask_", row["source_files_missing"])

    def test_a_genuinely_missing_stage_is_still_reported(self):
        os.remove(os.path.join(self.fx.root, "mask", "f0000_m2.png"))
        row = AN.build_frame_row(self.root, 0, None, self.names, self.info)
        self.assertIn("mask_m2", row["source_files_missing"])


# ---------------------------------------------------------------------------
# compare_v2_determinism
# ---------------------------------------------------------------------------
class DeterminismAcrossProfiles(unittest.TestCase):
    def test_public_vs_public_compares_two_stages(self):
        with MaskFixture(MP.PUBLIC) as a, MaskFixture(MP.PUBLIC) as b:
            report = CD.compare_output_roots(a.root, b.root)
            self.assertEqual(report["left_mask_profile"], MP.PUBLIC)
            self.assertEqual(report["right_mask_profile"], MP.PUBLIC)
            self.assertEqual(report["compared_mask_stages"], ["m0", "m4"])
            self.assertFalse(report["partial_mask_comparison"])
            self.assertFalse(report["mask_profile_mismatch"])
            self.assertTrue(report["deterministic"], report["mismatches"] + report["errors"])
            self.assertEqual(report["compared"]["masks"], 2 * 2)

    def test_full_audit_vs_full_audit_compares_five_stages(self):
        with MaskFixture(MP.FULL_AUDIT) as a, MaskFixture(MP.FULL_AUDIT) as b:
            report = CD.compare_output_roots(a.root, b.root)
            self.assertEqual(report["compared_mask_stages"], ["m0", "m1", "m2", "m3", "m4"])
            self.assertTrue(report["deterministic"], report["mismatches"] + report["errors"])
            self.assertEqual(report["compared"]["masks"], 2 * 5)

    def test_profile_mismatch_is_an_error_by_default(self):
        with MaskFixture(MP.PUBLIC) as a, MaskFixture(MP.FULL_AUDIT) as b:
            report = CD.compare_output_roots(a.root, b.root)
            self.assertTrue(report["mask_profile_mismatch"])
            self.assertFalse(report["deterministic"])
            self.assertTrue(any(e["category"] == "mask_profile_mismatch"
                                for e in report["errors"]))

    def test_allowing_the_mismatch_compares_only_the_shared_stages(self):
        with MaskFixture(MP.PUBLIC) as a, MaskFixture(MP.FULL_AUDIT) as b:
            report = CD.compare_output_roots(a.root, b.root,
                                             allow_mask_profile_mismatch=True)
            self.assertEqual(report["compared_mask_stages"], ["m0", "m4"])
            self.assertTrue(report["partial_mask_comparison"])
            # 부분 비교는 완전 결정성 통과로 표현하지 않는다
            self.assertFalse(report["deterministic"])

    def test_a_differing_mask_pixel_is_detected_in_the_public_layout(self):
        with MaskFixture(MP.PUBLIC) as a, MaskFixture(MP.PUBLIC) as b:
            path = MP.frame_mask_paths(b.root, 0, MP.PUBLIC)["m4"]
            _mask(11).save(path)
            report = CD.compare_output_roots(a.root, b.root)
            self.assertFalse(report["deterministic"])
            self.assertTrue(any(m.get("category") == "mask_pixels" and m.get("mask") == "m4"
                                for m in report["mismatches"]))

    def test_rgb_and_label_determinism_still_checked(self):
        with MaskFixture(MP.PUBLIC) as a, MaskFixture(MP.PUBLIC) as b:
            report = CD.compare_output_roots(a.root, b.root)
            self.assertEqual(report["compared"]["rgb"], 2)
            self.assertEqual(report["compared"]["labels"], 2)

    def test_legacy_mask_names_override_is_still_supported(self):
        with MaskFixture(MP.FULL_AUDIT) as a, MaskFixture(MP.FULL_AUDIT) as b:
            report = CD.compare_output_roots(a.root, b.root, mask_names=("m0", "m4"))
            self.assertEqual(report["left_mask_profile"], "legacy-explicit")
            self.assertEqual(report["compared_mask_stages"], ["m0", "m4"])
            self.assertTrue(report["deterministic"])

    def test_artifact_paths_never_assemble_the_mask_dir_by_hand(self):
        src = open(CD.__file__, encoding="utf-8").read()
        # 남아 있는 유일한 직접 조립은 legacy(profile=None) 분기 하나뿐이어야 한다.
        self.assertEqual(src.count('"mask" / f"{frame}_'), 1)


if __name__ == "__main__":
    unittest.main()
