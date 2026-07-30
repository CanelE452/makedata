# data/pallet 레이아웃 정본 (tracked)

`data/pallet` 은 `.gitignore:5 data/` 로 전체가 git 밖에 있다. 그래서 그 안의
`README.md` 들은 저장소에 남지 않는다. **이 문서가 tracked 정본**이고,
`data/pallet/README.md` 는 같은 내용의 로컬 사본이다.

- 최종 갱신: 2026-07-28 (Stage 2-A)
- 조사 근거: `reports/data_pallet_cleanup/` (Stage 1) + `reports/data_pallet_cleanup/stage2a/` (Stage 2-A)

---

## 1. 경로는 registry 로만 조회한다

```
config/synthetic/pallet_paths.yaml                 경로 정의 (JSON 서브셋, blender.yaml 과 같은 관례)
scripts/data_prep/blender/pallet_data_paths.py     resolver — bpy import 없음
```

```python
import pallet_data_paths as pdp

hdri   = pdp.get("hdri_root")             # 절대경로
paths  = pdp.load()
report = paths.audit()                    # {"ok": [...], "missing": [...], "absent_optional": [...]}
```

```bash
python scripts/data_prep/blender/pallet_data_paths.py            # 전 경로 감사
python scripts/data_prep/blender/pallet_data_paths.py --key hdri_root
PALLET_DATA_ROOT=/mnt/data/pallet python ...                     # root 만 override
```

### 정본은 하나다

```
runtime source of truth   config/synthetic/pallet_paths.yaml       <- 실행 코드는 이것만 읽는다
resolver                  scripts/data_prep/blender/pallet_data_paths.py
local inventory snapshot  data/pallet/manifests/*.csv              <- 조사 시점 기록. runtime config 아님
tracked 조사·이동 기록      reports/data_pallet_cleanup/
```

- 실행 코드는 `pallet_paths.yaml` 만 읽는다. `assets.csv` 를 읽는 실행 경로는 없다.
- `assets.csv` 를 수정해도 실행 경로는 **바뀌지 않는다.**
- runtime 경로 변경은 `pallet_paths.yaml` 수정으로만 한다.
- 경로 이동과 registry 변경은 **같은 transaction 단계에서 함께 검증**한다
  (옮기고 registry 를 안 고치면 audit 의 `missing` 으로, 반대면 실행 시 파일 없음으로 드러난다).

규칙:

- registry 에는 **지금 실제로 있는 경로**만 적는다. 옮기고 싶은 경로(TARGET)를 미리 적지 않는다.
  아직 비어 있는 `assets/` 를 가리키면 런타임이 조용히 빈 폴더를 읽게 된다
  (`tests/test_pallet_data_paths.py` 가 이걸 막는다).
- 없는 경로에 대해 **임의 fallback 을 만들지 않는다.** 없으면 `missing` 으로 보고한다.
- `optional_keys` 에 있는 키만 부재를 허용한다(`absent_optional`).

배선 완료된 소비자:

```
blender_config.py       WOOD_TEXTURE_DIR / FLOOR_TEXTURE_DIR  -> registry
v2_realize.py           목재·바닥 텍스처 폴백 경로              -> registry
v2_pipeline.py          DEFAULT_MANIFEST                      -> registry
distractor_pool_v2.py   DEFAULT_MANIFEST                      -> registry
```

legacy 생성기(`gen_dataset_v4.py`, `gen_4pallet_mask.py`, `gen_trunc_addon.py`,
`run_*.sh`, `_render_*`, `_make_*` 등)는 **일부러 그대로 뒀다.** 그 스크립트들의 경로는
"그때 그 데이터셋을 재현하기 위한 옛 경로"라서 현재 경로로 소급 수정하면 재현성이 깨진다.

---

## 2. 세 가지 상태

### CURRENT — 생성기가 지금 읽는 경로

**runtime source of truth 는 `config/synthetic/pallet_paths.yaml` 하나다.**
`data/pallet/manifests/*.csv` 는 **local inventory snapshot** 이지 runtime config 가 아니다.
아래 표는 그 registry 의 현재 값이다(`pallet_data_paths.py --audit` 로 언제든 재출력 가능).

