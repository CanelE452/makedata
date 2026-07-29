#!/bin/bash
# Production driver for gen_dataset_v4.py — FOLDER-SPLIT version.
#
# Splits the dataset into independent per-folder DOPE datasets of --per_folder
# frames each (default 200), instead of one giant flat split dir:
#
#   <out_dir>/
#     train_batch_000/                                      (200 frames, 000000..000199)
#       000000.png  000000.json  ...                        (png + json colocated)
#       overlay/000000.png ...                              (full overlays)
#     train_batch_001/ ... train_batch_019/                 (4000 train total)
#     val_batch_000/ ... val_batch_004/                     (1000 val total)
#     logs/                                                 (chunk stats + run logs)
#
# Layout matches data/pallet/test_palletobj_r3 (DOPE-ready flat folders).
# - Each batch folder is a self-contained dataset: frame index restarts at 0 per
#   folder ({i:06d}.png + {i:06d}.json colocated in the folder root), so any DOPE
#   loader can point at one folder.
# - ONE FRESH BLENDER PROCESS per (sub-)chunk (memory-leak guard). A folder of 200
#   is filled in chunks of --batch_size; a fresh Blender per chunk.
# - RESUME = per-folder PNG count. Completed folders (count >= per_folder) are
#   skipped; a partially-filled folder is continued from its current count; only
#   the last needed folder may be partial. Safe to ctrl-C and rerun.
# - Deterministic-ish per chunk: seed = seed_base + global_folder_offset + start_idx.
#
# Usage (full run, 4000 train + 1000 val, 200/folder):
#   bash run_dataset_v4.sh --n_train 4000 --n_val 1000 \
#        --out_dir data/pallet/training_data_v4 \
#        --seed 7000 --per_folder 200 --batch_size 200 --overlay_every 1
set -u

N_TRAIN=4000
N_VAL=1000
OUT_DIR="data/pallet/training_data_v4"
SEED=7000
PER_FOLDER=200       # frames per batch folder
BATCH=200            # frames per fresh-Blender chunk (<= PER_FOLDER)
OVERLAY_EVERY=1      # save overlay every N frames; 1 = full (r3 layout, every frame)

while [ $# -gt 0 ]; do
  case "$1" in
    --n_train) N_TRAIN="$2"; shift 2;;
    --n_val) N_VAL="$2"; shift 2;;
    --out_dir) OUT_DIR="$2"; shift 2;;
    --seed) SEED="$2"; shift 2;;
    --per_folder) PER_FOLDER="$2"; shift 2;;
    --batch_size) BATCH="$2"; shift 2;;
    --overlay_every) OVERLAY_EVERY="$2"; shift 2;;
    *) echo "unknown arg $1"; exit 1;;
  esac
done

# clamp chunk size to folder size
[ "$BATCH" -gt "$PER_FOLDER" ] && BATCH="$PER_FOLDER"

ROOT="E:/CODING/GitHub/FoundationPose"
BLENDER="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
# Stage 2-C1: 씬 경로는 리터럴 대신 registry(config/synthetic/pallet_paths.yaml)에 물어본다.
# active 씬은 portable blend 이고, 원본은 rollback source 로만 남는다.
SCENE="$(python "${ROOT}/scripts/data_prep/blender/pallet_data_paths.py" --key production_scene)"
SCRIPT="${ROOT}/scripts/data_prep/blender/gen_dataset_v4.py"
ABS_OUT="${ROOT}/${OUT_DIR}"
LOGDIR="${ABS_OUT}/logs"
mkdir -p "$LOGDIR"

