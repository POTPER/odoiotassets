import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / "publish"
        self.source = self.base / "source"
        self.repo = self.base / "repository"
        self.target.mkdir()
        self.source.mkdir()
        (self.source / "demo.py").write_bytes(b"print('new')\n")
        (self.source / "TrainTaskInfo.json").write_bytes(b'[{"new": true}]')
        (self.source / "font.ttf").write_bytes(b"real-font-fixture")
        (self.target / "demo.py").write_bytes(b"old")
        (self.target / "TrainTaskInfo.json").write_bytes(b"[]")
        (self.target / "font.ttf").write_bytes(b"")
        (self.target / "obsolete.py").write_bytes(b"obsolete")
        (self.target / "AIotApp").write_bytes(b"preserve-app")
        (self.target / "model.rknn").write_bytes(b"preserve-model")
        generator = "import sys; sys.path.insert(0,%r); from generate import generate; generate(%r,%r,'rk','RK','1')" % (
            str(ROOT / "engineer"), str(self.source), str(self.repo))
        result = subprocess.run([sys.executable, "-c", generator], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.settings = self.base / "settings.json"
        self.settings.write_text(json.dumps({"publish_dir": str(self.target), "local_catalog": str(self.repo / "catalog.json"),
            "home_update_profile": "rk", "file_extensions": [".py", ".json", ".ttf"]}), encoding="utf-8")

    def worker(self, command, offline=False, automatic=False):
        args = [sys.executable, str(ROOT / "content_update.py"), "--settings", str(self.settings)]
        if offline:
            args.append("--offline")
        if automatic:
            args.append("--auto-apply")
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        preview = json.loads(process.stdout.readline())
        self.assertEqual(preview["kind"], "preview", preview)
        if preview["changes"] and not automatic:
            process.stdin.write(json.dumps({"command": command}) + "\n")
            process.stdin.flush()
        # Keep stdin open while applying: EOF deliberately requests cancellation.
        records = [preview]
        for line in process.stdout:
            records.append(json.loads(line))
        code = process.wait(timeout=20)
        error = process.stderr.read()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        self.assertEqual(code, 0, error)
        return records

    def test_home_strict_update_replaces_json_and_font_deletes_selected_extras(self):
        records = self.worker("apply")
        self.assertEqual(records[-1]["kind"], "done")
        for name in ("demo.py", "TrainTaskInfo.json", "font.ttf"):
            self.assertEqual((self.target / name).read_bytes(), (self.source / name).read_bytes())
        self.assertFalse((self.target / "obsolete.py").exists())
        self.assertEqual((self.target / "AIotApp").read_bytes(), b"preserve-app")
        self.assertEqual((self.target / "model.rknn").read_bytes(), b"preserve-model")
        # Downloaded objects and manifest are enough for the next strict update offline.
        (self.target / "demo.py").write_bytes(b"changed offline")
        records = self.worker("apply", offline=True)
        self.assertEqual(records[-1]["kind"], "done")
        self.assertEqual((self.target / "demo.py").read_bytes(), b"print('new')\n")

    def test_cancel_after_preview_leaves_every_original_file_untouched(self):
        records = self.worker("cancel")
        self.assertEqual(records[-1]["kind"], "cancelled")
        self.assertEqual((self.target / "demo.py").read_bytes(), b"old")
        self.assertTrue((self.target / "obsolete.py").exists())
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), b"[]")

    def test_combined_updater_applies_publish_without_a_second_user_prompt(self):
        records = self.worker("", automatic=True)
        self.assertEqual(records[-1]["kind"], "done")
        self.assertFalse((self.target / "obsolete.py").exists())
        self.assertEqual((self.target / "font.ttf").read_bytes(), b"real-font-fixture")


if __name__ == "__main__":
    unittest.main()
