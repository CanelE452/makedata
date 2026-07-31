# Stage 2-D2 grouped_inventory.csv diff

```
before rows  277
after  rows  142
removed      199
added        64
```

## 그룹 단위 유지 확인

```
depth 분포   {1: 9, 2: 10, 3: 72, 4: 51}
entry_type   {'file': 32, 'dir': 110}
row 수 142 vs data/pallet 파일 363090 -> 그룹 인벤토리(전수 manifest 아님)
```

depth 3~4 를 유지한다 — D1/D1.1 이 만든 semantic 컨테이너(packages/ · legacy_datasets/ · legacy_scenes/)의 자식까지 내려가야 옮겨진 package·dataset 이 row 로 보인다. 여전히 디렉토리 단위다.

## 사라진 row (199) — 전부 D1 이 옮긴 것

```
  data/pallet/_addon_pilot2.log
  data/pallet/_addon_pilot3.log
  data/pallet/_addon_pilot4.log
  data/pallet/_addon_pilot_gen.log
  data/pallet/_copy_and_zip_c.py
  data/pallet/_copy_c.log
  data/pallet/_finalize_c_zip.py
  data/pallet/_floor_applied14_render.log
  data/pallet/_floor_catalog.png
  data/pallet/_floor_test10_render.log
  data/pallet/_make_split_zips.log
  data/pallet/_make_split_zips.py
  data/pallet/_make_zip_lowmem.log
  data/pallet/_make_zip_lowmem.py
  data/pallet/_mask_test10_gen.log
  data/pallet/_mask_test60_gen.log
  data/pallet/_mat_test10_gen.log
  data/pallet/_mat_test10b_gen.log
  data/pallet/_mat_test10e_closeup.log
  data/pallet/_mat_test10e_gen.log
  data/pallet/_material_compare_run.log
  data/pallet/_ram_test.log
  data/pallet/_ram_test.py
  data/pallet/_read_stability_test.py
  data/pallet/_rebuild_part7.log
  data/pallet/_rebuild_part7_nocache.py
  data/pallet/_rebuild_parts.log
  data/pallet/_rebuild_parts.py
  data/pallet/_repack.log
  data/pallet/_repack.py
  data/pallet/_repack_retry.log
  data/pallet/_repack_retry.py
  data/pallet/_stress_read.log
  data/pallet/_stress_read.py
  data/pallet/_tmp_ph
  data/pallet/_trunc_addon_v1_10m_example
  data/pallet/_trunc_addon_v1_far_example
  data/pallet/_v2_b3_check
  data/pallet/_v2_calib_200
  data/pallet/_v2_g5_reverify
  data/pallet/_v2_pilot_2k
  data/pallet/_v2_publicmask_overlay_smoke8
  data/pallet/_v2_scene_logic_500_seed7500
  data/pallet/_v2_scene_logic_probe_seed7500_f18_r19_log.console.txt
  data/pallet/_v2_scene_logic_probe_seed7500_idx02_prealign_r01.log
  data/pallet/_v2_scene_logic_smoke20_seed7500_r40.log
  data/pallet/_v2_scene_logic_smoke20_seed7500_r7_blender.log
  data/pallet/_v2_smoke50_9d
  data/pallet/_wood_closeup.log
  data/pallet/archive/_addon_pilot
  data/pallet/archive/_addon_pilot2
  data/pallet/archive/_addon_pilot3
  data/pallet/archive/_addon_pilot4
  data/pallet/archive/_cam_test10
  data/pallet/archive/_cam_test10b
  data/pallet/archive/_diag_pallet3
  data/pallet/archive/_efront_12kp_check
  data/pallet/archive/_emptywood_test
  data/pallet/archive/_floor_applied14
  data/pallet/archive/_floor_compare
  data/pallet/archive/_floor_emit
  data/pallet/archive/_floor_fix_test
  data/pallet/archive/_floor_smoke10
  data/pallet/archive/_floor_test10
  data/pallet/archive/_floor_test10b
  data/pallet/archive/_floor_test10b_std
  data/pallet/archive/_floor_uv_test
  data/pallet/archive/_mask_poc
  data/pallet/archive/_mask_test10
  data/pallet/archive/_mat_test10
  data/pallet/archive/_mat_test10b
  data/pallet/archive/_mat_test10c
  data/pallet/archive/_mat_test10d
  data/pallet/archive/_mat_test10d_scene3
  data/pallet/archive/_mat_test10e
  data/pallet/archive/_material_compare
  data/pallet/archive/_mesh_proc_compare
  data/pallet/archive/_pallet_catalog_0123
  data/pallet/archive/_perm_v4_fix_check
  data/pallet/archive/_preview10
  data/pallet/archive/_procedural_textures
  data/pallet/archive/_test_topview
  data/pallet/archive/_wood_skin_compare
  data/pallet/archive/rotation_debug
  data/pallet/archive/runtime_pallet_debug
  data/pallet/archive/test_blender_v1
  data/pallet/archive/test_blender_v10
  data/pallet/archive/test_blender_v11
  data/pallet/archive/test_blender_v12
  data/pallet/archive/test_blender_v13
  data/pallet/archive/test_blender_v14
  data/pallet/archive/test_blender_v15
  data/pallet/archive/test_blender_v16
  data/pallet/archive/test_blender_v17
  data/pallet/archive/test_blender_v18
  data/pallet/archive/test_blender_v19
  data/pallet/archive/test_blender_v2
  data/pallet/archive/test_blender_v20
  data/pallet/archive/test_blender_v21
  data/pallet/archive/test_blender_v22
  data/pallet/archive/test_blender_v23
  data/pallet/archive/test_blender_v24
  data/pallet/archive/test_blender_v25
  data/pallet/archive/test_blender_v26
  data/pallet/archive/test_blender_v27
  data/pallet/archive/test_blender_v28
  data/pallet/archive/test_blender_v29
  data/pallet/archive/test_blender_v3
  data/pallet/archive/test_blender_v30
  data/pallet/archive/test_blender_v31
  data/pallet/archive/test_blender_v32
  data/pallet/archive/test_blender_v33
  data/pallet/archive/test_blender_v34
  data/pallet/archive/test_blender_v35
  data/pallet/archive/test_blender_v36
  data/pallet/archive/test_blender_v37
  data/pallet/archive/test_blender_v38
  data/pallet/archive/test_blender_v39
  data/pallet/archive/test_blender_v4
  data/pallet/archive/test_blender_v40
  data/pallet/archive/test_blender_v41
  data/pallet/archive/test_blender_v42
  data/pallet/archive/test_blender_v43
  data/pallet/archive/test_blender_v44
  data/pallet/archive/test_blender_v45
  data/pallet/archive/test_blender_v46
  data/pallet/archive/test_blender_v47
  data/pallet/archive/test_blender_v48
  data/pallet/archive/test_blender_v49
  data/pallet/archive/test_blender_v5
  data/pallet/archive/test_blender_v50
  data/pallet/archive/test_blender_v51
  data/pallet/archive/test_blender_v52
  data/pallet/archive/test_blender_v53
  data/pallet/archive/test_blender_v54
  data/pallet/archive/test_blender_v55
  data/pallet/archive/test_blender_v56
  data/pallet/archive/test_blender_v57
  data/pallet/archive/test_blender_v58
  data/pallet/archive/test_blender_v59
  data/pallet/archive/test_blender_v6
  data/pallet/archive/test_blender_v60
  data/pallet/archive/test_blender_v61
  data/pallet/archive/test_blender_v62
  data/pallet/archive/test_blender_v63
  data/pallet/archive/test_blender_v66
  data/pallet/archive/test_blender_v7
  data/pallet/archive/test_blender_v8
  data/pallet/archive/test_blender_v9
  data/pallet/archive/test_canonical
  data/pallet/archive/test_diagnose
  data/pallet/archive/test_diagnose2
  data/pallet/archive/test_diagnose3
  data/pallet/archive/test_final_check
  data/pallet/archive/test_fix_axis
  data/pallet/archive/test_fix_scene
  data/pallet/archive/test_indoor
  data/pallet/archive/test_iter2
  data/pallet/archive/test_iter3
  data/pallet/archive/test_iter4
  data/pallet/archive/test_iter5
  data/pallet/archive/test_iter6
  data/pallet/archive/test_iter7
  data/pallet/archive/test_iter8
  data/pallet/archive/test_iter9
  data/pallet/archive/test_models
  data/pallet/archive/test_palletobj_cargo
  data/pallet/archive/test_palletobj_cargo_v2
  data/pallet/archive/test_palletobj_r1
  data/pallet/archive/test_palletobj_r2
  data/pallet/archive/test_palletobj_r3
  data/pallet/archive/test_palletobj_r4
  data/pallet/archive/test_palletobj_v1
  data/pallet/archive/test_v3_guide
  data/pallet/archive/test_v4_bright
  data/pallet/archive/test_v4_pt
  data/pallet/archive/test_v5_pt32
  data/pallet/archive/test_v6_reinhard
  data/pallet/archive/test_v7_reinhard2
  data/pallet/archive/test_v8_lowbounce
  data/pallet/archive/test_yup
  data/pallet/archive/train_4pallet_mask_v1_pilot
  data/pallet/archive/usd_debug
  data/pallet/eval_results
  data/pallet/logs
  data/pallet/render_2000.log
  data/pallet/test_canonical_log.txt
  data/pallet/test_indoor_v1_log.txt
  data/pallet/test_iter2_log.txt
  data/pallet/test_iter3_log.txt
  data/pallet/train_4pallet_mask_v1_gen.log
  data/pallet/train_palletobj_addon_v1_gen.log
  data/pallet/train_palletobj_v3_gen.log
  data/pallet/training_data_v4_emptywood_run.log
  data/pallet/training_data_v4_run.log
  data/pallet/training_data_v4_split_run.log
  data/pallet/trunc_addon_v1_gen.log
  data/pallet/trunc_addon_v1_pilot_gen.log
  data/pallet/v2_dryrun_audit
```

