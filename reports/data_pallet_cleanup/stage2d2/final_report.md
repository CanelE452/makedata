# Stage 2-D2 최종 보고 — data/pallet 레이아웃 정리 종료

## 1. 목적과 최종 판정

**목적** — Stage 2-A archive 계획에 destination 이 있으나 `executed=no` 로 남아 있던
물리적 잔여를 최종 destination 으로 옮겨 레이아웃 정책을 닫는다.

```
D2_SCOPE_COMPLETE                        ✅
FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE  ✅
FULL_PHYSICAL_MINIMAL_TREE               ✅
DATA_PALLET_CLEANUP_COMPLETE             ✅
```

## 2. branch / HEAD

```
branch  chore/data-pallet-stage2d2-layout-completion  (신규, 동명 branch 없음)
HEAD    d5e1ba181345fc7d84480606b26ba732ec3324e8      (= origin/main, 일치)
commit  없음 — 사용자 승인 대기
```

## 3. 기준선

```
registry     ok=28 missing=0        unit 745 / integration 31 / golden 51 (skip 0)
exclusion    entries 16 / 0 / 0     기존 원장 12종 failures 0
active scene 8cb4109a · abs 0 · missing 0 · Dist_ 209
5k           4,313 / 938f387d       4,439 / 3cd365ee / 12-12
process      blender 0 · FoundationPose python 0 (다른 프로젝트 4개는 미종료)
             배타 열기 probe FREE 3/3
```

## 4. 잔여 세 집합 재계산

```
A  FILESYSTEM_RESIDUAL                    201   (depth-1 66 + archive depth-1 135)
B  FINAL_TREE_RESIDUAL (stage2d12)        207
C  PLAN_PENDING (archive.csv, source 존재)  183
   A ∩ B ∩ C                              182

A − C = 18   17 = Stage 2-A 계획 수립 이후 생성된 v2 진단 run·로그 (row 없음)
              1 = isaac_assets
C − A =  0
A − B =  2   D1.2 가 KEEP 으로 분류한 2건 (isaac_assets · _noai_quarantine_usd)
B − A =  8   ★ D1.2 final_tree 분류기 결함 — semantic **하위** container
              (noai_baked · redistributable · partial · snapshots · blender_backups ·
               dataset_bundles · background_sources)와 archive/README.md 를
              RESIDUAL 로 세던 허수. D2 에서 SUBCONTAINERS 규칙으로 수정.

부가:  PLAN_STALE_SOURCE 12 (D1.1/D1.2 가 이미 옮김) · source 열 없는 row 3 (C2A 기록 전용)
```

## 5. 예상 200개와 실측 차이

```
D1.2 보고 예상   약 200 entry / 5.47 GiB
실측             201 entry / 이동 대상 199 / 5.47 GiB
```

차이 1건은 `archive/_noai_quarantine_usd` 다 — D1.2 는 `PLAN_ROW_KEEP_QUARANTINE` 으로
세어 잔여 200 에 넣지 않았으나 파일시스템 기준 archive depth-1 잔여에는 들어온다.
**숫자를 맞추려고 대상을 넣거나 빼지 않았다.**

## 6. Frozen final plan

```
reports/data_pallet_cleanup/stage2d2/frozen_final_plan.{csv,json}
plan_csv_sha256  7523904b13ed8d27…   (도구가 실행 시 재대조)
destination policy 문제 0 · nested source conflict 0 · duplicate destination 0
```

## 7. selected rows / files / bytes

```
199 row / 23,284 파일 / 5,876,337,378 B (5.47 GiB)
  STAGE2A_PLAN      182   기존 계획 row
  D2_PLAN_ADDITION   17   D2 에서 신설 (계획된 동종 48건과 같은 분류·destination)
```

## 8. 제외 — management / KEEP / quarantine

```
isaac_assets                    INTENTIONAL_QUARANTINE  4,543 파일 / 4.05 GiB
  역할       Isaac Sim 소스 에셋
  참조       config/synthetic/isaac_sim.yaml:9,10 (live)
  유지 근거   NVIDIA EULA (ledger B6) + exclusion 등재.
             archive.csv 에 이동 계획 row 가 **없다** — §12 "이동은 plan 과 라이선스
             근거가 모두 있을 때만 허용" 에 따라 옮기지 않았다.
archive/_noai_quarantine_usd    INTENTIONAL_QUARANTINE  3 파일
  유지 근거   plan 이 "이동 금지 — 현 위치가 라이선스 근거" 로 명시 (ledger B1)
archive/packages/background_sources  REGISTRY_OWNED_KEEP (background_package_archive)
```

