# data/pallet 정리 — Stage 1 조사·계획 보고서

- 작성일: **2026-07-28**
- 대상: `E:/CODING/GitHub/FoundationPose/data/pallet`
- **이번 단계 실행 결과: 이동 0건 / 삭제 0건 / data/pallet 하위 새 폴더 생성 0건** (9절 확인)
- 산출물은 전부 `reports/data_pallet_cleanup/` (기존 `reports/` 체계 하위 신규 폴더 — `reports/v2_overlay_fix`, `reports/v2_revision` 와 같은 레벨)

---

## 0. PRE-FLIGHT 결과

```
항목               값
──────────────────────────────────────────────────────────────────
repo root         E:/CODING/GitHub/FoundationPose
branch            main
HEAD              ff972c2b3b2fcfe187ab8fe2ae46c0308ea1647b
git status        clean (porcelain 무출력)
OS                Windows 11 (MINGW64_NT-10.0-26200), 셸 = Git Bash
data/pallet 절대   E:/CODING/GitHub/FoundationPose/data/pallet
gitignored        예 — .gitignore:5 `data/` (git ls-files data/pallet = 0건)
디스크             E: 1.9T 중 1.3T 여유 (33% 사용)
```

읽은 문서: `CLAUDE.md`, `AGENTS.md`(CLAUDE.md와 1줄 차이), `_docs/blender_mcp_onboarding.md`,
`_docs/dataset_license_ledger.md`, `_docs/history/2026-07-{24,25,27,28}.md`,
`reports/v2_overlay_fix/final_report.md`, `config/synthetic/blender.yaml`.

> `tests/` 는 저장소 루트에 없다. 실제 테스트 위치 = **`scripts/data_prep/blender/tests/`** (21개 파일). [확인]

---

## 1. 현재 data/pallet 구조의 문제 (관찰 → 판정 분리)

**관찰**

1. 최상위에 **68개 파일이 직접 방치**되어 있다 — zip 15, 로그 35, 일회성 `.py` 11, `_log.txt` 4 등. (85.30 GB)
2. `_v2_*` 로 시작하는 **런 디렉토리가 158개** 최상위에 평면 나열되어 있다. 그중 90개가 1~20 프레임짜리 probe.
3. `archive/` 는 89.80 GB / 328,942 파일로 전체의 47%를 차지하는데, **그 안에 현역 자산이 섞여 있다.**
4. 실행 코드·설정이 참조하는 경로 **252개 중 168개가 실제로 존재하지 않는다** (`active_path_references.csv`).
   그중 **74건이 문서가 아닌 실행 코드/설정**의 참조다.
5. 최상위 zip 15개(85.29 GB)와 `archive/` 추출본이 **엔트리 수·비압축 바이트까지 일치**한다.
6. 빈 디렉토리 400개.

**판정**

- 이름과 실제 역할이 어긋나 있다. `archive/` 는 "보관소"가 아니라 **현역 자산 + 테스트 정본 + legacy 가 섞인 혼합 폴더**다.
- 과거에 한 번 `archive/` 로 옮기는 정리가 있었으나 **코드를 따라 고치지 않아** 참조가 대량으로 끊겼다.
  같은 방식으로 또 옮기면 같은 문제가 재발한다 → **경로 registry 도입이 이동보다 먼저다** (7절).
- 데이터셋이 zip과 추출본으로 이중 보관되어 약 85 GB가 중복이다(삭제 권고는 하지 않음).

---

## 2. 총 폴더·파일·용량

```
항목                    값
────────────────────────────────────────────
디렉토리                2,489   (그중 빈 폴더 400)
파일                    363,015
총 용량                 191.02 GB  (191,023,311,090 bytes)
SHA256 계산 완료         3,005 파일 (≤8MB 전량 + 동일 크기 중복 후보)
SHA256 미계산            large_files.csv 의 54개 등 — hash_status=SKIPPED_LARGE 로 표기, 크기·mtime 은 기록
최상위 파일             68개 / 85.30 GB
최상위 디렉토리          174개 / 105.72 GB
```

확장자 상위: `.png` 245,653 / `.json` 111,249 / `.jpg` 2,478 / `.usd` 1,862 / `.log` 380 / `.jsonl` 139

> **인벤토리 범위 규칙**: `grouped_inventory.csv` (구 `inventory.csv`, Stage 2-D0.1 개명) 는 *분류 단위*(최상위 전체 + `archive/`·`blender_scene/` 하위 + 개별 지정 파일)
> **416행**을 담는다. 디렉토리는 `directories.csv` 에 **2,489행 전량**, 대용량 파일은 `large_files.csv` 에 **54행**.
> 363,015개 파일 전체를 행으로 펴지 않은 이유는 정리 판단이 폴더 단위로 이뤄지고,
> 개별 파일 지표(수·바이트·확장자 히스토그램)는 디렉토리 행에 재귀 집계로 이미 담겨 있기 때문이다.

