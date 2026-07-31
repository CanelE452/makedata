"""manage_pallet_data_layout — Stage 2-D2 layout-completion policy unit tests.

**실제 data/pallet 을 옮기지 않는다.** 전부 tmpdir fixture 위에서 돈다
(마지막 회귀 클래스만 실제 저장소 원장을 **읽기 전용**으로 본다).

이 policy 가 지켜야 하는 것:
  - frozen_final_plan 이 allowlist 다 (SHA256 결속, 변경되면 거부)
  - cohort 를 임의로 쪼개 일부만 옮길 수 없다
  - live runtime/test 참조가 살아있으면 옮기지 않는다 (옛 경로 재생성 방지)
  - 제한 라이선스 자료는 redistributable·release 로 갈 수 없다
  - 최종 policy container 는 옮길 수 없다 (구조 자체가 사라진다)
  - prior ledger 구성원은 successor chain 계획 없이 옮길 수 없다
"""

import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
_DATA_PREP_DIR = os.path.dirname(_BLENDER_DIR)
for _p in (_BLENDER_DIR, _DATA_PREP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import manage_pallet_data_layout as MPL  # noqa: E402

PLAN_FIELDS = [
    "d2_move_id", "source", "destination", "entry_kind", "classification",
    "license_status", "exclusion_required", "source_file_count",
    "source_total_bytes", "current_runtime_refs", "current_test_refs",
    "current_doc_refs", "registry_refs", "prior_ledger_members",
    "successor_chain_required", "destination_policy_root", "transaction_group",
    "plan_origin", "rollback_source", "rollback_destination",
]


def sha_file(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            b = fh.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class Args(object):
    def __init__(self, **kw):
        self.d2_plan = kw.get("d2_plan")
        self.d2_plan_sha256 = kw.get("d2_plan_sha256")
        self.cohort = kw.get("cohort")
        self.move_ids = kw.get("move_ids")
        self.max_hash_read_gib = kw.get("max_hash_read_gib")


class FakePaths(object):
    def __init__(self, root):
        self.project_root = root

    def get(self, key):
        if key == "pallet_data_root":
            return os.path.join(self.project_root, "data", "pallet")
        raise KeyError(key)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="d2policy_")
        self.addCleanup(self._cleanup)
        self.paths = FakePaths(self.tmp)
        os.makedirs(os.path.join(self.tmp, "reports", "data_pallet_cleanup"))

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- fixture helpers -------------------------------------------------
    def make_item(self, rel, files=("a.txt",)):
        ap = os.path.join(self.tmp, rel.replace("/", os.sep))
        os.makedirs(ap, exist_ok=True)
        for f in files:
            with open(os.path.join(ap, f), "wb") as fh:
                fh.write(b"payload-" + f.encode())
        return ap

    def row(self, mid, src, dst, **kw):
        r = {k: "" for k in PLAN_FIELDS}
        r.update({
            "d2_move_id": mid, "source": src, "destination": dst,
            "entry_kind": kw.get("entry_kind", "dir"),
            "classification": kw.get("classification", "SUPERSEDED_RUN"),
            "license_status": kw.get("license_status", "LOW"),
            "exclusion_required": kw.get("exclusion_required", "false"),
            "source_file_count": kw.get("files", 1),
            "source_total_bytes": kw.get("bytes", 10),
            "current_runtime_refs": kw.get("rt", 0),
            "current_test_refs": kw.get("test", 0),
            "current_doc_refs": 0, "registry_refs": kw.get("registry", 0),
            "prior_ledger_members": "", "successor_chain_required":
                kw.get("chain", "false"),
            "destination_policy_root": "/".join(dst.split("/")[:4]),
            "transaction_group": kw.get("cohort", "D2_SUPERSEDED_RUNS"),
            "plan_origin": "TEST",
            "rollback_source": dst, "rollback_destination": src,
        })
        return r

    def freeze(self, rows, **overrides):
        out = os.path.join(self.tmp, "reports", "data_pallet_cleanup", "stage2d2")
        os.makedirs(out, exist_ok=True)
        csv_abs = os.path.join(out, "frozen_final_plan.csv")
        with open(csv_abs, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=PLAN_FIELDS)
            w.writeheader()
            w.writerows(rows)
        spec = {
            "plan_csv": "reports/data_pallet_cleanup/stage2d2/frozen_final_plan.csv",
            "plan_csv_sha256": sha_file(csv_abs),
            "selected_count": len(rows),
            "destination_policy_problems": [], "nested_source_conflicts": [],
            "duplicate_destinations": [],
            "hash_budget": {"within": True, "limit_gib": 16},
        }
        spec.update(overrides)
        json_abs = os.path.join(out, "frozen_final_plan.json")
        with open(json_abs, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=2)
        return json_abs, csv_abs

    def run_plan(self, json_abs, **kw):
        args = Args(d2_plan=json_abs, **kw)
        policy = MPL.get_policy(MPL.POLICY_STAGE2D2)
        return list(MPL._stage2d2_candidates(args, policy, self.paths))


class PlanBinding(Base):
    def test_valid_plan_yields_rows(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a")])
        got = self.run_plan(j)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "data/pallet/_diag_a")

    def test_plan_csv_modified_after_freeze_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, csv_abs = self.freeze([self.row(
            "D2-001", "data/pallet/_diag_a",
            "data/pallet/archive/superseded_runs/_diag_a")])
        with open(csv_abs, "a", encoding="utf-8-sig") as fh:
            fh.write("D2-002,x,y,dir,,,,,,,,,,,,,,,,\n")
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_row_count_mismatch_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a")],
                           selected_count=5)
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_missing_plan_file_is_rejected(self):
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(os.path.join(self.tmp, "nope.json"))

    def test_plan_sha_mismatch_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a")])
        args = Args(d2_plan=j, d2_plan_sha256="0" * 64)
        with self.assertRaises(MPL.PlanBindingError):
            list(MPL._stage2d2_candidates(args, MPL.get_policy(MPL.POLICY_STAGE2D2),
                                          self.paths))

    def test_recorded_policy_problems_block_the_plan(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze(
            [self.row("D2-001", "data/pallet/_diag_a",
                      "data/pallet/archive/superseded_runs/_diag_a")],
            destination_policy_problems=[["x", "DEST_COLLISION", "y"]])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_hash_budget_over_limit_blocks_before_hashing(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze(
            [self.row("D2-001", "data/pallet/_diag_a",
                      "data/pallet/archive/superseded_runs/_diag_a")],
            hash_budget={"within": False, "limit_gib": 16})
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)


class CohortRules(Base):
    def _two_cohorts(self):
        self.make_item("data/pallet/_diag_a")
        self.make_item("data/pallet/_diag_b")
        self.make_item("data/pallet/_ds_c")
        return [
            self.row("D2-001", "data/pallet/_diag_a",
                     "data/pallet/archive/superseded_runs/_diag_a"),
            self.row("D2-002", "data/pallet/_diag_b",
                     "data/pallet/archive/superseded_runs/_diag_b"),
            self.row("D2-003", "data/pallet/_ds_c",
                     "data/pallet/archive/legacy_datasets/_ds_c",
                     cohort="D2_LEGACY_DATASETS"),
        ]

    def test_selecting_one_cohort_takes_all_of_its_rows(self):
        j, _ = self.freeze(self._two_cohorts())
        got = self.run_plan(j, cohort="D2_SUPERSEDED_RUNS")
        self.assertEqual(len(got), 2)

    def test_cohort_selection_cannot_be_narrowed(self):
        """--cohort 로 고른 cohort 는 **전부** 나와야 한다.

        plan 이 그 cohort 를 3행 갖고 있는데 2행만 나오면 예산에 맞춰 일부만 옮기는
        것이라 atomic 계약이 깨진다. (부분 선택은 --move-ids 로 **명시** 요청할 때만
        허용되는 복구용 escape hatch다 — D1 부터의 설계.)
        """
        rows = self._two_cohorts()
        j, _ = self.freeze(rows)
        got = self.run_plan(j, cohort="D2_SUPERSEDED_RUNS")
        want = sum(1 for r in rows if r["transaction_group"] == "D2_SUPERSEDED_RUNS")
        self.assertEqual(len(got), want)

    def test_explicit_move_ids_are_honoured_as_recovery_hatch(self):
        j, _ = self.freeze(self._two_cohorts())
        got = self.run_plan(j, move_ids="D2-001")
        self.assertEqual([g[0] for g in got], ["data/pallet/_diag_a"])

    def test_unknown_cohort_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a",
                                     cohort="D2_MADE_UP")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_duplicate_destination_in_plan_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        self.make_item("data/pallet/_diag_b")
        j, _ = self.freeze([
            self.row("D2-001", "data/pallet/_diag_a",
                     "data/pallet/archive/superseded_runs/same"),
            self.row("D2-002", "data/pallet/_diag_b",
                     "data/pallet/archive/superseded_runs/same"),
        ])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_nested_parent_and_child_sources_conflict(self):
        self.make_item("data/pallet/_diag_a")
        self.make_item("data/pallet/_diag_a/inner")
        j, _ = self.freeze([
            self.row("D2-001", "data/pallet/_diag_a",
                     "data/pallet/archive/superseded_runs/_diag_a"),
            self.row("D2-002", "data/pallet/_diag_a/inner",
                     "data/pallet/archive/superseded_runs/inner"),
        ])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)


