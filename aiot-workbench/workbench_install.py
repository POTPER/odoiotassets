"""Install one desktop entry, keeping the launcher's session wrapper unchanged."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from launcher_install import install, desktop_quote
from launcher_process import install_interpreters
from launcher_runtime import config_directory, load_settings
from launcher_settings_store import read_settings, write_settings
import tool_update

ROOT = Path(__file__).resolve().parent


def install_workbench(publish, config_dir=None, applications=None, desktop_dir=None, shortcut_dir=None):
    config = Path(config_dir) if config_dir is not None else config_directory()
    # install() retains the proven script backup, process checks and interpreter aliases.
    result = install(publish, tool_dir=ROOT / "launcher", config_dir=config,
                     applications=applications, desktop_dir=desktop_dir, shortcut_dir=shortcut_dir)
    settings = config / "settings.json"
    data = read_settings(settings)
    data["target"] = data["publish_dir"]
    data.setdefault("workbench_directory", "aiot-workbench")
    data.pop("program_update_url", None)
    write_settings(settings, data)
    interpreters = install_interpreters(config)
    state = tool_update.update_state(ROOT)
    bootstrap = state / "workbench-bootstrap.py"
    shutil.copyfile(ROOT / "tool_update.py", bootstrap)
    content = ("[Desktop Entry]\nType=Application\nName=AIoT 工作台\nComment=启动 AIoT、查看成果和维护部署\nExec=" +
               " ".join(desktop_quote(arg) for arg in (interpreters["desktop"], bootstrap, "--launch", ROOT)) +
               "\nIcon=" + (ROOT / "launcher/assets/icon.png").as_posix() +
               "\nStartupWMClass=Aiotlauncher\nTerminal=false\nCategories=Utility;\n")
    # The copied installer uses this product's filename, so old projects' entries survive.
    paths = [Path(result["entry"])]
    paths += [Path(folder) / "aiot-workbench.desktop" for folder in (desktop_dir, shortcut_dir) if folder is not None]
    for path in set(paths):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        if sys.platform == "linux" and shutil.which("gio"):
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装 AIoT 工作台，不会启动 AIoT")
    parser.add_argument("publish", nargs="?", help="已有的 publish 目录，缺省读取保存设置")
    options = parser.parse_args(argv)
    target = options.publish or load_settings()["publish_dir"]
    desktop = Path.home() / "Desktop"
    if shutil.which("xdg-user-dir"):
        found = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=False)
        if found.returncode == 0 and found.stdout.strip():
            desktop = Path(found.stdout.strip())
    with tool_update.instance_lock(ROOT):
        tool_update.recover_update(ROOT)
        result = install_workbench(target, desktop_dir=desktop, shortcut_dir=Path.cwd())
    print("已安装：" + result["entry"])
    print("启动命令：python3 workbench.py gui")
    print("工程师面板：Ctrl+Shift+F12；SSH 菜单：python3 workbench.py cli")
    print("桌面提示不可信时，右键快捷方式选择“允许启动”。")
    return 0
