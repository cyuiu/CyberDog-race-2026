#!/usr/bin/env bash
set -euo pipefail

DOG_HOST="${DOG_HOST:-cyberdog}"

if [[ $# -gt 0 ]]; then
  exec ssh "$DOG_HOST" "$@"
fi

exec ssh "$DOG_HOST"
