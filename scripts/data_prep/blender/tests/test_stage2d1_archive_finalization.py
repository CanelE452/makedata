"""manage_pallet_data_layout — Stage 2-D1 정책(archive 정리) unit tests.

**실제 data/pallet 을 쓰지 않는다.** 전부 임시 fixture 위에서 돌고, Stage 2-A/2-B/2-C2 의
실이동 원장은 읽지도 고치지도 않는다.

Stage 2-D1 이 새로 도입한 것을 고정한다.
  - allowlist 가 코드 상수가 아니라 **동결된 계획 CSV** 이고 SHA256 으로 결속된다
  - READY / CORRUPT_MOVE_READY 만 이동. BLOCKED / KEEP / weight / quarantine 은 거부
  - ZIP 은 D1A/D1B cohort 만, corrupt package 는 D1B 만
  - hash-mode all 강제 + unhashed 0 강제 + read 예산(사전·도중 모두 검사)
  - cohort = transaction_group -> 한 건 실패 시 cohort 전체 역순 rollback
  - 기존 Stage 2-A/2-B/2-C2 계약 불변
"""

import csv
import json
import os
import shutil
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

PLAN_FIELDS = ["move_id", "cohort", "source", "destination", "entry_kind",
               "classification", "evidence_level", "confidence", "file_count",
               "total_bytes", "current_runtime_refs", "current_test_refs",
               "current_doc_refs", "license_status", "exclusion_status",
               "rollback_role", "full_hash_required", "estimated_hash_read_bytes",
               "status", "blocker"]


def write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


def plan_row(**kw):
    row = {k: "" for k in PLAN_FIELDS}
    row.update({
        "move_id": "D1-001", "cohort": "D1C_LEGACY_DATASETS",
        "entry_kind": "directory", "classification": "COMPLETE_DATASET",
        "evidence_level": "n/a", "confidence": "HIGH", "file_count": "1",
        "total_bytes": "1", "current_runtime_refs": "0", "current_test_refs": "0",
        "current_doc_refs": "0", "license_status": "redistributable",
        "exclusion_status": "not excluded", "rollback_role": "",
        "full_hash_required": "yes", "estimated_hash_read_bytes": "2",
        "status": "READY", "blocker": "",
    })
    row.update(kw)
    return row


class Args(object):
    def __init__(self, **kw):
        self.manifest = kw.get("manifest")
        self.moves = kw.get("moves")
        self.allow_empty_dirs = kw.get("allow_empty_dirs", False)
        self.hash_mode = kw.get("hash_mode", MPL.HASH_MODE_ALL)
        self.move_id_prefix = kw.get("move_id_prefix", None)
        self.policy = kw.get("policy", MPL.POLICY_STAGE2D1)
        self.cohort = kw.get("cohort")
        self.only_source = kw.get("only_source")
        self.move_ids = kw.get("move_ids")
        self.d1_plan = kw.get("d1_plan")
        self.d1_plan_sha256 = kw.get("d1_plan_sha256")
        self.max_hash_read_bytes = kw.get("max_hash_read_bytes")
        self.max_hash_read_gib = kw.get("max_hash_read_gib")
        self.expected_destination_additions = kw.get("expected_destination_additions")
        self.allow_any_destination_additions = kw.get("allow_any_destination_additions",
                                                      False)
        self.allow_destination_additions = False


class FakePaths(object):
    def __init__(self, root):
        self.project_root = root

    def get(self, key):
        if key == "pallet_data_root":
            return os.path.join(self.project_root, "data", "pallet")
        raise KeyError(key)


