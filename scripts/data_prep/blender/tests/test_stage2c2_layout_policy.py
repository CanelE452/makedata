"""manage_pallet_data_layout — Stage 2-C2 정책(file entry + transaction group) unit tests.

**실제 data/pallet 을 쓰지 않는다.** 전부 임시 fixture 위에서 돌고, Stage 2-A/2-B 의 실이동
원장은 읽지도 고치지도 않는다.

Stage 2-C2 가 새로 도입한 것만 고정한다.
  - file entry (background 안의 원본 ZIP 을 파일 단위로 분리)
  - transaction_group 원자성 (distractors + blender_scene 은 함께 가거나 함께 남는다)
  - ZIP 은 C2A cohort 에서만 허용, directory cohort 에 남아 있으면 계획 거부
  - hash-mode all 강제, unhashed 0
  - 기존 Stage 2-A 계약(실패하면 그 자리에서 멈추고 이미 옮긴 것은 둔다) 불변
"""

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


def write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


class Args(object):
    def __init__(self, **kw):
        self.manifest = kw.get("manifest")
        self.moves = kw.get("moves")
        self.allow_empty_dirs = kw.get("allow_empty_dirs", False)
        self.hash_mode = kw.get("hash_mode", MPL.HASH_MODE_ALL)
        self.move_id_prefix = kw.get("move_id_prefix", "TST")
        self.policy = kw.get("policy", MPL.POLICY_STAGE2C2)
        self.cohort = kw.get("cohort")
        self.only_source = kw.get("only_source")


class FakePaths(object):
    def __init__(self, root):
        self.project_root = root

    def get(self, key):
        if key == "pallet_data_root":
            return os.path.join(self.project_root, "data", "pallet")
        raise KeyError(key)


class Repo(object):
    """background / distractors / blender_scene 를 흉내낸 최소 fixture."""

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="c2_"))
        self.data = os.path.join(self.root, "data", "pallet")
        os.makedirs(self.data, exist_ok=True)
        self.paths = FakePaths(self.root)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def abs(self, rel):
        return os.path.join(self.root, rel.replace("/", os.sep))

    def make_background(self, with_zip=True):
        write(self.abs("data/pallet/background/parking_lot/scene.gltf"), b"{}")
        write(self.abs("data/pallet/background/parking_lot/scene.bin"), b"bin")
        write(self.abs("data/pallet/background/parking_lot/license.txt"), b"CC0")
        write(self.abs("data/pallet/background/parking_lot/textures/t.png"), b"png")
        if with_zip:
            write(self.abs("data/pallet/background/parking_lot.zip"), b"PK-a")
            write(self.abs("data/pallet/background/sub/other.zip"), b"PK-b")

    def make_distractors(self):
        write(self.abs("data/pallet/distractors/distractors_manifest.csv"), b"name\na\n")
        write(self.abs("data/pallet/distractors/large/LICENSE.txt"), b"CC0")
        write(self.abs("data/pallet/distractors/large/m/a.gltf"), b"{}")

    def make_scene(self):
        write(self.abs("data/pallet/blender_scene/synth.blend"), b"BLEND")
        write(self.abs("data/pallet/blender_scene/textures/x.png"), b"png")

    def manifest(self, name="c2.jsonl"):
        return os.path.join(self.root, "out", name)

    def plan(self, **kw):
        args = Args(manifest=self.manifest(kw.pop("name", "c2.jsonl")), **kw)
        return MPL.cmd_plan(args, self.paths), args

    def rows(self, args):
        return MPL._read_manifest(args.manifest)