class DestinationPolicy(Base):
    def test_destination_outside_allowed_root_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/made_up_root/_diag_a")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_destination_outside_archive_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/runs/_diag_a")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_path_escape_is_rejected(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row(
            "D2-001", "data/pallet/_diag_a",
            "data/pallet/archive/superseded_runs/../../../escape")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_restricted_license_cannot_go_to_redistributable(self):
        self.make_item("data/pallet/_noai_ds")
        j, _ = self.freeze([self.row(
            "D2-001", "data/pallet/_noai_ds",
            "data/pallet/archive/legacy_datasets/redistributable/_noai_ds",
            license_status="HIGH(NoAI baked)", cohort="D2_LEGACY_DATASETS")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_restricted_license_to_noai_baked_is_allowed(self):
        self.make_item("data/pallet/_noai_ds")
        j, _ = self.freeze([self.row(
            "D2-001", "data/pallet/_noai_ds",
            "data/pallet/archive/legacy_datasets/noai_baked/_noai_ds",
            license_status="HIGH(NoAI baked)", cohort="D2_LEGACY_DATASETS")])
        self.assertEqual(len(self.run_plan(j)), 1)

    def test_zip_outside_packages_root_is_rejected(self):
        self.make_item("data/pallet/_pkg")
        j, _ = self.freeze([self.row(
            "D2-001", "data/pallet/_pkg",
            "data/pallet/archive/superseded_runs/thing.zip", entry_kind="file")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)


class ReferenceGuards(Base):
    def test_live_runtime_reference_blocks_the_move(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a",
                                     rt=1)])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_live_test_reference_blocks_the_move(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a",
                                     test=1)])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_registry_owned_source_blocks_the_move(self):
        self.make_item("data/pallet/_diag_a")
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_diag_a",
                                     "data/pallet/archive/superseded_runs/_diag_a",
                                     registry=1)])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_doc_only_reference_does_not_block(self):
        self.make_item("data/pallet/_diag_a")
        r = self.row("D2-001", "data/pallet/_diag_a",
                     "data/pallet/archive/superseded_runs/_diag_a")
        r["current_doc_refs"] = 12
        j, _ = self.freeze([r])
        self.assertEqual(len(self.run_plan(j)), 1)