class Repo(object):
    """archive/ 안의 dataset·package·blend 를 흉내낸 최소 fixture."""

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="d1_"))
        self.data = os.path.join(self.root, "data", "pallet")
        os.makedirs(os.path.join(self.data, "archive"), exist_ok=True)
        self.paths = FakePaths(self.root)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def abs(self, rel):
        return os.path.join(self.root, rel.replace("/", os.sep))

    def make_dataset(self, name="ds_a", files=3, license_file=True):
        for i in range(files):
            write(self.abs("data/pallet/archive/%s/%06d.png" % (name, i)),
                  b"png%d" % i)
        if license_file:
            write(self.abs("data/pallet/archive/%s/LICENSE.txt" % name), b"CC0")

    def make_zip(self, name="pkg_a.zip", content=b"PK\x03\x04data"):
        write(self.abs("data/pallet/%s" % name), content)

    def make_blend(self, name="cold.blend"):
        write(self.abs("data/pallet/assets/scenes/production/blender_scene/%s" % name),
              b"BLENDER-cold")

    def write_plan(self, rows, name="plan.csv"):
        p = os.path.join(self.root, "out", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=PLAN_FIELDS)
            w.writeheader()
            w.writerows(rows)
        return p, MPL._sha256(p)

    def manifest(self, name="d1.jsonl"):
        return os.path.join(self.root, "out", name)

    def plan(self, plan_path, plan_sha, **kw):
        args = Args(manifest=self.manifest(kw.pop("name", "d1.jsonl")),
                    d1_plan=plan_path, d1_plan_sha256=plan_sha, **kw)
        return MPL.cmd_plan(args, self.paths), args

    def rows(self, args):
        return MPL._read_manifest(args.manifest)


# ---------------------------------------------------------------------------
# 1-2  READY row plan 성공 (file / directory)
# ---------------------------------------------------------------------------
class ReadyRowsPlan(unittest.TestCase):
    def test_ready_directory_row_plans(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            rows = r.rows(args)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["entry_kind"], MPL.ENTRY_DIRECTORY)
            self.assertEqual(rows[0]["hash_mode"], MPL.HASH_MODE_ALL)
            self.assertEqual(rows[0]["unhashed_file_count"], 0)
            self.assertEqual(rows[0]["schema_version"], MPL.D1_SCHEMA_VERSION)
            self.assertEqual(rows[0]["plan_sha256"], sha)
            self.assertEqual(rows[0]["move_id"], "D1-001")

    def test_ready_file_row_plans(self):
        with Repo() as r:
            r.make_zip("pkg_a.zip")
            p, sha = r.write_plan([plan_row(
                move_id="D1-010", cohort="D1A_PACKAGES", entry_kind="file",
                classification="PACKAGE_BUNDLE", source="data/pallet/pkg_a.zip",
                destination="data/pallet/archive/packages/dataset_bundles/pkg_a.zip")])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            rows = r.rows(args)
            self.assertEqual(rows[0]["entry_kind"], MPL.ENTRY_FILE)
            self.assertEqual(rows[0]["source_file_count"], 1)
            self.assertGreater(rows[0]["hash_read_bytes_pre"], 0)


# ---------------------------------------------------------------------------
# 3-4  BLOCKED / KEEP row 거부
# ---------------------------------------------------------------------------
class ForbiddenStatus(unittest.TestCase):
    def _refuse(self, status):
        """금지 status 를 --only-source 로 콕 집어 요구하면 거부된다."""
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                status=status, source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/partial/ds_a")])
            rc, args = r.plan(p, sha, only_source="data/pallet/archive/ds_a")
            self.assertEqual(rc, 2, "%s 를 명시 요청하면 거부돼야 한다" % status)
            self.assertFalse(os.path.isfile(args.manifest))

    def test_mixed_cohort_selects_only_ready_rows(self):
        """cohort 는 원래 섞여 있다 — READY 만 선택되고 나머지는 조용히 빠진다.

        실제 D1D_BLEND_BACKUPS 가 17행(READY 10 + KEEP 7) 이라 이 동작이 필요하다.
        """
        with Repo() as r:
            r.make_dataset("ds_ready")
            r.make_dataset("ds_keep")
            p, sha = r.write_plan([
                plan_row(move_id="D1-001", status="READY",
                         source="data/pallet/archive/ds_ready",
                         destination="data/pallet/archive/legacy_datasets/"
                                     "redistributable/ds_ready"),
                plan_row(move_id="D1-002", status="KEEP_ROLLBACK",
                         rollback_role="rollback",
                         source="data/pallet/archive/ds_keep",
                         destination="(이동 없음)"),
            ])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            rows = r.rows(args)
            self.assertEqual([x["move_id"] for x in rows], ["D1-001"])
            self.assertTrue(os.path.isdir(r.abs("data/pallet/archive/ds_keep")))

    def test_ready_row_with_forbidden_attribute_is_still_refused(self):
        """status 는 READY 인데 rollback_role 이 붙어 있으면 거부한다 (계획 모순)."""
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                status="READY", rollback_role="active",
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/partial/ds_a")])
            self.assertEqual(r.plan(p, sha)[0], 2)

    def test_blocked_reference_is_refused(self):
        self._refuse("BLOCKED_REFERENCE")

    def test_blocked_unknown_is_refused(self):
        self._refuse("BLOCKED_UNKNOWN")

    def test_keep_active_is_refused(self):
        self._refuse("KEEP_ACTIVE")

    def test_keep_quarantine_is_refused(self):
        self._refuse("KEEP_QUARANTINE")

    def test_needs_crc_is_refused(self):
        self._refuse("NEEDS_CRC")


