# Stage 2-D1 transaction policy

`scripts/data_prep/manage_pallet_data_layout.py` 에 policy 를 **추가**했다.
기존 3개(`stage2a-runs` · `stage2b-active-assets` · `stage2c2-final-layout`)는
한 글자도 바꾸지 않았다 — 회귀 테스트로 고정한다 (§5, `NoRegressionInOlderPolicies`).

```
policy   stage2d1-archive-finalization
prefix   S2D1  (단, move_id 는 계획 CSV 의 D1-0xx 를 그대로 쓴다)
```

## 이 policy 만의 핵심 — allowlist 가 코드 상수가 아니다

Stage 2-B/2-C2 는 `(source, destination)` 쌍을 코드 상수 tuple 로 갖고 있었다.
Stage 2-D1 은 40행이 **외부 CSV**(Stage 2-D0.1 이 확정)라 그럴 수 없다. 그래서
계획 파일을 SHA256 으로 결속한다.

```
--d1-plan         reports/data_pallet_cleanup/stage2d01/proposed_stage2d1_moves_final.csv
--d1-plan-sha256  c343b807a0e3b5df8b8f6ee8843344b11511564c7046be55810c631cdc3b8e8b
```

계획 파일이 한 바이트라도 바뀌면 plan 이 exit 2 로 거부한다. 원장 각 row 에
`plan_path` · `plan_sha256` 을 박아 두므로 "어느 계획대로 옮겼는지"가 사후에도 남는다.

## 거부 규칙 (전부 exit 2 = 계획 자체를 만들지 않는다)

```
조건                                                   근거
───────────────────────────────────────────────────────────────────────────────
status 가 READY / CORRUPT_MOVE_READY 가 아니다          D1_MOVE_STATUS
선택 범위에 BLOCKED_* / KEEP_* / NEEDS_CRC 가 있다      D1_FORBIDDEN_STATUS
rollback_role 이 있다 (active / rollback)               계획 CSV 열 재확인
license_status 에 UNKNOWN 이 있다                        같음
classification == LICENSE_QUARANTINE                    같음
source 가 weights/ 로 시작한다                           같음
current_runtime_refs > 0 또는 current_test_refs > 0      같음
destination 이 data/pallet/archive/ 밖이다                allowed_dest_prefixes
destination 이 정규화 후 archive/ 를 벗어난다 (escape)     commonpath 검사
source/destination 에 ".." 가 있다                       같음
ZIP 인데 cohort 가 D1A/D1B 가 아니다                      D1_ARCHIVE_COHORTS
CORRUPT_PACKAGE 인데 cohort 가 D1B 가 아니다              D1_CORRUPT_COHORT
--hash-mode 가 all 이 아니다                              require_hash_mode
해시 예산 초과가 예상된다                                  HashBudget.precheck
```

`prefix 검사만으로는 escape 를 막을 수 없다` — `data/pallet/archive/../../../escaped`
도 prefix 를 통과한다. 정규화 후 `commonpath` 로 다시 본다. 이 경우는 skip 이 아니라
**계획 거부**다: 동결된 계획에 escape 가 있다는 것은 계획 자체를 믿을 수 없다는 뜻이다.

## skip 규칙 (계획에서 빠지지만 중단은 아님 — 기존 precheck 재사용)

```
SOURCE_NOT_A_FILE / SOURCE_NOT_A_DIRECTORY   source 부재
DEST_COLLISION                                destination 이 이미 있다 (덮어쓰지 않는다)
SOURCE_IS_SYMLINK / SYMLINK_OR_REPARSE        symlink·reparse
PATH_LENGTH_OVER_240 / RESERVED_WINDOWS_NAME  Windows 제약
FORBIDDEN_EXTENSION                            weight 확장자
INACCESSIBLE_FILE                              읽을 수 없는 파일
ARCHIVE_IN_NON_PACKAGE_COHORT                  directory cohort 안에 ZIP 이 남아 있다
```

skip 은 `<manifest>_skipped.csv` 에 사유와 함께 기록된다. 이번 실행에서 skip 이
하나라도 나오면 40건이 안 되므로 §18 중단 기준에 걸린다.

## cohort = transaction_group

`transaction_group` 을 cohort 이름으로 둔다. 기존 group 원자성 로직이 그대로 적용돼
**한 건이 실패하면 그 cohort 에서 이미 옮긴 것을 역순으로 되돌린다.** 앞선 cohort 는
건드리지 않는다 (§7-10 의 "실패 시 해당 cohort 만 rollback" 과 일치).

`REQUIRED_GROUP_SOURCES` 는 확장하지 않았다 — 그건 C2C 의 "두 폴더가 함께 가야 한다"
전용 제약이고, D1 cohort 는 구성원이 서로 독립이다.

## entry_kind

```
D1B_CORRUPT           file        ZIP 1개
D1D_BLEND_BACKUPS     file        blend/blend1 10개
D1A_PACKAGES          file        ZIP 14개
D1C_LEGACY_DATASETS   directory   dataset 15개 (191,503 파일)
```

## 원장 필드 (§3 요구 전부)

기존 스키마 필드를 유지하고 D1 전용 필드를 덧붙였다 (`schema_version: stage2d1.1`).

```
schema_version · policy · plan_path · plan_sha256 · cohort · move_id · source ·
destination · entry_kind · classification · evidence_level · license_status ·
exclusion_status · source_file_count · source_total_bytes · source_sha256 ·
hashed_file_count · unhashed_file_count · hash_read_bytes_pre ·
hash_read_bytes_post · applied_at · verified_at · rollback_source ·
rollback_destination · transaction_group
```

`hash_read_bytes_post` 와 `verified_at` 은 verify 가 채우고, **D1 원장만** 다시 쓴다.
`schema_version` 이 D1 이 아니면 verify 는 원장을 건드리지 않는다(테스트로 고정).

## 삭제·중복 제거 기능은 없다

이 도구에는 파일 삭제 경로가 존재하지 않는다. `--rollback` 도 역순 rename 이다.
structural match package 를 duplicate 로 재분류하는 코드도 없다 — `duplicates/`
목적지는 계획 CSV 가 명시할 때만 쓰이고, 이번 계획에는 그런 row 가 없다.