## 9. Destination policy 검증

```
승인 final root 밖              0
제한 라이선스 → redistributable  0
package → dataset destination   0
destination collision           0
cross-volume                    0
path escape                     0
```

## 10. Hash budget

```
                    추정        실사용      한도
D2 이동 pre+post   10.95 GiB   10.95 GiB   16 GiB   (68.4%)
```

`hash-mode=all` · unhashed 0 · selective 강등 0 · 초과 0.

## 11. Prior ledger membership

199 source 를 prior ledger **7종 전체**와 전수 조회:

```
구성원        0 건
필요 chain    0 개
```

## 12. Successor chain 목록

**신규 chain 0개.** 기존 2종은 수정 없이 그대로 쓴다:

```
stage2d11/c2c_successor_chain.json                     mapping 10
stage2d12/chains/c2c_distractor_scene_to_d12.json      mapping  1
-> C2C: successor chain 11 file(s) from 2 chain(s) / 인정된 이관 11 / failures 0
```

## 13~17. Cohort 별 plan / pre-hash / apply / post-hash / verify

```
cohort                rows  files    bytes          pre        apply  post       verify
──────────────────────────────────────────────────────────────────────────────────────────
D2_LEGACY_DATASETS      64   1,963    607,410,306   0.57 GiB   64     0.57 GiB   failures 0
D2_SUPERSEDED_RUNS     135  21,321  5,268,927,072   4.91 GiB  135     4.91 GiB   failures 0
──────────────────────────────────────────────────────────────────────────────────────────
                       199  23,284  5,876,337,378   5.47 GiB  199     5.47 GiB   failures 0
```

sha256 checked 1,963 + 21,321 = 23,284 · mismatch 0 · unhashed 0 · source 잔존 0.
cohort 순차 실행, 각 cohort 는 atomic transaction group.

## 18. Restricted / quarantine 이동

**이동 0.** §12 의 권장 목적지(`nonredistributable/{nvidia,noai_usd}`)가 있으나
두 항목 모두 **plan 이 이동을 승인하지 않았다**(isaac_assets 는 row 자체가 없고,
`_noai_quarantine_usd` 는 "이동 금지" 로 명시). "plan 과 라이선스 근거가 **모두**"라는
조건을 지켰다. 둘 다 exclusion 등재·final_status 기록 완료.

## 19~20. Stale empty directory 분류·이동

```
빈 디렉토리                420
  EMPTY_POLICY_CONTAINER    19   최종 semantic container(4) + prior ledger 가
                                 존재를 요구하는 run 폴더(15)
  EMPTY_PAYLOAD_SUBDIR     401   최종 구조 **안**의 빈 하위폴더 — 항목·뼈대의 일부
  STALE_EMPTY_SOURCE         0
보존 이동                    0
삭제                        0
```

§20 기준은 "stale empty source **outside final roots**"다. 최종 구조 안의 빈
하위폴더를 옮기면 아카이브된 dataset 의 내부 구조를 뜯어내고 현재 구조의 뼈대를 부순다.
`archive/legacy_layout/empty_sources/` 는 **만들지 않았다**.

## 21. archive.csv 실행 상태

```
총 263 row (기존 246 + D2 신설 17)
executed=yes                                     247
final_status
  MOVED_STAGE2D2                                 199
  (빈값 = 이전 단계 executed=yes)                  48
  ALREADY_MOVED_BY_PRIOR_STAGE (source 부재)       12
  NO_SOURCE_ROW (2C2 원장 기록 전용)                 3
  KEEP_QUARANTINE — 현 위치가 라이선스 근거          1
──────────────────────────────────────────────────────
★ source 가 현재 존재하는 승인 row 중 executed=no   0
```

historical 필드(original_path · 최초 destination · 최초 classification · 과거 blocker ·
과거 evidence)는 삭제·덮어쓰기 하지 않았다.

## 22~24. path_map / assets / grouped inventory

```
path_map.csv       갱신 8 / 신규 191 / 총 414   (pre_stage2d2_path 보존)
assets.csv         17 row · SHA256 변경 0 · 경로부재 0
grouped_inventory  277 -> 142 rows (removed 199 / added 64)
                   depth {1:9, 2:10, 3:72, 4:51} · 그룹 단위 유지(파일 manifest 아님)
```