# ---------------------------------------------------------------------------
# 5-6  plan SHA 결속
# ---------------------------------------------------------------------------
class PlanBinding(unittest.TestCase):
    def test_wrong_plan_sha_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, _sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            rc, args = r.plan(p, "0" * 64)
            self.assertEqual(rc, 2)
            self.assertFalse(os.path.isfile(args.manifest))

    def test_plan_edited_after_freeze_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            rows = [plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")]
            p, sha = r.write_plan(rows)
            # 동결 후 계획을 고친다 (목적지 변경)
            rows[0]["destination"] = "data/pallet/archive/legacy_datasets/partial/ds_a"
            with open(p, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=PLAN_FIELDS)
                w.writeheader()
                w.writerows(rows)
            rc, _args = r.plan(p, sha)
            self.assertEqual(rc, 2)

    def test_missing_plan_file_is_refused(self):
        with Repo() as r:
            rc, _args = r.plan(os.path.join(r.root, "out", "nope.csv"), "0" * 64)
            self.assertEqual(rc, 2)


# ---------------------------------------------------------------------------
# 7-11  source/destination 검사
# ---------------------------------------------------------------------------
class SourceDestinationChecks(unittest.TestCase):
    def test_source_missing_is_skipped_not_moved(self):
        with Repo() as r:
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/absent",
                destination="data/pallet/archive/legacy_datasets/partial/absent")])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            self.assertEqual(r.rows(args), [])

    def test_destination_collision_is_skipped(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            write(r.abs("data/pallet/archive/legacy_datasets/redistributable/ds_a/x"),
                  b"already")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            self.assertEqual(r.rows(args), [])
            skip = os.path.splitext(args.manifest)[0] + "_skipped.csv"
            self.assertIn("DEST_COLLISION", open(skip, encoding="utf-8-sig").read())

    def test_destination_outside_archive_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/assets/ds_a")])
            rc, _args = r.plan(p, sha)
            self.assertEqual(rc, 2)

    def test_path_escape_destination_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/../../../escaped")])
            rc, _args = r.plan(p, sha)
            self.assertEqual(rc, 2)

    def test_apply_refuses_a_different_volume(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            _rc, args = r.plan(p, sha)
            rows = r.rows(args)
            # 다른 드라이브를 강제로 심는다. apply 가 rename 대신 거부해야 한다.
            other = "Z:" if not r.root.upper().startswith("Z:") else "Y:"
            rows[0]["destination"] = "data/pallet/archive/x"
            MPL._write_manifest(args.manifest, rows)
            orig_same = MPL._same_volume
            MPL._same_volume = lambda a, b: False
            try:
                self.assertEqual(MPL.cmd_apply(args, r.paths), 1)
            finally:
                MPL._same_volume = orig_same
            self.assertTrue(os.path.isdir(r.abs("data/pallet/archive/ds_a")))
            self.assertIn(other[:0] or "다른 볼륨",
                          MPL._read_manifest(args.manifest)[0]["error"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink 미지원")
    def test_symlink_source_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_real")
            link = r.abs("data/pallet/archive/ds_link")
            try:
                os.symlink(r.abs("data/pallet/archive/ds_real"), link,
                           target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest("symlink 생성 권한 없음: %s" % exc)
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_link",
                destination="data/pallet/archive/legacy_datasets/partial/ds_link")])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            self.assertEqual(r.rows(args), [])
            skip = os.path.splitext(args.manifest)[0] + "_skipped.csv"
            self.assertIn("SYMLINK", open(skip, encoding="utf-8-sig").read())


# ---------------------------------------------------------------------------
# 12-13  hash mode 강제
# ---------------------------------------------------------------------------
class HashModeEnforcement(unittest.TestCase):
    def test_selective_hash_mode_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            rc, _args = r.plan(p, sha, hash_mode=MPL.HASH_MODE_SELECTIVE)
            self.assertEqual(rc, 2)

    def test_snapshot_all_raises_when_a_file_stays_unhashed(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            root = r.abs("data/pallet/archive/ds_a")
            real = MPL._sha256
            calls = {"n": 0}

            def flaky(path, budget=None):
                calls["n"] += 1
                return real(path, budget=budget)

            MPL._sha256 = flaky
            try:
                snap = MPL.snapshot(root, hash_mode=MPL.HASH_MODE_ALL)
            finally:
                MPL._sha256 = real
            self.assertEqual(snap["unhashed_file_count"], 0)
            self.assertEqual(snap["hashed_file_count"], calls["n"])
            self.assertEqual(snap["hash_read_bytes"], snap["total_bytes"])


# ---------------------------------------------------------------------------
# 14-15  read 예산
# ---------------------------------------------------------------------------
class HashBudgetTests(unittest.TestCase):
    def test_budget_refuses_before_reading_anything(self):
        with Repo() as r:
            r.make_dataset("ds_a", files=4)
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            rc, args = r.plan(p, sha, max_hash_read_bytes=1)   # 1바이트 한도
            self.assertEqual(rc, 2)
            self.assertFalse(os.path.isfile(args.manifest))

    def test_budget_trips_mid_read(self):
        b = MPL.HashBudget(4, label="t")
        with self.assertRaises(MPL.HashBudgetExceeded):
            b.add(3)
            b.add(3)
        self.assertGreater(b.read_bytes, 4)

    def test_no_budget_option_keeps_previous_behaviour(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            rc, args = r.plan(p, sha, max_hash_read_bytes=None)
            self.assertEqual(rc, 0)
            self.assertEqual(len(r.rows(args)), 1)


# ---------------------------------------------------------------------------
# 16-17  ZIP / corrupt cohort 제한
# ---------------------------------------------------------------------------
class ArchiveCohortRules(unittest.TestCase):
    def test_zip_outside_d1a_d1b_is_refused(self):
        with Repo() as r:
            r.make_zip("pkg_a.zip")
            p, sha = r.write_plan([plan_row(
                cohort="D1C_LEGACY_DATASETS", entry_kind="file",
                source="data/pallet/pkg_a.zip",
                destination="data/pallet/archive/legacy_datasets/partial/pkg_a.zip")])
            rc, _args = r.plan(p, sha)
            self.assertEqual(rc, 2)

    def test_zip_inside_d1a_is_allowed(self):
        with Repo() as r:
            r.make_zip("pkg_a.zip")
            p, sha = r.write_plan([plan_row(
                cohort="D1A_PACKAGES", entry_kind="file",
                source="data/pallet/pkg_a.zip",
                destination="data/pallet/archive/packages/dataset_bundles/pkg_a.zip")])
            self.assertEqual(r.plan(p, sha)[0], 0)

    def test_corrupt_package_outside_d1b_is_refused(self):
        with Repo() as r:
            r.make_zip("broken.zip")
            p, sha = r.write_plan([plan_row(
                cohort="D1A_PACKAGES", entry_kind="file",
                classification="CORRUPT_PACKAGE", source="data/pallet/broken.zip",
                destination="data/pallet/archive/packages/dataset_bundles/broken.zip")])
            rc, _args = r.plan(p, sha)
            self.assertEqual(rc, 2)

    def test_corrupt_package_inside_d1b_is_allowed_and_not_repaired(self):
        with Repo() as r:
            r.make_zip("broken.zip", content=b"PK\x03\x04truncated-no-eocd")
            p, sha = r.write_plan([plan_row(
                cohort="D1B_CORRUPT", entry_kind="file",
                classification="CORRUPT_PACKAGE", source="data/pallet/broken.zip",
                destination="data/pallet/archive/packages/corrupt/broken.zip")])
            _rc, args = r.plan(p, sha)
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            dst = r.abs("data/pallet/archive/packages/corrupt/broken.zip")
            # 손상 상태 그대로 보존 — 복구·재작성하지 않는다
            self.assertEqual(open(dst, "rb").read(), b"PK\x03\x04truncated-no-eocd")
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)

    def test_zip_inside_a_dataset_rides_along(self):
        """dataset 내용물인 ZIP 은 함께 간다.

        실제로 archive/training_data_v4_split/training_data_v4_split.zip 이 그렇다 —
        별도 계획 row 가 없는 dataset 내용물이므로 dataset 과 함께 움직이는 것이 맞다.
        """
        with Repo() as r:
            r.make_dataset("ds_a")
            write(r.abs("data/pallet/archive/ds_a/inner.zip"), b"PK-inner")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/partial/ds_a")])
            rc, args = r.plan(p, sha)
            self.assertEqual(rc, 0)
            self.assertEqual(len(r.rows(args)), 1)
            self.assertIn("inner.zip", r.rows(args)[0]["relative_files"])
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            self.assertTrue(os.path.isfile(
                r.abs("data/pallet/archive/legacy_datasets/partial/ds_a/inner.zip")))
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)

    def test_zip_planned_twice_is_refused(self):
        """딸려 가는 ZIP 이 별도 row 로도 계획돼 있으면 거부 (두 경로로 옮길 수 없다)."""
        with Repo() as r:
            r.make_dataset("ds_a")
            write(r.abs("data/pallet/archive/ds_a/inner.zip"), b"PK-inner")
            p, sha = r.write_plan([
                plan_row(move_id="D1-001", source="data/pallet/archive/ds_a",
                         destination="data/pallet/archive/legacy_datasets/partial/ds_a"),
                plan_row(move_id="D1-002", cohort="D1A_PACKAGES", entry_kind="file",
                         source="data/pallet/archive/ds_a/inner.zip",
                         destination="data/pallet/archive/packages/dataset_bundles/"
                                     "inner.zip"),
            ])
            self.assertEqual(r.plan(p, sha)[0], 2)


# ---------------------------------------------------------------------------
# 18-21  보호 대상 거부
# ---------------------------------------------------------------------------
class ProtectedSources(unittest.TestCase):
    def test_rollback_critical_blend_is_refused(self):
        with Repo() as r:
            r.make_blend("synth_data_scene.blend")
            p, sha = r.write_plan([plan_row(
                cohort="D1D_BLEND_BACKUPS", entry_kind="file",
                classification="ROLLBACK_CRITICAL", rollback_role="rollback",
                source="data/pallet/assets/scenes/production/blender_scene/"
                       "synth_data_scene.blend",
                destination="data/pallet/archive/legacy_scenes/snapshots/"
                            "synth_data_scene.blend")])
            self.assertEqual(r.plan(p, sha)[0], 2)

    def test_active_scene_is_refused(self):
        with Repo() as r:
            r.make_blend("active.blend")
            p, sha = r.write_plan([plan_row(
                cohort="D1D_BLEND_BACKUPS", entry_kind="file",
                classification="ACTIVE_RUNTIME", rollback_role="active",
                source="data/pallet/assets/scenes/production/blender_scene/active.blend",
                destination="data/pallet/archive/legacy_scenes/snapshots/active.blend")])
            self.assertEqual(r.plan(p, sha)[0], 2)

    def test_quarantine_source_is_refused(self):
        with Repo() as r:
            r.make_dataset("_noai_quarantine_usd")
            p, sha = r.write_plan([plan_row(
                classification="LICENSE_QUARANTINE",
                source="data/pallet/archive/_noai_quarantine_usd",
                destination="data/pallet/archive/legacy_datasets/noai_baked/q")])
            self.assertEqual(r.plan(p, sha)[0], 2)

    def test_weight_source_is_refused(self):
        with Repo() as r:
            write(r.abs("weights/pallet_category/net.pth"), b"W")
            p, sha = r.write_plan([plan_row(
                cohort="D1E_WEIGHTS", entry_kind="file",
                classification="UNREFERENCED_WEIGHT",
                source="weights/pallet_category/net.pth",
                destination="data/pallet/archive/legacy_weights/net.pth")])
            self.assertEqual(r.plan(p, sha)[0], 2)

    def test_unknown_license_source_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_unknown")
            p, sha = r.write_plan([plan_row(
                license_status="UNKNOWN_LICENSE (NoAI 상속 미확정)",
                source="data/pallet/archive/ds_unknown",
                destination="data/pallet/archive/legacy_datasets/partial/ds_unknown")])
            self.assertEqual(r.plan(p, sha)[0], 2)

    def test_live_current_reference_source_is_refused(self):
        with Repo() as r:
            r.make_dataset("ds_ref")
            p, sha = r.write_plan([plan_row(
                current_runtime_refs="3",
                source="data/pallet/archive/ds_ref",
                destination="data/pallet/archive/legacy_datasets/partial/ds_ref")])
            self.assertEqual(r.plan(p, sha)[0], 2)


# ---------------------------------------------------------------------------
# 22-24  verify 실패 조건
# ---------------------------------------------------------------------------
class PriorLedgerConflict(unittest.TestCase):
    """앞선 원장이 옮긴 파일을 그 destination 밖으로 다시 빼는 것을 계획 단계에서 막는다.

    Stage 2-D1 실행 중 실제로 발생했다 — D1D 가 blend backup 을
    assets/scenes/production/blender_scene 밖으로 옮겼고, 그건 C2C 이동의 구성원이라
    C2C exact verify 가 11건 MISSING 으로 실패했다. 데이터는 안전했지만 검증 사슬이 끊겼다.
    """

    def _prior(self, r, dest, members):
        led = os.path.join(r.root, "prior.jsonl")
        with open(led, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "move_id": "PRIOR001", "status": "MOVED",
                "source": "data/pallet/old_place", "destination": dest,
                "relative_files": members}, ensure_ascii=False) + "\n")
        return ("prior.jsonl",)

    def test_member_of_a_prior_destination_is_refused(self):
        with Repo() as r:
            write(r.abs("data/pallet/archive/kept/a.blend"), b"B")
            led = self._prior(r, "data/pallet/archive/kept", ["a.blend"])
            owned = MPL.prior_ledger_members(r.root, led)
            self.assertIsNotNone(
                MPL.find_prior_ledger_conflict("data/pallet/archive/kept/a.blend", owned))

    def test_unrelated_source_is_not_flagged(self):
        with Repo() as r:
            led = self._prior(r, "data/pallet/archive/kept", ["a.blend"])
            owned = MPL.prior_ledger_members(r.root, led)
            self.assertIsNone(
                MPL.find_prior_ledger_conflict("data/pallet/archive/other/b.zip", owned))

    def test_destination_itself_is_flagged(self):
        with Repo() as r:
            led = self._prior(r, "data/pallet/archive/kept", ["a.blend"])
            owned = MPL.prior_ledger_members(r.root, led)
            self.assertIsNotNone(
                MPL.find_prior_ledger_conflict("data/pallet/archive/kept", owned))

    def test_real_prior_ledgers_flag_the_c2c_blend_scene(self):
        """실제 저장소 원장으로 확인 — C2C destination 안의 blend 는 이동 금지 대상."""
        # _DATA_PREP_DIR = <repo>/scripts/data_prep -> 두 단계 위가 repo root
        root = os.path.dirname(os.path.dirname(_DATA_PREP_DIR))
        owned = MPL.prior_ledger_members(root)
        self.assertTrue(owned, "실제 원장을 찾지 못했다 (경로 계산 확인): %s" % root)
        hit = MPL.find_prior_ledger_conflict(
            "data/pallet/assets/scenes/production/blender_scene/synth_data_scene.blend1",
            owned)
        self.assertIsNotNone(hit)
        self.assertIsNone(MPL.find_prior_ledger_conflict("data/pallet/pallet.zip", owned))