```
registry key                current path                                              비고
───────────────────────────────────────────────────────────────────────────────────────────────────
production_scene            assets/scenes/production/blender_scene/
                              synth_data_scene_portable_stage2c2.blend                 ★ active (Stage 2-C2)
production_scene_stage2c1_rollback
                            assets/scenes/production/blender_scene/
                              synth_data_scene_portable.blend                          rollback 2 (수정 금지)
production_scene_rollback_source
                            assets/scenes/production/blender_scene/synth_data_scene.blend  rollback 3 (수정 금지)
production_scene_textures   assets/scenes/production/blender_scene/textures            blend //textures 158
experimental_scene          assets/scenes/production/blender_scene/_sandbox_palletobj_production.blend
background_root             assets/scenes/backgrounds/background                       Stage 2-C2 이동 완료
background_package_archive  archive/packages/background_sources                        원본 ZIP 3개 보존
distractor_root             assets/distractors/library                                 Stage 2-C2 이동 완료
distractor_manifest         assets/distractors/library/distractors_manifest.csv        209종
hdri_root                   data/pallet/assets/lighting/hdri/library                   Poly Haven CC0 30
pallet_material_root        data/pallet/assets/materials/pallet/textures_wood
floor_material_root         data/pallet/assets/materials/floor/textures_floor
pallet_model_roots          data/pallet/assets/pallets/models/models_usd,
                            data/pallet/assets/pallets/source/pallets_v2_add/models
pallet_measurements         data/pallet/assets/pallets/source/pallets_v2_add/measurements.json
golden_overlay_reference    data/pallet/reference/golden_overlay/trunc_addon_v1_pilot
real_data_root              data/pallet/reference/real_images/real_data                실촬영 1,924
runs_root                   data/pallet/runs
```

**2026-07-29 Stage 2-B**: Stage 1 이 찾아낸 "이름은 `archive/` 인데 현역"이던 3종
(`archive/textures_wood` · `archive/textures_floor` · `archive/trunc_addon_v1_pilot`)을
정상 위치로 **이동 완료**했다. 더 이상 archive 아래에 현역 자산은 없다.

### 이동 보류 → **Stage 2-C2 에서 전부 해소** [확인]

```
경로                        Stage 2-C1 시점 보류 사유            Stage 2-C2 결과
──────────────────────────────────────────────────────────────────────────────────────────────
distractors/                상대참조 356건 rebase 필요            assets/distractors/library 로 이동 +
                                                                //../../../distractors/library/ 로 rebase
background/                 원본 ZIP 3개(157MB) 포함             ZIP 을 archive/packages/background_sources/
                                                                로 먼저 분리 후 폴더 이동
blender_scene/              //textures 158 + //../distractors    폴더째 이동. textures 는 동반 이동이라
                            356 둘 다 rebase 대상                 //textures/ 문자열 그대로 유효(158)
──────────────────────────────────────────────────────────────────────────────────────────────
data/pallet 루트에 남은 자산군: 없음
```

**2026-07-29 Stage 2-C1**: production `.blend` 의 절대경로를 **원본을 건드리지 않고** 해소했다.
`synth_data_scene.blend`(sha256 `46f436dc…`) 는 그대로 두고, 같은 폴더에
`synth_data_scene_portable.blend` 를 새로 만들어 registry 의 `production_scene` 을 그쪽으로 옮겼다.

```
                          원본(rollback 3)   C1 portable(rollback 2)
────────────────────────────────────────────────────────────────────
절대 외부경로                229                    0
그중 data/pallet 안          228                    0  -> //../distractors/ 로 변환
누락 경로                     1                     0  -> factory_yard_2k.hdr repoint
image datablock             603                   603  (구조 diff 0)
sha256                 46f436dc…              5cad94e5…
```

**2026-07-29 Stage 2-C2**: 세 자산군을 최종 위치로 옮기고, 옮긴 뒤 상대경로를 rebase 한
새 씬을 만들어 승격했다. 앞선 두 blend 는 수정하지 않고 rollback source 로 함께 보존한다.

