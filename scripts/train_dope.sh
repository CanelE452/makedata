#!/bin/bash
# DOPE 학습 실행 — config/default.yaml 기반
#
# 사용법:
#   bash scripts/train_dope.sh                    # scratch (pretrain)
#   bash scripts/train_dope.sh --finetune         # fine-tune from latest weight
#   bash scripts/train_dope.sh --finetune --net_path weights/custom/net.pth
#
# 환경: conda activate pallet-pose

set -e

CONFIG="config/default.yaml"

# --- YAML 파서 (python one-liner) ---
yq() {
    python -c "
import yaml, sys
with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)
keys = sys.argv[1].split('.')
v = cfg
for k in keys:
    v = v[k]
print(v)
" "$1"
}

PYTHON_EXE="${PYTHON_EXE:-$(yq paths.python_exe)}"

# --- 인자 파싱 ---
FINETUNE=false
NET_PATH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --finetune) FINETUNE=true; shift ;;
        --net_path) NET_PATH="$2"; shift 2 ;;
        *) echo "[WARN] Unknown arg: $1"; shift ;;
    esac
done

# --- config에서 값 로드 ---
TRAIN_DIR="$(yq data.train_dir)"
OBJECT="$(yq data.object)"
IMAGE_SIZE="$(yq model.input_size)"
SIGMA="$(yq train.sigma)"
WORKERS="$(yq train.workers)"
SAVE_EVERY="$(yq train.save_every)"
LOG_INTERVAL="$(yq train.log_interval)"
MIN_IMAGES="$(yq data.min_train_images)"

if $FINETUNE; then
    OUTPUT_DIR="$(yq train.finetune.output_dir)"
    EPOCHS="$(yq train.finetune.epochs)"
    LR="$(yq train.finetune.learning_rate)"
    if [ -z "$NET_PATH" ]; then
        NET_PATH="$(yq train.finetune.pretrained_weights)"
    fi
else
    OUTPUT_DIR="$(yq train.pretrain.output_dir)"
    EPOCHS="$(yq train.pretrain.epochs)"
    LR="$(yq train.pretrain.learning_rate)"
fi

# 데이터 확인
TRAIN_COUNT=$(ls "$TRAIN_DIR"/*.png 2>/dev/null | wc -l)
echo "Train images: $TRAIN_COUNT"
if [ "$TRAIN_COUNT" -lt "$MIN_IMAGES" ]; then
    echo "[ERROR] Too few training images ($TRAIN_COUNT < $MIN_IMAGES). Run generate_all.sh first."
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

cd Deep_Object_Pose/train

echo "============================================"
if $FINETUNE; then
    echo " DOPE Fine-tune"
    echo "============================================"
    echo " Pretrain:   ../../$NET_PATH"
else
    echo " DOPE Training (from scratch)"
    echo "============================================"
fi
echo " Config:     ../../$CONFIG"
echo " Data:       ../../$TRAIN_DIR ($TRAIN_COUNT images)"
echo " Output:     ../../$OUTPUT_DIR"
echo " Object:     $OBJECT"
echo " Epochs:     $EPOCHS"
echo " Batch size: $(if $FINETUNE; then yq train.finetune.batch_size; else yq train.pretrain.batch_size; fi)"
echo " LR:         $LR"
echo " Image size: $IMAGE_SIZE"
echo " Sigma:      $SIGMA"
echo " Workers:    $WORKERS"
echo "============================================"

BATCH_SIZE=$(if $FINETUNE; then yq train.finetune.batch_size; else yq train.pretrain.batch_size; fi)

TRAIN_CMD="\"$PYTHON_EXE\" train.py \
    --data \"../../$TRAIN_DIR\" \
    --object $OBJECT \
    --epochs $EPOCHS \
    --batchsize $BATCH_SIZE \
    --imagesize $IMAGE_SIZE \
    --lr $LR \
    --save_every $SAVE_EVERY \
    --outf \"../../$OUTPUT_DIR\" \
    --loginterval $LOG_INTERVAL \
    --workers $WORKERS \
    --sigma $SIGMA"

if $FINETUNE && [ -f "../../$NET_PATH" ]; then
    TRAIN_CMD="$TRAIN_CMD --net_path \"../../$NET_PATH\""
    echo "[INFO] Fine-tuning from: $NET_PATH"
elif $FINETUNE; then
    echo "[ERROR] Pretrain weight not found: $NET_PATH"
    exit 1
fi

eval $TRAIN_CMD

echo ""
echo "[DONE] Training complete!"
echo "  Weights: $OUTPUT_DIR/"
echo "  TensorBoard: python scripts/launch_tensorboard.py"

# 자동 Val 평가 (PCK@3/5/10px + PnP Reproj)
cd ../..
VAL_DIR="$(yq data.val_dir)"
if $FINETUNE; then
    WEIGHTS="$OUTPUT_DIR/final_net_epoch_$(printf '%04d' $EPOCHS).pth"
else
    WEIGHTS="$OUTPUT_DIR/final_net_epoch_$(printf '%04d' $EPOCHS).pth"
fi
MAX_FRAMES="$(yq eval.max_frames)"
if [ -d "$VAL_DIR" ] && [ -f "$WEIGHTS" ]; then
    echo ""
    echo "============================================"
    echo " Running Val Evaluation"
    echo "============================================"
    "$PYTHON_EXE" "$(yq paths.eval_script)" \
        --weights "$WEIGHTS" \
        --val_dir "$VAL_DIR" \
        --output_dir "$OUTPUT_DIR/eval_results" \
        --max_frames "$MAX_FRAMES"
fi

# 학습 완료 알림 (ntfy.sh)
NTFY_TOPIC="${NTFY_TOPIC:-$(yq notification.ntfy_topic)}"
if $FINETUNE; then
    MSG="DOPE fine-tune done! (lr=$LR, ${EPOCHS}ep, $TRAIN_COUNT images)"
else
    MSG="DOPE training done! (sigma=$SIGMA, ${EPOCHS}ep, $TRAIN_COUNT images)"
fi
curl -s -H "Content-Type: text/plain; charset=utf-8" -d "$MSG" "ntfy.sh/$NTFY_TOPIC" > /dev/null 2>&1 || true
