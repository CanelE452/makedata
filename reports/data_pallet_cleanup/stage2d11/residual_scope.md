# Stage 2-D1.1 §2 — 잔여 범위 정본화

Stage 2-D1 보고 숫자를 그대로 쓰지 않고 **현재 파일시스템에서 재계산**했다.
결과적으로 row 수는 D1 보고와 같지만(10 / 4 / 4) bytes 는 실측값이다.

```
scope                     rows     files            bytes
────────────────────────────────────────────────────────────────
D1D_ROLLBACK_SOURCE         10        10       2,400,984,463   (2.24 GiB)
BLOCKED_REFERENCE            4    92,429      17,334,010,020  (16.14 GiB)
BLOCKED_UNKNOWN              4    39,620      15,588,789,193  (14.52 GiB)
────────────────────────────────────────────────────────────────
합계                        18   132,059      35,323,783,676  (32.90 GiB)
```

정본 CSV: `residual_scope.csv` (27열) / 동결: `frozen_scope.json`

## A. D1D rollback source — 전제 전부 성립 [확인]

```
exists                      10/10
D0 classification           COLD_ARCHIVE 10/10
현재 SHA256 == D0 기록       10/10
prior C2C 원장 구성원        10/10
prior 원장의 SHA256 == 현재  10/10   ← chain 을 만들 수 있는 근거
active registry ref          0
rollback registry ref        0
current runtime/test ref     0
destination collision        0
```

## B. BLOCKED_REFERENCE (4)

```
move_id  source                                              bytes      refs  prior ledger
──────────────────────────────────────────────────────────────────────────────────────────
D1-003   …/blender_scene/_sandbox_parking_lot_check.blend    0.13 GiB     2   C2C (S2C2002)
D1-033   archive/train_palletobj_v3                          9.95 GiB     1   —
D1-038   archive/training_data                               5.99 GiB    10   —
D1-053   archive/train_palletobj_v3_post_v1                  0.07 GiB     1   —
```

참조 위치 (실측):

```
D1-003  gen_palletobj_v1.py:4 (docstring) · :569 (save_as_mainfile 출력)
D1-033  postprocess_v3.py:199 (argparse default)
D1-038  config/default.yaml:53,54 · config/stage3_selftrain.yaml:81,85 ·
        evaluate_on_val.py:12 · visualize_inference.py:9,187 ·
        visualize_pretrain.py:193 · isaac_sim/generate_all.sh:44 · self_train.py:17
D1-053  postprocess_v3.py:202 (argparse default)
```

D1-003 은 **C2C 원장 구성원**이라 D1D 와 같은 chain 처리가 필요하다.

## C. BLOCKED_UNKNOWN (4)

```
move_id  source                                        bytes      ref  exclusion
──────────────────────────────────────────────────────────────────────────────────
D1-041   archive/training_data_v4_split_GREYBUG        4.93 GiB     0   EXCLUDED
D1-042   archive/training_data_v4_split_bg1bak        4.93 GiB     0   EXCLUDED
D1-043   archive/training_data_v4_emptywood           4.49 GiB     0   EXCLUDED
D1-049   archive/training_data_v4_pilotA              0.18 GiB     0   EXCLUDED
```

현재 참조 0 · prior ledger 구성원 아님 → 이동 자체의 기술적 장애는 없다.
막고 있던 것은 **라이선스 판정**이었고 §9 에서 해소했다 (전부 PROVEN_NOAI).

## D. 기타 잔여 전수 조사 (233 entry, `final_tree.csv`)

```
classification                     n     files        MiB   proposed_action
──────────────────────────────────────────────────────────────────────────────────
EXPECTED_ROOT                      6   339,353  175,032.01  유지
SEMANTIC_CONTAINER                 9   191,522  137,730.14  유지
RESIDUAL_DATASET_DIR             107   194,405  129,864.84  다음 단계 후보
PLAN_ROW_BLOCKED_REFERENCE         3    92,428   16,399.59  ★ 이번 범위
PLAN_ROW_BLOCKED_UNKNOWN           4    39,620   14,866.63  ★ 이번 범위
RESIDUAL_DIAGNOSTIC_RUN           44    20,187    4,808.78  다음 단계 후보
KEEP_QUARANTINE                    1     4,543    4,149.13  유지 (isaac_assets, EULA)
RESIDUAL_OUTPUT_DIR                3       160       12.14  다음 단계 후보
RESIDUAL_LOG                      40        40        8.30  다음 단계 후보
RESIDUAL_DIAGNOSTIC_IMAGE          1         1        0.95  다음 단계 후보
PLAN_ROW_KEEP_QUARANTINE           1         3        0.70  유지 (NoAI USD)
RESIDUAL_ONE_OFF_SCRIPT           11        11        0.03  다음 단계 후보
MANAGEMENT_FILE                    2         2        0.01  유지
RESIDUAL_FILE                      1         1        0.01  다음 단계 후보
──────────────────────────────────────────────────────────────────────────────────
★ UNKNOWN / 미분류                 0
빈 폴더 (삭제하지 않음)              7
```

`PLAN_ROW_BLOCKED_REFERENCE` 가 3인 것은 이 스캔이 depth 1~3 만 보기 때문이다 —
D1-003(depth 5, `assets/scenes/production/blender_scene/`)은 `residual_scope.csv` 에 있다.

**이번 작업의 실제 이동 대상은 위 3범위로 제한한다.** `RESIDUAL_*` 208개는 추가 이동
후보로 발견됐지만 자동 포함하지 않는다.

## ★ §6 hash 예산 사전 계산 — 전역 상한 20 GiB 초과

이동 전 실측 bytes 로 예상 read(= bytes × 2)를 계산했다.

```
cohort                    bytes        예상 read      판정
──────────────────────────────────────────────────────────────
D11A_BLEND_BACKUPS      2.24 GiB       4.47 GiB     예산 내
D11B_REFERENCE_TRANSITION 16.14 GiB    32.29 GiB    ★ 초과
D11C_LICENSE_RESOLUTION  14.52 GiB     29.04 GiB    ★ 초과
──────────────────────────────────────────────────────────────
합계                    32.90 GiB      65.80 GiB    상한의 3.3배
```

§6 은 "예상 read 가 20GiB 를 넘으면 apply 전에 중단", §17 은 "hash read 20GiB 초과"를
중단 기준으로 명시한다. selective 강등도 금지다. 세 조건을 동시에 만족시킬 방법은 없다.

**처리**: cohort 원자성을 지키면서 예산 안의 것만 실행했다.

```
D11A  예산 내      -> 실행·검증 완료
D11B  예산 초과     -> registry 전환(코드/config, read 0)까지 완료. 실이동 미실행
D11C  예산 초과     -> provenance 판정 완료 (읽기 전용). 실이동 미실행
```

cohort 를 쪼개 일부만 옮기는 방법도 있었으나(D1-003+D1-053+D1-038 = 12.38 GiB 는 남은
15.53 GiB 안에 들어간다) **cohort = transaction_group 원자성**을 깨뜨리므로 하지 않았다.
