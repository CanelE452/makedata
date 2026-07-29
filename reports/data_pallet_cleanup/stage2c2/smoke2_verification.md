# §21 최종 2-frame smoke

```
scene       data/pallet/assets/scenes/production/blender_scene/synth_data_scene_portable_stage2c2.blend
            (registry production_scene 조회로 지정 — 리터럴 아님)
out         data/pallet/runs/smoke/_stage2c2_final_layout_smoke2_seed7220/
seed        7220
options     --completion-mode usable --n 2 --start 0 --count 2
            --mask-profile public --render-profile dataset-quality --noise-tier clean
GPU         OPTIX        elapsed 61.07s (wall 1m03s)
delivered   2 / 2        complete=True   render 시도 2 / reject 0 / proposals 3
전체 렌더    2 frames     (상한 3, 500/40k 미실행)
```

`--noise-tier clean` = `camera_effects.NOISE_TIER_LABELS` 의 첫 항목(현재 구현된 가장 약한 tier).
씬은 Blender CLI 인자로 준다 — 러너에 `--scene` 류 옵션은 없고, 만들지 않았다.

## 필수 검증 93항목, 실패 0 [확인, 실행함]

원자료: `smoke2_verification.json`. 마스크 전경 판정은 파이프라인 정본
`audit_v2_scene_logic.strict_decode_mask`(픽셀 > 127)를 import 해서 썼다.

```
산출물      rgb 2 · labels 2 · mask_amodal 2 · mask_visible 2 · archive-style overlay 2
            mask/ 디렉토리 미생성 (public)
세션        usable_delivered 2 · complete True · mask_profile public ·
            render_profile dataset-quality · noise_tier clean ·
            mask_dirs [mask_amodal, mask_visible] · occlusion_decomposition_available False ·
            magenta_max_fraction 0.0 · gpu OPTIX
프레임별     magenta 0 (record + 픽셀 실측) · visible ⊆ amodal 위반 0px ·
            mask_m0 non-empty · mask_invariants_pass · mask_pixel_inclusion_ok ·
            corrupt_mask/corrupt_rgb False · mask_paths 키 [m0,m4] ·
            mask_area_after_{static,cargo,context} = None (public) ·
            overlay canvas == RGB · camera distance <= limit ·
            pallet_support_pass · support_pass · cargo_collision_pass ·
            static_collision_pass · ground_continuity_pass ·
            all_pass + G1~G5 전부 True · gate_valid True
메타데이터   background / floor_mode + floor_texture / material_variant /
            scene_preset + exposure_ev / pallet_type / source_asset 전부 non-null
라벨        keypoint_convention = camera_dynamic_0123_v4 유지 ·
            projected_cuboid 8 + centroid ·
            옛 경로 문자열 0건 (data/pallet/hdri · Documents/GitHub · AppData ·
            **data/pallet/distractors · data/pallet/blender_scene · data/pallet/background**)
```

### 프레임별 표

```
항목                f0000                              f0001
──────────────────────────────────────────────────────────────────────────────────
pallet              Pallet_3                           Pallet_2
source_asset        eur_pallet_bk_cc0.glb              woodpallet_block_jtoastie_ccby.glb
background          parking_lot                        parking_lot
scene_preset        random-mix                         outdoor-night
exposure_ev         -1.2491                            -1.3046
floor               plane / gravel_concrete_02         plane / tile_brown
material            weathered_brown                    worn_natural
cargo               off (0)                            on (2 placed)
occluder            (context-rich, explicit 없음)       controlled-occlusion /
                                                       Dist_utility_box_01
RGB / overlay 캔버스 640x480 / 640x480                  640x480 / 640x480
camera distance     4.58 m                             2.10 m
mask m0 / m4 (px)   6,040 / 6,040                      13,696 / 13,312
visible ⊆ amodal    위반 0 px                          위반 0 px
magenta             0 px (record 0.0)                  0 px (record 0.0)
texture status      누락 0                             누락 0
overlay status      정상 (kp 0~7 + centroid 8 + 축)     정상 (kp 0~7 + centroid 8 + 축)
Kpt Vis / Ray Vis   100% (8/8) / 100% (8/8)            88% (7/8) / 75% (6/8)
all_pass G1~G5      True                               True
판정                PASS                               PASS
```

### 이미지 직접 확인 [확인, RGB 2장 + overlay 2장 전부 열어봄]

- **f0000** — parking_lot 배경(차단바, 경비 부스, 주차 표지판). 자갈/콘크리트 바닥 위에
  EUR 목재 팔레트가 접지. **외부 distractor 가 실제로 렌더됨**: 노란 "CAUTION WET FLOOR"
  표지판(좌), 캔/쓰레기(우하). overlay 패널 `Object: Pallet_3 / BG: parking_lot /
  Distance 4.58m / Kpt Vis 100% (8/8) / Area 2.4% / Size 1268x152x846mm`,
  키포인트 9개가 팔레트 위에 정확히 얹힘.
- **f0001** — 야간 하늘 + 아파트 배경. 타일 바닥 위 목재 팔레트에 카고 박스 2개가 적재되고,
  `Dist_utility_box_01`(우측 배전함)과 좌측 금속 선반·탄약통이 함께 렌더. `Trunc: Y Occ: Y
  Cargo 2`, `Kpt Vis 88% (7/8) / Ray Vis 75% (6/8)` 로 가림이 라벨과 일치.

**외부 distractor 가 렌더된 프레임 = 2 / 2.** 따라서 "209개 decode 는 됐지만 실제로 그려지진
않았다" 는 미확인 구간이 남지 않았다 — 새 `//../../../distractors/library/` 상대경로가
**렌더 시점에도** 해석된다는 직접 증거다.

> 이 smoke 는 경로 이동·rebase 검증용이다. 수율·분포 판단에 쓰지 않는다.