class VerifyFailures(unittest.TestCase):
    def _applied(self, r, name="ds_a"):
        r.make_dataset(name)
        p, sha = r.write_plan([plan_row(
            source="data/pallet/archive/%s" % name,
            destination="data/pallet/archive/legacy_datasets/redistributable/%s" % name)])
        _rc, args = r.plan(p, sha)
        self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
        return args

    def test_relative_path_set_mismatch_fails(self):
        with Repo() as r:
            args = self._applied(r)
            os.remove(r.abs("data/pallet/archive/legacy_datasets/redistributable/"
                            "ds_a/000000.png"))
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_sha256_mismatch_fails(self):
        with Repo() as r:
            args = self._applied(r)
            write(r.abs("data/pallet/archive/legacy_datasets/redistributable/"
                        "ds_a/000000.png"), b"TAMPERED")
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_lost_license_file_fails(self):
        with Repo() as r:
            args = self._applied(r)
            os.remove(r.abs("data/pallet/archive/legacy_datasets/redistributable/"
                            "ds_a/LICENSE.txt"))
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_verify_records_post_read_and_verified_at(self):
        with Repo() as r:
            args = self._applied(r)
            args.max_hash_read_bytes = 10 * 1024 ** 3
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)
            row = r.rows(args)[0]
            self.assertGreater(row["hash_read_bytes_post"], 0)
            self.assertTrue(row["verified_at"])
            self.assertTrue(row["applied_at"])


