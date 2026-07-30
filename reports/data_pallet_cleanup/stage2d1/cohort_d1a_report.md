# D1A_PACKAGES — package 보존 이동

```
[판정]  VERIFIED  (14건 / 80,761,480,127 B = 75.21 GiB / file 14)
```

## 대상

`data/pallet/` 루트의 ZIP 14개 → `data/pallet/archive/packages/dataset_bundles/`

```
move_id  package                              bytes
────────────────────────────────────────────────────────
D1-019   pallet.zip                        16,637,698,137
D1-020   test_blender_v64.zip               1,781,592,200
D1-021   test_blender_v65.zip                  86,723,195
D1-022   test_blender_v68.zip                 906,940,260
D1-023   test_blender_v69.zip               3,653,659,280
D1-024   test_blender_v70.zip                 913,350,083
D1-025   test_indoor_v1.zip                   587,372,076
D1-026   train_4pallet_mask_v1.zip          9,675,248,635   ★ NoAI baked
D1-027   train_palletobj_addon_v1.zip       5,648,950,621
D1-028   train_palletobj_v1 (2).zip         8,316,876,455
D1-029   train_palletobj_v2 (2).zip         8,321,314,846
D1-030   train_palletobj_v2.zip             8,346,416,419
D1-031   train_palletobj_v3.zip            10,449,502,513
D1-032   trunc_addon_v1.zip                 5,435,835,407
```

이동 후 `data/pallet/*.zip` = **0개** (루트에 남은 ZIP 없음).

## 보존 규칙 — 삭제·병합 0

```
전부 보존                     14/14 이동, 삭제 0
structural match 도 보존       train_palletobj_v2.zip ↔ (2).zip (path·size 동일)
                              -> 둘 다 dataset_bundles/ 로. duplicates/ 미사용
CRC 가 다른 package 도 보존    Stage 2-D0 이 CRC 3~4건 불일치를 실측했다
bundle 보존                   pallet.zip (= v1+v2, 60,022 entries)
package 내부 수정 0            압축해제 0 · 재생성 0 · testzip 0
```

**structural match 를 duplicate 로 재분류하지 않았다.** Stage 2-D0 이 central directory
CRC 로 실측했을 때 `train_palletobj_v2.zip` vs `(2).zip` 은 path·size 가 전부 같은데도
CRC 가 3건 달랐다 — 같은 이름·같은 크기인데 내용이 다른 PNG 가 있었다. 파일 수와 총
bytes 만 봤다면 "중복이니 하나 지워도 된다"로 갔을 것이다. `duplicates/` 목적지는
이번 계획에 아예 없다.

## 절차와 결과

```
plan (hash-mode all)   14 moves / hashed 14 / unhashed 0 / 66.5s
  pre SHA256 read      80,761,480,127 B (75.21 GiB) / 한도 160 GiB
  destination collision 0
  same volume (E:)     yes
apply (rename)         14 moves / 0.1s
verify                 failures 0 / sha256 checked 14 / 66.5s
  post SHA256 read     80,761,480,127 B (75.21 GiB)
  pre == post SHA256   14/14 일치
  source 잔존           0
예산 사용               150.43 / 160 GiB (94.0%)
checkpoint             VERIFIED
```

mtime 은 rename 이므로 그대로 보존됐다 (예: `pallet.zip` 2026-05-20 09:54).

## license / exclusion 갱신 [확인]

`train_4pallet_mask_v1.zip` 은 NoAI baked 산출물의 압축본이라 배포 제외 대상이다.
이동으로 옛 경로가 사라졌으므로 `_DISTRIBUTION_EXCLUDE.txt` 를 새 경로로 정정했다.

```
before  train_4pallet_mask_v1.zip
after   archive/packages/dataset_bundles/train_4pallet_mask_v1.zip
```

검증 (`exclusion_after_d1a.csv`):

```
entries 16 / problems 0 / release leaks 0 / stale 0 / exit 0
```

다른 13개는 redistributable 이라 제외 대상이 아니다 — **과잉 제외하지 않았다.**
`archive/packages/background_sources/`(C2A 이동분) 항목은 영향 없다.

license/source sidecar: 이 14개는 ZIP 단일 파일 entry 이므로 별도 sidecar 가 없다
(`license files : 0 verified`). ZIP **안**의 license 항목은 압축을 풀지 않았으므로
그대로 보존된다.

## cohort 회귀 (§11)

```
registry                ok=24 missing=0
exclusion               entries 16 / problems 0 / leaks 0 / stale 0
C2C exact verify        failures 0
Stage 2-A / 2-B b1      failures 0
Stage 2-C2 C2A / C2B    failures 0
active scene SHA256     8cb4109adc6d3213…  (불변)
canonical CURRENT ref   fix_required 0
unit                    713 passed, skip 0, fail 0
integration              31 passed, skip 0, fail 0
```

## rollback

```
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d1/transactions/d1a_packages.jsonl
```

되돌리면 `_DISTRIBUTION_EXCLUDE.txt` 의 `train_4pallet_mask_v1.zip` 항목도 옛 경로로
함께 되돌려야 한다 (gitignored 파일이라 수동 — `rollback_plan.md` 참조).