---

## 3. Active asset 목록 (실행 코드/설정이 실제로 읽는 것)

```
경로                                             용량      참조  근거
──────────────────────────────────────────────────────────────────────────────────────────────
blender_scene/synth_data_scene.blend             0.359GB    35  run_v2_scene_logic.py:13/25 등 실행 스크립트 20개
blender_scene/textures/                          0.064GB     -  위 blend 의 내부 상대참조(//textures/) 대상
blender_scene/_sandbox_palletobj_production.blend 0.157GB    7  run_addon_v1.sh:56 SCENE=
distractors/ (209종)                             1.959GB     9  blend 통합 + manifest 기준 트리
distractors/distractors_manifest.csv             1.4MB       3  v2_pipeline.py:63, distractor_pool_v2.py:33 (하드코딩)
hdri/ (Poly Haven CC0 30종)                      0.199GB    17  blender.yaml:330 → blender_config.py:365 → v2_realize.py:90
models_usd/ (scene.usd 외)                       0.080GB    14  blender.yaml:26 pallet_source_dir
background/ (parking_lot/scene.gltf)             0.291GB     7  blender.yaml:69 filepath
pallets_v2_add/ (신규 목재 2종 + measurements)     0.005GB     5  efront_kp12.py:32, ledger:154~158
★ archive/textures_floor/                        0.675GB     1  v2_realize.py:804-810 하드코딩 폴백
★ archive/textures_wood/                         0.315GB     1  v2_realize.py:768-774 하드코딩 폴백
hdri/{LICENSE,SOURCES}.txt                       -           1  ledger:176-179 가 CC0 근거로 인용
pallets_v2_add/{LICENSE,SOURCES}.txt             -           -  ledger:158 라이선스 정본
_tmp_ph/*_files.json                             6개         -  ledger:266 "다운로드 CDN URL 원본"
```

★ = **폴더명이 `archive` 지만 현역**. 프롬프트가 경고한 "이름으로 판단하지 말 것" 사례가 실제로 있었다. [확인]

---

## 4. Current production path 목록 (v2 파이프라인 실행 시 실제 해석 경로)

```
심볼                        해석 방식                                         최종 경로
────────────────────────────────────────────────────────────────────────────────────────────
씬(blend)                  실행 명령줄 리터럴                                data/pallet/blender_scene/synth_data_scene.blend
cfg.HDRI_DIR               blender.yaml:330 → blender_config.py:365          data/pallet/hdri
cfg.PALLET_SOURCE_DIR      blender.yaml:26  → blender_config.py:115          data/pallet/models_usd
cfg.OUTPUT_BASE_DIR        blender.yaml:20  → blender_config.py:93           data/pallet
배경 glTF                  blender.yaml:69                                   data/pallet/background/parking_lot/scene.gltf
DEFAULT_MANIFEST           v2_pipeline.py:63 / distractor_pool_v2.py:33 하드코딩  data/pallet/distractors/distractors_manifest.csv
WOOD_TEXTURE_DIR (폴백)     v2_realize.py:768-774 하드코딩                     data/pallet/archive/textures_wood
FLOOR_TEXTURE_DIR (폴백)    v2_realize.py:804-810 하드코딩                     data/pallet/archive/textures_floor
기본 --out                 run_v2_scene_logic.py:485                         data/pallet/_v2_scene_logic_500_seed7500
```

`config/synthetic/blender.yaml` 은 확장자만 yaml 이고 **내용은 JSON** 이다(`blender_config.py:40 json.loads`). [확인]

---

## 5. Run 목록과 분류

```
분류              건수   파일       용량      대표
──────────────────────────────────────────────────────────────────────────────────────
RUN_DIAGNOSTIC    117    6,072     1.84GB    _v2_scene_logic_probe_* ×90, _v2_scene_logic_500_seed7500(EDA 정본)
RUN_SMOKE          34    4,888     1.03GB    _v2_scene_logic_smoke20_* ×27, _v2_smoke50_9d, _v2_smoke20_9c_run1/2
RUN_PILOT           2   13,158     2.64GB    _v2_pilot_2k(2.50GB), _v2_calib_200
RUN_FAILED          5    1,782     0.25GB    *_failed_missing_hdri_*, *_failed_prereview_p1_*, *_failed_precontactmatrix_* 등
RUN_PRODUCTION      1       49     0.001GB   logs/ (train_4pallet_mask_v1 청크 통계 49개)
SUPERSEDED_RUN    120    ~1,900    0.56GB    archive/_mat_test*, _floor_*, _mask_test*, eval_results 등
LEGACY_DATASET     99   307,565   168.45GB   archive/train_*, training_data*, test_blender_v* + 최상위 zip 15
```

