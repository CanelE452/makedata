# §15 최종 archive 구조 제안

## ★ 현재 실제 구조 — Stage 2-A skeleton 이 비어 있다 [확인]

```
data/pallet/archive/                    166 entries / 327,650 files / 82.589 GB
├── (dataset·run 폴더 156개가 depth 1 에 직접 놓여 있음)
│     train_palletobj_v3 9.95GB · train_4pallet_mask_v1 9.17GB · train_palletobj_v2 7.77GB
│     train_palletobj_v1 7.77GB · training_data_v4_split 7.75GB · training_data 5.99GB · ...
├── packages/                           3 파일 (background_sources, Stage 2-C2 에서 채움)
├── _noai_quarantine_usd/               3 파일 (LICENSE_QUARANTINE)
├── README.md
└── ★ Stage 2-A 가 만든 semantic 하위폴더 7개가 **전부 비어 있다** (0 파일)
      corrupt/ · legacy_assets/ · legacy_datasets/ · legacy_scenes/ ·
      nonredistributable/ · superseded_runs/ · unidentified/
```

즉 "archive/legacy_datasets 87.7GB" 는 **계획된 목적지 이름**이었고, 실제 dataset 은 아직
`archive/` 최상단에 평평하게 있다. Stage 2-D1 이 채워야 할 곳이 바로 그 빈 폴더 7개다.

## 제안 (기존 구조 우선 · 불필요한 중첩 없음)

```
data/pallet/archive/
├── legacy_datasets/
│   ├── redistributable/     COMPLETE_LEGACY_DATASET 13종 (NoAI 아님)
│   ├── noai_baked/          training_data · training_data_v4 · training_data_v4_split ·
│   │                        train_4pallet_mask_v1  (릴리스 불가, exclusion 등록됨)
│   ├── partial/             PARTIAL_DATASET 중 50MB 이상
│   └── failed/              (해당 없음 — runs/failed 는 Stage 2-A 에서 이미 분리됨)
├── packages/
│   ├── dataset_bundles/     최상위 ZIP 14개 (84.8GB) — pallet.zip 등 bundle 포함
│   ├── background_sources/  (Stage 2-C2 완료, 유지)
│   ├── duplicates/          **비워 둔다** — CRC 로 확인된 중복이 없다 (아래 참조)
│   └── corrupt/             train_palletobj_v1.zip (truncated, 4.22GB)
├── legacy_scenes/
│   ├── rollback/            **비워 둔다** — rollback blend 는 production 폴더에 유지
│   ├── snapshots/           legacy .blend 8개
│   └── blender_backups/     .blend1 3개
├── legacy_assets/           (해당 없음)
├── nonredistributable/
│   ├── nvidia/              isaac_assets 4.05GB — 이동 시 exclusion 동시 갱신 필요
│   └── unknown_license/     (해당 없음)
└── unidentified/            (해당 없음 — UNKNOWN 0건)
```

### `packages/duplicates/` 를 비워 두는 이유 [확인]

이름·파일 수·bytes 로는 중복처럼 보였던 쌍이 **CRC 로는 전부 달랐다.**

```
비교                                        entries   path  size  CRC        판정
────────────────────────────────────────────────────────────────────────────────────────
train_palletobj_v2.zip vs (2).zip            30,010    ✓     ✓    ✗ 3건 불일치  STRUCTURAL only
pallet.zip/train_palletobj_v1 vs (2).zip     30,012    ✓     ✓    ✗ 4건 불일치  STRUCTURAL only
pallet.zip/train_palletobj_v2 vs v2.zip      30,010    ✓     ✓    ✗ 4건 불일치  STRUCTURAL only
modular_buildings_industrial_area(.)zip ×2       29    ✓     ✓    ✓            CONTENT_VERIFIED
```

불일치 파일만 표적 CRC 검증한 결과(3.3MB read), 세 사본(추출본 · ZIP · bundle) 중
**어느 것도 다른 것의 정확한 복제가 아니다.** 같은 파일명·같은 크기인데 내용이 다른 PNG 가
3~4개씩 있다. 따라서 `duplicates/` 로 넣을 항목이 없다.

유일한 CONTENT_VERIFIED_BY_CRC 쌍은 background_sources 의 modular zip 2개이고,
그건 Stage 2-C2 에서 이미 둘 다 보존 이동했다.

**이번 단계에서는 폴더를 하나도 만들지 않았다.** 위 구조는 Stage 2-D1 계획서일 뿐이다.