```
이동 (같은 볼륨 rename, SHA256 전수, 삭제 0, overwrite 0)
  C2A  background/*.zip 3          -> archive/packages/background_sources/   157,408,367 B
  C2B  background/ 74              -> assets/scenes/backgrounds/background/  133,646,354 B
  C2C  distractors/ 1,161          -> assets/distractors/library/          1,958,754,064 B  ┐ 같은
       blender_scene/ 173          -> assets/scenes/production/blender_scene/3,836,556,170 B ┘ group
  합계 1,411 파일 / 6,086,364,955 B / SHA256 mismatch 0

blend 상대경로 rebase (Stage 2-C1 portable 을 byte 복사 후)
                          C1 portable(rollback 2)   C2 stable(active)
  ────────────────────────────────────────────────────────────────────────────
  //textures/                    158                 158   문자열 그대로 유효 (동반 이동)
  distractor 참조                356                 356   -> //../../../distractors/library/
  HDRI 외부 상대참조                1                   1   -> //../../../lighting/hdri/library/
  절대 외부경로                     0                   0
  누락 경로                        0                   0
  image datablock                603                 603   구조 diff 0 · packed 86 불변
  sha256                    5cad94e5…           8cb4109a…
```

`//textures` 는 문자열이 그대로 맞고 나머지 357건만 바뀌었다 — 이 판정은 root 이동 여부가
아니라 **이동 후 디렉토리 기준으로 상대경로를 실제 계산해** 기존 문자열과 비교해서 내렸다.

### TARGET — 최종 구조 (Stage 2-A 에서 뼈대만 생성)

```
data/pallet/
├── assets/
│   ├── scenes/{production,backgrounds,experimental}/
│   ├── pallets/{models,source,metadata}/
│   ├── distractors/{models,manifest,metadata}/
│   ├── materials/{pallet,floor}/
│   ├── lighting/hdri/
│   └── licenses/
├── runs/{smoke,pilot,diagnostics,failed,production}/
├── reference/{golden_overlay,real_images,camera_calibration,expected_outputs}/
├── manifests/
├── release/{datasets,attribution,packaging}/
└── archive/{legacy_datasets,legacy_scenes,legacy_assets,packages,
            superseded_runs,nonredistributable,corrupt,unidentified}/
```

**실제로 채워진 것은 `runs/{smoke,diagnostics,failed}` 와 `manifests/` 뿐**이다.
나머지는 빈 폴더 + README. 빈 폴더를 근거로 코드를 고치면 안 된다.

### ARCHIVED — 현재 파이프라인이 읽지 않는 보존 자료

`data/pallet/archive/` 아래(위 ★ 3건 제외).
라이선스: 2026-07-24 blend 재-bake **이전** 렌더 산출물에는 NoAI 목재가 baked 되어 있어
로컬 보관은 가능하나 **공개 릴리스 불가**(`dataset_license_ledger.md:25,70`).
`archive/_noai_quarantine_usd/` 는 격리 위치 자체가 라이선스 근거이므로 이동 금지.

---

## 3. Stage 2-A 에서 실제로 옮긴 것

```
목적지                                    건수   파일     용량
───────────────────────────────────────────────────────────────
runs/smoke/                                30   4,174   0.825 GB
runs/failed/                                5   1,782   0.248 GB
runs/diagnostics/v2_scene_logic_probes/    99     564   0.070 GB
runs/diagnostics/                          12     401   0.054 GB
───────────────────────────────────────────────────────────────
합계                                      146   6,921   1.197 GB
```

- 폴더 basename 은 바꾸지 않았다(`_v2_...` 접두 유지). 경로 변경과 개명을 동시에 하면
  나중에 무엇 때문에 경로가 달라졌는지 분리할 수 없다.
- 코드/설정/테스트가 직접 참조하는 run 은 옮기지 않았다.
- 과거 history 문서의 옛 경로는 **의도적으로 그대로 뒀다**(22건). 대응은 `manifests/path_map.csv`.

## 4. 이 트리를 바꾸는 방법

```bash
python scripts/data_prep/manage_pallet_data_layout.py --plan     # 사전검사 + 이동 전 snapshot
python scripts/data_prep/manage_pallet_data_layout.py --apply    # 같은 볼륨 rename
python scripts/data_prep/manage_pallet_data_layout.py --verify   # count/bytes/relpath/SHA256
python scripts/data_prep/manage_pallet_data_layout.py --rollback # 역순 역이동
```

정책(코드에 상수로 박혀 있다):

- 이동 허용 목적지: `runs/smoke/`, `runs/diagnostics/`, `runs/failed/`
- 단일·전체 5GB 상한, 금지 확장자(zip/blend/usd/glb/hdr/exr/가중치) 포함 시 차단
- destination 충돌·경로 240자 초과·Windows 예약어·symlink·읽기 불가 파일이 있으면 차단
- **삭제 명령 없음.** copytree 후 원본 삭제 방식도 쓰지 않는다.
- 실패 시 다음 항목으로 넘어가지 않고 트랜잭션을 중단한다.

