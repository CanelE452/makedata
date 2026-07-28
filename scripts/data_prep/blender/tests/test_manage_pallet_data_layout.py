"""manage_pallet_data_layout — 트랜잭션 unit tests.

**실제 data/pallet 을 쓰지 않는다.** 전부 임시 디렉토리 fixture 로 돌고,
Stage 2-A 의 실이동 원장(`reports/data_pallet_cleanup/stage2a/move_transaction.jsonl`)은
읽지도 고치지도 않는다.
"""

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


class Args(object):
    """argparse.Namespace 대용 (cmd_* 가 읽는 필드만)."""

    def __init__(self, **kw):
        self.manifest = kw.get("manifest")
        self.moves = kw.get("moves")
        self.allow_empty_dirs = kw.get("allow_empty_dirs", True)
        self.hash_mode = kw.get("hash_mode", MPL.HASH_MODE_SELECTIVE)
        self.move_id_prefix = kw.get("move_id_prefix", "TST")


class FakePaths(object):
    """PalletDataPaths 대용 — project_root 와 pallet_data_root 만 쓴다."""

    def __init__(self, root):
        self.project_root = root

    def get(self, key):
        if key == "pallet_data_root":
            return os.path.join(self.project_root, "data", "pallet")
        raise KeyError(key)


def write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


class TempRepo(object):
    """`<tmp>/data/pallet` 과 이동 계획 CSV 를 갖춘 최소 fixture."""

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="mpl_"))
        self.data_root = os.path.join(self.root, "data", "pallet")
        for sub in ("runs/smoke", "runs/diagnostics", "runs/failed"):
            os.makedirs(os.path.join(self.data_root, sub.replace("/", os.sep)), exist_ok=True)
        self.paths = FakePaths(self.root)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def make_run(self, name, files=None, big_bytes=0):
        run = os.path.join(self.data_root, name)
        files = files if files is not None else {
            "rgb/f0000_rgb.png": b"png-bytes",
            "labels/f0000_label.json": b'{"a":1}',
            "records.jsonl": b'{"idx":0}\n',
        }
        for rel, content in files.items():
            write(os.path.join(run, rel.replace("/", os.sep)), content)
        if big_bytes:
            write(os.path.join(run, "big.bin"), b"\0" * big_bytes)
        return run

    def moves_csv(self, rows, name="moves.csv"):
        import csv

        path = os.path.join(self.root, name)
        fields = ["source", "destination", "status", "required_code_changes",
                  "required_test_changes"]
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({"source": r[0], "destination": r[1],
                            "status": r[2] if len(r) > 2 else "SAFE_CANDIDATE",
                            "required_code_changes": r[3] if len(r) > 3 else "none",
                            "required_test_changes": r[4] if len(r) > 4 else "none"})
        return path

    def manifest_path(self):
        return os.path.join(self.root, "out", "move_transaction.jsonl")

    def plan(self, rows, **kw):
        args = Args(manifest=self.manifest_path(), moves=self.moves_csv(rows), **kw)
        rc = MPL.cmd_plan(args, self.paths)
        return rc, args

    def read_manifest(self, args):
        return MPL._read_manifest(args.manifest)


