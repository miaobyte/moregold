#!/bin/bash
# 金价查询后台服务
# 每5分钟查询一次金价并记录到本地文件
# 使用方式: ./gold_price_service.sh start

SCRIPT_DIR="/Users/peng.li24/minimax/gold"
FETCHER_SCRIPT="$SCRIPT_DIR/gold_price_fetcher.py"
LOG_FILE="$SCRIPT_DIR/service.log"

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

start_service() {
    log_message "🚀 金价查询服务启动"
    
    while true; do
        # 记录开始时间
        log_message "⏰ 开始查询金价 ($(date '+%Y-%m-%d %H:%M:%S'))"
        
        # 执行查询脚本
        python3 "$FETCHER_SCRIPT"
        
        # 等待5分钟 (300秒)
        sleep 300
    done
}

stop_service() {
    log_message "🛑 金价查询服务停止"
    # 杀掉当前脚本的进程
    pkill -f "gold_price_service.sh"
    exit 0
}

case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    *)
        echo "用法: $0 {start|stop}"
        exit 1
        ;;
esac