이동 원장: `reports/data_pallet_cleanup/stage2a/move_transaction.jsonl`
rollback 절차: `reports/data_pallet_cleanup/rollback_plan.md`

## 5. manifests

```
data/pallet/manifests/assets.csv     현역 자산의 로컬 snapshot. registry 값을 조사 시점에 찍어둔 것.
                                     이걸 고쳐도 실행 경로는 바뀌지 않는다(정본은 pallet_paths.yaml).
data/pallet/manifests/runs.csv       run 목록(이동 146 + 원위치 유지 8)
data/pallet/manifests/path_map.csv   original -> current -> desired_final, referenced_by
data/pallet/manifests/archive.csv    archive 이동 계획 (Stage 2-A 실행 0건, executed=no)
```

## 6. 당시 "다음 단계 (Stage 2-B 후보)" — 현재 처리 상태

1. ✅ `.blend` 상대참조 확인 후 `assets/scenes/production/` 이동 — Stage 2-C1/C2
2. ✅ `archive/textures_{wood,floor}` → `assets/materials/{pallet,floor}` — Stage 2-B
3. ✅ `archive/trunc_addon_v1_pilot` → `reference/golden_overlay/` — Stage 2-B (golden 51 passed, skip 0)
4. ✅ `hdri` / `models_usd` / `background` / `distractors` → `assets/` — Stage 2-B/C2
5. ✅ `_DISTRIBUTION_EXCLUDE.txt` 갱신 — Stage 2-B(경로 정정) + Stage 2-D0.1(entry 11 → 16)
6. ◐ archive 대상 이동 — **Stage 2-D1 부분 실행: 30/40 VERIFIED, 10건 rollback**

## 7. archive 내부 정리 상태 (Stage 2-D0 / 2-D0.1)

`data/pallet` 루트에 남은 **자산군은 없다.** 남은 일은 `archive/` **안**의 평면 배치를
semantic 하위폴더로 정리하는 것이다.

```
현재 archive/          depth-1 entry 166개가 평평하게 놓여 있다
Stage 2-A 가 만든        packages/ · legacy_datasets/ · legacy_scenes/ · … 7개 — 현재 **비어 있음**
semantic 하위폴더        (Stage 2-D1 이 채울 곳)
```

Stage 2-D0(비파괴 감사, 이동 0)이 잔여 대용량을 분류하고 Stage 2-D0.1(안정화, 이동 0)이
계획을 실행 가능한 상태로 고정했다. 계획 정본:

```
reports/data_pallet_cleanup/stage2d01/proposed_stage2d1_moves_final.csv
reports/data_pallet_cleanup/stage2d01/stage2d1_readiness.md
```

```
Stage 2-D1 계획 (Stage 2-D0.1 재계산 정본)
──────────────────────────────────────────────────────────────
row 60 = READY 40 (132.37 GiB · 191,528 파일) / BLOCKED 8 / KEEP 12

cohort                READY   bytes        내용
D1A_PACKAGES            14    75.21 GiB    원본 ZIP -> archive/packages/dataset_bundles/
D1B_CORRUPT              1     4.22 GiB    열리지 않는 ZIP -> archive/packages/corrupt/ (삭제 아님)
D1C_LEGACY_DATASETS     15    50.70 GiB    -> archive/legacy_datasets/{redistributable,partial,noai_baked}/
D1D_BLEND_BACKUPS       10     2.24 GiB    cold blend/blend1 -> archive/legacy_scenes/{snapshots,blender_backups}/
D1E_WEIGHTS              0        —        UNREFERENCED_WEIGHT 4개. data/pallet 밖 + 목적지 미정 -> 별도 승인
D1F_QUARANTINE           0        —        isaac_assets(EULA) · NoAI USD -> 이동 금지
```

주의해서 읽을 것:

- **package structural match 를 exact duplicate 라고 부르지 않는다.** ZIP 20개 중 어떤
  쌍도 SHA256/CRC 로 동일 내용이 증명되지 않았다. `duplicates/` 목적지는 쓰지 않고
  전부 보존 이동한다.
