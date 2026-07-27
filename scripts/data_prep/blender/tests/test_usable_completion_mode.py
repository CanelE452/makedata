"""Phase-7 usable-count completion mode (bpy-free).

Covers three things the runner must get right:

  1. `usable_conditions` evaluates every condition INDEPENDENTLY and ANDs them, so each
     condition can reject on its own and `None` (= not measured) never counts as a pass.
  2. `run_usable` fills ids 0..n-1 exactly, keeps every rejected proposal in
     records_rejected.jsonl, deletes the images of rejected attempts and aborts loudly at
     the attempt cap.
  3. `--completion-mode records` still produces the pre-Phase-7 record schema (snapshot).

The orchestration tests patch `_process_frame` (the Blender half) and drive `run_usable`
with a fake v2_pipeline stream, so nothing here needs bpy.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace


BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

RUNNER_PATH = os.path.join(BLENDER_DIR, "run_v2_scene_logic.py")


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_v2_scene_logic", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Frozen schema of a rendered record BEFORE Phase 7 (146 keys).  records mode must keep
# producing exactly this set; usable mode is only allowed to ADD keys on top.
RECORD_RENDERED_KEYS = (
    "G1_pass", "G2_pass", "G3_pass", "G4_pass", "G5_pass", "V_actual", "V_vis", "all_pass",
    "anchor_attempts", "anchor_reject_counts_by_reason", "anchor_reject_reason",
    "anchor_translation", "attempt_frame_index", "azimuth_bin", "background_asset",
    "blur_applied", "blur_radius_px", "broad_phase_hits", "camera_clearance_pass",
    "camera_distance_actual_m", "camera_distance_error_m", "camera_distance_limit_m",
    "camera_distance_target_m", "cargo_collision_count", "cargo_collision_pass", "cargo_on",
    "cargo_placement_attempts", "cargo_support_pass", "collision_reject_reason",
    "context_context_collision_count", "context_placement_attempts",
    "context_reject_counts_by_reason", "context_screen_area_ratio", "context_support_pass",
    "context_visible_pixel_ratio", "corrupt_mask", "corrupt_mask_reasons", "corrupt_rgb",
    "corrupt_rgb_reason", "dark_factor", "diagnostic_mode", "elev_actual", "elev_target",
    "exact_collision_count", "exact_collision_hits", "explicit_abs_error",
    "explicit_candidate_log", "explicit_collision_pass", "explicit_feedback_depth_step_m",
    "explicit_initial_proposal", "explicit_occluder_placed",
    "explicit_occluder_visible_pixels", "explicit_proposal_count",
    "explicit_proposal_dimension_normalizations", "explicit_proposal_dimension_rejects",
    "explicit_proposal_names", "explicit_reject_counts_by_reason",
    "explicit_reservation_count", "explicit_reservations", "explicit_search_runs",
    "explicit_selected_object", "explicit_selected_stage", "explicit_solver_fail_reason",
    "explicit_support_pass", "explicit_target_mask_stats", "f_cargo", "f_context",
    "f_explicit", "f_explicit_actual", "f_explicit_target", "f_static", "f_target", "f_total",
    "floor_mode", "front_face_visibility", "front_visibility_after_cargo",
    "gaussian_noise_applied", "gaussian_sigma", "ground_continuity_pass",
    "ground_continuity_reason", "ground_probe_count", "ground_probe_fail_count",
    "ground_probe_hit_objects", "ground_probe_max_step_m", "idx", "jpeg_applied",
    "jpeg_quality", "label_path", "left_opening_visibility",
    "left_opening_visibility_after_cargo", "luma_frame", "luma_frame_final", "luma_frame_raw",
    "luma_pallet", "luma_pallet_final", "luma_pallet_raw", "magenta_fraction",
    "mask_area_after_cargo", "mask_area_after_context", "mask_area_after_static",
    "mask_area_target_only", "mask_area_visible", "mask_invariants_pass", "mask_paths",
    "min_camera_clearance", "n_cargo_placed", "n_cargo_requested", "n_context_placed",
    "n_context_requested", "n_context_visible", "noise_tier", "occluder_feedback_iterations",
    "occluder_side_actual", "occluder_side_match", "occluder_side_target",
    "occlusion_decomposition_order", "opening_visibility_reason",
    "pallet_obstacle_collision_count", "pallet_support_pass", "pallet_type", "placement_mode",
    "procedural_floor_edge_margin_m", "procedural_floor_edge_risk",
    "procedural_support_shift", "projected_size_actual", "projected_size_feasible_lower",
    "projected_size_target", "realize_ok", "reject_reason", "rendered", "rgb_path",
    "right_opening_visibility", "right_opening_visibility_after_cargo", "runtime_s",
    "scene_preset", "seed", "stage_runtime_s", "static_collision_pass", "static_los_pass",
    "support_pass", "support_surface_name", "tested_collision_pairs", "v_target",
    "vignette_applied", "vignette_strength", "wb_gain_rgb",
)


def passing_record(idx, mask_hash):
    """A record that satisfies every usable condition."""
    return {
        "idx": idx,
        "rendered": True,
        "realize_ok": True,
        "camera_clearance_pass": True,
        "support_pass": True,
        "mask_invariants_pass": True,
        "ground_continuity_pass": True,
        "corrupt_rgb": False,
        "corrupt_mask": False,
        "exact_collision_count": 0,
        "camera_distance_limit_m": 10.0,
        "camera_distance_actual_m": 3.25,
        "mask_m0_area_px": 5000,
        "mask_area_target_only": 5000.0,
        "magenta_fraction": 0.0,
        "mask_pixel_inclusion_ok": True,
        "mask_m0_content_sha256": mask_hash,
        "G1_pass": True,
        "G2_pass": True,
        "G3_pass": True,
        "G4_pass": True,
        "G5_pass": True,
        "all_pass": True,
        "runtime_s": 1.0,
        "diagnostic_mode": "clean-static",
        "pallet_type": "P0",
        "scene_preset": "indoor",
        "luma_pallet_final": 18.0,
        "bbox_vis_min_side_px": 120.0,
        "visible_kp_count": 9,
    }


class UsableConditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def test_full_pass_record_is_usable(self):
        verdict = self.runner.usable_conditions(passing_record(0, "h0"))
        self.assertTrue(verdict["usable"])
        self.assertEqual([], verdict["failed_conditions"])
        self.assertEqual([], verdict["reject_reasons"])
        self.assertTrue(verdict["physical_valid"])
        self.assertTrue(verdict["gate_valid"])

    def test_each_condition_rejects_on_its_own(self):
        cases = {
            "rendered": {"rendered": False},
            "realize_ok": {"realize_ok": False},
            "camera_clearance_pass": {"camera_clearance_pass": False},
            "support_pass": {"support_pass": False},
            "mask_invariants_pass": {"mask_invariants_pass": False},
            "ground_continuity_pass": {"ground_continuity_pass": False},
            "no_corrupt_rgb": {"corrupt_rgb": True},
            "no_corrupt_mask": {"corrupt_mask": True},
            "exact_collision_zero": {"exact_collision_count": 1},
            "camera_distance_within_limit": {"camera_distance_actual_m": 10.5},
            "mask_m0_non_empty": {"mask_m0_area_px": 0, "mask_area_target_only": 0.0},
            "no_magenta": {"magenta_fraction": 0.02},
            "mask_pixel_inclusion": {"mask_pixel_inclusion_ok": False},
            "G1": {"G1_pass": False},
            "G2": {"G2_pass": False},
            "G3": {"G3_pass": False},
            "G4": {"G4_pass": False},
            "G5": {"G5_pass": False},
        }
        for condition, override in cases.items():
            with self.subTest(condition=condition):
                record = {**passing_record(0, "h0"), **override}
                verdict = self.runner.usable_conditions(record)
                self.assertFalse(verdict["usable"])
                self.assertEqual([condition], verdict["failed_conditions"])
                prefix = (
                    "gate_fail" if condition in self.runner.GATE_CONDITIONS
                    else "usable_reject"
                )
                self.assertEqual([f"{prefix}:{condition}"], verdict["reject_reasons"])

    def test_primary_reject_reason_collapses_unmeasurable_failures(self):
        rendered = {**passing_record(0, "h0"), "G5_pass": False}
        verdict = self.runner.usable_conditions(rendered)
        self.assertEqual(
            "gate_fail:G5", self.runner.primary_reject_reason(rendered, verdict)
        )

        never_rendered = {"rendered": False, "realize_ok": False,
                          "reject_reason": "bounded_local_search_exhausted"}
        verdict = self.runner.usable_conditions(never_rendered)
        self.assertGreater(len(verdict["reject_reasons"]), 10)
        self.assertEqual(
            "usable_reject:rendered|usable_reject:realize_ok",
            self.runner.primary_reject_reason(never_rendered, verdict),
        )
        self.assertEqual(
            "realize_fail:x",
            self.runner.primary_reject_reason(
                {"reject_reason": "x"},
                {"reject_reasons": ["usable_reject:rendered:unknown"]},
            ),
        )

    def test_stale_cross_frame_mask_duplicate_rejects(self):
        record = passing_record(0, "dup")
        verdict = self.runner.usable_conditions(record, seen_m0_hashes={"dup"})
        self.assertFalse(verdict["usable"])
        self.assertEqual(["no_stale_cross_frame_mask"], verdict["failed_conditions"])
        self.assertTrue(
            self.runner.usable_conditions(record, seen_m0_hashes={"other"})["usable"]
        )

    def test_missing_measurement_is_not_a_pass(self):
        for field in ("ground_continuity_pass", "support_pass", "mask_pixel_inclusion_ok",
                      "camera_distance_actual_m", "magenta_fraction",
                      "mask_m0_content_sha256"):
            with self.subTest(field=field):
                record = {**passing_record(0, "h0"), field: None}
                if field == "mask_m0_content_sha256":
                    record.pop("mask_m0_content_sha256")
                    record["mask_m0_content_sha256"] = None
                verdict = self.runner.usable_conditions(record)
                self.assertFalse(verdict["usable"])
                self.assertEqual(1, len(verdict["unknown_conditions"]))
                self.assertTrue(
                    verdict["reject_reasons"][0].endswith(":unknown"),
                    verdict["reject_reasons"],
                )

    def test_all_failures_are_reported_not_just_the_first(self):
        record = {
            **passing_record(0, "h0"),
            "G5_pass": False,
            "ground_continuity_pass": False,
            "camera_distance_actual_m": 42.0,
        }
        verdict = self.runner.usable_conditions(record)
        self.assertEqual(
            {"G5", "ground_continuity_pass", "camera_distance_within_limit"},
            set(verdict["failed_conditions"]),
        )
        self.assertIn("gate_fail:G5", verdict["reject_reasons"])
        self.assertIn(
            "usable_reject:camera_distance_within_limit", verdict["reject_reasons"]
        )
        self.assertFalse(verdict["physical_valid"])
        self.assertFalse(verdict["gate_valid"])

    def test_distance_limit_is_inclusive_and_falls_back_to_10m(self):
        at_limit = {**passing_record(0, "h0"), "camera_distance_actual_m": 10.0}
        self.assertTrue(self.runner.usable_conditions(at_limit)["usable"])
        over = {**passing_record(0, "h0"), "camera_distance_actual_m": 10.000002}
        self.assertFalse(self.runner.usable_conditions(over)["usable"])
        no_limit = {**passing_record(0, "h0"), "camera_distance_actual_m": 11.0}
        no_limit.pop("camera_distance_limit_m")
        verdict = self.runner.usable_conditions(no_limit)
        self.assertEqual(["camera_distance_within_limit"], verdict["failed_conditions"])

    def test_magenta_tolerance_is_configurable(self):
        record = {**passing_record(0, "h0"), "magenta_fraction": 3.2e-6}
        self.assertFalse(self.runner.usable_conditions(record)["usable"])
        self.assertTrue(
            self.runner.usable_conditions(record, magenta_max=1e-4)["usable"]
        )

    def test_m0_area_falls_back_to_mask_area_target_only(self):
        record = passing_record(0, "h0")
        record.pop("mask_m0_area_px")
        self.assertTrue(self.runner.usable_conditions(record)["usable"])
        record["mask_area_target_only"] = 0.0
        self.assertEqual(
            ["mask_m0_non_empty"],
            self.runner.usable_conditions(record)["failed_conditions"],
        )

    def test_physical_valid_matches_phase4_field_list(self):
        """physical_valid must be built from audit_pnp_eligibility.physical_validity's fields."""
        try:
            import audit_pnp_eligibility as ape
        except Exception as exc:                      # cv2 missing (e.g. inside Blender)
            self.skipTest(f"audit_pnp_eligibility unavailable: {exc}")
        self.assertEqual(
            set(ape.PHYSICAL_BOOL_FIELDS), set(self.runner.PHYSICAL_TRUE_FIELDS)
        )
        self.assertEqual(
            set(ape.PHYSICAL_NEGATED_FIELDS), set(self.runner.PHYSICAL_NEGATED_FIELDS)
        )
        self.assertEqual(
            set(ape.GATE_BOOL_FIELDS),
            {self.runner.GATE_RECORD_FIELDS[g] for g in self.runner.GATE_CONDITIONS},
        )


class UsableScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def test_slot_modes_apportion_the_500_shares(self):
        modes = self.runner.usable_diagnostic_modes(50)
        self.assertEqual(50, len(modes))
        self.assertEqual(10, modes.count("clean-static"))
        self.assertEqual(10, modes.count("cargo-only"))
        self.assertEqual(15, modes.count("context-rich"))
        self.assertEqual(15, modes.count("controlled-occlusion"))

    def test_slot_modes_sum_to_n_for_every_small_n(self):
        for n in range(1, 61):
            with self.subTest(n=n):
                self.assertEqual(n, len(self.runner.usable_diagnostic_modes(n)))
        self.assertEqual([2, 2, 3, 3], self.runner.apportion(10, (0.2, 0.2, 0.3, 0.3)))
        self.assertEqual([0, 0, 1, 0], self.runner.apportion(1, (0.2, 0.2, 0.3, 0.3)))

    def test_attempt_cap_defaults_and_override(self):
        self.assertEqual(60, self.runner.usable_max_render_attempts(1))
        self.assertEqual(300, self.runner.usable_max_render_attempts(10))
        self.assertEqual(1500, self.runner.usable_max_render_attempts(50))
        self.assertEqual(77, self.runner.usable_max_render_attempts(50, 77))

    def test_pnp_size_columns_are_thresholds_of_8px_cells(self):
        fields = self.runner.pnp_size_fields(24.0, 5000)
        self.assertTrue(fields["pnp_size_eligible_2cell"])
        self.assertTrue(fields["pnp_size_eligible_3cell"])
        self.assertFalse(fields["pnp_size_eligible_4cell"])
        self.assertFalse(fields["tiny_warning"])
        tiny = self.runner.pnp_size_fields(12.0, 100)
        self.assertFalse(tiny["pnp_size_eligible_2cell"])
        self.assertTrue(tiny["tiny_warning"])
        unknown = self.runner.pnp_size_fields(None, None)
        self.assertIsNone(unknown["pnp_size_eligible_2cell"])
        self.assertFalse(unknown["tiny_warning"])

    def test_records_mode_rejects_free_n_and_usable_mode_accepts_it(self):
        errors = []

        def fail(message):
            errors.append(message)
            raise ValueError(message)

        args = SimpleNamespace(completion_mode="records", n=37, rerun_failures=False,
                               max_attempts=None)
        with self.assertRaises(ValueError):
            self.runner.validate_args(args, fail)
        for n in (20, 500):
            self.runner.validate_args(
                SimpleNamespace(completion_mode="records", n=n, rerun_failures=False,
                                max_attempts=None),
                fail,
            )
        self.runner.validate_args(
            SimpleNamespace(completion_mode="usable", n=37, rerun_failures=False,
                            max_attempts=None),
            fail,
        )
        with self.assertRaises(ValueError):
            self.runner.validate_args(
                SimpleNamespace(completion_mode="usable", n=10, rerun_failures=True,
                                max_attempts=None),
                fail,
            )
        with self.assertRaises(ValueError):
            self.runner.validate_args(
                SimpleNamespace(completion_mode="usable", n=10, rerun_failures=False,
                                max_attempts=3),
                fail,
            )


