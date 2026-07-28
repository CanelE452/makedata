# data/pallet 제안 폴더 구조 (Stage 1 — 계획 전용, 이동 0건)

- 생성일: 2026-07-28
- 조사 대상: `E:/CODING/GitHub/FoundationPose/data/pallet` (전체 gitignored — `.gitignore:5 data/`)
- 규모: **디렉토리 2,489 / 파일 363,015 / 191.02 GB**
- 이 문서는 **제안**이다. 이번 단계에서 폴더를 만들지 않았고 파일을 옮기지 않았다.

---

## 1. 현재 구조 (실측, depth 1~2 요약)

```
data/pallet/                                    191.02 GB   363,015 f   2,489 dir
│
├── [최상위 파일 68개]                            85.30 GB        68 f
│     ├── *.zip            ×15                   85.29 GB   (데이터셋 패키징본 — archive/ 추출본과 중복)
│     ├── *.log            ×35                    0.005GB   (생성 로그, 2026-04~07)
│     ├── *.py             ×11                    0.00 GB   (data 트리에 방치된 일회성 스크립트, 2026-05)
│     ├── *_log.txt        × 4 + _floor_catalog.png
│     └── _DISTRIBUTION_EXCLUDE.txt              (릴리스 제외 목록 = 라이선스 게이트 근거)
│
├── archive/                                     89.80 GB   328,942 f   ★ 실제로는 "현역+legacy 혼재"
│     ├── textures_floor/          0.675GB   ← v2_realize.py:804 가 하드코딩으로 읽는 현역 자산
│     ├── textures_wood/           0.315GB   ← v2_realize.py:768 가 하드코딩으로 읽는 현역 자산
│     ├── trunc_addon_v1_pilot/    0.283GB   ← tests/test_overlay_archive_trunc_style.py:42 golden fixture
│     ├── _noai_quarantine_usd/    0.001GB   ← NoAI 격리 보관(ledger:60) — 이동 금지
│     ├── train_palletobj_v1/v2/v3, train_palletobj_addon_v1,
│     │   train_4pallet_mask_v1, trunc_addon_v1,
│     │   training_data, training_data_v4*, test_blender_v1..v70,
│     │   test_indoor_v1 …                 (구 학습셋 렌더 산출물, 코드 참조 0)
│     └── _mask_test*/_mat_test*/_floor_*/_wood_skin_compare/_efront_12kp_check … (구 실험)
│
├── blender_scene/                                3.12 GB       171 f
│     ├── synth_data_scene.blend    0.359GB  ★ v2 production 씬 정본 (35 참조)
│     ├── textures/                 0.064GB  (blend 내부 상대참조 대상)
│     ├── _sandbox_palletobj_production.blend     (run_addon_v1.sh:56)
│     └── *.blend1 / POSTBAKE_CLEAN / PREBAKE_BACKUP / REBAKE_WIP / scene12 / scene121 / _indoor
│
├── isaac_assets/                                 4.35 GB     4,543 f   ← UNIDENTIFIED (근거 충돌)
├── distractors/                                  1.96 GB     1,161 f   ★ 209종 occluder + manifest
├── background/                                   0.29 GB        77 f   ★ parking_lot/scene.gltf
├── hdri/                                         0.20 GB        33 f   ★ Poly Haven CC0 30종
├── models_usd/                                   0.08 GB        21 f   ★ USD 팔레트 원본
├── pallets_v2_add/                               0.005GB        14 f   ★ v2 신규 목재 2종 + measurements
├── real_data/                                    0.15 GB     1,924 f   실촬영 D435i (본인 IP)
├── eval_results/                                 0.01 GB       103 f   2026-04 평가 산출물
├── logs/                                         0.001GB        49 f   4pallet_mask 생성 통계
├── v2_dryrun_audit/                              0.00 GB         8 f
├── _tmp_ph/                                      0.00 GB         6 f   Poly Haven 다운로드 provenance
│
└── _v2_* 런 디렉토리 ×158                          5.9 GB    24,000+ f
      ├── _v2_scene_logic_probe_seed7500_* ×90    (1~20 프레임 진단 probe, 대부분 참조 0)
      ├── _v2_scene_logic_smoke20_* ×27           (smoke)
      ├── _v2_scene_logic_500_seed7500            1.70GB  ★ EDA 정본 (78 참조)
      ├── _v2_pilot_2k                            2.50GB  ★ pilot_frames.csv (17 참조)
      ├── _v2_smoke50_9d                          0.18GB  ★ 최신 리포트 근거 (57 참조)
      ├── _v2_calib_200 / _v2_b3_check / _v2_g5_reverify / _v2_ph7_* / _v2_publicmask_overlay_smoke8
      └── *_failed_* ×5                           (실패 run, 사유·날짜가 폴더명에 있음)
```

**빈 디렉토리 400개** (주로 `*/logs`, `*/overlay`, `*/mask` 스켈레톤) — 이동 대상에서 자동 제외 대상.

---

## 2. 제안 구조 (현재 파일에 맞춰 축소·조정한 안)

기본 후보 트리에서 **현재 실제 파일이 없는 하위폴더는 제외**했다
(`release/`, `manifests/`, `reference/camera_calibration/`, `assets/pallets/blender_baked/` 등).