- **weights exact duplicate 0** — 29개 전부 고유 SHA256. UNREFERENCED_WEIGHT 4개는
  "참조가 없다"는 사실 기술이고 삭제 후보가 아니다.
- **isaac_assets(4.05GB, NVIDIA EULA) · NoAI quarantine USD 3개는 이동 금지.**
- BLOCKED 8 = 라이선스 미확정 4(v4 파생, ledger B8) + **CURRENT 경로 참조가 살아있는 4**
  (`archive/training_data` 등). 후자는 이동 전에 registry 키 등록 + 참조 전환이 선행돼야
  한다 — 지금 옮기면 방금 고친 참조가 다시 깨진다.

## 8. Stage 2-D1 실행 결과 (2026-07-30) — archive/ 내부 정리

```
[판정] D1_PARTIAL — READY 40건 중 30건 VERIFIED (130.14 GiB), 10건 rollback
       FULL_DATA_PALLET_LAYOUT_COMPLETE 아님 (아래 잔여 참조)
```

```
cohort                결과        건수   bytes        목적지
──────────────────────────────────────────────────────────────────────────────────────
D1B_CORRUPT           VERIFIED      1     4.22 GiB   archive/packages/corrupt/
D1A_PACKAGES          VERIFIED     14    75.21 GiB   archive/packages/dataset_bundles/
D1C_LEGACY_DATASETS   VERIFIED     15    50.70 GiB   archive/legacy_datasets/
                                                       redistributable 11 · noai_baked 3 · partial 1
D1D_BLEND_BACKUPS     ROLLED_BACK  10     2.24 GiB   ★ 앞선 원장 충돌 — 아래
──────────────────────────────────────────────────────────────────────────────────────
이동 완료                           30   130.14 GiB   191,518 파일
```

검증: 전 파일 SHA256 을 이동 전·후 두 번 (read 260.27 GiB) — mismatch 0 · unhashed 0 ·
file count/bytes/relpath 전부 일치 · source 잔존 0. `data/pallet` 파일 수 363,090 불변
(삭제 0 · 생성 0), bytes +624 = `_DISTRIBUTION_EXCLUDE.txt` 단독.

### ★ D1D 가 드러낸 구조적 제약 — 원장 연쇄가 없다

cold blend 10개는 **Stage 2-C2 C2C 이동의 구성원**이었다. C2C destination
(`assets/scenes/production/blender_scene/`) 밖으로 빼내자 C2C 원장의 verify 가
`MISSING` 11건으로 실패했다. 데이터는 안전했지만(D1D 원장이 새 위치·해시 기록,
verify 통과) **검증 사슬**이 끊겼다.

"예상된 제거"를 허용하는 옵션을 만들면 통과하지만 그건 검증 완화다. rollback 했고,
대신 계획 단계 guard 를 코드에 넣었다:

```
manage_pallet_data_layout.py
  PRIOR_LEDGERS · prior_ledger_members() · find_prior_ledger_conflict()
  -> 앞선 원장이 옮긴 파일을 그 destination 밖으로 옮기려 하면 plan 이 exit 2
```

계획 40건 전수 재검사 결과 충돌은 **D1D 10건에만** 있었다 (D1A/D1B/D1C 는 0).

