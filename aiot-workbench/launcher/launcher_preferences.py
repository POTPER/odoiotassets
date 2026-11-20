"""Per-user appearance and results folder; no AIoT task configuration changes."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

from core import SyncError
from launcher_settings_store import read_settings, write_settings


def desktop_directory():
    command = shutil.which("xdg-user-dir") if sys.platform == "linux" else None
    if command:
        try:
            result = subprocess.run([command, "DESKTOP"], capture_output=True, text=True, timeout=3, check=False)
            path = Path(result.stdout.strip()).expanduser()
            if result.returncode == 0 and result.stdout.strip() and path.is_absolute():
                return path
        except (OSError, subprocess.TimeoutExpired):
            pass
    home = Path.home()
    return home / "桌面" if (home / "桌面").is_dir() and not (home / "Desktop").is_dir() else home / "Desktop"


def preferences(settings):
    value = settings.get("results_dir")
    folder = Path(value).expanduser() if isinstance(value, str) and value.strip() else None
    if folder is None or not folder.is_absolute():
        folder = desktop_directory() / "成果输出"
    elif folder.name == "成果输出文件夹" and folder == desktop_directory() / "成果输出文件夹":
        # Correct the previous default without changing unrelated custom locations.
        folder = folder.with_name("成果输出")
    theme = settings.get("theme", "dark")
    return folder, theme if theme in ("dark", "light") else "dark"


def save_preferences(path, publish_dir, results_dir, theme, submission_enabled=None, submission_dir=None):
    if not isinstance(results_dir, str) or not results_dir.strip() or "\x00" in results_dir:
        raise SyncError("请选择成果文件夹。")
    folder = Path(results_dir).expanduser()
    if not folder.is_absolute():
        raise SyncError("成果文件夹必须为绝对路径。")
    if folder.exists() and not folder.is_dir():
        raise SyncError("成果路径指向文件，请选择文件夹。")
    if theme not in ("dark", "light"):
        raise SyncError("请选择深色或浅色主题。")
    path = Path(path)
    data = read_settings(path, default={'publish_dir': str(publish_dir)})
    if not isinstance(data, dict):
        raise SyncError("启动器设置格式无效。")
    enabled = data.get("submission_enabled", False) if submission_enabled is None else submission_enabled
    destination = data.get("submission_dir", "") if submission_dir is None else submission_dir
    if not isinstance(enabled, bool):
        raise SyncError("成果提交开关必须为布尔值。")
    if not isinstance(destination, str):
        raise SyncError("提交目标文件夹设置无效。")
    if enabled:
        from results_files import validate_submission_directories
        destination = str(validate_submission_directories(folder, destination, publish_dir=publish_dir))
        if data.get('publish_dir') != str(publish_dir):
            destination = str(validate_submission_directories(folder, destination, publish_dir=data.get('publish_dir')))
    data.setdefault("publish_dir", str(publish_dir))
    data.update(results_dir=str(folder), theme=theme, submission_enabled=enabled, submission_dir=destination)
    write_settings(path, data)
    return data


def open_results_directory(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(folder))
        return
    if sys.platform == "darwin":
        command = ["open", str(folder)]
    elif shutil.which("xdg-open"):
        command = [shutil.which("xdg-open"), str(folder)]
    elif shutil.which("gio"):
        command = [shutil.which("gio"), "open", str(folder)]
    else:
        raise SyncError("找不到文件管理器入口，请安装 xdg-utils。")
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        raise SyncError("无法打开成果文件夹：" + (result.stderr.strip() or str(folder)))
