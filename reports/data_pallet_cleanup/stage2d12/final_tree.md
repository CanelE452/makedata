# Stage 2-D1.2 최종 구조 감사

전수 조사: `data/pallet` depth 1 + `archive/` depth 1~3 = **277 entry** (`final_tree.csv`)

D1.1 은 depth 1~3(233 entry)까지만 봤다. D1.2 의 목적지는 semantic 컨테이너의 **손자**
(예: `archive/legacy_datasets/noai_baked/training_data`)라 depth 3 까지만 보면 이번에
옮긴 것이 하나도 안 보인다. **depth 4 를 추가**했다(+51 entry).

```
depth   n     내용
──────────────────────────────────────────────────────────────
1      74     data/pallet/*
2     144     archive/*
3       8     archive/{packages,legacy_datasets,legacy_scenes}/*
4      51     그 컨테이너의 자식 = 옮겨진 package·dataset·blend
──────────────────────────────────────────────────────────────
      277
```

## 분류 전수

```
분류                          n    files      MiB          성격
──────────────────────────────────────────────────────────────────────────────────
EXPECTED_ROOT                 6   339,353   175,032.03    권장 구조 6폴더
SEMANTIC_CONTAINER            9   323,581   171,417.52    2-A 뼈대 / D1·D1.1·D1.2 가 채움
MOVED_BY_LEDGER              51   323,580   167,097.92    원장이 옮긴 결과 위치
RESIDUAL_DATASET_DIR        107   326,464   163,552.22    archive/ 미정리 (이번 범위 아님)
RESIDUAL_DIAGNOSTIC_RUN      44    20,187     4,808.78    진단·중간 산출물 (_ 접두)
KEEP_QUARANTINE               1     4,543     4,149.13    isaac_assets (NVIDIA EULA)
RESIDUAL_OUTPUT_DIR           3       160        12.14    도구 출력 디렉토리
RESIDUAL_LOG                 40        40         8.30    생성·렌더 로그
RESIDUAL_DIAGNOSTIC_IMAGE     1         1         0.95    _floor_catalog.png
PLAN_ROW_KEEP_QUARANTINE      1         3         0.70    _noai_quarantine_usd (B1)
RESIDUAL_ONE_OFF_SCRIPT      11        11         0.03    일회성 repack/zip 스크립트
MANAGEMENT_FILE               2         2         0.01    README · _DISTRIBUTION_EXCLUDE
RESIDUAL_FILE                 1         1         0.01    기타 파일
```

(계층이 겹치므로 files/bytes 는 합산하면 중복된다 — depth 1 합계가 363,090 파일 /
179.25 GiB 로 실제 총량이다.)

```
★ UNKNOWN / 미분류               0
분류되지 않은 top-level ZIP       0
역할 불명 dataset                 0
current path / old path 중복      0
이동 완료 source 잔존             0
```

## archive/ semantic 컨테이너 (depth 3)

```
컨테이너                              files       MiB      채운 단계
────────────────────────────────────────────────────────────────────────────
packages/background_sources               3     150.12    2-C2 C2A
packages/dataset_bundles                 14  77,020.15    2-D1  D1A
packages/corrupt                          1   4,319.60    2-D1  D1B (BadZipFile 보존)
legacy_datasets/redistributable      193,564  44,668.03    2-D1  D1C + ★2-D1.2 D12B (+2)
legacy_datasets/noai_baked           129,746  38,456.79    2-D1  D1C + ★2-D1.2 D12B/D12C (+5)
legacy_datasets/partial                 241      62.07    2-D1  D1C
legacy_scenes/snapshots                   7   1,567.30    2-D1.1 D11A + ★2-D1.2 D12B (+1)
legacy_scenes/blender_backups             4     853.86    2-D1.1 D11A
```

`.blend` 는 `snapshots/`, `.blend1`(autosave 백업)은 `blender_backups/` — D1.1 이 정한
확장자 규칙을 D1.2 도 따랐다. `_sandbox_parking_lot_check` 의 `.blend`(D1.2)와
`.blend1`(D1.1)이 서로 다른 폴더에 있는 것은 이 규칙 때문이지 모순이 아니다 [확인].

## NoAI baked 8종이 한곳에 모였다

```
archive/legacy_datasets/noai_baked/
├── training_data                        34,704  6,435,540,124   ★D1.2 D12B
├── training_data_v4                      D1 D1C
├── training_data_v4_split                D1 D1C
├── train_4pallet_mask_v1                 D1 D1C
├── training_data_v4_split_GREYBUG       15,051  5,291,018,327   ★D1.2 D12C
├── training_data_v4_split_bg1bak        15,056  5,288,678,749   ★D1.2 D12C
├── training_data_v4_emptywood            9,031  4,820,265,222   ★D1.2 D12C
└── training_data_v4_pilotA                 482    188,826,895   ★D1.2 D12C
```

8종 전부 `_DISTRIBUTION_EXCLUDE.txt` 에 등재 (entries 16 / problems 0 / leaks 0 / stale 0).

## 남은 것 — 이번 범위가 **아니다**

### depth 1: 권장 구조 밖 65개 (4.27 GiB)

```
분류                        n    MiB        성격
──────────────────────────────────────────────────────────────
RESIDUAL_DIAGNOSTIC_RUN    10   4,349.29   _v2_* · _tmp_ph · _trunc_*_example
RESIDUAL_OUTPUT_DIR         3      12.14   eval_results · logs · v2_dryrun_audit
RESIDUAL_LOG               40       8.30   생성·렌더 로그
RESIDUAL_DIAGNOSTIC_IMAGE   1       0.95   _floor_catalog.png
RESIDUAL_ONE_OFF_SCRIPT    11       0.03   일회성 repack/zip/stress 스크립트
──────────────────────────────────────────────────────────────
                           65   4,370.71
```

D1.1 때와 같은 65개다 — D1.2 는 depth 1 을 건드리지 않았다.

### depth 2: `archive/` 미정리 135개 (1.20 GiB)

```
RESIDUAL_DATASET_DIR       100     773.91   test_blender_v* 등 과거 렌더 산출물
RESIDUAL_DIAGNOSTIC_RUN     34     459.49   _efront_12kp_check 등 일회성 검사
RESIDUAL_FILE                1       0.01
```

이 200개(65 + 135)는 Stage 2-A `archive.csv` 에 이동 계획이 있으나 `executed=no` 다.
**다음 단계 후보이며 D1.2 의 범위가 아니다.** 크기가 작아(합 5.5 GiB) 정리해도
용량 이득은 없고, 목적은 "권장 구조 밖에 뭐가 있는지 불명인 상태"를 없애는 것이다 —
그 목적은 이미 달성했다(UNKNOWN 0).

## 빈 폴더 7개 — 삭제하지 않았다

```
archive/corrupt              2-A 뼈대. D1 이 packages/corrupt/ 를 쓰면서 비었다
archive/legacy_assets        2-A 뼈대, 미사용
archive/nonredistributable   2-A 뼈대, 미사용
archive/superseded_runs      2-A 뼈대, 미사용
archive/unidentified         2-A 뼈대. D1.1 이 UNKNOWN 을 없애 비었다
archive/test_blender_v35     하위에 빈 overlay/ 만 있다
archive/test_blender_v49     하위에 빈 overlay/ 만 있다
```

지시가 삭제를 금지한다. 빈 뼈대 폴더를 남겨 두는 것이 다음 단계 분류의 목적지가 된다.
