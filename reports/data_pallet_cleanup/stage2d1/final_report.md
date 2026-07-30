# Stage 2-D1 최종 보고 — data/pallet archive 정리

## 1. 목적과 최종 판정

Stage 2-D0.1 이 확정한 계획의 READY 40건을 archive 의미별 하위폴더로 실제 이동한다.
같은 볼륨 rename 만, 전 파일 SHA256 이동 전·후 대조, 삭제 0.

```
[판정]  D1_PARTIAL
        READY 40건 중 30건 VERIFIED (130.14 GiB / 191,518 파일)
        10건(D1D_BLEND_BACKUPS)은 앞선 원장 충돌로 ROLLED_BACK

        D1_READY_SCOPE_COMPLETE          ✗  40건 전부 VERIFIED 아님 (30/40)
        FULL_DATA_PALLET_LAYOUT_COMPLETE ✗  top-level 잔여 65 · BLOCKED 8 · KEEP 12

        commit 0 / push 0 — 사용자 승인 대기
```

## 2. branch / HEAD

```
branch  chore/data-pallet-stage2d1-archive-finalization
HEAD    01290786b978cdaa2b70fcb99bb48625dbfe3b39  (= origin/main, 작업 전과 동일)
```

## 3. frozen plan SHA256

```
plan    reports/data_pallet_cleanup/stage2d01/proposed_stage2d1_moves_final.csv
sha256  c343b807a0e3b5df8b8f6ee8843344b11511564c7046be55810c631cdc3b8e8b
```

원장 각 row 에 `plan_path` · `plan_sha256` 을 박았다. 계획이 바뀌면 plan 이 exit 2 로
거부한다(테스트 `test_plan_edited_after_freeze_is_refused`).

## 4. selected READY count

```
total_rows      60
selected        40  (READY 39 + CORRUPT_MOVE_READY 1)
selected_bytes  142,134,662,870  (132.37 GiB)
selected_files  191,528
cohort          D1B 1 · D1D 10 · D1A 14 · D1C 15   (기대치와 정확히 일치)
재검증 문제      0  (source 존재 · collision 0 · same volume · refs 0 · role/license/quarantine/weight)
```

## 5. excluded BLOCKED / KEEP count

```
BLOCKED_REFERENCE  4    KEEP_ACTIVE      6
BLOCKED_UNKNOWN    4    KEEP_ROLLBACK    4
                        KEEP_QUARANTINE  2
합계 BLOCKED 8 / KEEP 12 — 계획에 들어가지 않았고 이동하지도 않았다
```

## 6. hash budget

```
cohort                예산      pre       post      합계       사용률
────────────────────────────────────────────────────────────────────
D1B_CORRUPT           10 GiB    4.22      4.22      8.44 GiB   84.4%
D1D_BLEND_BACKUPS      6 GiB    2.24      2.24      4.47 GiB   74.5%
D1A_PACKAGES         160 GiB   75.21     75.21    150.43 GiB   94.0%
D1C_LEGACY_DATASETS  110 GiB   47.22*    47.22*   101.41 GiB   92.2%
────────────────────────────────────────────────────────────────────
상한 286 GiB / 실사용 257.78 GiB    worker=1 (순차) · cohort 동시 hash 0
```

*D1C 는 50.70 GiB(= 54,442,767,106 B). 위 GiB 값은 cohort 표기 반올림 차이다.

예산 초과 시 **selective 로 강등하지 않고 중단**한다. 해시 시작 전(stat 기반)과 읽는 중
양쪽에서 검사한다. 옵션을 생략하면 무제한 = 기존 정책 동작 불변.

## 7. D1B plan/apply/verify

```
plan    1 move / hashed 1 / unhashed 0 / 3.2s / pre 4.22 GiB
apply   1 move / 0.1s / rename
verify  failures 0 / sha256 1 / 3.5s / post 4.22 GiB / pre==post
source  data/pallet/train_palletobj_v1.zip            (잔존 0)
dest    archive/packages/corrupt/train_palletobj_v1.zip
```

