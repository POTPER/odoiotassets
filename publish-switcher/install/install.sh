#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
tool_dir="$script_dir"
if [[ ! -f "$script_dir/switcher.py" && -f "$script_dir/../switcher.py" ]]; then
  tool_dir="$(cd -- "$script_dir/.." && pwd)"
fi
cli=false
offline=false
deb_dir=
with_polkit=false

usage() {
  cat <<'USAGE'
用法：bash install.sh [--cli] [--offline [--deb-dir 目录] [--with-polkit]]
  --cli            只准备命令行模式
  --offline        只使用已安装依赖和本地 .deb，默认目录为工具下的 debs/
  --deb-dir 目录   指定离线 .deb 目录
  --with-polkit    离线安装桌面版时同时补齐管理员授权组件
USAGE
}

while (($#)); do
  case "$1" in
    --cli) cli=true ;;
    --offline) offline=true ;;
    --deb-dir)
      if (($# < 2)) || [[ -z "$2" || "$2" == --* ]]; then
        echo '--deb-dir 需要一个目录。' >&2
        exit 2
      fi
      deb_dir=$2
      shift
      ;;
    --with-polkit) with_polkit=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done
if { [[ -n "$deb_dir" ]] || "$with_polkit"; } && ! "$offline"; then
  echo '--deb-dir 和 --with-polkit 需要配合 --offline 使用。' >&2
  exit 2
fi
if "$cli" && "$with_polkit"; then
  echo '--with-polkit 只用于桌面版安装。' >&2
  exit 2
fi

check_python() {
  python3 -c 'import sys; sys.exit("需要 Python 3.8 或更新版本；当前版本：" + sys.version.split()[0]) if sys.version_info < (3, 8) else None'
}

required=()
if command -v python3 >/dev/null 2>&1; then
  check_python
else
  required+=(python3)
fi
if ! "$cli" && ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  required+=(python3-tk)
fi
if ! "$cli" && ! command -v pkexec >/dev/null 2>&1; then
  if ! "$offline"; then
    required+=(policykit-1)
  elif "$with_polkit"; then
    # Resolve the distribution's package name from the local collection.
    required+=(polkit)
  fi
fi

if "$offline"; then
  echo '离线安装模式。'
  if ((${#required[@]})); then
    bash "$script_dir/install_offline_debs.sh" "${deb_dir:-$tool_dir/debs}" "${required[@]}"
  fi
elif ((${#required[@]})); then
  sudo apt-get update
  sudo apt-get install -y "${required[@]}"
fi

check_python
if "$cli"; then
  echo 'SSH 命令行模式就绪。数字菜单：python3 switcher.py cli；命令帮助：python3 switcher.py --help'
  exit 0
fi
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  echo 'Tkinter 尚不可用。请确认已安装与当前 python3 对应的 python3-tk，或用 --cli 安装命令行版。' >&2
  exit 1
fi
if ! command -v pkexec >/dev/null 2>&1; then
  if "$with_polkit"; then
    echo '未找到 pkexec，请检查离线包中的管理员授权组件。' >&2
    exit 1
  fi
  echo '缺少 pkexec。“辅助工具”中的管理员授权操作需要该组件，可用 --offline --with-polkit 补装。'
fi
# Desktop Exec quoted strings require escaping backslashes, quotes, dollar signs and backticks.
python3 - "$tool_dir" <<'PY'
import os
import pathlib
import shutil
import subprocess
import sys
directory = pathlib.Path(sys.argv[1])
if '\n' in str(directory) or '\r' in str(directory):
    raise SystemExit('工具路径不能包含换行')
def quote(value):
    value = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    return '"' + value + '"'

def entry_value(value):
    # Icon/Path are desktop-entry strings, not shell or Exec arguments.
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

def desktop_directory():
    if shutil.which('xdg-user-dir'):
        try:
            result = subprocess.run(['xdg-user-dir', 'DESKTOP'], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, universal_newlines=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                path = pathlib.Path(result.stdout.strip())
                # XDG returns HOME when the desktop directory is disabled.
                if path.is_absolute() and path.resolve() != pathlib.Path.home().resolve():
                    return path if path.is_dir() else None
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Handle minimal desktops without xdg-user-dirs, including Chinese Ubuntu.
    for name in ('Desktop', '桌面'):
        path = pathlib.Path.home() / name
        if path.is_dir():
            return path
    return None
data_home = pathlib.Path(os.environ.get('XDG_DATA_HOME', pathlib.Path.home() / '.local/share'))
desktop = data_home / 'applications/publish-switcher.desktop'
desktop.parent.mkdir(parents=True, exist_ok=True)
launch = [sys.executable, directory / 'switcher.py', 'gui']
working_directory = directory
helper_source = directory / 'publish_switcher/updates/bootstrap.py'
if not helper_source.is_file():
    helper_source = directory / 'tool_update.py'
if helper_source.is_file():
    # This entry survives a power loss between the two installation renames.
    update_state = directory.parent / ('.' + directory.name + '-updater')
    if update_state.is_symlink():
        raise SystemExit('程序更新目录不能是符号链接')
    update_state.mkdir(exist_ok=True)
    bootstrap = update_state / 'bootstrap.py'
    shutil.copyfile(helper_source, bootstrap)
    launch = [sys.executable, bootstrap, '--launch', directory]
    working_directory = directory.parent
content = ('[Desktop Entry]\nVersion=1.0\nType=Application\nName=swicher\n'
           'Comment=配置与资源管理\nExec=' + ' '.join(quote(arg) for arg in launch) +
           '\nPath=' + entry_value(working_directory) +
           '\nStartupWMClass=PublishSwitcher\nTerminal=false\nCategories=Utility;\n')
icon = directory / 'icons/swicher-256.png'
if icon.is_file():
    content += 'Icon=' + entry_value(icon) + '\n'

desktop.write_text(content, encoding='utf-8')
desktop.chmod(0o755)
print('已安装应用菜单快捷方式：', desktop)
folder = desktop_directory()
if folder is None:
    print('未找到启用的桌面目录；可从应用菜单打开，或将上面的快捷方式复制到桌面。')
else:
    shortcut = folder / 'publish-switcher.desktop'
    try:
        # Replacing the directory entry also handles an old link to another installation.
        temporary = folder / '.publish-switcher.desktop.installing'
        if temporary.is_symlink():
            raise OSError('临时快捷方式路径为符号链接')
        temporary.write_text(content, encoding='utf-8')
        temporary.chmod(0o755)
        temporary.replace(shortcut)
        print('已更新桌面快捷方式：', shortcut)
        trusted = False
        if shutil.which('gio'):
            try:
                result = subprocess.run(['gio', 'set', str(shortcut), 'metadata::trusted', 'true'],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                trusted = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not trusted:
            print('若桌面仍显示文本图标或双击不能启动，请右键该快捷方式选择“允许启动”（或“信任并启动”）。')
    except OSError as exc:
        print('桌面快捷方式更新失败：{}；应用菜单已安装。请检查桌面目录写权限。'.format(exc))
PY
echo '安装完成。也可以运行：python3 switcher.py gui'