class PolicyShape(unittest.TestCase):
    def test_policy_is_registered(self):
        self.assertIn(MPL.POLICY_STAGE2C2, MPL.POLICIES)

    def test_policy_requires_hash_mode_all(self):
        self.assertEqual(MPL.POLICIES[MPL.POLICY_STAGE2C2]["require_hash_mode"],
                         MPL.HASH_MODE_ALL)

    def test_policy_forbids_weights_and_checkpoints(self):
        forbidden = MPL.POLICIES[MPL.POLICY_STAGE2C2]["forbidden_ext"]
        for ext in (".pt", ".pth", ".ckpt", ".onnx", ".safetensors"):
            self.assertIn(ext, forbidden)

    def test_allowlist_destinations_are_exact(self):
        dests = {d for _s, d, _c, _k, _g in MPL.STAGE2C2_ALLOWLIST}
        self.assertEqual(dests, {
            "data/pallet/assets/scenes/backgrounds/background",
            "data/pallet/assets/distractors/library",
            "data/pallet/assets/scenes/production/blender_scene",
        })

    def test_distractors_and_scene_share_one_transaction_group(self):
        groups = {s: g for s, _d, _c, _k, g in MPL.STAGE2C2_ALLOWLIST}
        self.assertEqual(groups["data/pallet/distractors"],
                         groups["data/pallet/blender_scene"])

    def test_group_requirement_names_both_sources(self):
        self.assertEqual(set(MPL.REQUIRED_GROUP_SOURCES["C2C_DISTRACTOR_SCENE"]),
                         {"data/pallet/distractors", "data/pallet/blender_scene"})


class FileEntry(unittest.TestCase):
    def test_snapshot_file_hashes_the_single_file(self):
        with Repo() as r:
            p = r.abs("data/pallet/background/parking_lot.zip")
            write(p, b"PK-a")
            snap = MPL.snapshot_file(p)
            self.assertEqual(snap["file_count"], 1)
            self.assertEqual(snap["unhashed_file_count"], 0)
            self.assertEqual(list(snap["sha256"]), ["parking_lot.zip"])

    def test_snapshot_file_rejects_selective_hash_mode(self):
        with Repo() as r:
            p = r.abs("data/pallet/background/a.zip")
            write(p)
            with self.assertRaises(ValueError):
                MPL.snapshot_file(p, hash_mode=MPL.HASH_MODE_SELECTIVE)

    def test_precheck_file_accepts_a_plain_file(self):
        with Repo() as r:
            src = r.abs("data/pallet/background/a.zip")
            write(src)
            problems, stats = MPL.precheck_file(
                src, r.abs("data/pallet/archive/packages/background_sources/a.zip"),
                r.paths.get("pallet_data_root"), MPL.POLICIES[MPL.POLICY_STAGE2C2])
            self.assertEqual(problems, [])
            self.assertEqual(stats["file_count"], 1)

    def test_precheck_file_rejects_a_directory(self):
        with Repo() as r:
            os.makedirs(r.abs("data/pallet/background/dir"))
            problems, _ = MPL.precheck_file(
                r.abs("data/pallet/background/dir"),
                r.abs("data/pallet/archive/packages/background_sources/dir"),
                r.paths.get("pallet_data_root"), MPL.POLICIES[MPL.POLICY_STAGE2C2])
            self.assertIn("SOURCE_NOT_A_FILE", problems)

    def test_precheck_file_rejects_destination_collision(self):
        with Repo() as r:
            src = r.abs("data/pallet/background/a.zip")
            dst = r.abs("data/pallet/archive/packages/background_sources/a.zip")
            write(src); write(dst)
            problems, _ = MPL.precheck_file(src, dst, r.paths.get("pallet_data_root"),
                                            MPL.POLICIES[MPL.POLICY_STAGE2C2])
            self.assertIn("DEST_COLLISION", problems)

    def test_archive_scan_finds_nested_archives(self):
        with Repo() as r:
            r.make_background(with_zip=True)
            found = MPL.archive_files_under(r.abs("data/pallet/background"))
            self.assertEqual(found, ["parking_lot.zip", "sub/other.zip"])

    def test_archive_scan_is_empty_without_archives(self):
        with Repo() as r:
            r.make_background(with_zip=False)
            self.assertEqual(MPL.archive_files_under(r.abs("data/pallet/background")), [])