이동 전 D0 판정과 대조: `open_status=NO` · `BadZipFile` · size 4,529,431,174 동일 [확인].
이동 후에도 `BadZipFile` — **손상 상태 그대로 보존**. 복구·압축해제·재작성·삭제 0.

## 8. D1D plan/apply/verify → ROLLED_BACK

```
plan    10 moves / hashed 10 / unhashed 0 / 1.8s / pre 2.24 GiB
apply   10 moves / 0.1s
verify  failures 0 / sha256 10 / post 2.24 GiB      ← cohort 자체는 통과했다
회귀    ★ Stage 2-C2 C2C exact verify failures 11 (MISSING)
조치    D1D 만 역순 rollback -> 10건 원위치, C2C failures 0 복구
```

상세는 §11 과 `cohort_d1d_report.md`.

## 9. D1A plan/apply/verify

```
plan    14 moves / hashed 14 / unhashed 0 / 66.5s / pre 75.21 GiB
apply   14 moves / 0.1s
verify  failures 0 / sha256 14 / 66.5s / post 75.21 GiB / 14/14 pre==post
source  data/pallet/*.zip 14개                        (잔존 0 — 루트 ZIP 0개)
dest    archive/packages/dataset_bundles/
```

## 10. D1C plan/apply/verify

```
plan    15 moves / hashed 191,503 / unhashed 0 / 1,186.7s / pre 50.70 GiB
apply   15 directory rename / 0.7s
verify  failures 0 / sha256 191,503 / 1,082.3s / post 50.70 GiB
        pre==post: 파일 수 191,503 · bytes 54,442,767,106 · relpath set 일치
dest    legacy_datasets/redistributable 11 · noai_baked 3 · partial 1
```

목적지는 **final plan 을 정본**으로 썼다. NOAI_BAKED 를 redistributable 로 보내지
않았고 PARTIAL 을 COMPLETE 로 재분류하지 않았다.

## 11. 전체 이동 files / bytes

```
cohort                rows   files      bytes            상태
──────────────────────────────────────────────────────────────────────
D1B_CORRUPT              1        1     4,529,431,174    VERIFIED
D1A_PACKAGES            14       14    80,761,480,127    VERIFIED
D1C_LEGACY_DATASETS     15  191,503    54,442,767,106    VERIFIED
──────────────────────────────────────────────────────────────────────
합계                    30  191,518   139,733,678,407    130.14 GiB
D1D (rollback)          10       10     2,400,984,463    ROLLED_BACK
```

## 12. 전체 SHA256 결과

```
hash_mode              all (전 cohort 강제)
hashed_file_count      191,518
unhashed_file_count    0
SHA256 mismatch        0
pre-hash read          139,733,678,407 B (130.14 GiB)
post-hash read         139,733,678,407 B (130.14 GiB)
합계 read              260.27 GiB
source 잔존             0 / 30
destination 존재        30 / 30
relative path set      pre == post (missing 0 / extra 0)
file count / bytes     pre == post
```

D1C 는 두 번째 verify 를 돌리지 않았다 — 50.70 GiB 재독은 그 cohort 예산(101.41/110 GiB
사용)을 넘긴다. 근거로 원장 기록(15/15 `verified_at` · `post==pre` · src 잔존 0)을 쓴다.

## 13. corrupt package 보존 결과

```
train_palletobj_v1.zip   4,529,431,174 B
  이동 전  BadZipFile: File is not a zip file   (D0 판정과 동일)
  이동 후  BadZipFile: File is not a zip file   (상태 보존)
  위치     archive/packages/corrupt/
  삭제     0 · 복구 시도 0 · testzip 0 · 재압축 0
```

유일본이 아니라는 사실(`train_palletobj_v1 (2).zip` 존재)을 삭제 근거로 쓰지 않았다.

