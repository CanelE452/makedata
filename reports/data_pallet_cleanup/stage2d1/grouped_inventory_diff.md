# Stage 2-D1 grouped_inventory.csv diff

```
before rows  416
after  rows  266
removed      206
added        56
```

## 그룹 단위 유지 확인

```
depth 분포   {1: 74, 2: 151, 3: 8, 4: 33}
entry_type   {'file': 73, 'dir': 193}
row 수 266 vs data/pallet 파일 363090 -> 그룹 인벤토리(전수 manifest 아님)
```

depth 3~4 를 추가했다 — D1 이 만든 semantic 컨테이너(packages/ · legacy_datasets/ · legacy_scenes/)의 자식까지 내려가야 옮겨진 package·dataset 이 row 로 보인다. 여전히 디렉토리 단위다.

## 사라진 row (206) — 전부 D1 이 옮긴 것

```
  data/pallet/_v2_exactclearance_idx12_seed7500
  data/pallet/_v2_exactclearance_idx12_seed7500_r2
  data/pallet/_v2_legacy_regression_seed7000
  data/pallet/_v2_ph7_regress_base
  data/pallet/_v2_ph7_regress_final
  data/pallet/_v2_ph7_regress_new
  data/pallet/_v2_ph7_usable10
  data/pallet/_v2_ph7_usable_resume12
  data/pallet/_v2_scene_logic_500_seed7500_failed_missing_hdri_20260726
  data/pallet/_v2_scene_logic_500_seed7500_failed_prereview_p1_20260726
  data/pallet/_v2_scene_logic_probe1_seed7500
  data/pallet/_v2_scene_logic_probe1b_seed7500
  data/pallet/_v2_scene_logic_probe_modes2_repeat_seed7500
  data/pallet/_v2_scene_logic_probe_modes2_seed7500
  data/pallet/_v2_scene_logic_probe_modes_seed7500
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r1
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r10
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r11
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r13
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r14
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r15
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r16
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r17
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r17_current
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r18_no_context
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r19
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r2
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r20_support_hits
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r21_mesh_contacts
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r22_best_seed
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r22_current
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r23_axis_feedback
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r24_failclosed
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r24_side_seed_axis_feedback
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r25_infeasible_guard
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r25_side_candidate_feedback
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r26_pool640_mesh_support
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r27_pool640_six_fallback
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r28_shape_diverse
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r29_bidirectional_depth
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r3
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r30_ground_compensated_depth
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r31_axis_fixed
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r32_thin_upright
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r33_manifest_normalized
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r33_thin_upright
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r34_reserved_corridor
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r34_uniform_scale
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r35_feedback_yaw90
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r35_reserved_world_pose
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r36_tall_shallow
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r37_ground_feasible_bottom
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r38_aspect_lowres
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r39_current_modes
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r4
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r5
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r6
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r7
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r8
  data/pallet/_v2_scene_logic_probe_seed7500_f16_r9
  data/pallet/_v2_scene_logic_probe_seed7500_f18_19_r18_current
  data/pallet/_v2_scene_logic_probe_seed7500_f18_19_r26_failclosed
  data/pallet/_v2_scene_logic_probe_seed7500_f18_19_r27_targeted
  data/pallet/_v2_scene_logic_probe_seed7500_f18_r01
  data/pallet/_v2_scene_logic_probe_seed7500_f18_r19_log
  data/pallet/_v2_scene_logic_probe_seed7500_f19_r1
  data/pallet/_v2_scene_logic_probe_seed7500_f19_r20_current
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_all_assets_initial_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_bvhfallback_r05
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_controlled_image_space_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_explicit_primary_only_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_norm_final_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_prealign_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_prealign_r02
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_scorestage_r06
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_swept_reservation_r04
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_swept_reservation_r05
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_targeted_u_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_targetscore_r07
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_targetscore_r08
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_utility_first_r03
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r02
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r03
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r04
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r05
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r06
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r07
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r08
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r09
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r10
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r11
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r12
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r13
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r14
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r15
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_r16
  data/pallet/_v2_scene_logic_probe_seed7500_idx06_targetscore_r03
  data/pallet/_v2_scene_logic_probe_seed7500_idx07_norm_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx09_10_state_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx09_norm_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx09_norm_r02
  data/pallet/_v2_scene_logic_probe_seed7500_idx09_norm_r03
  data/pallet/_v2_scene_logic_probe_seed7500_idx09_norm_r04
  data/pallet/_v2_scene_logic_probe_seed7500_idx10_context_image_space_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx10_norm_r02
  data/pallet/_v2_scene_logic_probe_seed7500_idx14_norm_r01
  data/pallet/_v2_scene_logic_probe_seed7500_idx14_norm_r02
  data/pallet/_v2_scene_logic_probe_supportfix_seed7500
  data/pallet/_v2_scene_logic_smoke20_seed7500
  data/pallet/_v2_scene_logic_smoke20_seed7500_cpu_probe_g
  data/pallet/_v2_scene_logic_smoke20_seed7500_cpu_probe_h
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_a
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_c
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_d
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_e
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_f
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_g_cpu
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_h_cpu
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_m_exact
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_n_exact
  data/pallet/_v2_scene_logic_smoke20_seed7500_nodenoise_probe_i
  data/pallet/_v2_scene_logic_smoke20_seed7500_nodenoise_probe_j
  data/pallet/_v2_scene_logic_smoke20_seed7500_r10_failed_preexplicitfix_20260726
  data/pallet/_v2_scene_logic_smoke20_seed7500_r11_failed_prefailclosed_20260726
  data/pallet/_v2_scene_logic_smoke20_seed7500_r12
  data/pallet/_v2_scene_logic_smoke20_seed7500_r2
  data/pallet/_v2_scene_logic_smoke20_seed7500_r3
  data/pallet/_v2_scene_logic_smoke20_seed7500_r3_repeat
  data/pallet/_v2_scene_logic_smoke20_seed7500_r4
  data/pallet/_v2_scene_logic_smoke20_seed7500_r40
  data/pallet/_v2_scene_logic_smoke20_seed7500_r5
  data/pallet/_v2_scene_logic_smoke20_seed7500_r6
  data/pallet/_v2_scene_logic_smoke20_seed7500_r7
  data/pallet/_v2_scene_logic_smoke20_seed7500_r7_probe_idx7
  data/pallet/_v2_scene_logic_smoke20_seed7500_r8
  data/pallet/_v2_scene_logic_smoke20_seed7500_r8_failed_precontactmatrix_20260726
  data/pallet/_v2_scene_logic_smoke20_seed7500_r9
  data/pallet/_v2_scene_logic_smoke20_seed7500_singlethread_probe_k
  data/pallet/_v2_scene_logic_smoke20_seed7500_singlethread_probe_l
  data/pallet/_v2_smoke20_9c_run1
  data/pallet/_v2_smoke20_9c_run2
  data/pallet/_v2_statefix_fresh_idx2_seed7500
  data/pallet/_v2_statefix_sequence0_6_seed7500
  data/pallet/_v2_supportclearance_idx12_seed7500
  data/pallet/_v2_supportsnap_idx12_seed7500
  data/pallet/archive/_mask_test60
  data/pallet/archive/test_blender_v64
  data/pallet/archive/test_blender_v65
  data/pallet/archive/test_blender_v67
  data/pallet/archive/test_blender_v68
  data/pallet/archive/test_blender_v69
  data/pallet/archive/test_blender_v70
  data/pallet/archive/test_indoor_v1
  data/pallet/archive/textures_floor
  data/pallet/archive/textures_wood
  data/pallet/archive/train_4pallet_mask_v1
  data/pallet/archive/train_palletobj_addon_v1
  data/pallet/archive/train_palletobj_v1
  data/pallet/archive/train_palletobj_v2
  data/pallet/archive/training_data_v4
  data/pallet/archive/training_data_v4_split
  data/pallet/archive/trunc_addon_v1
  data/pallet/archive/trunc_addon_v1_pilot
  data/pallet/background
  data/pallet/blender_scene
  data/pallet/blender_scene/_sandbox_palletobj_production.blend
  data/pallet/blender_scene/_sandbox_parking_lot_check.blend
  data/pallet/blender_scene/_sandbox_parking_lot_check.blend1
  data/pallet/blender_scene/synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend
  data/pallet/blender_scene/synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend
  data/pallet/blender_scene/synth_data_scene.REBAKE_WIP.blend
  data/pallet/blender_scene/synth_data_scene.REBAKE_WIP.blend1
  data/pallet/blender_scene/synth_data_scene.blend
  data/pallet/blender_scene/synth_data_scene.blend1
  data/pallet/blender_scene/synth_data_scene12.blend
  data/pallet/blender_scene/synth_data_scene12.blend1
  data/pallet/blender_scene/synth_data_scene121.blend
  data/pallet/blender_scene/synth_data_scene_indoor.blend
  data/pallet/blender_scene/textures
  data/pallet/distractors
  data/pallet/distractors/distractors_manifest.csv
  data/pallet/distractors/distractors_manifest.csv.bak_prefill
  data/pallet/hdri
  data/pallet/hdri/LICENSE.txt
  data/pallet/hdri/SOURCES.txt
  data/pallet/models_usd
  data/pallet/pallet.zip
  data/pallet/pallets_v2_add
  data/pallet/pallets_v2_add/LICENSE.txt
  data/pallet/pallets_v2_add/SOURCES.txt
  data/pallet/real_data
  data/pallet/test_blender_v64.zip
  data/pallet/test_blender_v65.zip
  data/pallet/test_blender_v68.zip
  data/pallet/test_blender_v69.zip
  data/pallet/test_blender_v70.zip
  data/pallet/test_indoor_v1.zip
  data/pallet/train_4pallet_mask_v1.zip
  data/pallet/train_palletobj_addon_v1.zip
  data/pallet/train_palletobj_v1 (2).zip
  data/pallet/train_palletobj_v1.zip
  data/pallet/train_palletobj_v2 (2).zip
  data/pallet/train_palletobj_v2.zip
  data/pallet/train_palletobj_v3.zip
  data/pallet/trunc_addon_v1.zip
```

