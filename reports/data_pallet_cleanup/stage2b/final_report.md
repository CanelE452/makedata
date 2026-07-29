# Stage 2-B 최종 보고 — 현역 자산·golden reference 이동

## 1. 목적과 판정

Stage 2-A/2-A.1 의 registry·transaction 기반으로 **현역 자산과 golden reference 를
`assets/`·`reference/` 로 이동**. 10개 source 중 **7개 이동 완료, 3개 BLOCKED**.

**판정: 부분 완료.** BLOCKED 3건은 전부 `.blend` 의존성·ZIP 규칙 때문이며,
`.blend` 를 고쳐서 억지로 통과시키지 않았다(§3 지시 준수). 중단 기준 해당 없음.

## 2. branch / HEAD

```
분기 기준     0264ae48c28e4cc6068f3e8d140ed2a3b58444c8  (= main = origin/main)
작업 branch   chore/data-pallet-stage2b-active-assets
작업 전 상태   clean, 실행 중 blender.exe 0개
```

## 3. 이동 전 기준선

`baseline.md` / `baseline_checksums.json` — registry ok=21 missing=0 · unit 566 · integration 20 ·
Stage 2-A verify 146/6,921/failures 0 · 5k accepted 4,313 rejected 687 · distractors 209 ·
FrameSpec `938f387d…` · NaN/inf 0.

## 4. production `.blend` dependency 감사

`blend_dependency_audit.md` / `.json` / `blend_external_paths.csv` (603행)

```
BLOCKED_ABSOLUTE   356   전부 data/pallet/distractors/... 절대경로 (파일은 실재)
SAFE_RELATIVE      246   //textures/ 158 + packed 86 + generated 2
MISSING_CURRENT      1   factory_yard_2k.hdr -> C:\Users\User\Documents\GitHub\... (기존 파손)
libraries            0
```

**부수 발견**: 이 절대경로들 때문에 `synth_data_scene.blend` 는 이미 이 머신에 못박혀 있다.
다른 워크스테이션에서 열면 distractor 텍스처 356개가 깨진다 — Stage 2-C 과제.

감사 중 내 `is_within()` 이 `commonpath`(백슬래시) 결과를 forward-slash 와 비교해 항상 False 였던
버그를 잡았다. 처음엔 514건으로 보였고, 고친 뒤 356건이 진짜였다.

## 5. model / background dependency 감사

`model_dependency_audit.csv` (648행) / `broken_dependencies.csv`

```
broken dependency            0
EXTERNAL scope(자기 source 밖) 0     -> 폴더 통째 이동해도 내부 상대참조 유지
UNKNOWN binary               3 -> 전부 해소 (pxr USD API 로 확인)
```

`scene_noemit.usd` 가 `scene.usd` 를 절대경로로 참조하는 듯 보였으나,
`Sdf.Layer.GetExternalReferences()` / `GetCompositionAssetDependencies()` / `subLayerPaths`
가 **전부 빈 리스트**였다. 그 문자열은 `documentation` 필드의 주석
("Generated from Composed Stage of root layer …")이고, 레이어는 flatten 된 자기 완결본이다.
`scene_1.usd` 는 `./textures/*.png` 상대참조 → 동반 이동으로 유지된다.

## 6. 이동 허용 · 차단 source

```
K  source                        files    GB     의존성 판정              결정
────────────────────────────────────────────────────────────────────────────────────
A  archive/textures_wood            27   0.315   OK                      이동
B  archive/textures_floor           59   0.675   OK                      이동
H  archive/trunc_addon_v1_pilot   1210   0.283   OK                      이동
I  real_data                      1924   0.154   OK                      이동
C  hdri                             33   0.199   OK                      이동
D  models_usd                       21   0.080   OK (USD 자기완결)         이동
E  pallets_v2_add                   14   0.005   OK (GLB 자기완결)         이동
F  background                       77   0.291   OK                      **BLOCKED** — 원본 ZIP 3개(157MB)
                                                                          포함, "ZIP 이동 금지" 규칙
G  distractors                    1161   1.959   BLOCKED_BLEND_ABSOLUTE  **BLOCKED** — .blend 절대참조 356
J  blender_scene                   171   3.119   -                       **BLOCKED** — blend 감사 미통과
────────────────────────────────────────────────────────────────────────────────────
이동 7 source / 3,288 files / 1.711 GB      차단 3 source / 1,409 files / 5.369 GB
```

