# Stage 2-D1 readiness gate

기준 커밋 `60e0860` / branch `chore/data-pallet-stage2d01-stabilization` / 2026-07-30

## 항목별 판정

```
#   항목                                       실측                                   판정
──────────────────────────────────────────────────────────────────────────────────────────
1   canonical broken CURRENT ref = 0           0  (before 44행 / unique 39 / 파일 23)   PASS
2   exclusion problems = 0                     0  (entries 16)                         PASS
3   exclusion leaks = 0                        0  (before 5)                           PASS
4   C2C exact verify failures = 0              0  (strict 모드는 3 — 원인 규명 완료)     PASS
5   grouped inventory rename 완료              git mv 완료, 416행, 코드참조 0           PASS
6   registry missing = 0                       ok=24 missing=0 absent_optional=0        PASS
7   active scene hash 불변                     8cb4109adc6d3213… (동일)                 PASS
8   Stage 2-A/B 원장 불변                      fe1adc26 · 43461e47 · 0d0c06a8 (동일)     PASS
9   Stage 2-C2 moved file hash mismatch = 0    0  (sha256 checked 1,334 / missing 0)    PASS
10  proposed D1 READY row blocker = 0          0  (status=READY 39행 blocker 없음.       PASS
                                                  CORRUPT_MOVE_READY 1행은 blocker 가
                                                  아니라 주의문 "삭제 금지 — 보존 이동만")
11  READY source missing = 0                   0  (40/40 존재 확인)                     PASS
12  READY destination collision = 0            0  (40/40 목적지 부재 확인)               PASS
13  UNKNOWN 이동 후보 = 0                      0  (v4 파생 4건은 BLOCKED_UNKNOWN)        PASS
14  quarantine 이동 후보 = 0                   0  (isaac_assets · NoAI USD = KEEP)      PASS
15  rollback-critical 이동 후보 = 0            0  (blend 4건 = KEEP_ROLLBACK,            PASS
                                                  active 2건 = KEEP_ACTIVE)
──────────────────────────────────────────────────────────────────────────────────────────
                                               15 PASS / 0 FAIL
```

## 최종 판정

```
READY_FOR_STAGE_2_D1
```

15개 게이트 항목 전부 PASS 이며 FAIL 은 없다.

**단, 이 판정의 범위는 "READY 로 분류된 40건"이다.** 계획 60행 중 20행은 D1 실행
대상이 아니며 그 이유가 각각 확정돼 있다 (아래). Stage 2-D1 을 실행할 때
`status == READY` 또는 `CORRUPT_MOVE_READY` 인 40행만 대상으로 삼아야 한다.

## READY 40건 (132.37 GiB · 191,528 파일)

```
cohort                READY   bytes         목적지
────────────────────────────────────────────────────────────────────────────────────
D1B_CORRUPT              1     4.22 GiB     archive/packages/corrupt/
D1D_BLEND_BACKUPS       10     2.24 GiB     archive/legacy_scenes/{snapshots,blender_backups}/
D1A_PACKAGES            14    75.21 GiB     archive/packages/dataset_bundles/
D1C_LEGACY_DATASETS     15    50.70 GiB     archive/legacy_datasets/{redistributable,partial}/
────────────────────────────────────────────────────────────────────────────────────
                        40   132.37 GiB
```

cohort 실행 순서는 지시문 권장대로 **D1B → D1D → D1A → D1C**. 가장 작고 위험이 낮은
것부터 트랜잭션을 검증한다.

READY 조건 11개를 코드로 강제했다 (`d01_plan.py::ready_or_block`) — source 존재 /
destination collision 0 / current runtime ref 0 / current test ref 0 / registry ref 0 /
rollback-critical 아님 / quarantine 아님 / UNKNOWN 아님 / license 판정 완료 /
transaction rollback 가능 / source·destination 같은 볼륨(E:).

## 이동하지 않는 20건 — 이유별

### BLOCKED_UNKNOWN 4건 (14.53 GiB) — 라이선스 미확정