`runs/production/` 에 들어갈 산출물은 **현재 없다** — 40k 본생성이 아직 승인 대기이기 때문이다.

---

## 6. Reference 목록

```
분류                        경로                                 용량      근거
────────────────────────────────────────────────────────────────────────────────────────
REFERENCE_GOLDEN           archive/trunc_addon_v1_pilot/        0.283GB   tests/test_overlay_archive_trunc_style.py:42
                                                                          + overlay_v2_detailed.py:9 / overlay_archive_trunc_style.py:6
                                                                          / _verify_archive_style_pixels.py:48 / _make_archive_vs_new_sheet.py:22
REFERENCE_REAL             real_data/ (1,924 jpg)               0.154GB   visualize_inference.py:10, visualize_pretrain.py:197
                                                                          ledger:324 "본인 촬영(D435i) → 본인 IP"
REFERENCE_EXPECTED_OUTPUT  _trunc_addon_v1_{10m,far}_example/   0.002GB   trunc_addon_v1 run 의 예시 프레임(rgb/mask/overlay)
REFERENCE_CAMERA           (해당 없음)                            -         camera intrinsic 은 config/synthetic/blender.yaml:7-12 내부
```

---

## 7. Legacy / archive 후보

```
분류            건수  용량       내용
──────────────────────────────────────────────────────────────────────────────
LEGACY_DATASET   84   87.69GB   archive/train_palletobj_v1~v3, train_palletobj_addon_v1,
                                train_4pallet_mask_v1, trunc_addon_v1, training_data,
                                training_data_v4*, test_blender_v1..v70, test_indoor_v1
LEGACY_DATASET   15   85.29GB   최상위 zip 15개 (추출본과 중복 — 4절 duplicate_groups.csv)
LEGACY_SCENE     11    2.54GB   blend 백업 9종 + .blend1
LEGACY_ASSET      2    0.001GB  distractors_manifest.csv.bak_prefill,
                                archive/_noai_quarantine_usd (★이동 금지)
SUPERSEDED_RUN  120    0.56GB   구 실험 산출물
```

**라이선스 주의** [확인, `_docs/dataset_license_ledger.md:25,70`]:
2026-07-24 blend 재-bake 이전에 렌더된 산출물(v4 / v4_split / 4pallet_mask 등)에는
**NoAI 목재 팔레트가 이미 baked** 되어 있다. → 로컬 보관은 가능하나 **공개 릴리스 불가**.
`proposed_moves.csv` 의 `license_risk` 컬럼에 `HIGH(NoAI baked → 공개 릴리스 금지)` 로 표기했다.

---

## 8. UNIDENTIFIED 목록 (규칙 6·7 — 이동 계획에서 제외)

```
경로                     용량      파일    충돌하는 근거
──────────────────────────────────────────────────────────────────────────────────────
isaac_assets/            4.351GB   4,543   ACTIVE 신호: config/synthetic/isaac_sim.yaml:7 이 참조
                                           반대 신호: ledger:103 "B6 — NVIDIA EULA, 배포 트리 포함 금지"
                                                     + Isaac 파이프라인 휴면(현재 Blender 경로)
                                           → 근거 충돌 → UNIDENTIFIED
_floor_catalog.png       0.001GB       1   최상위 방치 png, 생성 스크립트 특정 실패
```

추가로 **`BLOCKED_BY_UNKNOWN_PURPOSE` 20건**(archive 하위 소규모 실험 폴더, 0.29GB / 18,369 파일)은
분류는 `SUPERSEDED_RUN`(confidence=low, `[추정]`)이지만 개별 목적 검증을 끝내지 못해 이동을 막아 두었다.

---

## 9. 코드 참조 때문에 이동 불가능한 항목

`blocked_moves.csv` 참조. 요약:

```
status                       건수   용량       대표
──────────────────────────────────────────────────────────────────────────────────
BLOCKED_BY_CODE_REFERENCE     13    5.87GB    _v2_pilot_2k(17ref), _v2_scene_logic_500_seed7500(78ref),
                                              archive/textures_floor·textures_wood(v2_realize 하드코딩),
                                              distractors_manifest.csv, real_data, eval_results
BLOCKED_BY_TEST_REFERENCE      1    0.28GB    archive/trunc_addon_v1_pilot
BLOCKED_BY_LICENSE             1    0.001GB   archive/_noai_quarantine_usd
BLOCKED_BY_UNKNOWN_PURPOSE    20    0.29GB    archive 하위 소규모 실험 폴더
NEEDS_USER_DECISION           36    4.53GB    최상위 .py/.log 35개, train_palletobj_v1.zip(손상)
KEEP_CURRENT                  11    2.96GB    production 자산 (3절)
```

