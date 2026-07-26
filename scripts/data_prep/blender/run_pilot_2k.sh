#!/bin/bash
# v2 규약 PILOT 2k chunk launcher: N frames in CHUNK-sized fresh Blender sessions.
# Each chunk = a fresh Blender process (bounds memory / OOM; no mid-run restart).
# Resumable: the driver skips frames whose rgb already exists (deterministic plan list).
set -u
TOTAL=${1:-2000}
CHUNK=${2:-200}
SEED=${3:-7000}

BLENDER="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
SCENE="E:/CODING/GitHub/FoundationPose/data/pallet/blender_scene/synth_data_scene.blend"
SCRIPT="E:/CODING/GitHub/FoundationPose/scripts/data_prep/blender/_v2_pilot_2k.py"
OUT="E:/CODING/GitHub/FoundationPose/data/pallet/_v2_pilot_2k"
LOGDIR="${OUT}/logs"
mkdir -p "$LOGDIR" "${OUT}/rgb"

echo "=== v2 PILOT 2k launcher ===  TOTAL=$TOTAL CHUNK=$CHUNK SEED=$SEED"
chunk_num=1
stall=0
while : ; do
    done_cnt=$(ls "$OUT"/rgb/f*_rgb.png 2>/dev/null | wc -l)
    if [ "$done_cnt" -ge "$TOTAL" ]; then
        echo "[$(date '+%H:%M:%S')] reached $done_cnt/$TOTAL rendered. DONE."
        break
    fi
    chunk_log="${LOGDIR}/chunk_$(printf '%03d' $chunk_num).log"
    echo "[$(date '+%H:%M:%S')] chunk $chunk_num: have $done_cnt/$TOTAL -> render up to $CHUNK more -> $chunk_log"
    "$BLENDER" -b "$SCENE" --python "$SCRIPT" -- \
        --out "$OUT" --seed "$SEED" --n "$TOTAL" --max_render "$CHUNK" \
        > "$chunk_log" 2>&1
    ec=$?
    new_cnt=$(ls "$OUT"/rgb/f*_rgb.png 2>/dev/null | wc -l)
    echo "[$(date '+%H:%M:%S')] chunk $chunk_num exit=$ec  rendered $done_cnt -> $new_cnt"
    if [ "$new_cnt" -le "$done_cnt" ]; then
        stall=$((stall+1))
        echo "  WARNING: no progress (stall=$stall). last log lines:"
        grep -E "Error|Traceback|EXCEPTION|EXC " "$chunk_log" | tail -5
        if [ "$stall" -ge 3 ]; then
            echo "  ABORT: 3 consecutive stalls."
            exit 1
        fi
        sleep 3
    else
        stall=0
    fi
    chunk_num=$((chunk_num + 1))
done
echo "=== PILOT DONE ===  rgb=$(ls "$OUT"/rgb/f*_rgb.png 2>/dev/null | wc -l)  labels=$(ls "$OUT"/labels/*.json 2>/dev/null | wc -l)"
