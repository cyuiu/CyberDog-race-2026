#!/usr/bin/env bash
set -euo pipefail

LOCAL_PORT="${LOCAL_PORT:-18080}"
REMOTE_PORT="${REMOTE_PORT:-8080}"
DURATION="${DURATION:-3600}"
REMOTE_DIR="/home/mi/cyberdog_course/program"
REMOTE_LOG="/tmp/cyberdog_camera_view_start.log"
URL="http://127.0.0.1:${LOCAL_PORT}/"

cleanup() {
  if [[ -n "${REMOTE_PID:-}" ]]; then
    kill "$REMOTE_PID" 2>/dev/null || true
  fi
  if [[ -n "${TUNNEL_PID:-}" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[INFO] 清理旧的相机预览进程"
# 不使用 pkill -f 'python3 camera_view.py'，因为它可能匹配并杀掉远端 ssh shell 自己。
# 这里用 pgrep 的精确模式，并且整个 ssh 命令即使失败也不让本地脚本退出。
ssh cyberdog "pgrep -f 'python3[[:space:]]+camera_view.py' | xargs -r kill 2>/dev/null || true" || true

echo "[INFO] 启动 SSH 隧道: local ${LOCAL_PORT} -> robot ${REMOTE_PORT}"
ssh -o ExitOnForwardFailure=yes -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" cyberdog &
TUNNEL_PID=$!

sleep 1

echo "[INFO] 在机器狗上启动相机预览，远端日志: ${REMOTE_LOG}"
ssh cyberdog "cd ${REMOTE_DIR} && ./run_camera_view.sh --duration ${DURATION} --web-port ${REMOTE_PORT} > ${REMOTE_LOG} 2>&1" &
REMOTE_PID=$!

echo "[INFO] 等待网页服务就绪..."
READY=0
for i in $(seq 1 45); do
  if curl --noproxy "*" -fsS "$URL" >/dev/null 2>&1; then
    READY=1
    echo "[OK] 网页已就绪: $URL"
    break
  fi

  if ! kill -0 "$REMOTE_PID" 2>/dev/null; then
    echo "[ERROR] 远端 camera_view.py 已退出。远端日志如下："
    ssh cyberdog "cat ${REMOTE_LOG} 2>/dev/null || true"
    exit 1
  fi

  if (( i % 5 == 0 )); then
    echo "[INFO] 仍在等待... ${i}s"
    ssh cyberdog "ss -ltnp 2>/dev/null | grep ':${REMOTE_PORT}' || true" || true
  fi

  sleep 1
done

if [[ "$READY" != "1" ]]; then
  echo "[ERROR] 等待网页服务超时: $URL"
  echo "[ERROR] 远端端口状态："
  ssh cyberdog "ss -ltnp 2>/dev/null | grep ':${REMOTE_PORT}' || true"
  echo "[ERROR] 远端日志："
  ssh cyberdog "cat ${REMOTE_LOG} 2>/dev/null || true"
  exit 1
fi

echo "[INFO] 打开浏览器: $URL"
env http_proxy= https_proxy= all_proxy= HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= xdg-open "$URL" >/dev/null 2>&1 || true

echo
echo "[INFO] 相机预览运行中。按 Ctrl-C 停止。"
wait "$REMOTE_PID"