## 새로 생긴 row (64)

```
  data/pallet/archive/legacy_datasets/test_blender_v1 <- data/pallet/archive/test_blender_v1
  data/pallet/archive/legacy_datasets/test_blender_v10 <- data/pallet/archive/test_blender_v10
  data/pallet/archive/legacy_datasets/test_blender_v11 <- data/pallet/archive/test_blender_v11
  data/pallet/archive/legacy_datasets/test_blender_v12 <- data/pallet/archive/test_blender_v12
  data/pallet/archive/legacy_datasets/test_blender_v13 <- data/pallet/archive/test_blender_v13
  data/pallet/archive/legacy_datasets/test_blender_v14 <- data/pallet/archive/test_blender_v14
  data/pallet/archive/legacy_datasets/test_blender_v15 <- data/pallet/archive/test_blender_v15
  data/pallet/archive/legacy_datasets/test_blender_v16 <- data/pallet/archive/test_blender_v16
  data/pallet/archive/legacy_datasets/test_blender_v17 <- data/pallet/archive/test_blender_v17
  data/pallet/archive/legacy_datasets/test_blender_v18 <- data/pallet/archive/test_blender_v18
  data/pallet/archive/legacy_datasets/test_blender_v19 <- data/pallet/archive/test_blender_v19
  data/pallet/archive/legacy_datasets/test_blender_v2 <- data/pallet/archive/test_blender_v2
  data/pallet/archive/legacy_datasets/test_blender_v20 <- data/pallet/archive/test_blender_v20
  data/pallet/archive/legacy_datasets/test_blender_v21 <- data/pallet/archive/test_blender_v21
  data/pallet/archive/legacy_datasets/test_blender_v22 <- data/pallet/archive/test_blender_v22
  data/pallet/archive/legacy_datasets/test_blender_v23 <- data/pallet/archive/test_blender_v23
  data/pallet/archive/legacy_datasets/test_blender_v24 <- data/pallet/archive/test_blender_v24
  data/pallet/archive/legacy_datasets/test_blender_v25 <- data/pallet/archive/test_blender_v25
  data/pallet/archive/legacy_datasets/test_blender_v26 <- data/pallet/archive/test_blender_v26
  data/pallet/archive/legacy_datasets/test_blender_v27 <- data/pallet/archive/test_blender_v27
  data/pallet/archive/legacy_datasets/test_blender_v28 <- data/pallet/archive/test_blender_v28
  data/pallet/archive/legacy_datasets/test_blender_v29 <- data/pallet/archive/test_blender_v29
  data/pallet/archive/legacy_datasets/test_blender_v3 <- data/pallet/archive/test_blender_v3
  data/pallet/archive/legacy_datasets/test_blender_v30 <- data/pallet/archive/test_blender_v30
  data/pallet/archive/legacy_datasets/test_blender_v31 <- data/pallet/archive/test_blender_v31
  data/pallet/archive/legacy_datasets/test_blender_v32 <- data/pallet/archive/test_blender_v32
  data/pallet/archive/legacy_datasets/test_blender_v33 <- data/pallet/archive/test_blender_v33
  data/pallet/archive/legacy_datasets/test_blender_v34 <- data/pallet/archive/test_blender_v34
  data/pallet/archive/legacy_datasets/test_blender_v35 <- data/pallet/archive/test_blender_v35
  data/pallet/archive/legacy_datasets/test_blender_v36 <- data/pallet/archive/test_blender_v36
  data/pallet/archive/legacy_datasets/test_blender_v37 <- data/pallet/archive/test_blender_v37
  data/pallet/archive/legacy_datasets/test_blender_v38 <- data/pallet/archive/test_blender_v38
  data/pallet/archive/legacy_datasets/test_blender_v39 <- data/pallet/archive/test_blender_v39
  data/pallet/archive/legacy_datasets/test_blender_v4 <- data/pallet/archive/test_blender_v4
  data/pallet/archive/legacy_datasets/test_blender_v40 <- data/pallet/archive/test_blender_v40
  data/pallet/archive/legacy_datasets/test_blender_v41 <- data/pallet/archive/test_blender_v41
  data/pallet/archive/legacy_datasets/test_blender_v42 <- data/pallet/archive/test_blender_v42
  data/pallet/archive/legacy_datasets/test_blender_v43 <- data/pallet/archive/test_blender_v43
  data/pallet/archive/legacy_datasets/test_blender_v44 <- data/pallet/archive/test_blender_v44
  data/pallet/archive/legacy_datasets/test_blender_v45 <- data/pallet/archive/test_blender_v45
  data/pallet/archive/legacy_datasets/test_blender_v46 <- data/pallet/archive/test_blender_v46
  data/pallet/archive/legacy_datasets/test_blender_v47 <- data/pallet/archive/test_blender_v47
  data/pallet/archive/legacy_datasets/test_blender_v48 <- data/pallet/archive/test_blender_v48
  data/pallet/archive/legacy_datasets/test_blender_v49 <- data/pallet/archive/test_blender_v49
  data/pallet/archive/legacy_datasets/test_blender_v5 <- data/pallet/archive/test_blender_v5
  data/pallet/archive/legacy_datasets/test_blender_v50 <- data/pallet/archive/test_blender_v50
  data/pallet/archive/legacy_datasets/test_blender_v51 <- data/pallet/archive/test_blender_v51
  data/pallet/archive/legacy_datasets/test_blender_v52 <- data/pallet/archive/test_blender_v52
  data/pallet/archive/legacy_datasets/test_blender_v53 <- data/pallet/archive/test_blender_v53
  data/pallet/archive/legacy_datasets/test_blender_v54 <- data/pallet/archive/test_blender_v54
  data/pallet/archive/legacy_datasets/test_blender_v55 <- data/pallet/archive/test_blender_v55
  data/pallet/archive/legacy_datasets/test_blender_v56 <- data/pallet/archive/test_blender_v56
  data/pallet/archive/legacy_datasets/test_blender_v57 <- data/pallet/archive/test_blender_v57
  data/pallet/archive/legacy_datasets/test_blender_v58 <- data/pallet/archive/test_blender_v58
  data/pallet/archive/legacy_datasets/test_blender_v59 <- data/pallet/archive/test_blender_v59
  data/pallet/archive/legacy_datasets/test_blender_v6 <- data/pallet/archive/test_blender_v6
  data/pallet/archive/legacy_datasets/test_blender_v60 <- data/pallet/archive/test_blender_v60
  data/pallet/archive/legacy_datasets/test_blender_v61 <- data/pallet/archive/test_blender_v61
  data/pallet/archive/legacy_datasets/test_blender_v62 <- data/pallet/archive/test_blender_v62
  data/pallet/archive/legacy_datasets/test_blender_v63 <- data/pallet/archive/test_blender_v63
  data/pallet/archive/legacy_datasets/test_blender_v66 <- data/pallet/archive/test_blender_v66
  data/pallet/archive/legacy_datasets/test_blender_v7 <- data/pallet/archive/test_blender_v7
  data/pallet/archive/legacy_datasets/test_blender_v8 <- data/pallet/archive/test_blender_v8
  data/pallet/archive/legacy_datasets/test_blender_v9 <- data/pallet/archive/test_blender_v9
```
