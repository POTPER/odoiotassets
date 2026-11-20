import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher_preferences as prefs
from core import SyncError, atomic_json


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def test_localized_desktop_and_default_results(self):
        desktop = self.base / "当前用户/桌面"
        response = subprocess.CompletedProcess([], 0, str(desktop) + "\n", "")
        with patch.object(prefs.sys, "platform", "linux"), \
                patch.object(prefs.shutil, "which", return_value="/usr/bin/xdg-user-dir"), \
                patch.object(prefs.subprocess, "run", return_value=response):
            folder, theme = prefs.preferences({})
        self.assertEqual(folder, desktop / "成果输出")
        self.assertEqual(theme, "dark")

    def test_old_default_is_corrected_without_changing_custom_locations(self):
        desktop = self.base / "桌面"
        with patch.object(prefs, "desktop_directory", return_value=desktop):
            self.assertEqual(prefs.preferences({"results_dir": str(desktop / "成果输出文件夹")})[0], desktop / "成果输出")
            for folder in (self.base / "自定义成果", self.base / "其他位置/成果输出文件夹"):
                self.assertEqual(prefs.preferences({"results_dir": str(folder)})[0], folder)

    def test_saving_preferences_preserves_deployment_and_collection_settings(self):
        path = self.base / "settings.json"
        original = {"publish_dir": str(self.base / "publish"), "collection_enabled": False,
                    "apply_config_enabled": True, "archive_dir": "unchanged", "future": {"keep": 1}}
        atomic_json(path, original)
        target = self.base / "中文成果 space"
        prefs.save_preferences(path, "ignored", str(target), "light")
        saved = json.loads(path.read_text(encoding="utf-8"))
        for key, value in original.items():
            self.assertEqual(saved[key], value)
        self.assertEqual(prefs.preferences(saved), (target, "light"))
        self.assertFalse(target.exists())
        for bad in ("", "relative/path"):
            with self.assertRaises(SyncError):
                prefs.save_preferences(path, "ignored", bad, "dark")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), saved)

    def test_results_folder_is_created_and_opened_without_a_shell(self):
        folder = self.base / "成果 with space"
        result = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(prefs.sys, "platform", "linux"), \
                patch.object(prefs.shutil, "which", return_value="/usr/bin/xdg-open"), \
                patch.object(prefs.subprocess, "run", return_value=result) as run:
            prefs.open_results_directory(folder)
        self.assertTrue(folder.is_dir())
        self.assertEqual(run.call_args.args[0], ["/usr/bin/xdg-open", str(folder)])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_file_manager_error_is_reported(self):
        result = subprocess.CompletedProcess([], 1, "", "file manager unavailable")
        with patch.object(prefs.sys, "platform", "linux"), \
                patch.object(prefs.shutil, "which", return_value="/usr/bin/xdg-open"), \
                patch.object(prefs.subprocess, "run", return_value=result), self.assertRaisesRegex(SyncError, "unavailable"):
            prefs.open_results_directory(self.base / "results")

    def test_submission_defaults_off_and_requires_an_independent_target(self):
        path = self.base / "settings.json"
        source, target = self.base / "source", self.base / "target"
        data = prefs.save_preferences(path, str(self.base / "publish"), str(source), "dark")
        self.assertIs(data["submission_enabled"], False)
        self.assertEqual(data["submission_dir"], "")
        for destination in ("", str(source), str(source / "nested")):
            with self.assertRaises(SyncError):
                prefs.save_preferences(path, "ignored", str(source), "dark", True, destination)
        enabled = prefs.save_preferences(path, "ignored", str(source), "light", True, str(target))
        self.assertIs(enabled["submission_enabled"], True)
        self.assertEqual(enabled["submission_dir"], str(target))
        self.assertFalse(target.exists())

    def test_submission_cannot_save_a_destination_inside_the_saved_or_current_publish(self):
        path = self.base / 'settings.json'
        publish = self.base / 'workspace/publish'
        current = self.base / 'other-publish'
        source = self.base / 'results'
        atomic_json(path, {'publish_dir': str(publish), 'submission_enabled': False})
        original = json.loads(path.read_text(encoding='utf-8'))
        for destination in (publish, publish / 'app/task/student_data', publish.parent, current / 'IoT/task'):
            with self.subTest(destination=destination), self.assertRaisesRegex(SyncError, 'publish'):
                prefs.save_preferences(path, str(current), str(source), 'dark', True, str(destination))
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), original)


if __name__ == "__main__":
    unittest.main()