## 25. Exclusion

```
entries 16 / problems 0 / leaks 0 / stale 0 / duplicates 0 / path escape 0
```

이동 직후 1차 검사에서 **stale 4건**(`archive/_pallet_catalog_0123` ·
`_efront_12kp_check` · `_floor_applied14` · `_floor_compare`)이 나와 새 경로로 갱신했다.

⚠️ `_DISTRIBUTION_EXCLUDE.txt` 는 **gitignored** 라 다른 머신에는 없다.
tracked 재구축 명세 `distribution_exclusion_rebuild_spec.md` 를 신설했다.

## 26. License ledger

이동 대상에 라이선스 변경이 없어 판정 갱신은 없다. 문서 내 `_tmp_ph` 경로 1건을 최종
경로로 정정했다. NoAI baked 8종 · NVIDIA EULA · NoAI USD provenance 의 최종 위치는
`distribution_exclusion_rebuild_spec.md` 에 근거와 함께 정리했다.

## 27. Current reference — canonical

```
fix_required 0
```

이동 직후 **16건**이 걸렸다(현재 문서가 옛 경로를 CURRENT 로 서술). 40 치환으로 0.

## 28. Current reference — extended (`--no-ignore`)

```
actionable fix_required 0 / 비-actionable 7
```

7건은 `archive/` 내부 provenance README · 진단 코드 스냅샷 · 아카이브된 일회성 도구 ·
D1.2 가 남긴 의도적 각주다. 고치면 기록이 훼손된다.

## 29. Final top-level

```
assets/ reference/ runs/ manifests/ release/ archive/
README.md  _DISTRIBUTION_EXCLUDE.txt
isaac_assets/     ← management allowlist (역할·참조·유지근거 기록)

unexpected 0 · ZIP 0
```

## 30. Final archive tree

```
legacy_datasets/{redistributable 193,564 · noai_baked 129,746 · partial 241}
packages/{dataset_bundles 14 · background_sources 3 · corrupt 1}
superseded_runs/            21,321 파일 / 5,025 MiB   ★ D2 가 채웠다
legacy_scenes/{snapshots 7 · blender_backups 4}
legacy_assets/ nonredistributable/ unidentified/ corrupt/   (빈 policy container)
_noai_quarantine_usd/  README.md

archive depth-1: 134 감소 / 0 증가
```

## 31~32. 잔여

```
planned residual remaining   0
UNKNOWN remaining            0
BLOCKED remaining            0
unclassified remaining       0
```

## 33~41. 회귀

```
registry     ok=28 missing=0
unit         778 (745 + 신규 33) skip 0 fail 0
integration  31 skip 0
golden       51 skip 0
prior ledger 12종 failures 0 · C2C chain x2 -> 11 file(s) / failures 0
D2 ledger    199/199 VERIFIED · all · unhashed 0 · mismatch 0 · failures 0
5k FrameSpec 4,313 / 687 / 938f387d
5k proposal  4,439 / 3cd365ee / 12-12 PASS
no-render    8cb4109a · abs 0 · missing 0 · node 누락 0 · Dist_ 209  (렌더 0)
```

## 42. Filesystem invariance

```
data/pallet  before  dirs 2,567  files 363,090  bytes 192,468,109,581
             after   dirs 2,567  files 363,090  bytes 192,468,260,125
             delta   dirs 0      files 0        bytes +150,544

+150,286  data/pallet/manifests/*.csv        (archive +17행·+16열 · path_map +191행 ·
                                              assets stage2d2_status)
+   258   data/pallet/_DISTRIBUTION_EXCLUDE.txt
────────
+150,544  전액 특정 — 자산·데이터셋 바이트 변경 0, 새 data file 생성 0
```

## 43. Rollback 가능 여부

가능. cohort 별 원장에 `rollback_source`/`rollback_destination` 전량 보유.
순서는 D2_SUPERSEDED_RUNS → D2_LEGACY_DATASETS. 참조 전환·exclusion·문서·manifests 를
함께 되돌려야 하며 gitignored 파일은 명세·백업으로 복구한다 (`rollback_plan.md`).

## 44. D2_SCOPE_COMPLETE — ✅

