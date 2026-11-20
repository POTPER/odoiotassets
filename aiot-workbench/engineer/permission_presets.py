"""Explicit Linux ownership/mode presets; administrator authorization uses polkit."""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from compat import is_relative_to
from core import SyncError, assert_stopped, operation_lock

PRESETS = {"root": "所有者设为 root:root", "777": "权限设为 777", "root-and-777": "依次设为 root:root 和 777"}


def checked_target(value, expected=None):
    path = Path(value).expanduser().absolute()
    if path.is_symlink() or path.resolve() != path or not path.is_dir():
        raise SyncError("权限目标必须是存在的真实目录，路径不能包含符号链接：" + str(path))
    top = {"/", "/home", "/root", "/tmp", "/var", "/opt", "/srv", "/mnt", "/media"}
    system = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/dev", "/proc", "/sys", "/boot", "/run")
    if (str(path) in top or path == Path.home().resolve() or path.parent == Path("/home")
            or any(is_relative_to(path, Path(p)) for p in system)
            or is_relative_to(Path(__file__).resolve(), path)):
        raise SyncError("不能对系统目录、用户主目录或工具自身执行递归权限预设。")
    if os.path.ismount(path):
        raise SyncError("权限目标不能是挂载点。")
    info = path.stat()
    identity = (info.st_dev, info.st_ino)
    if expected is not None and identity != tuple(expected):
        raise SyncError("授权期间目标目录已被替换，请重新确认权限操作。")
    return path, identity


def commands(target, preset):
    if preset not in PRESETS:
        raise SyncError("未知权限预设。")
    result = []
    if preset in ("root", "root-and-777"):
        # Change links themselves; never follow their targets outside publish.
        result.append(["chown", "-h", "-R", "-P", "--preserve-root", "root:root", "--", str(target)])
    if preset in ("777", "root-and-777"):
        # GNU chmod ignores symlinks encountered during recursive traversal.
        result.append(["chmod", "-R", "--preserve-root", "777", "--", str(target)])
    return result


def command_text(target, preset):
    return "\n".join("sudo " + " ".join(shlex.quote(part) for part in command) for command in commands(target, preset))


def _check_tree(target):
    count = 1
    def failed(exc):
        raise exc
    for root, dirs, files in os.walk(target, followlinks=False, onerror=failed):
        for name in dirs:
            path = Path(root) / name
            if not path.is_symlink() and os.path.ismount(path):
                raise SyncError("目录中有嵌套挂载点，已停止权限操作：" + str(path))
        count += len(dirs) + len(files)
    return count


def apply_as_root(target, preset, expected, caller_pid=None):
    if sys.platform != "linux" or getattr(os, "geteuid", lambda: -1)() != 0:
        raise SyncError("权限预设必须在 Linux 上通过管理员授权执行。")
    path, identity = checked_target(target, expected)
    state = path.parent / (".publish-switcher-" + path.name)
    lock = state / "operation.lock"
    if state.is_symlink() or not state.is_dir() or lock.is_symlink() or not lock.is_file():
        raise SyncError("外部操作锁不存在或无效，请从 Switcher 界面重新执行。")
    with operation_lock(lock):
        if (state / "transaction.json").exists() or (state / "config-transaction.json").exists():
            raise SyncError("有未完成的切换，请先恢复后再执行权限预设。")
        assert_stopped(path, exclude_pids=tuple(p for p in (caller_pid, os.getppid()) if p))
        count = _check_tree(path)
        print("权限预设：{}；目标：{}；约 {} 个文件/目录条目。".format(PRESETS[preset], path, count), flush=True)
        completed = 0
        for command in commands(path, preset):
            checked_target(path, identity)
            print("执行：" + " ".join(shlex.quote(part) for part in command), flush=True)
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode:
                raise SyncError("命令失败（已完成 {} 项，失败命令也可能已部分修改）：{}\n{}".format(
                    completed, command[0], result.stderr.strip() or result.stdout.strip() or "无错误输出"))
            completed += 1
            print(command[0] + " 已完成。", flush=True)
        print("权限预设执行完成。", flush=True)


def launch_preset(engine, preset, log=lambda message: None):
    if sys.platform != "linux":
        raise SyncError("这些权限预设仅支持 Ubuntu/Linux。")
    engine.startup_recover()
    with engine.lock():
        path, identity = checked_target(engine.target)
        commands(path, preset)
    helper = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--target", str(path),
              "--preset", preset, "--device", str(identity[0]), "--inode", str(identity[1]), "--caller-pid", str(os.getpid())]
    if os.geteuid() != 0:
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise SyncError("缺少管理员授权组件 pkexec。联网时运行 bash install.sh，离线时可用 bash install.sh --offline --with-polkit --deb-dir 目录。")
        helper.insert(0, pkexec)
    log("请求管理员授权：" + PRESETS[preset] + "；目标：" + str(path))
    # Authentication belongs to the system agent; passwords never enter this process or logs.
    result = subprocess.run(helper, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        if line.strip():
            log(line)
    if result.returncode == 126:
        raise SyncError("管理员授权已取消，未执行权限预设。")
    if result.returncode == 127:
        raise SyncError("管理员授权失败；请在 Ubuntu 图形桌面确认授权代理正在运行。")
    if result.returncode:
        raise SyncError("权限预设未完成，可能已有部分条目修改；请查看操作日志。")
    return {"target": str(path), "preset": preset}


def main():
    parser = argparse.ArgumentParser(description="Switcher 内部权限预设助手，通过系统管理员授权运行")
    parser.add_argument("--target", required=True)
    parser.add_argument("--preset", choices=tuple(PRESETS), required=True)
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--inode", type=int, required=True)
    parser.add_argument("--caller-pid", type=int, required=True)
    args = parser.parse_args()
    try:
        apply_as_root(args.target, args.preset, (args.device, args.inode), caller_pid=args.caller_pid)
        return 0
    except Exception as exc:
        print("权限操作失败：" + str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
