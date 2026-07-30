"""manage_pallet_data_layout — destination additions exact allowlist unit tests (Stage 2-D0.1).

**실제 data/pallet 을 쓰지 않는다.** 전부 tmpdir fixture 위에서 돌고, Stage 2-A/B/C2 의
실이동 원장은 읽지도 고치지도 않는다.

고정하는 계약
  - 추가 파일이 없으면 strict 로 통과한다
  - 추가 파일은 **exact allowlist** 로만 허용한다 (경로 + 크기 + SHA256)
  - 명세에 없는 extra / 명세에 있는데 없는 파일 / 크기·해시 불일치 -> 실패
  - 옮긴 파일의 누락·해시 불일치는 allowlist 와 무관하게 항상 실패
  - 명세는 manifest_sha256 으로 그 원장에 결속된다 (다른 transaction 에 재사용 불가)
  - relative_path escape / destination_root 불일치 -> 실패
  - Stage 2-A/2-B/C2A 기존 verify 동작과 transaction_group rollback 은 회귀 없음
"""

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
    return path


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


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
        self.expected_destination_additions = kw.get("expected_destination_additions")
        self.allow_any_destination_additions = kw.get("allow_any_destination_additions", False)
        self.allow_destination_additions = kw.get("allow_destination_additions", False)


class FakePaths(object):
    def __init__(self, root):
        self.project_root = root

    def get(self, key):
        if key == "pallet_data_root":
            return os.path.join(self.project_root, "data", "pallet")
        raise KeyError(key)


class Repo(object):
    """distractors + blender_scene 를 흉내낸 C2C 형태 fixture."""

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="d01_"))
        self.paths = FakePaths(self.root)
        write(self.abs("data/pallet/distractors/distractors_manifest.csv"), b"name\na\n")
        write(self.abs("data/pallet/distractors/large/LICENSE.txt"), b"CC0")
        write(self.abs("data/pallet/blender_scene/synth.blend"), b"BLENDBYTES")
        write(self.abs("data/pallet/blender_scene/textures/x.png"), b"png")
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def abs(self, rel):
        return os.path.join(self.root, rel.replace("/", os.sep))

    def manifest(self):
        return os.path.join(self.root, "out", "c2c.jsonl")

    def plan_and_apply(self):
        args = Args(manifest=self.manifest(), cohort="C2C_DISTRACTOR_SCENE")
        assert MPL.cmd_plan(args, self.paths) == 0
        assert MPL.cmd_apply(args, self.paths) == 0
        return args

    def scene_dest(self):
        return "data/pallet/assets/scenes/production/blender_scene"

    def add_to_scene_dest(self, name, content=b"NEWSCENE"):
        return write(os.path.join(self.abs(self.scene_dest()), name), content)

    def spec(self, entries, manifest_sha=None, destination_root=None, name="spec.json"):
        p = os.path.join(self.root, name)
        payload = {
            "manifest_sha256": manifest_sha or sha(self.manifest()),
            "destination_root": (destination_root if destination_root is not None
                                 else self.scene_dest()),
            "expected_additions": entries,
        }
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return p

    def entry(self, name, path=None, size=None, digest=None, role="test"):
        ap = path or os.path.join(self.abs(self.scene_dest()), name)
        return {"relative_path": name,
                "size": os.path.getsize(ap) if size is None else size,
                "sha256": sha(ap) if digest is None else digest,
                "role": role}


class NoAdditions(unittest.TestCase):
    def test_strict_pass_when_nothing_was_added(self):
        with Repo() as r:
            args = r.plan_and_apply()
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)

    def test_spec_with_zero_entries_still_passes(self):
        with Repo() as r:
            args = r.plan_and_apply()
            args.expected_destination_additions = r.spec([])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)


