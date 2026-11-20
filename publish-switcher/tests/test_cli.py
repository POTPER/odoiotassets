import contextlib
import io
import json
import logging
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import switcher
from generate import generate


class CliTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).resolve().parent / ".tmp")))
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / "publish"
        self.target.mkdir()
        self.log = self.base / "debug.log"
        self.addCleanup(self.close_logs)
        self.config_patch = patch("switcher.settings", return_value={})
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.proc_patch = patch("core.assert_stopped")
        self.proc_patch.start()
        self.addCleanup(self.proc_patch.stop)

    @staticmethod
    def close_logs():
        logger = logging.getLogger("publish-switcher")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def call(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = switcher.main(["--target", str(self.target), "--log-file", str(self.log)] + args)
        self.close_logs()
        return result, output.getvalue(), errors.getvalue()

    def test_formats_discovery_persistence_and_font_sync_without_tk(self):
        source = self.base / 'font-source'
        source.mkdir()
        (source / 'sample.ttf').write_bytes(b'\x00\x01font')
        (source / 'model.bin').write_bytes(b'model')
        repo = self.base / 'font-repo'
        generate(source, repo, 'rk', 'RK', '1')
        args = ['--local-catalog', str(repo / 'catalog.json'), '--extensions', '.ttf']
        saved = self.base / 'font-settings.json'
        with patch('switcher.settings_path', return_value=saved):
            result, output, errors = self.call(args + ['formats', '--profile', 'rk', '--save'])
        self.assertEqual(result, 0, errors)
        self.assertIn('[x] .ttf', output)
        self.assertIn('[ ] .bin', output)
        self.assertEqual(json.loads(saved.read_text(encoding='utf-8'))['file_extensions'], ['.ttf'])
        result, output, errors = self.call(['--local-catalog', str(repo / 'catalog.json'), 'sync', '--profile', 'rk', '--extensions', '.ttf', '--yes'])
        self.assertEqual(result, 0, errors)
        self.assertEqual((self.target / 'sample.ttf').read_bytes(), b'\x00\x01font')
        self.assertFalse((self.target / 'model.bin').exists())

    def test_config_bundle_runs_without_gui_and_logs(self):
        from test_config_versions import write_bundle
        raw = write_bundle(self.target, "福建农职", "_福建农职")
        result, output, errors = self.call(["config", "list"])
        self.assertEqual(result, 0, errors)
        self.assertIn("福建农职", output)
        result, output, errors = self.call(["config", "check", "--version", "福建农职"])
        self.assertEqual(result, 0, errors)
        self.assertFalse((self.target / "TrainTaskInfo.json").exists())
        result, output, errors = self.call(["config", "apply", "--version", "福建农职", "--yes"])
        self.assertEqual(result, 0, errors)
        for name, data in raw.items():
            self.assertEqual((self.target / name).read_bytes(), data)
        self.assertIn("配置版本已应用", self.log.read_text(encoding="utf-8"))

    def test_iot_demo_list_check_run_and_errors(self):
        script = self.target / "IoT/test/demo.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('CLI-demo-ok')\n", encoding="utf-8")
        task = {"TrainTaskId": 2, "TrainTaskName": "测试任务", "PythonExePath": sys.executable,
                "ScriptFloderPath": "IoT/test", "PythonScriptPath": "demo.py"}
        (self.target / "TrainTaskInfo.json").write_text(json.dumps([task]), encoding="utf-8")
        result, output, errors = self.call(["demo", "--list"])
        self.assertEqual(result, 0, errors)
        self.assertIn("测试任务", output)
        self.assertFalse((self.base / "iot-demo").exists())
        result, output, errors = self.call(["demo", "--task", "2", "--check"])
        self.assertEqual(result, 0, errors)
        result, output, errors = self.call(["demo", "--task", "2"])
        self.assertEqual(result, 0, errors)
        self.assertIn("CLI-demo-ok", output)
        self.assertIn("CLI-demo-ok", next((self.base / "iot-demo").glob("*.log")).read_text(encoding="utf-8"))
        script.write_text("raise RuntimeError('CLI-demo-failure')\n", encoding="utf-8")
        result, output, errors = self.call(["demo", "--task", "2"])
        self.assertEqual(result, 1)
        self.assertIn("CLI-demo-failure", output)

    def test_errors_have_traceback_in_file_and_terminal(self):
        result, output, errors = self.call(["config", "apply", "--version", "missing", "--yes"])
        self.assertEqual(result, 1)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("Traceback", text)
        self.assertIn("版本", text)
        self.assertIn("操作失败", errors)

    def test_config_diff_is_readonly_and_can_show_original_text(self):
        from test_config_versions import write_bundle
        write_bundle(self.target, "福建农职", "_福建农职")
        active = self.target / "TrainTaskInfo.json"
        old = b'[{"PythonScriptPath":"cli-old-secret.py"}]'
        active.write_bytes(old)
        result, output, errors = self.call(["config", "diff", "--version", "福建农职", "--file", "TrainTaskInfo.json"])
        self.assertEqual(result, 0, errors)
        self.assertIn("JSON 内容差异（格式化）", output)
        self.assertIn("cli-old-secret.py", output)
        self.assertNotIn("cli-old-secret.py", self.log.read_text(encoding="utf-8"))
        self.assertEqual(active.read_bytes(), old)
        result, output, errors = self.call(["config", "diff", "--version", "福建农职", "--raw"])
        self.assertEqual(result, 0, errors)
        self.assertIn("原始文本差异", output)
        self.assertEqual(output.count("配置 JSON 对比："), 3)

    def test_assets_check_then_missing_only_download(self):
        source, repo = self.base / "source", self.base / "repo"
        (source / "Assets").mkdir(parents=True)
        (source / "Assets/missing.png").write_bytes(b"image")
        (source / "Assets/different.avi").write_bytes(b"BBBB")
        (self.target / "Assets").mkdir()
        (self.target / "Assets/different.avi").write_bytes(b"AAAA")
        (self.target / "Assets/local.txt").write_bytes(b"keep")
        generate(source, repo, "rk", "RK", "1")
        options = ["--local-catalog", str(repo / "catalog.json")]
        result, output, errors = self.call(options + ["assets", "check", "--profile", "rk"])
        self.assertEqual(result, 0, errors)
        self.assertIn("内容不同", output)
        self.assertFalse((self.target / "Assets/missing.png").exists())
        result, output, errors = self.call(options + ["assets", "download", "--profile", "rk", "--yes"])
        self.assertEqual(result, 0, errors)
        self.assertEqual((self.target / "Assets/missing.png").read_bytes(), b"image")
        self.assertEqual((self.target / "Assets/different.avi").read_bytes(), b"AAAA")
        self.assertEqual((self.target / "Assets/local.txt").read_bytes(), b"keep")
        (self.target / "Assets/missing.png").unlink()
        result, output, errors = self.call(["--offline", "assets", "download", "--profile", "rk", "--yes"])
        self.assertEqual(result, 0, errors)
        self.assertEqual((self.target / "Assets/missing.png").read_bytes(), b"image")

    def test_competition_is_deprecated_without_changing_files(self):
        result, output, errors = self.call(["competition"])
        self.assertEqual(result, 1)
        self.assertIn("config apply", errors)

    def test_local_check_then_sync_requires_yes(self):
        source, repo = self.base / "source", self.base / "repo"
        source.mkdir()
        (source / "script.py").write_bytes(b"print('ok')")
        (self.target / "model.rknn").write_bytes(b"installed model")
        generate(source, repo, "rk", "RK", "1")
        options = ["--local-catalog", str(repo / "catalog.json")]
        result, output, errors = self.call(options + ["check", "--profile", "rk"])
        self.assertEqual(result, 0, errors)
        self.assertIn("script.py", output)
        self.assertFalse((self.target / "script.py").exists())
        with patch("switcher.sys.stdin.isatty", return_value=False):
            result, output, errors = self.call(options + ["sync", "--profile", "rk"])
        self.assertEqual(result, 1)
        self.assertFalse((self.target / "script.py").exists())
        result, output, errors = self.call(options + ["sync", "--profile", "rk", "--yes"])
        self.assertEqual(result, 0, errors)
        self.assertTrue((self.target / "script.py").exists())
        self.assertEqual((self.target / "model.rknn").read_bytes(), b"installed model")
        result, output, errors = self.call(["--offline", "list"])
        self.assertEqual(result, 0, errors)
        self.assertIn("RK", output)

    def test_log_tail_and_exit_code(self):
        self.log.write_text("one\ntwo\nthree\n", encoding="utf-8")
        result, output, errors = self.call(["logs", "--tail", "2"])
        self.assertEqual(result, 0)
        self.assertIn("two\nthree", output)
        self.assertNotIn("one\n", output)

    def test_self_test_needs_no_target_or_settings(self):
        with patch("switcher.settings", side_effect=AssertionError("must not load user target")):
            result, output, errors = self.call(["self-test"])
        self.assertEqual(result, 0, errors)
        self.assertIn("全部 6 项通过", output)

    def test_diagnose_reports_newlines_without_syncing(self):
        source, repo = self.base / "source", self.base / "repo"
        source.mkdir()
        (source / "script.py").write_bytes(b"print('ok')\n")
        (self.target / "script.py").write_bytes(b"print('ok')\r\n")
        generate(source, repo, "rk", "RK", "1")
        result, output, errors = self.call(["--local-catalog", str(repo / "catalog.json"), "diagnose", "--profile", "rk", "--path", "script.py"])
        self.assertEqual(result, 0, errors)
        self.assertIn("仅换行不同", output)
        self.assertIn("SHA-256", output)
        self.assertNotIn("请重新启动", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('ok')\r\n")

    def test_diagnose_does_not_trigger_transaction_recovery(self):
        from core import Engine
        source, repo = self.base / "source", self.base / "repo"
        source.mkdir()
        (source / "script.py").write_bytes(b"print('ok')\n")
        generate(source, repo, "rk", "RK", "1")
        engine = Engine(self.target)
        engine.journal.write_text("{}")
        result, output, errors = self.call(["--local-catalog", str(repo / "catalog.json"), "diagnose", "--profile", "rk", "--path", "script.py"])
        self.assertEqual(result, 1)
        self.assertIn("未完成的切换", errors)
        self.assertEqual(engine.journal.read_text(), "{}")
        self.assertFalse((self.target / "script.py").exists())

    def test_cli_import_does_not_import_tkinter(self):
        # Use a fresh process; test modules may already have imported Tk in this interpreter.
        import subprocess
        command = [sys.executable, "-c", "import sys; import switcher; assert 'tkinter' not in sys.modules"]
        result = subprocess.run(command, cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnose_prints_colored_diff_but_logs_only_summary(self):
        source, repo = self.base / "source", self.base / "repo"
        source.mkdir()
        (source / "script.py").write_bytes(b"print('REMOTE_TEST_CONTENT')\n")
        (self.target / "script.py").write_bytes(b"print('LOCAL_TEST_CONTENT')\n")
        generate(source, repo, "rk", "RK", "1")
        with patch("switcher.stdout_colors", return_value=True):
            result, output, errors = self.call(["--local-catalog", str(repo / "catalog.json"), "diagnose", "--profile", "rk", "--path", "script.py"])
        self.assertEqual(result, 0, errors)
        self.assertIn("\x1b[31m-print('LOCAL_TEST_CONTENT')", output)
        self.assertIn("\x1b[32m+print('REMOTE_TEST_CONTENT')", output)
        log = self.log.read_text(encoding="utf-8")
        self.assertNotIn("LOCAL_TEST_CONTENT", log)
        self.assertNotIn("REMOTE_TEST_CONTENT", log)
        self.assertIn("新增 1 行，删除 1 行", log)

    @unittest.skipUnless(os.name == "posix", "Linux permissions")
    def test_permission_flags_saved_policy_and_incremental(self):
        source, repo = self.base / "source", self.base / "repo"
        source.mkdir()
        for folder in (source, self.target):
            (folder / "script.py").write_bytes(b"print('ok')\n")
        os.chmod(source / "script.py", 0o644)
        os.chmod(self.target / "script.py", 0o777)
        generate(source, repo, "rk", "RK", "1")
        options = ["--local-catalog", str(repo / "catalog.json")]
        with patch("switcher.settings", return_value={"sync_permissions": True}):
            result, output, errors = self.call(options + ["check", "--profile", "rk", "--mode", "strict"])
            self.assertEqual(result, 0, errors)
            self.assertIn("权限不同", output)
            result, output, errors = self.call(options + ["sync", "--profile", "rk", "--mode", "strict", "--keep-permissions", "--yes"])
            self.assertEqual(result, 0, errors)
            self.assertIn("内容相同", output)
            self.assertEqual(stat.S_IMODE((self.target / "script.py").stat().st_mode), 0o777)
        result, output, errors = self.call(options + ["sync", "--profile", "rk", "--mode", "incremental", "--sync-permissions", "--yes"])
        self.assertEqual(result, 0, errors)
        self.assertEqual(stat.S_IMODE((self.target / "script.py").stat().st_mode), 0o777)
        result, output, errors = self.call(options + ["sync", "--profile", "rk", "--mode", "strict", "--sync-permissions", "--yes"])
        self.assertEqual(result, 0, errors)
        self.assertEqual(stat.S_IMODE((self.target / "script.py").stat().st_mode), 0o644)
