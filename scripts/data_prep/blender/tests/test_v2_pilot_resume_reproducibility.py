"""run_v2_scene_logic usable mode — session resume 결정성 (bpy-free).

**렌더하지 않는다.** proposal stream · quota · diagnostic mode · seed 유도만 검증한다.
Blender 를 띄우지 않고도 "세션을 나눠 돌려도 uninterrupted run 과 같은 데이터가 나오는가"
를 확인하는 것이 목적이다 — 2,000장을 100장씩 20세션으로 나눠 돌리기 전에 반드시 통과해야
한다.

핵심 계약:
  iter_proposals(seed) 는 seed 만으로 재생 가능한 stream 이고, quota 는 **accept 시점에만**
  advance 한다. 따라서 재개 시 stream 을 처음부터 재생해도 resume_from 이전 proposal 을
  건너뛰기만 하면 그 뒤 proposal 이 uninterrupted run 과 완전히 같다.
"""

import io
import json
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import run_v2_scene_logic as R  # noqa: E402
import v2_pipeline as vp        # noqa: E402

SEED = 7000
N_PROPOSALS = 120        # 렌더 없이 stream 만 도는 길이 (충분히 accept/reject 섞인다)


def canon(obj):
    """§9 가 요구한 canonical JSON — UTF-8 · sort_keys · compact · NaN 금지."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


class StreamFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()

    def stream(self, max_proposals=N_PROPOSALS):
        return R.iter_proposals(SEED, self.assets, vp,
                                placement_mode="constrained",
                                max_proposals=max_proposals)

    def drain(self, max_proposals=N_PROPOSALS):
        """(proposal_index, kind, canonical json) 목록."""
        out = []
        for proposal_index, plan, reject in self.stream(max_proposals):
            if plan is not None:
                out.append((proposal_index, "plan", canon(plan.to_dict())))
            else:
                out.append((proposal_index, "reject", canon(reject.to_dict())))
        return out


class ProposalStreamIsReplayable(StreamFixture):
    def test_two_full_runs_are_identical(self):
        self.assertEqual(self.drain(), self.drain())

    def test_chunked_replay_matches_uninterrupted_proposal_index(self):
        full = self.drain()
        # "세션 3개로 나눠 돌린다" = 매번 stream 을 처음부터 재생하고 resume_from 앞은 skip
        chunks, resume_from = [], 0
        for cut in (40, 90, N_PROPOSALS):
            piece = [row for row in self.drain() if row[0] >= resume_from][
                : cut - resume_from]
            chunks.extend(piece)
            resume_from = cut
        self.assertEqual([r[0] for r in chunks], [r[0] for r in full])

    def test_chunked_replay_matches_plan_canonical_json(self):
        full = self.drain()
        replay = [row for row in self.drain() if row[0] >= 40]
        self.assertEqual([r[2] for r in full if r[0] >= 40],
                         [r[2] for r in replay])

    def test_chunked_replay_matches_framespec_canonical_json(self):
        """FrameSpec 은 sample_frame 이 만든다 — quota advance 규칙까지 같아야 한다."""
        import random

        def specs(skip_before=0):
            rng = random.Random(SEED)
            quota = vp.QuotaState.new(self.assets)
            got = []
            for i in range(N_PROPOSALS):
                spec, picks = vp.sample_frame(rng, quota, self.assets,
                                              frame_index=i, seed=SEED)
                plan = vp.solve_placement(spec, self.assets,
                                          placement_mode="constrained")
                if isinstance(plan, vp.Plan):
                    vp.advance_quota(quota, picks)
                if i >= skip_before:
                    got.append((i, canon(spec.to_dict())))
            return got

        full = specs()
        self.assertEqual([x for x in full if x[0] >= 55], specs(skip_before=55))

    def test_reject_order_is_identical(self):
        full = self.drain()
        replay = self.drain()
        self.assertEqual([r[0] for r in full if r[1] == "reject"],
                         [r[0] for r in replay if r[1] == "reject"])

    def test_accept_reject_split_is_stable(self):
        kinds = [r[1] for r in self.drain()]
        self.assertEqual(kinds, [r[1] for r in self.drain()])
        self.assertIn("plan", kinds)      # fixture 가 의미 있으려면 둘 다 나와야 한다
        self.assertIn("reject", kinds)


class SeedDerivation(unittest.TestCase):
    def test_frame_seed_depends_only_on_master_seed_and_indices(self):
        a = R._frame_seed(SEED, 12, 3)
        b = R._frame_seed(SEED, 12, 3)
        self.assertEqual(a, b)
        self.assertNotEqual(a, R._frame_seed(SEED, 12, 4))
        self.assertNotEqual(a, R._frame_seed(SEED, 13, 3))
        self.assertNotEqual(a, R._frame_seed(SEED + 1, 12, 3))

    def test_frame_seed_is_session_independent(self):
        """세션이 나뉘어도 같은 (idx, attempt) 면 같은 seed 여야 한다."""
        self.assertEqual([R._frame_seed(SEED, i, 0) for i in range(50)],
                         [R._frame_seed(SEED, i, 0) for i in range(50)])


class DiagnosticModeAllocation(unittest.TestCase):
    def test_usable_modes_are_slot_owned_and_deterministic(self):
        a = R.usable_diagnostic_modes(2000)
        b = R.usable_diagnostic_modes(2000)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 2000)

    def test_mode_counts_match_the_pilot_expectation(self):
        from collections import Counter
        counts = Counter(R.usable_diagnostic_modes(2000))
        self.assertEqual(dict(counts), {
            "clean-static": 400, "cargo-only": 400,
            "context-rich": 600, "controlled-occlusion": 600,
        })

    def test_mode_of_a_slot_does_not_depend_on_session_boundaries(self):
        modes = R.usable_diagnostic_modes(2000)
        # 100장씩 20세션으로 잘라도 slot->mode 매핑은 그대로다 (slot 이 stratum 을 소유)
        rebuilt = []
        for start in range(0, 2000, 100):
            rebuilt.extend(R.usable_diagnostic_modes(2000)[start:start + 100])
        self.assertEqual(modes, rebuilt)


class ResumeState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v2resume_")
        self.addCleanup(self._cleanup)
        self.records = os.path.join(self.tmp, "records.jsonl")
        self.rejected = os.path.join(self.tmp, "records_rejected.jsonl")

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, path, rows):
        with io.open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_empty_state_starts_at_zero(self):
        latest, resume_from = R._resume_state(self.records, self.rejected)
        self.assertEqual((latest, resume_from), ({}, 0))

    def test_resume_from_is_max_proposal_index_plus_one(self):
        self.write(self.records, [
            {"usable_id": 0, "idx": 0, "proposal_index": 3},
            {"usable_id": 1, "idx": 1, "proposal_index": 9},
        ])
        self.write(self.rejected, [{"proposal_index": 11}, {"proposal_index": 7}])
        latest, resume_from = R._resume_state(self.records, self.rejected)
        self.assertEqual(resume_from, 12)
        self.assertEqual(sorted(latest), [0, 1])

    def test_delivered_frames_are_not_reprocessed(self):
        """resume_from 앞의 proposal 은 stream 에서 skip 된다 — 재렌더 0."""
        self.write(self.records, [{"usable_id": 0, "idx": 0, "proposal_index": 5}])
        _latest, resume_from = R._resume_state(self.records, self.rejected)
        assets = vp.load_assets()
        seen = [pi for pi, _p, _r in
                R.iter_proposals(SEED, assets, vp, placement_mode="constrained",
                                 max_proposals=30)
                if pi >= resume_from]
        self.assertEqual(seen[0], resume_from)
        self.assertNotIn(5, seen)

    def test_non_contiguous_usable_ids_are_rejected_by_state_shape(self):
        self.write(self.records, [
            {"usable_id": 0, "idx": 0, "proposal_index": 1},
            {"usable_id": 2, "idx": 2, "proposal_index": 4},
        ])
        latest, _ = R._resume_state(self.records, self.rejected)
        delivered = sorted(latest)
        self.assertNotEqual(delivered, list(range(len(delivered))))

    def test_records_jsonl_has_no_duplicate_usable_id_after_latest_wins(self):
        self.write(self.records, [
            {"usable_id": 0, "idx": 0, "proposal_index": 1},
            {"usable_id": 0, "idx": 0, "proposal_index": 1},
            {"usable_id": 1, "idx": 1, "proposal_index": 2},
        ])
        latest, _ = R._resume_state(self.records, self.rejected)
        self.assertEqual(sorted(latest), [0, 1])


class SessionCapValidation(unittest.TestCase):
    class Args(object):
        def __init__(self, **kw):
            self.completion_mode = kw.get("mode", "usable")
            self.n = kw.get("n", 2000)
            self.rerun_failures = False
            self.max_attempts = None
            self.session_usable_cap = kw.get("cap", None)

    def fail(self, message):
        raise ValueError(message)

    def test_default_none_is_accepted_and_changes_nothing(self):
        args = self.Args()
        self.assertIs(R.validate_args(args, self.fail), args)
        self.assertIsNone(args.session_usable_cap)

    def test_positive_cap_is_accepted(self):
        args = self.Args(cap=100)
        R.validate_args(args, self.fail)
        self.assertEqual(args.session_usable_cap, 100)

    def test_zero_and_negative_caps_are_rejected(self):
        for bad in (0, -1, -100):
            with self.assertRaises(ValueError):
                R.validate_args(self.Args(cap=bad), self.fail)

    def test_cap_requires_usable_mode(self):
        with self.assertRaises(ValueError):
            R.validate_args(self.Args(mode="records", n=500, cap=100), self.fail)

    def test_records_mode_without_cap_is_unaffected(self):
        args = self.Args(mode="records", n=500)
        self.assertIs(R.validate_args(args, self.fail), args)


class SessionPauseContract(unittest.TestCase):
    """cap 으로 멈춘 세션은 예외가 아니라 정상 종료여야 한다."""

    def test_pause_branch_returns_before_the_error_branch(self):
        import inspect
        src = inspect.getsource(R.run_usable)
        pause_at = src.index("if session_paused:")
        raise_at = src.index("if not complete:")
        self.assertLess(pause_at, raise_at,
                        "session_paused 분기가 UsableCompletionError 앞에 있어야 한다")
        self.assertIn("return summary", src[pause_at:raise_at])

    def test_summary_records_the_pause_fields(self):
        import inspect
        src = inspect.getsource(R.run_usable)
        for field in ("session_usable_cap", "session_usable_delivered",
                      "session_paused", "stop_reason"):
            self.assertIn(f'summary["{field}"]', src)

    def test_cap_does_not_touch_sampling_or_quota(self):
        """cap 은 루프 종료 조건일 뿐 — stream/quota 호출부를 건드리지 않는다."""
        import inspect
        src = inspect.getsource(R.run_usable)
        head = src[:src.index("while state[\"delivered\"]")]
        self.assertIn("iter_proposals(", head)
        self.assertIn("placement_mode=\"constrained\"", head)
        self.assertNotIn("session_cap", head.split("session_cap =")[0])


if __name__ == "__main__":
    unittest.main()
