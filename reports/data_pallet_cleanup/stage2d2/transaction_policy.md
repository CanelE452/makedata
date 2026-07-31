# Stage 2-D2 transaction policy — `stage2d2-layout-completion`

## 왜 새 policy 인가

기존 policy 6개(`stage2a-runs` · `stage2b-active-assets` · `stage2c2-final-layout` ·
`stage2d1-archive-finalization` · `stage2d11-residual-finalization` ·
`stage2d12-final-moves`)는 **하나도 수정하지 않았다.** 기존 policy 를 고치면 이미 검증이
끝난 원장의 재검증 의미가 바뀐다.

```python
POLICY_STAGE2D2 = "stage2d2-layout-completion"
D2_SCHEMA_VERSION = "stage2d2.1"
D2_COHORTS = ("D2_SUPERSEDED_RUNS", "D2_LEGACY_DATASETS", "D2_LEGACY_SCENES",
              "D2_LEGACY_ASSETS", "D2_PACKAGES", "D2_NONREDISTRIBUTABLE",
              "D2_LEGACY_LAYOUT")
D2_ALLOWED_DEST_ROOTS = (legacy_datasets/ · legacy_scenes/ · legacy_assets/ ·
                         packages/ · superseded_runs/ · nonredistributable/ ·
                         legacy_layout/)
D2_FORBIDDEN_RESTRICTED_DEST = ("/redistributable/", "/release/")
D2_POLICY_CONTAINERS = 최종 semantic container 15종
```

## `_stage2d2_candidates()` 가 강제하는 것

```
 1  frozen_final_plan.json ↔ .csv SHA256 결속 (변경되면 거부)
 2  plan row 수 == 동결 selected_count
 3  기록된 destination policy 문제 / nested conflict / duplicate destination 있으면 거부
 4  hash 예산 within=false 면 hashing 전 거부
 5  cohort 임의 분할 거부 (--move-ids 명시는 복구용 escape hatch)
 6  중복 destination 거부
 7  path escape(..) 거부
 8  destination 이 승인된 final root 밖이면 거부
 9  destination 이 archive/ 를 벗어나면 거부
10  live current runtime/test 참조가 1건이라도 있으면 거부
11  registry key 가 가리키는 source 거부
12  제한 라이선스(HIGH/NoAI/EULA) -> redistributable·release 거부
13  ZIP 은 packages/ 계열만
14  최종 policy container 는 이동 불가
15  중첩 source(부모 ⊃ 자식) 거부
16  prior ledger 구성원인데 chain 계획 없으면 거부
```

## 이동 규칙 (Stage 2-A 부터 불변)

same-volume `os.rename` 만 · destination overwrite 금지 · 삭제 0 · symlink 0 ·
cohort = `transaction_group` (한 row 실패 시 cohort 전체 역순 rollback) ·
manifest 가 유일한 rollback 근거.

## manifest schema (`stage2d2.1`)

`schema_version` · `policy` · `frozen_plan_path` · `frozen_plan_sha256` · `cohort` ·
`transaction_group` · `d2_move_id` · `source` · `destination` · `entry_kind` ·
`classification` · `license_status` · `exclusion_before/after` ·
`prior_ledger_members` · `successor_chain_required` · `empty_before/after` ·
`source_file_count` · `source_total_bytes` · `source_relative_paths` ·
`source_sha256` · `hash_mode` · `hashed_file_count` · `unhashed_file_count` ·
`hash_read_bytes_pre/post` · `applied_at` · `verified_at` ·
`rollback_source` · `rollback_destination`

## ★ 작업 중 발견한 도구 결함 1건

verify 의 D1 계열 판정이 schema version 화이트리스트였다:

```python
is_d1 = row.get("schema_version") in (D1_SCHEMA_VERSION, D11_SCHEMA_VERSION,
                                      D12_SCHEMA_VERSION)   # ← D2 가 빠져 있었다
```

이 때문에 `--verify` 가 `failures 0` 을 보고하면서도 원장에 `verified_at` 을 **하나도
남기지 않았다**(199/199 verified=0). 실측으로 잡아 `D2_SCHEMA_VERSION` 을 추가했고,
재검증 후 199/199 기록 + 원장 SHA256 불변(멱등)을 확인했다.

같은 실수가 반복되지 않게 주석으로 경고를 남겼다.