# ----------------------------------------------------------------------------------------
# Fake pipeline / Blender halves for the run_usable orchestration tests
# ----------------------------------------------------------------------------------------

class FakeSpec:
    def __init__(self, frame_index, f_target):
        self.frame_index = frame_index
        self.f_target = f_target

    def to_dict(self):
        return {"frame_index": self.frame_index, "f_target": self.f_target}


class FakePlan:
    def __init__(self, spec):
        self.spec = spec


class FakeReject:
    def __init__(self, spec, reason, detail=""):
        self.spec = spec
        self.reason = reason
        self.detail = detail


class FakePipeline:
    """Minimal v2_pipeline surface used by iter_proposals / run_usable."""

    Plan = FakePlan
    Reject = FakeReject

    def __init__(self, script=None):
        # script[i] = "plan" | "reject" | "plan_no_occluder"
        self.script = script or []
        self.advanced = 0

    class QuotaState:
        @staticmethod
        def new(assets):
            return {"n": 0}

    def load_assets(self):
        return {"assets": True}

    def sample_frame(self, rng, quota, assets, frame_index=-1, seed=-1):
        kind = self.script[frame_index] if frame_index < len(self.script) else "plan"
        f_target = 0.0 if kind == "plan_no_occluder" else 0.2
        return FakeSpec(frame_index, f_target), {"picks": frame_index}

    def solve_placement(self, spec, assets, placement_mode="constrained"):
        kind = (
            self.script[spec.frame_index]
            if spec.frame_index < len(self.script) else "plan"
        )
        if kind == "reject":
            return FakeReject(spec, "camera_distance_out_of_range", "d=94m")
        return FakePlan(spec)

    def advance_quota(self, quota, picks):
        self.advanced += 1
        quota["n"] += 1

    def prepare_diagnostic_explicit_occluders(self, plan, assets):
        return plan


