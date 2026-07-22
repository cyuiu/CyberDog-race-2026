#!/usr/bin/env bash

# 注意：这里不要 set -u，因为 ROS2 setup.bash 在 CyberDog 上可能引用未定义变量。
set +u

source /opt/ros2/galactic/setup.bash >/tmp/run_camera_view_source.log 2>&1 || true
source /opt/ros2/cyberdog/setup.bash >>/tmp/run_camera_view_source.log 2>&1 || true

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///etc/mi/cyclonedds.xml
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0

cd /home/mi/cyberdog_course/program

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