# Fill ONE batch folder to PER_FOLDER frames, chunk by chunk (fresh Blender each).
#   $1 split (train|val)  $2 folder_name  $3 seed_base_for_folder
fill_folder () {
  local split="$1"; local folder="$2"; local seed_base="$3"
  local fdir="${ABS_OUT}/${folder}"           # batch folder = dataset root (--flat_out)
  local sdir="$fdir"                           # r3 layout: png/json in folder root
  mkdir -p "$sdir"
  local done_count
  done_count=$(ls "$sdir"/[0-9]*.png 2>/dev/null | wc -l)
  if [ "$done_count" -ge "$PER_FOLDER" ]; then
    echo "  [SKIP] $folder already complete ($done_count/$PER_FOLDER)"
    return 0
  fi
  echo "  [FOLDER] $folder  existing=$done_count target=$PER_FOLDER"
  local chunk_num=0
  while [ "$done_count" -lt "$PER_FOLDER" ]; do
    local remaining=$((PER_FOLDER - done_count))
    local this=$BATCH
    [ $remaining -lt $BATCH ] && this=$remaining
    local seed=$((seed_base + done_count))
    local log="${LOGDIR}/${folder}_c$(printf '%03d' $chunk_num)_${done_count}.log"
    echo "  [$(date '+%H:%M:%S')] $folder chunk $chunk_num: ${done_count}..$((done_count+this-1)) -> $log"
    "$BLENDER" -b "$SCENE" --python "$SCRIPT" -- \
        --split "$split" --flat_out --start_idx "$done_count" --num_frames "$this" \
        --seed "$seed" --out_dir "${OUT_DIR}/${folder}" --overlay_every "$OVERLAY_EVERY" \
        > "$log" 2>&1
    local code=$?
    local new_count
    new_count=$(ls "$sdir"/[0-9]*.png 2>/dev/null | wc -l)
    echo "  [$(date '+%H:%M:%S')] $folder chunk $chunk_num exit=$code  png ${done_count}->${new_count}"
    if [ "$new_count" -le "$done_count" ]; then
      echo "    WARNING: no progress. errors:"; grep -Ei "error|traceback|exception" "$log" | head -5
      sleep 3
    fi
    done_count=$new_count
    chunk_num=$((chunk_num + 1))
  done
  echo "  [FOLDER DONE] $folder  $(ls "$sdir"/[0-9]*.png 2>/dev/null | wc -l)/$PER_FOLDER png"
}

# Generate $2 total frames for split $1, sharded into PER_FOLDER folders.
run_split () {
  local split="$1"; local total="$2"; local seed_base="$3"
  local n_folders=$(( (total + PER_FOLDER - 1) / PER_FOLDER ))
  echo "=== SPLIT $split: total=$total per_folder=$PER_FOLDER -> $n_folders folders ==="
  local i=0
  while [ "$i" -lt "$n_folders" ]; do
    local folder
    folder=$(printf '%s_batch_%03d' "$split" "$i")
    # last folder may be smaller than PER_FOLDER (handled below)
    local cap=$PER_FOLDER
    local already=$(( i * PER_FOLDER ))
    local left=$(( total - already ))
    [ $left -lt $cap ] && cap=$left
    # distinct seed region per folder so folders are not identical
    local folder_seed=$(( seed_base + i * 10000 ))
    # temporarily fill to `cap` (may be < PER_FOLDER for the last folder)
    PER_FOLDER_SAVE=$PER_FOLDER
    PER_FOLDER=$cap
    fill_folder "$split" "$folder" "$folder_seed"
    PER_FOLDER=$PER_FOLDER_SAVE
    i=$((i + 1))
  done
  echo "=== SPLIT $split DONE: $n_folders folders ==="
}

echo "########## DATASET v4 GENERATION (folder-split) ##########"
echo "out=$ABS_OUT  n_train=$N_TRAIN n_val=$N_VAL seed=$SEED per_folder=$PER_FOLDER batch=$BATCH overlay_every=$OVERLAY_EVERY"
run_split train "$N_TRAIN" "$SEED"
run_split val   "$N_VAL"   "$((SEED + 100000))"
echo "########## ALL DONE ##########"
echo "train folders: $(ls -d "${ABS_OUT}"/train_batch_* 2>/dev/null | wc -l)"
echo "val   folders: $(ls -d "${ABS_OUT}"/val_batch_* 2>/dev/null | wc -l)"
echo "train png total: $(ls "${ABS_OUT}"/train_batch_*/[0-9]*.png 2>/dev/null | wc -l)"
echo "val   png total: $(ls "${ABS_OUT}"/val_batch_*/[0-9]*.png 2>/dev/null | wc -l)"
