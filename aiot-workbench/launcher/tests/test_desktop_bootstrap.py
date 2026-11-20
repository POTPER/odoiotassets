import os
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_bootstrap as bootstrap


class DesktopBootstrapTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.tool = self.base / "中文 tool space"
        self.tool.mkdir()
        self.gui = self.tool / "aiot_launcher.py"
        self.logs = self.base / "settings/logs"

    def test_early_import_error_is_logged_and_reported(self):
        self.gui.write_text("import missing_launcher_module_937615\n", encoding="utf-8")
        with patch.object(bootstrap, "report_failure") as report:
            result = bootstrap.run_gui(self.gui, [], self.logs)
        self.assertNotEqual(result, 0)
        logfile = report.call_args.args[0]
        text = logfile.read_text(encoding="utf-8")
        self.assertIn("ModuleNotFoundError", text)
        self.assertIn("missing_launcher_module_937615", text)

    def test_success_preserves_arguments_cwd_and_retains_separate_logs(self):
        self.gui.write_text("import sys,os,faulthandler\nfrom pathlib import Path\n"
                            "assert os.environ['PYTHONFAULTHANDLER'] == '1'\n"
                            "assert faulthandler.is_enabled()\n"
                            "assert Path.cwd() == Path(__file__).parent\n"
                            "assert sys.argv[1:] == ['--settings-file', 'with space/settings.json']\n"
                            "print('GUI launched')\n", encoding="utf-8")
        with patch.object(bootstrap, "report_failure") as report:
            for _ in range(2):
                self.assertEqual(bootstrap.run_gui(self.gui, ['--settings-file', 'with space/settings.json'], self.logs), 0)
        report.assert_not_called()
        logs = list(self.logs.glob("gui-startup-*.log"))
        self.assertEqual(len(logs), 2)
        self.assertTrue(all("GUI launched" in path.read_text(encoding="utf-8") for path in logs))

    def test_failure_report_works_without_notification_tools(self):
        output = io.StringIO()
        with patch.object(bootstrap.shutil, "which", return_value=None), contextlib.redirect_stderr(output):
            bootstrap.report_failure(self.logs / "error.log")
        self.assertIn("error.log", output.getvalue())


if __name__ == "__main__":
    unittest.main()
