# Stage 2-D1.1 PRE-FLIGHT

일시: 2026-07-30 / 목적: Stage 2-D1 이 남긴 잔여 3범위(D1D 10 · BLOCKED_REFERENCE 4 ·
BLOCKED_UNKNOWN 4)를 **검증 사슬을 유지한 채** 해소한다.

## 0.1 환경 [확인, 실행함]

```
repo root            E:/CODING/GitHub/FoundationPose
HEAD (작업 전)        1577e25d52a0c603b77729db7475934cc7cb6f1b
origin/main          1577e25  (동일)
작업 branch           chore/data-pallet-stage2d11-residual-finalization  (신규, 동일명 없음)
디스크 (E:)           1.9T 중 1.3T 여유 — 이동은 rename 이라 추가 공간 0
data/pallet          dirs 2,567 · files 363,090 · bytes 192,468,081,042
```

**working tree**: `_docs/history/.last-compact-resume.md` 1개만 dirty. 허용 목록과
일치한다. 이 파일은 수정·복구·stage·commit 하지 않는다.

## 0.2 실행 중 process [확인]

```
blender.exe                              0개
FoundationPose / data/pallet 관련 python  0개
```

`wmic process where "CommandLine like '%FoundationPose%'"` 매칭은 이 조사에 쓴 bash 자신
5개뿐. python.exe 5개는 다른 프로젝트(Algorithmic-Trading 1 · koapy 2 · Trading32 4 —
중복 매칭)이고 data/pallet 를 건드리지 않아 **종료하지 않았다.**

## 0.3 기준 측정값 [확인, 실행함]

```
항목                          값                              기대치       일치
────────────────────────────────────────────────────────────────────────────────
A registry audit              ok=24 missing=0 absent=0        missing=0    ✓
B default unit                714 passed, skip 0, fail 0      >=714        ✓
C local integration            31 passed, skip 0, fail 0      >=31         ✓
D golden overlay               51 passed, skip 0, fail 0      >=51         ✓
E exclusion                    entries 16 / problems 0 /      전부 0        ✓
                              leaks 0 / stale 0
F 기존 원장                     아래 표                         전부 0        ✓
G active Blender no-render     images 603 · absolute 0 ·      Dist_ 209    ✓
                              missing 0 · Dist_ 209
   active scene sha256         8cb4109adc6d3213…               동일         ✓
H 5k FrameSpec                 4,313 / 687 · 938f387d…         동일         ✓
  5k proposals                 4,439 · 3cd365ee… · 12/12       동일         ✓
```

### F. 원장 상태 (11개)

```
원장                       rows  status                 src존재  dst존재  verified  failures
────────────────────────────────────────────────────────────────────────────────────────────
stage2a                     146  MOVED                      -       -        -        0
stage2b b1 / b2 / b3        4/3/0 MOVED                     -       -        -        0
stage2c2 c2a / c2b          3/1   MOVED                     -       -        -        0
stage2c2 c2c                  2   MOVED                     -       -        -        0 (exact)
stage2d1 d1b                  1   MOVED                     0       1       1        0
stage2d1 d1a                 14   MOVED                     0      14      14        0
stage2d1 d1c                 15   MOVED                     0      15      15        0
stage2d1 d1d                 10   ROLLED_BACK               10       0      10        —
```

**D1D 는 ROLLED_BACK 이고 source 10건이 전부 원위치에 있으며 destination 잔존 0** —
D1.1-A 를 시작할 수 있는 전제가 성립한다 [확인].

C2C 는 exact expected-addition 모드로만 검증했다. broad allow 를 쓰지 않았다.

## 0.4 선행 문서 읽음 [확인]

Stage 2-D1: `final_report.md` · `final_tree.md` · `checkpoint.json` · `rollback_plan.md` ·
`filesystem_after.json` · `filesystem_diff.json` · `transactions/*.jsonl` 4개
Stage 2-D0.1: `proposed_stage2d1_moves_final.csv` · `current_reference_audit.csv` ·
`distribution_exclusion_canonical.csv` · `c2c_expected_additions.json` ·
`plan_reference_hits.csv`
Stage 2-C2: `transactions/c2c_distractor_scene.jsonl` · `source_hashes.csv` ·
`final_report.md`
Stage 2-D0: `blend_inventory.csv` · `legacy_datasets.csv` · `packages.csv`
그 외: `manage_pallet_data_layout.py` · `audit_pallet_archives.py` ·
`verify_distribution_exclusions.py` · `pallet_paths.yaml` · `_DISTRIBUTION_EXCLUDE.txt` ·
`manifests/{archive,path_map,assets}.csv` · `grouped_inventory.csv` ·
`_docs/data_pallet_layout.md` · `_docs/dataset_license_ledger.md` ·
`_docs/history/2026-07-30.md` · `changelog.md` · `CLAUDE.md` · `AGENTS.md`

project-local memory: `C:\Users\User\.claude\projects\E--CODING-GitHub-FoundationPose\memory\`
[확인] — 전역/타 프로젝트 memory 는 건드리지 않는다.

## 0.5 출력 폴더

`reports/data_pallet_cleanup/stage2d11/` + `transactions/`