이 10건을 옮기려면 원장 연쇄(chained ledger — verify 가 "이 파일은 원장 X 가
이어받았다"를 SHA256 까지 따라가는 것) 도입이 선행돼야 한다. 범위 밖이라 하지 않았다.

### 잔여 (전체 정리 미완)

```
BLOCKED_REFERENCE     4건   16.13 GiB   registry 키 등록 + 참조 전환 선행 필요
BLOCKED_UNKNOWN       4건   14.53 GiB   v4 파생 NoAI 상속 확정 필요 (ledger B8)
KEEP_ACTIVE/ROLLBACK  6건               registry blend — 이동 대상 아님
UNREFERENCED_WEIGHT   4건               weights/ 밖 · 삭제 후보 아님 · 별도 승인
KEEP_QUARANTINE       2건               isaac_assets(EULA) · NoAI USD
D1D                  10건    2.24 GiB   원장 연쇄 선행 필요
data/pallet top-level 잔여 65건 4.27 GiB log 40 · script 11 · 진단 dir 10 · 출력 3 · 이미지 1
archive/ depth-1 잔여 136건            진단·중간 산출물 (Stage 2-A 계획 미실행분)
```

상세: `reports/data_pallet_cleanup/stage2d1/` (final_report.md · final_tree.md ·
cohort_d1*_report.md · regression_results.md · rollback_plan.md)

## 9. Stage 2-D1.1 실행 결과 (2026-07-30) — 잔여 3범위

```
[판정] D11A COMPLETE (10건 2.24 GiB) / D11B·D11C PARTIAL (준비 완료, 이동 미실행)
       D11_SCOPE_COMPLETE 아님 · FULL_*_COMPLETE 아님
```

### D11A — chained-ledger 로 D1D 를 되살렸다

Stage 2-D1 에서 rollback 했던 cold blend 10개를 **검증 사슬을 유지한 채** 옮겼다.

```
--successor-ledger-chain <json>   신규
  immutable prior ledger(C2C)와 verified successor ledger(D11A)를
  **파일 단위 SHA256 identity** 로 잇는다. 16개 조건 전부 강제.
  broad removal allow / expected-removal 목록은 쓰지 않는다.

C2C 검증   chain 없이 failures 11  ->  exact additions + chain 으로 failures 0
```

★ 실행 중 발견: verify 가 재실행마다 `verified_at` 을 갱신해 successor 원장 SHA256 이
바뀌면 chain 결속이 깨진다. **원장은 첫 검증만 기록하는 immutable 기록**이어야 한다 —
멱등으로 고치고 테스트 2개로 고정했다.

### D11B — registry 전환 완료, 이동 미실행

```
신규 key 4   legacy_training_data_root · legacy_train_palletobj_v3_root ·
             legacy_train_palletobj_v3_post_v1_root · legacy_sandbox_parking_lot_scene
             (registry ok=24 -> 28)
전환 16곳    config YAML 값도 "registry:<key>/<sub>" 참조로 바꿨다 —
             resolve_config_value() + CLI --resolve 신설, 리터럴은 그대로 통과(하위호환)
             이동 시 pallet_paths.yaml 의 키 값 1줄만 바꾸면 된다
검증         옛 경로 직접 참조 0 · canonical broken ref 0 · unit 745
```

### D11C — provenance 판정 완료, 이동 미실행

v4 파생 4종 **전부 PROVEN_NOAI** (라벨 JSON 13,122개 = 프레임 13,120 전수 스캔,
NoAI 사용 9,634 = 73.4%). ledger B8 해소.

### ★ 중단 사유 — hash read 예산

```
cohort                     bytes       예상 read(×2)   판정
D11A                      2.24 GiB      4.47 GiB      실행
D11B                     16.14 GiB     32.29 GiB      ★ 20 GiB 상한 초과
D11C                     14.52 GiB     29.04 GiB      ★ 초과
합계                     32.90 GiB     65.80 GiB      상한의 3.3배
```

cohort = transaction_group 원자성을 지키려고 쪼개지 않았다. 예산 승인 시 두 cohort 를
순차 실행하면 이동이 끝난다.

상세: `reports/data_pallet_cleanup/stage2d11/`

## 10. Stage 2-D1.2 실행 결과 (2026-07-31) — D11 범위 종료

승인 예산(D12B 36 + D12C 34 = 70 GiB)으로 §9 의 잔여 2 cohort 를 실제로 옮겼다.

```
cohort                  row  files     bytes            hash read(pre+post)   failures
──────────────────────────────────────────────────────────────────────────────────────
D12B_REFERENCE_MOVE      4   92,429   17,334,010,020   16.14 + 16.14 GiB        0
D12C_PROVEN_NOAI_MOVE    4   39,620   15,588,789,193   14.52 + 14.52 GiB        0
──────────────────────────────────────────────────────────────────────────────────────
                         8  132,049   32,922,799,213   61.32 / 70 GiB           0
```

hash-mode all · workers 1 · same-volume rename · 삭제 0 · overwrite 0 · unhashed 0 ·
`data/pallet` 파일수 **363,090 불변**.

### 이동 결과

```
D1-003  assets/scenes/production/blender_scene/_sandbox_parking_lot_check.blend
                                            -> archive/legacy_scenes/snapshots/
D1-033  archive/train_palletobj_v3          -> archive/legacy_datasets/redistributable/
D1-038  archive/training_data               -> archive/legacy_datasets/noai_baked/
D1-053  archive/train_palletobj_v3_post_v1  -> archive/legacy_datasets/redistributable/
D1-041  archive/training_data_v4_split_GREYBUG -> archive/legacy_datasets/noai_baked/
D1-042  archive/training_data_v4_split_bg1bak  -> archive/legacy_datasets/noai_baked/
D1-043  archive/training_data_v4_emptywood     -> archive/legacy_datasets/noai_baked/
D1-049  archive/training_data_v4_pilotA        -> archive/legacy_datasets/noai_baked/
```

NoAI baked **8종이 `archive/legacy_datasets/noai_baked/` 한곳에** 모였다
(training_data · training_data_v4 · training_data_v4_split · train_4pallet_mask_v1 +
v4 파생 4종). 전부 `_DISTRIBUTION_EXCLUDE.txt` 등재, `release_allowed = NO`.

### archive/ 최종 구조

```
archive/packages/
├── background_sources/        3     150.12 MiB   2-C2 C2A
├── dataset_bundles/          14  77,020.15 MiB   2-D1 D1A
└── corrupt/                   1   4,319.60 MiB   2-D1 D1B (BadZipFile 보존)
archive/legacy_datasets/
├── redistributable/      193,564  44,668.03 MiB   2-D1 D1C + ★2-D1.2 D12B (+2)
├── noai_baked/           129,746  38,456.79 MiB   2-D1 D1C + ★2-D1.2 D12B/D12C (+5)
└── partial/                 241      62.07 MiB   2-D1 D1C
archive/legacy_scenes/
├── snapshots/                 7   1,567.30 MiB   2-D1.1 D11A + ★2-D1.2 D12B (+1)
└── blender_backups/           4     853.86 MiB   2-D1.1 D11A
```

`.blend` 는 `snapshots/`, `.blend1`(autosave)은 `blender_backups/` — 확장자 규칙.

### registry 전환의 효과

D11B 4건은 D1.1 이 깔아 둔 registry 덕분에 **실행 표면을 한 줄도 고치지 않고**
`config/synthetic/pallet_paths.yaml` 의 값 4줄만 바꿔 이동했다 (`--audit` ok=28 missing=0).

★ live reference 는 D1.1 CSV 값을 복사하지 않고 **다시 쟀다**. 복사했으면 registry 전환
이전 값이라 4건 전부 LIVE_REF 오탐이다. 재측정 결과 3건 0, 1건(`generate_all.sh:42`
낡은 주석)은 진짜라서 갱신했다.

### ★ chain 은 자기 mapping 만 책임진다

C2C 원장에서 D1.1 이 10개, D1.2 가 1개를 빼냈다 → 재검증 시 11 MISSING.

```
D11A chain 만 -> failures 2 · D12 chain 만 -> failures 11 · 둘 다 -> failures 0
   (successor chain: 11 file(s) from 2 chain(s) / 인정된 이관 11)
```

`--successor-ledger-chain` 을 반복 지정 가능하게 고쳤고, 여러 chain 이 같은 prior key 를
중복 주장하면 exit 2 로 거부한다. D1.1 chain 파일은 수정하지 않았다.

### 세 판정

```
D11_SCOPE_COMPLETE                        ✅  residual_scope 18행 전부 해소
FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE   ❌  권장 구조 밖 200개(5.47 GiB) 잔존
FULL_PHYSICAL_MINIMAL_TREE                ❌  빈 폴더 7 유지 + 위 200개
```

성격 미상은 0 이다 — UNKNOWN 0 · 미분류 0 · broken ref 0 · leak 0 · BLOCKED 0.
남은 200개는 "뭔지 모르는 것"이 아니라 "아직 제자리로 안 옮긴 것"이며 전부 Stage 2-A
`archive.csv` 에 계획이 있다(`executed = no`).

```
위치                    n     크기       내용
────────────────────────────────────────────────────────────────────
data/pallet/ depth 1   65   4.27 GiB   _v2_* 진단 run · 로그 40 · 일회성 스크립트 11
archive/ depth 2      135   1.20 GiB   test_blender_v* 과거 렌더 · _efront_12kp_check 등
────────────────────────────────────────────────────────────────────
                      200   5.47 GiB
```

상세: `reports/data_pallet_cleanup/stage2d12/` (final_report.md 가 45항목 순서 + 마감 수치)