class PolicyContainerGuards(Base):
    def test_final_policy_container_cannot_be_moved(self):
        self.make_item("data/pallet/release")
        j, _ = self.freeze([self.row(
            "D2-001", "data/pallet/release",
            "data/pallet/archive/legacy_layout/empty_sources/release")])
        with self.assertRaises(MPL.PlanBindingError):
            self.run_plan(j)

    def test_is_policy_container_recognises_semantic_roots(self):
        for p in ("data/pallet/archive/legacy_datasets",
                  "data/pallet/archive/superseded_runs",
                  "data/pallet/archive/nonredistributable",
                  "data/pallet/release", "data/pallet/runs"):
            self.assertTrue(MPL.is_policy_container(p), p)

    def test_is_policy_container_does_not_swallow_payload(self):
        for p in ("data/pallet/archive/superseded_runs/_v2_pilot_2k",
                  "data/pallet/_diag_a",
                  "data/pallet/archive/legacy_datasets/noai_baked/x"):
            self.assertFalse(MPL.is_policy_container(p), p)


class EmptyDirectoryHandling(Base):
    def test_empty_directory_is_planned_when_allowed(self):
        os.makedirs(os.path.join(self.tmp, "data", "pallet", "_empty_run"))
        j, _ = self.freeze([self.row("D2-001", "data/pallet/_empty_run",
                                     "data/pallet/archive/superseded_runs/_empty_run",
                                     files=0, bytes=0)])
        got = self.run_plan(j)
        self.assertEqual(len(got), 1)

    def test_empty_source_relocation_preserves_relative_path(self):
        # §13: basename 평탄화 금지 — 원래 상대경로 구조를 유지한다
        src = "data/pallet/old_parent/old_child"
        dst = ("data/pallet/archive/legacy_layout/empty_sources/"
               "old_parent/old_child")
        os.makedirs(os.path.join(self.tmp, src.replace("/", os.sep)))
        j, _ = self.freeze([self.row("D2-001", src, dst, files=0, bytes=0,
                                     cohort="D2_LEGACY_LAYOUT")])
        got = self.run_plan(j)
        self.assertEqual(got[0][1], dst)


