#!/bin/bash
# Start remote camera preview from CyberDog
# Usage:
#   ./start_camera_view.sh                  # RGB camera
#   ./start_camera_view.sh --source fisheye # Dual fisheye
#   ./start_camera_view.sh -p               # push files first
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/config.sh"

SOURCE="rgb"
PUSH_FIRST=false
REMOTE_PID_FILE="/tmp/cyberdog_camera_remote.pid"
REMOTE_TAILWIND_PID_FILE="/tmp/cyberdog_camera_tailwind.pid"
REMOTE_LOG_FILE="/tmp/camera_view_remote.log"
REMOTE_TAILWIND_LOG_FILE="/tmp/camera_view_tailwind.log"
REMOTE_VIEW_PORT=8080

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--source)      SOURCE="$2"; shift 2 ;;
    -p|--push-first)  PUSH_FIRST=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

case "$SOURCE" in
  rgb)
    REMOTE_SCRIPT="program/perception/run_camera_view.sh"
    REMOTE_RUN_DIR="program/perception"
    REMOTE_RUN_CMD="./run_camera_view.sh"
    ;;
  fisheye)
    REMOTE_SCRIPT="program/perception/fisheye_probe.py"
    REMOTE_RUN_DIR="program/perception"
    REMOTE_RUN_CMD="python3 fisheye_probe.py"
    ;;
  *)
    echo "[ERROR] Unknown camera source: $SOURCE (supported: rgb, fisheye)"
    exit 1
    ;;
esac

if $PUSH_FIRST; then
  echo "[INFO] Pushing files to CyberDog..."
  "$SCRIPT_DIR/push_to_dog.sh" -f "$REMOTE_SCRIPT" || { echo "[ERROR] Push failed."; exit 1; }
fi

cleanup() {
  echo ""
  echo "[INFO] Cleaning up..."
  pkill -f "ssh.*-L.*$REMOTE_VIEW_PORT" 2>/dev/null || true
  ssh "$DogTarget" "kill $(cat $REMOTE_PID_FILE 2>/dev/null) 2>/dev/null; rm -f $REMOTE_PID_FILE" 2>/dev/null || true
  if [[ "$SOURCE" == "fisheye" ]]; then
    ssh "$DogTarget" "kill $(cat $REMOTE_TAILWIND_PID_FILE 2>/dev/null) 2>/dev/null; rm -f $REMOTE_TAILWIND_PID_FILE" 2>/dev/null || true
  fi
  echo "[INFO] Stopped."
}
trap cleanup EXIT INT TERM

echo "[INFO] Cleaning up previous camera processes..."
ssh "$DogTarget" "kill $(cat $REMOTE_PID_FILE 2>/dev/null) 2>/dev/null; rm -f $REMOTE_PID_FILE" 2>/dev/null || true
if [[ "$SOURCE" == "fisheye" ]]; then
  ssh "$DogTarget" "kill $(cat $REMOTE_TAILWIND_PID_FILE 2>/dev/null) 2>/dev/null; rm -f $REMOTE_TAILWIND_PID_FILE" 2>/dev/null || true
fi
pkill -f "ssh.*$REMOTE_VIEW_PORT" 2>/dev/null || true

echo "[INFO] Starting SSH tunnel (localhost:$REMOTE_VIEW_PORT -> CyberDog:$REMOTE_VIEW_PORT) ..."
ssh -f -N -L "$REMOTE_VIEW_PORT:localhost:$REMOTE_VIEW_PORT" "$DogTarget"
sleep 1
LOCAL_TUNNEL_PID=$(pgrep -f "ssh.*-L.*$REMOTE_VIEW_PORT.*$DogTarget" | head -1 || true)
[[ -z "$LOCAL_TUNNEL_PID" ]] && echo "[ERROR] Failed to start SSH tunnel." && exit 1
echo "[INFO] SSH tunnel running (PID: $LOCAL_TUNNEL_PID)"

echo "[INFO] Starting camera service on CyberDog (source=$SOURCE) ..."
if [[ "$SOURCE" == "rgb" ]]; then
  ssh "$DogTarget" "cd '$REMOTE_RUN_DIR' && nohup bash '$REMOTE_RUN_CMD' > $REMOTE_LOG_FILE 2>&1 & echo \$! > $REMOTE_PID_FILE"
else
  ssh "$DogTarget" "cd '$REMOTE_RUN_DIR' && nohup python3 -m http.server $REMOTE_VIEW_PORT > $REMOTE_TAILWIND_LOG_FILE 2>&1 & echo \$! > $REMOTE_TAILWIND_PID_FILE && nohup $REMOTE_RUN_CMD > $REMOTE_LOG_FILE 2>&1 & echo \$! > $REMOTE_PID_FILE"
fi

echo "[INFO] Waiting for camera service..."
for i in $(seq 1 30); do
  curl -s "http://localhost:$REMOTE_VIEW_PORT" > /dev/null 2>&1 && echo "[INFO] Camera service ready." && break
  sleep 1
done

echo "[INFO] Opening browser..."
open "http://localhost:$REMOTE_VIEW_PORT"

echo ""
echo "[INFO] Camera preview running. Press Ctrl+C to stop."
wait