## 7. cohort별 transaction plan

```
cohort                    moves  files   bytes         hash-mode  unhashed  license  collision
──────────────────────────────────────────────────────────────────────────────────────────────
B1_REFERENCE_MATERIALS      4    3,220   1,427,373,269  all        0         2        0
B2_LIGHTING_MODELS          3       68     283,552,000  all        0         4        0
B3_SCENE_ASSETS             0        0               0  all        0         0        -   (전부 BLOCKED)
B4_PRODUCTION_SCENE         -        -               -  -          -         -        -   (계획 안 함)
```

manifest: `transactions/b1_reference_materials.jsonl`, `b2_lighting_models.jsonl`,
`b3_scene_assets.jsonl`(빈 계획 + `_skipped.csv`)

## 8~10. 실제 이동 · count/bytes · SHA256

```
move_id  source                        -> destination                                   files  MB
──────────────────────────────────────────────────────────────────────────────────────────────────
S2B001   archive/textures_wood         -> assets/materials/pallet/textures_wood            27   314.9
S2B002   archive/textures_floor        -> assets/materials/floor/textures_floor            59   674.9
S2B003   archive/trunc_addon_v1_pilot  -> reference/golden_overlay/trunc_addon_v1_pilot  1210   283.0
S2B004   real_data                     -> reference/real_images/real_data                1924   154.5
S2B001   hdri                          -> assets/lighting/hdri/library                     33   199.0
S2B002   models_usd                    -> assets/pallets/models/models_usd                 21    79.6
S2B003   pallets_v2_add                -> assets/pallets/source/pallets_v2_add             14     4.9
──────────────────────────────────────────────────────────────────────────────────────────────────
합계                                                                                     3,288  1,711 MB
```

verify 결과 (`--policy stage2b-active-assets --hash-mode all`):

```
cohort  moves  files   bytes          sha256 checked  license verified  failures
─────────────────────────────────────────────────────────────────────────────────
B1        4    3,220   1,427,373,269   3,220           2                 0
B2        3       68     283,552,000      68           4                 0
─────────────────────────────────────────────────────────────────────────────────
합계      7    3,288   1,710,925,269   3,288           6                 0
```

**SHA256 mismatch 0 · destination overwrite 0 · 삭제 0.**
source 7곳 전부 부재 확인, destination 7곳 전부 존재 확인.
이동 전 인벤토리 대비 파일 수·바이트 **전부 일치**(A 27/27 · B 59/59 · H 1210/1210 ·
I 1924/1924 · C 33/33 · D+E 35/35).

## 11. registry 변경 전후

```
key                        before                                   after
──────────────────────────────────────────────────────────────────────────────────────────────
hdri_root                  data/pallet/hdri                         assets/lighting/hdri/library
pallet_material_root       data/pallet/archive/textures_wood        assets/materials/pallet/textures_wood
floor_material_root        data/pallet/archive/textures_floor       assets/materials/floor/textures_floor
pallet_model_roots[0]      data/pallet/models_usd                   assets/pallets/models/models_usd
pallet_model_roots[1]      data/pallet/pallets_v2_add/models         assets/pallets/source/pallets_v2_add/models
pallet_measurements        data/pallet/pallets_v2_add/…json          assets/pallets/source/pallets_v2_add/…json
golden_overlay_reference   data/pallet/archive/trunc_addon_v1_pilot reference/golden_overlay/trunc_addon_v1_pilot
real_data_root             data/pallet/real_data                    reference/real_images/real_data
──────────────────────────────────────────────────────────────────────────────────────────────
production_scene / _textures / experimental_scene / background_root /
distractor_root / distractor_manifest                              **변경 없음** (BLOCKED)
```

audit: `ok=21 missing=0 absent_optional=0`. 존재하지 않는 경로를 registry 에 넣지 않았다.

## 12. 코드 · config 경로 변경

