"""Headless configuration and owned-process lifecycle for the AIoT launcher."""
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

import collection_config
from compat import is_relative_to
from config_versions import activate_version_locked, preview_version
from core import Engine, SyncError, read_json
from desktop_identity import child_environment
from running_aiot import find_running_aiot, owned_group_alive
from launcher_settings_store import read_settings


VERSION = "赛事版本1"
DEFAULT_PUBLISH = "/home/ubuntu/linux-arm64/publish"


def config_directory():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "aiot-workbench"


def load_settings(path=None, *, read_only=False):
    path = Path(path) if path is not None else config_directory() / "settings.json"
    data = read_settings(path, read_only=read_only)
    if data is not None:
        return data
    switcher = path.parent.parent / "publish-switcher" / "settings.json"
    if switcher.is_file():
        data = read_json(switcher)
        if isinstance(data, dict) and isinstance(data.get("target"), str) and data["target"].strip():
            return {"publish_dir": data["target"]}
    from workbench_paths import default_publish
    return {"publish_dir": default_publish()}


def check_installation(target):
    if not target.is_dir():
        raise SyncError("未找到 AIoT 安装目录，请重新运行安装脚本指定目录。")
    for name in ("AIotApp",):
        path = target / name
        if path.is_symlink() or not path.is_file():
            raise SyncError("缺少有效文件：" + name)
        if path.stat().st_size == 0:
            raise SyncError(name + " 是零字节文件，请安装完整程序。")
        if not os.access(path, os.R_OK):
            raise SyncError("无法读取：" + name)
    if os.name == "posix" and not os.access(target / "AIotApp", os.X_OK):
        raise SyncError("AIotApp 没有执行权限，请为该文件添加执行权限。")


def managed_command(target):
    if sys.platform != "linux":
        raise SyncError("实际启动需要在 Ubuntu 设备上运行。")
    return [str(target / "AIotApp")]


def _group_alive(process):
    if os.name != "posix":
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
        return owned_group_alive(process) if sys.platform == 'linux' else True
    except ProcessLookupError:
        return False


def stop_owned_process(process, timeout=5.0):
    """Clean this session's process group, including children left by its leader."""
    def send(sig):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                if sig == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()
        except ProcessLookupError:
            pass

    for sig, wait_seconds in ((signal.SIGTERM, timeout), (getattr(signal, "SIGKILL", signal.SIGTERM), 2.0)):
        if not _group_alive(process):
            break
        send(sig)
        deadline = time.monotonic() + wait_seconds
        while _group_alive(process) and time.monotonic() < deadline:
            time.sleep(0.05)
    if _group_alive(process):
        raise SyncError("AIoT 或本次会话的任务进程仍在运行，请重试停止。")
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired as exc:
        raise SyncError("AIoT 未能结束，请检查设备上的残留进程。") from exc