```
archive/training_data_v4_split_GREYBUG    4.93 GiB
archive/training_data_v4_split_bg1bak     4.93 GiB
archive/training_data_v4_emptywood        4.49 GiB
archive/training_data_v4_pilotA           0.18 GiB
```

이름상 `training_data_v4*` 파생이고 본체는 NoAI baked 로 릴리스 제외 대상이다. 파생본이
같은 blend 로 렌더됐는지 **라벨 metadata 로 확인하지 않았다**. 이름 유사성만으로 NoAI
를 단정하지도, 일반 archive 로 분류하지도 않는다 → `UNKNOWN_LICENSE` 유지 + 배포 제외
유지(ledger B8). 목적지를 정할 수 없으므로 계획에서 제외한다.

**해소 방법**: 각 파생 dataset 의 라벨 JSON 에서 사용 blend/자산 metadata 를 읽어 NoAI
목재 포함 여부를 확정. 확정되면 `legacy_datasets/noai_baked/` 또는
`legacy_datasets/redistributable/` 로 배정.

### BLOCKED_REFERENCE 4건 (18.39 GiB) — CURRENT 경로 참조가 살아있다

```
move_id  source                                          runtime ref  참조 위치
──────────────────────────────────────────────────────────────────────────────────────
D1-038   archive/training_data                    5.99GiB     10      config/default.yaml:53,54
                                                                      config/stage3_selftrain.yaml:81,85
                                                                      evaluate_on_val.py:12
                                                                      visualize_inference.py:9,187
                                                                      visualize_pretrain.py:193
                                                                      isaac_sim/generate_all.sh:44
                                                                      self_training/self_train.py:17
D1-033   archive/train_palletobj_v3               9.95GiB      1      postprocess_v3.py:199
D1-053   archive/train_palletobj_v3_post_v1       0.07GiB      1      postprocess_v3.py:202
                                                                      gen_surface_fps_v1.py(옛 경로)
D1-003   …/blender_scene/_sandbox_parking_lot     0.13GiB      2      gen_palletobj_v1.py:4,569
         _check.blend
```

이 참조들은 **Stage 2-D0.1 §3 에서 방금 고친 것들이다.** 지금 이 dataset 을
`archive/legacy_datasets/...` 로 한 단계 더 내리면 같은 참조가 다시 깨진다.

**해소 방법 (Stage 2-D1 선행 단계)**: registry(`config/synthetic/pallet_paths.yaml`)에
dataset 키를 등록하고 위 참조를 `_pdp.get("<key>")` / `--key <key>` 로 전환한 뒤 이동한다.
그러면 이동은 registry 값 한 줄 변경으로 끝난다. 근거 행은
`plan_reference_hits.csv` 의 `kind=path_current`.

> 참고: `kind=path_stale_old` 19건(예: `run_addon_v1.sh:39 OUT="data/pallet/train_palletobj_addon_v1"`)
> 은 **이미 깨져 있는 옛 경로**이고 이동이 더 깨뜨리지 않으므로 차단 근거로 쓰지 않았다.
> 다만 이 중 출력 경로들은 실행 시 옛 위치에 새 폴더를 만든다 — D1 이후 별도 정리 대상.

### KEEP_ACTIVE 2 / KEEP_ROLLBACK 4 — blend 17개 중 6개 [확인]

```
move_id  파일                                                  D0 분류            상태
────────────────────────────────────────────────────────────────────────────────────────
D1-017   synth_data_scene_portable_stage2c2.blend              ACTIVE_RUNTIME     KEEP_ACTIVE
D1-002   _sandbox_palletobj_production.blend                   ACTIVE_RUNTIME     KEEP_ACTIVE
D1-009   synth_data_scene.blend                                ROLLBACK_CRITICAL  KEEP_ROLLBACK
D1-015   synth_data_scene_portable.blend                       ROLLBACK_CRITICAL  KEEP_ROLLBACK
D1-016   synth_data_scene_portable_candidate_20260729.blend1   ROLLBACK_CRITICAL  KEEP_ROLLBACK
D1-018   synth_data_scene_portable_stage2c2_candidate.blend1   ROLLBACK_CRITICAL  KEEP_ROLLBACK
```

