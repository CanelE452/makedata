"""pallet_data_paths — 이 workstation 의 실제 data/pallet 을 검사하는 integration test.

`data/pallet` 은 gitignored 라 새 clone 에는 없다. 그래서 이 파일은 기본 pytest
collection(`scripts/data_prep/blender/tests`)에 **들어가지 않는 별도 디렉토리**에 있고,
환경변수를 켰을 때만 돈다. 조용한 skip 을 만들지 않으려는 배치다 — 켜면 전부 돌고,
안 켜면 애초에 수집되지 않는다.

실행:

    # bash
    PALLET_DATA_INTEGRATION=1 python -m pytest \
        scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py -q

    # PowerShell
    $env:PALLET_DATA_INTEGRATION="1"
    python -m pytest scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py -q

환경변수 없이 실행하면 수집 시점에 명확한 오류로 중단한다(skip 아님).
"""

import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_THIS_DIR)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

ENV_FLAG = "PALLET_DATA_INTEGRATION"

if os.environ.get(ENV_FLAG) != "1":
    raise RuntimeError(
        "이 파일은 로컬 data/pallet 이 있는 workstation 전용 integration test 입니다.\n"
        "  %s=1 을 설정하고 실행하세요.\n"
        "  예: %s=1 python -m pytest %s -q"
        % (ENV_FLAG, ENV_FLAG, os.path.relpath(__file__).replace(os.sep, "/"))
    )

import pallet_data_paths as PDP  # noqa: E402
import distractor_pool_v2 as dpool  # noqa: E402
import mask_profiles as MP  # noqa: E402  (레이아웃 상수 확인용)


EXPECTED_DISTRACTOR_POOL = 209


class RegistryResolvesToRealFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PDP.clear_cache()
        cls.paths = PDP.load(use_cache=False)
        cls.report = cls.paths.audit()

    def test_audit_reports_no_missing_path(self):
        self.assertEqual(
            [e["relative"] for e in self.report["missing"]], [],
            "registry 가 존재하지 않는 경로를 가리키고 있습니다",
        )

    def test_production_scene_exists(self):
        self.assertTrue(os.path.isfile(self.paths.get("production_scene")))

    def test_production_scene_textures_exist_next_to_the_blend(self):
        blend = self.paths.get("production_scene")
        textures = self.paths.get("production_scene_textures")
        self.assertTrue(os.path.isdir(textures))
        # blend 내부 상대참조(//textures/)가 성립하려면 같은 폴더여야 한다.
        self.assertEqual(os.path.normcase(os.path.dirname(blend)),
                         os.path.normcase(os.path.dirname(textures)))
        self.assertTrue(os.listdir(textures), "textures 폴더가 비어 있습니다")

    def test_background_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("background_root")))

    def test_distractor_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("distractor_root")))

    def test_distractor_manifest_exists(self):
        self.assertTrue(os.path.isfile(self.paths.get("distractor_manifest")))

    def test_distractor_pool_is_exactly_209(self):
        rows = dpool.load_pool()
        self.assertEqual(len(rows), EXPECTED_DISTRACTOR_POOL)

    def test_distractor_pool_uses_the_registry_path(self):
        self.assertEqual(os.path.normcase(os.path.abspath(dpool.DEFAULT_MANIFEST)),
                         os.path.normcase(self.paths.get("distractor_manifest")))

    def test_v2_pipeline_uses_the_registry_path(self):
        import v2_pipeline

        self.assertEqual(os.path.normcase(os.path.abspath(v2_pipeline.DEFAULT_MANIFEST)),
                         os.path.normcase(self.paths.get("distractor_manifest")))

    def test_hdri_root_exists_and_has_hdr_files(self):
        root = self.paths.get("hdri_root")
        self.assertTrue(os.path.isdir(root))
        self.assertTrue([n for n in os.listdir(root) if n.lower().endswith(".hdr")])

    def test_floor_material_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("floor_material_root")))

    def test_pallet_material_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("pallet_material_root")))

    def test_material_roots_match_what_blender_config_resolves(self):
        import blender_config as cfg

        self.assertEqual(os.path.normcase(cfg.WOOD_TEXTURE_DIR),
                         os.path.normcase(self.paths.get("pallet_material_root")))
        self.assertEqual(os.path.normcase(cfg.FLOOR_TEXTURE_DIR),
                         os.path.normcase(self.paths.get("floor_material_root")))

    def test_every_pallet_model_root_exists(self):
        for root in self.paths.get("pallet_model_roots"):
            self.assertTrue(os.path.isdir(root), root)

    def test_golden_overlay_reference_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("golden_overlay_reference")))

    def test_golden_overlay_reference_has_the_sample_the_tests_pin(self):
        root = self.paths.get("golden_overlay_reference")
        sample = os.path.join(root, "overlay", "000000.png")
        self.assertTrue(os.path.isfile(sample),
                        "golden fixture 가 없으면 overlay 테스트가 조용히 SKIP 된다: " + sample)
        self.assertTrue([n for n in os.listdir(root) if n.endswith(".json")],
                        "golden reference 에 label JSON 이 없습니다")

    def test_golden_overlay_pixel_test_is_not_skipped_here(self):
        """clone-safe unit 에서는 skipUnless 로 넘어가지만, 로컬에서는 반드시 실행돼야 한다."""
        import importlib.util

        tests_dir = os.path.join(_BLENDER_DIR, "tests")
        spec = importlib.util.spec_from_file_location(
            "test_overlay_archive_trunc_style",
            os.path.join(tests_dir, "test_overlay_archive_trunc_style.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("test_overlay_archive_trunc_style", mod)
        spec.loader.exec_module(mod)
        self.assertTrue(mod.ARCHIVE_SAMPLE.exists(),
                        "golden 픽셀 테스트가 skip 된다: %s" % mod.ARCHIVE_SAMPLE)
        self.assertEqual(os.path.normcase(str(mod.ARCHIVE_SAMPLE.parent.parent)),
                         os.path.normcase(self.paths.get("golden_overlay_reference")),
                         "golden 테스트가 registry 가 아닌 다른 경로를 본다")

    def test_real_data_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("real_data_root")))

    def test_runs_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("runs_root")))

    def test_registry_never_names_a_bare_container_root(self):
        """Stage 2-A 에서는 'assets/ 를 가리키면 빈 폴더를 읽는다'가 불변식이었다.

        Stage 2-B 로 자산이 실제로 들어왔으므로 불변식이 바뀐다: 이제 금지 대상은
        컨테이너 루트 자체(assets/ · reference/)를 가리키는 것이다. leaf 없이 루트를
        가리키면 런타임이 여러 자산군을 한 폴더로 착각한다.
        """
        bare = {os.path.normcase(self.paths.get("assets_root")),
                os.path.normcase(self.paths.get("reference_root"))}
        for key in self.paths.keys():
            if key in ("assets_root", "reference_root"):
                continue
            value = self.paths.get(key)
            for p in (value if isinstance(value, list) else [value]):
                self.assertNotIn(os.path.normcase(p).rstrip(os.sep), bare,
                                 "%s 가 컨테이너 루트를 그대로 가리킵니다: %s" % (key, p))

    def test_stage2b_moved_assets_now_live_under_assets_or_reference(self):
        """Stage 2-B 에서 옮긴 7개 자산이 실제로 새 트리 아래에 있고 비어 있지 않다."""
        assets_root = os.path.normcase(self.paths.get("assets_root"))
        reference_root = os.path.normcase(self.paths.get("reference_root"))
        moved = {
            "pallet_material_root": assets_root,
            "floor_material_root": assets_root,
            "hdri_root": assets_root,
            "golden_overlay_reference": reference_root,
            "real_data_root": reference_root,
        }
        for key, root in moved.items():
            p = self.paths.get(key)
            self.assertTrue(os.path.normcase(p).startswith(root + os.sep),
                            "%s 가 아직 새 트리 밖입니다: %s" % (key, p))
            self.assertTrue(os.listdir(p), "%s 가 비어 있습니다: %s" % (key, p))
        for p in self.paths.get("pallet_model_roots"):
            self.assertTrue(os.path.normcase(p).startswith(assets_root + os.sep), p)
            self.assertTrue(os.listdir(p), p)

    def test_no_registry_key_still_points_at_a_stage2b_source_location(self):
        """이동한 자산의 옛 경로가 registry 에 남아 있지 않은지."""
        old = [
            "data/pallet/archive/textures_wood", "data/pallet/archive/textures_floor",
            "data/pallet/archive/trunc_addon_v1_pilot", "data/pallet/real_data",
            "data/pallet/hdri", "data/pallet/models_usd", "data/pallet/pallets_v2_add",
        ]
        for key in self.paths.keys():
            rel = self.paths.relative(key)
            for r in (rel if isinstance(rel, list) else [rel]):
                for o in old:
                    self.assertFalse(r == o or r.startswith(o + "/"),
                                     "%s 가 이동 전 경로를 가리킵니다: %s" % (key, r))

    def test_the_old_source_locations_are_gone(self):
        for rel in ("archive/textures_wood", "archive/textures_floor",
                    "archive/trunc_addon_v1_pilot", "real_data", "hdri",
                    "models_usd", "pallets_v2_add"):
            p = os.path.join(self.paths.get("pallet_data_root"), rel.replace("/", os.sep))
            self.assertFalse(os.path.exists(p), "이동했는데 원본이 남아 있습니다: " + p)


if __name__ == "__main__":
    unittest.main()