**가장 위험한 항목** — `archive/trunc_addon_v1_pilot`:
`test_overlay_archive_trunc_style.py:292` 가 `@unittest.skipUnless(ARCHIVE_SAMPLE.exists())` 이다.
이 폴더를 옮기면 테스트가 **FAIL 이 아니라 조용히 SKIP** 된다 → 커버리지가 소리 없이 사라진다.
현재 상태 확인: `pytest tests/test_overlay_archive_trunc_style.py -q` → **51 passed** (skip 0). [확인, 실행함]

---

## 10. 추천 최종 tree

`proposed_tree.md` 참조 (현재 구조 ↔ 제안 구조 나란히 + 기본 후보에서 제외한 폴더와 이유).

---

## 11~12. proposed move 수 / SAFE·BLOCKED·UNKNOWN 개수

```
status                        건수   용량        파일수
──────────────────────────────────────────────────────────
SAFE_CANDIDATE                 330   172.74GB   316,308
NEEDS_USER_DECISION             36     4.53GB        36
BLOCKED_BY_UNKNOWN_PURPOSE      20     0.29GB    18,369
BLOCKED_BY_CODE_REFERENCE       13     5.87GB    21,082
KEEP_CURRENT                    11     2.96GB     1,469
BLOCKED_BY_LICENSE               1     0.00GB         3
BLOCKED_BY_TEST_REFERENCE        1     0.28GB     1,210
──────────────────────────────────────────────────────────
proposed_moves.csv 총계        412
이동 계획에서 제외(UNIDENTIFIED)   2     4.35GB     4,544
```

---

## 13. 사용자에게 결정이 필요한 항목

```
#   항목                                          질문
────────────────────────────────────────────────────────────────────────────────────────
D1  최상위 *.py 11개 (_repack.py, _make_zip_lowmem.py 등)  data/ 안 `_staging/` 로 격리할지,
                                                  scripts/data_prep/blender/ 로 승격할지
D2  train_palletobj_v1.zip (4.53GB, BadZipFile)   손상본 — 보관(_corrupt/)할지 별도 처리할지
D3  최상위 zip 15개 (85.29GB)                       추출본과 중복 확인됨. archive 로 옮길지,
                                                  아니면 별도 외장/콜드 스토리지로 뺄지
D4  isaac_assets (4.35GB)                          Isaac 파이프라인을 되살릴 계획이 있는지
                                                  (있으면 ACTIVE, 없으면 archive)
D5  _DISTRIBUTION_EXCLUDE.txt                      경로 5/5가 이미 stale. 지금 갱신할지,
                                                  Stage 2 이동과 함께 갱신할지
D6  깨진 참조 74건 (실행 코드/설정)                    Stage 2 이전에 일괄 수정할지,
                                                  이동과 함께 registry 로 흡수할지
D7  경로 registry (config/paths.yaml)               아래 14절 설계안 채택 여부
```

---

## 14. 정리 후 경로 설계 (7절 요구사항 — 설계만, 구현 안 함)

> **[Stage 2-A.1 갱신]** registry 는 도입 완료됐다. 정본 관계는 다음 하나로 고정한다 —
> `config/synthetic/pallet_paths.yaml` 이 **runtime source of truth** 이고,
> `data/pallet/manifests/*.csv` 는 **local inventory snapshot** 이다.
> 상세: `reports/data_pallet_cleanup/stage2a1/source_of_truth_audit.md`

### 경로 registry 가 필요한가 → **필요하다.**

근거: `data/pallet` 경로 리터럴이 **124개 파일에 552회** 등장하고, 그중 **209회가 실행 코드/설정**이다.
과거 archive 이동 때 코드를 따라 고치지 않아 **168개 참조가 이미 끊겼다**. registry 없이 또 옮기면 반복된다.

