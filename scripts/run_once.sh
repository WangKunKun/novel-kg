#!/usr/bin/env bash
# 单次运行管道：LLM 429 限速或其他失败时立即停止（状态已逐章落库，安全断点），
# 不做进程级重试——由 30 分钟定时任务检查后决定是否重新启动。
# 退出码：0=全部完成；3=中途失败（大概率 429 限速），等待下次启动。
set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG=/tmp/novel_kg_run2.log
LIMIT=${1:-1617}

# 强制直连：bigmodel.cn 是国内 API，走系统代理（127.0.0.1:7897）会慢/瞬断
export HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= ALL_PROXY= all_proxy=
export NO_PROXY='*' no_proxy='*'

echo "[run_once] $(date '+%F %H:%M:%S') 启动，limit=$LIMIT" >> "$LOG"
if python -m novel_kg.cli --novel 玄鉴仙族.txt --schema config/novels/xuanjian.yaml \
    --db data/novel.db --model glm-5.3 --limit "$LIMIT" >> "$LOG" 2>&1; then
  echo "[run_once] $(date '+%F %H:%M:%S') 完成" >> "$LOG"
  exit 0
else
  rc=$?
  echo "[run_once] $(date '+%F %H:%M:%S') 失败退出(rc=$rc，大概率429限速)，已停止，等待下次定时启动" >> "$LOG"
  exit 3
fi