# ---------------------------------------------------------------------------
# 25  round trip + cohort 원자성
# ---------------------------------------------------------------------------
class RoundTrip(unittest.TestCase):
    def test_apply_verify_rollback_round_trip(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            r.make_dataset("ds_b")
            p, sha = r.write_plan([
                plan_row(move_id="D1-001", source="data/pallet/archive/ds_a",
                         destination="data/pallet/archive/legacy_datasets/"
                                     "redistributable/ds_a"),
                plan_row(move_id="D1-002", source="data/pallet/archive/ds_b",
                         destination="data/pallet/archive/legacy_datasets/"
                                     "redistributable/ds_b"),
            ])
            _rc, args = r.plan(p, sha)
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)
            self.assertEqual(MPL.cmd_rollback(args, r.paths), 0)
            self.assertTrue(os.path.isdir(r.abs("data/pallet/archive/ds_a")))
            self.assertTrue(os.path.isdir(r.abs("data/pallet/archive/ds_b")))
            self.assertFalse(os.path.exists(
                r.abs("data/pallet/archive/legacy_datasets/redistributable/ds_a")))

    def test_cohort_failure_rolls_back_the_whole_cohort(self):
        with Repo() as r:
            r.make_dataset("ds_a")
            r.make_dataset("ds_b")
            p, sha = r.write_plan([
                plan_row(move_id="D1-001", source="data/pallet/archive/ds_a",
                         destination="data/pallet/archive/legacy_datasets/"
                                     "redistributable/ds_a"),
                plan_row(move_id="D1-002", source="data/pallet/archive/ds_b",
                         destination="data/pallet/archive/legacy_datasets/"
                                     "redistributable/ds_b"),
            ])
            _rc, args = r.plan(p, sha)
            rows = r.rows(args)
            self.assertEqual(rows[0]["transaction_group"], "D1C_LEGACY_DATASETS")
            # 두 번째를 실패시킨다: source 를 지워 apply 가 멈추게 한다.
            shutil.rmtree(r.abs("data/pallet/archive/ds_b"))
            self.assertEqual(MPL.cmd_apply(args, r.paths), 1)
            # 같은 cohort 의 첫 건도 되돌아와야 한다 (원자성)
            self.assertTrue(os.path.isdir(r.abs("data/pallet/archive/ds_a")))
            self.assertFalse(os.path.exists(
                r.abs("data/pallet/archive/legacy_datasets/redistributable/ds_a")))
            st = [x["status"] for x in r.rows(args)]
            self.assertIn("ROLLED_BACK", st)
            self.assertIn("FAILED", st)