class FakeRealize:
    @staticmethod
    def enable_gpu():
        return "fake-gpu"


def _fake_process_frame(overrides, salt=""):
    """Patched _process_frame: writes placeholder files, returns a scripted record.

    `salt` makes the fake M0 content hashes unique across separate runs (a resumed session
    renders genuinely different frames; without the salt the runner's cross-frame stale-mask
    check would - correctly - reject them as duplicates of the already delivered ones).
    """
    calls = []

    def fake(idx, plan, mode, args, assets, dirs, vp, vr, np, write_label=True):
        attempt = len(calls)
        override = overrides(attempt) if callable(overrides) else (
            overrides[attempt] if attempt < len(overrides) else {}
        )
        rgb_path = os.path.join(dirs["rgb"], f"f{idx:04d}_rgb.png")
        label_path = os.path.join(dirs["labels"], f"f{idx:04d}_label.json")
        masks = {}
        for stage in ("m0", "m1", "m2", "m3", "m4"):
            path = os.path.join(dirs["mask"], f"f{idx:04d}_{stage}.png")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("mask")
            masks[stage] = path
        with open(rgb_path, "w", encoding="utf-8") as handle:
            handle.write("rgb")
        record = passing_record(idx, f"hash{salt}{attempt}")
        record.update({
            "mask_paths": masks,
            "rgb_path": rgb_path,
            "label_path": label_path,
            "diagnostic_mode": mode,
        })
        record.update(override)
        calls.append({"idx": idx, "mode": mode, "attempt": attempt,
                      "frame_index": plan.spec.frame_index})
        return {
            "record": record,
            "rs": {},
            "meas": None,          # skip the real mask decode; fields are scripted above
            "gates": None,
            "label": {"frame": idx},
            "effects": None,
            "frame_seed": 900000 + attempt,
            "plan": plan,
            "rgb_path": rgb_path,
            "label_path": label_path,
        }

    fake.calls = calls
    return fake