```yaml
# config/paths.yaml  (제안 — 이번 단계에서 생성하지 않음)
pallet_data_root: data/pallet

production_scene:        ${pallet_data_root}/assets/scenes/production/synth_data_scene.blend
sandbox_scene:           ${pallet_data_root}/assets/scenes/experimental/_sandbox_palletobj_production.blend
background_gltf:         ${pallet_data_root}/assets/scenes/backgrounds/parking_lot/scene.gltf
pallet_source_dir:       ${pallet_data_root}/assets/pallets/source_models
pallet_v2_add_dir:       ${pallet_data_root}/assets/pallets/source_models/v2_add
hdri_dir:                ${pallet_data_root}/assets/lighting/hdri
wood_texture_dir:        ${pallet_data_root}/assets/materials/pallet
floor_texture_dir:       ${pallet_data_root}/assets/materials/floor
distractor_manifest:     ${pallet_data_root}/assets/distractors/manifest/distractors_manifest.csv
distractor_models_root:  ${pallet_data_root}/assets/distractors/models
golden_overlay_reference: ${pallet_data_root}/reference/golden_overlay/trunc_addon_v1_pilot
real_images:             ${pallet_data_root}/reference/real_images
runs_root:               ${pallet_data_root}/runs
```

- 해석 지점은 **`blender_config.py` 한 곳**으로 모은다(이미 `_resolve_project_path()` 가 있어 확장만 하면 된다).
- `blender.yaml` 의 `assets.pallet_source_dir` / `lighting.hdri_dir` / `background.assets.*.filepath` /
  `output.base_dir` 는 registry 키를 가리키게 바꾼다.

### 환경변수 `PALLET_DATA_ROOT` 가 필요한가 → **있으면 좋다(필수는 아님).**

`blender_config.py:29` 에 이미 `BLENDER_SYNTH_CONFIG_PATH` 환경변수 오버라이드 선례가 있다.
같은 방식으로 `PALLET_DATA_ROOT` 를 두면 Windows/Ubuntu 공유(전역 규칙) 시 유용하다.
기본값은 repo-relative `data/pallet` 로 두고, **미설정이 정상 동작**이어야 한다.

### Windows 절대경로 제거 가능 여부 → **가능하다. 31건 중 실행 코드 27건.**

```
파일                                          라인      대상
────────────────────────────────────────────────────────────────────
floor_and_mask.py                             22       textures_floor  (E:/… 하드코딩, 이미 깨짐)
run_mass_10k.py                               19,52    train_palletobj_v1, hdri
run_trunc_addon.py                            29,61    trunc_addon_v1, hdri
_inspect_usd_shapes.py                        6,7      models_usd
_probe_dist.py / _probe_v.py                  31 / 26  hdri
run_pilot_2k.sh                               11,13    blend, _v2_pilot_2k
run_chunks.sh / run_chunks_v2.sh              9,11,17,19
palletobj_fill/{build_filled,diagnose,fill_test,loop_locations}.py
analyze_stats.py, _audit_perm_disagreement.py, audit_trunc_addon.py,
gen_trunc_addon.py, gen_palletobj_scenarios.py, render_indoor_data.py,
_make_smoke10_sheet.py, _verify_smoke10.py
```

전부 `PROJECT_ROOT` 상대로 바꿀 수 있다(다른 파일들이 이미 그 방식을 쓴다).
단, `_docs/history/2026-07-26-v2-attempt-log.md:108` 에 기록된 사례처럼
**다른 워크스페이스 경로(`C:\Users\User\Documents\GitHub\FoundationPose`)로 실행되던 이력**이 있으므로,
절대경로 제거는 오히려 이 문제를 없애는 방향이다.

### .blend 내부 external texture path 처리

- `synth_data_scene.blend` 는 `blender_scene/textures/` 를 **상대참조(`//textures/`)** 한다고 보는 것이 자연스럽다 `[추정]`
  — blend 내부 이미지 경로를 실제로 덤프해 확인하지 않았다.
- **Stage 2 착수 전 반드시 확인할 것** (읽기 전용):
  ```
  blender -b data/pallet/blender_scene/synth_data_scene.blend --python-expr \
    "import bpy;[print(i.name, i.filepath) for i in bpy.data.images]"
  ```
  - 결과가 `//textures/...` (상대)면 → blend 와 textures 를 **같은 상대 위치로 동반 이동**하면 안전.
  - 절대경로(`E:/...`)가 섞여 있으면 → `bpy.ops.file.make_paths_relative()` 또는 재저장이 선행되어야 한다.
- distractor 209종은 2026-07-24 에 blend 안으로 **append(복사)** 되었다고 기록되어 있으므로
  `distractors/` 이동이 blend 렌더를 깨뜨리지 않을 가능성이 높다 `[추정]` — 위 덤프로 같이 검증한다.

### relative path 로 바꿀 때 위험한 자산