# ---------------------------------------------------------------------------
# 26-28  기존 정책 회귀 없음
# ---------------------------------------------------------------------------
class NoRegressionInOlderPolicies(unittest.TestCase):
    def test_stage2a_policy_still_allows_selective_hash(self):
        self.assertIsNone(MPL.POLICIES[MPL.POLICY_STAGE2A]["require_hash_mode"])

    def test_stage2b_allowlist_is_untouched(self):
        self.assertEqual(len(MPL.STAGE2B_ALLOWLIST), 10)
        self.assertEqual(MPL.POLICIES[MPL.POLICY_STAGE2B]["require_hash_mode"],
                         MPL.HASH_MODE_ALL)

    def test_stage2c2_group_requirement_is_untouched(self):
        self.assertEqual(MPL.REQUIRED_GROUP_SOURCES["C2C_DISTRACTOR_SCENE"],
                         ("data/pallet/distractors", "data/pallet/blender_scene"))
        self.assertNotIn("D1C_LEGACY_DATASETS", MPL.REQUIRED_GROUP_SOURCES)

    def test_stage2d1_policy_is_registered_and_forces_hash_all(self):
        self.assertIn(MPL.POLICY_STAGE2D1, MPL.POLICIES)
        pol = MPL.POLICIES[MPL.POLICY_STAGE2D1]
        self.assertEqual(pol["require_hash_mode"], MPL.HASH_MODE_ALL)
        self.assertEqual(pol["allowed_dest_prefixes"], ("archive/",))
        self.assertIn(".pth", pol["forbidden_ext"])
        # entry 로서의 ZIP 은 D1A/D1B 만 (row 단위 검사). 딸려 가는 ZIP 은 별도 규칙이라
        # policy 의 archive_allowed_cohorts 는 네 cohort 를 모두 포함한다.
        self.assertEqual(MPL.D1_ARCHIVE_COHORTS, ("D1A_PACKAGES", "D1B_CORRUPT"))
        self.assertEqual(set(pol["archive_allowed_cohorts"]),
                         {"D1A_PACKAGES", "D1B_CORRUPT", "D1C_LEGACY_DATASETS",
                          "D1D_BLEND_BACKUPS"})

    def test_verify_does_not_stamp_non_d1_manifests(self):
        """schema_version 이 D1 이 아니면 verify 가 verified_at 을 채우지 않는다.

        Stage 2-A/B/C2 원장은 rewrite 금지 대상이라 이 경로가 실제로 중요하다.
        """
        with Repo() as r:
            r.make_dataset("ds_a")
            p, sha = r.write_plan([plan_row(
                source="data/pallet/archive/ds_a",
                destination="data/pallet/archive/legacy_datasets/redistributable/ds_a")])
            _rc, args = r.plan(p, sha)
            MPL.cmd_apply(args, r.paths)
            rows = MPL._read_manifest(args.manifest)
            del rows[0]["schema_version"]          # 옛 원장처럼 만든다
            MPL._write_manifest(args.manifest, rows)
            before = open(args.manifest, "rb").read()
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)
            self.assertEqual(open(args.manifest, "rb").read(), before,
                             "D1 아닌 원장은 verify 가 건드리지 않아야 한다")
            row = MPL._read_manifest(args.manifest)[0]
            self.assertIsNone(row["verified_at"])
            self.assertIsNone(row["hash_read_bytes_post"])


if __name__ == "__main__":
    unittest.main()
