#!/bin/bash
# Check connection or open interactive SSH session
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/config.sh"

echo "[INFO] Testing connection to $DogTarget ..."
if ssh -o BatchMode=yes -o ConnectTimeout=5 "$DogTarget" "echo connection_ok" 2>/dev/null; then
  echo "[OK] $DogTarget is reachable."
  if [[ "${1:-}" == "-i" ]]; then
    echo "[INFO] Opening interactive SSH session ..."
    exec ssh -t "$DogTarget" "bash -l"
  fi
else
  echo "[ERROR] Cannot connect to $DogTarget"
  echo "  - Is the robot powered on and connected to Wi-Fi?"
  echo "  - Is $DogHost correct in config.sh?"
  exit 1
fi
