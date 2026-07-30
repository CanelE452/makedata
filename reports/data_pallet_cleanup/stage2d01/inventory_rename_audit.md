# Stage 2-D0.1 §7 — inventory.csv rename 감사

## 결과

```
old path   reports/data_pallet_cleanup/inventory.csv
new path   reports/data_pallet_cleanup/grouped_inventory.csv
방법        git mv   (tracked rename, 내용 변경 0)
row count  416
```

`git status` 는 `R  inventory.csv -> grouped_inventory.csv` 로 잡힌다 — 복사본 두 개를
남기지 않았다.

## grouped 판정 근거 [확인]

지시문의 4조건을 모두 확인했다.

```
조건                                         실측                                    판정
────────────────────────────────────────────────────────────────────────────────────────
한 row 가 개별 파일이 아니라 directory/group  entry_type 열 = dir/file 구분 존재        ✓
recursive 집계 필드를 가짐                    file_count_recursive ·                  ✓
                                             total_bytes_recursive
전체 파일 수와 row 수가 크게 다름             416 row vs data/pallet 파일 363,090개    ✓
                                             (전수 manifest 라면 363,090 row 여야 함)
Stage 1 조사 설명과 일치                      Stage 1 은 "디렉토리 단위 인벤토리"로     ✓
                                             기술 — depth 기반 그룹 집계
```

즉 이 파일은 파일 363,090개의 전수 manifest가 아니라 **grouped/directory-level
inventory** 다. 이름을 실제 성격에 맞췄다.

## 현재 참조 전수 검색

```
검색 대상          rg 'inventory\.csv' (전 저장소, 확장자 무관)
code 참조          0건   (스크립트가 이 이름을 기본값으로 쓰지 않는다)
current docs 참조  2건 -> 수정
```

수정한 current reference:

```
reports/data_pallet_cleanup/README.md        2곳  (산출물 목록 · 설명 문장)
reports/data_pallet_cleanup/rollback_plan.md 5곳  (근거 파일 경로)
```

코드 참조가 0이므로 migration warning / 자동 탐지 fallback 은 추가하지 않았다.
없는 문제에 대한 방어 코드를 넣지 않는다.

## 보존한 historical reference (수정하지 않음)

```
_docs/history/*.md                       당시 파일명 그대로
reports/data_pallet_cleanup/stage2a/     당시 report snapshot
reports/data_pallet_cleanup/stage2b/     당시 report snapshot
reports/data_pallet_cleanup/stage2c1/    당시 report snapshot
reports/data_pallet_cleanup/stage2c2/    당시 report snapshot
reports/data_pallet_cleanup/stage2d0/    당시 report snapshot (inventory_rename_plan.md 포함)
*/transactions/*.jsonl                   이동 원장
```

과거 문서가 당시 이름으로 그 파일을 부르는 것은 틀린 기록이 아니다. 소급 수정하지 않는다.

## data/pallet 영향

**없다.** 이것은 report artifact 이름 정정이고 data/pallet 파일 이동이 아니다.
`filesystem_invariance.json` 의 `data_pallet_delta.files = 0` 로 확인된다.
