# §16 distribution exclusion 갱신

`data/pallet/_DISTRIBUTION_EXCLUDE.txt` / 검증 `scripts/data_prep/verify_distribution_exclusions.py`

## 변경

background 안에 있던 원본 다운로드 ZIP 3개가 `archive/packages/background_sources/` 로
옮겨졌다. 압축 해제본이 `assets/scenes/backgrounds/background/` 에 있으므로, 릴리스에
원본 패키지까지 넣으면 **같은 자산을 두 번 배포**하게 된다. 새 entry 를 추가했다.

```
+ archive/packages/background_sources/
```

기존 entry(NoAI quarantine · isaac_assets · NoAI baked legacy dataset 4종 · 작업 산출물 4종)는
**전부 유지**했다. 하나도 지우거나 완화하지 않았다.

## 검증 결과 [확인, 실행함]

```
entries      : 11   (10 -> +1)
  OK   isaac_assets
  OK   archive/_noai_quarantine_usd
  OK   archive/_pallet_catalog_0123
  OK   archive/_efront_12kp_check
  OK   archive/_floor_applied14
  OK   archive/_floor_compare
  OK   archive/training_data
  OK   archive/training_data_v4
  OK   archive/training_data_v4_split
  OK   archive/train_4pallet_mask_v1
  OK   archive/packages/background_sources        ← 신규
problems     : 0    (stale 0 · duplicate 0 · path escape 0 · missing 0)
release leaks: 0
exit code    : 0
```

## 이동된 자산 쪽 확인

```
assets/scenes/backgrounds/background   archive 확장자 파일 0개   (C2A 로 전부 분리)
archive/packages/background_sources    zip 3개 / 157,408,367 bytes
                                       runtime/code/config/test 참조 0
```

배경 해제본(`assets/scenes/backgrounds/background/`)은 **릴리스 대상**이므로 exclude 하지 않는다.
CC-BY 4.0 표기 의무는 `_docs/dataset_license_ledger.md` · `attribution_cc-by_appendix.md` 가 계속 관리한다.