```
자산                                위험
─────────────────────────────────────────────────────────────────────────────
blender_scene/textures/            blend 내부 상대참조 — blend 와 분리 이동하면 텍스처 유실(렌더는 성공하고
                                   결과만 잘못 나오므로 조용히 실패한다)
models_usd/scene.usd               blend 가 USD 를 link 하고 있으면 이동 시 깨짐 (append 면 무해) — 미검증
archive/trunc_addon_v1_pilot/      skipUnless 로 인해 테스트가 조용히 SKIP (9절)
distractors_manifest.csv           distractor_pool_v2.py 가 `__file__` 기준 3단계 상위로 계산 →
                                   manifest 만 옮기면 209 pool 이 0 이 되고, 로더가 예외 대신
                                   "size-class only" 로 **성능 저하 상태로 계속 동작**한다
_DISTRIBUTION_EXCLUDE.txt          경로가 stale 이면 릴리스 제외 게이트가 조용히 무력화 → 라이선스 사고
```

공통 패턴: **이 저장소의 경로 실패는 예외를 던지지 않고 조용히 열화된다.** 그래서 rollback_plan.md 의
검증 게이트 G4~G7 은 "에러가 안 났다"가 아니라 "기대값과 같다"를 확인하도록 짰다.

---

## 15. 다음 실제 이동 단계의 예상 작업량

```
단계                                          규모                        비고
────────────────────────────────────────────────────────────────────────────────────
S2-0 blend 내부 경로 덤프 검증                  명령 1회                     읽기 전용, 5분
S2-1 config/paths.yaml + blender_config 확장   파일 2개                    구현 + 단위 테스트
S2-2 깨진 참조 74건 정리                        파일 ~30개                  대부분 `_` 접두 일회성 스크립트
S2-3 SAFE_CANDIDATE 330건 이동                 316,308 파일 / 172.74GB     동일 볼륨 rename → I/O 거의 0,
                                                                          단 원장·해시 검증이 실제 비용
     └ 대량 항목: archive/legacy_datasets 84건(87.69GB), _packaged 14건(80.76GB),
       runs/diagnostics/v2_scene_logic_probes 101건(566파일)
S2-4 BLOCKED 13건 해제(코드 수정 동반)           파일 ~8개                   v2_realize.py, v2_pipeline.py,
                                                                          distractor_pool_v2.py, 테스트 1개
S2-5 KEEP_CURRENT 11건 이동                    2.96GB                      registry 완료 후에만
```

권장 순서: **S2-0 → S2-1 → S2-2 → (검증) → S2-3 → S2-4 → S2-5.**
S2-3 을 먼저 하고 싶은 유혹이 있으나(용량이 커서 성과가 크게 보임), 이 폴더들은 참조가 0이라
**정리 효과는 크고 위험은 낮은 대신, 근본 원인(경로 하드코딩)은 전혀 줄지 않는다.**

---

## 16. 생성한 보고서 경로

```
reports/data_pallet_cleanup/
├── README.md                        이 문서 (최종 보고)
├── proposed_tree.md                 현재 구조 ↔ 제안 구조
├── rollback_plan.md                 Stage 2 rollback 절차 (삭제 명령 없음)
├── grouped_inventory.csv            266행 — 분류 단위(디렉토리/그룹) 엔트리 (35 컬럼)
│                                    Stage 2-D1 에서 최종 tree 로 재생성 (416 -> 266).
│                                    사라진 206행은 Stage 2-A/B/C2/D1 이동분 —
│                                    목록은 stage2d1/grouped_inventory_diff.md
│                                    ※ Stage 2-D0.1 에서 inventory.csv 를 개명. 전 파일
│                                      manifest 가 아니라 그룹 집계임을 이름에 반영.
├── directories.csv                  2,489행 — 전체 디렉토리
├── large_files.csv                  54행 — 50MB 이상 파일
├── active_path_references.csv       556행 — 경로 참조 그래프
├── duplicate_groups.csv             138행 — 중복 그룹 (전부 deletion_recommended=false)
├── proposed_moves.csv               412행 — 이동 계획
├── blocked_moves.csv                 71행 — 차단 항목만
└── _inventory_raw.csv / _dirs_raw.csv / _raw_refs.json / _dups_raw.json / _zip_map.json   (중간 산출물)
```

---

## 17. git status

```
$ git status --porcelain
?? reports/data_pallet_cleanup/
```

**커밋·푸시하지 않았다.**

---

# 반드시 먼저 볼 두 표

## A. KEEP_ACTIVE — 옮기면 안 되는 것 (26건)

