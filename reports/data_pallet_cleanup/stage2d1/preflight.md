# Stage 2-D1 PRE-FLIGHT

일시: 2026-07-30 / 목적: Stage 2-D0.1 이 확정한 READY 40건을 archive 의미별 하위폴더로
실제 이동한다. 같은 볼륨 rename 만, 전 파일 SHA256 이동 전·후 대조, 삭제 0.

## 0.1 환경 [확인, 실행함]

```
repo root            E:/CODING/GitHub/FoundationPose
data/pallet 절대경로  E:\CODING\GitHub\FoundationPose\data\pallet
HEAD (작업 전)        01290786b978cdaa2b70fcb99bb48625dbfe3b39
origin/main          0129078  (동일)
작업 branch           chore/data-pallet-stage2d1-archive-finalization  (신규, 동일명 없음)
디스크 (E:)           1.9T 중 1.3T 여유 (33% 사용) — 이동은 rename 이라 추가 공간 0
source/destination   둘 다 E: 볼륨 (같은 볼륨 rename 가능)
```

**working tree**: `_docs/history/.last-compact-resume.md` 1개만 modified. 이 파일은
compact hook 이 세션마다 덮어쓰는 것으로 data/pallet·코드와 무관하다. 이전 5개 스테이지
커밋에서도 포함하지 않았다. 그 외는 clean.

## 0.2 실행 중 process [확인]

```
blender.exe                              0개
FoundationPose / data/pallet 관련 python  0개
```

`wmic process where "CommandLine like '%FoundationPose%'"` 매칭은 이 조사에 쓴 bash/wmic
자신뿐이었다. python.exe 5개는 다른 프로젝트(Algorithmic-Trading / koapy)이고 data/pallet
를 건드리지 않는다 — **종료하지 않았다.**

## 0.3 기준 측정값 [확인, 실행함]

```
항목                          값                              기대치       일치
────────────────────────────────────────────────────────────────────────────────
A registry audit              ok=24 missing=0 absent=0        missing=0    ✓
B default unit                664 passed, skip 0, fail 0      >=664        ✓
C local integration            31 passed, skip 0, fail 0      >=31         ✓
  (PALLET_DATA_INTEGRATION=1 필요)
D golden overlay               51 passed, skip 0, fail 0      >=51         ✓
E exclusion                    entries 16 / problems 0 /      전부 0        ✓
                              leaks 0 / stale 0
F Stage 2-A 원장               6,921 files / failures 0        동일         ✓
  Stage 2-B B1/B2/B3          3,220 · 68 · 0 / failures 0     동일         ✓
  Stage 2-C2 C2A/C2B          3 · 74 / failures 0             동일         ✓
  Stage 2-C2 C2C (exact)      1,336 / sha256 1,334 /          failures 0   ✓
                              failures 0
G active Blender no-render     images 603 · absolute 0 ·      abs 0        ✓
                              missing 0 · textures 158 ·      missing 0
                              distractors 356 · hdri 1 ·      Dist_ 209
                              Dist_ 209 · node 누락 0
H 5k FrameSpec                 accepted 4,313 / rejected 687   동일         ✓
                              938f387dd65258e0…
  5k proposals                 accepted 4,439 · 3cd365ee… ·    동일         ✓
                              12/12 PASS
```

C2C 는 **exact expected-addition 모드**로만 검증했다 (`--expected-destination-additions
reports/data_pallet_cleanup/stage2d01/c2c_expected_additions.json`). broad allow 를
쓰지 않았다.

## 0.4 선행 문서 읽음 [확인]

Stage 2-D0.1: `final_report.md` · `stage2d1_readiness.md` ·
`proposed_stage2d1_moves_final.csv` · `current_reference_audit.csv` ·
`distribution_exclusion_canonical.csv` · `c2c_expected_additions.json` ·
`filesystem_invariance.json`
Stage 2-D0: `packages.csv` · `legacy_datasets.csv` · `blend_inventory.csv` ·
`blend_relationships.csv` · `license_crosscheck.csv`
그 외: `grouped_inventory.csv` · `manage_pallet_data_layout.py` ·
`audit_pallet_archives.py` · `verify_distribution_exclusions.py` ·
`config/synthetic/pallet_paths.yaml` · `data/pallet/_DISTRIBUTION_EXCLUDE.txt` ·
`manifests/{archive,path_map,assets}.csv` · `_docs/data_pallet_layout.md` ·
`_docs/dataset_license_ledger.md` · `_docs/history/2026-07-30.md` ·
`reports/data_pallet_cleanup/README.md`

## 0.5 참조 문서 SHA256 결속

`ledger_checksums_before.json` 에 앞선 원장 7개 + 참조문서 6개의 SHA256 을 박았다.
D0.1 readiness 문서와 exact C2C additions spec 이 존재함을 확인했다.

## 0.6 출력 폴더

`reports/data_pallet_cleanup/stage2d1/` (신규) + `transactions/` 하위
