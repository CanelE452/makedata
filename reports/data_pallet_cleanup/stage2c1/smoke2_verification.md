# §10 candidate 대상 2-frame smoke

```
scene         data/pallet/blender_scene/synth_data_scene_portable_candidate_20260729.blend
              (승격 후 = synth_data_scene_portable.blend, 동일 파일)
out           data/pallet/runs/smoke/_stage2c1_portable_blend_smoke2_seed7210/
seed          7210
options       --completion-mode usable --n 2 --start 0 --count 2
              --mask-profile public --render-profile dataset-quality --noise-tier clean
GPU           OPTIX          elapsed 181.45s (wall 3m03s)
delivered     2 / 2          complete=True
render 시도    5 (usable 2 + reject 3)   proposals 7   solve reject 1
```

`--noise-tier clean` 은 `camera_effects.NOISE_TIER_LABELS = ("clean","low","medium","high")` 의
**첫 항목 = 현재 구현된 가장 약한 tier** 다. 새 CLI 옵션을 만들지 않았다.
씬은 Blender CLI 인자로 지정한다(`blender -b <scene> --python run_v2_scene_logic.py -- …`) —
러너에 `--scene` 류 옵션은 존재하지 않으므로 만들지 않았다.

## 필수 검증 87항목, 실패 0 [확인, 실행함]

원자료: `smoke2_verification.json`

마스크 전경 판정은 추측하지 않고 파이프라인 정본
`audit_v2_scene_logic.strict_decode_mask`(전경 = 픽셀 > 127)를 그대로 import 해서 썼다.
(처음에 `> 0` 으로 세어 면적이 402,393px 로 나왔는데, 실제 마스크는 배경이 1~2, 전경이
254~255 인 이미지라 잘못된 값이었다. 정본 규칙으로 바꾼 뒤 3,308px / 17,628px 이 나왔고
이것이 record 의 `mask_area_target_only` 와 일치한다.)

```
산출물          rgb 2 · labels 2 · mask_amodal 2 · mask_visible 2 · archive-style overlay 2
                mask/ 디렉토리 미생성 (public 프로파일)
세션            usable_delivered 2 · complete True · mask_profile public ·
                render_profile dataset-quality · noise_tier clean ·
                mask_dirs [mask_amodal, mask_visible] · occlusion_decomposition_available False ·
                magenta_max_fraction 0.0
프레임별         magenta 0 (record + 픽셀 실측) · visible ⊆ amodal 위반 0px ·
                mask_m0 non-empty · mask_invariants_pass · mask_pixel_inclusion_ok ·
                corrupt_mask False · corrupt_rgb False · mask_paths 키 [m0,m4] ·
                mask_area_after_{static,cargo,context} = None (public) ·
                overlay canvas == RGB · camera distance <= limit ·
                pallet_support_pass · support_pass · cargo_collision_pass ·
                static_collision_pass · ground_continuity_pass ·
                all_pass + G1~G5 전부 True · gate_valid True
메타데이터       background / floor_mode + floor_texture / material_variant /
                scene_preset + exposure_ev / pallet_type / source_asset 전부 non-null
라벨            keypoint_convention = camera_dynamic_0123_v4 유지 ·
                projected_cuboid 8 + centroid · 옛 경로(data/pallet/hdri, Documents/GitHub,
                AppData) 문자열 0건 · mask_paths 가 이 run 안을 가리킴
```

### 프레임별 표

```
항목                f0000                              f0001
──────────────────────────────────────────────────────────────────────────────────
pallet              Pallet_2                           Pallet_1
source_asset        woodpallet_block_jtoastie_ccby.glb scene_1.usd
background          parking_lot                        parking_lot
scene_preset        random-mix                         outdoor-night
exposure_ev         -2.5025                            -1.4827
floor               plane / dirt_ground                plane / gravel_concrete_02
material            brown_dry                          ind_blue
cargo               off (0 placed)                     off (0 placed)
occluder            (context-rich, explicit 없음)       controlled-occlusion /
                                                       Dist_utility_box_01
RGB / overlay 캔버스 960x540 / 960x540                  960x540 / 960x540
camera distance     4.38 m                             2.32 m
mask m0 / m4 (px)   3,308 / 3,308                      17,628 / 13,255
visible ⊆ amodal    위반 0 px                          위반 0 px
magenta             0 px (record 0.0)                  0 px (record 0.0)
texture status      누락 0 (no-render 감사 node 0)      누락 0
overlay status      정상 (kp 0~7 + centroid 8 + 축)     정상 (kp 0~7 + centroid 8 + 축)
all_pass G1~G5      True                               True
판정                PASS                               PASS
```

### 이미지 직접 확인 [확인, 4장 전부 열어봄]

- **f0000** — 야외 저조도(exposure -2.5EV). 흙바닥 위 중거리에 목재 팔레트, 전경에 드럼통과
  타이어 디스트랙터. 전부 접지. overlay 패널이 `Object: Pallet_2 / BG: parking_lot /
  Distance 4.38m / Kpt Vis 100% (8/8) / Ray Vis 100% (8/8) / Area 0.8% /
  Size 1178x183x1001mm` 를 표시하고 키포인트 9개가 팔레트 위에 정확히 얹혀 있다.
  마젠타·회색 미텍스처 영역 없음.
- **f0001** — 콘크리트 벽 앞. 청색 플라스틱 팔레트가 화면 하단에서 트런케이션되고 회색 배전함
  (`Dist_utility_box_01`)이 앞을 가린다. overlay: `Kpt Vis 88% (7/8) / Ray Vis 62% (5/8) /
  Trunc: Y Occ: Y / Size 1192x136x990mm`. 가림·트런케이션이 라벨과 일치.
  배전함 데칼·콘크리트·자갈 텍스처 모두 정상 렌더.

## 검증에서 조정한 것 (내 검사 쪽 오류였던 것)

```
증상                                  원인                                   조치
──────────────────────────────────────────────────────────────────────────────────────────
mask 면적 402,393px (비현실적)          전경을 >0 으로 셈. 실제 배경값은 1~2      정본 strict_decode_mask
                                                                            (>127) 로 교체
G1~G5 를 못 읽음                       필드명이 G1..G5 가 아니라 G1_pass..      실제 스키마로 교체
hdri / material 이 None                records 가 아니라 label 의 v2_labels·   실제 위치로 교체
                                      camera_data 에 있음
mask_paths 비교 실패                   dict 인데 list 로 가정                   키 집합 비교로 교체
```

## HDRI 메타데이터에 대한 정직한 기록 [확인]

지시서는 "HDRI metadata non-null" 을 요구했다. **v2 라벨 스키마에는 HDRI 파일명 필드가
존재하지 않는다** — label / records / driver_summary 어디에도 `hdri` 문자열이 없다(전수 검색).
조명 메타데이터는 `camera_data.scene_preset` 과 `camera_data.exposure_ev` 이며 두 프레임 모두
non-null 임을 확인했다. **없는 필드를 만들어 넣지 않았다.**

> 이 smoke 는 경로 변환 검증용이다. 수율·분포 판단에 쓰지 않는다.
