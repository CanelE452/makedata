# D1C_LEGACY_DATASETS — legacy dataset 의미별 이동

```
[판정]  VERIFIED  (15건 / 54,442,767,106 B = 50.70 GiB / file 191,503)
```

## 목적지 — final plan 을 정본으로 사용했다

폴더명만 보고 다시 분류하지 않았다. 계획 CSV 의 `destination` 을 그대로 썼다.

```
archive/legacy_datasets/redistributable/   11건   (COMPLETE / attribution 만 필요)
  test_blender_v64 · v65 · v67 · v68 · v69 · v70 · test_indoor_v1
  train_palletobj_addon_v1 · train_palletobj_v1 · train_palletobj_v2 · trunc_addon_v1

archive/legacy_datasets/noai_baked/         3건   ★ NoAI baked — 릴리스 제외 유지
  train_4pallet_mask_v1 · training_data_v4 · training_data_v4_split

archive/legacy_datasets/partial/            1건   (PARTIAL_DATASET)
  _mask_test60
```

**NOAI_BAKED 를 redistributable 로 보내지 않았다.** **PARTIAL 을 COMPLETE 로
재분류하지 않았다.** `failed/` 는 이번 계획에 해당 row 가 없어 만들지 않았다.

## 이동 전 확인 [확인]

```
current runtime ref      0   (15건 전부)
current test ref         0
registry ref             0   (registry 24 경로와 교차 0)
golden/reference 아님     계획 CSV rollback_role 공란 · classification 확인
rollback-critical 아님    같음
license status 확정       redistributable 11 / NoAI baked 3 / partial 1
exclusion status 확정     NoAI 3건은 제외 등록 상태
source 존재              15/15
destination leaf 없음     15/15 (collision 0)
앞선 원장 충돌            0   ← D1D 실패 후 전수 재검사에서 확인
```

## ★ 계획 중 발견 — dataset 안의 package

`archive/training_data_v4_split/` 안에 `training_data_v4_split.zip` 이 있었다.
정책의 `ARCHIVE_IN_NON_PACKAGE_COHORT` 가 directory cohort 의 ZIP 을 막으므로
그대로면 D1-037 이 skip 되어 15건이 14건이 됐을 것이다.

무조건 허용으로 완화하지 않고 **두 층으로 분리**했다.

```
(a) entry 로서의 ZIP        -> D1A/D1B cohort 만 (row 단위 검사, 그대로 유지)
(b) dataset 내용물인 ZIP    -> 함께 이동. 단 같은 계획에 별도 row 로도 있으면 거부
                              (한 파일을 두 경로로 옮기려는 모순)
```

C2C 때의 blanket 금지는 "background 의 ZIP 을 C2A 가 먼저 분리한다"는 별개 요구였다.
이 ZIP 은 별도 계획 row 가 없는 dataset 내용물이라 함께 가는 것이 맞다. 테스트 2개로
고정했다 (`test_zip_inside_a_dataset_rides_along` ·
`test_zip_planned_twice_is_refused`).

이동 후에도 NoAI 제외 디렉토리 **안**에 있으므로 배포 제외가 유지된다.

## 절차와 결과

```
plan (hash-mode all)   15 moves / hashed 191,503 / unhashed 0 / 1,186.7s
  pre SHA256 read      54,442,767,106 B (50.70 GiB) / 한도 110 GiB
  source relpath set   원장 relative_files 에 191,503 경로 기록
  destination collision 0
  same volume (E:)     yes
apply (directory rename) 15 moves / 0.7s
verify                 failures 0 / sha256 checked 191,503 / 1,082.3s
  post SHA256 read     54,442,767,106 B (50.70 GiB)
  pre == post 파일 수   191,503 == 191,503
  pre == post bytes    54,442,767,106 == 54,442,767,106
  pre == post relpath  일치 (missing 0 / extra 0)
  SHA256 mismatch      0
  source 잔존           0 / 15
  destination 존재      15 / 15
예산 사용               101.41 / 110 GiB (92.2%)
checkpoint             VERIFIED
```

`license files : 0 verified` — 이 15개 dataset 트리에는 license 힌트 파일명이 없다
(라이선스는 `_docs/dataset_license_ledger.md` 와 exclusion 목록이 관리한다).

## exclusion 갱신 [확인]

NoAI 3건의 옛 경로가 사라져 stale 이 됐다. 검증기가 실제로 잡았다:

```
BAD  archive/training_data_v4          STALE_ENTRY
BAD  archive/training_data_v4_split    STALE_ENTRY
BAD  archive/train_4pallet_mask_v1     STALE_ENTRY
problems : 3
```

새 경로로 정정했다:

```
archive/legacy_datasets/noai_baked/training_data_v4/
archive/legacy_datasets/noai_baked/training_data_v4_split/
archive/legacy_datasets/noai_baked/train_4pallet_mask_v1/
```

`archive/training_data/` 는 **옛 경로 그대로 유지**했다 — CURRENT runtime 참조가
살아있어 D1 에서 이동하지 않은 `BLOCKED_REFERENCE` 항목이다.

재검증 (`exclusion_after_d1c.csv` = `exclusion_final.csv`):

```
entries 16 / problems 0 / release leaks 0 / stale 0 / exit 0
```

## cohort 회귀 (§11)

```
registry                 ok=24 missing=0
exclusion                entries 16 / problems 0 / leaks 0 / stale 0
C2C exact verify         failures 0
Stage 2-A / 2-B b1,b2,b3 failures 0
Stage 2-C2 C2A / C2B     failures 0
active scene SHA256      8cb4109adc6d3213…  (불변)
Blender no-render        absolute 0 · missing 0 · Dist_ 209 · node 누락 0
canonical CURRENT ref    fix_required 0
unit                     714 passed, skip 0, fail 0
integration               31 passed, skip 0, fail 0
golden overlay            51 passed, skip 0, fail 0
5k FrameSpec             4,313 / 687 · 938f387d…  (동일)
5k proposals             4,439 · 3cd365ee… · 12/12 PASS
```

## rollback

```
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d1/transactions/d1c_legacy_datasets.jsonl
```

되돌리면 exclusion 의 NoAI 3건도 옛 경로로 함께 되돌려야 한다 (gitignored — 수동).