## 14. blend backup 결과

```
계획 10건 -> 이동 -> verify 통과 -> ★ C2C 원장 깨짐 -> 전체 rollback
현재  assets/scenes/production/blender_scene/ 에 blend 17개 그대로
      archive/legacy_scenes/{snapshots,blender_backups}/ 는 비어 있다 (폴더 삭제 안 함)
보호 blend 6개(active 2 · rollback-critical 4) SHA256 전부 불변
```

이동 전 확인: 10건 전부 `COLD_ARCHIVE` · registry 참조 0 · runtime/test 참조 0 ·
**SHA256 identity 일치**. `.blend1` 이라는 이유로 옮기지 않았다.

## 15. package 보존 결과

```
14/14 이동, 삭제 0, 내부 수정 0, 압축해제 0
structural match 도 보존: train_palletobj_v2.zip ↔ (2).zip (path·size 동일)
CRC 불일치 package 도 보존 (Stage 2-D0 이 3~4건 실측)
bundle 보존: pallet.zip (v1+v2, 60,022 entries)
duplicates/ 목적지 사용 0 — 계획에 그런 row 가 없다
mtime 보존 (rename)
```

## 16. legacy dataset 결과

```
redistributable 11   test_blender_v64/65/67/68/69/70 · test_indoor_v1 ·
                     train_palletobj_addon_v1 · train_palletobj_v1 · v2 · trunc_addon_v1
noai_baked       3   train_4pallet_mask_v1 · training_data_v4 · training_data_v4_split
partial          1   _mask_test60
failed           —   해당 row 없음 (폴더 만들지 않았다)
```

`archive/training_data_v4_split/` 안의 `training_data_v4_split.zip` 은 dataset
내용물로 함께 이동했다 — 별도 계획 row 가 없으므로. 이동 후에도 NoAI 제외 디렉토리
안이라 배포 제외 유지.

## 17. structural match package 보존 확인

```
Stage 2-D0 central directory CRC 실측:
  train_palletobj_v2.zip vs (2).zip   30,010 entries, path·size 동일 -> CRC 3건 불일치
  pallet.zip/v1 vs (2).zip                                          -> CRC 4건 불일치
```

path·size 만 같고 내용이 다르다. **duplicate 로 재분류하지 않았고 전부 보존했다.**
`archive/packages/duplicates/` 는 만들지 않았다.

## 18. exclusion 변경

```
시점        entries  problems  leaks  stale   변경
───────────────────────────────────────────────────────────────────────────────
before          16        0       0     0
D1A 후          16        0       0     0    train_4pallet_mask_v1.zip ->
                                             archive/packages/dataset_bundles/…
D1C 전          16        3       0     3    ★ 검증기가 stale 3건을 잡았다
D1C 후          16        0       0     0    NoAI 3건 -> legacy_datasets/noai_baked/…
```

`archive/training_data/` 는 D1 이 옮기지 않아 옛 경로 유지. redistributable 11건은
제외 대상이 아니므로 등록하지 않았다(과잉 제외 금지).

`data/pallet/_DISTRIBUTION_EXCLUDE.txt` 는 **gitignored** 다 — 이 파일 변경은 커밋에
포함되지 않는다. tracked 정본 기록은 `_docs/dataset_license_ledger.md`.

## 19. license ledger

저장경로 열을 새 경로로 갱신하고 Stage 2-D1 섹션을 추가했다. B8(v4 파생 NoAI 상속
미확정)은 **여전히 미해결** — 그 4종은 `BLOCKED_UNKNOWN` 으로 이동하지 않았다.

## 20. local manifests

```
archive.csv    30 row 갱신 (executed=yes · moved_stage=Stage2-D1) + D1 열 16개 추가
               나머지 202 row 는 executed=no (Stage 2-A 계획 미실행분)
path_map.csv   D1 이동 30건 신규 row (175 -> 205). original_path 유지
assets.csv     stage2d1_status 열 — 현역 자산 17개 SHA256 재확인, 변경 0
```