# ---------------------------------------------------------------------------
# 경로 경계 (§3-B)
# ---------------------------------------------------------------------------
class PathBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="mpl_bound_"))
        self.root = os.path.join(self.tmp, "data", "pallet")
        os.makedirs(os.path.join(self.root, "runs"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp, "data", "pallet_backup"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp, "outside"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_child_directory_is_within(self):
        self.assertTrue(MPL.is_within(os.path.join(self.root, "runs"), self.root))

    def test_the_root_itself_is_within(self):
        self.assertTrue(MPL.is_within(self.root, self.root))

    def test_sibling_with_a_shared_name_prefix_is_not_within(self):
        # 문자열 startswith 였다면 True 로 잘못 판정되던 사례
        sibling = os.path.join(self.tmp, "data", "pallet_backup")
        self.assertTrue(str(sibling).startswith(str(self.root)))   # 옛 방식이면 통과했음
        self.assertFalse(MPL.is_within(sibling, self.root))

    def test_dotdot_traversal_escapes_the_root(self):
        escaped = os.path.join(self.root, "..", "..", "outside")
        self.assertFalse(MPL.is_within(escaped, self.root))

    def test_a_path_on_another_drive_is_not_within(self):
        other = "Z:\\somewhere" if os.name == "nt" else "/other/mount/somewhere"
        self.assertFalse(MPL.is_within(other, self.root))

    def test_case_differences_are_normalised_on_windows(self):
        upper = self.root.upper()
        expected = os.name == "nt"
        self.assertEqual(MPL.is_within(upper, self.root), expected)

    def test_precheck_flags_a_source_outside_the_data_root(self):
        outside = os.path.join(self.tmp, "outside", "run")
        write(os.path.join(outside, "a.txt"))
        problems, _ = MPL.precheck(outside, os.path.join(self.root, "runs", "run"),
                                   [], self.root)
        self.assertIn("SOURCE_OUTSIDE_DATA_ROOT", problems)

    def test_precheck_flags_a_destination_outside_the_data_root(self):
        src = os.path.join(self.root, "run")
        write(os.path.join(src, "a.txt"))
        dst = os.path.join(self.tmp, "outside", "run")
        problems, _ = MPL.precheck(src, dst, [], self.root)
        self.assertIn("DEST_OUTSIDE_DATA_ROOT", problems)

    def test_precheck_flags_a_prefix_collision_destination(self):
        src = os.path.join(self.root, "run")
        write(os.path.join(src, "a.txt"))
        dst = os.path.join(self.tmp, "data", "pallet_backup", "run")
        problems, _ = MPL.precheck(src, dst, [], self.root)
        self.assertIn("DEST_OUTSIDE_DATA_ROOT", problems)


# ---------------------------------------------------------------------------
# 사전검사 (§3-B 나머지)
# ---------------------------------------------------------------------------
class Precheck(unittest.TestCase):
    def test_destination_collision_is_reported(self):
        with TempRepo() as fx:
            src = fx.make_run("run_a")
            dst = os.path.join(fx.data_root, "runs", "smoke", "run_a")
            os.makedirs(dst)
            problems, _ = MPL.precheck(src, dst, [], fx.data_root)
            self.assertIn("DEST_COLLISION", problems)

    def test_forbidden_extension_is_reported(self):
        with TempRepo() as fx:
            src = fx.make_run("run_b", files={"a.blend": b"x", "b.txt": b"y"})
            problems, stats = MPL.precheck(
                src, os.path.join(fx.data_root, "runs", "smoke", "run_b"), [], fx.data_root)
            self.assertTrue(any(p.startswith("FORBIDDEN_EXTENSION") for p in problems))
            self.assertEqual(stats["forbidden_ext"], ["a.blend"])

    def test_reserved_windows_filename_is_reported(self):
        with TempRepo() as fx:
            src = fx.make_run("run_c", files={"CON.txt": b"x"})
            problems, _ = MPL.precheck(
                src, os.path.join(fx.data_root, "runs", "smoke", "run_c"), [], fx.data_root)
            self.assertTrue(any(p.startswith("RESERVED_WINDOWS_NAME") for p in problems))

    def test_license_file_is_reported(self):
        with TempRepo() as fx:
            src = fx.make_run("run_d", files={"LICENSE.txt": b"x"})
            problems, _ = MPL.precheck(
                src, os.path.join(fx.data_root, "runs", "smoke", "run_d"), [], fx.data_root)
            self.assertTrue(any(p.startswith("LICENSE_FILE") for p in problems))

    def test_empty_directory_is_reported(self):
        with TempRepo() as fx:
            src = os.path.join(fx.data_root, "run_empty")
            os.makedirs(src)
            problems, _ = MPL.precheck(
                src, os.path.join(fx.data_root, "runs", "smoke", "run_empty"), [], fx.data_root)
            self.assertIn("EMPTY_DIRECTORY", problems)

    def test_code_reference_blocks_the_move(self):
        with TempRepo() as fx:
            src = fx.make_run("run_e")
            problems, _ = MPL.precheck(
                src, os.path.join(fx.data_root, "runs", "smoke", "run_e"),
                ["some_script.py:12"], fx.data_root)
            self.assertTrue(any(p.startswith("CODE_OR_TEST_REFERENCE") for p in problems))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unsupported")
    def test_a_symlinked_file_inside_the_source_is_reported(self):
        with TempRepo() as fx:
            src = fx.make_run("run_f")
            target = os.path.join(src, "rgb", "f0000_rgb.png")
            link = os.path.join(src, "rgb", "link.png")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest("symlink 생성 권한 없음: %s" % exc)
            problems, _ = MPL.precheck(
                src, os.path.join(fx.data_root, "runs", "smoke", "run_f"), [], fx.data_root)
            self.assertTrue(any(p.startswith("SYMLINK_OR_REPARSE") for p in problems))


# ---------------------------------------------------------------------------
# hash mode (§3-A)
# ---------------------------------------------------------------------------
BIG = MPL.HASH_SIZE_LIMIT + 1024


class HashMode(unittest.TestCase):
    def test_selective_leaves_a_large_binary_unhashed(self):
        with TempRepo() as fx:
            fx.make_run("run_sel", big_bytes=BIG)
            _, args = fx.plan([("data/pallet/run_sel", "runs/smoke/")])
            row = fx.read_manifest(args)[0]
            self.assertEqual(row["hash_mode"], MPL.HASH_MODE_SELECTIVE)
            self.assertIn("big.bin", row["pre_hash_manifest"]["unhashed"])
            self.assertEqual(row["unhashed_file_count"], 1)

    def test_all_hashes_every_file(self):
        with TempRepo() as fx:
            fx.make_run("run_all", big_bytes=BIG)
            _, args = fx.plan([("data/pallet/run_all", "runs/smoke/")],
                              hash_mode=MPL.HASH_MODE_ALL)
            row = fx.read_manifest(args)[0]
            self.assertEqual(row["hash_mode"], MPL.HASH_MODE_ALL)
            self.assertEqual(row["unhashed_file_count"], 0)
            self.assertEqual(row["pre_hash_manifest"]["unhashed"], [])
            self.assertEqual(len(row["pre_hash_manifest"]["sha256"]), row["file_count"])
            self.assertIn("big.bin", row["pre_hash_manifest"]["sha256"])

    def test_manifest_records_the_hash_timestamps_and_counts(self):
        with TempRepo() as fx:
            fx.make_run("run_ts")
            _, args = fx.plan([("data/pallet/run_ts", "runs/smoke/")])
            row = fx.read_manifest(args)[0]
            for key in ("hash_mode", "hashed_file_count", "unhashed_file_count",
                        "hash_started_at", "hash_completed_at"):
                self.assertIn(key, row)
            self.assertEqual(row["hashed_file_count"] + row["unhashed_file_count"],
                             row["file_count"])

    def test_snapshot_rejects_an_unknown_hash_mode(self):
        with TempRepo() as fx:
            run = fx.make_run("run_x")
            with self.assertRaises(ValueError):
                MPL.snapshot(run, set(), hash_mode="sometimes")

    def test_all_mode_never_reports_unhashed_files(self):
        with TempRepo() as fx:
            run = fx.make_run("run_y", big_bytes=BIG)
            snap = MPL.snapshot(run, set(), hash_mode=MPL.HASH_MODE_ALL)
            self.assertEqual(snap["unhashed"], [])

    def test_legacy_manifest_without_hash_mode_reads_as_selective_legacy(self):
        self.assertEqual(MPL.manifest_hash_mode({"move_id": "X"}), MPL.HASH_MODE_LEGACY)
        self.assertEqual(MPL.manifest_hash_mode({"hash_mode": "all"}), MPL.HASH_MODE_ALL)
        self.assertEqual(MPL.manifest_hash_mode({"hash_mode": "selective"}),
                         MPL.HASH_MODE_SELECTIVE)

    def test_a_legacy_manifest_still_verifies(self):
        with TempRepo() as fx:
            fx.make_run("run_leg")
            _, args = fx.plan([("data/pallet/run_leg", "runs/smoke/")])
            self.assertEqual(MPL.cmd_apply(args, fx.paths), 0)
            # hash_mode 필드를 지워 Stage 2-A 이전 형식으로 만든다
            rows = fx.read_manifest(args)
            for row in rows:
                row.pop("hash_mode", None)
            MPL._write_manifest(args.manifest, rows)
            self.assertEqual(MPL.cmd_verify(args, fx.paths), 0)


# ---------------------------------------------------------------------------
# plan / apply / verify / rollback (§3-C)
# ---------------------------------------------------------------------------
class Transaction(unittest.TestCase):
    def test_plan_does_not_move_anything(self):
        with TempRepo() as fx:
            src = fx.make_run("run_p")
            fx.plan([("data/pallet/run_p", "runs/smoke/")])
            self.assertTrue(os.path.isdir(src))
            self.assertFalse(os.path.exists(
                os.path.join(fx.data_root, "runs", "smoke", "run_p")))

    def test_apply_moves_the_directory_and_leaves_no_source(self):
        with TempRepo() as fx:
            src = fx.make_run("run_q")
            _, args = fx.plan([("data/pallet/run_q", "runs/smoke/")])
            self.assertEqual(MPL.cmd_apply(args, fx.paths), 0)
            self.assertFalse(os.path.exists(src))
            self.assertTrue(os.path.isdir(
                os.path.join(fx.data_root, "runs", "smoke", "run_q")))
            self.assertEqual(fx.read_manifest(args)[0]["status"], "MOVED")

    def test_verify_passes_after_a_clean_apply(self):
        with TempRepo() as fx:
            fx.make_run("run_r")
            _, args = fx.plan([("data/pallet/run_r", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            self.assertEqual(MPL.cmd_verify(args, fx.paths), 0)

    def test_verify_detects_a_changed_file(self):
        with TempRepo() as fx:
            fx.make_run("run_s")
            _, args = fx.plan([("data/pallet/run_s", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            tampered = os.path.join(fx.data_root, "runs", "smoke", "run_s",
                                    "labels", "f0000_label.json")
            write(tampered, b'{"a":2}')
            self.assertEqual(MPL.cmd_verify(args, fx.paths), 1)

    def test_verify_detects_a_missing_file(self):
        with TempRepo() as fx:
            fx.make_run("run_t")
            _, args = fx.plan([("data/pallet/run_t", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            os.remove(os.path.join(fx.data_root, "runs", "smoke", "run_t",
                                   "labels", "f0000_label.json"))
            self.assertEqual(MPL.cmd_verify(args, fx.paths), 1)

    def test_verify_detects_an_extra_file(self):
        with TempRepo() as fx:
            fx.make_run("run_u")
            _, args = fx.plan([("data/pallet/run_u", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            write(os.path.join(fx.data_root, "runs", "smoke", "run_u", "extra.txt"))
            self.assertEqual(MPL.cmd_verify(args, fx.paths), 1)

    def test_apply_refuses_to_overwrite_an_existing_destination(self):
        with TempRepo() as fx:
            fx.make_run("run_v")
            _, args = fx.plan([("data/pallet/run_v", "runs/smoke/")])
            # plan 이후에 목적지가 생겨 버린 상황
            dst = os.path.join(fx.data_root, "runs", "smoke", "run_v")
            write(os.path.join(dst, "already_here.txt"), b"keep me")
            self.assertEqual(MPL.cmd_apply(args, fx.paths), 1)
            self.assertEqual(open(os.path.join(dst, "already_here.txt"), "rb").read(),
                             b"keep me")
            self.assertEqual(fx.read_manifest(args)[0]["status"], "FAILED")

    def test_apply_stops_at_the_first_failure_and_keeps_manifest_state(self):
        with TempRepo() as fx:
            fx.make_run("run_w1")
            fx.make_run("run_w2")
            fx.make_run("run_w3")
            _, args = fx.plan([("data/pallet/run_w1", "runs/smoke/"),
                               ("data/pallet/run_w2", "runs/smoke/"),
                               ("data/pallet/run_w3", "runs/smoke/")])
            os.makedirs(os.path.join(fx.data_root, "runs", "smoke", "run_w2"))
            self.assertEqual(MPL.cmd_apply(args, fx.paths), 1)
            rows = fx.read_manifest(args)
            self.assertEqual([r["status"] for r in rows],
                             ["MOVED", "FAILED", "PLANNED"])
            # 세 번째는 손대지 않았다
            self.assertTrue(os.path.isdir(os.path.join(fx.data_root, "run_w3")))

    def test_rollback_restores_the_original_location(self):
        with TempRepo() as fx:
            fx.make_run("run_rb")
            _, args = fx.plan([("data/pallet/run_rb", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            self.assertEqual(MPL.cmd_rollback(args, fx.paths), 0)
            self.assertTrue(os.path.isdir(os.path.join(fx.data_root, "run_rb")))
            self.assertFalse(os.path.exists(
                os.path.join(fx.data_root, "runs", "smoke", "run_rb")))
            self.assertEqual(fx.read_manifest(args)[0]["status"], "ROLLED_BACK")

    def test_rollback_stops_when_the_original_location_is_occupied(self):
        with TempRepo() as fx:
            fx.make_run("run_rc")
            _, args = fx.plan([("data/pallet/run_rc", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            write(os.path.join(fx.data_root, "run_rc", "squatter.txt"), b"do not clobber")
            self.assertEqual(MPL.cmd_rollback(args, fx.paths), 1)
            self.assertEqual(
                open(os.path.join(fx.data_root, "run_rc", "squatter.txt"), "rb").read(),
                b"do not clobber")
            self.assertIn("FAILED", fx.read_manifest(args)[0]["rollback_status"])

    def test_rollback_runs_in_reverse_order(self):
        with TempRepo() as fx:
            fx.make_run("run_o1")
            fx.make_run("run_o2")
            _, args = fx.plan([("data/pallet/run_o1", "runs/smoke/"),
                               ("data/pallet/run_o2", "runs/diagnostics/")])
            MPL.cmd_apply(args, fx.paths)
            self.assertEqual(MPL.cmd_rollback(args, fx.paths), 0)
            for name in ("run_o1", "run_o2"):
                self.assertTrue(os.path.isdir(os.path.join(fx.data_root, name)))

    def test_plan_skips_a_destination_outside_the_allowed_prefixes(self):
        with TempRepo() as fx:
            fx.make_run("run_z")
            _, args = fx.plan([("data/pallet/run_z", "archive/legacy_datasets/")])
            self.assertEqual(fx.read_manifest(args), [])

    def test_plan_honours_the_move_id_prefix(self):
        with TempRepo() as fx:
            fx.make_run("run_id")
            _, args = fx.plan([("data/pallet/run_id", "runs/smoke/")],
                              move_id_prefix="S2B")
            self.assertTrue(fx.read_manifest(args)[0]["move_id"].startswith("S2B"))

    def test_same_volume_check(self):
        with TempRepo() as fx:
            a = os.path.join(fx.data_root, "x")
            b = os.path.join(fx.data_root, "y")
            self.assertTrue(MPL._same_volume(a, b))
            other = "Z:\\elsewhere" if os.name == "nt" else "/other/mount"
            self.assertEqual(MPL._same_volume(a, other), os.name != "nt")


class StageTwoALedgerIsUntouched(unittest.TestCase):
    """실이동 원장은 이 테스트들이 절대 건드리지 않는다."""

    LEDGER = os.path.join(
        os.path.dirname(os.path.dirname(_DATA_PREP_DIR)),
        "reports", "data_pallet_cleanup", "stage2a", "move_transaction.jsonl")

    def _ledger_sha(self):
        import hashlib

        with open(self.LEDGER, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def test_a_full_transaction_cycle_never_touches_the_real_ledger(self):
        """fixture 위에서 plan->apply->verify->rollback 을 다 돌려도 원장은 그대로다."""
        if not os.path.isfile(self.LEDGER):
            self.skipTest("Stage 2-A 원장이 없는 환경 (새 clone)")
        before = self._ledger_sha()
        with TempRepo() as fx:
            fx.make_run("run_guard")
            _, args = fx.plan([("data/pallet/run_guard", "runs/smoke/")])
            MPL.cmd_apply(args, fx.paths)
            MPL.cmd_verify(args, fx.paths)
            MPL.cmd_rollback(args, fx.paths)
            # fixture manifest 가 실제 원장과 다른 파일임을 명시적으로 확인
            self.assertNotEqual(os.path.normcase(os.path.abspath(args.manifest)),
                                os.path.normcase(os.path.abspath(self.LEDGER)))
        self.assertEqual(self._ledger_sha(), before,
                         "실이동 원장이 변경되었습니다 — rollback 근거가 사라집니다")

    def test_the_real_ledger_still_parses_and_reports_a_legacy_hash_mode(self):
        if not os.path.isfile(self.LEDGER):
            self.skipTest("Stage 2-A 원장이 없는 환경 (새 clone)")
        rows = MPL._read_manifest(self.LEDGER)
        self.assertTrue(rows)
        self.assertEqual({MPL.manifest_hash_mode(r) for r in rows},
                         {MPL.HASH_MODE_LEGACY})


if __name__ == "__main__":
    unittest.main()
