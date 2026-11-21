import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_cli
from publish_switcher.repositories.generate import generate


class TerminalMenuTests(unittest.TestCase):
    setUp = test_cli.CliTests.setUp
    close_logs = staticmethod(test_cli.CliTests.close_logs)
    call = test_cli.CliTests.call

    def menu(self, answers, options=()):
        with patch("switcher.sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=answers):
            return self.call(list(options) + ["cli"])

    def test_format_menu_saves_selection_without_updating_publish(self):
        options = self.repository()
        saved = self.base / 'format-settings.json'
        with patch('publish_switcher.cli.menu.settings_path', return_value=saved):
            result, output, errors = self.menu(['13', '1', '3', '0', '0'], options)
        self.assertEqual(result, 0, errors)
        data = json.loads(saved.read_text(encoding='utf-8'))
        self.assertEqual(data['file_extensions'], ['.json', '.py'])
        self.assertEqual(data['format_inventory']['id'], 'rk')
        self.assertIn('.ttf', output)
        self.assertFalse((self.target / 'missing.json').exists())
        self.assertEqual((self.target / 'script.py').read_bytes(), b"print('original')\n")

    def repository(self):
        source, repo = self.base / "source", self.base / "repo"
        source.mkdir()
        (source / "script.py").write_bytes(b"print('updated')\n")
        (source / "missing.json").write_bytes(b"[]\n")
        (self.target / "script.py").write_bytes(b"print('original')\n")
        (self.target / "extra.json").write_bytes(b"[]\n")
        (self.target / "model.bin").write_bytes(b"model stays")
        generate(source, repo, "rk", "RK", "1")
        return ["--local-catalog", str(repo / "catalog.json")]

    def test_entry_and_exit_need_no_publish(self):
        result, output, errors = self.menu(["0"], ["--target", ""])
        self.assertEqual(result, 0, errors)
        self.assertIn("publish：未设置", output)
        self.assertIn("终端菜单", output)
        self.assertIn("查看／切换配置版本", output)
        self.assertIn("运行 IoT Demo", output)

    def test_demo_menu_runs_task_and_returns_to_switcher(self):
        script = self.target / "IoT/test/demo.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('menu-demo-ok')\n", encoding="utf-8")
        task = {"TrainTaskId": 2, "PythonExePath": sys.executable,
                "ScriptFloderPath": "IoT/test", "PythonScriptPath": "demo.py"}
        (self.target / "TrainTaskInfo.json").write_text(json.dumps([task]), encoding="utf-8")
        result, output, errors = self.menu(["10", "2", "q", "0"])
        self.assertEqual(result, 0, errors)
        self.assertIn("menu-demo-ok", output)
        self.assertIn("已退出", output)

    def test_noninteractive_menu_is_rejected(self):
        with patch("switcher.sys.stdin.isatty", return_value=False):
            result, output, errors = self.call(["cli"])
        self.assertEqual(result, 1)
        self.assertIn("需要交互终端", errors)

    def test_check_does_not_apply_files(self):
        options = self.repository()
        result, output, errors = self.menu(["3", "1", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertIn("实际本地目标", output)
        self.assertIn("检查完成，尚未修改", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('original')\n")
        self.assertFalse((self.target / "missing.json").exists())

    def test_incremental_and_strict_are_selected_after_check(self):
        options = self.repository()
        result, output, errors = self.menu(["4", "1", "1", "yes", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertTrue((self.target / "missing.json").exists())
        self.assertTrue((self.target / "extra.json").exists())
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('original')\n")
        result, output, errors = self.menu(["4", "1", "2", "yes", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertFalse((self.target / "extra.json").exists())
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('updated')\n")
        self.assertEqual((self.target / "model.bin").read_bytes(), b"model stays")

    def test_cancel_after_preview_changes_nothing(self):
        options = self.repository()
        result, output, errors = self.menu(["4", "1", "2", "no", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertIn("已取消", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('original')\n")
        self.assertTrue((self.target / "extra.json").exists())
        self.assertFalse((self.target / "missing.json").exists())

    def test_restore_menu_recovers_previous_files(self):
        options = self.repository()
        result, output, errors = self.menu(["4", "1", "2", "yes", "6", "yes", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertIn("恢复完成", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('original')\n")
        self.assertTrue((self.target / "extra.json").exists())
        self.assertFalse((self.target / "missing.json").exists())
        self.assertEqual((self.target / "model.bin").read_bytes(), b"model stays")

    def test_edit_after_check_is_rejected_and_menu_keeps_running(self):
        options = self.repository()
        answers = iter(["3", "1", "4", "2", "yes", "0"])
        def answer(prompt):
            value = next(answers)
            if value == "yes":
                (self.target / "script.py").write_bytes(b"edited after check")
            return value
        result, output, errors = self.menu(answer, options)
        self.assertEqual(result, 0, errors)
        self.assertIn("重新检查", output)
        self.assertIn("已退出", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"edited after check")
        self.assertFalse((self.target / "missing.json").exists())

    def test_missing_directory_does_not_report_all_new_or_fetch_remote(self):
        with patch("publish_switcher.cli.menu.common.profiles", side_effect=AssertionError("must not fetch")):
            result, output, errors = self.menu(["3", "0"], ["--target", str(self.base / "nonexistent")])
        self.assertEqual(result, 0, errors)
        self.assertIn("publish 目录不存在", output)
        self.assertFalse((self.base / "nonexistent").exists())

    def test_missing_target_from_interrupted_swap_is_recovered(self):
        from tools.packaging.legacy.core import Engine, atomic_json
        options = self.repository()
        engine = Engine(self.target)
        stage = engine.state / "stage-interrupted"
        stage.mkdir()
        atomic_json(engine.journal, {"phase": "prepared", "backup": "interrupted", "stage": stage.name,
                                    "had_target": True, "old_state": None, "new_state": {}})
        self.target.rename(engine.state / "backups/interrupted")
        result, output, errors = self.menu(["3", "1", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertIn("检查完成", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('original')\n")
        self.assertFalse(engine.journal.exists())

    def test_configuration_switch_applies_three_files(self):
        from test_config_versions import write_bundle
        raw = write_bundle(self.target, "福建农职", "_福建农职")
        result, output, errors = self.menu(["5", "1", "yes", "0"])
        self.assertEqual(result, 0, errors)
        self.assertIn("配置已切换为 福建农职", output)
        for name, data in raw.items():
            self.assertEqual((self.target / name).read_bytes(), data)

    def test_configuration_diff_menu_does_not_apply(self):
        from test_config_versions import write_bundle
        write_bundle(self.target, "福建农职")
        active = self.target / "TrainTaskInfo.json"
        active.write_bytes(b'[{"menu":"old"}]')
        result, output, errors = self.menu(["11", "1", "1", "0"])
        self.assertEqual(result, 0, errors)
        self.assertIn("JSON 内容差异（格式化）", output)
        self.assertEqual(active.read_bytes(), b'[{"menu":"old"}]')

    def test_assets_menu_checks_confirms_and_downloads(self):
        source, repo = self.base / "source", self.base / "repo"
        (source / "Assets").mkdir(parents=True)
        (source / "Assets/image.png").write_bytes(b"image")
        generate(source, repo, "rk", "RK", "1")
        result, output, errors = self.menu(["12", "1", "no", "0"], ["--local-catalog", str(repo / "catalog.json")])
        self.assertEqual(result, 0, errors)
        self.assertFalse((self.target / "Assets/image.png").exists())
        result, output, errors = self.menu(["12", "1", "yes", "0"], ["--local-catalog", str(repo / "catalog.json")])
        self.assertEqual(result, 0, errors)
        self.assertEqual((self.target / "Assets/image.png").read_bytes(), b"image")

    def test_settings_save_permission_preference(self):
        saved = self.base / "settings.json"
        with patch("publish_switcher.cli.menu.settings_path", return_value=saved):
            result, output, errors = self.menu(["1", "4", "2", "6", "0", "0"])
        self.assertEqual(result, 0, errors)
        self.assertTrue(json.loads(saved.read_text(encoding="utf-8"))["sync_permissions"])
        self.assertIn("已保存", output)

    def test_eof_and_ctrl_c_exit_cleanly(self):
        for exception in (EOFError(), KeyboardInterrupt()):
            with self.subTest(exception=type(exception).__name__):
                result, output, errors = self.menu(exception)
                self.assertEqual(result, 0, errors)
                self.assertIn("已退出终端菜单", output)

    def test_diagnostic_works_without_updating(self):
        options = self.repository()
        result, output, errors = self.menu(["7", "1", "script.py", "0"], options)
        self.assertEqual(result, 0, errors)
        self.assertIn("文件诊断：script.py", output)
        self.assertIn("SHA-256", output)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('original')\n")

    def test_self_test_and_logs_need_no_target(self):
        result, output, errors = self.menu(["8", "9", "0"], ["--target", ""])
        self.assertEqual(result, 0, errors)
        self.assertIn("全部 6 项通过", output)
        self.assertIn("日志文件", output)

    def test_ssh_menu_import_does_not_load_tkinter_or_switcher(self):
        import subprocess
        command = [sys.executable, "-c", "import sys; import publish_switcher.cli.menu; assert 'tkinter' not in sys.modules; assert 'switcher' not in sys.modules"]
        result = subprocess.run(command, cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name == "posix", "Linux pseudoterminal")
    def test_real_terminal_cli_entry_starts_and_exits(self):
        import subprocess
        master, slave = os.openpty()
        environment = dict(os.environ, XDG_CONFIG_HOME=str(self.base / "isolated-config"))
        process = None
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "switcher.py"),
                                        "--log-file", str(self.log), "cli"], stdin=slave,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
            os.write(master, b"0\n")
            output, errors = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, errors.decode("utf-8", errors="replace"))
            self.assertIn("swicher 终端菜单", output.decode("utf-8"))
            self.assertIn("已退出", output.decode("utf-8"))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            os.close(master)
            os.close(slave)
