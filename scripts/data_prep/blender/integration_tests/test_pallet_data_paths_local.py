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

    def test_real_data_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("real_data_root")))

    def test_runs_root_exists(self):
        self.assertTrue(os.path.isdir(self.paths.get("runs_root")))

    def test_registry_does_not_point_into_the_empty_target_asset_tree(self):
        assets_root = self.paths.get("assets_root")
        for key in self.paths.keys():
            if key == "assets_root":
                continue
            value = self.paths.get(key)
            for p in (value if isinstance(value, list) else [value]):
                self.assertFalse(
                    os.path.normcase(p).startswith(os.path.normcase(assets_root) + os.sep),
                    "%s 가 아직 비어 있는 TARGET 트리를 가리킵니다: %s" % (key, p))

    def test_the_target_asset_tree_is_still_empty_of_data_files(self):
        # 자산은 Stage 2-B 에서 옮긴다. 지금 채워져 있으면 registry 와 실제가 어긋난 것이다.
        assets_root = self.paths.get("assets_root")
        stray = []
        for dirpath, _dirnames, filenames in os.walk(assets_root):
            for name in filenames:
                if name != "README.md":
                    stray.append(os.path.join(dirpath, name))
        self.assertEqual(stray[:5], [], "assets/ 에 예상치 못한 파일이 있습니다")


if __name__ == "__main__":
    unittest.main()
