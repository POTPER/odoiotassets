"""Install per-user desktop entries and launcher.sh, without launching."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys
import uuid

from compat import is_relative_to
from core import Engine, SyncError, assert_stopped, fsync_dir
from launcher_runtime import config_directory, load_settings
from launcher_preferences import preferences
from launcher_process import install_interpreters
from launcher_settings_store import read_settings, write_settings


def desktop_quote(value):
    value = str(value)
    if "\n" in value or "\r" in value or "\x00" in value:
        raise SyncError("快捷方式路径不能包含换行或空字符。")
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("`", "\\`"), ("$", "\\$"), ("%", "%%")):
        value = value.replace(old, new)
    return '"' + value + '"'


def render_launcher(tool_dir, engine_target_name="publish", settings_path=None, interpreter=None):
    command = [interpreter or sys.executable, str(Path(tool_dir).resolve() / "session_cli.py")]
    if settings_path is not None:
        command += ["--settings-file", str(Path(settings_path).absolute())]
    return ('#!/usr/bin/env bash\nset -euo pipefail\n'
            'base_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
            'exec ' + ' '.join(shlex.quote(arg) for arg in command) +
            ' --publish-dir "$base_dir"/' + shlex.quote(engine_target_name) + ' "$@"\n')


def install(publish, tool_dir=None, config_dir=None, applications=None, desktop_dir=None, shortcut_dir=None, basic=False):
    tool_dir = Path(tool_dir) if tool_dir is not None else Path(__file__).resolve().parent
    config_dir = Path(config_dir) if config_dir is not None else config_directory()
    applications = Path(applications) if applications is not None else Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    target = Path(publish).expanduser().absolute()
    if not target.is_dir() or target.is_symlink():
        raise SyncError("请指定已有的普通 publish 目录。")
    for folder in (tool_dir, config_dir, applications, desktop_dir, shortcut_dir):
        if folder is not None and is_relative_to(Path(folder).resolve(), target.resolve()):
            raise SyncError("启动器、设置和快捷方式必须放在 publish 外。")
    settings_path = config_dir / "settings.json"
    engine = Engine(target)
    engine.startup_recover()
    backup = None
    with engine.lock():
        engine.recover()
        assert_stopped(engine.target)
        settings = read_settings(settings_path, default={'publish_dir': str(engine.target)})
        interpreters = install_interpreters(config_dir)
        template = render_launcher(tool_dir, engine_target_name=target.name, settings_path=settings_path,
                                   interpreter=interpreters["session"]).encode("utf-8")
        content = ("[Desktop Entry]\nType=Application\nName=2026金砖赛事\\n物联传感技术应用\n"
                   "Comment=启动或关闭物联传感技术应用 AIoT 软件\nExec=" + desktop_quote(interpreters["desktop"]) + " " +
                   desktop_quote((tool_dir / "desktop_bootstrap.py").resolve()) + " --settings-file " +
                   desktop_quote(settings_path.absolute()) + "\nIcon=" +
                   (tool_dir / "assets/icon.png").resolve().as_posix() +
                   "\nStartupWMClass=Aiotlauncher\nTerminal=false\nCategories=Utility;\n")
        script = engine.target.parent / "launcher.sh"
        if script.is_symlink() or (script.exists() and not script.is_file()):
            raise SyncError("launcher.sh 必须是普通文件。")
        if script.exists() and script.read_bytes() != template:
            backups = engine.state / "launcher-script-backups"
            if backups.is_symlink():
                raise SyncError("启动脚本备份目录不能是符号链接。")
            backups.mkdir(exist_ok=True)
            backup = backups / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-launcher.sh")
            shutil.copy2(script, backup)
        temp = script.with_name(".launcher.sh-" + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("xb") as stream:
                stream.write(template)
                stream.flush()
                os.fchmod(stream.fileno(), 0o755) if os.name == "posix" else os.chmod(temp, 0o755)
                os.fsync(stream.fileno())
            os.replace(temp, script)
            fsync_dir(script.parent)
        finally:
            temp.unlink(missing_ok=True)
        executable = engine.target / "AIotApp"
        if os.name == "posix" and executable.is_file() and not executable.is_symlink() and not os.access(executable, os.X_OK):
            executable.chmod(stat.S_IMODE(executable.stat().st_mode) | stat.S_IXUSR)
        settings.update(publish_dir=str(engine.target))
        settings.setdefault("apply_config_enabled", False)
        settings.setdefault("collection_enabled", False)
        if basic:
            settings.update(apply_config_enabled=False, collection_enabled=False)
        settings.setdefault("archive_dir", "/home/ubuntu/aiot-archive")
        folder, theme = preferences(settings)
        settings["results_dir"] = str(folder)
        settings.setdefault("theme", theme)
        settings.setdefault("submission_enabled", False)
        settings.setdefault("submission_dir", "")
        write_settings(settings_path, settings)
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / "aiot-workbench.desktop"
    entry.write_text(content, encoding="utf-8")
    entry.chmod(0o755)
    written = {entry.resolve()}
    for folder in (desktop_dir, shortcut_dir):
        if folder is None:
            continue
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        shortcut = folder / "aiot-workbench.desktop"
        if shortcut.resolve() in written:
            continue
        shortcut.write_text(content, encoding="utf-8")
        shortcut.chmod(0o755)
        written.add(shortcut.resolve())
        if sys.platform == "linux" and shutil.which("gio"):
            # Some desktop environments require the user to choose "Allow Launching".
            subprocess.run(["gio", "set", str(shortcut), "metadata::trusted", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return {"entry": str(entry), "backup": str(backup) if backup else None,
            "script": str(script),
            "local_entry": str(Path(shortcut_dir) / "aiot-workbench.desktop") if shortcut_dir is not None else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装2026金砖赛事 物联传感技术应用启动器")
    parser.add_argument("publish", nargs="?", help="实际 publish 目录，缺省沿用保存的目录")
    parser.add_argument("--basic", action="store_true", help="关闭已保存的赛事配置复制和源码收录，仅测试启动与退出")
    args = parser.parse_args(argv)
    try:
        target = args.publish or load_settings()["publish_dir"]
        desktop = Path.home() / "Desktop"
        if shutil.which("xdg-user-dir"):
            found = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=False)
            if found.returncode == 0 and found.stdout.strip():
                desktop = Path(found.stdout.strip())
        result = install(target, desktop_dir=desktop, shortcut_dir=Path.cwd(), basic=args.basic)
    except (OSError, ValueError, SyncError) as exc:
        print("安装失败：" + str(exc), file=sys.stderr)
        return 1
    print("已安装：" + result["entry"])
    print("AIoT 启动入口：" + result["script"])
    print("启动器窗口日志：" + str(config_directory() / "logs/gui-startup-*.log"))
    if result["local_entry"]:
        print("当前目录快捷方式：" + result["local_entry"])
    if result["backup"]:
        print("原启动脚本已备份：" + result["backup"])
    print("可在当前目录、应用菜单或桌面打开“2026金砖赛事 物联传感技术应用”。提示时请选择“允许启动”。")
    print("安装不会启动 AIoT；打开启动器后点击“启动”。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
