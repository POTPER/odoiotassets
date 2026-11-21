import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sync
from tools.packaging.legacy.core import Engine, SyncError


class UpdateModeTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp
    build = test_sync.SyncTests.build

    def prepare(self):
        (self.target / "TrainTaskInfo.json").write_bytes(b'[{"local":"competition"}]')
        (self.target / "app/hat/hat30.py").write_bytes(b"local customization")
        return self.build()

    def test_comparison_and_incremental_retains_existing_and_local_only(self):
        source, manifest = self.prepare()
        engine = Engine(self.target)
        strict = engine.preview(manifest, mode="strict")
        inc = engine.preview(manifest, mode="incremental", actual=strict["actual"])
        rows = {r["path"]: r for r in inc["comparison"]}
        self.assertEqual(rows["TrainTaskInfo.json"]["status"], "内容不同")
        self.assertEqual(rows["TrainTaskInfo.json"]["incremental"], "跳过")
        self.assertEqual(rows["TrainTaskInfo.json"]["strict"], "替换")
        self.assertEqual(rows["app/hat/hat20.py"]["strict"], "删除")
        self.assertTrue(all(action == "新增" for action, path in inc["changes"]))
        with patch.object(source, "download", wraps=source.download) as download:
            engine.apply(manifest, source, mode="incremental", expected_actual=inc["actual"])
        self.assertTrue(all("TrainTaskInfo.json" not in call.args[0] and "hat30.py" not in call.args[0] for call in download.call_args_list))
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), b'[{"local":"competition"}]')
        self.assertEqual((self.target / "app/hat/hat30.py").read_bytes(), b"local customization")
        self.assertTrue((self.target / "app/hat/hat20.py").exists())
        self.assertTrue((self.target / "student_data/result.json").exists())

    def test_strict_updates_active_config_and_removes_extra(self):
        source, manifest = self.prepare()
        engine = Engine(self.target)
        preview = engine.preview(manifest, mode="strict")
        engine.apply(manifest, source, mode="strict", expected_actual=preview["actual"])
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), (self.source / "TrainTaskInfo.json").read_bytes())
        self.assertFalse((self.target / "app/hat/hat20.py").exists())
        self.assertFalse((self.target / "student_data/result.json").exists())
        self.assertEqual((self.target / "app.log").read_bytes(), b"log")

    def test_changes_after_check_require_new_confirmation(self):
        source, manifest = self.prepare()
        engine = Engine(self.target)
        checked = engine.preview(manifest, mode="strict")
        (self.target / "TrainTaskInfo.json").write_bytes(b'[{"changed":"after check"}]')
        with self.assertRaisesRegex(SyncError, "重新检查"):
            engine.apply(manifest, source, mode="strict", expected_actual=checked["actual"])
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), b'[{"changed":"after check"}]')

    def test_incremental_empty_remote_existing_file_does_not_block(self):
        source, manifest = self.prepare()
        entry = next(e for e in manifest["entries"] if e["path"] == "TrainTaskInfo.json")
        entry["size"] = 0
        entry["sha256"] = hashlib.sha256(b"").hexdigest()
        entry["git_sha1"] = hashlib.sha1(b"blob 0\0").hexdigest()
        engine = Engine(self.target)
        self.assertFalse(engine.preview(manifest, mode="incremental")["blocker"])
        self.assertTrue(engine.preview(manifest, mode="strict")["blocker"])

    def test_repeated_incremental_is_noop_and_does_not_replace_backup(self):
        source, manifest = self.prepare()
        engine = Engine(self.target)
        first = engine.apply(manifest, source, mode="incremental")
        record = engine.current.read_bytes()
        with patch.object(source, "download", side_effect=AssertionError("no download")):
            result = engine.apply(manifest, source, mode="incremental")
        self.assertTrue(result["unchanged"])
        self.assertIsNone(result["backup"])
        self.assertEqual(engine.current.read_bytes(), record)
        self.assertTrue((engine.state / "backups" / first["backup"]).exists())

    def test_general_config_copy_is_independent_of_update(self):
        from test_config_versions import write_bundle
        raw = write_bundle(self.target, "交付版本")
        (self.target / "TrainOverviewInfo.json").write_bytes(b'{"title":"original"}')
        result = Engine(self.target).activate_config_version("交付版本")
        self.assertEqual((self.target / "TrainOverviewInfo.json").read_bytes(), raw["TrainOverviewInfo.json"])
        self.assertEqual((Path(result["backup"]) / "TrainOverviewInfo.json").read_bytes(), b'{"title":"original"}')

    def test_edit_during_download_aborts_before_commit(self):
        source, manifest = self.prepare()
        engine = Engine(self.target)
        download = source.download
        def changing_download(*args):
            result = download(*args)
            (self.target / "TrainTaskInfo.json").write_bytes(b'[{"changed":"during download"}]')
            return result
        with patch.object(source, "download", side_effect=changing_download):
            with self.assertRaisesRegex(SyncError, "准备更新期间"):
                engine.apply(manifest, source, mode="strict")
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), b'[{"changed":"during download"}]')
        self.assertTrue((self.target / "app/hat/hat20.py").exists())
