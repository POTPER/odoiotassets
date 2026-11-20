import ast
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import iot_runner as iotdemo


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        if temp_root:
            temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.publish = self.base / "publish"
        self.publish.mkdir()
        self.logs = self.base / "logs"
        self.task = {"TrainTaskId": 2, "TrainTaskName": "蜂鸣器\n模块", "PythonExePath": sys.executable,
                     "ScriptFloderPath": "IoT/模块", "PythonScriptPath": "demo.py"}
        self.script = self.publish / "IoT/模块/demo.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("print('sample')\n", encoding="utf-8")
        self.save([self.task])

    def save(self, tasks):
        (self.publish / "TrainTaskInfo.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8-sig")

    def run_demo(self, task=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return iotdemo.run_task(self.publish, task or self.task, self.logs)

    def log(self):
        return next(self.logs.glob("*.log")).read_text(encoding="utf-8")

    def test_single_script_uses_folder_and_script_directory(self):
        (self.script.parent / "relative-resource.txt").write_text("resource-ok", encoding="utf-8")
        self.script.write_text("from pathlib import Path\nprint(Path('relative-resource.txt').read_text())\n", encoding="utf-8")
        self.assertEqual(iotdemo.resolve_scripts(self.publish, self.task), [self.script.resolve()])
        self.assertEqual(self.run_demo(), 0)
        self.assertIn("resource-ok", self.log())
        self.assertIn("IoT/模块/demo.py", self.log())
        self.assertIn("退出码 0", self.log())

    def test_full_paths_and_windows_separators(self):
        self.task["PythonScriptPath"] = "IoT\\模块\\demo.py"
        self.task["ScriptFloderPath"] = "IoT/其他/extra.py|IoT/其他/extra2.py"
        self.assertEqual(iotdemo.resolve_scripts(self.publish, self.task), [self.script.resolve()])

    def test_composite_runs_concurrently_without_extra_actuators(self):
        other = self.publish / "IoT/另一个模块/demo.py"
        other.parent.mkdir()
        for index, script, counterpart in ((1, self.script, 2), (2, other, 1)):
            script.write_text(
                "from pathlib import Path\nimport time\n"
                "root=Path(__file__).resolve().parents[2]\n"
                "(root/'ready{}').write_text('ready')\n".format(index) +
                "deadline=time.monotonic()+3\n"
                "while not (root/'ready{}').exists():\n".format(counterpart) +
                "    assert time.monotonic()<deadline, 'not concurrent'\n"
                "    time.sleep(.02)\nprint('both-ready')\n", encoding="utf-8")
        self.task["PythonScriptPath"] = "IoT/模块/demo.py|IoT/另一个模块/demo.py|IoT/模块/demo.py"
        self.task["ScriptFloderPath"] = "IoT/actuator/missing.py|IoT/actuator2/missing.py"
        self.assertEqual(len(iotdemo.resolve_scripts(self.publish, self.task)), 2)
        self.assertEqual(self.run_demo(), 0)
        self.assertEqual(self.log().count("both-ready"), 2)
        self.assertNotIn("actuator", self.log())

    def test_every_script_checked_before_start(self):
        self.script.write_text("from pathlib import Path\nPath('started').touch()\n", encoding="utf-8")
        self.task["PythonScriptPath"] = "IoT/模块/demo.py|IoT/missing.py"
        with self.assertRaisesRegex(iotdemo.DemoError, "脚本不存在"):
            self.run_demo()
        self.assertFalse((self.script.parent / "started").exists())
        self.assertFalse(self.logs.exists())

    def test_rejects_empty_script_traversal_and_non_iot(self):
        self.script.write_bytes(b"")
        with self.assertRaisesRegex(iotdemo.DemoError, "零字节"):
            iotdemo.resolve_scripts(self.publish, self.task)
        for value in ("IoT/../outside.py", "/tmp/demo.py", "C:\\IoT\\demo.py", "app/hat.py", "IoT/模块/demo.py|"):
            with self.subTest(path=value):
                self.task["PythonScriptPath"] = value
                with self.assertRaises(iotdemo.DemoError):
                    iotdemo.resolve_scripts(self.publish, self.task)

    @unittest.skipUnless(os.name == "posix", "Requires Linux symlinks")
    def test_symlink_cannot_escape_iot(self):
        outside = self.base / "outside.py"
        outside.write_text("print('outside')")
        self.script.unlink()
        self.script.symlink_to(outside)
        with self.assertRaisesRegex(iotdemo.DemoError, "IoT 外"):
            iotdemo.resolve_scripts(self.publish, self.task)

    def test_json_errors_and_duplicate_ids(self):
        for text in ("{", "{}", "[3]"):
            (self.publish / "TrainTaskInfo.json").write_text(text)
            with self.assertRaises(iotdemo.DemoError):
                iotdemo.load_tasks(self.publish)
        self.save([self.task, self.task])
        with self.assertRaisesRegex(iotdemo.DemoError, "重复"):
            iotdemo.load_tasks(self.publish)

    def test_config_reloaded_and_app_tasks_excluded(self):
        other = dict(self.task, TrainTaskId=24, ScriptFloderPath="app/hat", PythonScriptPath="hat20.py")
        self.save([self.task, other])
        self.assertEqual(len(iotdemo.load_tasks(self.publish)), 1)
        replacement = dict(self.task, TrainTaskName="赛事版本", PythonScriptPath="updated.py")
        self.save([replacement])
        self.assertEqual(iotdemo.load_tasks(self.publish)[0]["PythonScriptPath"], "updated.py")
        self.assertFalse(self.logs.exists())

    def test_menu_reloads_before_running_selected_task(self):
        def choose(prompt):
            replacement = dict(self.task, PythonScriptPath="changed.py")
            self.save([replacement])
            return "2"
        with patch("builtins.input") as read, \
                patch("iot_runner.run_task", return_value=0) as run, contextlib.redirect_stdout(io.StringIO()):
            # Mock input needs a function side effect to perform the configuration change.
            responses = iter([choose, lambda _: "q"])
            read.side_effect = lambda prompt: next(responses)(prompt)
            self.assertEqual(iotdemo.main(["--publish", str(self.publish), "--log-dir", str(self.logs)]), 0)
            self.assertEqual(run.call_args.args[1]["PythonScriptPath"], "changed.py")

    def test_traceback_and_nonzero_status_saved(self):
        self.script.write_text("print('before-error')\nraise RuntimeError('demo-failure')\n", encoding="utf-8")
        self.assertEqual(self.run_demo(), 1)
        self.assertIn("Traceback", self.log())
        self.assertIn("demo-failure", self.log())
        self.assertIn("before-error", self.log())

    def test_failed_composite_stops_other_script(self):
        other = self.publish / "IoT/模块/other.py"
        other.write_text("import time\nprint('waiting')\ntime.sleep(30)\n", encoding="utf-8")
        self.script.write_text("raise RuntimeError('stop-composite')\n", encoding="utf-8")
        self.task["PythonScriptPath"] = "IoT/模块/other.py|IoT/模块/demo.py"
        started = time.monotonic()
        self.assertEqual(self.run_demo(), 1)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("stop-composite", self.log())

    def test_list_check_and_missing_task_do_not_execute(self):
        self.script.write_text("from pathlib import Path\nPath('started').touch()\n", encoding="utf-8")
        args = ["--publish", str(self.publish)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(iotdemo.main(args + ["--list"]), 0)
            self.assertEqual(iotdemo.main(args + ["--task", "2", "--check"]), 0)
            self.assertEqual(iotdemo.main(args + ["--task", "999"]), 1)
            self.script.unlink()
            self.assertEqual(iotdemo.main(args + ["--check"]), 1)
        self.assertFalse((self.script.parent / "started").exists())

    def test_interpreter_override_and_log_directory_rejection(self):
        self.task["PythonExePath"] = "/does-not-exist/python3"
        with self.assertRaises(iotdemo.DemoError):
            iotdemo.interpreter(self.task)
        self.assertTrue(iotdemo.interpreter(self.task, sys.executable))
        with self.assertRaisesRegex(iotdemo.DemoError, "publish 外"):
            iotdemo.run_task(self.publish, self.task, self.publish / "logs", python=sys.executable)
        self.assertFalse((self.publish / "logs").exists())

    def test_saved_workbench_directory(self):
        folder = self.base / "config/aiot-workbench"
        folder.mkdir(parents=True)
        (folder / "settings.json").write_text(json.dumps({"target": str(self.publish)}))
        previous = Path.cwd()
        try:
            os.chdir(self.base)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(folder.parent)}):
                self.assertEqual(iotdemo.find_publish(None), self.publish.resolve())
                os.chdir(self.publish)
                self.assertEqual(iotdemo.find_publish(None), self.publish.resolve())
        finally:
            os.chdir(previous)

    @unittest.skipUnless(os.name == "posix", "Requires POSIX process group signals")
    def test_ctrl_c_stops_child_and_grandchild(self):
        pidfile = self.script.parent / "grandchild.pid"
        self.script.write_text(
            "import subprocess,sys,time\nfrom pathlib import Path\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
            "Path('grandchild.pid').write_text(str(child.pid))\n"
            "try:\n    time.sleep(30)\n"
            "finally:\n    child.wait()\n", encoding="utf-8")
        runner = subprocess.Popen([sys.executable, str(Path(iotdemo.__file__)), "--publish", str(self.publish),
                                   "--task", "2", "--log-dir", str(self.logs)],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8")
        try:
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            child_pid = int(pidfile.read_text())
            runner.send_signal(signal.SIGINT)
            output, _ = runner.communicate(timeout=8)
            self.assertEqual(runner.returncode, 130, output)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if runner.poll() is None:
                runner.kill()
                runner.communicate(timeout=5)

    def test_python38_syntax(self):
        ast.parse(Path(iotdemo.__file__).read_text(encoding="utf-8"), feature_version=8)

    def test_selected_task_holds_switcher_lock_until_return(self):
        from core import Engine, SyncError
        def run(publish, task, log_dir, **kwargs):
            with self.assertRaises(SyncError):
                with Engine(publish).lock():
                    self.fail("Concurrent update must be blocked")
            self.assertEqual(task["TrainTaskId"], 2)
            return 0
        with patch("iot_runner.run_task", side_effect=run):
            self.assertEqual(iotdemo.run_selected(self.publish, "2", self.logs), 0)
        with Engine(self.publish).lock():
            pass  # Lock released when Demo exits.

    def test_active_program_blocks_demo_launch(self):
        from core import SyncError
        with patch("iot_runner.assert_stopped", side_effect=SyncError("主程序仍在运行")), patch("iot_runner.run_task") as run:
            with self.assertRaisesRegex(SyncError, "主程序"):
                iotdemo.run_selected(self.publish, "2", self.logs)
            run.assert_not_called()

    def test_gui_cancel_event_stops_running_demo(self):
        self.script.write_text("import time\nprint('cancel-ready')\ntime.sleep(30)\n", encoding="utf-8")
        cancel = threading.Event()
        timer = threading.Timer(.3, cancel.set)
        lines = []
        timer.start()
        try:
            result = iotdemo.run_selected(self.publish, "2", self.logs, cancel=cancel, output=lines.append)
            self.assertEqual(result, 130)
            self.assertIn("cancel-ready", "\n".join(lines))
            self.assertIn("结果码 130", self.log())
        finally:
            timer.cancel()


if __name__ == "__main__":
    unittest.main()
