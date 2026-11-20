#!/usr/bin/env bash
set -euo pipefail
base_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Portable layout: linux-arm64/launcher.sh and linux-arm64/aiot-launcher/.
# The installer generates this entry with the actual backend/interpreter paths.
backend="${AIOT_LAUNCHER_BACKEND:-$base_dir/aiot-launcher/session_cli.py}"
exec python3 "$backend" --publish-dir "$base_dir/publish" "$@"
