"""mode semantics — "그 mode 의 물체가 실제로 화면에 있는가" (bpy-free).

2026-08-01 pilot 감사에서 드러난 결함:
  - cargo-only 400장 중 51장은 cargo 가 하나도 놓이지 않았는데 usable 로 통과했다.
  - context-rich 600장 중 39장은 context 배치를 **시도조차** 하지 않았는데 통과했다.
  - controlled-occlusion 은 f_target=0 plan 을 fallback 으로 렌더할 수 있었다.

여기서 검증하는 계약:
  usable = (기존 물리/마스크/게이트 조건) AND (mode 내용 조건)
  None 은 통과가 아니다 · 0 은 진짜 0 · False 는 진짜 실패.
"""

import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import run_v2_scene_logic as R    # noqa: E402
import scene_placement_v2 as SP2  # noqa: E402


def verdict(mode, **fields):
    return SP2.mode_semantics_verdict(mode, dict(fields))


CLEAN = dict(explicit_occluder_placed=False, cargo_visible_pixels=0,
             n_context_visible=0)
CARGO = dict(n_cargo_placed=2, cargo_visible_pixels=140)
CONTEXT = dict(n_context_requested=3, n_context_placed=3, n_context_visible=3,
               context_visible_pixel_ratio=1.0)
CONTROLLED = dict(f_explicit_target=0.2, explicit_occluder_placed=True,
                  explicit_occluder_visible_pixels=120, occluder_side_match=True)


class ModeSchedule(unittest.TestCase):
    """§3 — 10장 주기 interleave (2/2/3/3), 총량은 그대로."""

    def counts(self, n):
        from collections import Counter
        return dict(Counter(R.usable_diagnostic_modes(n)))

    def test_n10_is_2_2_3_3(self):
        self.assertEqual(self.counts(10), {
            "clean-static": 2, "cargo-only": 2,
            "context-rich": 3, "controlled-occlusion": 3})

    def test_n100_counts(self):
        self.assertEqual(self.counts(100), {
            "clean-static": 20, "cargo-only": 20,
            "context-rich": 30, "controlled-occlusion": 30})

    def test_n2000_counts(self):
        self.assertEqual(self.counts(2000), {
            "clean-static": 400, "cargo-only": 400,
            "context-rich": 600, "controlled-occlusion": 600})

    def test_first_ten_slots_cover_every_mode(self):
        self.assertEqual(set(R.usable_diagnostic_modes(2000)[:10]),
                         set(R.DIAGNOSTIC_MODES))

    def test_every_ten_block_is_2_2_3_3(self):
        from collections import Counter
        modes = R.usable_diagnostic_modes(2000)
        for start in range(0, 2000, 10):
            self.assertEqual(dict(Counter(modes[start:start + 10])), {
                "clean-static": 2, "cargo-only": 2,
                "context-rich": 3, "controlled-occlusion": 3}, f"block {start}")

    def test_same_n_gives_the_same_schedule(self):
        for n in (7, 10, 33, 100, 250, 2000):
            self.assertEqual(R.usable_diagnostic_modes(n),
                             R.usable_diagnostic_modes(n))

    def test_totals_match_apportionment_for_every_n_up_to_250(self):
        from collections import Counter
        for n in range(1, 251):
            modes = R.usable_diagnostic_modes(n)
            self.assertEqual(len(modes), n)
            counter = Counter(modes)
            self.assertEqual([counter[m] for m in R.DIAGNOSTIC_MODES],
                             R.apportion(n, R.USABLE_MODE_FRACTIONS), f"n={n}")

    def test_records_mode_allocation_is_untouched(self):
        from collections import Counter
        self.assertEqual(
            dict(Counter(R.diagnostic_mode_for_index(i, 20) for i in range(20))),
            {"clean-static": 5, "cargo-only": 5,
             "context-rich": 5, "controlled-occlusion": 5})
        self.assertEqual(
            dict(Counter(R.diagnostic_mode_for_index(i, 500) for i in range(500))),
            {"clean-static": 100, "cargo-only": 100,
             "context-rich": 150, "controlled-occlusion": 150})


