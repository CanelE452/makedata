"""pallet_data_paths registry resolver 테스트 (Stage 2-A).

이 모듈은 bpy 없이 동작해야 하므로 Blender 밖에서 그대로 돈다.
"""

import json
import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import pallet_data_paths as PDP  # noqa: E402

REPO = os.path.abspath(os.path.join(_BLENDER_DIR, "..", "..", ".."))


def _write_registry(tmpdir, mapping):
    path = os.path.join(tmpdir, "pallet_paths.yaml")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f)
    return path


MINIMAL = {
    "pallet_data_root": "data/pallet",
    "production_scene": "data/pallet/blender_scene/synth_data_scene.blend",
    "background_root": "data/pallet/background",
    "distractor_root": "data/pallet/distractors",
    "distractor_manifest": "data/pallet/distractors/distractors_manifest.csv",
    "hdri_root": "data/pallet/hdri",
    "floor_material_root": "data/pallet/archive/textures_floor",
    "pallet_material_root": "data/pallet/archive/textures_wood",
    "pallet_model_roots": ["data/pallet/models_usd"],
    "golden_overlay_reference": "data/pallet/archive/trunc_addon_v1_pilot",
    "real_data_root": "data/pallet/real_data",
    "runs_root": "data/pallet/runs",
    "release_root": "data/pallet/release",
    "archive_root": "data/pallet/archive",
}


class ModuleIsBpyFree(unittest.TestCase):
    def test_source_never_imports_bpy(self):
        src = open(PDP.__file__, encoding="utf-8").read()
        self.assertNotIn("import bpy", src)

    def test_module_imports_without_bpy_in_sys_modules(self):
        self.assertNotIn("bpy", sys.modules)


class RealRegistry(unittest.TestCase):
    def setUp(self):
        PDP.clear_cache()
        self.paths = PDP.load(use_cache=False)

    def test_every_required_key_is_present(self):
        for key in PDP.REQUIRED_KEYS:
            self.assertIn(key, self.paths, key)

    def test_audit_reports_no_missing_path(self):
        report = self.paths.audit()
        self.assertEqual(
            [e["relative"] for e in report["missing"]], [],
            "registry 가 존재하지 않는 경로를 가리키고 있습니다",
        )

    def test_paths_are_absolute_and_under_project_root(self):
        for key in self.paths.keys():
            value = self.paths.get(key)
            for p in (value if isinstance(value, list) else [value]):
                self.assertTrue(os.path.isabs(p), key)
                self.assertTrue(p.startswith(self.paths.project_root), key)

    def test_relative_is_posix_and_repo_relative(self):
        self.assertEqual(self.paths.relative("hdri_root"), "data/pallet/hdri")
        self.assertEqual(self.paths.relative("pallet_data_root"), "data/pallet")

    def test_material_roots_point_at_the_archive_location_that_code_actually_reads(self):
        # Stage 1 [확인]: v2_realize.py 가 archive/textures_* 를 읽는다.
        # registry 는 "가고 싶은 곳"이 아니라 "지금 있는 곳"을 담아야 한다.
        self.assertEqual(self.paths.relative("pallet_material_root"),
                         "data/pallet/archive/textures_wood")
        self.assertEqual(self.paths.relative("floor_material_root"),
                         "data/pallet/archive/textures_floor")

    def test_registry_does_not_point_into_the_empty_target_asset_tree(self):
        # assets/ 하위는 Stage 2-A 에서 뼈대만 만든 빈 폴더다.
        # 자산 키가 그쪽을 미리 가리키면 런타임이 조용히 빈 폴더를 읽는다.
        for key in ("production_scene", "hdri_root", "distractor_root",
                    "floor_material_root", "pallet_material_root", "background_root"):
            rel = self.paths.relative(key)
            rels = rel if isinstance(rel, list) else [rel]
            for r in rels:
                self.assertFalse(r.startswith("data/pallet/assets/"),
                                 "%s 가 아직 비어 있는 TARGET 트리를 가리킵니다: %s" % (key, r))

    def test_project_root_detection_finds_the_repo(self):
        self.assertEqual(os.path.normcase(PDP.detect_project_root()),
                         os.path.normcase(REPO))


