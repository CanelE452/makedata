# Stage 2-D1.2 grouped_inventory.csv diff

```
before rows  276
after  rows  277
removed      7
added        8
```

## 그룹 단위 유지 확인

```
depth 분포   {1: 74, 2: 144, 3: 8, 4: 51}
entry_type   {'file': 84, 'dir': 193}
row 수 277 vs data/pallet 파일 363090 -> 그룹 인벤토리(전수 manifest 아님)
```

depth 3~4 를 유지한다 — D1/D1.1 이 만든 semantic 컨테이너(packages/ · legacy_datasets/ · legacy_scenes/)의 자식까지 내려가야 옮겨진 package·dataset 이 row 로 보인다. 여전히 디렉토리 단위다.

## 사라진 row (7) — 전부 D1 이 옮긴 것

```
  data/pallet/archive/train_palletobj_v3
  data/pallet/archive/train_palletobj_v3_post_v1
  data/pallet/archive/training_data
  data/pallet/archive/training_data_v4_emptywood
  data/pallet/archive/training_data_v4_pilotA
  data/pallet/archive/training_data_v4_split_GREYBUG
  data/pallet/archive/training_data_v4_split_bg1bak
```

## 새로 생긴 row (8)

```
  data/pallet/archive/legacy_datasets/noai_baked/training_data <- data/pallet/archive/training_data
  data/pallet/archive/legacy_datasets/noai_baked/training_data_v4_emptywood <- data/pallet/archive/training_data_v4_emptywood
  data/pallet/archive/legacy_datasets/noai_baked/training_data_v4_pilotA <- data/pallet/archive/training_data_v4_pilotA
  data/pallet/archive/legacy_datasets/noai_baked/training_data_v4_split_GREYBUG <- data/pallet/archive/training_data_v4_split_GREYBUG
  data/pallet/archive/legacy_datasets/noai_baked/training_data_v4_split_bg1bak <- data/pallet/archive/training_data_v4_split_bg1bak
  data/pallet/archive/legacy_datasets/redistributable/train_palletobj_v3 <- data/pallet/archive/train_palletobj_v3
  data/pallet/archive/legacy_datasets/redistributable/train_palletobj_v3_post_v1 <- data/pallet/archive/train_palletobj_v3_post_v1
  data/pallet/archive/legacy_scenes/snapshots/_sandbox_parking_lot_check.blend <- data/pallet/assets/scenes/production/blender_scene/_sandbox_parking_lot_check.blend
```
