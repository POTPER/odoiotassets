"""工具自身安装助手（独立于包内代码）。

GUI 退出后由外部进程执行：整目录备份、切换到已校验的新版本、失败回滚并重启。
故意留在安装根目录，以便替换程序目录时仍能运行。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class UpdateError(RuntimeError):
    """工具目录切换或恢复失败。"""


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def save_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def update_state(install):
    install = Path(install).absolute()
    if install.is_symlink() or install == install.parent:
        raise UpdateError("程序安装目录不能是符号链接或文件系统根目录。")
    state = install.parent / ("." + install.name + "-updater")
    if state.is_symlink():
        raise UpdateError("程序更新目录不能是符号链接。")
    state.mkdir(exist_ok=True)
    return state


@contextmanager
def instance_lock(install, timeout=0):
    """Every GUI instance and the external update helper use the same lock."""
    path = update_state(install) / "instance.lock"
    deadline = time.monotonic() + timeout
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise UpdateError("另一个 Switcher 窗口或程序更新正在运行，请先关闭其他窗口。") from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def pending_paths(install):
    state = update_state(install)
    record = read_json(state / "pending.json")
    for key in ("stage", "backup"):
        if not re.fullmatch(key + r"-[0-9a-f]{32}", record.get(key, "")):
            raise UpdateError("程序更新恢复记录路径无效。")
        if (state / record[key]).is_symlink():
            raise UpdateError("程序更新目录不能是符号链接。")
    return state, record, state / record["stage"], state / record["backup"]


def recover_update(install):
    install = Path(install).absolute()
    state = update_state(install)
    if not (state / "pending.json").exists():
        return
    state, record, stage, backup = pending_paths(install)
    if record["phase"] != "committed" and backup.is_dir():
        if install.exists():
            os.replace(install, state / ("failed-" + uuid.uuid4().hex))
        os.replace(backup, install)
        sync_directory(install.parent)
        sync_directory(state)
    if not install.is_dir():
        raise UpdateError("程序更新恢复失败，请从完整安装包恢复工具目录。")
    if stage.is_dir():
        shutil.rmtree(stage)
    (state / "pending.json").unlink()


def commit_update(install):
    install = Path(install).absolute()
    state, record, stage, backup = pending_paths(install)
    if record["phase"] != "prepared" or not stage.is_dir():
        raise UpdateError("程序更新准备记录无效。")
    try:
        os.replace(install, backup)
        sync_directory(install.parent)
        sync_directory(state)
        record["phase"] = "backed_up"
        save_json(state / "pending.json", record)
        os.replace(stage, install)
        sync_directory(install.parent)
        sync_directory(state)
        probe = subprocess.run([sys.executable, "-B", str(install / "switcher.py"), "--version"],
                               cwd=str(install.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               encoding="utf-8", errors="replace", timeout=30)
        if probe.returncode or probe.stdout.strip() != "Publish Switcher " + record["version"]:
            raise UpdateError("新版启动校验失败：" + probe.stderr[-2000:])
        record["phase"] = "committed"
        save_json(state / "pending.json", record)
        save_json(state / "last-update.json", {"version": record["version"], "backup": str(backup), "error": None})
        (state / "pending.json").unlink()
    except BaseException as exc:
        recover_update(install)
        save_json(state / "last-update.json", {"error": str(exc)})
        raise


def launch_update_helper(install, engineer=False, *, startup=False):
    state = update_state(install)
    helper = state / "apply-update.py"
    shutil.copyfile(Path(__file__), helper)
    command = [sys.executable, "-B", str(helper), "--apply", str(Path(install).absolute())]
    if engineer:
        command.append("--engineer")
    if startup:
        command.append("--resume-startup-update")
    options = {"start_new_session": True} if os.name == "posix" else {"creationflags": subprocess.CREATE_NO_WINDOW}
    with (state / "helper.log").open("a", encoding="utf-8") as log:
        return subprocess.Popen(command, cwd=str(state), stdout=log, stderr=log, **options)


def helper_main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply")
    action.add_argument("--launch")
    parser.add_argument("--engineer", action="store_true")
    parser.add_argument("--resume-startup-update", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    install = Path(args.apply or args.launch)
    with instance_lock(install, timeout=90):
        if args.launch:
            recover_update(install)
        else:
            error = None
            try:
                commit_update(install)
            except Exception as exc:
                error = str(exc)
                print(str(exc), file=sys.stderr, flush=True)
            # The publish deployment is independent and remains committed on tool failure.
            summary = update_state(install) / "combined-update.json"
            if summary.exists():
                try:
                    result = read_json(summary)
                    if result.get("phase") == "restarting":
                        result.update(program="更新失败，已恢复旧版" if error else "更新成功",
                                      success=not bool(error), restart=False,
                                      phase="failed" if error else "complete")
                        if error:
                            result["error"] = error
                        save_json(summary, result)
                except (OSError, ValueError, TypeError):
                    print("无法保存组合更新结果，请查看 last-update.json 和 helper.log。", file=sys.stderr, flush=True)
    command = [sys.executable, str(install / "switcher.py"), "gui"]
    if args.engineer:
        command.append("--engineer")
    if args.apply and args.resume_startup_update:
        command.append("--resume-startup-update")
    os.chdir(install)
    os.execv(sys.executable, command)


def __getattr__(name):
    # Compatibility for callers of the updater before the package split.
    if name in {
        "DEFAULT_UPDATE_URL", "REQUIRED_FILES", "check_release", "https_url", "mirror_locations",
        "package_version", "prepare_offline", "prepare_online", "prepare_package", "remember_release",
        "remote_file", "validate_release", "version_number",
    }:
        from publish_switcher.updates import release
        return getattr(release, name)
    raise AttributeError(name)


if __name__ == "__main__":
    helper_main()
elif __name__ == "tool_update":
    # The generated root entry shares the same API and exception types as the package.
    from publish_switcher.updates import bootstrap
    sys.modules[__name__] = bootstrap
