# Stage 2-D2 §2 — 잔여 항목 재계산 (세 자료 대조)

D1.2 보고서의 "약 200개 / 5.47 GiB"를 그대로 믿지 않고 세 자료를 **독립적으로** 읽어
대조했다. 한 집합을 정본으로 골라 나머지를 무시하지 않았다.

## 0. 세 집합

```
집합                                     실측    D1.2 보고 예상
────────────────────────────────────────────────────────────────
A  FILESYSTEM_RESIDUAL                   201     200
     data/pallet depth-1                  66      65
     archive/ depth-1                     135     135
B  FINAL_TREE_RESIDUAL (stage2d12)        207     200
C  PLAN_PENDING (archive.csv, source 존재) 183      -
────────────────────────────────────────────────────────────────
   A ∩ B ∩ C                              182
```

## 1. 차이와 원인 — 전부 규명했다

```
차이       n    원인
──────────────────────────────────────────────────────────────────────────────
A − C     18    archive.csv 에 계획 row 가 없다.
                17 = Stage 2-A 계획 수립(2026-07-28) **이후** 생성된 v2 진단 run·로그
                     -> 계획된 동종 48건과 분류·destination 이 같다
                 1 = isaac_assets (계획 row 자체가 없는 KEEP_QUARANTINE)
C − A      0    계획에 있는데 파일시스템에 없는 것 = 없음
A − B      2    D1.2 final_tree 가 KEEP 으로 분류한 항목
                (isaac_assets = KEEP_QUARANTINE, _noai_quarantine_usd =
                 PLAN_ROW_KEEP_QUARANTINE)
B − A      8    ★ D1.2 final_tree 분류기 결함.
                semantic container 의 **하위 container**
                (legacy_datasets/{noai_baked,redistributable,partial} ·
                 legacy_scenes/{snapshots,blender_backups} ·
                 packages/{dataset_bundles,background_sources})와 archive/README.md 를
                RESIDUAL_DATASET_DIR 로 세고 있었다. 최종 구조 그 자체인데 "잔여"로
                잡히던 허수다. D2 에서 분류기를 고쳤다(SUBCONTAINERS 규칙).
```

`archive.csv` 부가 상태:

```
PLAN_STALE_SOURCE            12   source 가 이미 없다 (D1.1/D1.2 가 옮긴 blend·bak)
source 열이 빈 row            3   Stage 2-C2 원장 기록 전용 row (배경 ZIP 3개)
```

## 2. 분류 결과

```
분류                        n    설명
──────────────────────────────────────────────────────────────────────────
ACTIONABLE                 182   계획 destination 이 있고 이동 가능
UNPLANNED_RESIDUAL          24   계획 row 없음 (그중 파일시스템 잔여 17,
                                 나머지 7 = B−A 의 허수)
INTENTIONAL_QUARANTINE       2   isaac_assets · archive/_noai_quarantine_usd
REGISTRY_OWNED_KEEP          1   archive/packages/background_sources
                                 (registry background_package_archive)
```

## 3. ★ 이동 전 참조 실측 — 여기서 오탐 145건을 걸렀다

"계획에 있으니 옮겨도 된다"가 아니라 **지금 누가 이 경로를 가리키는지**를 셌다
(Stage 2-D1.2 교훈: 이전 단계 CSV 의 ref 수치를 복사하면 안 된다).

1차 측정에서 145건이 live runtime 참조를 갖는 것으로 나왔다. 확인해 보니
**join-form 패턴이 leaf 의 첫 세그먼트만 요구**해서

```python
BASE_DIR = os.path.join("data", "pallet", "archive", "training_data")
#          merge_and_validate.py:18 — 이 한 줄이 archive/* 후보 120건에 전부 걸렸다
```

패턴을 "leaf 의 **모든** 세그먼트를 요구"로 고치자 **145 → 14** 가 됐다.

실제 live 참조 14건의 처리:

```
대상                              참조                                  처리
──────────────────────────────────────────────────────────────────────────────────
eval_results (5)                  evaluate_on_val.py --output_dir 등     WRITE
                                  전부 **출력 기본값**                   -> runs/eval
_v2_b3_check / _v2_calib_200 /    _ 접두 진단기의 --out 기본값           WRITE
_v2_g5_reverify / _v2_pilot_2k /                                        -> runs/diagnostics
_v2_scene_logic_500_seed7500 /
v2_dryrun_audit
같은 대상의 --dir / --records /   기존 산출물을 읽는 곳                  READ
DEFAULT_DIR / DEFAULT_BASELINE                                          -> archive/superseded_runs
archive/_procedural_textures      isaac_sim.yaml procedural_texture_dir  READ -> archive
archive/test_canonical            verify_keypoints.py argv 기본 입력     READ -> archive
archive/_efront_12kp_check        efront_kp12.py docstring · README      READ -> archive
train_palletobj_addon_v1_gen.log  run_addon_v1.sh 주석                   READ -> archive
isaac_assets                      isaac_sim.yaml:9,10                    이동 안 함
archive/_noai_quarantine_usd      test_stage2d1_*.py:550                 이동 안 함
```

**출력 경로를 archive 로 보내지 않은 이유**: 그러면 재실행이 아카이브를 오염시키고
옛 레이아웃이 되살아난다(Stage 2-D0.1 이 `gen_palletobj_v1.py:569` 에서 잡은 함정과
같은 형태). 도구에도 이미 `EXPLICIT_EXCLUSIONS` 로 `v2_dryrun_audit` 이 그 이유로
이동 금지돼 있었다 — D2 는 **함정 자체를 해소**하고 그 사실을 `RESOLVED_EXCLUSIONS` 에
남겼다(가드를 지우지 않았다).

전환 후 재측정: live runtime/test 참조 **0** (이동 대상 199 전부).

## 4. 최종 선정

```
선정 199 row / 23,284 파일 / 5,876,337,378 B (5.47 GiB)
  STAGE2A_PLAN      182   기존 계획 row
  D2_PLAN_ADDITION   17   D2 에서 신설 (동종 48건과 같은 분류·destination)
제외 2
  isaac_assets                    INTENTIONAL_QUARANTINE (계획 row 없음 · NVIDIA EULA)
  archive/_noai_quarantine_usd    INTENTIONAL_QUARANTINE (plan 이 "이동 금지 —
                                  현 위치가 라이선스 근거" 로 명시)
```

D1.2 예상 200개와 실측 199개의 차이는 **`_noai_quarantine_usd` 1건**이다 — D1.2 는 이걸
`PLAN_ROW_KEEP_QUARANTINE` 으로 세었고 잔여 200 에는 넣지 않았으나, 파일시스템 기준
archive depth-1 잔여에는 들어온다. 숫자를 맞추려고 대상을 넣거나 빼지 않았다.
