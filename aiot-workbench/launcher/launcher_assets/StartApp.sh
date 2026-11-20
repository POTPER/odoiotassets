#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export LIBGL_ALWAYS_SOFTWARE=1

case "${1:-}" in
  --managed)
    if [[ "$#" -ne 1 ]]; then
      echo '用法：StartApp.sh [--managed]' >&2
      exit 2
    fi
    cd -- "$app_dir"
    if [[ ! -s ./AIotApp || ! -x ./AIotApp ]]; then
      echo 'AIotApp 不存在、为空或没有执行权限。' >&2
      exit 126
    fi
    exec ./AIotApp
    ;;
  "")
    # Keep the legacy terminal entry, but resolve paths relative to this script.
    cd -- "$app_dir"
    chmod 755 ./AIotApp
    exec gnome-terminal -- bash "$app_dir/StartApp.sh" --managed
    ;;
  *)
    echo '用法：StartApp.sh [--managed]' >&2
    exit 2
    ;;
esac
