#!/usr/bin/env python3
"""Linux: place this script beside the new pmdevserver, then run with sudo.

  sudo python3 replace_pmdevserver.py
  sudo python3 replace_pmdevserver.py --service pmdevserver.service --restart
  sudo python3 replace_pmdevserver.py --target /home/server/pmdevserver

By default, stop and replace only. For systemd, supply the actual unit name.
Requires Python 3.8+; uses only the standard library.
"""

import argparse
import datetime
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time


def systemctl(action, service):
    subprocess.run(["systemctl", action, "--", service], check=True, timeout=60)


def process_token(pid, identity):
    """Return process start time only if its executable is the old target."""
    try:
        exe = Path("/proc") / str(pid) / "exe"
        info = exe.stat()
        if (info.st_dev, info.st_ino) != identity:
            return None
        # The command name may contain spaces or parentheses.
        fields = (exe.parent / "stat").read_text().rsplit(")", 1)[1].split()
        return fields[19]  # Linux /proc stat field 22: starttime
    except (FileNotFoundError, ProcessLookupError):
        return None


def matching_processes(identity):
    result = {}
    for item in Path("/proc").iterdir():
        if item.name.isdigit():
            pid = int(item.name)
            token = process_token(pid, identity)
            if token is not None:
                result[pid] = token
    return result


def send_signal(processes, identity, sig):
    for pid, token in processes.items():
        # Recheck executable and start time to avoid signaling a reused PID.
        if process_token(pid, identity) == token:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass


def stop_processes(identity, timeout):
    processes = matching_processes(identity)
    if processes:
        print("停止进程：", ", ".join(map(str, processes)))
        send_signal(processes, identity, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while matching_processes(identity) and time.monotonic() < deadline:
            time.sleep(0.2)
        remaining = matching_processes(identity)
        if remaining:
            print("等待超时，强制结束剩余进程。")
            send_signal(remaining, identity, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while matching_processes(identity) and time.monotonic() < deadline:
                time.sleep(0.2)
    # Catch immediate supervisor restarts before changing the file.
    time.sleep(1)
    if matching_processes(identity):
        raise RuntimeError("进程仍在运行或被自动拉起。请停止守护程序，或用 --service 指定 systemd 服务。")


def main():
    parser = argparse.ArgumentParser(description="停止并替换 /home/server/pmdevserver；默认不重新启动。")
    parser.add_argument("--target", type=Path, default=Path("/home/server/pmdevserver"),
                        help="服务器上旧可执行文件的完整路径")
    parser.add_argument("--service", help="实际的 systemd 服务名称（如 pmdevserver.service）")
    parser.add_argument("--restart", action="store_true", help="替换后启动指定的 systemd 服务，需配合 --service")
    parser.add_argument("--timeout", type=float, default=15, help="强制结束前等待秒数，默认 15")
    args = parser.parse_args()
    if args.restart and not args.service:
        parser.error("--restart 必须配合 --service 使用")
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout 必须为有限的正数")
    if not sys.platform.startswith("linux"):
        raise RuntimeError("请在 Linux 服务器上运行此脚本。")
    if os.geteuid() != 0:
        raise RuntimeError("请使用 sudo python3 replace_pmdevserver.py 运行。")

    source = Path(__file__).resolve().parent / "pmdevserver"
    target = args.target.absolute()
    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError("脚本所在文件夹中缺少非空的新 pmdevserver 文件。")
    if target.is_symlink() or not target.is_file():
        raise RuntimeError("目标必须是已存在的普通文件，且不能是符号链接：" + str(target))
    if os.path.samefile(source, target):
        raise RuntimeError("新文件与目标文件相同。请把脚本和新文件放到单独的更新文件夹。")
    with source.open("rb") as handle:
        if handle.read(4) != b"\x7fELF":
            raise RuntimeError("新文件不是 Linux ELF 可执行文件。")

    old = target.stat()
    identity = (old.st_dev, old.st_ino)
    temporary = None
    backup = None
    try:
        # Prepare everything before stopping the running program.
        fd, name = tempfile.mkstemp(prefix=".pmdevserver-new-", dir=str(target.parent))
        temporary = Path(name)
        with os.fdopen(fd, "wb") as destination, source.open("rb") as original:
            shutil.copyfileobj(original, destination)
            destination.flush()
            os.fsync(destination.fileno())
        os.chown(temporary, old.st_uid, old.st_gid)
        os.chmod(temporary, stat.S_IMODE(old.st_mode) | stat.S_IXUSR)

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = target.with_name(target.name + ".bak." + stamp)
        with backup.open("xb") as destination, target.open("rb") as original:
            shutil.copyfileobj(original, destination)
            destination.flush()
            os.fsync(destination.fileno())
        shutil.copystat(target, backup)
        os.chown(backup, old.st_uid, old.st_gid)
        print("旧文件已备份：", backup, flush=True)

        if args.service:
            systemctl("stop", args.service)
        stop_processes(identity, args.timeout)
        if (target.stat().st_dev, target.stat().st_ino) != identity:
            raise RuntimeError("目标文件已被其他程序修改，已取消替换。")
        # Same-directory rename atomically replaces the executable.
        os.replace(temporary, target)
        temporary = None
        print("替换完成：", target, flush=True)
        if args.restart:
            systemctl("start", args.service)
            systemctl("is-active", args.service)
            print("服务已启动。")
        else:
            print("服务已停止；未自动启动。")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("操作失败：{}\n若服务已经停止，请检查后手动恢复；旧文件备份保留在目标目录。".format(error),
              file=sys.stderr)
        sys.exit(1)
