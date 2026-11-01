#!/bin/bash
# Install Chore Helper as a boot-time systemd service (needs sudo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="$ROOT/deploy/chore-helper.service"
UNIT_DST=/etc/systemd/system/chore-helper.service

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now chore-helper.service
systemctl --no-pager --full status chore-helper.service