```
category                  status                     용량GB   파일   ref  경로
──────────────────────────────────────────────────────────────────────────────────────────────────────────
ACTIVE_ASSET_SCENE        KEEP_CURRENT                0.359      1   35  blender_scene/synth_data_scene.blend
ACTIVE_ASSET_MATERIAL     KEEP_CURRENT                0.064    158    0  blender_scene/textures
ACTIVE_ASSET_DISTRACTOR   KEEP_CURRENT                1.959   1161    9  distractors
ACTIVE_ASSET_BACKGROUND   KEEP_CURRENT                0.291     77    7  background
ACTIVE_ASSET_HDRI         KEEP_CURRENT                0.199     33   17  hdri
ACTIVE_ASSET_PALLET       KEEP_CURRENT                0.080     21   14  models_usd
ACTIVE_ASSET_PALLET       KEEP_CURRENT                0.005     14    5  pallets_v2_add
ACTIVE_LICENSE            KEEP_CURRENT                    -      4    1  hdri/{LICENSE,SOURCES}.txt,
                                                                          pallets_v2_add/{LICENSE,SOURCES}.txt
ACTIVE_MANIFEST           BLOCKED_BY_CODE_REFERENCE   0.001      1    3  distractors/distractors_manifest.csv
ACTIVE_ASSET_MATERIAL     BLOCKED_BY_CODE_REFERENCE   0.675     59    1  archive/textures_floor      ★
ACTIVE_ASSET_MATERIAL     BLOCKED_BY_CODE_REFERENCE   0.315     27    1  archive/textures_wood       ★
ACTIVE_ASSET_SCENE        BLOCKED_BY_CODE_REFERENCE   0.157      1    7  blender_scene/_sandbox_palletobj_production.blend
REFERENCE_GOLDEN          BLOCKED_BY_TEST_REFERENCE   0.283   1210   11  archive/trunc_addon_v1_pilot ★★
REFERENCE_REAL            BLOCKED_BY_CODE_REFERENCE   0.154   1924    4  real_data
RUN_PILOT                 BLOCKED_BY_CODE_REFERENCE   2.495  12147   17  _v2_pilot_2k
RUN_DIAGNOSTIC            BLOCKED_BY_CODE_REFERENCE   1.699   4995   78  _v2_scene_logic_500_seed7500
RUN_SMOKE                 BLOCKED_BY_CODE_REFERENCE   0.182    616   57  _v2_smoke50_9d
RUN_PILOT                 BLOCKED_BY_CODE_REFERENCE   0.141   1011    6  _v2_calib_200
RUN_SMOKE                 BLOCKED_BY_CODE_REFERENCE   0.020     96    7  _v2_publicmask_overlay_smoke8
RUN_DIAGNOSTIC            BLOCKED_BY_CODE_REFERENCE   0.013     66    2  _v2_g5_reverify
RUN_DIAGNOSTIC            BLOCKED_BY_CODE_REFERENCE   0.008     36    4  _v2_b3_check
SUPERSEDED_RUN            BLOCKED_BY_CODE_REFERENCE   0.011    103    5  eval_results
LEGACY_ASSET              BLOCKED_BY_LICENSE          0.001      3    0  archive/_noai_quarantine_usd
──────────────────────────────────────────────────────────────────────────────────────────────────────────
★  이름은 archive 인데 v2_realize.py 가 하드코딩으로 읽는 현역 자산
★★ 옮기면 테스트가 FAIL 이 아니라 SKIP 되어 조용히 커버리지가 사라짐
```

## B. PROPOSED_MOVE — 목적지별 요약 (SAFE_CANDIDATE 330건 / 172.74GB)

```
건수   파일수     용량GB    목적지
──────────────────────────────────────────────────────────────────────────
  84  307,551    87.692   archive/legacy_datasets/
  14       14    80.761   archive/legacy_datasets/_packaged/        (최상위 zip 15 중 14)
   7        7     1.555   archive/legacy_scenes/
   4        4     0.984   archive/legacy_scenes/rebake_20260724/
  32    4,176     0.826   runs/smoke/
  52    1,723     0.542   archive/superseded_runs/
   5    1,782     0.248   runs/failed/
 101      566     0.070   runs/diagnostics/v2_scene_logic_probes/
  12      401     0.054   runs/diagnostics/
  13       13     0.008   _staging/logs/
   2        7     0.002   reference/expected_outputs/trunc_addon_v1/
   1       49     0.001   archive/legacy_datasets/train_4pallet_mask_v1/_stats/   (logs/)
   1        8     0.000   runs/diagnostics/v2_dryrun_audit/
   1        6     0.000   assets/licenses/polyhaven_download_provenance/          (_tmp_ph/)
   1        1     0.000   archive/legacy_assets/
──────────────────────────────────────────────────────────────────────────
 330  316,308   172.740   합계
```

건별 상세는 `proposed_moves.csv` (move_id, source, destination, reason, evidence, license_risk,
rollback_source/destination, approval_required, status 포함).


---

## Stage 2-C1 (2026-07-29) — production .blend portable 화

