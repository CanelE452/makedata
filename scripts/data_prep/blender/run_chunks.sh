#!/bin/bash
# Chunk launcher: run mass production in N chunks, each chunk is a separate Blender process.
# This prevents memory accumulation crashes (EXCEPTION_ACCESS_VIOLATION after ~2500 frames).
#
# Usage:
#   bash run_chunks.sh [TOTAL] [CHUNK] [START_FROM]
#   defaults: TOTAL=10000, CHUNK=1000, START_FROM=0
#
# Each chunk launches a fresh Blender CLI process that renders CHUNK frames starting at start_idx.
# Frames already on disk are auto-skipped (resume support).

TOTAL=${1:-10000}
CHUNK=${2:-1000}
START_FROM=${3:-0}

BLENDER="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
SCENE="E:/CODING/GitHub/FoundationPose/data/pallet/blender_scene/_sandbox_palletobj_production.blend"
SCRIPT="E:/CODING/GitHub/FoundationPose/scripts/data_prep/blender/run_mass_10k.py"
OUT="E:/CODING/GitHub/FoundationPose/data/pallet/train_palletobj_v1"
LOGDIR="${OUT}/logs"
mkdir -p "$LOGDIR" "${OUT}/overlay"

# Detect already-finished frames so we can resume
EXISTING=$(ls $OUT/*.png 2>/dev/null | wc -l)
if [ $EXISTING -gt $START_FROM ]; then
    echo "Found $EXISTING existing PNG files. Resuming from frame $EXISTING."
    START_FROM=$EXISTING
fi

echo "=== Chunk launcher ==="
echo "Total target: $TOTAL"
echo "Chunk size:   $CHUNK"
echo "Start from:   $START_FROM"
echo "Output:       $OUT"
echo ""

idx=$START_FROM
chunk_num=$((idx / CHUNK + 1))
while [ $idx -lt $TOTAL ]; do
    remaining=$((TOTAL - idx))
    if [ $remaining -lt $CHUNK ]; then this_chunk=$remaining; else this_chunk=$CHUNK; fi
    chunk_log="${LOGDIR}/chunk_$(printf '%03d' $chunk_num)_${idx}.log"
    echo "[$(date '+%H:%M:%S')] Chunk $chunk_num: frames $idx..$((idx+this_chunk-1)) → $chunk_log"

    seed=$((42 + chunk_num))
    "$BLENDER" -b "$SCENE" --python "$SCRIPT" -- \
        --num_frames $this_chunk \
        --start_idx $idx \
        --out "$OUT" \
        --seed $seed \
        --progress_every 100 \
        --purge_every 100 \
        --chunk_size 500 \
        > "$chunk_log" 2>&1
    exit_code=$?
    echo "[$(date '+%H:%M:%S')] Chunk $chunk_num exit code: $exit_code"

    # Verify chunk progress (don't trust exit code alone)
    new_count=$(ls $OUT/*.png 2>/dev/null | wc -l)
    if [ $new_count -le $idx ]; then
        echo "  WARNING: no new frames generated in this chunk. Possibly hung or failed early."
        # Look for error
        tail -20 "$chunk_log" | grep -E "Error|Traceback|EXCEPTION" | head -3
        echo "  Retrying same chunk after 5s..."
        sleep 5
        # don't advance idx — try again
        continue
    fi
    idx=$new_count
    chunk_num=$((chunk_num + 1))
done

echo ""
echo "=== ALL CHUNKS DONE ==="
echo "Total PNG files: $(ls $OUT/*.png 2>/dev/null | wc -l)"
echo "Total JSON files: $(ls $OUT/*.json 2>/dev/null | wc -l)"
