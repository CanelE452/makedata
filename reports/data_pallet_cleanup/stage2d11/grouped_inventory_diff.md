# Stage 2-D1 grouped_inventory.csv diff

```
before rows  266
after  rows  276
removed      0
added        10
```

## 그룹 단위 유지 확인

```
depth 분포   {1: 74, 2: 151, 3: 8, 4: 43}
entry_type   {'file': 83, 'dir': 193}
row 수 276 vs data/pallet 파일 363090 -> 그룹 인벤토리(전수 manifest 아님)
```

depth 3~4 를 유지한다 — D1/D1.1 이 만든 semantic 컨테이너(packages/ · legacy_datasets/ · legacy_scenes/)의 자식까지 내려가야 옮겨진 package·dataset 이 row 로 보인다. 여전히 디렉토리 단위다.

## 사라진 row (0) — 전부 D1 이 옮긴 것

```
```

## 새로 생긴 row (10)

```
  data/pallet/archive/legacy_scenes/blender_backups/_sandbox_parking_lot_check.blend1 <- data/pallet/assets/scenes/production/blender_scene/_sandbox_parking_lot_check.blend1
  data/pallet/archive/legacy_scenes/blender_backups/synth_data_scene.REBAKE_WIP.blend1 <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene.REBAKE_WIP.blend1
  data/pallet/archive/legacy_scenes/blender_backups/synth_data_scene.blend1 <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene.blend1
  data/pallet/archive/legacy_scenes/blender_backups/synth_data_scene12.blend1 <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene12.blend1
  data/pallet/archive/legacy_scenes/snapshots/synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend
  data/pallet/archive/legacy_scenes/snapshots/synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend
  data/pallet/archive/legacy_scenes/snapshots/synth_data_scene.REBAKE_WIP.blend <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene.REBAKE_WIP.blend
  data/pallet/archive/legacy_scenes/snapshots/synth_data_scene12.blend <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene12.blend
  data/pallet/archive/legacy_scenes/snapshots/synth_data_scene121.blend <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene121.blend
  data/pallet/archive/legacy_scenes/snapshots/synth_data_scene_indoor.blend <- data/pallet/assets/scenes/production/blender_scene/synth_data_scene_indoor.blend
```