class C2APackages(unittest.TestCase):
    def test_plan_preserves_the_relative_path_instead_of_flattening(self):
        with Repo() as r:
            r.make_background()
            rc, args = r.plan(cohort="C2A_BACKGROUND_PACKAGES")
            self.assertEqual(rc, 0)
            rows = r.rows(args)
            dests = sorted(x["destination"] for x in rows)
            self.assertEqual(dests, [
                "data/pallet/archive/packages/background_sources/parking_lot.zip",
                "data/pallet/archive/packages/background_sources/sub/other.zip",
            ])

    def test_plan_marks_them_as_file_entries_with_hash_all(self):
        with Repo() as r:
            r.make_background()
            _rc, args = r.plan(cohort="C2A_BACKGROUND_PACKAGES")
            for row in r.rows(args):
                self.assertEqual(row["entry_kind"], MPL.ENTRY_FILE)
                self.assertEqual(row["hash_mode"], MPL.HASH_MODE_ALL)
                self.assertEqual(row["unhashed_file_count"], 0)

    def test_apply_and_verify_a_file_entry(self):
        with Repo() as r:
            r.make_background()
            _rc, args = r.plan(cohort="C2A_BACKGROUND_PACKAGES")
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            self.assertFalse(os.path.exists(r.abs("data/pallet/background/parking_lot.zip")))
            self.assertTrue(os.path.isfile(
                r.abs("data/pallet/archive/packages/background_sources/parking_lot.zip")))
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)

    def test_rollback_restores_a_file_entry_to_its_original_relative_path(self):
        with Repo() as r:
            r.make_background()
            _rc, args = r.plan(cohort="C2A_BACKGROUND_PACKAGES")
            MPL.cmd_apply(args, r.paths)
            self.assertEqual(MPL.cmd_rollback(args, r.paths), 0)
            self.assertTrue(os.path.isfile(r.abs("data/pallet/background/parking_lot.zip")))
            self.assertTrue(os.path.isfile(r.abs("data/pallet/background/sub/other.zip")))

    def test_verify_fails_when_the_moved_file_is_altered(self):
        with Repo() as r:
            r.make_background()
            _rc, args = r.plan(cohort="C2A_BACKGROUND_PACKAGES")
            MPL.cmd_apply(args, r.paths)
            write(r.abs("data/pallet/archive/packages/background_sources/parking_lot.zip"),
                  b"TAMPERED")
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)


class ArchiveOnlyInPackageCohort(unittest.TestCase):
    def test_background_directory_plan_is_refused_while_a_zip_remains(self):
        with Repo() as r:
            r.make_background(with_zip=True)
            _rc, args = r.plan(cohort="C2B_BACKGROUND_ASSET", name="b.jsonl")
            self.assertEqual(r.rows(args), [])
            skipped = open(os.path.splitext(args.manifest)[0] + "_skipped.csv",
                           encoding="utf-8-sig").read()
            self.assertIn("ARCHIVE_IN_NON_PACKAGE_COHORT", skipped)

    def test_background_directory_plan_passes_once_the_zips_are_gone(self):
        with Repo() as r:
            r.make_background(with_zip=True)
            _rc, a = r.plan(cohort="C2A_BACKGROUND_PACKAGES", name="a.jsonl")
            MPL.cmd_apply(a, r.paths)
            _rc, b = r.plan(cohort="C2B_BACKGROUND_ASSET", name="b.jsonl")
            rows = r.rows(b)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["destination"],
                             "data/pallet/assets/scenes/backgrounds/background")
            self.assertEqual(rows[0]["entry_kind"], MPL.ENTRY_DIRECTORY)


