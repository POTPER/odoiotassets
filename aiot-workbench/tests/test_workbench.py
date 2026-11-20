import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "launcher"))
from core import Engine, SyncError
from config_operations import configure_questions
from config_versions import CONFIG_NAMES


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / "publish"
        self.target.mkdir()
        for version in ("公开版", "F内部版"):
            folder = self.target / "config" / version
            folder.mkdir(parents=True)
            for name in CONFIG_NAMES:
                (folder / name).write_text(json.dumps([{"version": version}]), encoding="utf-8")
                (self.target / name).write_text("[]", encoding="utf-8")
        (self.target / "config/versions.json").write_text(json.dumps({
            "rules": [{"prefix": "F", "user_visible": False}],
            "versions": {"公开版": {"display_name": "教学训练"}}}), encoding="utf-8")
        self.environment = dict(os.environ, XDG_CONFIG_HOME=str(self.base / "settings"), PYTHONIOENCODING="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "workbench.py")] + list(args),
                              capture_output=True, encoding="utf-8", env=self.environment, timeout=20)

    def test_one_entry_cli_without_tk_and_backend_import_collisions(self):
        code = self.cli("--version")
        self.assertEqual(code.returncode, 0, code.stderr)
        self.assertTrue(code.stdout.startswith("AIoT Workbench "))
        result = self.cli("cli", "--target", str(self.target), "config", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("F内部版", result.stdout)
        self.assertIn("公开版", result.stdout)
        # The CLI source only imports Tk when the engineer GUI is explicitly requested.
        probe = "import sys,runpy; sys.argv=['engineer_entry.py','--help']; " \
                "runpy.run_path(%r,run_name='__main__')" % str(ROOT / "engineer_entry.py")
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, env=self.environment, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_user_visibility_and_original_cleanup_are_one_transaction(self):
        tasks = self.target / "IoT/模块"
        tasks.mkdir(parents=True)
        (tasks / "target.py").write_bytes(b"generated")
        (tasks / "demo.py").write_bytes(b"keep")
        (tasks / "student_data").mkdir()
        (tasks / "student_data/result.csv").write_bytes(b"1,2")
        listed = configure_questions(self.target)
        self.assertEqual([v["display_name"] for v in listed["versions"]], ["教学训练"])
        with self.assertRaises(SyncError):
            configure_questions(self.target, "F内部版")
        result = configure_questions(self.target, "公开版")
        self.assertIn("教学训练", result["current"])
        self.assertFalse((tasks / "target.py").exists())
        self.assertFalse((tasks / "student_data").exists())
        self.assertEqual((tasks / "demo.py").read_bytes(), b"keep")
        for name in CONFIG_NAMES:
            self.assertEqual((self.target / name).read_bytes(), (self.target / "config/公开版" / name).read_bytes())
        # The maintenance engine understands v2 journals left by the user launcher.
        script = "import sys; sys.path.insert(0,%r); from core import Engine; Engine(%r).startup_recover()" % (
            str(ROOT / "shared"), str(self.target))
        result = subprocess.run([sys.executable, "-c", script], env=self.environment, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_installer_creates_only_workbench_shortcuts_and_shared_settings(self):
        import workbench_install
        toolkit = self.base / "tool"
        (toolkit / "launcher/assets").mkdir(parents=True)
        (toolkit / "tool_update.py").write_bytes((ROOT / "tool_update.py").read_bytes())
        config = self.base / "preferences"
        desktop = self.base / "桌面"
        with patch.object(workbench_install, "ROOT", toolkit):
            result = workbench_install.install_workbench(self.target, config_dir=config,
                applications=self.base / "applications", desktop_dir=desktop, shortcut_dir=self.base / "shortcut")
        entry = desktop / "aiot-workbench.desktop"
        self.assertTrue(entry.is_file())
        self.assertIn("workbench-bootstrap.py", entry.read_text(encoding="utf-8"))
        self.assertFalse((desktop / "aiot-launcher.desktop").exists())
        data = json.loads((config / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["target"], data["publish_dir"])
        self.assertEqual(data["workbench_directory"], "aiot-workbench")
        self.assertNotIn("program_update_url", data)
        self.assertIn("session_cli.py", Path(result["script"]).read_text(encoding="utf-8"))

    def test_update_gate_blocks_start_and_configuration_without_disabling_stop(self):
        try:
            from workbench_ui import WorkbenchWindow
        except ImportError:
            self.skipTest("Tkinter not installed")
        from aiot_launcher import LauncherWindow
        ui = WorkbenchWindow.__new__(WorkbenchWindow)
        ui.update_checked, ui.update_busy, ui.engineer_process = False, False, None
        ui.open_updates = Mock()
        ui.status = Mock()
        ui.controller = Mock()
        ui.busy, ui.config_busy, ui.closing, ui.external_running = True, False, False, False
        ui.exit_button, ui.start_button, ui.progress, ui.canvas = Mock(), Mock(), Mock(), Mock()
        ui.audit = Mock()
        ui.start()
        self.assertFalse(ui.controller.start.called)
        self.assertFalse(ui.begin_config("replace", "公开版"))
        self.assertTrue(ui.stop())
        ui.controller.request_stop.assert_called_once()
        ui.update_checked, ui.busy = True, False
        with patch.object(LauncherWindow, "start") as start:
            ui.start()
            start.assert_called_once()
        ui.engineer_process = Mock()
        with patch.object(LauncherWindow, "start") as start:
            ui.start()
            start.assert_not_called()

    def test_default_publish_prefers_hyphen_then_underscore_and_honors_saved_path(self):
        import workbench_paths
        from launcher_runtime import load_settings
        hyphen, underscore = self.base / "linux-arm64/publish", self.base / "linux_arm64/publish"
        underscore.mkdir(parents=True)
        with patch.object(workbench_paths, "DEFAULT_PUBLISH", hyphen), patch.object(workbench_paths, "ALTERNATE_PUBLISH", underscore):
            self.assertEqual(workbench_paths.default_publish(), str(underscore))
            hyphen.mkdir(parents=True)
            self.assertEqual(workbench_paths.default_publish(), str(hyphen))
            saved = self.base / "explicit.json"
            saved.write_text(json.dumps({"publish_dir": str(self.target)}), encoding="utf-8")
            self.assertEqual(load_settings(saved)["publish_dir"], str(self.target))


if __name__ == "__main__":
    unittest.main()