## 새로 생긴 row (56)

```
  data/pallet/README.md
  data/pallet/archive/README.md
  data/pallet/archive/corrupt
  data/pallet/archive/legacy_assets
  data/pallet/archive/legacy_datasets
  data/pallet/archive/legacy_datasets/noai_baked
  data/pallet/archive/legacy_datasets/noai_baked/train_4pallet_mask_v1 <- data/pallet/archive/train_4pallet_mask_v1
  data/pallet/archive/legacy_datasets/noai_baked/training_data_v4 <- data/pallet/archive/training_data_v4
  data/pallet/archive/legacy_datasets/noai_baked/training_data_v4_split <- data/pallet/archive/training_data_v4_split
  data/pallet/archive/legacy_datasets/partial
  data/pallet/archive/legacy_datasets/partial/_mask_test60 <- data/pallet/archive/_mask_test60
  data/pallet/archive/legacy_datasets/redistributable
  data/pallet/archive/legacy_datasets/redistributable/test_blender_v64 <- data/pallet/archive/test_blender_v64
  data/pallet/archive/legacy_datasets/redistributable/test_blender_v65 <- data/pallet/archive/test_blender_v65
  data/pallet/archive/legacy_datasets/redistributable/test_blender_v67 <- data/pallet/archive/test_blender_v67
  data/pallet/archive/legacy_datasets/redistributable/test_blender_v68 <- data/pallet/archive/test_blender_v68
  data/pallet/archive/legacy_datasets/redistributable/test_blender_v69 <- data/pallet/archive/test_blender_v69
  data/pallet/archive/legacy_datasets/redistributable/test_blender_v70 <- data/pallet/archive/test_blender_v70
  data/pallet/archive/legacy_datasets/redistributable/test_indoor_v1 <- data/pallet/archive/test_indoor_v1
  data/pallet/archive/legacy_datasets/redistributable/train_palletobj_addon_v1 <- data/pallet/archive/train_palletobj_addon_v1
  data/pallet/archive/legacy_datasets/redistributable/train_palletobj_v1 <- data/pallet/archive/train_palletobj_v1
  data/pallet/archive/legacy_datasets/redistributable/train_palletobj_v2 <- data/pallet/archive/train_palletobj_v2
  data/pallet/archive/legacy_datasets/redistributable/trunc_addon_v1 <- data/pallet/archive/trunc_addon_v1
  data/pallet/archive/legacy_scenes
  data/pallet/archive/legacy_scenes/blender_backups
  data/pallet/archive/legacy_scenes/snapshots
  data/pallet/archive/nonredistributable
  data/pallet/archive/packages
  data/pallet/archive/packages/background_sources
  data/pallet/archive/packages/background_sources/modular_buildings_industrial_area..zip
  data/pallet/archive/packages/background_sources/modular_buildings_industrial_area.zip
  data/pallet/archive/packages/background_sources/parking_lot.zip
  data/pallet/archive/packages/corrupt
  data/pallet/archive/packages/corrupt/train_palletobj_v1.zip <- data/pallet/train_palletobj_v1.zip
  data/pallet/archive/packages/dataset_bundles
  data/pallet/archive/packages/dataset_bundles/pallet.zip <- data/pallet/pallet.zip
  data/pallet/archive/packages/dataset_bundles/test_blender_v64.zip <- data/pallet/test_blender_v64.zip
  data/pallet/archive/packages/dataset_bundles/test_blender_v65.zip <- data/pallet/test_blender_v65.zip
  data/pallet/archive/packages/dataset_bundles/test_blender_v68.zip <- data/pallet/test_blender_v68.zip
  data/pallet/archive/packages/dataset_bundles/test_blender_v69.zip <- data/pallet/test_blender_v69.zip
  data/pallet/archive/packages/dataset_bundles/test_blender_v70.zip <- data/pallet/test_blender_v70.zip
  data/pallet/archive/packages/dataset_bundles/test_indoor_v1.zip <- data/pallet/test_indoor_v1.zip
  data/pallet/archive/packages/dataset_bundles/train_4pallet_mask_v1.zip <- data/pallet/train_4pallet_mask_v1.zip
  data/pallet/archive/packages/dataset_bundles/train_palletobj_addon_v1.zip <- data/pallet/train_palletobj_addon_v1.zip
  data/pallet/archive/packages/dataset_bundles/train_palletobj_v1 (2).zip <- data/pallet/train_palletobj_v1 (2).zip
  data/pallet/archive/packages/dataset_bundles/train_palletobj_v2 (2).zip <- data/pallet/train_palletobj_v2 (2).zip
  data/pallet/archive/packages/dataset_bundles/train_palletobj_v2.zip <- data/pallet/train_palletobj_v2.zip
  data/pallet/archive/packages/dataset_bundles/train_palletobj_v3.zip <- data/pallet/train_palletobj_v3.zip
  data/pallet/archive/packages/dataset_bundles/trunc_addon_v1.zip <- data/pallet/trunc_addon_v1.zip
  data/pallet/archive/superseded_runs
  data/pallet/archive/unidentified
  data/pallet/assets
  data/pallet/manifests
  data/pallet/reference
  data/pallet/release
  data/pallet/runs
```