class ExactAllowlist(unittest.TestCase):
    def test_exact_match_passes(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            args.expected_destination_additions = r.spec([r.entry("new_scene.blend")])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)

    def test_expected_addition_missing_fails(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            entry = r.entry("new_scene.blend")
            os.remove(os.path.join(r.abs(r.scene_dest()), "new_scene.blend"))
            args.expected_destination_additions = r.spec([entry])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_sha_mismatch_fails(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend", b"ORIGINAL")
            entry = r.entry("new_scene.blend")
            r.add_to_scene_dest("new_scene.blend", b"TAMPERED")   # 같은 길이, 다른 내용
            args.expected_destination_additions = r.spec([entry])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_size_mismatch_fails(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend", b"SHORT")
            entry = r.entry("new_scene.blend")
            entry["size"] = entry["size"] + 1
            args.expected_destination_additions = r.spec([entry])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_one_unexpected_extra_fails_even_with_a_valid_spec(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            entry = r.entry("new_scene.blend")
            r.add_to_scene_dest("sneaky.blend1", b"NOT-IN-SPEC")
            args.expected_destination_additions = r.spec([entry])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_broad_mode_would_have_passed_the_sneaky_file(self):
        """왜 exact 가 필요한지 고정: broad 모드는 예상 못 한 파일도 통과시킨다."""
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("sneaky.blend1", b"NOT-IN-SPEC")
            args.allow_any_destination_additions = True
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)
            args.allow_any_destination_additions = False
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)


class MovedFilesAlwaysChecked(unittest.TestCase):
    def test_moved_file_missing_fails_despite_spec(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            spec = r.spec([r.entry("new_scene.blend")])
            os.remove(os.path.join(r.abs(r.scene_dest()), "synth.blend"))
            args.expected_destination_additions = spec
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)

    def test_moved_file_sha_mismatch_fails_despite_spec(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            spec = r.spec([r.entry("new_scene.blend")])
            write(os.path.join(r.abs(r.scene_dest()), "synth.blend"), b"TAMPEREDXX")
            args.expected_destination_additions = spec
            self.assertEqual(MPL.cmd_verify(args, r.paths), 1)


class SpecBinding(unittest.TestCase):
    def test_path_escape_is_rejected(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            e = r.entry("new_scene.blend")
            e["relative_path"] = "../escaped.blend"
            args.expected_destination_additions = r.spec([e])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 2)

    def test_wrong_destination_root_is_rejected(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            args.expected_destination_additions = r.spec(
                [r.entry("new_scene.blend")], destination_root="data/pallet/somewhere/else")
            self.assertEqual(MPL.cmd_verify(args, r.paths), 2)

    def test_spec_pointing_at_another_transaction_sha_is_rejected(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            args.expected_destination_additions = r.spec(
                [r.entry("new_scene.blend")], manifest_sha="0" * 64)
            self.assertEqual(MPL.cmd_verify(args, r.paths), 2)

    def test_spec_without_manifest_sha_is_rejected(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            p = os.path.join(r.root, "nosha.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"destination_root": r.scene_dest(),
                           "expected_additions": [r.entry("new_scene.blend")]}, fh)
            args.expected_destination_additions = p
            self.assertEqual(MPL.cmd_verify(args, r.paths), 2)

    def test_duplicate_expected_entry_is_rejected(self):
        with Repo() as r:
            args = r.plan_and_apply()
            r.add_to_scene_dest("new_scene.blend")
            e = r.entry("new_scene.blend")
            args.expected_destination_additions = r.spec([e, dict(e)])
            self.assertEqual(MPL.cmd_verify(args, r.paths), 2)


class LegacyContracts(unittest.TestCase):
    """Stage 2-A/2-B/C2A 기존 동작과 group rollback 이 바뀌지 않았는지."""

    def test_stage2a_selective_verify_unchanged(self):
        with Repo() as r:
            run = r.abs("data/pallet/run_x")
            write(os.path.join(run, "rgb", "f0.png"), b"png")
            write(os.path.join(run, "records.jsonl"), b'{"i":0}\n')
            moves = os.path.join(r.root, "moves.csv")
            with open(moves, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write("source,destination,status,required_code_changes,"
                         "required_test_changes\n")
                fh.write("data/pallet/run_x,runs/smoke/,SAFE_CANDIDATE,none,none\n")
            args = Args(manifest=os.path.join(r.root, "out", "a.jsonl"), moves=moves,
                        policy=MPL.POLICY_STAGE2A, hash_mode=MPL.HASH_MODE_SELECTIVE,
                        allow_empty_dirs=True)
            self.assertEqual(MPL.cmd_plan(args, r.paths), 0)
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)
            rows = MPL._read_manifest(args.manifest)
            self.assertEqual(MPL.manifest_hash_mode(rows[0]), MPL.HASH_MODE_SELECTIVE)

    def test_c2a_file_entry_verify_unchanged(self):
        with Repo() as r:
            write(r.abs("data/pallet/background/parking_lot/scene.gltf"), b"{}")
            write(r.abs("data/pallet/background/parking_lot.zip"), b"PK-a")
            args = Args(manifest=os.path.join(r.root, "out", "c2a.jsonl"),
                        cohort="C2A_BACKGROUND_PACKAGES")
            self.assertEqual(MPL.cmd_plan(args, r.paths), 0)
            self.assertEqual(MPL.cmd_apply(args, r.paths), 0)
            self.assertEqual(MPL.cmd_verify(args, r.paths), 0)
            self.assertEqual(MPL._entry_kind(MPL._read_manifest(args.manifest)[0]),
                             MPL.ENTRY_FILE)

    def test_transaction_group_rollback_unchanged(self):
        with Repo() as r:
            args = r.plan_and_apply()
            self.assertEqual(MPL.cmd_rollback(args, r.paths), 0)
            self.assertTrue(os.path.isdir(r.abs("data/pallet/distractors")))
            self.assertTrue(os.path.isdir(r.abs("data/pallet/blender_scene")))


if __name__ == "__main__":
    unittest.main()
