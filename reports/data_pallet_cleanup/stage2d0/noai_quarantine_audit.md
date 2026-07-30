# §11 NoAI quarantine 감사

```
경로        data/pallet/archive/_noai_quarantine_usd
파일 수      3
bytes       738,082
```

```
파일             bytes    sha256
──────────────────────────────────────────────
README.md         1,505   d211f0a125b69250…
scene_2.usd     169,812   f32217c308f974be…
scene_3.usd     566,765   de838fb1d1d4ac35…
```

## 참조 [확인]

```
registry key                 0건
CURRENT_RUNTIME              0건
current scene 내부 baked      **없음** — ledger:28 이 zstd 해제 grep 으로 재검증:
                             scene_2.usd=0 · scene_3.usd=0 · LP_merge_lambert16=0 ·
                             Material_018=0 · Legacy_Pallet_2/3=0 (재-bake 후)
                             백업 blend 에는 각각 존재
다른 복사본                    현 트리에서 scene_2/3.usd 는 이 격리 폴더에만 존재
연관 추출 dataset              archive/{training_data, training_data_v4, training_data_v4_split,
                             train_4pallet_mask_v1} 는 재-bake 이전 렌더라 NoAI 목재가 baked
                             -> legacy_datasets.csv 에서 NOAI_BAKED_DATASET 로 분류
```

## 라이선스·배포

```
ledger :48  B1 해소 — "Old Wooden Pallet"(Luka Feric) = Standard + NoAI.
            파이프라인에서 제거 완료, 구 데이터셋만 v2 재생성 필요
_DISTRIBUTION_EXCLUDE.txt:18  archive/_noai_quarantine_usd/  -> 등록됨, 검증기 OK
```

## 판정: **LICENSE_QUARANTINE**

## 이번 단계 조치: **없음 (이동 0)**

Stage 2-D1 제안: **이동하지 않는다**(status=`KEEP_QUARANTINE`, destination="(이동 없음)").
사유 — **격리 위치 자체가 provenance 근거**다. `archive/nonredistributable/` 아래로 옮기면
의미가 더 명확해 보이지만, ledger·exclusion·history 가 모두 현재 경로를 근거로 인용하고 있어
경로를 바꾸면 그 사슬이 흐려진다. 유지를 권고한다.