## 21. grouped inventory

```
416 -> 266 행.  removed 206 / added 56
depth 분포  {1: 74, 2: 151, 3: 8, 4: 33}      entry_type {dir 193, file 73}
MOVED_STAGE2D1 30행
```

**그룹 단위 유지** — 266행 vs data/pallet 파일 363,090개. 전 파일 manifest 로 바꾸지
않았다. depth 3~4 를 추가한 이유는 D1 이 만든 semantic 컨테이너의 자식까지 내려가야
옮겨진 package·dataset 이 row 로 보이기 때문이다.

removed 206 은 D1 30건 + Stage 2-A/B/C2 이동분 176 이다 (이 파일은 Stage 1 스냅샷이라
그동안 재생성되지 않았다). 사라진 경로 전체 목록은 `grouped_inventory_diff.md` 에 남겼다.

## 22. final tree

`final_tree.md` 참조. 요약:

```
data/pallet top-level 74   권장 9 + 잔여 65 (log 40 · script 11 · 진단 dir 10 ·
                           출력 3 · 이미지 1 = 4.27 GiB)
data/pallet/*.zip      0   (before 15)
archive depth-1      151   (before 166)
semantic 폴더        packages/{background_sources 3, dataset_bundles 14, corrupt 1}
                     legacy_datasets/{redistributable 11, noai_baked 3, partial 1}
                     legacy_scenes/{snapshots 0, blender_backups 0}
빈 폴더 삭제           0
```

## 23. remaining BLOCKED

```
BLOCKED_REFERENCE 4  16.13 GiB  archive/training_data(runtime ref 10) ·
                                train_palletobj_v3 · train_palletobj_v3_post_v1 ·
                                _sandbox_parking_lot_check.blend
                                -> registry 키 등록 + 참조 전환 선행 필요
BLOCKED_UNKNOWN   4  14.53 GiB  v4 파생 (GREYBUG · bg1bak · emptywood · pilotA)
                                -> NoAI 상속 확정 필요 (ledger B8)
```

## 24. remaining KEEP

```
KEEP_ACTIVE      2  registry active blend (production_scene · experimental_scene)
KEEP_ROLLBACK    4  rollback-critical blend
KEEP_ACTIVE      4  UNREFERENCED_WEIGHT — weights/ 는 data/pallet 밖, gitignored.
                    "참조가 없다"는 사실 기술이며 삭제 후보가 아니다. 목적지 미정.
KEEP_QUARANTINE  2  isaac_assets (NVIDIA EULA) · archive/_noai_quarantine_usd
추가             10  D1D — 앞선 원장 충돌로 이동 불가 (원장 연쇄 선행 필요)
```

## 25. canonical current references

```
fix_required = 0   (D1B 후 · D1A 후 · 최종 3회 확인)
```

새 archive destination 을 current runtime 에서 직접 참조하는 row 는 생기지 않았다.

## 26. registry

```
ok=24  missing=0  absent_optional=0     (전 cohort 후 매번 확인)
```

## 27. unit

```
664 -> 714 passed (+50), skip 0, fail 0
신규 전부 tests/test_stage2d1_archive_finalization.py (tmpdir 전용)
```

## 28. integration

```
31 passed, skip 0, fail 0   (PALLET_DATA_INTEGRATION=1)
```

## 29. golden

```
51 passed, skip 0, fail 0
```

## 30. 기존 transaction verify

```
stage2a 6,921 / b1 3,220 / b2 68 / b3 0 / c2a 3 / c2b 74 / c2c 1,336   failures 전부 0
원장 SHA256 4종 불변: fe1adc26… · 43461e47… · 0d0c06a8… · 241f5c56…
C2C 는 exact expected-addition 모드 (broad allow 사용 0)
```

## 31. D1 transaction verify

