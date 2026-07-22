#!/bin/bash
# Recursive sync .py/.sh/.toml to CyberDog
# Usage:
#   ./push_to_dog.sh                              # interactive menu
#   ./push_to_dog.sh -a                           # push all
#   ./push_to_dog.sh -f perception/camera_view.py # push specific file(s)
#   ./push_to_dog.sh -d perception                # push directory
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/config.sh"
LOCAL_PROGRAM="$(cd "$SCRIPT_DIR/../program" && pwd)"

FILES=()
DIR=""
ALL=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -a|--all)  ALL=true; shift ;;
    -f|--file) FILES+=("$2"); shift 2 ;;
    -d|--dir)  DIR="$2"; shift 2 ;;
    *)         echo "Unknown option: $1"; exit 1 ;;
  esac
done

push_file() {
  local src="$1"
  local rel="${src#"$LOCAL_PROGRAM"/}"
  local remote_path="$RemoteProgramDir/$rel"
  local remote_dir
  remote_dir="$(dirname "$remote_path")"
  echo "[INFO] Copying $rel"
  ssh "$DogTarget" "mkdir -p '$remote_dir'"
  scp "$src" "${DogTarget}:${remote_path}"
  if [[ "$src" == *.sh ]]; then
    ssh "$DogTarget" "chmod +x '$remote_path'"
  fi
}

if $ALL; then
  while IFS= read -r -d '' f; do push_file "$f"; done < <(find "$LOCAL_PROGRAM" -type f \( -name "*.py" -o -name "*.sh" -o -name "*.toml" \) -print0 | sort -z)
elif [[ -n "$DIR" ]]; then
  dir_path="$LOCAL_PROGRAM/$DIR"
  [[ ! -d "$dir_path" ]] && echo "[ERROR] Directory not found: $DIR" && exit 1
  count=0
  while IFS= read -r -d '' f; do push_file "$f"; ((count++)); done < <(find "$dir_path" -type f \( -name "*.py" -o -name "*.sh" -o -name "*.toml" \) -print0 | sort -z)
  [[ $count -eq 0 ]] && echo "[ERROR] No .py/.sh/.toml files in $DIR" && exit 1
elif [[ ${#FILES[@]} -gt 0 ]]; then
  for name in "${FILES[@]}"; do
    [[ "$name" = /* ]] && src="$name" || src="$LOCAL_PROGRAM/$name"
    [[ ! -f "$src" ]] && echo "[ERROR] File not found: $src" && exit 1
    push_file "$src"
  done
else
  mapfile -t available < <(find "$LOCAL_PROGRAM" -type f \( -name "*.py" -o -name "*.sh" -o -name "*.toml" \) | sort)
  echo ""
  for i in "${!available[@]}"; do
    echo "$((i+1))) ${available[$i]#"$LOCAL_PROGRAM"/}"
  done
  echo "a) all"
  echo "q) quit"
  read -rp "Choice: " choice
  [[ "$choice" =~ ^[qQ] ]] && echo "[INFO] Cancelled." && exit 0
  if [[ "$choice" =~ ^(a|all|A|ALL)$ ]]; then
    for f in "${available[@]}"; do push_file "$f"; done
  else
    IFS=',' read -ra indexes <<< "$choice"
    for idx in "${indexes[@]}"; do
      idx="$(echo "$idx" | tr -d ' ')"
      if ! [[ "$idx" =~ ^[0-9]+$ ]] || (( idx < 1 || idx > ${#available[@]} )); then
        echo "[ERROR] Invalid choice: $idx"; exit 1
      fi
      push_file "${available[$((idx-1))]}"
    done
  fi
fi

echo "[OK] Push complete -> $DogTarget:$RemoteProgramDir"