```
CURRENT_RUNTIME (config)   blender.yaml(2) · blender_train_4000.yaml(2) · isaac_sim.yaml(1)
CURRENT_RUNTIME (py)       randomizers · v2_realize · efront_kp12 · overlay_archive_trunc_style ·
                           overlay_v2_detailed (주석/docstring)
                           _make_archive_vs_new_sheet · _verify_archive_style_pixels (실경로 상수)
                           visualize_inference(2) · visualize_pretrain (real_data 기본값)
CURRENT_TEST               test_overlay_archive_trunc_style (golden 경로를 **registry 조회**로 교체)
                           test_pallet_data_paths_unit (registry 내용 규칙 2건)
                           integration_tests (Stage 2-A 불변식 → Stage 2-B 불변식으로 교체 + 신규 3)
실행가능 legacy input       floor_and_mask · run_mass_10k · run_trunc_addon · gen_palletobj_v1 ·
                           run_addon_v1.sh (HDRI/텍스처 입력 경로)
수정하지 않음               _docs/history/* · reports/ snapshot · path_map original_path ·
                           rollback manifest source
```

이동 후 옛 경로 잔존 스캔: CURRENT_RUNTIME/TEST/DOC 중 **실제 참조 0건**
(남은 것은 전부 ① 이동 사실을 적은 주석 ② "옛 경로가 없어야 한다"를 단언하는 테스트
③ 임시 fixture 안의 임의 경로).

## 13. golden reference 이동 결과

`archive/trunc_addon_v1_pilot` → `reference/golden_overlay/trunc_addon_v1_pilot` (1,210 파일).
테스트는 이제 **registry key 로 경로를 얻는다**(리터럴 제거).
`test_overlay_archive_trunc_style.py` **51 passed, skip 0** — 픽셀 golden·archive source 상수
비교·canvas·legend diff 전부 유지.
integration 에 `test_golden_overlay_pixel_test_is_not_skipped_here` 를 추가해
"로컬에서 skip 되면 FAIL" 을 못박았다.

## 14. distribution exclusion 복구

`distribution_exclusion_audit.md` — stale 5건 정정 + 존재하지 않는 1건 주석 강등 +
NoAI baked legacy 4건 신규 추가. 신규 검증기 `verify_distribution_exclusions.py`
**entries 10 / problems 0 / release leaks 0 / exit 0**.

## 15. 로컬 manifest 갱신

```
assets.csv     14행 — MOVED_STAGE2B 8 / BLOCKED_STAGE2B 6, exists=no 0
               original_path 보존, full_hash_verified / transaction_manifest / cohort 추가
path_map.csv   169행 (신규 1) — original -> current -> desired_final, BLOCKED 사유 기록
runs.csv       155행 — Stage 2-B smoke run 1건 추가
archive.csv    232행 — 이동된 3종은 "archive 대상 아님" 으로 주석
```

## 16~17. 테스트

```
A default unit          568 passed, skip 0, fail 0   (566 -> +2 = PyYAML 회귀 방지 테스트)
B local integration      23 passed, skip 0, fail 0   (20 -> +3 = Stage 2-B 불변식)
C golden overlay         51 passed, skip 0
D Stage 2-A 원장          146 moves / 6,921 files / failures 0 / sha256 fe1adc26… **불변**
E Stage 2-B manifest      B1 4/3,220 · B2 3/68 · all-hash · unhashed 0 · failures 0
```

## 18. Stage 2-A 원장 verify

변경 없음. `fe1adc266bd91963c7be98779ed4c114b90b0b811fabdd60471a807aeb56d101`
(PRE-FLIGHT 값과 동일) — 재생성·정규화하지 않았다.

## 19. 5k dry-run 비교

```
                  before              after               일치
──────────────────────────────────────────────────────────────
FrameSpec sha256  938f387dd65258e0…   938f387dd65258e0…   ✓
accepted          4,313               4,313               ✓
rejected          687                 687                 ✓
distractors       209                 209                 ✓
NaN / inf         0                   0                   ✓
missing/Traceback -                   0                   ✓
```

## 20. Blender no-render asset audit

`postmove_blender_asset_audit.json` / 위 §4 말미 표 참조.
**신규 파손 0** — missing_images 1건은 이동 전과 동일한 factory_yard_2k.hdr.

