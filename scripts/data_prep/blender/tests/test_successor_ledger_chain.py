"""manage_pallet_data_layout — successor ledger chain unit tests (Stage 2-D1.1).

**실제 data/pallet 을 옮기지 않는다.** 22개 중 21개는 tmpdir fixture 위에서 돌고,
마지막 하나만 실제 저장소의 C2C 원장을 **읽기 전용**으로 참조한다.

chain 이 지켜야 하는 것: "prior 원장에서 없어진 파일"을 통과시키는 유일한 근거는
**파일 단위 SHA256 identity 로 후속 원장이 이어받았다는 증명**이다. broad allow 나
expected-removal 목록으로는 통과하지 않는다.
"""

import copy
import hashlib
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


def write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


class Args(object):
    def __init__(self, **kw):
        self.manifest = kw.get("manifest")
        self.expected_destination_additions = kw.get("expected_destination_additions")
        self.allow_any_destination_additions = kw.get("allow_any", False)
        self.allow_destination_additions = False
        self.successor_ledger_chain = kw.get("chain")
        self.max_hash_read_bytes = kw.get("max_hash_read_bytes")


class FakePaths(object):
    def __init__(self, root):
        self.project_root = root

    def get(self, key):
        if key == "pallet_data_root":
            return os.path.join(self.project_root, "data", "pallet")
        raise KeyError(key)


