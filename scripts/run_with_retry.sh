#!/usr/bin/env bash
# 带 429 限速退避的管道启动器：LLM 429 限速时 CLI 内部只退避 1/2/4s 不够用，
# 这里在进程级重试（断点续传安全，从首个未抽章节继续），最多 30 次、每次等 150s。
set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG=/tmp/novel_kg_run2.log
LIMIT=${1:-376}

n=0
while [ $n -lt 30 ]; do
  python -m novel_kg.cli --novel 玄鉴仙族.txt --schema config/novels/xuanjian.yaml \
    --db data/novel.db --model glm-5.3 --limit "$LIMIT" >> "$LOG" 2>&1 && {
    echo "[wrapper] $(date +%H:%M:%S) 完成" >> "$LOG"
    exit 0
  }
  n=$((n + 1))
  echo "[wrapper] $(date +%H:%M:%S) 第${n}次失败（大概率429限速），等150s重试" >> "$LOG"
  sleep 150
done
echo "[wrapper] $(date +%H:%M:%S) 重试30次仍失败，放弃" >> "$LOG"
exit 1