class C2CGroupAtomicity(unittest.TestCase):
    def test_plan_refuses_when_only_one_group_source_exists(self):
        with Repo() as r:
            r.make_distractors()          # blender_scene 없음
            rc, _args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            self.assertEqual(rc, 2)

    def test_plan_accepts_when_both_group_sources_exist(self):
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            rc, args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            self.assertEqual(rc, 0)
            rows = r.rows(args)
            self.assertEqual(len(rows), 2)
            self.assertEqual({x["transaction_group"] for x in rows}, {"C2C_DISTRACTOR_SCENE"})

    def test_apply_rolls_the_whole_group_back_when_the_second_move_fails(self):
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            _rc, args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            # 두 번째 destination 을 미리 점유해 실패를 유도한다.
            os.makedirs(r.abs("data/pallet/assets/scenes/production/blender_scene"))
            self.assertEqual(MPL.cmd_apply(args, r.paths), 1)
            # 첫 번째가 되돌아와야 한다 — 반쪽 이동 상태로 끝나면 안 된다.
            self.assertTrue(os.path.isdir(r.abs("data/pallet/distractors")))
            self.assertFalse(os.path.exists(r.abs("data/pallet/assets/distractors/library")))
            statuses = [x["status"] for x in r.rows(args)]
            self.assertIn("ROLLED_BACK", statuses)
            self.assertIn("FAILED", statuses)

    def test_group_apply_and_verify_succeed_together(self):
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            _rc, args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            self.assertFalse(os.path.exists(r.abs("data/pallet/distractors")))
            self.assertFalse(os.path.exists(r.abs("data/pallet/blender_scene")))
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)

    def test_group_rollback_is_reverse_order(self):
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            _rc, args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            MPL.cmd_apply(args, r.paths)
            self.assertEqual(MPL.cmd_rollback(args, r.paths), 0)
            self.assertTrue(os.path.isdir(r.abs("data/pallet/distractors")))
            self.assertTrue(os.path.isdir(r.abs("data/pallet/blender_scene")))
            self.assertFalse(os.path.exists(
                r.abs("data/pallet/assets/scenes/production/blender_scene")))

    def test_license_files_are_preserved_and_verified(self):
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            _rc, args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            rows = r.rows(args)
            dist = [x for x in rows if x["source"].endswith("distractors")][0]
            self.assertIn("large/LICENSE.txt", dist["license_files"])
            MPL.cmd_apply(args, r.paths)
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)


class HashModeIsForced(unittest.TestCase):
    def test_plan_refuses_selective_hash_mode(self):
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            rc, _args = r.plan(cohort="C2C_DISTRACTOR_SCENE",
                               hash_mode=MPL.HASH_MODE_SELECTIVE)
            self.assertEqual(rc, 2)

    def test_every_planned_row_reports_zero_unhashed(self):
        with Repo() as r:
            r.make_background(with_zip=False)
            r.make_distractors(); r.make_scene()
            _rc, args = r.plan()
            rows = r.rows(args)
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(row["hash_mode"], MPL.HASH_MODE_ALL)
                self.assertEqual(row["unhashed_file_count"], 0)
                self.assertEqual(row["pre_hash_manifest"]["unhashed"], [])


class LegacyContractUnchanged(unittest.TestCase):
    """Stage 2-A/2-B row 에는 transaction_group 이 없다. 그쪽 계약을 바꾸면 안 된다."""

    def test_entry_kind_defaults_to_directory_for_legacy_rows(self):
        self.assertEqual(MPL._entry_kind({}), MPL.ENTRY_DIRECTORY)
        self.assertEqual(MPL._entry_kind({"entry_kind": "bogus"}), MPL.ENTRY_DIRECTORY)

    def test_legacy_rows_are_not_grouped_by_cohort(self):
        """cohort 를 그룹으로 잘못 쓰면 Stage 2-A 의 부분 이동이 통째로 되돌려진다."""
        with Repo() as r:
            r.make_distractors(); r.make_scene()
            _rc, args = r.plan(cohort="C2C_DISTRACTOR_SCENE")
            rows = r.rows(args)
            for row in rows:
                row.pop("transaction_group")
            MPL._write_manifest(args.manifest, rows)
            os.makedirs(r.abs("data/pallet/assets/scenes/production/blender_scene"))
            self.assertEqual(MPL.cmd_apply(args, r.paths), 1)
            # 그룹이 없으므로 첫 이동은 그대로 남는다 (Stage 2-A 계약).
            statuses = [x["status"] for x in r.rows(args)]
            self.assertEqual(statuses, ["MOVED", "FAILED"])


if __name__ == "__main__":
    unittest.main()