class CargoSemantics(unittest.TestCase):
    def test_cargo_not_placed_is_rejected(self):
        v = verdict("cargo-only", n_cargo_placed=0, cargo_visible_pixels=0)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:cargo_not_placed")

    def test_placed_but_invisible_is_rejected(self):
        v = verdict("cargo-only", n_cargo_placed=2, cargo_visible_pixels=0)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:cargo_not_visible")

    def test_visible_pixels_gt_zero_passes(self):
        self.assertTrue(verdict("cargo-only", **CARGO)["pass"])

    def test_visible_cargo_that_does_not_occlude_the_pallet_still_passes(self):
        """cargo 가 팔레트를 가리도록 강제하지 않는다 — 보이기만 하면 된다."""
        v = verdict("cargo-only", n_cargo_placed=1, cargo_visible_pixels=12,
                    front_visibility_after_cargo=1.0,
                    left_opening_visibility_after_cargo=1.0,
                    right_opening_visibility_after_cargo=1.0)
        self.assertTrue(v["pass"])

    def test_pallet_mask_fields_are_not_used_for_cargo_visibility(self):
        """public mask 는 팔레트 전용이라 cargo 가시성의 근거가 될 수 없다."""
        v = verdict("cargo-only", n_cargo_placed=2, cargo_visible_pixels=0,
                    mask_m0_area_px=5000, mask_area_visible=3000)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:cargo_not_visible")


class ContextSemantics(unittest.TestCase):
    def test_requested_zero_is_rejected(self):
        v = verdict("context-rich", n_context_requested=0, n_context_placed=0,
                    n_context_visible=0, context_visible_pixel_ratio=0.0)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:context_not_requested")

    def test_placed_zero_is_rejected(self):
        v = verdict("context-rich", n_context_requested=3, n_context_placed=0,
                    n_context_visible=0, context_visible_pixel_ratio=0.0)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:context_not_placed")

    def test_placed_but_invisible_is_rejected(self):
        v = verdict("context-rich", n_context_requested=3, n_context_placed=3,
                    n_context_visible=0, context_visible_pixel_ratio=0.0)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:context_not_visible")

    def test_visible_context_passes(self):
        self.assertTrue(verdict("context-rich", **CONTEXT)["pass"])

    def test_cargo_cannot_substitute_for_context(self):
        v = verdict("context-rich", n_context_requested=3, n_context_placed=0,
                    n_context_visible=0, context_visible_pixel_ratio=0.0,
                    n_cargo_placed=2, cargo_visible_pixels=900)
        self.assertFalse(v["pass"])


class ControlledSemantics(unittest.TestCase):
    def test_zero_target_is_rejected(self):
        v = verdict("controlled-occlusion", **dict(CONTROLLED, f_explicit_target=0.0))
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:explicit_target_not_positive")

    def test_missing_occluder_is_rejected(self):
        v = verdict("controlled-occlusion",
                    **dict(CONTROLLED, explicit_occluder_placed=False))
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:explicit_occluder_missing")

    def test_invisible_occluder_is_rejected(self):
        v = verdict("controlled-occlusion",
                    **dict(CONTROLLED, explicit_occluder_visible_pixels=0))
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:explicit_occluder_not_visible")

    def test_side_mismatch_is_rejected(self):
        v = verdict("controlled-occlusion",
                    **dict(CONTROLLED, occluder_side_match=False))
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "mode_semantics:occluder_side_mismatch")

    def test_valid_controlled_passes(self):
        self.assertTrue(verdict("controlled-occlusion", **CONTROLLED)["pass"])

    def test_runner_never_renders_a_zero_target_plan_for_a_controlled_slot(self):
        """skip 상한을 넘겨도 f_target=0 plan 을 controlled 슬롯에 채우지 않는다."""
        import inspect
        src = inspect.getsource(R.run_usable)
        head = src[src.index('mode == "controlled-occlusion"'):]
        head = head[:head.index("consecutive_mode_skips = 0")]
        self.assertNotIn("consecutive_mode_skips < CONTROLLED_MODE_MAX_SKIPS", head)
        self.assertIn("stop_reason", head)


class NullSemantics(unittest.TestCase):
    def test_none_is_unknown_and_never_a_pass(self):
        v = verdict("cargo-only", n_cargo_placed=2, cargo_visible_pixels=None)
        self.assertFalse(v["pass"])
        self.assertIn("cargo_visible", v["unknown_conditions"])
        self.assertEqual([], v["failed_conditions"])

    def test_zero_is_a_real_zero_not_unknown(self):
        v = verdict("cargo-only", n_cargo_placed=2, cargo_visible_pixels=0)
        self.assertIn("cargo_visible", v["failed_conditions"])
        self.assertEqual([], v["unknown_conditions"])

    def test_false_is_a_real_failure(self):
        v = verdict("controlled-occlusion",
                    **dict(CONTROLLED, occluder_side_match=False))
        self.assertIn("occluder_side_match", v["failed_conditions"])
        self.assertEqual([], v["unknown_conditions"])


