#!/bin/bash
# Reproduce the `train_palletobj_addon_v1` dataset (D435i-aligned add-on, 6000 frames).
#
# This is a thin, parametric wrapper around run_mass_10k.py that pins the EXACT
# preset used for the original add-on run (verified from
# data/pallet/train_palletobj_addon_v1_gen.log):
#
#   blend   = data/pallet/blender_scene/_sandbox_palletobj_production.blend
#   driver  = scripts/data_prep/blender/run_mass_10k.py  (-> gen_palletobj_scenarios.py)
#   frames  = 6000    seed = 7777    out = data/pallet/train_palletobj_addon_v1
#   engine  = EEVEE 16spp, 640x480    result: 6000/6000, 6498 attempts, ~64 min
#
# What this dataset is (see _docs/history/2026-06-24.md "add-on 렌더" section):
#   - D435i factory intrinsic pinned (fx=605.9 cx=317.6 cy=256.3, distortion=0),
#     lens 34.08mm HORIZONTAL, reproj < 0.1px.
#   - azimuth 0~360 uniform, elevation 0~60, projected-size 5-bin uniform.
#   - camera_effects.py RGB post-DR (WB/vignette/blur/sensor noise/JPEG),
#     per-frame deterministic (seeded by frame index; labels/mask unaffected).
#   - labels: camera-facing dynamic 0123 + visible mask (same convention as v3).
#
# Determinism: run_mass_10k.py seeds `random` once (7777) and consumes it
# sequentially, so the SAME seed reproduces the SAME scenario stream (incl. the
# rejection points). Only EEVEE/GPU pixels may differ by a hair; labels are exact.
#
# Usage:
#   # exact reproduction (refuses to overwrite an existing non-empty out):
#   bash scripts/data_prep/blender/run_addon_v1.sh
#   # make a fresh variant (e.g. addon_v2) with a different seed:
#   bash scripts/data_prep/blender/run_addon_v1.sh --seed 8888 \
#        --out data/pallet/train_palletobj_addon_v2
#   # resume a partial run from its current png count:
#   bash scripts/data_prep/blender/run_addon_v1.sh --start_idx <n>
#   # allow overwriting an existing out:
#   bash scripts/data_prep/blender/run_addon_v1.sh --force
set -u

NUM_FRAMES=6000
SEED=7777
OUT="data/pallet/train_palletobj_addon_v1"
START_IDX=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --num_frames) NUM_FRAMES="$2"; shift 2;;
    --seed)       SEED="$2"; shift 2;;
    --out)        OUT="$2"; shift 2;;
    --start_idx)  START_IDX="$2"; shift 2;;
    --force)      FORCE=1; shift;;
    *) echo "unknown arg $1"; exit 1;;
  esac
done

ROOT="E:/CODING/GitHub/FoundationPose"
BLENDER="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
SCENE="${ROOT}/data/pallet/blender_scene/_sandbox_palletobj_production.blend"
SCRIPT="${ROOT}/scripts/data_prep/blender/run_mass_10k.py"
ABS_OUT="${ROOT}/${OUT}"
LOG="${ROOT}/data/pallet/$(basename "$OUT")_gen.log"

# --- preflight: dependencies must exist or the run silently mis-renders ---
missing=0
for dep in "$BLENDER" "$SCENE" "$SCRIPT" \
           "${ROOT}/data/palletobj/pallet_full.obj" \
           "${ROOT}/data/pallet/hdri" \
           "${ROOT}/data/pallet/textures_floor" \
           "${ROOT}/data/pallet/textures_wood"; do
  if [ ! -e "$dep" ]; then echo "MISSING dependency: $dep"; missing=1; fi
done
[ "$missing" -eq 1 ] && { echo "Aborting: fix missing dependencies above."; exit 1; }

# --- guard: don't clobber an existing dataset unless resuming or --force ---
existing=$(ls "${ABS_OUT}"/[0-9]*.png 2>/dev/null | wc -l)
if [ "$existing" -gt 0 ] && [ "$START_IDX" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
  echo "REFUSING: '$OUT' already has $existing png. run_mass_10k.py overwrites from"
  echo "start_idx=0. Use --force to overwrite, --start_idx $existing to resume, or"
  echo "--out data/pallet/train_palletobj_addon_v2 to make a fresh variant."
  exit 1
fi

mkdir -p "${ABS_OUT}/overlay" "${ABS_OUT}/mask"
echo "########## PALLETOBJ ADD-ON GENERATION ##########"
echo "out=$ABS_OUT  frames=$NUM_FRAMES  seed=$SEED  start_idx=$START_IDX"
echo "blend=$SCENE"
echo "log=$LOG"
echo "started: $(date '+%Y-%m-%d %H:%M:%S')"

"$BLENDER" -b "$SCENE" --python "$SCRIPT" -- \
    --num_frames "$NUM_FRAMES" --out "$ABS_OUT" --seed "$SEED" --start_idx "$START_IDX" \
    > "$LOG" 2>&1
code=$?

png=$(ls "${ABS_OUT}"/[0-9]*.png 2>/dev/null | wc -l)
msk=$(ls "${ABS_OUT}/mask"/[0-9]*.png 2>/dev/null | wc -l)
jsn=$(ls "${ABS_OUT}"/[0-9]*.json 2>/dev/null | wc -l)
echo "########## DONE (exit=$code) ##########"
echo "png=$png  mask=$msk  json=$jsn   (target=$NUM_FRAMES)"
echo "tail of log:"; tail -3 "$LOG"