class Chain(object):
    """prior 원장(디렉토리 이동) + successor 원장(파일 이동) fixture.

    prior:      data/pallet/old_scene            -> data/pallet/assets/scene
                파일 3개 (keep.txt · cold.blend · other.txt)
    successor:  data/pallet/assets/scene/cold.blend -> data/pallet/archive/cold/cold.blend
    """

    COLD = b"BLENDER-cold-backup"

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="chain_"))
        self.paths = FakePaths(self.root)
        self.prior_dest = "data/pallet/assets/scene"
        self.succ_src = self.prior_dest + "/cold.blend"
        self.succ_dest = "data/pallet/archive/cold/cold.blend"
        self.files = {"keep.txt": b"keep", "cold.blend": self.COLD,
                      "other.txt": b"other"}
        # prior destination 상태를 만든다 (이동이 이미 끝난 상태)
        for name, data in self.files.items():
            write(self.abs("%s/%s" % (self.prior_dest, name)), data)
        os.makedirs(os.path.join(self.root, "out"), exist_ok=True)
        self.prior_path = os.path.join(self.root, "out", "prior.jsonl")
        self.succ_path = os.path.join(self.root, "out", "succ.jsonl")
        self._write_prior()
        self._write_succ(applied=False)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def abs(self, rel):
        return os.path.join(self.root, rel.replace("/", os.sep))

    def _write_prior(self):
        row = {
            "move_id": "PRIOR001", "policy": "prior-policy", "cohort": "PRIOR",
            "entry_kind": MPL.ENTRY_DIRECTORY, "transaction_group": "",
            "license_files": [], "source": "data/pallet/old_scene",
            "destination": self.prior_dest,
            "relative_files": sorted(self.files),
            "file_count": len(self.files),
            "total_bytes": sum(len(v) for v in self.files.values()),
            "hash_mode": MPL.HASH_MODE_ALL,
            "hashed_file_count": len(self.files), "unhashed_file_count": 0,
            "pre_hash_manifest": {
                "sha256": {k: sha_bytes(v) for k, v in self.files.items()},
                "sizes": {k: len(v) for k, v in self.files.items()},
                "hashed_over_limit": [], "unhashed": []},
            "status": "MOVED", "started_at": "t", "completed_at": "t",
            "error": None, "rollback_status": None,
        }
        MPL._write_manifest(self.prior_path, [row])

    def _write_succ(self, applied=True, verified=True, sha_override=None,
                    src_override=None, dest_override=None):
        digest = sha_override or sha_bytes(self.COLD)
        row = {
            "move_id": "SUCC001", "policy": MPL.POLICY_STAGE2D1,
            "schema_version": MPL.D1_SCHEMA_VERSION,
            "cohort": "D11A_BLEND_BACKUPS", "entry_kind": MPL.ENTRY_FILE,
            "transaction_group": "D11A_BLEND_BACKUPS", "license_files": [],
            "source": src_override or self.succ_src,
            "destination": dest_override or self.succ_dest,
            "relative_files": ["cold.blend"], "file_count": 1,
            "total_bytes": len(self.COLD), "hash_mode": MPL.HASH_MODE_ALL,
            "hashed_file_count": 1, "unhashed_file_count": 0,
            "pre_hash_manifest": {"sha256": {"cold.blend": digest},
                                  "sizes": {"cold.blend": len(self.COLD)},
                                  "hashed_over_limit": [], "unhashed": []},
            "source_sha256": {"cold.blend": digest},
            "hash_read_bytes_pre": len(self.COLD),
            "hash_read_bytes_post": len(self.COLD) if verified else None,
            "status": "MOVED" if applied else "PLANNED",
            "applied_at": "t" if applied else None,
            "verified_at": "t" if (applied and verified) else None,
            "rollback_source": src_override or self.succ_src,
            "rollback_destination": dest_override or self.succ_dest,
            "started_at": "t", "completed_at": "t", "error": None,
            "rollback_status": None,
        }
        MPL._write_manifest(self.succ_path, [row])

    def do_move(self):
        """successor 이동을 실제로 수행 (tmpdir 안)."""
        src = self.abs(self.succ_src)
        dst = self.abs(self.succ_dest)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
        self._write_succ(applied=True, verified=True)

    def chain_spec(self, **over):
        spec = {
            "schema_version": 1,
            "prior_manifest": {"path": _rel(self.prior_path, self.root),
                               "sha256": MPL._sha256(self.prior_path)},
            "successor_manifests": [{"path": _rel(self.succ_path, self.root),
                                     "sha256": MPL._sha256(self.succ_path),
                                     "policy": MPL.POLICY_STAGE2D1}],
            "mappings": [{
                "prior_move_id": "PRIOR001",
                "prior_relative_path": "cold.blend",
                "prior_destination_path": self.prior_dest,
                "size": len(self.COLD), "sha256": sha_bytes(self.COLD),
                "successor_manifest": _rel(self.succ_path, self.root),
                "successor_move_id": "SUCC001",
                "successor_source_path": self.succ_src,
                "successor_destination_path": self.succ_dest,
                "role": "cold_blend_backup"}],
        }
        spec.update(over)
        return spec

    def write_chain(self, spec=None, name="chain.json"):
        spec = spec if spec is not None else self.chain_spec()
        p = os.path.join(self.root, "out", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(spec, open(p, "w", encoding="utf-8"), indent=2)
        return p

    def verify(self, chain=None, **kw):
        return MPL.cmd_verify(Args(manifest=self.prior_path, chain=chain, **kw),
                              self.paths)

    def load(self, chain_path):
        rows = MPL._read_manifest(self.prior_path)
        return MPL.load_successor_chain(chain_path, self.prior_path, rows, self.root)


def _rel(p, root):
    return os.path.relpath(p, root).replace("\\", "/")


# ---------------------------------------------------------------------------
# 1 · 19  기본 동작
# ---------------------------------------------------------------------------
class ValidChain(unittest.TestCase):
    def test_valid_one_hop_chain_passes(self):
        with Chain() as c:
            c.do_move()
            self.assertEqual(c.verify(chain=c.write_chain()), 0)

    def test_missing_without_chain_still_fails(self):
        """chain 을 주지 않으면 기존처럼 missing 으로 실패해야 한다."""
        with Chain() as c:
            c.do_move()
            self.assertEqual(c.verify(), 1)

    def test_chain_is_refused_while_file_still_in_prior_destination(self):
        """아직 prior destination 에 있는 파일을 chain 으로 우회시킬 수 없다."""
        with Chain() as c:
            # 이동하지 않은 상태에서 destination 만 복사해 둔다
            write(c.abs(c.succ_dest), Chain.COLD)
            c._write_succ(applied=True, verified=True)
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain())


# ---------------------------------------------------------------------------
# 2-7  prior 쪽 검증
# ---------------------------------------------------------------------------
class PriorSideChecks(unittest.TestCase):
    def test_prior_manifest_sha_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["prior_manifest"]["sha256"] = "0" * 64
            self.assertEqual(c.verify(chain=c.write_chain(spec)), 2)

    def test_prior_manifest_path_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["prior_manifest"]["path"] = "out/other.jsonl"
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_unknown_prior_move_id_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"][0]["prior_move_id"] = "NOPE"
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_prior_relative_path_not_in_ledger_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"][0]["prior_relative_path"] = "not_in_ledger.blend"
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_prior_size_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"][0]["size"] = len(Chain.COLD) + 1
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_prior_sha_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"][0]["sha256"] = "f" * 64
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_prior_destination_path_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"][0]["prior_destination_path"] = "data/pallet/elsewhere"
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))


