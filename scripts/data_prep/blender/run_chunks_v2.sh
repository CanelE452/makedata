#!/bin/bash
# V2 chunk launcher: 10,000 frames in 10 chunks of 1000.
# Each chunk = fresh Blender process (prevents memory accumulation crash).
TOTAL=${1:-10000}
CHUNK=${2:-1000}
START_FROM=${3:-0}

BLENDER="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
SCENE="E:/CODING/GitHub/FoundationPose/data/pallet/blender_scene/_sandbox_palletobj_production.blend"
SCRIPT="E:/CODING/GitHub/FoundationPose/scripts/data_prep/blender/run_mass_10k.py"
OUT="E:/CODING/GitHub/FoundationPose/data/pallet/train_palletobj_v2"
LOGDIR="${OUT}/logs"
mkdir -p "$LOGDIR" "${OUT}/overlay"

EXISTING=$(ls $OUT/[0-9]*.png 2>/dev/null | wc -l)
if [ $EXISTING -gt $START_FROM ]; then
    echo "Found $EXISTING existing PNG files. Resuming from frame $EXISTING."
    START_FROM=$EXISTING
fi

echo "=== V2 Chunk launcher ==="
echo "Total: $TOTAL  Chunk: $CHUNK  Start: $START_FROM  Out: $OUT"

idx=$START_FROM
chunk_num=$((idx / CHUNK + 1))
while [ $idx -lt $TOTAL ]; do
    remaining=$((TOTAL - idx))
    if [ $remaining -lt $CHUNK ]; then this_chunk=$remaining; else this_chunk=$CHUNK; fi
    chunk_log="${LOGDIR}/chunk_$(printf '%03d' $chunk_num)_${idx}.log"
    echo "[$(date '+%H:%M:%S')] Chunk $chunk_num: frames $idx..$((idx+this_chunk-1)) → $chunk_log"
    seed=$((1042 + chunk_num))  # different seeds from v1
    "$BLENDER" -b "$SCENE" --python "$SCRIPT" -- \
        --num_frames $this_chunk --start_idx $idx --out "$OUT" --seed $seed \
        --progress_every 100 --purge_every 100 --chunk_size 500 \
        > "$chunk_log" 2>&1
    exit_code=$?
    echo "[$(date '+%H:%M:%S')] Chunk $chunk_num exit code: $exit_code"
    new_count=$(ls $OUT/[0-9]*.png 2>/dev/null | wc -l)
    if [ $new_count -le $idx ]; then
        echo "  WARNING: no new frames. Retrying..."
        tail -20 "$chunk_log" | grep -E "Error|Traceback|EXCEPTION" | head -3
        sleep 5
        continue
    fi
    idx=$new_count
    chunk_num=$((chunk_num + 1))
done

echo ""
echo "=== ALL CHUNKS DONE ==="
echo "Total PNG: $(ls $OUT/[0-9]*.png 2>/dev/null | wc -l)"
echo "Total JSON: $(ls $OUT/[0-9]*.json 2>/dev/null | wc -l)"
