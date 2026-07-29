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
production_scene            data/pallet/blender_scene/synth_data_scene.blend           ✋ 이동 보류
production_scene_textures   data/pallet/blender_scene/textures                         ✋ blend //textures
experimental_scene          data/pallet/blender_scene/_sandbox_palletobj_production.blend  ✋
background_root             data/pallet/background                                     ✋ 이동 보류(ZIP)
distractor_root             data/pallet/distractors                                    ✋ 이동 보류(blend 절대참조)
distractor_manifest         data/pallet/distractors/distractors_manifest.csv           ✋ 209종
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

✋ = 아직 원위치. 이유는 아래 "이동 보류" 절 참조.

### 이동 보류 (Stage 2-C 대상)

```
경로                        보류 사유
──────────────────────────────────────────────────────────────────────────────────────
distractors/                production .blend 안의 이미지 356개가 이 폴더를 **절대경로**로
                            참조한다(`E:\...\data\pallet\distractors\...`). 옮기면 씬 텍스처가
                            끊기고, .blend rewrite 는 이번 단계에서 금지되어 있다.
background/                 원본 다운로드 ZIP 3개(157MB)를 품고 있어 "ZIP 이동 금지" 규칙에 걸린다.
                            ZIP 을 archive/packages/ 로 먼저 분리해야 폴더째 옮길 수 있다.
blender_scene/              .blend 감사에서 BLOCKED_ABSOLUTE=356 · MISSING_CURRENT=1
                            (factory_yard_2k.hdr 가 다른 워크스페이스 경로를 가리킨다).
                            §3 이동 조건(둘 다 0)을 채우지 못했다.
```

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

## 6. 다음 단계 (Stage 2-B 후보)

1. `.blend` 내부 이미지 경로 덤프로 상대참조 확인 후 `assets/scenes/production/` 이동
2. `archive/textures_{wood,floor}` → `assets/materials/{pallet,floor}` (registry 값만 바꾸면 코드 수정 불필요)
3. `archive/trunc_addon_v1_pilot` → `reference/golden_overlay/` + 테스트 수정 + `pytest -rs` 로 skip 0 확인
4. `hdri` / `models_usd` / `background` / `distractors` → `assets/` (registry + blender.yaml 동기화)
5. `_DISTRIBUTION_EXCLUDE.txt` 갱신(현재 5/5 경로가 stale — 릴리스 게이트가 작동하지 않는 상태)
6. archive 대상 이동(legacy_datasets 87.7GB, packages 80.8GB) — `manifests/archive.csv` 계획
