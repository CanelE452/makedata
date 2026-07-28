"""pallet_data_paths resolver — clone-safe unit tests.

**이 파일은 실제 `data/pallet` 를 한 번도 건드리지 않는다.** 전부 임시 디렉토리
fixture 로 돌아가므로 방금 clone 한 저장소(=data/pallet 없음)에서도 그대로 통과한다.
실데이터 단언은 `integration_tests/test_pallet_data_paths_local.py` 로 분리했다.

Stage 2-A 의 test_pallet_data_paths.py 가 실 workstation 파일 존재를 단언해서
새 clone 에서 3건이 실패하고 1건(project-root 탐지)은 fallback 덕에 **틀린 이유로
통과**하던 문제를 여기서 바로잡는다.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import pallet_data_paths as PDP  # noqa: E402


# resolver 가 요구하는 최소 registry. 값은 전부 fixture 안에서만 의미를 갖는다.
MINIMAL = {
    "pallet_data_root": "data/pallet",
    "production_scene": "data/pallet/blender_scene/synth_data_scene.blend",
    "background_root": "data/pallet/background",
    "distractor_root": "data/pallet/distractors",
    "distractor_manifest": "data/pallet/distractors/distractors_manifest.csv",
    "hdri_root": "data/pallet/hdri",
    "floor_material_root": "data/pallet/archive/textures_floor",
    "pallet_material_root": "data/pallet/archive/textures_wood",
    "pallet_model_roots": ["data/pallet/models_usd", "data/pallet/pallets_v2_add/models"],
    "golden_overlay_reference": "data/pallet/archive/trunc_addon_v1_pilot",
    "real_data_root": "data/pallet/real_data",
    "runs_root": "data/pallet/runs",
    "release_root": "data/pallet/release",
    "archive_root": "data/pallet/archive",
}

# fixture repo 안에 실제로 만들어 둘 경로 (존재/부재를 구분해 검사하기 위함)
FIXTURE_DIRS = [
    "config/synthetic",
    "data/pallet",
    "data/pallet/blender_scene",
    "data/pallet/background",
    "data/pallet/distractors",
    "data/pallet/hdri",
    "data/pallet/archive",
    "data/pallet/archive/textures_floor",
    "data/pallet/archive/textures_wood",
    "data/pallet/models_usd",
    "data/pallet/pallets_v2_add/models",
    "data/pallet/archive/trunc_addon_v1_pilot",
    "data/pallet/real_data",
    "data/pallet/runs",
    "data/pallet/release",
]
FIXTURE_FILES = [
    "data/pallet/blender_scene/synth_data_scene.blend",
    "data/pallet/distractors/distractors_manifest.csv",
]


class FixtureRepo(object):
    """임시 디렉토리에 `config/synthetic` + `data/pallet` 를 갖춘 가짜 repo 를 만든다."""

    def __init__(self, mapping=None, make_paths=True):
        self.mapping = dict(MINIMAL if mapping is None else mapping)
        self.make_paths = make_paths

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="pdp_fixture_"))
        if self.make_paths:
            for rel in FIXTURE_DIRS:
                os.makedirs(os.path.join(self.root, rel.replace("/", os.sep)), exist_ok=True)
            for rel in FIXTURE_FILES:
                path = os.path.join(self.root, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("fixture\n")
        else:
            os.makedirs(os.path.join(self.root, "config", "synthetic"), exist_ok=True)
        self.config_path = os.path.join(self.root, "config", "synthetic", "pallet_paths.yaml")
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self.mapping, fh)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def load(self, **kwargs):
        kwargs.setdefault("config_path", self.config_path)
        kwargs.setdefault("project_root", self.root)
        kwargs["use_cache"] = False
        return PDP.load(**kwargs)


class ModuleIsBpyFree(unittest.TestCase):
    def test_source_never_imports_bpy(self):
        src = open(PDP.__file__, encoding="utf-8").read()
        self.assertNotIn("import bpy", src)

    def test_module_imports_without_bpy_in_sys_modules(self):
        self.assertNotIn("bpy", sys.modules)

    def test_importing_the_module_in_a_clean_interpreter_needs_no_bpy(self):
        code = (
            "import sys; sys.path.insert(0, %r);"
            "import pallet_data_paths;"
            "assert 'bpy' not in sys.modules;"
            "print('ok')" % _BLENDER_DIR
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ok", proc.stdout)


class ConfigParsing(unittest.TestCase):
    def test_registry_loads_from_an_explicit_config_path(self):
        with FixtureRepo() as fx:
            paths = fx.load()
            self.assertEqual(os.path.normcase(paths.config_path),
                             os.path.normcase(fx.config_path))
            self.assertEqual(paths.relative("hdri_root"), "data/pallet/hdri")

    def test_comment_keys_are_not_treated_as_paths(self):
        mapping = dict(MINIMAL)
        mapping["// note"] = "이건 주석이지 경로가 아니다"
        with FixtureRepo(mapping) as fx:
            paths = fx.load()
            self.assertNotIn("// note", paths.keys())

    def test_config_env_var_overrides_the_default_location(self):
        with FixtureRepo() as fx:
            os.environ[PDP.CONFIG_ENV_VAR] = fx.config_path
            try:
                PDP.clear_cache()
                paths = PDP.load(project_root=fx.root, use_cache=False)
                self.assertEqual(os.path.normcase(paths.config_path),
                                 os.path.normcase(fx.config_path))
            finally:
                os.environ.pop(PDP.CONFIG_ENV_VAR, None)
                PDP.clear_cache()

    def test_list_values_resolve_element_wise(self):
        with FixtureRepo() as fx:
            paths = fx.load()
            value = paths.get("pallet_model_roots")
            self.assertIsInstance(value, list)
            self.assertEqual(len(value), 2)
            for item in value:
                self.assertTrue(os.path.isabs(item))
            self.assertEqual(paths.relative("pallet_model_roots"),
                             ["data/pallet/models_usd", "data/pallet/pallets_v2_add/models"])


class ProjectRootDetection(unittest.TestCase):
    """`config/synthetic` 와 `data/pallet` 를 함께 가진 상위 디렉토리를 찾는다."""

    def test_walks_up_to_the_directory_that_has_both_markers(self):
        with FixtureRepo() as fx:
            deep = os.path.join(fx.root, "scripts", "data_prep", "blender")
            os.makedirs(deep, exist_ok=True)
            self.assertEqual(os.path.normcase(PDP.detect_project_root(deep)),
                             os.path.normcase(fx.root))

    def test_a_directory_with_only_one_marker_is_not_the_project_root(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="pdp_half_"))
        try:
            os.makedirs(os.path.join(tmp, "config", "synthetic"))   # data/pallet 없음
            # 4단계 이상 내려가서 "3단계 위" fallback 이 tmp 와 우연히 겹치지 않게 한다.
            deep = os.path.join(tmp, "a", "b", "c", "d")
            os.makedirs(deep)
            self.assertNotEqual(os.path.normcase(PDP.detect_project_root(deep)),
                                os.path.normcase(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_both_markers_are_required_not_just_config(self):
        """config/synthetic 만 있는 트리를 project root 로 오인하지 않는다."""
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="pdp_cfgonly_"))
        try:
            os.makedirs(os.path.join(tmp, "config", "synthetic"))
            deep = os.path.join(tmp, "x", "y", "z", "w")
            os.makedirs(deep)
            detected = PDP.detect_project_root(deep)
            self.assertNotEqual(os.path.normcase(detected), os.path.normcase(tmp))
            # data/pallet 을 만들어 주면 그때는 찾아낸다.
            os.makedirs(os.path.join(tmp, "data", "pallet"))
            self.assertEqual(os.path.normcase(PDP.detect_project_root(deep)),
                             os.path.normcase(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_explicit_project_root_is_used_verbatim(self):
        with FixtureRepo() as fx:
            paths = PDP.load(config_path=fx.config_path, project_root=fx.root, use_cache=False)
            self.assertEqual(os.path.normcase(paths.project_root),
                             os.path.normcase(fx.root))


class RootOverride(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(PDP.ROOT_ENV_VAR, None)
        PDP.clear_cache()

    def test_env_var_overrides_only_the_root_and_rebuilds_children(self):
        with FixtureRepo() as fx:
            os.environ[PDP.ROOT_ENV_VAR] = "somewhere/else"
            paths = fx.load()
            self.assertEqual(paths.relative("pallet_data_root"), "somewhere/else")
            self.assertEqual(paths.relative("hdri_root"), "somewhere/else/hdri")
            self.assertEqual(paths.relative("distractor_manifest"),
                             "somewhere/else/distractors/distractors_manifest.csv")

    def test_argument_override_matches_env_behaviour(self):
        with FixtureRepo() as fx:
            paths = fx.load(data_root="somewhere/else")
            self.assertEqual(paths.relative("runs_root"), "somewhere/else/runs")

    def test_absolute_root_override_is_kept_absolute(self):
        with FixtureRepo() as fx:
            other = os.path.join(fx.root, "elsewhere")
            paths = fx.load(data_root=other)
            self.assertEqual(os.path.normcase(paths.get("pallet_data_root")),
                             os.path.normcase(other))
            self.assertEqual(os.path.normcase(paths.get("hdri_root")),
                             os.path.normcase(os.path.join(other, "hdri")))

    def test_override_does_not_touch_paths_outside_the_data_root(self):
        mapping = dict(MINIMAL)
        mapping["reports_root"] = "reports/data_pallet_cleanup"
        with FixtureRepo(mapping) as fx:
            paths = fx.load(data_root="somewhere/else")
            self.assertEqual(paths.relative("reports_root"), "reports/data_pallet_cleanup")


class SeparatorHandling(unittest.TestCase):
    def test_backslash_registry_values_are_accepted(self):
        mapping = dict(MINIMAL)
        mapping["pallet_data_root"] = "data\\pallet"
        mapping["hdri_root"] = "data\\pallet\\hdri"
        with FixtureRepo(mapping) as fx:
            paths = fx.load()
            self.assertEqual(paths.relative("hdri_root"), "data/pallet/hdri")
            self.assertTrue(os.path.isdir(paths.get("hdri_root")))

    def test_relative_output_is_always_posix(self):
        with FixtureRepo() as fx:
            paths = fx.load()
            for key in paths.keys():
                rel = paths.relative(key)
                for r in (rel if isinstance(rel, list) else [rel]):
                    self.assertNotIn("\\", r, key)

    def test_resolved_paths_are_absolute_and_under_the_project_root(self):
        with FixtureRepo() as fx:
            paths = fx.load()
            for key in paths.keys():
                value = paths.get(key)
                for p in (value if isinstance(value, list) else [value]):
                    self.assertTrue(os.path.isabs(p), key)
                    self.assertTrue(
                        os.path.normcase(p).startswith(os.path.normcase(fx.root)), key)


class MissingAndOptional(unittest.TestCase):
    def test_every_required_key_must_be_present(self):
        for key in PDP.REQUIRED_KEYS:
            mapping = dict(MINIMAL)
            mapping.pop(key, None)
            with FixtureRepo(mapping) as fx:
                with self.assertRaises(KeyError, msg=key):
                    fx.load()

    def test_required_key_set_is_complete_in_the_fixture(self):
        with FixtureRepo() as fx:
            paths = fx.load()
            for key in PDP.REQUIRED_KEYS:
                self.assertIn(key, paths, key)

    def test_nonexistent_path_is_reported_missing_not_silently_substituted(self):
        mapping = dict(MINIMAL)
        mapping["hdri_root"] = "data/pallet/__no_such_dir__"
        with FixtureRepo(mapping) as fx:
            paths = fx.load()
            report = paths.audit()
            self.assertIn("hdri_root", [e["key"] for e in report["missing"]])
            # fallback 으로 다른 경로를 돌려주지 않는다
            self.assertTrue(paths.get("hdri_root").endswith("__no_such_dir__"))

    def test_optional_key_absence_is_reported_separately_from_missing(self):
        mapping = dict(MINIMAL)
        mapping["release_root"] = "data/pallet/__not_created_yet__"
        mapping["optional_keys"] = ["release_root"]
        with FixtureRepo(mapping) as fx:
            paths = fx.load()
            report = paths.audit()
            self.assertNotIn("release_root", [e["key"] for e in report["missing"]])
            self.assertIn("release_root", [e["key"] for e in report["absent_optional"]])

    def test_audit_is_clean_when_every_path_exists(self):
        with FixtureRepo() as fx:
            report = fx.load().audit()
            self.assertEqual([e["relative"] for e in report["missing"]], [])
            self.assertGreater(len(report["ok"]), 0)

    def test_unknown_key_raises_instead_of_returning_none(self):
        with FixtureRepo() as fx:
            with self.assertRaises(KeyError):
                fx.load().get("no_such_key")

    def test_get_existing_raises_when_path_is_absent(self):
        mapping = dict(MINIMAL)
        mapping["hdri_root"] = "data/pallet/__no_such_dir__"
        with FixtureRepo(mapping) as fx:
            with self.assertRaises(FileNotFoundError):
                fx.load().get_existing("hdri_root")

    def test_get_existing_checks_every_element_of_a_list(self):
        mapping = dict(MINIMAL)
        mapping["pallet_model_roots"] = ["data/pallet/models_usd", "data/pallet/__nope__"]
        with FixtureRepo(mapping) as fx:
            with self.assertRaises(FileNotFoundError):
                fx.load().get_existing("pallet_model_roots")


class Caching(unittest.TestCase):
    def test_same_arguments_return_the_cached_instance(self):
        with FixtureRepo() as fx:
            a = PDP.load(config_path=fx.config_path, project_root=fx.root)
            b = PDP.load(config_path=fx.config_path, project_root=fx.root)
            self.assertIs(a, b)
            PDP.clear_cache()

    def test_clear_cache_forces_a_reload(self):
        with FixtureRepo() as fx:
            a = PDP.load(config_path=fx.config_path, project_root=fx.root)
            PDP.clear_cache()
            b = PDP.load(config_path=fx.config_path, project_root=fx.root)
            self.assertIsNot(a, b)
            PDP.clear_cache()


class RegistryContentRules(unittest.TestCase):
    """실 registry 파일의 *내용 규칙*. 파일시스템 실재는 단언하지 않는다."""

    def setUp(self):
        PDP.clear_cache()
        self.raw = PDP._load_raw(
            os.path.join(PDP.detect_project_root(), PDP.DEFAULT_CONFIG_RELPATH))

    def test_shipped_registry_declares_every_required_key(self):
        for key in PDP.REQUIRED_KEYS:
            self.assertIn(key, self.raw, key)

    def test_shipped_registry_never_points_into_the_empty_target_asset_tree(self):
        # assets/ 는 Stage 2-A 에서 만든 빈 TARGET 뼈대다. registry 가 그쪽을 가리키면
        # 런타임이 조용히 빈 폴더를 읽는다.
        for key, value in self.raw.items():
            if key.startswith("//") or key in ("optional_keys", "assets_root"):
                continue
            for v in (value if isinstance(value, list) else [value]):
                self.assertFalse(str(v).replace("\\", "/").startswith("data/pallet/assets/"),
                                 "%s -> %s" % (key, v))

    def test_shipped_registry_material_roots_name_the_archive_location(self):
        # [확인] v2_realize.py 가 실제로 읽는 위치. registry 는 "가고 싶은 곳"이 아니라
        # "지금 있는 곳"을 담아야 한다.
        self.assertEqual(str(self.raw["pallet_material_root"]).replace("\\", "/"),
                         "data/pallet/archive/textures_wood")
        self.assertEqual(str(self.raw["floor_material_root"]).replace("\\", "/"),
                         "data/pallet/archive/textures_floor")

    def test_shipped_registry_paths_are_repo_relative(self):
        for key, value in self.raw.items():
            if key.startswith("//") or key == "optional_keys":
                continue
            for v in (value if isinstance(value, list) else [value]):
                self.assertFalse(os.path.isabs(str(v)), "%s -> %s" % (key, v))


class CommandLineInterface(unittest.TestCase):
    """`or True` 회귀 방지 — --audit 플래그가 실제로 의미를 가져야 한다."""

    def test_source_has_no_always_true_branch(self):
        src = open(PDP.__file__, encoding="utf-8").read()
        self.assertNotIn("or True", src)

    def _run(self, fx, *args, data_root=None):
        """CLI 를 fixture 안에서만 해석되게 실행한다.

        project_root 는 모듈 파일 위치에서 탐지되므로 --config 만 주면 상대경로가
        **실제 저장소**를 향한다. 그러면 fixture 가 아니라 이 workstation 의 data/pallet
        존재 여부를 검사하게 되어(= clone 에서 결과가 달라진다) 테스트가 의미를 잃는다.
        그래서 항상 --data-root 로 fixture 를 못박는다.

        encoding 을 명시하지 않으면 Windows 콘솔 기본(cp949)으로 디코드해 한글 메시지가 깨진다.
        """
        root = data_root or os.path.join(fx.root, "data", "pallet")
        return subprocess.run(
            [sys.executable, PDP.__file__,
             "--config", fx.config_path, "--data-root", root, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": _BLENDER_DIR},
            cwd=fx.root,
        )

    def test_cli_paths_resolve_inside_the_fixture_not_the_real_repo(self):
        """이 클래스의 나머지 테스트가 실제 data/pallet 을 보고 통과하지 않음을 고정한다."""
        with FixtureRepo() as fx:
            proc = self._run(fx, "--key", "hdri_root")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            printed = proc.stdout.strip()
            self.assertTrue(os.path.normcase(printed).startswith(os.path.normcase(fx.root)),
                            printed)
            repo_root = PDP.detect_project_root()
            self.assertFalse(os.path.normcase(printed).startswith(os.path.normcase(repo_root)),
                             "fixture 가 아니라 실제 저장소 경로를 출력했습니다: " + printed)

    def test_no_argument_prints_the_full_audit_and_exits_zero(self):
        with FixtureRepo() as fx:
            proc = self._run(fx)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("ok=", proc.stdout)
            self.assertIn("missing=0", proc.stdout)

    def test_audit_flag_prints_the_same_report(self):
        with FixtureRepo() as fx:
            plain = self._run(fx).stdout
            flagged = self._run(fx, "--audit").stdout
            self.assertEqual(plain, flagged)

    def test_key_prints_only_that_path(self):
        # project_root 는 모듈 위치에서 탐지되므로, 값 자체를 고정하려면 --data-root 를 쓴다.
        with FixtureRepo() as fx:
            data_root = os.path.join(fx.root, "pinned_root")
            proc = self._run(fx, "--key", "hdri_root", data_root=data_root)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), os.path.join(data_root, "hdri"))
            self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
            self.assertNotIn("ok=", proc.stdout)

    def test_key_of_a_list_prints_one_line_per_element(self):
        with FixtureRepo() as fx:
            proc = self._run(fx, "--key", "pallet_model_roots")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(proc.stdout.strip().splitlines()), 2)

    def test_invalid_key_lists_the_available_keys_on_stderr_and_exits_nonzero(self):
        with FixtureRepo() as fx:
            proc = self._run(fx, "--key", "definitely_not_a_key")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("hdri_root", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_missing_required_path_exits_one(self):
        mapping = dict(MINIMAL)
        mapping["hdri_root"] = "data/pallet/__no_such_dir__"
        with FixtureRepo(mapping) as fx:
            proc = self._run(fx)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("MISSING", proc.stdout)

    def test_absent_optional_path_still_exits_zero(self):
        mapping = dict(MINIMAL)
        mapping["release_root"] = "data/pallet/__not_created_yet__"
        mapping["optional_keys"] = ["release_root"]
        with FixtureRepo(mapping) as fx:
            proc = self._run(fx)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("ABSENT?", proc.stdout)


if __name__ == "__main__":
    unittest.main()
