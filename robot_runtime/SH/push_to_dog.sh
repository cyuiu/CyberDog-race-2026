#!/usr/bin/env bash
set -euo pipefail

DOG_HOST="${DOG_HOST:-cyberdog}"
REMOTE_DIR="${REMOTE_DIR:-/home/mi/cyberdog_course/program}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

echo "[INFO] Local dir:  $SCRIPT_DIR"
echo "[INFO] Remote dir: $DOG_HOST:$REMOTE_DIR"

if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$DOG_HOST" "mkdir -p '$REMOTE_DIR'" >/dev/null 2>&1; then
  echo "[ERROR] SSH key login failed. Run setup first or check network/IP."
  exit 1
fi

mapfile -t files < <(find . -maxdepth 1 -type f -name "*.py" -printf "%f\n" | sort)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "[ERROR] No .py files found in $SCRIPT_DIR"
  exit 1
fi

echo
echo "Select Python file to copy:"
echo "0) all .py files"
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

selected=()

if [[ "$choice" == "0" || "$choice" == "all" || "$choice" == "ALL" ]]; then
  for f in "${files[@]}"; do
    selected+=("$SCRIPT_DIR/$f")
  done
elif [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#files[@]} )); then
  selected+=("$SCRIPT_DIR/${files[$((choice - 1))]}")
else
  echo "[ERROR] Invalid choice: $choice"
  exit 1
fi

echo "[INFO] Copying:"
printf "  %s\n" "${selected[@]}"

scp "${selected[@]}" "$DOG_HOST:$REMOTE_DIR/"

echo "[OK] Copy finished."
ssh "$DOG_HOST" "ls -la '$REMOTE_DIR'"
