# Stage 2-D0.1 PRE-FLIGHT

일시: 2026-07-30 / 목적: Stage 2-D0 감사가 찾은 결함 4종을 고치고 Stage 2-D1 계획을
실행 가능한 상태로 고정한다. **데이터 이동 0.**

## 0.1 환경 [확인, 실행함]

```
repo root            E:/CODING/GitHub/FoundationPose
data/pallet 절대경로  E:\CODING\GitHub\FoundationPose\data\pallet
platform             win32 / Windows 11 (bash 도구 = Git Bash)
HEAD (작업 전)        60e0860840fbacf4da8233e4adb33bcaed1c2b75
origin/main          60e0860  (동일)
working tree         clean
작업 branch           chore/data-pallet-stage2d01-stabilization  (신규 생성, 기존 동일명 없음)
data/pallet          dirs=2,560  files=363,090  bytes=192,468,045,942 (179.25 GiB)
```

실행 중 process: `blender.exe` **0개**. data/pallet 를 건드리는 Python process **0개**.
(다른 프로젝트의 trading/koapy process 5개는 그대로 두었다 — 종료 금지 규칙 준수.)

## 0.2 기준 측정값 [확인, 실행함]

```
항목                          값                              기대치       일치
────────────────────────────────────────────────────────────────────────────────
A registry audit              ok=24 missing=0 absent=0        missing=0    ✓
B default unit                646 passed, skip 0, fail 0      >=646        ✓
C local integration            31 passed, skip 0, fail 0      >=31         ✓
  (PALLET_DATA_INTEGRATION=1 필요 — 없으면 collection error)
D golden overlay               51 passed, skip 0, fail 0      >=51         ✓
E exclusion 검증 (before)      entries 11 / problems 0        기록용        —
                              release leak 5 (미등록 항목)
F Stage 2-A 원장               146 / 6,921 / failures 0        동일         ✓
  Stage 2-B B1/B2/B3          4/3,220 · 3/68 · 0/0 / fail 0    동일         ✓
  Stage 2-C2 C2A/C2B          3/3 · 1/74 / failures 0          동일         ✓
  Stage 2-C2 C2C (strict)     2/1,336 / failures 3             실패 예상    ★
active scene sha256           8cb4109adc6d3213…                동일         ✓
```

★ C2C strict 실패 3건은 예상된 것이다 — 원인·근거는 `c2c_verify_before.json`
및 `c2c_verify_semantics.md` 에 전수 기록했다. 요약: manifest 생성 이후 destination 에
Stage 2-C2 가 정상 생성한 2개 파일(active stable blend + Blender 자동 백업)이 추가돼
파일 수·bytes·relpath set 이 어긋난다. **원래 옮긴 1,334 파일은 SHA256 전수 일치,
누락 0, moved-file hash mismatch 0.**

## 0.3 필수 선행 문서 읽음 [확인]

Stage 2-D0: `final_report.md` · `proposed_stage2d1_moves.csv` · `license_crosscheck.csv` ·
`distribution_exclusion_status.md` · `remaining_reference_graph.csv` ·
`blocked_by_reference.csv` · `inventory_rename_plan.md` · `memory_sync_plan.md` ·
`blend_inventory.csv` · `blend_relationships.csv` · `baseline_checksums.json`
Stage 2-C2: `final_report.md` · `transactions/c2c_distractor_scene.jsonl` · `source_hashes.csv`
그 외: `config/synthetic/pallet_paths.yaml` · `manage_pallet_data_layout.py` ·
`verify_distribution_exclusions.py` · `audit_pallet_archives.py` ·
`data/pallet/_DISTRIBUTION_EXCLUDE.txt` · `_docs/dataset_license_ledger.md` ·
`_docs/data_pallet_layout.md` · `_docs/history/2026-07-30.md` · `changelog.md` ·
`reports/data_pallet_cleanup/README.md`

## 0.4 디스크

E: 드라이브에 여유 공간 충분. **이 단계는 이동을 하지 않으므로 추가 공간을 쓰지 않는다**
(hash 읽기 9.48 GB 만 발생, 쓰기는 report artifact 뿐).

## 0.5 출력 폴더

`reports/data_pallet_cleanup/stage2d01/` (신규)