class RootOverride(unittest.TestCase):
    def setUp(self):
        PDP.clear_cache()

    def tearDown(self):
        os.environ.pop(PDP.ROOT_ENV_VAR, None)
        PDP.clear_cache()

    def test_env_var_overrides_only_the_root_and_rebuilds_children(self):
        os.environ[PDP.ROOT_ENV_VAR] = "somewhere/else"
        paths = PDP.load(use_cache=False)
        self.assertEqual(paths.relative("pallet_data_root"), "somewhere/else")
        self.assertEqual(paths.relative("hdri_root"), "somewhere/else/hdri")
        self.assertEqual(paths.relative("distractor_manifest"),
                         "somewhere/else/distractors/distractors_manifest.csv")

    def test_argument_override_matches_env_behaviour(self):
        paths = PDP.load(data_root="somewhere/else", use_cache=False)
        self.assertEqual(paths.relative("runs_root"), "somewhere/else/runs")

    def test_absolute_root_override_is_kept_absolute(self):
        other = os.path.join(REPO, "reports")
        paths = PDP.load(data_root=other, use_cache=False)
        self.assertEqual(os.path.normcase(paths.get("pallet_data_root")),
                         os.path.normcase(other))


class SeparatorHandling(unittest.TestCase):
    def test_backslash_registry_values_are_accepted(self):
        import tempfile

        mapping = dict(MINIMAL)
        mapping["hdri_root"] = "data\\pallet\\hdri"
        mapping["pallet_data_root"] = "data\\pallet"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_registry(tmp, mapping)
            paths = PDP.load(config_path=cfg, project_root=REPO, use_cache=False)
            self.assertEqual(paths.relative("hdri_root"), "data/pallet/hdri")
            self.assertTrue(os.path.isdir(paths.get("hdri_root")))

    def test_relative_output_is_always_posix(self):
        paths = PDP.load(use_cache=False)
        for key in paths.keys():
            rel = paths.relative(key)
            for r in (rel if isinstance(rel, list) else [rel]):
                self.assertNotIn("\\", r, key)


class MissingAndOptional(unittest.TestCase):
    def test_missing_required_key_raises_on_load(self):
        import tempfile

        mapping = dict(MINIMAL)
        del mapping["hdri_root"]
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_registry(tmp, mapping)
            with self.assertRaises(KeyError):
                PDP.load(config_path=cfg, project_root=REPO, use_cache=False)

    def test_nonexistent_path_is_reported_missing_not_silently_substituted(self):
        import tempfile

        mapping = dict(MINIMAL)
        mapping["hdri_root"] = "data/pallet/__no_such_dir__"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_registry(tmp, mapping)
            paths = PDP.load(config_path=cfg, project_root=REPO, use_cache=False)
            report = paths.audit()
            missing = [e["key"] for e in report["missing"]]
            self.assertIn("hdri_root", missing)
            # fallback 으로 다른 경로를 돌려주지 않는다
            self.assertTrue(paths.get("hdri_root").endswith("__no_such_dir__"))

    def test_optional_key_absence_is_not_missing(self):
        import tempfile

        mapping = dict(MINIMAL)
        mapping["release_root"] = "data/pallet/__not_created_yet__"
        mapping["optional_keys"] = ["release_root"]
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_registry(tmp, mapping)
            paths = PDP.load(config_path=cfg, project_root=REPO, use_cache=False)
            report = paths.audit()
            self.assertNotIn("release_root", [e["key"] for e in report["missing"]])
            self.assertIn("release_root", [e["key"] for e in report["absent_optional"]])

    def test_unknown_key_raises_instead_of_returning_none(self):
        paths = PDP.load(use_cache=False)
        with self.assertRaises(KeyError):
            paths.get("no_such_key")

    def test_get_existing_raises_when_path_is_absent(self):
        import tempfile

        mapping = dict(MINIMAL)
        mapping["hdri_root"] = "data/pallet/__no_such_dir__"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_registry(tmp, mapping)
            paths = PDP.load(config_path=cfg, project_root=REPO, use_cache=False)
            with self.assertRaises(FileNotFoundError):
                paths.get_existing("hdri_root")


class ConsumersUseTheRegistry(unittest.TestCase):
    """registry 를 배선한 모듈이 실제로 같은 경로를 쓰는지 확인."""

    def test_distractor_pool_manifest_matches_registry(self):
        import distractor_pool_v2 as dpool

        expected = PDP.load(use_cache=False).get("distractor_manifest")
        self.assertEqual(os.path.normcase(os.path.abspath(dpool.DEFAULT_MANIFEST)),
                         os.path.normcase(expected))

    def test_v2_pipeline_manifest_matches_registry(self):
        import v2_pipeline

        expected = PDP.load(use_cache=False).get("distractor_manifest")
        self.assertEqual(os.path.normcase(os.path.abspath(v2_pipeline.DEFAULT_MANIFEST)),
                         os.path.normcase(expected))

    def test_distractor_pool_still_loads_the_full_209_pool(self):
        import distractor_pool_v2 as dpool

        rows = dpool.load_pool()
        self.assertGreaterEqual(len(rows), 200)


if __name__ == "__main__":
    unittest.main()
