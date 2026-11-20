"""Capture GUI startup failures before Tk or the launcher modules are imported."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import signal
from launcher_process import interpreter_for, set_process_role


def report_failure(logfile):
    message = "启动器未能打开。请查看日志：\n" + str(logfile)
    print(message, file=sys.stderr)
    zenity = shutil.which("zenity")
    notify = shutil.which("notify-send")
    command = ([zenity, "--error", "--title=AIoT 启动器", "--text=" + message] if zenity else
               [notify, "AIoT 启动器", message] if notify else None)
    if command:
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def run_gui(script, args, log_dir):
    script, log_dir = Path(script).resolve(), Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / ("gui-startup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
    with logfile.open("x", encoding="utf-8", buffering=1) as log:
        log.write("Python: " + sys.executable + "\nGUI: " + str(script) + "\n")
        log.write("Bootstrap PID: {}\n".format(os.getpid()))
        log.write("DISPLAY=" + os.environ.get("DISPLAY", "") + "\n")
        log.write("WAYLAND_DISPLAY=" + os.environ.get("WAYLAND_DISPLAY", "") + "\n")
        log.flush()
        try:
            result = subprocess.run([interpreter_for("gui"), "-u", str(script)] + list(args),
                                    cwd=str(script.parent), stdout=log, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONFAULTHANDLER="1"),
                                    check=False)
            code = result.returncode
        except Exception:
            traceback.print_exc(file=log)
            code = 1
        log.write("\nGUI exit code: " + str(code) + "\n")
        if code < 0 and os.name == "posix":
            try:
                reason = signal.Signals(-code).name
            except ValueError:
                reason = str(-code)
            log.write("GUI terminated by signal: " + reason + "\n")
    if code:
        report_failure(logfile)
    return code if code >= 0 else 1


def main(argv=None):
    set_process_role("desktop")
    parser = argparse.ArgumentParser(description="AIoT 启动器桌面入口")
    parser.add_argument("--settings-file")
    options, rest = parser.parse_known_args(argv)
    if options.settings_file:
        settings = Path(options.settings_file).expanduser().absolute()
        log_dir = settings.parent / "logs"
        rest = ["--settings-file", str(settings)] + rest
    else:
        log_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "aiot-launcher/logs"
    try:
        return run_gui(Path(__file__).with_name("aiot_launcher.py"), rest, log_dir)
    except OSError as exc:
        print("无法写入启动日志：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
