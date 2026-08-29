#!/usr/bin/env bash
# 单次运行管道：LLM 429 限速或其他失败时立即停止（状态已逐章落库，安全断点），
# 不做进程级重试——由 30 分钟定时任务检查后决定是否重新启动。
# 另含看门狗：超过 25 分钟无新章节落库（连接僵死，超时兜底不触发的场景）
# 则杀掉 CLI 退出，同样交给定时任务重启。
# 退出码：0=全部完成；3=中途失败/卡死，等待下次启动。
set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG=/tmp/novel_kg_run2.log
LIMIT=${1:-1617}
DB=data/novel.db
STALL_MINUTES=25

# 强制直连：bigmodel.cn 是国内 API，走系统代理（127.0.0.1:7897）会慢/瞬断
export HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= ALL_PROXY= all_proxy=
export NO_PROXY='*' no_proxy='*'

progress() { sqlite3 "$DB" "SELECT COALESCE(MAX(chapter),0) FROM extractions;" 2>/dev/null || echo 0; }

echo "[run_once] $(date '+%F %H:%M:%S') 启动，limit=${LIMIT}（看门狗${STALL_MINUTES}分钟）" >> "$LOG"
python -m novel_kg.cli --novel 玄鉴仙族.txt --schema config/novels/xuanjian.yaml \
    --db "$DB" --model glm-5.3 --limit "$LIMIT" >> "$LOG" 2>&1 &
PID=$!

LAST=$(progress); LAST_AT=$(date +%s)
while kill -0 "$PID" 2>/dev/null; do
  sleep 60
  CUR=$(progress)
  if [ "$CUR" != "$LAST" ]; then
    LAST=$CUR; LAST_AT=$(date +%s)
  elif [ $(( $(date +%s) - LAST_AT )) -gt $(( STALL_MINUTES * 60 )) ]; then
    echo "[run_once] $(date '+%F %H:%M:%S') 看门狗：${STALL_MINUTES}分钟无进展（卡在${CUR}章），杀掉重启换连接" >> "$LOG"
    kill "$PID" 2>/dev/null; sleep 2; kill -9 "$PID" 2>/dev/null
    exit 3
  fi
done

wait "$PID"; rc=$?
if [ "$rc" -eq 0 ]; then
  echo "[run_once] $(date '+%F %H:%M:%S') 完成" >> "$LOG"
  exit 0
else
  echo "[run_once] $(date '+%F %H:%M:%S') 失败退出(rc=$rc，大概率429/网络)，已停止，等待下次定时启动" >> "$LOG"
  exit 3
fi
