"""GUI transport: all business operations run behind launcher.sh."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading

from desktop_identity import child_environment


def _close_pipe(stream):
    try:
        stream.close()
    except OSError:
        pass


class LauncherController:
    def __init__(self, publish):
        self.publish = Path(publish).expanduser().absolute()
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.pending_stop = threading.Event()
        self.guard = threading.Lock()
        self.busy = False
        self.thread = None

    def initialize(self):
        return self._start(True)

    def start(self):
        return self._start(False)

    def list_configs(self):
        return self._start(False, ('--list-configs',))

    def replace_config(self, version):
        return self._start(False, ('--replace-config', version))

    def clear_task_data(self):
        return self._start(False, ('--clear-task-data',))

    def stop_existing(self):
        return self._start(False, ('--stop-existing',))

    def request_stop(self):
        with self.guard:
            if not self.stop_event.is_set():
                self.stop_event.set()
                self.pending_stop.set()

    def _start(self, check, extra=()):
        with self.guard:
            if self.busy:
                return False
            self.busy = True
            self.stop_event.clear()
            self.pending_stop.clear()
            self.thread = threading.Thread(target=self._run, args=(check, extra), daemon=False)
            self.thread.start()
            return True

    def command(self, check, extra=()):
        script = self.publish.parent / "launcher.sh"
        if not script.is_file() or script.is_symlink():
            raise RuntimeError("缺少 launcher.sh，请重新运行 install-launcher.sh。")
        if os.name != "posix" or not shutil.which("bash"):
            raise RuntimeError("实际启动需要 Ubuntu 环境。")
        command = [shutil.which("bash"), str(script), "--events-json", "--no-apply-config", "--monitor-existing"]
        if check:
            command.append("--check")
        return command + list(extra)

    def _run(self, check, extra=()):
        process = None
        completed = False
        terminal = None
        try:
            command = self.command(check, extra)
            process = subprocess.Popen(command, cwd=str(self.publish.parent), stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=child_environment(),
                                       encoding="utf-8", errors="replace", start_new_session=(os.name == "posix"))
            errors = []
            def read_errors():
                for line in process.stderr:
                    errors.append(line)
                    if len(errors) > 40:
                        del errors[0]
            reader = threading.Thread(target=read_errors, daemon=True)
            reader.start()
            def stop_when_requested():
                while process.poll() is None:
                    if self.pending_stop.wait(0.1):
                        self.pending_stop.clear()
                        try:
                            # The session owns AIoT cleanup and config restoration.
                            process.stdin.write('stop\n')
                            process.stdin.flush()
                        except (OSError, ValueError):
                            return
            stopper = threading.Thread(target=stop_when_requested, daemon=True)
            stopper.start()
            for line in process.stdout:
                event = json.loads(line)
                if event["event"] in ("ready", "finished"):
                    terminal = (event["event"], event["data"])
                    completed = True
                    _close_pipe(process.stdin)
                else:
                    if event['event'] == 'stop_failed':
                        with self.guard:
                            self.stop_event.clear()
                    self.events.put((event["event"], event["data"]))
            process.wait()
            reader.join(1)
            if not completed:
                raise RuntimeError("启动会话提前结束：" + "".join(errors)[-2000:])
        except Exception as exc:
            if process is not None and process.poll() is None:
                # Closing stdin requests a final cleanup attempt without waiting for a GUI retry.
                _close_pipe(process.stdin)
                process.wait()  # Backend cleans owned processes before exiting.
            if not completed:
                terminal = ("ready" if check else "finished", {
                    "error": str(exc), "returncode": None, "stopped": self.stop_event.is_set(), "logfile": None})
        finally:
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    _close_pipe(stream)
            with self.guard:
                self.busy = False
            if terminal is not None:
                self.events.put(terminal)