# ---------------------------------------------------------------------------
# 3 · 8-11  successor 쪽 검증
# ---------------------------------------------------------------------------
class SuccessorSideChecks(unittest.TestCase):
    def test_successor_manifest_sha_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["successor_manifests"][0]["sha256"] = "0" * 64
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_successor_source_not_prior_destination_fails(self):
        with Chain() as c:
            c.do_move()
            c._write_succ(applied=True, verified=True,
                          src_override="data/pallet/somewhere_else/cold.blend")
            spec = c.chain_spec()
            spec["mappings"][0]["successor_source_path"] = \
                "data/pallet/somewhere_else/cold.blend"
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_successor_row_not_verified_fails(self):
        with Chain() as c:
            c.do_move()
            c._write_succ(applied=True, verified=False)
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain())

    def test_successor_row_not_moved_fails(self):
        with Chain() as c:
            c.do_move()
            c._write_succ(applied=False)
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain())

    def test_successor_destination_missing_fails(self):
        with Chain() as c:
            c.do_move()
            chain = c.write_chain()
            os.remove(c.abs(c.succ_dest))
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(chain)

    def test_successor_destination_sha_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            chain = c.write_chain()
            write(c.abs(c.succ_dest), b"TAMPERED-but-same-length!")
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(chain)

    def test_successor_prehash_mismatch_fails(self):
        with Chain() as c:
            c.do_move()
            c._write_succ(applied=True, verified=True, sha_override="a" * 64)
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain())


# ---------------------------------------------------------------------------
# 12-16  구조 검증
# ---------------------------------------------------------------------------
class StructuralChecks(unittest.TestCase):
    def test_duplicate_prior_mapping_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"].append(copy.deepcopy(spec["mappings"][0]))
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_duplicate_successor_mapping_fails(self):
        with Chain() as c:
            c.do_move()
            os.remove(c.abs("%s/other.txt" % c.prior_dest))
            spec = c.chain_spec()
            dup = copy.deepcopy(spec["mappings"][0])
            dup["prior_relative_path"] = "other.txt"
            dup["size"] = len(b"other")
            dup["sha256"] = sha_bytes(b"other")
            spec["mappings"].append(dup)      # 같은 successor destination 을 재사용
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_unmapped_prior_missing_still_fails(self):
        with Chain() as c:
            c.do_move()
            os.remove(c.abs("%s/other.txt" % c.prior_dest))   # chain 에 없는 유실
            self.assertEqual(c.verify(chain=c.write_chain()), 1)

    def test_path_escape_in_mapping_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"][0]["successor_destination_path"] = "../escaped/cold.blend"
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_ledger_cycle_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["successor_manifests"] = [
                {"path": _rel(c.prior_path, c.root),
                 "sha256": MPL._sha256(c.prior_path)}]
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_empty_mappings_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            spec["mappings"] = []
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))

    def test_mapping_missing_required_field_fails(self):
        with Chain() as c:
            c.do_move()
            spec = c.chain_spec()
            del spec["mappings"][0]["sha256"]
            with self.assertRaises(MPL.SuccessorChainError):
                c.load(c.write_chain(spec))


# ---------------------------------------------------------------------------
# 17-18  additions 와 공존
# ---------------------------------------------------------------------------
class WithExpectedAdditions(unittest.TestCase):
    def _additions(self, c, entries):
        spec = {"manifest_sha256": MPL._sha256(c.prior_path),
                "destination_root": c.prior_dest,
                "expected_additions": entries}
        p = os.path.join(c.root, "out", "add.json")
        json.dump(spec, open(p, "w", encoding="utf-8"), indent=2)
        return p

    def test_unrelated_addition_still_fails(self):
        with Chain() as c:
            c.do_move()
            write(c.abs("%s/surprise.txt" % c.prior_dest), b"?")
            self.assertEqual(c.verify(chain=c.write_chain(),
                                      expected_destination_additions=self._additions(
                                          c, [])), 1)

    def test_expected_addition_and_chain_pass_together(self):
        with Chain() as c:
            c.do_move()
            data = b"new-active-scene"
            write(c.abs("%s/new.blend" % c.prior_dest), data)
            add = self._additions(c, [{"relative_path": "new.blend",
                                       "size": len(data),
                                       "sha256": sha_bytes(data),
                                       "role": "active_scene"}])
            self.assertEqual(c.verify(chain=c.write_chain(),
                                      expected_destination_additions=add), 0)


