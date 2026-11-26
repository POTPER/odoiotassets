#!/usr/bin/env python3
"""IoT Demo 运行器。

读取当前 TrainTaskInfo.json，检查脚本路径与解释器，单任务或顺序运行，日志在 publish 外。
"""
import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

from publish_switcher.sync.engine import Engine, assert_stopped
from publish_switcher.common.errors import SyncError
from publish_switcher.common.diagnostics import default_log_path


class DemoError(SyncError):
    pass


class DemoPreflightError(DemoError):
    """The queue configuration or its launch dependencies need to be refreshed."""


class DemoQueueControl:
    """Bind a skip request to one active module, never to a later queue item."""
    def __init__(self):
        self._lock = threading.Lock()
        self._active = None
        self._skip = None

    def begin(self, task_id):
        with self._lock:
            self._active = str(task_id)
            self._skip = threading.Event()
            return self._skip

    def end(self):
        with self._lock:
            self._active = self._skip = None

    def can_skip(self, task_id):
        with self._lock:
            return self._active == task_id and self._skip is not None and not self._skip.is_set()

    def request_skip(self, task_id):
        with self._lock:
            if self._active != task_id or self._skip is None or self._skip.is_set():
                return False
            self._skip.set()
            return True


def relative_path(value):
    if not isinstance(value, str) or not value.strip():
        raise DemoError("路径为空或不是字符串")
    path = PurePosixPath(value.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in str(path):
        raise DemoError("只允许 IoT 内的相对路径：" + value)
    return path


def within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_iot_task(task):
    # Composite tasks use ScriptFloderPath for OTHER actuators. Never launch those.
    for value in (task.get("PythonScriptPath", ""), task.get("ScriptFloderPath", "")):
        if isinstance(value, str) and any(
                part.strip().replace("\\", "/").startswith("IoT/") for part in value.split("|")):
            return True
    return False


def load_tasks(publish, *, allow_empty=False):
    config = publish / "TrainTaskInfo.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DemoError("无法读取配置 {}：{}".format(config, exc)) from exc
    if not isinstance(data, list) or any(not isinstance(task, dict) for task in data):
        raise DemoError("TrainTaskInfo.json 顶层必须是任务对象数组")
    tasks = [task for task in data if is_iot_task(task)]
    ids = [str(task.get("TrainTaskId", "")) for task in tasks]
    if any(not value or value == "None" for value in ids) or len(set(ids)) != len(ids):
        raise DemoError("IoT 任务的 TrainTaskId 缺失或重复，不能确定运行哪个任务")
    if not tasks and not allow_empty:
        raise DemoError("当前配置没有 IoT 任务；检查 PythonScriptPath 和 ScriptFloderPath")
    return tasks


def resolve_scripts(publish, task):
    iot = (publish / "IoT").resolve()
    raw = task.get("PythonScriptPath")
    if not isinstance(raw, str) or not raw.strip():
        raise DemoError("PythonScriptPath 为空或不是字符串")
    scripts = []
    for value in raw.split("|"):
        relative = relative_path(value)
        if len(relative.parts) == 1:
            # The spelling ScriptFloderPath is defined by the existing project JSON.
            folder = relative_path(task.get("ScriptFloderPath"))
            if "|" in str(folder) or folder.suffix.lower() == ".py":
                raise DemoError("仅文件名的 PythonScriptPath 需要一个目录形式的 ScriptFloderPath")
            relative = folder / relative
        if not relative.parts or relative.parts[0] != "IoT":
            raise DemoError("运行范围仅限 publish/IoT：" + str(relative))
        script = (publish / str(relative)).resolve()
        if not within(script, iot) or not within(iot, publish):
            raise DemoError("脚本路径或符号链接指向 publish/IoT 外：" + str(relative))
        if script.suffix.lower() != ".py":
            raise DemoError("不是 Python 脚本：" + str(relative))
        if not script.is_file():
            raise DemoError("脚本不存在：" + str(script))
        if script.stat().st_size == 0:
            raise DemoError("脚本是零字节占位文件：" + str(script))
        with script.open("rb") as stream:
            stream.read(1)
        if script not in scripts:
            scripts.append(script)
    return scripts


def interpreter(task, override=None):
    value = override or task.get("PythonExePath") or sys.executable
    if not isinstance(value, str) or not value.strip():
        raise DemoError("PythonExePath 无效，请用 --python 指定解释器")
    found = shutil.which(value)
    if not found:
        raise DemoError("Python 解释器不存在或不能执行：{}；可用 --python python3 覆盖".format(value))
    return found


def describe(publish, task, python=None):
    try:
        scripts = resolve_scripts(publish, task)
        executable = interpreter(task, python)
        return scripts, executable, None
    except (DemoError, OSError) as exc:
        return [], None, str(exc)


def task_name(task):
    return " ".join(str(task.get("TrainTaskName", "未命名任务")).split())


def show_tasks(publish, tasks, python=None):
    print("\n配置：{}".format(publish / "TrainTaskInfo.json"))
    print("运行前退出主程序和其他占用同一硬件的 Demo。")
    errors = 0
    for task in tasks:
        scripts, _, error = describe(publish, task, python)
        print("[{}] {}  {}".format(task["TrainTaskId"], task_name(task),
                                   "不可运行：" + error if error else "就绪（{} 个脚本）".format(len(scripts))))
        print("    " + str(task.get("PythonScriptPath", "")))
        errors += bool(error)
    return errors


def stop_processes(processes):
    """Signal only groups created by this invocation; allow Demo cleanup first."""
    def send(sig):
        for process in processes:
            try:
                if os.name == "posix":
                    # The direct child may already have exited, leaving its descendants.
                    os.killpg(process.pid, sig)
                elif process.poll() is None:
                    if sig == signal.SIGINT:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass

    send(signal.SIGINT)
    deadline = time.monotonic() + 4
    while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
        time.sleep(0.05)
    send(signal.SIGTERM)
    deadline = time.monotonic() + 1
    while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
        time.sleep(0.05)
    if os.name == "posix":
        send(signal.SIGKILL)
    for process in processes:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_task(publish, task, log_dir, python=None, cancel=None, output=None, state=None, skip=None, log_event=None,
             on_result=None):
    # Check EVERY configured script before starting any of them.
    scripts = resolve_scripts(publish, task)
    executable = interpreter(task, python)
    if within(log_dir.resolve(), publish):
        raise DemoError("日志目录必须放在 publish 外，避免文件更新覆盖或删除")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    logfile = log_dir / ("iotdemo-" + stamp + ".log")
    output = output or (lambda line: print(line, flush=True))
    def deliver(line, level="info", log_path=None):
        output(line)
        if log_event:
            log_event({"task_id": str(task["TrainTaskId"]), "line": line, "level": level,
                       "log_path": str(log_path) if log_path else None})
    def stopping():
        return (cancel is not None and cancel.is_set()) or (skip is not None and skip.is_set())
    def skipping():
        return skip is not None and skip.is_set() and not (cancel is not None and cancel.is_set())
    deliver("日志：" + str(logfile), log_path=logfile)
    deliver("Ctrl+C 或停止按钮结束本次任务；不会结束其他已存在的程序。")
    processes, readers = [], []
    events = queue.Queue()
    previous_signals = {}
    result = 0
    interrupted = False
    reported = set()

    def notify(script, phase, process=None, error=None):
        if state:
            state({"task_id": str(task["TrainTaskId"]), "script": script.relative_to(publish).as_posix(),
                   "phase": phase, "pid": process.pid if process else None,
                   "exit_code": process.returncode if process else None, "error": error})

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    def read_output(process, label):
        try:
            for line in process.stdout:
                events.put("[{}] {}".format(label, line.rstrip("\r\n")))
        finally:
            process.stdout.close()

    with logfile.open("w", encoding="utf-8", buffering=1) as log:
        def emit(line, level="info"):
            deliver(line, level=level)
            log.write(line + "\n")

        def drain(limit=200):
            for _ in range(limit):
                try:
                    emit(events.get_nowait())
                except queue.Empty:
                    break

        try:
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
                    if sig not in previous_signals:
                        previous_signals[sig] = signal.signal(sig, interrupt)
            emit("开始：{} / {}".format(task["TrainTaskId"], task_name(task)))
            emit("配置：" + str(publish / "TrainTaskInfo.json"))
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            for script in scripts:
                notify(script, "queued")
            for script in scripts:
                if stopping():
                    raise KeyboardInterrupt
                label = script.relative_to(publish).as_posix()
                emit("启动：{} -u {}；工作目录：{}".format(executable, script, script.parent))
                options = {"start_new_session": True} if os.name == "posix" else {
                    "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                try:
                    process = subprocess.Popen([executable, "-u", str(script)], cwd=str(script.parent),
                                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               encoding="utf-8", errors="replace", bufsize=1, **options)
                except OSError as exc:
                    notify(script, "failed", error=str(exc))
                    reported.add(len(processes))
                    raise
                processes.append(process)
                notify(script, "running", process)
                emit("进程：{}；PID {}".format(label, process.pid))
                reader = threading.Thread(target=read_output, args=(process, label), daemon=True)
                readers.append(reader)
                reader.start()
            while True:
                drain()
                if stopping():
                    raise KeyboardInterrupt
                for index, process in enumerate(processes):
                    code = process.poll()
                    if code is not None and index not in reported:
                        notify(scripts[index], "completed" if code == 0 else "failed", process)
                        reported.add(index)
                failed = next((p.returncode for p in processes if p.poll() not in (None, 0)), None)
                if failed is not None:
                    result = failed if failed > 0 else 1
                    emit("脚本异常退出（退出码 {}），停止本次组合的其他脚本。".format(failed), level="error")
                    break
                if all(p.poll() is not None for p in processes):
                    break
                try:
                    emit(events.get(timeout=0.1))
                except queue.Empty:
                    pass
        except KeyboardInterrupt:
            interrupted = True
            result = 130
            emit("收到跳过请求，正在清理当前模块…" if skipping() else "收到停止请求，正在停止本次任务…", level="warning")
        except OSError as exc:
            result = 1
            emit("启动或运行失败：" + str(exc), level="error")
        finally:
            # Ignore repeated interrupt requests while cleanup escalates gracefully.
            cleanup_signals = {}
            if threading.current_thread() is threading.main_thread():
                for sig in set(previous_signals) | {signal.SIGINT}:
                    cleanup_signals[sig] = signal.signal(sig, signal.SIG_IGN)
            try:
                stop_processes(processes)
                for reader in readers:
                    reader.join(timeout=2)
                while not events.empty():
                    drain()
                for script, process in zip(scripts, processes):
                    emit("退出：{}；退出码 {}".format(script.relative_to(publish), process.returncode))
                phase = ("skipped" if skipping() else "stopped") if interrupted else ("failed" if result else "completed")
                for index, script in enumerate(scripts):
                    if index not in reported:
                        if index < len(processes):
                            process = processes[index]
                            script_phase = phase if interrupted else (
                                "completed" if process.returncode == 0 else "stopped" if result else "failed")
                            notify(script, script_phase, process)
                        else:
                            notify(script, "skipped" if phase == "skipped" else "not_started")
                emit("任务结束，结果码 {}".format(result))
            finally:
                for sig, handler in cleanup_signals.items():
                    signal.signal(sig, previous_signals.get(sig, handler))
    if on_result:
        on_result(phase)
    return result


def run_selected(publish, task_id, log_dir, python=None, cancel=None, output=None, state=None, progress=None, log_event=None):
    """Hold the Switcher operation lock until all Demo processes have stopped."""
    publish = Path(publish).expanduser().resolve()
    if not publish.is_dir():
        raise DemoError("publish 目录不存在：" + str(publish))
    engine = Engine(publish)
    logger = logging.getLogger("publish-switcher")
    with engine.lock():
        engine.recover()
        assert_stopped(engine.target)
        tasks = [t for t in load_tasks(engine.target) if str(t["TrainTaskId"]) == str(task_id)]
        if not tasks:
            raise DemoError("当前配置没有这个 IoT 任务编号，请刷新：" + str(task_id))
        logger.info("IoT Demo 开始 target=%s task=%s", engine.target, task_id)
        started = time.monotonic()
        def report(phase):
            if progress:
                progress({"task_id": str(task_id), "index": 1, "total": 1, "phase": phase,
                          "started": started, "elapsed": time.monotonic() - started})
        try:
            options = {"state": state} if state is not None else {}
            if log_event is not None:
                options["log_event"] = log_event
            if progress is not None:
                options["on_result"] = report
            report("running")
            result = run_task(engine.target, tasks[0], Path(log_dir), python=python, cancel=cancel, output=output, **options)
        except Exception:
            report("failed")
            logger.exception("IoT Demo 运行失败")
            raise
        logger.info("IoT Demo 结束 task=%s result=%s log_dir=%s", task_id, result, log_dir)
        return result


def run_many(publish, task_ids, log_dir, python=None, cancel=None, output=None, state=None, expected_tasks=None,
             control=None, progress=None, log_event=None):
    """Run modules in configuration order, waiting for complete cleanup between them."""
    engine = Engine(publish)
    cancel = cancel if cancel is not None else threading.Event()
    control = control if control is not None else DemoQueueControl()
    output = output or (lambda line: print(line, flush=True))
    log_dir = Path(log_dir).expanduser().resolve()
    requested = {str(key) for key in task_ids}
    if not requested:
        raise DemoError("没有可运行的模块。")
    with engine.lock():
        engine.recover()
        assert_stopped(engine.target)
        try:
            tasks = load_tasks(engine.target)
        except DemoError as exc:
            raise DemoPreflightError(str(exc)) from exc
        if expected_tasks is not None and tasks != expected_tasks:
            raise DemoPreflightError("任务配置在检查后发生变化，请刷新模块再运行。")
        selected = [t for t in tasks if str(t["TrainTaskId"]) in requested]
        if {str(t["TrainTaskId"]) for t in selected} != requested:
            raise DemoPreflightError("当前配置中的模块编号已变化，请刷新后重试。")
        if within(log_dir, engine.target):
            raise DemoError("日志目录必须放在 publish 外，避免文件更新覆盖或删除")
        plan = []
        # Preflight the whole queue before executing any module.
        for task in selected:
            try:
                scripts = resolve_scripts(engine.target, task)
                interpreter(task, python)
            except (DemoError, OSError) as exc:
                raise DemoPreflightError("模块 #{} {} 无法启动：{}".format(task["TrainTaskId"], task_name(task), exc)) from exc
            plan.append((task, scripts))
        log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / ("iotdemo-all-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
        output("日志：" + str(logfile))
        if log_event:
            log_event({"task_id": None, "line": "日志：" + str(logfile), "log_path": str(logfile), "level": "info"})
        logger = logging.getLogger("publish-switcher")
        logger.info("IoT 顺序运行 target=%s tasks=%s log=%s", engine.target,
                    [str(t["TrainTaskId"]) for t in selected], logfile)
        with logfile.open("w", encoding="utf-8", buffering=1) as log:
            def emit(line, task_id=None, level="info", module_log_path=None):
                log.write(line + "\n")
                output(line)
                if log_event:
                    log_event({"task_id": task_id, "line": line, "level": level, "module_log_path": module_log_path})

            def report(task, index, phase, started=None):
                if progress:
                    progress({"task_id": str(task["TrainTaskId"]), "index": index + 1, "total": len(plan),
                              "phase": phase, "started": started,
                              "elapsed": time.monotonic() - started if started is not None else 0})

            def notify(task, script, phase, error=None):
                if state:
                    state({"task_id": str(task["TrainTaskId"]), "script": script.relative_to(engine.target).as_posix(),
                           "phase": phase, "pid": None, "exit_code": None, "error": error})

            for task, scripts in plan:
                for script in scripts:
                    notify(task, script, "queued")
            emit("顺序运行：{} 个模块，按当前配置／卡片顺序执行。".format(len(plan)))
            emit("当前模块全部脚本退出并完成清理后再启动下一个；可跳过当前模块，停止全部或异常会取消后续队列。")
            result, next_index = 0, 0
            stopped = False
            try:
                for index, (task, scripts) in enumerate(plan):
                    if cancel.is_set():
                        result, stopped = 130, True
                        break
                    next_index = index + 1
                    key = str(task["TrainTaskId"])
                    skip = control.begin(key)
                    started = time.monotonic()
                    tag = "{} {}".format(task["TrainTaskId"], task_name(task))
                    def tagged(event):
                        emit("[{}] {}".format(tag, event["line"]), key, event.get("level", "info"), event.get("log_path"))
                    def relay(event):
                        if state and event["phase"] != "queued":
                            state(event)
                    phase = "failed"
                    def record_phase(value):
                        nonlocal phase
                        phase = value
                    try:
                        report(task, index, "running", started)
                        emit("队列进度：{}/{}；开始模块 {} / {}".format(index + 1, len(plan), key, task_name(task)), key)
                        # run_task returns only after all its processes/readers are cleaned up.
                        result = run_task(engine.target, task, log_dir, python=python, cancel=cancel,
                                          output=lambda line: None, state=relay, skip=skip, log_event=tagged,
                                          on_result=record_phase)
                    except Exception as exc:
                        for script in scripts:
                            notify(task, script, "failed", str(exc))
                        report(task, index, "failed", started)
                        raise
                    finally:
                        control.end()
                    report(task, index, phase, started)
                    if phase == "skipped":
                        emit("已跳过模块 {} / {}，清理完成，继续后续队列。".format(key, task_name(task)), key, "warning")
                        result = 0
                    if phase == "stopped" or cancel.is_set():
                        result, stopped = 130, True
                    if result != 0:
                        break
                if result == 0 and cancel.is_set():
                    result, stopped = 130, True
            except KeyboardInterrupt:
                result, stopped = 130, True
                cancel.set()
            except BaseException:
                result = 1
                cancel.set()
                raise
            finally:
                reason = "队列已停止，未启动" if stopped else "前一模块异常，未启动" if result else "未启动"
                for index in range(next_index, len(plan)):
                    task, scripts = plan[index]
                    for script in scripts:
                        notify(task, script, "not_started", reason)
                    report(task, index, "not_started")
                emit("顺序运行结束，结果码 {}".format(result))
                logger.info("IoT 顺序运行结束 result=%s log=%s", result, logfile)
            return result


def find_publish(value):
    if value:
        path = Path(value).expanduser().resolve()
    elif (Path.cwd() / "TrainTaskInfo.json").is_file():
        path = Path.cwd().resolve()
    else:
        settings = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "publish-switcher/settings.json"
        try:
            config = json.loads(settings.read_text(encoding="utf-8-sig"))
            target = config.get("target")
            if not isinstance(target, str) or not target.strip():
                raise ValueError("未设置 target")
            path = Path(target).expanduser().resolve()
        except (OSError, ValueError, AttributeError) as exc:
            raise DemoError("请用 --publish 指定 publish 目录；也可在 publish 内运行或沿用 Switcher 的已保存目录") from exc
    if not path.is_dir():
        raise DemoError("publish 目录不存在：" + str(path))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="根据当前 TrainTaskInfo.json 选择运行 IoT Demo；兼容 Python 3.8+。")
    parser.add_argument("--publish", help="publish 目录；默认当前目录或 Switcher 保存的目录")
    parser.add_argument("--task", help="运行指定 TrainTaskId；未指定则进入数字菜单")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--list", action="store_true", help="列出当前配置的 IoT 任务，不运行")
    modes.add_argument("--check", action="store_true", help="检查脚本路径和解释器，不运行；可配合 --task")
    parser.add_argument("--python", help="覆盖 PythonExePath，例如 python3 或虚拟环境解释器路径")
    parser.add_argument("--log-dir", type=Path, default=default_log_path().parent / "iot-demo",
                        help="日志目录，必须在 publish 外；默认 ~/.config/publish-switcher/logs/iot-demo")
    args = parser.parse_args(argv)
    try:
        publish = find_publish(args.publish)
        log_dir = args.log_dir.expanduser().resolve()
        while True:
            tasks = load_tasks(publish)  # Reload after every menu action/config version change.
            if args.task:
                tasks = [t for t in tasks if str(t["TrainTaskId"]) == args.task]
                if not tasks:
                    raise DemoError("当前配置没有这个 IoT 任务编号：" + args.task)
            if args.list or args.check:
                errors = show_tasks(publish, tasks, args.python)
                return 1 if args.check and errors else 0
            if args.task:
                return run_selected(publish, tasks[0]["TrainTaskId"], log_dir, args.python)
            show_tasks(publish, tasks, args.python)
            choice = input("\n输入任务编号运行（r 刷新，0/q 返回）：").strip()
            if choice.lower() in ("0", "q", "quit", "exit"):
                return 0
            if choice.lower() == "r":
                continue
            # Reload again so a configuration changed while the menu was open is used.
            current = [t for t in load_tasks(publish) if str(t["TrainTaskId"]) == choice]
            if not current:
                print("没有这个 IoT 任务编号，请重新选择。")
                continue
            try:
                run_selected(publish, current[0]["TrainTaskId"], log_dir, args.python)
            except (SyncError, OSError) as exc:
                logging.getLogger("publish-switcher").warning("IoT Demo 无法运行：%s", exc)
                print("无法运行：" + str(exc), file=sys.stderr)
    except (SyncError, OSError) as exc:
        logging.getLogger("publish-switcher").error("IoT Demo 错误：%s", exc)
        print("错误：" + str(exc), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