rollback-critical / active 를 READY 로 분류하지 않았다 (게이트 #15, 실측 0).

나머지 11개 중 10개는 COLD_ARCHIVE → READY, 1개(D1-003)는 위 BLOCKED_REFERENCE.
`synth_data_scene_indoor.blend`(D1-014)은 COLD_ARCHIVE → READY 다 —
`render_indoor_data.py:6` 의 언급은 디렉토리 없는 **파일명 단독**(`blender
synth_data_scene_indoor.blend`)이라 경로 참조가 아니다 [확인].

### KEEP_ACTIVE 4건 — UNREFERENCED_WEIGHT

```
weights/pallet_category_test/final_net_epoch_0001.pth
weights/pallet_category_test/net_epoch_0001.pth
weights/2024-01-11-20-02-45/model_best.pth
weights/2023-10-28-18-33-37/model_best.pth
```

`weights/` 는 `data/pallet` 밖이고 gitignored 다. "참조가 없다"는 **사실 기술**이며
삭제 후보가 아니다. 목적지가 정해지지 않았으므로 D1 기본 실행계획에서 제외하고 별도
승인을 받는다. 29개 전부 고유 SHA256 — exact duplicate 0.

### KEEP_QUARANTINE 2건 — 이동 금지

```
data/pallet/isaac_assets                 4.05 GiB  NVIDIA EULA (ledger B6)
data/pallet/archive/_noai_quarantine_usd            NoAI USD 3개 (ledger B1)
```

이동하면 `_DISTRIBUTION_EXCLUDE.txt` 경로를 동시에 갱신해야 하므로 릴리스 게이트가
일시적으로 뚫린다. 이동 이득이 없어 그대로 둔다 (게이트 #14).

## Stage 2-D1 실행 시 반드시 지킬 것

```
1  cohort 순서 D1B -> D1D -> D1A -> D1C. 각 cohort 마다 --plan -> --apply -> --verify.
2  같은 볼륨 rename 만. copy 후 삭제 금지. destination overwrite 금지. 삭제 명령 없음.
3  D1B 손상 ZIP 은 **보존 이동**이다. 삭제 권고가 아니다.
4  D1A 는 structural match 를 duplicate 로 취급하지 않는다 — duplicates/ 목적지 사용 금지.
   (ZIP 20개 중 SHA256/CRC 로 동일 내용이 증명된 쌍은 없다.)
5  D1C 는 NoAI baked / partial / redistributable 목적지를 분리하고 NoAI 는 exclusion 유지.
6  이동 후 exclusion 경로가 바뀌면 _DISTRIBUTION_EXCLUDE.txt 를 같은 커밋에서 갱신하고
   verify_distribution_exclusions.py 를 다시 돌린다 (problems 0 / leaks 0 / stale 0).
7  full hash 예산: READY 40건을 hash-mode all 로 검증하면 읽기 264.75 GiB (source+dest).
   기본 예산 20 GB 를 크게 넘는다 -> cohort 단위로 --max-full-hash-bytes 를 명시적으로
   올리거나 selective 모드를 선택하고, 무엇을 hash 하지 않았는지 원장에 남긴다.
   (지금 이 게이트는 이 결정을 대신하지 않는다.)
```

## 근거 파일

```
proposed_stage2d1_moves_final.csv   계획 정본 60행 (status/blocker/참조수 포함)
plan_reference_hits.csv             READY 차단 근거 (kind=path_current) + stale 목록
current_reference_audit.csv         canonical 참조 감사 (after)
current_reference_audit_base.csv    같은 검출기 · 기준 커밋 (before)
distribution_exclusion_canonical.csv  배포 제외 canonical 판정
c2c_verify_after.json               C2C exact allowlist 검증 + 음성 사례 5종
filesystem_invariance.json          이 단계의 데이터 불변 증거
regression_results.md               §11 전체 검증
```
