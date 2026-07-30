# §5 남은 data/pallet 구조 (depth 1/2)

```
data/pallet   2,560 dirs / 363,090 files / 192,468,045,942 bytes (179.25 GB)
```

## 정리 완료 영역 — 내용 재감사 제외 [판정]

```
assets/       Stage 2-B/2-C2 완료. registry 가 직접 가리키는 현역 자산
reference/    Stage 2-B 완료. golden overlay + real images
runs/         Stage 2-A 완료. smoke/diagnostics/failed
release/      비어 있음 (뼈대)
manifests/    로컬 inventory snapshot
```

참조 그래프·registry 보호 검사에는 포함했고, 파일 내용 재감사만 제외했다.

## 감사 대상 — 최상위 85 entries / 170.34 GB

```
entry                                    type   files       GB   flags     분류
─────────────────────────────────────────────────────────────────────────────────────────────
archive                                  dir   327,647   82.589  ZIP       (아래 별도)
pallet.zip                               file        1   15.495  ZIP       PACKAGE_BUNDLE
train_palletobj_v3.zip                   file        1    9.732  ZIP       PACKAGE_STRUCTURAL_MATCH
train_4pallet_mask_v1.zip                file        1    9.011  ZIP       PACKAGE_STRUCTURAL_MATCH (NoAI)
train_palletobj_v2.zip                   file        1    7.773  ZIP       PACKAGE_STRUCTURAL_MATCH
train_palletobj_v2 (2).zip               file        1    7.750  ZIP       PACKAGE_STRUCTURAL_MATCH
train_palletobj_v1 (2).zip               file        1    7.746  ZIP       PACKAGE_STRUCTURAL_MATCH
train_palletobj_addon_v1.zip             file        1    5.261  ZIP       PACKAGE_STRUCTURAL_MATCH
trunc_addon_v1.zip                       file        1    5.063  ZIP       PACKAGE_STRUCTURAL_MATCH
train_palletobj_v1.zip                   file        1    4.218  ZIP       ★ CORRUPT_PACKAGE
isaac_assets                             dir     4,543    4.052  LIC       LICENSE_QUARANTINE
test_blender_v69.zip                     file        1    3.403  ZIP       PACKAGE_STRUCTURAL_MATCH
_v2_pilot_2k                             dir    12,147    2.324  DS,REC    ACTIVE_RUNTIME (analyze 정본)
test_blender_v64.zip                     file        1    1.659  ZIP       PACKAGE_STRUCTURAL_MATCH
_v2_scene_logic_500_seed7500             dir     4,995    1.582  DS,REC    ACTIVE_RUNTIME (EDA 정본)
test_blender_v70.zip / v68 / indoor_v1   file        3    2.243  ZIP       PACKAGE_STRUCTURAL_MATCH
_v2_smoke50_9d                           dir       616    0.170  DS,REC    ACTIVE_RUNTIME (픽셀 비교)
_v2_calib_200                            dir     1,011    0.131  DS,REC    ACTIVE_RUNTIME
test_blender_v65.zip                     file        1    0.081  ZIP       PACKAGE_STRUCTURAL_MATCH
_v2_publicmask_overlay_smoke8            dir        96    0.018  DS,REC    ACTIVE_RUNTIME (리포트 근거)
_v2_g5_reverify / _v2_b3_check           dir       102    0.020            ACTIVE_RUNTIME (전용 출력)
eval_results                             dir       103    0.011            COLD_ARCHIVE
v2_dryrun_audit                          dir         8    0.000            ACTIVE_RUNTIME (DEFAULT_OUT)
logs · _tmp_ph · _trunc_addon_v1_*_example         59    0.002            COLD_ARCHIVE
로그·스크립트 단독 파일 (~50개)           file       50   ~0.006            COLD_ARCHIVE
_DISTRIBUTION_EXCLUDE.txt · README.md    file        2    0.000            ACTIVE_RUNTIME
```

`_v2_*` 폴더 8종은 Stage 2-A 가 **원위치 유지**로 결정한 것들이다(코드가 그 경로를 직접
출력·입력으로 쓴다). 이번 감사에서도 그 판정을 유지한다.

## archive/ 166 entries / 82.589 GB

```
role                          entries   비고
────────────────────────────────────────────────────────────────────────────────────
LEGACY_DATASET_OR_RUN            156    dataset·run 폴더가 depth 1 에 평평하게 놓여 있음
STAGE2A_SKELETON (빈 폴더)          7    corrupt · legacy_assets · legacy_datasets ·
                                        legacy_scenes · nonredistributable ·
                                        superseded_runs · unidentified  ← 전부 0 파일
PACKAGE_STORE                      1    packages/ (background_sources 3파일)
LICENSE_QUARANTINE                 1    _noai_quarantine_usd (3파일)
DOC                                1    README.md
```

★ **Stage 2-A 가 만든 semantic 하위폴더 7개는 아직 비어 있다.** "archive/legacy_datasets
87.7GB" 는 계획된 목적지 이름이었고, 실제 dataset 은 `archive/` 최상단에 있다.
Stage 2-D1 이 채워야 할 곳이 그 7개다.

원자료: `remaining_top_level_inventory.csv` · `remaining_archive_inventory.csv`