class UsableGateIntegration(unittest.TestCase):
    """usable_conditions 는 mode semantics 를 AND 한다 (short-circuit 없음)."""

    def base(self, mode, **extra):
        record = {
            "diagnostic_mode": mode,
            "rendered": True, "realize_ok": True, "camera_clearance_pass": True,
            "support_pass": True, "mask_invariants_pass": True,
            "ground_continuity_pass": True, "corrupt_rgb": False,
            "corrupt_mask": False, "exact_collision_count": 0,
            "camera_distance_limit_m": 10.0, "camera_distance_actual_m": 3.0,
            "mask_m0_area_px": 5000, "magenta_fraction": 0.0,
            "mask_pixel_inclusion_ok": True, "mask_m0_content_sha256": "h",
            "G1_pass": True, "G2_pass": True, "G3_pass": True,
            "G4_pass": True, "G5_pass": True,
        }
        record.update(extra)
        return record

    def test_every_mode_passes_when_its_content_is_present(self):
        for mode, fields in (("clean-static", CLEAN), ("cargo-only", CARGO),
                             ("context-rich", CONTEXT),
                             ("controlled-occlusion", CONTROLLED)):
            with self.subTest(mode=mode):
                v = R.usable_conditions(self.base(mode, **fields))
                self.assertTrue(v["usable"], v["reject_reasons"])
                self.assertTrue(v["mode_semantics_pass"])

    def test_semantics_failure_alone_rejects_an_otherwise_perfect_frame(self):
        v = R.usable_conditions(
            self.base("cargo-only", n_cargo_placed=0, cargo_visible_pixels=0))
        self.assertFalse(v["usable"])
        self.assertEqual(["mode_semantics:cargo_placed",
                          "mode_semantics:cargo_visible"], v["failed_conditions"])
        self.assertIn("mode_semantics:cargo_not_placed", v["reject_reasons"])

    def test_all_semantics_failures_are_reported_not_just_the_first(self):
        v = R.usable_conditions(self.base(
            "context-rich", n_context_requested=0, n_context_placed=0,
            n_context_visible=0, context_visible_pixel_ratio=0.0))
        self.assertEqual(3, len(v["mode_semantics_failed_conditions"]))

    def test_unknown_mode_is_left_alone(self):
        v = R.usable_conditions(self.base("clean-static", **CLEAN))
        self.assertTrue(v["usable"])
        record = self.base("clean-static", **CLEAN)
        record["diagnostic_mode"] = None
        self.assertTrue(R.usable_conditions(record)["usable"])


class PublicMaskUnchanged(unittest.TestCase):
    """§33-35 — public output 은 amodal + visible 2장뿐이고, 임시 마스크는 저장되지 않는다."""

    def test_public_profile_writes_only_amodal_and_visible(self):
        import mask_profiles as MP
        self.assertEqual(("mask_amodal", "mask_visible"),
                         tuple(MP.mask_dirnames("public")))
        paths = MP.frame_mask_paths("/out", 7, "public")
        self.assertEqual({"m0", "m4"}, set(paths))

    def test_cargo_visibility_masks_are_temporary_only(self):
        """cargo 가시성 측정은 _lowres_holdout 을 쓰고 그 임시 PNG 는 지워진다."""
        import inspect
        source = inspect.getsource
        import importlib
        spec = importlib.util.find_spec("v2_realize")
        text = open(spec.origin, encoding="utf-8").read()
        block = text[text.index("cargo_visible_union = 0"):
                     text.index('stage_runtime["cargo"] =')]
        self.assertIn("_lowres_holdout", block)
        self.assertNotIn("mask_prefix", block)
        self.assertNotIn("mask_paths", block)
        # _lowres_holdout 자체가 finally 에서 임시 파일을 지운다.
        holdout = text[text.index("def _lowres_holdout("):
                       text.index("def _lowres_stage_areas(")]
        self.assertIn("os.remove(path)", holdout)
        del source


if __name__ == "__main__":
    unittest.main()
