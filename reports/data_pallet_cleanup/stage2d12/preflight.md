# Stage 2-D1.2 preflight

base commit `3a6ade5313d89ccb976cd35fc154d1e7388daa13` (Stage 2-D1.1 종료 시점)

## 1. working tree

지시가 허용한 dirty 는 `_docs/history/.last-compact-resume.md` 하나뿐이다.
이 파일은 **수정하지 않고 · 복구하지 않고 · stage 하지 않고 · commit 대상에 넣지 않는다.**

## 2. 범위 — D1.1 이 남긴 잔여 2 cohort

D1.1 은 예산 충돌로 이동을 하지 못하고 조사·근거만 남겼다. D1.2 는 그 2건을 실제로 옮긴다.
**계획서 숫자를 재사용하지 않고 파일시스템을 다시 재서** frozen scope 를 만들었다
(`frozen_scope.json` / `.csv`, `recomputed_from_filesystem = true`).

```
cohort                  row  files     bytes            내용
──────────────────────────────────────────────────────────────────────────────────
D12B_REFERENCE_MOVE      4   92,429   17,334,010,020   registry 전환이 끝나 이동 가능해진 것
D12C_PROVEN_NOAI_MOVE    4   39,620   15,588,789,193   PROVEN_NOAI 확정분
──────────────────────────────────────────────────────────────────────────────────
합계                     8  132,049   32,922,799,213   (30.66 GiB)
```

각 cohort 는 **atomic transaction group** 이다. 예산에 들어오는 일부 row 만 골라 먼저
옮기지 않는다 (도구가 cohort 분할 요청을 거부한다).

## 3. D12B 4건 — 왜 이제 옮길 수 있나

D1.1 시점에 이 4건은 `BLOCKED_REFERENCE` 였다. 실행 표면이 **리터럴 경로**로 이들을
가리키고 있어서, 옮기면 참조가 깨진다. D1.1 이 registry 전환을 끝내
(`config/synthetic/pallet_paths.yaml` 에 키 4개 신설 + config/스크립트를 `registry:` 참조로
교체) 이제 **키 값 한 줄만 바꾸면** 되는 상태다.

```
move_id  source                                              registry key
────────────────────────────────────────────────────────────────────────────────────
D1-003   assets/scenes/production/blender_scene/             legacy_sandbox_parking_lot_scene
         _sandbox_parking_lot_check.blend
D1-033   archive/train_palletobj_v3                          legacy_train_palletobj_v3_root
D1-038   archive/training_data                               legacy_training_data_root
D1-053   archive/train_palletobj_v3_post_v1                  legacy_train_palletobj_v3_post_v1_root
```

**live reference 재측정** — D1.1 CSV 의 `current_runtime_test_refs` 를 그대로 복사하면
registry 전환 **이전** 값이라 4건이 전부 LIVE_REF 문제로 잡힌다. 실제로 처음에 그렇게
만들어 오탐 4건이 나왔고, **지금 실행 표면을 다시 재서** 고쳤다
(registry 정본 `pallet_paths.yaml` 과 resolver docstring 은 카운트에서 제외 — 그 둘이
경로를 소유한다). 결과: 3건은 0 이 됐고, `generate_all.sh:42` 의 낡은 주석 1건은
**진짜였다** → 갱신했다.

## 4. D12C 4건 — provenance 확정본

D1.1 이 라벨 JSON 13,122개(= 프레임 13,120)를 전수 스캔해 `PROVEN_NOAI` 로 확정한 것.
D1.2 는 그 판정을 **다시 믿지 않고** file_count/bytes 로 동일성을 재확인했다
(`provenance_verification.csv`, `identity_unchanged = True` 4/4).

`PROVEN_NOAI` 는 `archive/legacy_datasets/noai_baked/` **외의 목적지로 갈 수 없다**
(도구가 `/redistributable/` `/packages/` `/unidentified/` `/release/` `/partial/` 를 거부).

## 5. prior ledger 소속 조회

"chain 이 안 만들어졌으니 없을 것"으로 넘기지 않고 8건 전부 직접 조회했다.

```
D1-003  -> c2c_distractor_scene.jsonl / S2C2002    ★ successor chain 필요
나머지 7건 -> prior ledger 소속 없음                  chain 불필요
```

## 6. baseline

`baseline_checksums.json` — 기존 원장 8종 + D1/D1.1 원장 4종 + chain + registry + 도구,
총 18개 파일의 SHA256. D1.2 가 기존 원장을 rewrite 하지 않았음을 이 값으로 보인다.

`ledger_status_before.json` — 원장 13종의 row/moved/verified/files/bytes.

## 7. before 스냅샷

`filesystem_before.json` 은 **새로 재지 않고** Stage 2-D1.1 의 `filesystem_after.json`
을 쓴다. D1.1 종료와 D1.2 시작 사이에 `data/pallet` 을 건드린 작업이 없기 때문이다.
이 주장을 그냥 두지 않고 **after + 이동 8건 역산 == D1.1 after** 로 검증했다
(`filesystem_diff.json` 의 `reconstruction_check`, mismatch 0).

## 8. 이동 전 기준선 (regression before)

```
exclusion_before.csv            entries 16 / problems 0 / leaks 0
no_render/d12_before_no_render_audit.json   abs 0 · missing 0 · Dist_ 209
dryrun_before/                  5k proposals 4,439 / 12/12 checks
registry audit                  ok=28 missing=0
```
