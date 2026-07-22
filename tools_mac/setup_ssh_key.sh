#!/bin/bash
# Setup passwordless SSH from macOS to CyberDog
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/config.sh"

KEY_PATH="${HOME}/.ssh/cyberdog_ed25519"
mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"

if [[ ! -f "$KEY_PATH" ]]; then
  echo "[INFO] Generating SSH key: $KEY_PATH"
  ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -C "cyberdog-mac"
else
  echo "[INFO] SSH key already exists: $KEY_PATH"
fi

[[ ! -f "${KEY_PATH}.pub" ]] && echo "[ERROR] Public key not found" && exit 1

PUB=$(cat "${KEY_PATH}.pub")
ENCODED=$(echo -n "$PUB" | base64)

echo "[INFO] Installing public key on CyberDog. Password may be requested once."
ssh "$DogTarget" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo $ENCODED | base64 -d >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

CONFIG_FILE="${HOME}/.ssh/config"
if [[ -f "$CONFIG_FILE" ]] && grep -q "Host cyberdog-mac" "$CONFIG_FILE"; then
  echo "[INFO] SSH config host already exists: cyberdog-mac"
else
  cat >> "$CONFIG_FILE" << CONF

Host cyberdog-mac
    HostName $DogHost
    User $DogUser
    IdentityFile $KEY_PATH
    IdentitiesOnly yes
CONF
  echo "[INFO] Added SSH config host: cyberdog-mac"
fi

echo "[INFO] Testing passwordless login..."
if ssh -o BatchMode=yes cyberdog-mac "echo key_login_ok" 2>/dev/null; then
  echo "[OK] macOS passwordless SSH is ready."
else
  echo "[ERROR] Passwordless SSH test failed."
  exit 1
fi
