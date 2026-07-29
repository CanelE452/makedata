"""`blend_path_utils` 단위 테스트 (Stage 2-C1).

실제 production `.blend` 를 요구하지 않는다 — 전부 tmpdir 위에서 돈다. bpy 도 쓰지 않는다.
`.blend` 재작성에서 틀리면 조용히 텍스처가 깨지는 판단(경로 포함 관계 / 상대경로 계산 /
plan 강제 / 해시 대조 / 누락 datablock 판정)만 골라 고정한다.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blend_path_utils as U  # noqa: E402


def _touch(path, payload=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(payload)
    return path


class IsWithin(unittest.TestCase):
    def test_same_path_is_within(self):
        self.assertTrue(U.is_within(r"C:\a\b", r"C:\a\b"))

    def test_child_is_within(self):
        self.assertTrue(U.is_within(os.path.join("C:", os.sep, "a", "b", "c.txt"),
                                    os.path.join("C:", os.sep, "a", "b")))

    def test_prefix_collision_is_not_within(self):
        """`/a/bc` 는 `/a/b` 안이 아니다. 구분자 없이 startswith 하면 틀린다."""
        self.assertFalse(U.is_within(os.path.join("C:", os.sep, "a", "bc"),
                                     os.path.join("C:", os.sep, "a", "b")))

    def test_slash_and_backslash_are_equivalent(self):
        self.assertTrue(U.is_within("C:/a/b/c.png", "C:\\a\\b"))

    def test_case_insensitive_on_windows_normcase(self):
        expected = os.path.normcase("C:/A/B") == os.path.normcase("c:/a/b")
        self.assertEqual(U.is_within("C:/A/B/x.png", "c:/a/b"), expected)

    def test_parent_is_not_within_child(self):
        self.assertFalse(U.is_within("C:/a", "C:/a/b"))

    def test_none_is_not_within(self):
        self.assertFalse(U.is_within(None, "C:/a"))


class Relative(unittest.TestCase):
    def test_blend_relative_uses_forward_slashes(self):
        rel = U.to_blend_relative(os.path.join("C:", os.sep, "p", "distractors", "a.png"),
                                  os.path.join("C:", os.sep, "p", "blender_scene"))
        self.assertIsNotNone(rel)
        self.assertTrue(rel.startswith("//"))
        self.assertNotIn("\\", rel)

    def test_blend_relative_goes_up_one_level(self):
        rel = U.to_blend_relative(os.path.join("C:", os.sep, "p", "distractors", "a.png"),
                                  os.path.join("C:", os.sep, "p", "blender_scene"))
        self.assertEqual(rel, "//../distractors/a.png")

    def test_sibling_file_has_no_dotdot(self):
        rel = U.to_blend_relative(os.path.join("C:", os.sep, "p", "bs", "textures", "a.png"),
                                  os.path.join("C:", os.sep, "p", "bs"))
        self.assertEqual(rel, "//textures/a.png")

    @unittest.skipUnless(os.name == "nt", "drive letter semantics are Windows-only")
    def test_different_drive_returns_none(self):
        self.assertIsNone(U.to_blend_relative(r"D:\x\a.png", r"C:\p\bs"))

    def test_round_trip_resolves_back_to_the_same_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            blend_dir = os.path.join(tmp, "blender_scene")
            os.makedirs(blend_dir)
            target = _touch(os.path.join(tmp, "distractors", "sub", "a.png"))
            rel = U.to_blend_relative(target, blend_dir)
            self.assertEqual(U.norm(U.resolve_blend_relative(rel, blend_dir)), U.norm(target))

    def test_resolve_passthrough_for_absolute(self):
        self.assertEqual(U.norm(U.resolve_blend_relative(os.path.abspath("x.png"), "C:/p")),
                         U.norm(os.path.abspath("x.png")))


class AbsoluteDetection(unittest.TestCase):
    def test_blend_relative_is_not_absolute(self):
        self.assertFalse(U.is_absolute_filepath("//textures/a.png"))
        self.assertFalse(U.is_absolute_filepath("//..\\distractors\\a.png"))

    def test_drive_path_is_absolute(self):
        self.assertTrue(U.is_absolute_filepath(r"E:\CODING\a.png"))

    def test_posix_root_is_absolute(self):
        self.assertTrue(U.is_absolute_filepath("/home/u/a.png"))

    def test_empty_is_not_absolute(self):
        self.assertFalse(U.is_absolute_filepath(""))
        self.assertFalse(U.is_absolute_filepath(None))


class UserSpecific(unittest.TestCase):
    def test_user_profile_path_is_flagged(self):
        self.assertTrue(U.has_user_specific_prefix(
            r"C:\Users\User\Documents\GitHub\FoundationPose\data\pallet\hdri\x.hdr"))

    def test_home_path_is_flagged(self):
        self.assertTrue(U.has_user_specific_prefix("/home/someone/data/x.png"))

    def test_relative_path_is_not_flagged(self):
        self.assertFalse(U.has_user_specific_prefix("//../distractors/a.png"))

    def test_plain_project_absolute_is_not_flagged(self):
        self.assertFalse(U.has_user_specific_prefix(r"E:\CODING\GitHub\FoundationPose\a.png"))


class Escape(unittest.TestCase):
    def test_dotdot_escaping_root_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data", "pallet")
            blend_dir = os.path.join(root, "blender_scene")
            os.makedirs(blend_dir)
            self.assertTrue(U.escapes_root("//../../outside/a.png", blend_dir, root))
            self.assertFalse(U.escapes_root("//../distractors/a.png", blend_dir, root))


class Sha(unittest.TestCase):
    def test_same_content_same_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _touch(os.path.join(tmp, "a.bin"), b"hello")
            b = _touch(os.path.join(tmp, "b.bin"), b"hello")
            self.assertEqual(U.sha256_file(a), U.sha256_file(b))

    def test_different_content_different_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _touch(os.path.join(tmp, "a.bin"), b"hello")
            b = _touch(os.path.join(tmp, "b.bin"), b"world")
            self.assertNotEqual(U.sha256_file(a), U.sha256_file(b))

    def test_missing_file_returns_none(self):
        self.assertIsNone(U.sha256_file(os.path.join(tempfile.gettempdir(), "no_such_file_xyz")))


class Guards(unittest.TestCase):
    def test_source_equal_candidate_is_rejected(self):
        with self.assertRaises(U.PlanError):
            U.assert_distinct_files("C:/p/a.blend", "C:/p/./a.blend")

    def test_distinct_files_pass(self):
        U.assert_distinct_files("C:/p/a.blend", "C:/p/a_portable.blend")

    def test_existing_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _touch(os.path.join(tmp, "c.blend"))
            with self.assertRaises(U.PlanError):
                U.assert_candidate_not_present(path)

    def test_absent_candidate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            U.assert_candidate_not_present(os.path.join(tmp, "c.blend"))

    def test_source_hash_change_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _touch(os.path.join(tmp, "s.blend"), b"one")
            good = U.sha256_file(src)
            U.assert_source_unchanged(src, good)
            _touch(os.path.join(tmp, "s.blend"), b"two")
            with self.assertRaises(U.PlanError):
                U.assert_source_unchanged(src, good)

    def test_unplanned_change_is_rejected(self):
        with self.assertRaises(U.PlanError):
            U.assert_only_planned_changes(["a"], ["a", "b"])

    def test_missed_planned_change_is_rejected(self):
        with self.assertRaises(U.PlanError):
            U.assert_only_planned_changes(["a", "b"], ["a"])

    def test_exact_match_passes(self):
        U.assert_only_planned_changes(["a", "b"], ["b", "a"])


class BuildMapping(unittest.TestCase):
    def _layout(self, tmp):
        root = os.path.join(tmp, "data", "pallet")
        blend_dir = os.path.join(root, "blender_scene")
        os.makedirs(blend_dir)
        target = _touch(os.path.join(root, "distractors", "sm", "t.png"), b"pixels")
        return root, blend_dir, target

    def test_plans_an_exact_relative_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, blend_dir, target = self._layout(tmp)
            plan = U.build_mapping({"name": "t.png", "filepath_raw": target,
                                    "filepath_absolute": target}, blend_dir, root)
            self.assertEqual(plan["status"], "PLANNED")
            self.assertEqual(plan["new_filepath"], "//../distractors/sm/t.png")
            self.assertTrue(plan["same_file"])
            self.assertEqual(plan["old_sha256"], plan["new_sha256"])

    def test_missing_source_file_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, blend_dir, _ = self._layout(tmp)
            ghost = os.path.join(root, "distractors", "sm", "ghost.png")
            plan = U.build_mapping({"name": "g", "filepath_raw": ghost,
                                    "filepath_absolute": ghost}, blend_dir, root)
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertEqual(plan["blocker"], "source_file_missing")

    def test_target_outside_allowed_root_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, blend_dir, _ = self._layout(tmp)
            outside = _touch(os.path.join(tmp, "elsewhere", "o.png"))
            plan = U.build_mapping({"name": "o", "filepath_raw": outside,
                                    "filepath_absolute": outside}, blend_dir, root)
            self.assertEqual(plan["blocker"], "outside_allowed_root")

    def test_basename_collision_does_not_merge_distinct_files(self):
        """같은 basename 이 여러 개 있어도 각자 자기 절대경로 기준으로만 매핑된다."""
        with tempfile.TemporaryDirectory() as tmp:
            root, blend_dir, _ = self._layout(tmp)
            a = _touch(os.path.join(root, "distractors", "one", "t.png"), b"AAA")
            b = _touch(os.path.join(root, "distractors", "two", "t.png"), b"BBB")
            pa = U.build_mapping({"name": "t.png", "filepath_raw": a,
                                  "filepath_absolute": a}, blend_dir, root)
            pb = U.build_mapping({"name": "t.png.001", "filepath_raw": b,
                                  "filepath_absolute": b}, blend_dir, root)
            self.assertEqual(pa["status"], "PLANNED")
            self.assertEqual(pb["status"], "PLANNED")
            self.assertNotEqual(pa["new_filepath"], pb["new_filepath"])
            self.assertNotEqual(pa["new_sha256"], pb["new_sha256"])


class MissingDatablockDecision(unittest.TestCase):
    def test_single_candidate_is_repoint_exact(self):
        self.assertEqual(
            U.decide_missing_datablock(["/x/a.hdr"], users=1, fake_user=False,
                                       referenced_by="world:World/env"),
            U.DECISION_REPOINT_EXACT)

    def test_multiple_candidates_is_ambiguous(self):
        self.assertEqual(
            U.decide_missing_datablock(["/x/a.hdr", "/y/a.hdr"], users=1, fake_user=False,
                                       referenced_by=""),
            U.DECISION_BLOCKED_AMBIGUOUS)

    def test_no_candidate_but_used_is_blocked(self):
        self.assertEqual(
            U.decide_missing_datablock([], users=1, fake_user=False, referenced_by=""),
            U.DECISION_BLOCKED_USED)

    def test_no_candidate_and_fake_user_is_blocked(self):
        self.assertEqual(
            U.decide_missing_datablock([], users=0, fake_user=True, referenced_by=""),
            U.DECISION_BLOCKED_USED)

    def test_no_candidate_and_referenced_is_blocked(self):
        self.assertEqual(
            U.decide_missing_datablock([], users=0, fake_user=False,
                                       referenced_by="material:M/node"),
            U.DECISION_BLOCKED_USED)

    def test_no_candidate_and_unused_is_removable_in_candidate_only(self):
        self.assertEqual(
            U.decide_missing_datablock([], users=0, fake_user=False, referenced_by=""),
            U.DECISION_REMOVE_UNUSED)


if __name__ == "__main__":
    unittest.main()
