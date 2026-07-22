#!/bin/bash
# Run Python script on CyberDog with ROS2 environment loaded
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/config.sh"
LOCAL_PROGRAM="$(cd "$SCRIPT_DIR/../program" && pwd)"

SCRIPT_NAME=""
SCRIPT_ARGS=()
PUSH_FIRST=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--script)     SCRIPT_NAME="$2"; shift 2 ;;
    -p|--push-first) PUSH_FIRST=true; shift ;;
    --)              shift; SCRIPT_ARGS=("$@"); break ;;
    *)               SCRIPT_ARGS+=("$1"); shift ;;
  esac
done

if [[ -z "$SCRIPT_NAME" ]]; then
  mapfile -t available < <(find "$LOCAL_PROGRAM" -name "*.py" -type f | sort)
  echo ""
  for i in "${!available[@]}"; do
    echo "$((i+1))) ${available[$i]#"$LOCAL_PROGRAM"/}"
  done
  echo "q) quit"
  read -rp "Choice: " choice
  [[ "$choice" =~ ^[qQ] ]] && echo "[INFO] Cancelled." && exit 0
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#available[@]} )); then
    SCRIPT_NAME="${available[$((choice-1))]#"$LOCAL_PROGRAM"/}"
  else
    echo "[ERROR] Invalid choice"; exit 1
  fi
fi

[[ "$SCRIPT_NAME" = /* ]] && echo "[ERROR] Must be relative to program dir" && exit 1
LOCAL_SCRIPT="$LOCAL_PROGRAM/$SCRIPT_NAME"
[[ ! -f "$LOCAL_SCRIPT" ]] && echo "[ERROR] Not found: $LOCAL_SCRIPT" && exit 1

if $PUSH_FIRST; then
  "$SCRIPT_DIR/push_to_dog.sh" -f "$SCRIPT_NAME"
fi

NO_MOTION="manual_tests/check_status.py|perception/camera_view.py|perception/ball_detect2.py|perception/fisheye_probe.py"
if ! echo "$SCRIPT_NAME" | grep -qE "^($NO_MOTION)$"; then
  echo ""
  echo "[SAFETY] $SCRIPT_NAME may move the robot."
  echo "[SAFETY] Keep the robot on open ground and have APP emergency stop ready."
  read -rp "Continue? [y/N] " confirm
  [[ ! "$confirm" =~ ^[yY]$ ]] && echo "[INFO] Cancelled." && exit 0
fi

echo "[INFO] Running on CyberDog: python3 $SCRIPT_NAME ${SCRIPT_ARGS[*]:-}"

ssh "$DogTarget" bash -s -- "'$RemoteProgramDir'" "'$SCRIPT_NAME'" "${SCRIPT_ARGS[@]}" << 'REMOTE_BOOTSTRAP'
set +u
source /opt/ros2/galactic/setup.bash >/tmp/run_on_dog_source.log 2>&1 || true
source /opt/ros2/cyberdog/setup.bash >>/tmp/run_on_dog_source.log 2>&1 || true
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///etc/mi/cyclonedds.xml
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
program_dir="$1"
script="$2"
shift 2
cd "$program_dir"
echo "[REMOTE] python3 ${script} $*"
python3 "$script" "$@"
REMOTE_BOOTSTRAP
