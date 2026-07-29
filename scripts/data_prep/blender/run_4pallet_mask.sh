#!/bin/bash
# Driver for gen_4pallet_mask.py -- 4-USD-pallet "latest format" dataset.
#
# Format (palletobj "latest"): per frame writes
#   <out>/000000.png            RGB (Cycles 24spp) + camera_effects sensor post
#   <out>/000000.json           camera_dynamic_0123_v4 cuboid + visible-mask COCO RLE
#   <out>/overlay/000000.png    9-keypoint cuboid overlay (drawn on post-processed RGB)
#   <out>/mask/000000.png       binary visible(modal) mask (hierarchy holdout)
#   <out>/logs/                 per-chunk stats
#
# Pallets: ALL FOUR USD pallets, PALLET_WEIGHTS=[0.5, 1/6, 1/6, 1/6]
#   (scene.usd/Pallet_0 50% + scene_1/2/3 each ~16.67%). Pallet_0 emission killed.
#
# Single FLAT dataset dir (train_palletobj_v3 convention). ONE FRESH BLENDER per
# chunk (memory-leak guard). RESUME = count of {6d}.png in --out_dir. Absolute
# --out_dir passed to Blender (relative would render to C:\ but PIL post to E:\).
#
# Usage (pilot):   bash run_4pallet_mask.sh --num_frames 40  --out data/pallet/train_4pallet_mask_v1_pilot --seed 4444 --batch_size 40
# Usage (10k):     bash run_4pallet_mask.sh --num_frames 10000 --out data/pallet/train_4pallet_mask_v1 --seed 4444 --batch_size 250
set -u

NUM_FRAMES=40
OUT_DIR="data/pallet/train_4pallet_mask_v1_pilot"
SEED=4444
BATCH=40             # frames per fresh-Blender chunk
OVERLAY_EVERY=1

while [ $# -gt 0 ]; do
  case "$1" in
    --num_frames) NUM_FRAMES="$2"; shift 2;;
    --out|--out_dir) OUT_DIR="$2"; shift 2;;
    --seed) SEED="$2"; shift 2;;
    --batch_size) BATCH="$2"; shift 2;;
    --overlay_every) OVERLAY_EVERY="$2"; shift 2;;
    *) echo "unknown arg $1"; exit 1;;
  esac
done

ROOT="E:/CODING/GitHub/FoundationPose"
BLENDER="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
# Stage 2-C1: 씬 경로는 리터럴 대신 registry(config/synthetic/pallet_paths.yaml)에 물어본다.
SCENE="$(python "${ROOT}/scripts/data_prep/blender/pallet_data_paths.py" --key production_scene)"
SCRIPT="${ROOT}/scripts/data_prep/blender/gen_4pallet_mask.py"
case "$OUT_DIR" in
  /*|[A-Za-z]:*) ABS_OUT="$OUT_DIR";;          # already absolute
  *) ABS_OUT="${ROOT}/${OUT_DIR}";;
esac
LOGDIR="${ABS_OUT}/logs"
mkdir -p "$ABS_OUT" "$LOGDIR"

echo "########## 4-PALLET MASK DATASET ##########"
echo "out=$ABS_OUT  num_frames=$NUM_FRAMES seed=$SEED batch=$BATCH"

done_count=$(ls "$ABS_OUT"/[0-9]*.png 2>/dev/null | wc -l)
chunk_num=0
while [ "$done_count" -lt "$NUM_FRAMES" ]; do
  remaining=$((NUM_FRAMES - done_count))
  this=$BATCH
  [ $remaining -lt $BATCH ] && this=$remaining
  seed=$((SEED + done_count))
  log="${LOGDIR}/chunk_$(printf '%03d' $chunk_num)_${done_count}.log"
  echo "  [$(date '+%H:%M:%S')] chunk $chunk_num: ${done_count}..$((done_count+this-1)) -> $log"
  "$BLENDER" -b "$SCENE" --python "$SCRIPT" -- \
      --split train --flat_out --start_idx "$done_count" --num_frames "$this" \
      --seed "$seed" --out_dir "$ABS_OUT" --overlay_every "$OVERLAY_EVERY" \
      > "$log" 2>&1
  code=$?
  new_count=$(ls "$ABS_OUT"/[0-9]*.png 2>/dev/null | wc -l)
  echo "  [$(date '+%H:%M:%S')] chunk $chunk_num exit=$code  png ${done_count}->${new_count}"
  if [ "$new_count" -le "$done_count" ]; then
    echo "    WARNING: no progress. errors:"; grep -Ei "error|traceback|exception" "$log" | head -8
    sleep 2
    [ "$code" -ne 0 ] && break
  fi
  done_count=$new_count
  chunk_num=$((chunk_num + 1))
done

echo "########## DONE ##########"
echo "png:     $(ls "$ABS_OUT"/[0-9]*.png 2>/dev/null | wc -l)"
echo "json:    $(ls "$ABS_OUT"/[0-9]*.json 2>/dev/null | wc -l)"
echo "mask:    $(ls "$ABS_OUT"/mask/[0-9]*.png 2>/dev/null | wc -l)"
echo "overlay: $(ls "$ABS_OUT"/overlay/[0-9]*.png 2>/dev/null | wc -l)"