class RunUsableTests(unittest.TestCase):
    def setUp(self):
        self.runner = _load_runner()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "usable")
        self.dirs = {
            "out": self.out,
            "rgb": os.path.join(self.out, "rgb"),
            "mask": os.path.join(self.out, "mask"),
            "labels": os.path.join(self.out, "labels"),
            "logs": os.path.join(self.out, "logs"),
        }
        for path in self.dirs.values():
            os.makedirs(path, exist_ok=True)

    def _args(self, n=4, **kwargs):
        base = dict(
            out=self.out, seed=7500, n=n, completion_mode="usable", max_attempts=None,
            magenta_max_fraction=0.0, samples=None, render_profile="diagnostic-exact",
            noise_tier="auto", start=0, count=100, rerun_failures=False,
        )
        base.update(kwargs)
        return SimpleNamespace(**base)

    def _run(self, overrides, n=4, script=None, args=None, salt=""):
        self.runner._process_frame = _fake_process_frame(overrides, salt=salt)
        pipeline = FakePipeline(script)
        summary = self.runner.run_usable(
            args or self._args(n=n), self.dirs, pipeline, FakeRealize, None
        )
        return summary, self.runner._process_frame, pipeline

    def _read_jsonl(self, name):
        path = os.path.join(self.out, name)
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_delivers_exactly_n_contiguous_ids_with_provenance(self):
        summary, process, _ = self._run(lambda attempt: {}, n=4)
        records = self._read_jsonl("records.jsonl")

        self.assertEqual(4, summary["usable_delivered"])
        self.assertTrue(summary["complete"])
        self.assertEqual([0, 1, 2, 3], [r["idx"] for r in records])
        self.assertEqual([0, 1, 2, 3], [r["usable_id"] for r in records])
        self.assertEqual([0, 1, 2, 3], [r["proposal_index"] for r in records])
        self.assertEqual(
            [900000 + i for i in range(4)], [r["attempt_seed"] for r in records]
        )
        self.assertEqual(4, len(os.listdir(self.dirs["rgb"])))
        self.assertEqual(4, len(os.listdir(self.dirs["labels"])))
        self.assertEqual(20, len(os.listdir(self.dirs["mask"])))
        self.assertEqual([], self._read_jsonl("records_rejected.jsonl"))
        self.assertEqual(4, process.calls[-1]["attempt"] + 1)

    def test_rejected_attempts_are_logged_and_their_files_removed(self):
        # every other attempt fails G5 -> 4 usable frames need 8 render attempts
        summary, process, _ = self._run(
            lambda attempt: {} if attempt % 2 else {"G5_pass": False, "all_pass": False},
            n=4,
        )
        rejected = self._read_jsonl("records_rejected.jsonl")

        self.assertEqual(4, summary["usable_delivered"])
        self.assertEqual(8, summary["render_attempts"])
        self.assertEqual(4, summary["render_rejects"])
        self.assertEqual(4, len(rejected))
        self.assertTrue(all(r["stage"] == "render" for r in rejected))
        self.assertTrue(all(r["reject_reason"] == "gate_fail:G5" for r in rejected))
        self.assertEqual({"gate_fail:G5": 4}, summary["reject_reason_counts"])
        self.assertEqual({"gate_fail:G5": 4}, summary["primary_reject_reason_counts"])
        self.assertEqual({"G5": 4}, summary["condition_fail_counts"])
        self.assertTrue(all(r["primary_reject_reason"] == "gate_fail:G5" for r in rejected))
        self.assertEqual([0, 1, 2, 3], [r["idx"] for r in self._read_jsonl("records.jsonl")])
        # the delivered set is exactly n; nothing from a rejected attempt survives
        self.assertEqual(4, len(os.listdir(self.dirs["rgb"])))
        self.assertEqual(20, len(os.listdir(self.dirs["mask"])))
        for entry in rejected:
            # rgb + 5 masks (no label is written before the usable verdict)
            self.assertEqual(6, len(entry["removed_files"]))
            self.assertFalse(any(p.endswith("_label.json") for p in entry["removed_files"]))

    def test_solve_rejects_are_individually_recorded(self):
        script = ["reject", "plan", "reject", "plan"]
        summary, _, pipeline = self._run(lambda attempt: {}, n=2, script=script)
        rejected = self._read_jsonl("records_rejected.jsonl")

        self.assertEqual(2, summary["usable_delivered"])
        self.assertEqual(2, summary["solve_rejects"])
        self.assertEqual(2, pipeline.advanced)          # quota advances only on accept
        self.assertEqual(2, len(rejected))
        self.assertTrue(all(r["stage"] == "solve" for r in rejected))
        self.assertEqual(
            ["solve_reject:camera_distance_out_of_range"] * 2,
            [r["reject_reason"] for r in rejected],
        )
        self.assertEqual([0, 2], [r["proposal_index"] for r in rejected])
        self.assertEqual(
            {"camera_distance_out_of_range": 2}, summary["solve_reject_reason_counts"]
        )
        self.assertEqual(
            [1, 3], [r["proposal_index"] for r in self._read_jsonl("records.jsonl")]
        )

    def test_controlled_slot_skips_plans_without_an_explicit_occluder(self):
        # slot 0 is clean-static (n=1 apportions the single slot to context-rich)
        args = self._args(n=10)
        script = ["plan"] * 7 + ["plan_no_occluder", "plan_no_occluder"] + ["plan"] * 40
        summary, process, _ = self._run(lambda attempt: {}, script=script, args=args)
        rejected = self._read_jsonl("records_rejected.jsonl")

        self.assertEqual(10, summary["usable_delivered"])
        self.assertEqual(2, summary["mode_filter_skips"])
        skips = [r for r in rejected if r["stage"] == "mode_filter"]
        self.assertEqual(2, len(skips))
        self.assertTrue(
            all(r["diagnostic_mode"] == "controlled-occlusion" for r in skips)
        )
        self.assertEqual(
            ["proposal_skip:mode_requires_explicit_occluder"] * 2,
            [r["reject_reason"] for r in skips],
        )
        modes = [r["diagnostic_mode"] for r in self._read_jsonl("records.jsonl")]
        self.assertEqual(2, modes.count("clean-static"))
        self.assertEqual(3, modes.count("controlled-occlusion"))

    def test_stale_cross_frame_mask_is_rejected_against_delivered_frames(self):
        summary, _, _ = self._run(
            lambda attempt: {"mask_m0_content_sha256": "same"} if attempt < 2 else {},
            n=2,
        )
        rejected = self._read_jsonl("records_rejected.jsonl")
        self.assertEqual(2, summary["usable_delivered"])
        self.assertEqual(1, len(rejected))
        self.assertEqual(
            "usable_reject:no_stale_cross_frame_mask", rejected[0]["reject_reason"]
        )

    def test_attempt_cap_raises_with_progress_preserved(self):
        args = self._args(n=4, max_attempts=5)
        with self.assertRaises(self.runner.UsableCompletionError) as caught:
            self._run(lambda attempt: {"G5_pass": False}, args=args)

        self.assertIn("render attempt cap", str(caught.exception))
        summary = json.load(open(os.path.join(self.out, "driver_summary.json")))
        self.assertFalse(summary["complete"])
        self.assertEqual(0, summary["usable_delivered"])
        self.assertEqual(5, summary["render_attempts"])
        self.assertEqual(5, len(self._read_jsonl("records_rejected.jsonl")))
        self.assertEqual(0, len(os.listdir(self.dirs["rgb"])))

    def test_manifest_and_readme_state_the_delivery_level(self):
        self._run(lambda attempt: {}, n=3)
        with open(os.path.join(self.out, "usable_manifest.csv"), encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        header = lines[0].split(",")
        self.assertEqual(list(self.runner.USABLE_MANIFEST_COLUMNS), header)
        self.assertEqual(3, len(lines) - 1)
        self.assertIn("pnp_size_eligible_2cell", header)
        self.assertNotIn("pnp_eligible_candidate_2cell", header)

        manifest = json.load(open(os.path.join(self.out, "usable_manifest.json")))
        self.assertIn("NOT 'final training-ready'", manifest["delivery_level"])
        self.assertTrue(manifest["pnp_size_axis"]["not_a_filter"])
        self.assertEqual(
            {"2cell": 16.0, "3cell": 24.0, "4cell": 32.0},
            manifest["pnp_size_axis"]["thresholds_px"],
        )
        with open(os.path.join(self.out, "README_usable.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn('NOT "final training-ready"', readme)
        self.assertIn("records_rejected.jsonl", readme)

    def test_resume_continues_ids_and_does_not_replay_logged_proposals(self):
        self._run(lambda attempt: {}, n=2, salt="a")
        first_rejected = len(self._read_jsonl("records_rejected.jsonl"))

        summary, process, _ = self._run(lambda attempt: {}, n=4, salt="b")
        records = self._read_jsonl("records.jsonl")

        self.assertEqual(4, summary["usable_delivered"])
        self.assertEqual([0, 1, 2, 3], [r["idx"] for r in records])
        self.assertEqual([0, 1, 2, 3], [r["proposal_index"] for r in records])
        self.assertEqual(2, summary["render_attempts"])   # only the two missing slots
        self.assertEqual(first_rejected, len(self._read_jsonl("records_rejected.jsonl")))
        # session counters are per-session; the log total is cumulative
        self.assertEqual(first_rejected, summary["rejected_log_entries_total"])

    def test_records_mode_record_schema_is_unchanged(self):
        """Snapshot guard: usable-only fields must never leak into the records-mode schema."""
        import math
        import tempfile as tf

        from PIL import Image

        import v2_pipeline as vp

        assets = vp.load_assets()
        plans, _, _, _ = vp.generate_accepted(
            1, 7500, assets, placement_mode="constrained"
        )
        plan = plans[0]
        rs = {
            "cam_pos": [3.0, 0.0, 1.0], "W": 640, "pallet_name": plan.spec.pallet_type,
            "background": None, "floor_mode": None, "elevation_deg_actual": 18.0,
            "occluder": None, "n_cargo": 0, "constrained_metrics": {},
        }
        meas = {
            "mask_paths": {}, "V_inframe": 8, "V_vis": 8,
            "uv8_v4": [[100.0, 10.0]] * 4 + [[420.0, 300.0]] * 4,
            "centroid_world": [0.0, 0.0, 0.075],
        }
        with tf.TemporaryDirectory() as tmp:
            rgb_path = os.path.join(tmp, "f0000_rgb.png")
            Image.new("RGB", (8, 8), (30, 30, 30)).save(rgb_path)
            record = self.runner._record_rendered(
                0, 1, "clean-static", plan, rs, meas,
                {"G1_Vvis>=4": True, "all_pass": True}, 1.0, {"noise_tier": "clean"},
                rgb_path, os.path.join(tmp, "f0000_label.json"),
            )
        self.assertEqual(set(RECORD_RENDERED_KEYS), set(record))
        self.assertTrue(math.isfinite(record["camera_distance_actual_m"]))
        for leaked in ("usable", "usable_id", "proposal_index", "physical_valid",
                       "gate_valid", "mask_pixel_inclusion_ok"):
            self.assertNotIn(leaked, record)


class IterProposalsTests(unittest.TestCase):
    def setUp(self):
        self.runner = _load_runner()

    def test_indices_increase_over_rejects_and_quota_advances_on_accept_only(self):
        pipeline = FakePipeline(["plan", "reject", "reject", "plan"])
        seen = list(
            self.runner.iter_proposals(7500, {}, pipeline, max_proposals=4)
        )
        self.assertEqual([0, 1, 2, 3], [index for index, _, _ in seen])
        self.assertEqual([True, False, False, True],
                         [plan is not None for _, plan, _ in seen])
        self.assertEqual(2, pipeline.advanced)

    def test_stream_stops_at_max_proposals(self):
        pipeline = FakePipeline(["plan"] * 10)
        self.assertEqual(
            3, len(list(self.runner.iter_proposals(1, {}, pipeline, max_proposals=3)))
        )


if __name__ == "__main__":
    unittest.main()
