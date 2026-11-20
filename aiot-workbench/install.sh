#!/usr/bin/env bash
set -euo pipefail
tool_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
offline=false
cli=false
deb_dir="$tool_dir/debs"
target=()
while (($#)); do
  case "$1" in
    --offline) offline=true ;;
    --cli) cli=true ;;
    --deb-dir) [[ $# -ge 2 ]] || { echo '--deb-dir 需要一个目录' >&2; exit 2; }; deb_dir=$2; shift ;;
    -h|--help) echo '用法：bash install.sh [--offline] [--cli] [--deb-dir 目录] [publish目录]'; exit 0 ;;
    --*) echo "未知选项：$1" >&2; exit 2 ;;
    *) target+=("$1") ;;
  esac
  shift
done
[[ ${#target[@]} -le 1 ]] || { echo '只能指定一个 publish 目录' >&2; exit 2; }
if ! "$cli" && [[ "$(id -u)" -eq 0 ]]; then
  echo '请用桌面登录账户运行安装脚本，不要 sudo 整个脚本；依赖安装会单独请求 sudo。' >&2
  exit 1
fi
required=()
command -v python3 >/dev/null 2>&1 || required+=(python3)
if ! "$cli"; then
  python3 -c 'import tkinter' >/dev/null 2>&1 || required+=(python3-tk)
  python3 -c 'from PIL import Image' >/dev/null 2>&1 || required+=(python3-pil)
  python3 -c 'from PIL import ImageTk' >/dev/null 2>&1 || required+=(python3-pil.imagetk)
  command -v pkexec >/dev/null 2>&1 || { if "$offline"; then required+=(polkit); else required+=(policykit-1); fi; }
fi
if ((${#required[@]})); then
  if "$offline"; then
    bash "$tool_dir/install_offline_debs.sh" "$deb_dir" "${required[@]}"
  else
    sudo apt-get update
    sudo apt-get install -y "${required[@]}"
  fi
fi
python3 -c 'import sys; sys.exit("需要 Python 3.8 或更新版本") if sys.version_info < (3,8) else None'
if "$cli"; then
  echo 'SSH 模式已就绪：python3 workbench.py cli；帮助：python3 workbench.py cli --help'
  exit 0
fi
python3 -c 'import tkinter; from PIL import Image, ImageTk'
exec python3 "$tool_dir/workbench.py" install "${target[@]}"
