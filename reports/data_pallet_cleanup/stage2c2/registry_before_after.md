# §14 registry 변경 전후

`config/synthetic/pallet_paths.yaml`

```
key                                 before (Stage 2-C1)                          after (Stage 2-C2)
──────────────────────────────────────────────────────────────────────────────────────────────────────────
production_scene                    blender_scene/synth_data_scene_portable.blend assets/scenes/production/blender_scene/
                                                                                 synth_data_scene_portable_stage2c2.blend
production_scene_stage2c1_rollback  (없음)                                        assets/scenes/production/blender_scene/
                                                                                 synth_data_scene_portable.blend        ← 신규
production_scene_rollback_source    blender_scene/synth_data_scene.blend          assets/scenes/production/blender_scene/
                                                                                 synth_data_scene.blend
production_scene_textures           blender_scene/textures                        assets/scenes/production/blender_scene/textures
experimental_scene                  blender_scene/_sandbox_palletobj_…blend       assets/scenes/production/blender_scene/
                                                                                 _sandbox_palletobj_production.blend
background_root                     data/pallet/background                        assets/scenes/backgrounds/background
background_package_archive          (없음)                                        archive/packages/background_sources    ← 신규
distractor_root                     data/pallet/distractors                       assets/distractors/library
distractor_manifest                 data/pallet/distractors/…manifest.csv         assets/distractors/library/distractors_manifest.csv
──────────────────────────────────────────────────────────────────────────────────────────────────────────
hdri_root / floor_material_root / pallet_material_root / pallet_model_roots /
pallet_measurements / golden_overlay_reference / real_data_root / runs_root /
release_root / archive_root / manifests_root / assets_root / reference_root      **변경 없음**
```

```
audit    before  ok=22 missing=0 absent_optional=0
         after   ok=24 missing=0 absent_optional=0
```

22 → 24 는 신규 키 2개(`production_scene_stage2c1_rollback`, `background_package_archive`).

## rollback 사슬

```
1. production_scene                    synth_data_scene_portable_stage2c2.blend   ← active
2. production_scene_stage2c1_rollback  synth_data_scene_portable.blend            (Stage 2-C1)
3. production_scene_rollback_source    synth_data_scene.blend                     (pre-portable 원본)
```

2·3 은 최종 위치에 함께 있지만 **active 로 쓰지 않는다**:
- 2 는 상대경로가 옛 폴더 배치(`//../distractors`)를 전제하므로 지금 위치에서 열면 356건이 끊긴다.
- 3 은 이 머신 절대경로 228건 + 누락 1건을 그대로 갖고 있다.

`production_scene_stage2c1_rollback` 은 optional 이 아니라 **실재하는 필수 경로**로 관리한다
(audit 에서 missing 이면 실패).

## registry 를 우회하지 않기 위해 한 일

`config/synthetic/blender.yaml` · `blender_train_4000.yaml` 의 배경 자산은
`"filepath": "data/pallet/background/parking_lot/scene.gltf"` 리터럴이었다.
새 절대경로를 다시 박는 대신 **background_root 기준 상대키**로 바꿨다:

```json
"parking_lot": { "kind": "gltf", "relpath": "parking_lot/scene.gltf", ... }
```

`blender_config.py` 가 `relpath` 를 `PALLET_PATHS.get("background_root")` 와 조인한다
(옛 `filepath` 도 계속 읽어 하위호환 유지). 다음 단계에서 배경 폴더가 또 움직여도
registry 한 줄만 바꾸면 된다.