```
selected 199 = ledger 199 = verified 199 = moved 199
failed 0 · rolled_back 0 · mismatch 0 · unhashed 0 · source residual 0
```

## 45. FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE — ✅

```
D2_SCOPE_COMPLETE                                true
승인 plan 중 source 존재 & executed=no             0
planned residual remaining                        0
UNKNOWN / BLOCKED / unclassified                  0 / 0 / 0
current broken ref                                0
exclusion leak                                    0
prior ledger unmapped missing                     0
KEEP·quarantine 최종 위치·유지 이유·배포 정책 기록   2/2
```

## 46. FULL_PHYSICAL_MINIMAL_TREE — ✅

```
top-level unexpected                       0
top-level ZIP                              0
semantic container 밖 dataset/package       0
stale empty source outside final roots      0
old/new duplicate path                      0
(의도된 EMPTY_POLICY_CONTAINER 19 · EMPTY_PAYLOAD_SUBDIR 401 은 위반으로 세지 않는다)
```

## 47. DATA_PALLET_CLEANUP_COMPLETE — ✅

세 판정 전부 true.
**폴더 정리 프로젝트 종료. 추가 Stage 2-D3 없음.**
다음 작업은 별도 데이터셋 pilot / 모델 실험 단계이며 이번 작업에서 시작하지 않았다.

## 48. git diff

```
scripts/data_prep/manage_pallet_data_layout.py         stage2d2 policy + is_d1 수정
scripts/data_prep/blender/tests/
  test_stage2d2_layout_completion.py                   신규 33 테스트
scripts/data_prep/blender/*.py (16) · *.sh (2)         참조 전환
scripts/data_prep/{visualize_*,evaluate_on_val,
  verify_keypoints}.py                                 참조 전환
scripts/data_prep/efront_calibration/README.md         참조 전환
config/synthetic/isaac_sim.yaml                        procedural_texture_dir 전환
_docs/{data_pallet_layout,dataset_license_ledger,
  blender_mcp_onboarding}.md                           갱신
_docs/experiments/v2_smoke50_continuous_eda_results.md 경로 갱신
_docs/history/{2026-07-31.md,changelog.md}             기록
CLAUDE.md · AGENTS.md                                  최종 구조 서술
reports/data_pallet_cleanup/grouped_inventory.csv      재생성
reports/data_pallet_cleanup/stage2d2/                  신규 산출물

(gitignored — diff 에 안 나옴)
data/pallet/_DISTRIBUTION_EXCLUDE.txt
data/pallet/manifests/{archive,path_map,assets}.csv

_docs/history/.last-compact-resume.md   ← 허용된 dirty. 수정·복구·stage·commit 안 함.
```

## 49. commit / push 여부

**commit 0 / push 0.** 사용자 승인 대기.

---

# 마감 수치

```
residual expected count                200      (D1.2 보고)
residual actual count                  201      (파일시스템 실측)
selected move rows                     199
selected files                      23,284
selected bytes               5,876,337,378      (5.47 GiB)
verified rows                          199
failed rows                              0
rolled_back rows                         0
pre-hash read bytes          5,876,337,378
post-hash read bytes         5,876,337,378
total read bytes            11,752,674,756      (10.95 GiB / 16 GiB)
SHA256 mismatch                          0
unhashed                                 0
prior mapped missing                    11      (C2C, 기존 chain 2종이 증명)
prior unmapped missing                   0
planned executed=no remaining            0
stale empty source before/after        0 / 0
top-level unexpected before/after      1 / 0    (isaac_assets 를 allowlist 로 문서화)
top-level ZIP before/after             0 / 0
current broken refs                      0      (이동 직후 16 -> 40 치환 후 0)
exclusion problems/leaks/stale     0 / 0 / 0    (이동 직후 stale 4 -> 갱신 후 0)
UNKNOWN remaining                        0
BLOCKED remaining                        0
unclassified remaining                   0
KEEP remaining                           2
quarantine remaining                     2
data file count before/after   363,090 / 363,090
data 삭제                                 0
empty directory 삭제                      0
ZIP 삭제                                  0
ZIP 수정                                  0
압축해제                                  0
weight 삭제                               0
Blender 렌더                              0
데이터 생성                               0
모델 학습                                 0
commit                                   0
push                                     0
```

DATA_PALLET_CLEANUP_COMPLETE=true
Stage 2 폴더 정리 종료. 추가 Stage 2-D3 없음.