class SessionController:
    """One worker, one operation lock, and bounded-size GUI notifications."""
    def __init__(self, publish, log_dir=None, stable_seconds=3.0, collection_enabled=False, archive_dir="/home/ubuntu/aiot-archive", exclude_pids=(), apply_config_enabled=False, monitor_existing=False):
        self.publish = Path(publish).expanduser().absolute()
        self.log_dir = Path(log_dir) if log_dir is not None else config_directory() / "logs"
        self.collection_enabled = collection_enabled
        self.apply_config_enabled = apply_config_enabled
        self.monitor_existing = monitor_existing
        self.archive_dir = archive_dir
        self.exclude_pids = exclude_pids
        self.stable_seconds = stable_seconds
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.input_closed = threading.Event()
        self.guard = threading.Lock()
        self.busy = False
        self.thread = None
        self.logfile = None

    def initialize(self):
        return self._start(check_only=True)

    def start(self):
        return self._start(check_only=False)

    def _start(self, check_only):
        with self.guard:
            if self.busy:
                return False
            self.busy = True
            self.stop_event.clear()
            if self.input_closed.is_set():
                self.stop_event.set()
            # Non-daemon: normal application exit must wait for process cleanup.
            self.thread = threading.Thread(target=self._run, args=(check_only,), daemon=False)
            self.thread.start()
            return True

    def request_stop(self):
        self.stop_event.set()

    def close_input(self):
        self.input_closed.set()
        self.request_stop()

    def _finish_run(self, process, engine, result, write):
        group_stopped = process is None
        while True:
            try:
                if not group_stopped:
                    stop_owned_process(process)
                    group_stopped = True
                    result['returncode'] = process.returncode
                collection_config.recover_overlay(engine)
                return
            except Exception as exc:
                try:
                    write(traceback.format_exc())
                except OSError:
                    pass
                self.stop_event.clear()
                if self.input_closed.is_set():
                    raise
                self.events.put(('stop_failed', dict(result, error=str(exc))))
                self.stop_event.wait()
                result['stopped'] = True

    def _observe_existing(self, pids, result, write):
        result['already_running'] = pids
        self.events.put(('external_running', {'pids': pids}))
        write('AIoT 已在其他入口运行，进程：' + ', '.join(str(pid) for pid in pids))
        # This is observation only: no operation lock, recovery, config writes or signals.
        if self.monitor_existing:
            while not self.stop_event.wait(0.5):
                current = find_running_aiot(self.publish, self.exclude_pids)
                if not current:
                    write('已有 AIoT 已退出。')
                    break
                if current != pids:
                    pids = current
                    self.events.put(('external_running', {'pids': pids}))
            result['stopped'] = self.stop_event.is_set()

    def _run(self, check_only):
        result = {"returncode": None, "stopped": False, "error": None, "logfile": None}
        owned_started = False
        try:
            if is_relative_to(self.log_dir.resolve(), self.publish.resolve()):
                raise SyncError("启动日志必须保存在 AIoT 安装目录之外。")
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.logfile = self.log_dir / ("launcher-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
            result["logfile"] = str(self.logfile)
            with self.logfile.open("w", encoding="utf-8", buffering=1) as log:
                def write(message):
                    log.write(str(message) + "\n")

                try:
                    write("后台会话 PID：{}；Python：{}".format(os.getpid(), sys.executable))
                    write("检查：" + str(self.publish))
                    existing = find_running_aiot(self.publish, self.exclude_pids)
                    if existing:
                        self._observe_existing(existing, result, write)
                        return
                    engine = Engine(self.publish)
                    engine.exclude_pids = self.exclude_pids
                    engine.startup_recover()
                    with engine.lock():
                        engine.recover()
                        collection_config.recover_overlay(engine)
                        check_installation(engine.target)
                        engine.preflight()
                        preview = None
                        if self.apply_config_enabled:
                            preview = preview_version(engine, VERSION)
                            if not preview["valid"]:
                                raise SyncError("赛事配置无效：" + "；".join(preview["issues"]))
                        if check_only:
                            return
                        # Validate launch support before replacing any configuration.
                        command = managed_command(engine.target)
                        if self.stop_event.is_set():
                            result["stopped"] = True
                            return
                        if self.apply_config_enabled:
                            self.events.put(("status", "正在配置…"))
                            activate_version_locked(engine, VERSION, preview["snapshot"], log=write)
                        else:
                            write("赛事配置复制已关闭，使用现有配置。")
                        if self.stop_event.is_set():
                            result["stopped"] = True
                            return
                        self.events.put(("status", "正在启动…"))
                        # Check again immediately before spawn while still holding the lock.
                        engine.preflight()
                        check_installation(engine.target)
                        options = {"start_new_session": True} if os.name == "posix" else {
                            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                        process = None
                        try:
                            if self.collection_enabled:
                                collection_config.prepare_overlay(engine, self.archive_dir)
                            else:
                                write("源码收录已关闭。")
                            if self.stop_event.is_set():
                                result["stopped"] = True
                                return
                            log.flush()
                            process = subprocess.Popen(command, cwd=str(engine.target),
                                                       env=dict(child_environment(), LIBGL_ALWAYS_SOFTWARE="1"),
                                                       stdin=subprocess.DEVNULL, stdout=log,
                                                       stderr=subprocess.STDOUT, **options)
                            owned_started = True
                            self.events.put(("started", {"pid": process.pid}))
                            started, stable = time.monotonic(), False
                            while process.poll() is None:
                                if self.stop_event.wait(0.05):
                                    result["stopped"] = True
                                    break
                                if not stable and process.poll() is None and time.monotonic() - started >= self.stable_seconds:
                                    stable = True
                                    self.events.put(("stable", None))
                        finally:
                            self._finish_run(process, engine, result, write)
                        write("AIoT 退出码：" + str(result["returncode"]))
                        if not result["stopped"] and result["returncode"] != 0:
                            raise SyncError("AIoT 已异常退出（退出码 {}），请查看运行日志。".format(result["returncode"]))
                except Exception:
                    # Another entry may have started AIoT after the first check.
                    # Let the lock unwind before observing it; never take ownership.
                    if not owned_started:
                        existing = find_running_aiot(self.publish, self.exclude_pids)
                        if existing:
                            self._observe_existing(existing, result, write)
                            return
                    write(traceback.format_exc())
                    raise
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            with self.guard:
                self.busy = False
            self.events.put(("ready" if check_only else "finished", result))


from gui_session import LauncherController  # GUI only controls the shell session.