### 작업 중 발견한 Stage 2-A 잠복 회귀 [확인]

Blender 내장 Python(3.13.9)에는 **PyYAML 이 없어서** `pallet_data_paths._load_raw` 가
`json.loads` 로 떨어지는데, Stage 2-A 에서 내가 registry 파일 머리에 넣은 `#` 주석을
json 이 파싱하지 못해 **Blender 안에서 `blender_config` import 가 실패**하고 있었다.
Stage 2-A 이후 Blender 를 한 번도 돌리지 않아 드러나지 않았다.
`_strip_hash_comments()` 로 json fallback 을 방어하고, 회귀 테스트 2개를 추가했다.
이 감사를 하지 않았으면 다음 렌더에서 터졌을 문제다.

## 21. 2-frame smoke

`data/pallet/runs/smoke/_stage2b_asset_smoke2_seed7200/` — seed 7200, usable 2/2,
`--mask-profile public --render-profile dataset-quality --noise-tier clean`, 133.9s, GPU OPTIX.

**필수 항목 66개 전수 검증, 실패 0** (`smoke2_verification.json`):
RGB 2 · labels 2 · mask_amodal 2 · mask_visible 2 · archive-style overlay 2 ·
`mask/` 미생성 · magenta 0(record + 픽셀 실측) · camera distance 4.59m·5.79m ≤ 10m ·
visible ⊆ amodal 위반 0px · mask_m0 non-empty · overlay canvas == RGB(960×540, 720×480) ·
`mask_paths=[m0,m4]` · `mask_area_after_*` = None(public) · G1~G5 all_pass ·
background/floor/scene_preset/pallet_type non-null · label 에 옛 경로 0건.

두 overlay 와 RGB 를 **직접 열어 확인**: f0000 = Pallet_1/industrial(밴+의자 텍스처 정상),
f0001 = Pallet_3/parking_lot(controlled-occlusion, 판자에 일부 가림). 마젠타·누락 텍스처 없음.

> 이 smoke 는 경로 이동 검증용이다. 수율·분포 판단에 쓰지 않는다.

## 22. 남은 Stage 2-C 항목

1. **`synth_data_scene.blend` 의 절대경로 356건 해소** — `make_paths_relative` + 재저장.
   이게 되어야 distractors 와 blender_scene 을 옮길 수 있고, .blend 가 머신 독립이 된다.
2. `background/` 의 원본 ZIP 3개(157MB)를 `archive/packages/` 로 먼저 분리 → 그 후 폴더 이동.
3. `blender_scene` 안의 factory_yard_2k.hdr 깨진 datablock 정리.
4. archive 대량 이동(legacy_datasets 87.7GB + packages 80.8GB).
5. `inventory.csv` → `grouped_inventory.csv` 개명.
6. distractors GSO MTL 2건의 `map_object_normal` 참조 결측(기존 상태, 이동과 무관).

## 23. git diff

```
28 files changed, 394 insertions(+), 129 deletions(-)
신규(untracked): reports/data_pallet_cleanup/stage2b/
                scripts/data_prep/verify_distribution_exclusions.py
```

## 24. rollback 가능 여부

**가능.** cohort 별 manifest 에 3,288 파일의 SHA256 과 source/destination 이 전부 남아 있다.

```
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
    --manifest reports/data_pallet_cleanup/stage2b/transactions/b2_lighting_models.jsonl
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
    --manifest reports/data_pallet_cleanup/stage2b/transactions/b1_reference_materials.jsonl
```

(B2 → B1 역순. tracked 파일은 커밋되지 않았으므로 `git checkout` 으로 복구.)
Stage 2-A 원장은 건드리지 않았으므로 Stage 2-A 이동도 여전히 독립적으로 되돌릴 수 있다.

---

```
active source 이동 건수      7
active file 이동 수          3,288
active bytes                1,710,925,269  (1.711 GB)
SHA256 검사 수               3,288
SHA256 mismatch             0
데이터 삭제 수                0
ZIP 이동 수                  0
legacy dataset 이동 수       0
isaac_assets 이동 수         0
NoAI quarantine 이동 수      0
500 렌더 수                  0
40k 렌더 수                  0
commit                      0
push                        0
```
