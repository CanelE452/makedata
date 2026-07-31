# Stage 2-D2 최종 물리 구조 감사

전수 조사: `data/pallet` depth 1 + `archive/` depth 1~4 = **277 entry**
(`final_tree.csv`). depth 4 는 semantic **하위** container 아래만 펼친다 —
`superseded_runs/<item>` 같은 payload 를 펼치면 구조 감사가 파일 목록이 된다
(실측 2,981행 → 규칙 적용 후 277행).

## 1. top-level — 최종

```
data/pallet/
├── assets/                     현역 재사용 자산
├── reference/                  테스트가 픽셀 비교하는 정본 · 실사
├── runs/                       run 산출물 (diagnostics · eval · pilot · production · smoke)
├── manifests/                  local inventory (archive · path_map · assets · runs)
├── release/                    릴리스 패키징 뼈대
├── archive/                    과거 자산·데이터셋
├── README.md                   관리 파일
├── _DISTRIBUTION_EXCLUDE.txt   관리 파일 (gitignored)
└── isaac_assets/               ★ KEEP_QUARANTINE (management allowlist)
```

`isaac_assets/` 를 allowlist 에 넣은 근거 (§18 이 요구한 3항목):

```
역할            Isaac Sim 소스 에셋 (NVIDIA Isaac 4.5 Assets)
current 참조    config/synthetic/isaac_sim.yaml:9,10 — isaac_assets_root · hdri_dir (live)
최종 유지 근거   NVIDIA EULA 재배포 제한(ledger B6) + _DISTRIBUTION_EXCLUDE.txt 등재.
                archive.csv 에 이동 계획 row 가 **없어** 이번 범위의 승인 대상이 아니다.
                §12 는 "이동은 plan 과 라이선스 근거가 **모두** 있을 때만 허용" 이라
                근거만으로 옮기지 않았다.
```

```
top-level unexpected   0
top-level ZIP          0
```

## 2. archive/ — 최종

```
archive/
├── legacy_datasets/          325,514 files   83,766 MiB
│   ├── redistributable/      193,564 files   44,668 MiB
│   ├── noai_baked/           129,746 files   38,457 MiB   (릴리스 제외 8종)
│   └── partial/                  241 files       62 MiB
├── packages/                     18 files   81,490 MiB
│   ├── dataset_bundles/          14 files   77,020 MiB
│   ├── background_sources/        3 files      150 MiB
│   └── corrupt/                   1 file    4,320 MiB   (BadZipFile 보존)
├── superseded_runs/          21,321 files    5,025 MiB   ★ Stage 2-D2 가 채웠다 (199건)
├── legacy_scenes/                11 files    2,421 MiB
│   ├── snapshots/                 7 files    1,567 MiB
│   └── blender_backups/           4 files      854 MiB
├── legacy_assets/                 0 (빈 policy container)
├── nonredistributable/            0 (빈 policy container)
├── corrupt/                       0 (빈 policy container — packages/corrupt 로 대체됨)
├── unidentified/                  0 (빈 policy container — UNKNOWN 0 이라 비어 있다)
├── _noai_quarantine_usd/          3 files  ★ KEEP_QUARANTINE
└── README.md
```

`archive/` depth-1 은 **134 entry 가 줄고 0 이 늘었다** — 평평하게 널려 있던 진단·
데이터셋 디렉토리가 전부 semantic container 안으로 들어갔다.

## 3. 분류 전수 (277 entry)

```
분류                        n     files       MiB
──────────────────────────────────────────────────────
SEMANTIC_CONTAINER          16   670,444   339,800
EXPECTED_ROOT                6   358,545   179,403
MOVED_BY_LEDGER            250   346,864   172,702
KEEP_QUARANTINE              1     4,543     4,149   isaac_assets
PLAN_ROW_KEEP_QUARANTINE     1         3         1   _noai_quarantine_usd
MANAGEMENT_FILE              3         3         0
```

(계층이 겹치므로 합산하면 중복된다 — 실제 총량은 depth-1 합계 363,090 파일.)

```
★ UNKNOWN / 미분류                    0
   BLOCKED                            0
   unclassified                       0
   planned residual source 존재        0
   top-level ZIP                      0
   archive depth-1 평평한 dataset      0
   old/new duplicate path              0
   stale empty source outside final roots  0
```

## 4. 빈 디렉토리 — 420개, 삭제 0 · 이동 0

```
분류                       n     처리
──────────────────────────────────────────────────────────────────────
EMPTY_POLICY_CONTAINER    19     유지. 최종 semantic container(4) +
                                 prior ledger 가 존재를 요구하는 run 폴더(15)
EMPTY_PAYLOAD_SUBDIR     401     유지. 최종 구조 **안**의 빈 하위폴더
                                 (archive/<container>/<item>/logs · assets/…/metadata ·
                                  release/… 등) — 그 항목·뼈대의 일부다
STALE_EMPTY_SOURCE         0     보존 이동 대상 없음
```

§20 의 기준은 "stale empty source **outside final roots**"다. 최종 구조 안의 빈
하위폴더를 옮기면 아카이브된 dataset 의 내부 구조를 뜯어내고 현재 구조의 뼈대를 부순다
— 그래서 `archive/legacy_layout/empty_sources/` 는 **만들지 않았다**
(§18: "빈 폴더를 만들기 위해 억지로 모든 구조를 생성하지 않는다").