```
data/pallet/
├── README.md                                (신규 — 각 폴더 규칙 + 이동 이력)
│
├── assets/                                  재사용 자산 (실행마다 읽히는 것만)
│   ├── pallets/
│   │   ├── source_models/                   ← models_usd/ (scene.usd, scene_1.usd, scene_noemit.usd, *.glb)
│   │   │   └── v2_add/                      ← pallets_v2_add/models/ + measurements.json + silhouettes
│   │   └── metadata/                        ← models_usd/_scale_report.txt, _shader_report.txt, _shape_inspect/
│   ├── scenes/
│   │   ├── production/                      ← blender_scene/synth_data_scene.blend + textures/  (동반 이동 필수)
│   │   ├── backgrounds/                     ← background/{parking_lot, modular_buildings_industrial_area}/
│   │   └── experimental/                    ← blender_scene/_sandbox_palletobj_production.blend
│   ├── distractors/
│   │   ├── models/                          ← distractors/{large,medium,small,road,indoor}/
│   │   ├── manifest/                        ← distractors_manifest.csv
│   │   └── metadata/                        ← _measurements.json, _gso_expansion_classmap.json, 몽타주 png
│   ├── materials/
│   │   ├── pallet/                          ← archive/textures_wood/      (현역! 코드 수정 동반)
│   │   └── floor/                           ← archive/textures_floor/     (현역! 코드 수정 동반)
│   ├── lighting/
│   │   └── hdri/                            ← hdri/ (+ LICENSE.txt, SOURCES.txt)
│   └── licenses/                            ← 각 폴더 LICENSE/SOURCES 사본 + _tmp_ph/(Poly Haven CDN provenance)
│
├── runs/                                    생성 run 산출물
│   ├── smoke/                               ← _v2_scene_logic_smoke20_*, _v2_smoke20_9c_*, _v2_smoke50_9d,
│   │                                            _v2_publicmask_overlay_smoke8
│   ├── pilot/                               ← _v2_pilot_2k, _v2_calib_200
│   ├── diagnostics/
│   │   ├── v2_scene_logic_probes/           ← _v2_scene_logic_probe_* (×90, 대량)
│   │   ├── v2_scene_logic_500_seed7500/     ← EDA 정본
│   │   └── (그 외) _v2_b3_check, _v2_g5_reverify, _v2_ph7_*, _v2_statefix_*, v2_dryrun_audit
│   ├── production/                          (현재 해당 없음 — 40k 본생성 산출물이 들어올 자리)
│   └── failed/                              ← *_failed_*_20260726 ×5
│
├── reference/                               검증 정본
│   ├── golden_overlay/                      ← archive/trunc_addon_v1_pilot/   (테스트 fixture)
│   ├── real_images/                         ← real_data/ (1,924 jpg)
│   └── expected_outputs/                    ← _trunc_addon_v1_{10m,far}_example/
│
├── archive/                                 보관 (실행 경로에서 완전히 분리된 것만)
│   ├── legacy_datasets/                     ← archive/train_*, training_data*, test_blender_v*, test_indoor_v1
│   │   └── _packaged/                       ← 최상위 *.zip ×15  (추출본과 중복 — 근거는 duplicate_groups.csv)
│   │       └── _corrupt/                    ← train_palletobj_v1.zip (BadZipFile)
│   ├── legacy_scenes/                       ← blender_scene 백업 blend 9종
│   │   └── rebake_20260724/                 ← POSTBAKE_CLEAN / PREBAKE_BACKUP / REBAKE_WIP
│   ├── legacy_assets/                       ← distractors_manifest.csv.bak_prefill 등
│   ├── superseded_runs/                     ← archive/_mask_test*/_mat_test*/_floor_*/eval_results/logs
│   ├── quarantine_noai/                     ← (이동 금지) archive/_noai_quarantine_usd/ 는 현 위치 유지
│   └── unidentified/                        ← (이번 단계 이동 없음) isaac_assets, _floor_catalog.png
│
└── _staging/                                ← 최상위 *.log ×35, *.py ×11 임시 격리
```

### 기본 후보 트리에서 뺀 것과 이유

```
제외 항목                       이유
──────────────────────────────────────────────────────────────────────────────
release/{datasets,attribution,packaging}   현재 릴리스 산출물 0개. _DISTRIBUTION_EXCLUDE.txt 만 존재
                                           → 릴리스 스크립트 작성 시점에 만든다(빈 폴더 선생성 금지)
manifests/                                 manifest 실체는 distractors/ 1개뿐 → assets/distractors/manifest/ 로 충분
reference/camera_calibration/              data/pallet 아래 camera intrinsic 파일 없음(config/synthetic/blender.yaml 내부에 존재)
assets/pallets/{meshes,blender_baked}/     pallet mesh(pallet_full.obj)는 data/palletobj/ 소관, baked 는 .blend 내부
assets/materials/miscellaneous/            해당 파일 없음
archive/unidentified/                      UNIDENTIFIED 2건은 규칙7에 따라 이동계획 자체에서 제외 → 폴더 불필요
```

---

## 3. 이동 전 반드시 선행해야 하는 것

1. **`config/paths.yaml` 경로 registry 도입** (7절 참조) — 그 전에 자산을 옮기면
   `config/synthetic/*.yaml` 3개 + `scripts/data_prep/blender/*.py` 다수를 개별 수정해야 한다.
2. **`.blend` 내부 외부 텍스처 경로 처리** — `synth_data_scene.blend` 와 `textures/` 는
   반드시 같은 상대 위치를 유지한 채 동반 이동해야 한다.
3. **`_DISTRIBUTION_EXCLUDE.txt` 동시 갱신** — 이 파일의 5개 경로 중 **5개 전부가 이미 현재 위치와 불일치**
   (`_noai_quarantine_usd/`, `_efront_12kp_check/` 등이 `archive/` 아래로 내려감).
   이동하면서 갱신하지 않으면 릴리스 제외 게이트가 무력화된다.
