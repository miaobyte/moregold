#!/bin/bash
# ============================================================
# GoldTrader 训练启动脚本
# 用法:
#   ./run.sh                  # GoldFormer 训练
#   ./run.sh goldtrader p1    # GoldTrader-R1 Phase1
#   ./run.sh goldtrader all   # GoldTrader-R1 全阶段
# ============================================================
set -uo pipefail  # 不用 -e, 自己处理错误

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

# ---- 环境变量 ----
export GOLD_DB_HOST="${GOLD_DB_HOST:-bj-cdb-9ermqj8g.sql.tencentcdb.com}"
export GOLD_DB_PORT="${GOLD_DB_PORT:-26092}"
export GOLD_DB_USER="${GOLD_DB_USER:-gold_ro}"
export GOLD_DB_PASS="${GOLD_DB_PASS:-BNbQMsn4hhnmuw6P}"
export GOLD_DB_NAME="${GOLD_DB_NAME:-gold}"

# 强制 flush stdout (关键：避免缓冲导致日志缺失)
export PYTHONUNBUFFERED=1

# ---- 日志 ----
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/train_${TIMESTAMP}.log"

# ---- 选择模型 ----
MODEL="${1:-goldformer}"
PHASE="${2:-all}"

log() {
    local msg="[$(date '+%H:%M:%S')] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

on_error() {
    local exit_code=$?
    log "❌ 训练异常退出 (exit_code=$exit_code)"
    log "   最后 20 行日志:"
    tail -20 "$LOG_FILE" | while IFS= read -r line; do log "     $line"; done
}

trap on_error ERR

# ============================================================
log "============================================================"
log "🚀 GoldTrader 训练启动"
log "   模型: $MODEL"
log "   阶段: $PHASE"
log "   日志: $LOG_FILE"
log "   时间: $(date '+%Y-%m-%d %H:%M:%S')"
log "   venv: $REPO_ROOT/venv/bin/python3"
log "   PYTHONUNBUFFERED=$PYTHONUNBUFFERED"
log "============================================================"

# ---- venv ----
VENV="$REPO_ROOT/venv/bin/python3"
if [ ! -x "$VENV" ]; then
    log "❌ venv 不存在: $VENV"
    exit 1
fi
log "✅ venv OK ($($VENV --version))"

# ---- 检查缓存 ----
CACHE_DIR="$REPO_ROOT/models/cache"
if [ -d "$CACHE_DIR" ]; then
    log "📦 缓存目录: $CACHE_DIR ($(du -sh "$CACHE_DIR" 2>/dev/null | cut -f1))"
    ls -lh "$CACHE_DIR"/*.npz 2>/dev/null | while IFS= read -r line; do
        log "   $line"
    done
else
    log "📥 首次运行, 将从 DB 全量读取 (仅一次)"
fi

# ---- 训练 ----
log ""
log ">>> 训练开始 <<<"
log ""

START_TS=$(date +%s)

if [ "$MODEL" = "goldformer" ]; then

    $VENV models/train_goldformer.py \
        --epochs 2000 \
        --lr 1e-4 \
        --batch-size 128 \
        --d-model 256 \
        --n-layers 4 \
        --seq-len 192 \
        --use-future-vol \
        2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=$?

elif [ "$MODEL" = "goldtrader" ]; then

    # DDP 多卡: ./run.sh goldtrader all 4   (4 GPUs)
    # 单卡:     ./run.sh goldtrader all 1
    NPROC="${3:-1}"
    if [ "$NPROC" -gt 1 ] 2>/dev/null; then
        log "🔗 DDP 启动: $NPROC GPUs"
        $VENV -m torch.distributed.run \
            --nproc_per_node="$NPROC" \
            models/goldtrader_r1.py \
            --phase "$PHASE" \
            --epochs 80 \
            --lr 1e-4 \
            --batch-size 128 \
            --d-model 512 \
            --seq-len 576 \
            2>&1 | tee -a "$LOG_FILE"
        EXIT_CODE=$?
    else
        $VENV models/goldtrader_r1.py \
            --phase "$PHASE" \
            --epochs 80 \
            --lr 1e-4 \
            --batch-size 128 \
            --d-model 512 \
            --seq-len 576 \
            2>&1 | tee -a "$LOG_FILE"
        EXIT_CODE=$?
    fi

else
    log "❌ 未知模型: $MODEL (可选: goldformer | goldtrader)"
    exit 1
fi

ELAPSED=$(( $(date +%s) - START_TS ))

# ============================================================
log ""
log "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    log "✅ 训练成功完成!"
else
    log "❌ 训练失败 (exit_code=$EXIT_CODE)"
fi
log "   耗时: ${ELAPSED}s ($((ELAPSED / 60))m $((ELAPSED % 60))s)"
log "   日志: $LOG_FILE"
log "   结束: $(date '+%Y-%m-%d %H:%M:%S')"
log "============================================================"

exit $EXIT_CODE
