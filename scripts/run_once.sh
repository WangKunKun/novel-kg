#!/usr/bin/env bash
# 单次运行管道：LLM 429 限速或其他失败时立即停止（状态已逐章落库，安全断点），
# 不做进程级重试——由 30 分钟定时任务检查后决定是否重新启动。
# 看门狗：超过 55 分钟无新章节落库则杀掉重启。2026-08-29 实测服务降速期
# 单章 18.5min、单次请求可达 20min+（llm_client 超时已放宽到 2400s），
# 看门狗须大于单次超时，否则会把合法慢请求中途误杀造成死亡螺旋。
# 退出码：0=全部完成；3=中途失败/卡死，等待下次启动。
#
# 看门狗两处加固（2026-08-29 僵死 84 分钟未触发复盘）：
# 1. progress() 读库失败返回 ERR 而非 0——旧版 || echo 0 会把"读失败"伪装成
#    "进度=0"，与真实进度 720 不等 → 误判有进展重置计时器，0↔720 震荡永不触发
# 2. 每 5 分钟心跳日志——再看门狗失灵时可直接从日志看到循环内部状态
set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG=/tmp/novel_kg_run2.log
LIMIT=${1:-1617}
DB=data/novel.db
STALL_MINUTES=55

# 强制直连：bigmodel.cn 是国内 API，走系统代理（127.0.0.1:7897）会慢/瞬断
export HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= ALL_PROXY= all_proxy=
export NO_PROXY='*' no_proxy='*'

# 读失败输出 ERR（区别于任何真实进度值，含 0）
progress() { sqlite3 "$DB" "SELECT COALESCE(MAX(chapter),0) FROM extractions;" 2>/dev/null || echo ERR; }

echo "[run_once] $(date '+%F %H:%M:%S') 启动，limit=${LIMIT}（看门狗${STALL_MINUTES}分钟）" >> "$LOG"
python -m novel_kg.cli --novel 玄鉴仙族.txt --schema config/novels/xuanjian.yaml \
    --db "$DB" --model glm-5.3 --limit "$LIMIT" >> "$LOG" 2>&1 &
PID=$!

LAST=$(progress); LAST_AT=$(date +%s); ERR_N=0; HEART=0
while kill -0 "$PID" 2>/dev/null; do
  sleep 60
  CUR=$(progress)
  if [ "$CUR" = "ERR" ]; then
    # 读库失败：不算进展也不崩溃，连续 30 分钟读不到库本身就算僵死
    ERR_N=$((ERR_N + 1))
    CUR=$LAST
  else
    ERR_N=0
  fi
  HEART=$((HEART + 1))
  if [ $((HEART % 5)) -eq 0 ]; then
    echo "[watchdog] $(date '+%H:%M:%S') 心跳：进度=${CUR} 无进展$(( ($(date +%s) - LAST_AT) / 60 ))m 读库失败${ERR_N}次" >> "$LOG"
  fi
  if [ "$CUR" != "$LAST" ]; then
    LAST=$CUR; LAST_AT=$(date +%s)
  elif [ $(( $(date +%s) - LAST_AT )) -gt $(( STALL_MINUTES * 60 )) ] || [ "$ERR_N" -ge 30 ]; then
    echo "[run_once] $(date '+%F %H:%M:%S') 看门狗：${STALL_MINUTES}分钟无进展（卡在${CUR}章，读库失败${ERR_N}次），杀掉重启换连接" >> "$LOG"
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