원본 `synth_data_scene.blend`(sha256 46f436dc…) 를 **한 바이트도 건드리지 않고** 같은 폴더에
`synth_data_scene_portable.blend`(5cad94e5…) 를 만들어 registry `production_scene` 을 승격했다.

```
절대 외부경로   229 -> 0      (228 은 //../distractors/ 로 변환, 1 은 factory_yard repoint)
missing path     1 -> 0
image datablock 603 -> 603   (구조 diff 0)
데이터 폴더 이동   0          (distractors / blender_scene / background 전부 그대로)
```

★ Stage 2-B 가 보고한 `BLOCKED_ABSOLUTE=356` 은 과다계상이었다 — 그중 128건은 이미
`//..\distractors\` 상대경로였다(Stage 2-B 자신의 CSV 로 확인). 실제 재작성 대상은 228건.

보고서: `stage2c1/final_report.md` · 도구: `scripts/data_prep/blender/`
(`blend_path_utils.py` · `manage_blend_external_paths.py` · `audit_blend_assets.py`)


---

## Stage 2-D0 (2026-07-30) — 잔여 대용량 자료 비파괴 감사

**데이터 이동·삭제·rename 0건.** 파일시스템 delta dirs+0 / files+0 / bytes+0 으로 170.34GB 를
분류하고 Stage 2-D1 계획만 작성했다. hash read 9.48GB / 예산 20GB.

```
archive/ semantic 하위폴더 7개가 전부 비어 있다 -> Stage 2-D1 이 채울 곳
ZIP 20개 / 84.92GB · 손상 1건(truncated) · 중복 확정 0건 (CRC 로 보니 사본들이 서로 다름)
blend 17개 · weight 29개(전부 고유 SHA256) · quarantine 2 · legacy dataset 120
Stage 2-D1 계획 60행 / 이동 후보 48건 163.03GB
```

보고서: `stage2d0/final_report.md`
도구: `scripts/data_prep/audit_pallet_archives.py`

---

## stage2d1/ — Stage 2-D1 archive 정리 (2026-07-30, 실이동 30건)

```
[판정] D1_PARTIAL — READY 40건 중 30건 VERIFIED (130.14 GiB / 191,518 파일)
       10건(D1D)은 앞선 원장 충돌로 rollback. FULL layout 완료 아님.
```

Stage 2-D0.1 이 동결한 계획(SHA256 `c343b807…`)을 정본으로 써서 cohort 순서
D1B → D1D → D1A → D1C 로 실행했다.

```
파일                              내용
────────────────────────────────────────────────────────────────────────────────
preflight.md                      기준선 A~H (전부 기대치 일치)
baseline_checksums.json           registry·test·원장 SHA256·active scene·5k digest
ledger_checksums_before.json      앞선 원장 7 + 참조문서 6 의 SHA256
filesystem_before.json            이동 전 영역·top-level·archive depth1
frozen_plan.json                  계획 동결 (40행 / cohort별 재검증 문제 0)
transaction_policy.md             stage2d1-archive-finalization 정책 설계
hash_budget.md                    cohort별 read 예산과 실사용 (257.78 / 286 GiB)
checkpoint.json                   cohort 상태 + D1D incident 기록
transactions/d1b_corrupt.jsonl         1행  이동 원장 (rollback 근거)
transactions/d1d_blend_backups.jsonl  10행  ROLLED_BACK
transactions/d1a_packages.jsonl       14행
transactions/d1c_legacy_datasets.jsonl 15행  (relative_files 191,503 경로)
cohort_d1b_report.md              손상 ZIP 보존 이동 — 이동 후에도 BadZipFile 확인
cohort_d1d_report.md              ★ 실패 분석: C2C 원장 구성원을 옮겨 MISSING 11건
cohort_d1a_report.md              package 14건 — structural match 도 전부 보존
cohort_d1c_report.md              dataset 15건 — NoAI/PARTIAL 재분류 안 함
exclusion_before.csv              entries 16 / problems 0
exclusion_after_d1a.csv           ZIP 새 경로 반영
exclusion_after_d1c.csv           NoAI 3건 새 경로 반영
exclusion_final.csv               problems 0 / leaks 0 / stale 0
current_reference_final.csv        canonical broken CURRENT ref 0
grouped_inventory_diff.md         416 -> 266 행, 사라진 206 / 새로 생긴 56
final_tree.md                     최종 구조 감사 + 판정 근거 + 잔여 목록
regression_results.md             §16 전체 검증 (unit 714 · 5k digest 동일)
filesystem_after.json             이동 후 실측
filesystem_diff.json              delta + 보호 영역 전수 불변 (문제 0)
rollback_plan.md                  cohort별·전체 rollback 절차 + exclusion 수동 복구
final_report.md                   38항목 최종 보고
```