# ---------------------------------------------------------------------------
# 20-22  기존 동작 회귀 없음
# ---------------------------------------------------------------------------
class NoRegression(unittest.TestCase):
    def test_verify_without_chain_option_is_unchanged(self):
        with Chain() as c:
            self.assertEqual(c.verify(), 0)          # 이동 전 = 전부 제자리

    def test_successor_verify_is_idempotent(self):
        """재검증이 원장을 다시 쓰면 원장 SHA256 이 바뀌고 chain 이 깨진다.

        Stage 2-D1.1 에서 실제로 발생했다 — successor 원장을 두 번 verify 하자
        verified_at 타임스탬프가 갱신돼 chain 의 successor sha256 결속이 실패했다.
        첫 검증만 기록하고 재검증은 파일을 건드리지 않아야 한다.
        """
        with Chain() as c:
            c.do_move()
            args = Args(manifest=c.succ_path)
            self.assertEqual(MPL.cmd_verify(args, c.paths), 0)
            first = MPL._sha256(c.succ_path)
            row = MPL._read_manifest(c.succ_path)[0]
            self.assertTrue(row["verified_at"])
            self.assertEqual(MPL.cmd_verify(args, c.paths), 0)
            self.assertEqual(MPL._sha256(c.succ_path), first,
                             "재검증이 원장을 바꾸면 chain 결속이 깨진다")

    def test_chain_survives_successor_reverify(self):
        with Chain() as c:
            c.do_move()
            MPL.cmd_verify(Args(manifest=c.succ_path), c.paths)
            chain = c.write_chain()          # 검증 후 SHA 로 chain 을 만든다
            MPL.cmd_verify(Args(manifest=c.succ_path), c.paths)   # 재검증
            self.assertEqual(c.verify(chain=chain), 0)

    def test_chain_helpers_are_additive_only(self):
        for name in ("load_expected_additions", "check_expected_additions",
                     "prior_ledger_members", "find_prior_ledger_conflict"):
            self.assertTrue(hasattr(MPL, name), name)
        self.assertTrue(hasattr(MPL, "load_successor_chain"))
        self.assertTrue(issubclass(MPL.SuccessorChainError, Exception))

    def test_real_c2c_ledger_records_the_ten_d1d_blends(self):
        """실제 저장소 원장을 **읽기 전용**으로 확인한다 (이동·수정 없음).

        D1D 10개 blend 가 C2C 원장의 구성원이고 size·sha256 이 기록돼 있어야
        chain 을 만들 수 있다. 이 전제가 깨지면 D1.1-A 를 진행할 수 없다.
        """
        root = os.path.dirname(os.path.dirname(_DATA_PREP_DIR))
        c2c = os.path.join(root, "reports", "data_pallet_cleanup", "stage2c2",
                           "transactions", "c2c_distractor_scene.jsonl")
        d1d = os.path.join(root, "reports", "data_pallet_cleanup", "stage2d1",
                           "transactions", "d1d_blend_backups.jsonl")
        if not (os.path.isfile(c2c) and os.path.isfile(d1d)):
            self.skipTest("실제 원장이 없는 환경")
        crows = [r for r in MPL._read_manifest(c2c) if r["status"] == "MOVED"]
        drows = MPL._read_manifest(d1d)
        self.assertEqual(len(drows), 10)
        found = 0
        for d in drows:
            for cr in crows:
                dest = cr["destination"]
                if d["source"].startswith(dest + "/"):
                    inner = d["source"][len(dest) + 1:]
                    pre = cr["pre_hash_manifest"]
                    if inner in (cr.get("relative_files") or []):
                        self.assertIn(inner, pre["sha256"])
                        self.assertIn(inner, pre["sizes"])
                        found += 1
        self.assertEqual(found, 10, "10개 전부 C2C 원장 구성원이어야 한다")


if __name__ == "__main__":
    unittest.main()
