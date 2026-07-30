# §13 라이선스 · 배포 교차검증

대조: `_docs/dataset_license_ledger.md` × `data/pallet/_DISTRIBUTION_EXCLUDE.txt` × 실제 파일 트리
검증기: `scripts/data_prep/verify_distribution_exclusions.py --csv reports/.../stage2d0/...`

> 출력 경로를 stage2d0 로 명시했다. 기본값이 예전엔 Stage 2-B 스냅샷을 가리켜 돌릴 때마다
> 과거 증거를 덮어썼고, Stage 2-C2 에서 이를 발견해 기본값을 stage 중립 경로로 고쳤다.
> 이번 실행 후 `stage2b/` · `stage2c1/` · `stage2c2/` 스냅샷은 **git status clean** 으로 확인했다.

## 검증 결과 [확인, 실행함]

```
entries      : 11
  OK   isaac_assets                            NVIDIA EULA (ledger B6)
  OK   archive/_noai_quarantine_usd            NoAI 목재 USD (ledger B1)
  OK   archive/_pallet_catalog_0123            작업 산출물
  OK   archive/_efront_12kp_check              작업 산출물
  OK   archive/_floor_applied14                작업 산출물
  OK   archive/_floor_compare                  작업 산출물
  OK   archive/training_data                   NoAI baked (ledger:25,70)
  OK   archive/training_data_v4                NoAI baked
  OK   archive/training_data_v4_split          NoAI baked
  OK   archive/train_4pallet_mask_v1           NoAI baked
  OK   archive/packages/background_sources     원본 다운로드 ZIP (Stage 2-C2 추가)
problems     : 0   (stale 0 · duplicate 0 · path escape 0 · missing 0)
release leaks: 0
exit code    : 0
```

## 이번 감사에서 확인한 누락 후보

```
항목                                        현재 exclusion   판정
──────────────────────────────────────────────────────────────────────────────────────
최상위 ZIP 14개 (84.8GB)                     미등록          ★ 검토 필요 (아래)
archive/training_data_v4_split_GREYBUG      미등록          ★ 검토 필요 (아래)
archive/training_data_v4_split_bg1bak       미등록          ★ 검토 필요
archive/training_data_v4_emptywood          미등록          ★ 검토 필요
archive/training_data_v4_pilotA             미등록          ★ 검토 필요
archive/train_palletobj_v* (v1/v2/v3/addon) 미등록          유지 (attribution 후 사용 가능)
archive/trunc_addon_v1                      미등록          유지
archive/test_blender_v* · test_indoor_v1    미등록          유지
```

### ★ 최상위 ZIP 14개 — exclusion 검토 필요 [판정]

`pallet.zip`(15.5GB) 은 `train_palletobj_v1` + `v2` 를 담은 bundle 이고,
`train_4pallet_mask_v1.zip`(9.0GB) 은 **NoAI baked dataset 의 압축본**이다.
추출본(`archive/train_4pallet_mask_v1`)은 exclusion 에 있는데 **ZIP 은 없다.**

→ 같은 NoAI 자산이 ZIP 경로로 릴리스에 새어 나갈 수 있다.
Stage 2-D1 에서 `archive/packages/dataset_bundles/` 로 옮기면 그 폴더째 exclusion 하는 것이
가장 안전하다(background_sources 와 같은 방식). **이번 단계에서는 이동·수정하지 않았다.**

### ★ v4_split 파생 3종 — NoAI 상속 여부 미확정 [판정: UNKNOWN 아님, 확인 필요]

`training_data_v4_split_GREYBUG` · `_bg1bak` · `training_data_v4_emptywood` ·
`training_data_v4_pilotA` 는 이름상 `training_data_v4*` 계열 파생이고, 그 본체는 NoAI baked 로
exclusion 되어 있다. 그러나 **파생본이 같은 blend 로 렌더됐는지는 파일 근거로 확인하지 않았다**
(라벨 metadata 의 generator/blend 지문을 읽어야 한다).

- 이름 유사성만으로 NoAI 를 단정하지 않는다 → 현재 `COMPLETE_LEGACY_DATASET` 로 두었다
- Stage 2-D1 전에 라벨 metadata 확인이 필요하다. 확인 전에는 `legacy_datasets/noai_baked/` 로
  옮기지 않고 `redistributable/` 로도 옮기지 않는 것이 안전하다

## ledger 대응 [확인]

```
ledger 항목   상태          이번 감사에서 확인한 것
──────────────────────────────────────────────────────────────────────────────────────
B1 (NoAI)     해소          _noai_quarantine_usd 3파일 존재, 현 scene 에 baked 0 (ledger:28 재검증)
B2 (Isaac)    종료(오탐)     프로덕션 blend Isaac 지문 0 — 이번 감사에서 반증 없음
B5 (attribution) 미해결      CC-BY 표기 의무 — background 2종 · distractor CC-BY 계열
B6 (isaac 제외) 미해결 LOW   isaac_assets 4.05GB, exclusion 등록됨. 이동 계획만 작성
```