class PriorLedgerGuards(Base):
    def test_prior_member_without_chain_flag_is_rejected(self):
        # 실제 저장소 원장 대신 tmpdir 원장을 만들어 소유권을 흉내낸다
        led_dir = os.path.join(self.tmp, "reports", "data_pallet_cleanup", "stage2a")
        os.makedirs(led_dir, exist_ok=True)
        led = os.path.join(led_dir, "move_transaction.jsonl")
        with open(led, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "move_id": "S2A001", "status": "MOVED",
                "source": "data/pallet/old", "destination": "data/pallet/_diag_a",
                "pre_hash_manifest": {"sizes": {"a.txt": 1}, "sha256": {"a.txt": "x"}},
            }) + "\n")
        self.make_item("data/pallet/_diag_a")
        owned = MPL.prior_ledger_members(
            self.tmp, ledger_rels=("reports/data_pallet_cleanup/stage2a/"
                                   "move_transaction.jsonl",))
        self.assertTrue(MPL.find_prior_ledger_conflict("data/pallet/_diag_a", owned))


class NoRegressionOnRealLedgers(unittest.TestCase):
    """실제 저장소 원장을 **읽기 전용**으로 본다. 아무것도 옮기지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.root = os.path.abspath(os.path.join(_DATA_PREP_DIR, "..", ".."))
        cls.rpt = os.path.join(cls.root, "reports", "data_pallet_cleanup")
        if not os.path.isdir(cls.rpt):
            raise unittest.SkipTest("로컬 저장소 원장이 없는 환경")

    def test_existing_policies_are_untouched(self):
        for name in ("stage2a-runs", "stage2b-active-assets", "stage2c2-final-layout",
                     "stage2d1-archive-finalization",
                     "stage2d11-residual-finalization", "stage2d12-final-moves"):
            self.assertIn(name, MPL.POLICIES)

    def test_stage2d2_policy_is_registered_and_requires_all_hash(self):
        p = MPL.get_policy(MPL.POLICY_STAGE2D2)
        self.assertEqual(p["require_hash_mode"], MPL.HASH_MODE_ALL)
        self.assertEqual(p["move_id_prefix"], "S2D2")

    def test_d2_ledgers_exist_and_are_all_moved(self):
        base = os.path.join(self.rpt, "stage2d2", "transactions")
        if not os.path.isdir(base):
            raise unittest.SkipTest("Stage 2-D2 원장이 아직 없음")
        total = 0
        for fn in sorted(os.listdir(base)):
            if not fn.endswith(".jsonl"):
                continue
            with open(os.path.join(base, fn), encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    if r.get("_meta"):
                        continue
                    total += 1
                    self.assertEqual(r["status"], "MOVED", r.get("d2_move_id"))
                    self.assertEqual(r["hash_mode"], MPL.HASH_MODE_ALL)
                    self.assertEqual(int(r["unhashed_file_count"]), 0)
        self.assertGreater(total, 0)

    def test_resolved_exclusion_is_recorded_not_deleted(self):
        # v2_dryrun_audit 재생성 함정을 해소했다는 사실이 코드에 남아 있어야 한다
        self.assertIn("data/pallet/v2_dryrun_audit", MPL.RESOLVED_EXCLUSIONS)


if __name__ == "__main__":
    unittest.main()
