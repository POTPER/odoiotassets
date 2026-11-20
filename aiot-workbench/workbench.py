#!/usr/bin/env python3
"""One entry point and shared backend, with separate launcher/maintenance windows."""
import argparse
import logging
import os
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bootstrap import configure
configure()
from version import VERSION


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print("AIoT Workbench " + VERSION)
        return 0
    if not args:
        args = ["gui"]
    command = args.pop(0)
    if command in ("cli", "engineer", "sync", "check", "list", "config", "logs", "restore", "competition", "assets", "formats", "demo", "diagnose", "self-test"):
        # Separate Tk windows and long-running workers, using the same shared backend.
        from launcher_process import interpreter_for
        child = [interpreter_for("engineer"), str(ROOT / "engineer_entry.py")] + ((args or ["cli"]) if command == "cli" else [command] + args)
        if os.name == "nt":
            return subprocess.call(child)
        os.execv(child[0], child)
    if command == "install":
        from workbench_install import main as install
        return install(args)
    if command == "doctor":
        import aiot_launcher
        return aiot_launcher.main(["--doctor"] + args)
    if command != "gui":
        print("用法：python3 workbench.py [gui | engineer | cli | doctor | install | --version]", file=sys.stderr)
        print("SSH 帮助：python3 workbench.py cli --help", file=sys.stderr)
        return 0 if command in ("-h", "--help") else 2
    if "--desktop" in args:
        args.remove("--desktop")
        from desktop_bootstrap import run_gui
        from launcher_runtime import config_directory
        return run_gui(ROOT / "workbench.py", ["gui"] + args, config_directory() / "logs")
    engineer = "--engineer" in args
    if engineer:
        args.remove("--engineer")
    import aiot_launcher
    import launcher_style
    import tool_update
    from launcher_runtime import config_directory
    from workbench_ui import WorkbenchWindow
    launcher_style.APP_NAME = "AIoT 工作台"
    launcher_style.SIDEBAR_NAME = "AIoT 工作台"
    folder = config_directory() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(handlers=[logging.FileHandler(str(folder / "workbench.log"), encoding="utf-8")],
                        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    WorkbenchWindow.open_engineer_on_start = engineer
    aiot_launcher.LauncherWindow = WorkbenchWindow
    original = aiot_launcher.run_window
    def run_window(options, instance):
        with tool_update.instance_lock(ROOT):
            tool_update.recover_update(ROOT)
            return original(options, instance)
    aiot_launcher.run_window = run_window
    code = aiot_launcher.main(args)
    if WorkbenchWindow.restart_requested:
        os.execv(sys.executable, [sys.executable, str(ROOT / "workbench.py"), "gui"])
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("工作台操作失败")
        raise