```
d1b 1 / d1a 14 / d1c 15 = 30행, hash_mode all, unhashed 0, mismatch 0, failures 0
verified_at 30/30 · post==pre 30/30 · src 잔존 0 · dst 존재 30
```

## 32. 5k FrameSpec

```
accepted 4,313 / rejected 687
sha256 938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39   동일
```

## 33. 5k proposal

```
accepted 4,439 / 5,000 (88.78%)
digest 3cd365eec96d1009…  run1 == run2
12/12 checks passed
```

## 34. Blender no-render

```
absolute 0 · missing 0 · Dist_ 209 · node image missing 0
images 603 (textures 158 · distractors 356 · hdri 1)
HDRI 30/30 · floor 42/42 · wood 27/27 decode ok
active scene sha256 8cb4109adc6d3213…  불변
렌더 0
```

## 35. rollback 가능 여부

가능하다. 원장 3종이 살아 있고 각 row 에 `rollback_source` · `rollback_destination` ·
`source_sha256`(전 파일)이 기록돼 있다. 절차·주의(exclusion 수동 복구)는
`rollback_plan.md`.

## 36. FULL layout 완료 여부

**아니다.** BLOCKED 8 · KEEP 12 · D1D 10 · top-level 잔여 65 · archive depth-1 잔여 136.
`FULL_DATA_PALLET_LAYOUT_COMPLETE` 라고 쓰지 않는다.

## 37. git diff

```
10 files changed (tracked)
  scripts/data_prep/manage_pallet_data_layout.py       정책·budget·guard (+463)
  scripts/data_prep/blender/tests/test_stage2d1_...py  신규 50 테스트
  reports/data_pallet_cleanup/grouped_inventory.csv    416 -> 266 행
  reports/data_pallet_cleanup/README.md                stage2d1 섹션
  reports/data_pallet_cleanup/stage2d1/                신규 폴더 (보고서 24종 + 원장 4)
  _docs/data_pallet_layout.md                          §6 상태 · §8 신규
  _docs/dataset_license_ledger.md                      경로 갱신 + D1 섹션
  CLAUDE.md · AGENTS.md                                archive 구조 한 줄
  _docs/history/2026-07-30.md · changelog.md           기록
gitignored (커밋 대상 아님)
  data/pallet/_DISTRIBUTION_EXCLUDE.txt   3,586 -> 4,210
  data/pallet/manifests/*.csv             archive/path_map/assets 갱신
  data/pallet/README.md · archive/README.md · manifests/README.md
git add -A / git add . 사용 0
```

## 38. commit / push 여부

```
commit  0
push    0
```

사용자 승인 없이 commit·push 하지 않는다. 데이터 개선·pilot 생성·모델 학습을
자동 시작하지 않는다.

---

## 최종 수치

```
D1 READY selected count        40
D1 VERIFIED count              30
D1 FAILED count                 0   (D1D 는 cohort verify 통과 후 회귀에서 걸렸다)
D1 ROLLED_BACK count           10
D1B files / bytes               1 / 4,529,431,174
D1D files / bytes              10 / 2,400,984,463   (rollback)
D1A files / bytes              14 / 80,761,480,127
D1C files / bytes         191,503 / 54,442,767,106
전체 이동 files           191,518
전체 이동 bytes        139,733,678,407  (130.14 GiB)
pre-hash read bytes    139,733,678,407  (130.14 GiB)
post-hash read bytes   139,733,678,407  (130.14 GiB)
SHA256 mismatch                 0
unhashed files                  0
destination collision           0
canonical CURRENT refs          0
exclusion leaks                 0
BLOCKED remaining               8
KEEP remaining                 12  (+ D1D 10)
UNKNOWN remaining               0
data 삭제                       0
ZIP 삭제                        0
package 내용 수정                0
압축해제                        0
weight 이동                     0
isaac_assets 이동               0
NoAI USD 이동                   0
Blender 렌더                    0
모델 학습                       0
commit                          0
push                            0
```
