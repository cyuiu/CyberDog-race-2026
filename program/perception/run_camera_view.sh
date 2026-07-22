#!/usr/bin/env bash

# CyberDog 的 ROS2 setup.bash 可能引用未定义变量，因此这里只启用 set -e。
set -e
set +u

source /opt/ros2/galactic/setup.bash >/tmp/run_camera_view_source.log 2>&1 || true
source /opt/ros2/cyberdog/setup.bash >>/tmp/run_camera_view_source.log 2>&1 || true

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///etc/mi/cyclonedds.xml
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ "${1:-}" == "--import-test" ]]; then
  python3 - <<'PY'
import rclpy
import cyberdog_camera
import camera_view
print("remote_import_ok")
PY
  exit 0
fi

exec python3 camera_view.py "$@"
