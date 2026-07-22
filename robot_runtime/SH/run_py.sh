#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source_setup() {
  local setup_file="$1"

  if [[ ! -f "$setup_file" ]]; then
    echo "[WARN] setup file missing: $setup_file"
    return 0
  fi

  set +e
  set +u
  source "$setup_file"
  local rc=$?
  set -u
  set -e

  if [[ $rc -ne 0 ]]; then
    echo "[WARN] source returned $rc: $setup_file"
  fi
}

source_setup /opt/ros2/galactic/setup.bash
source_setup /opt/ros2/cyberdog/setup.bash

mapfile -t files < <(find . -maxdepth 1 -type f -name "*.py" -printf "%f\n" | sort)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "[ERROR] No .py files found in $SCRIPT_DIR"
  exit 1
fi

echo
echo "Select Python file to run:"
for i in "${!files[@]}"; do
  printf "%d) %s\n" "$((i + 1))" "${files[$i]}"
done
echo "q) quit"
echo

read -r -p "Choice: " choice

if [[ "$choice" == "q" || "$choice" == "Q" ]]; then
  echo "[INFO] Cancelled."
  exit 0
fi

if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#files[@]} )); then
  echo "[ERROR] Invalid choice: $choice"
  exit 1
fi

target="${files[$((choice - 1))]}"

case "$target" in
  *check*|*Check*|*status*|*Status*)
    ;;
  *)
    echo
    echo "[SAFETY] This script may move the robot: $target"
    echo "[SAFETY] Make sure the robot is on open ground and APP emergency stop is ready."
    read -r -p "Continue? [y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
      echo "[INFO] Cancelled."
      exit 1
    fi
    ;;
esac

echo "[INFO] Running: python3 $target"
python3 "$target"
