import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config_versions as bundles
import test_sync
from core import Engine, SyncError, Cancelled, atomic_json
from test_config_versions import write_bundle


class ConfigComparisonTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def prepare(self, old=b'[{"PythonScriptPath":"old-script.py"}]', new=b'[{"PythonScriptPath":"new-script.py"}]'):
        write_bundle(self.target, "福建农职", "_福建农职")
        self.active = self.target / "TrainTaskInfo.json"
        self.template = self.target / "config/福建农职/TrainTaskInfo_福建农职.json"
        if old is not None:
            self.active.write_bytes(old)
        self.template.write_bytes(new)
        self.engine = Engine(self.target)

    def compare(self, snapshot=None):
        return self.engine.compare_config_file("福建农职", "TrainTaskInfo.json", snapshot)

    def test_content_diff_direction_paths_and_no_changes(self):
        self.prepare()
        before = {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        report = self.compare()
        self.assertEqual(report["status"], "内容不同")
        self.assertIn("_福建农职.json", report["source_path"])
        rows = report["json_diff"]["rows"]
        self.assertTrue(any(row["kind"] == "delete" and "old-script.py" in row["text"] for row in rows))
        self.assertTrue(any(row["kind"] == "add" and "new-script.py" in row["text"] for row in rows))
        self.assertIn("当前生效/TrainTaskInfo.json", rows[0]["text"])
        self.assertIn("版本模板/TrainTaskInfo.json", rows[1]["text"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()})
        summary = bundles.format_comparison(report, include_diff=False)
        self.assertNotIn("old-script.py", summary)
        self.assertNotIn("new-script.py", summary)
        self.assertIn("\x1b[32m", bundles.format_comparison(report, color=True))

    def test_formatting_bom_object_order_and_apply_original_bytes(self):
        new = b'\xef\xbb\xbf[ {"a": 1, "b": 2} ]\r\n'
        self.prepare(old=b'[{"b":2,"a":1}]', new=new)
        preview = self.engine.preview_config_version("福建农职")
        report = self.compare(preview["snapshot"])
        self.assertEqual(report["status"], "仅 JSON 格式不同")
        self.assertEqual(report["json_diff"]["kind"], "same")
        self.assertFalse(report["byte_equal"])
        self.assertEqual(report["raw_diff"]["kind"], "changes")
        self.engine.activate_config_version("福建农职", preview["snapshot"])
        self.assertEqual(self.active.read_bytes(), new)

    def test_identical_bytes_have_no_diff(self):
        self.prepare(old=b'[{"same":true}]', new=b'[{"same":true}]')
        report = self.compare()
        self.assertEqual(report["status"], "相同")
        self.assertEqual(report["raw_diff"]["rows"], [])
        self.assertEqual(report["json_diff"]["rows"], [])

    def test_array_order_and_boolean_number_changes_are_visible(self):
        for old, new in ((b'[1,2]', b'[2,1]'), (b'[1]', b'[true]')):
            with self.subTest(old=old):
                self.prepare(old, new)
                report = self.compare()
                self.assertFalse(report["json_equal"])
                self.assertEqual(report["json_diff"]["kind"], "changes")

    def test_missing_active_is_all_additions(self):
        self.prepare(old=None)
        report = self.compare()
        self.assertEqual(report["status"], "新增")
        self.assertFalse(report["active"]["exists"])
        self.assertGreater(report["json_diff"]["added"], 0)
        self.assertEqual(report["json_diff"]["deleted"], 0)
        self.assertFalse(self.active.exists())

    def test_invalid_or_duplicate_json_keeps_raw_comparison(self):
        for old, new, note in ((b'{broken', b'[]', "当前生效"),
                                (b'[{"x":1,"x":2}]', b'[{"x":2}]', "重复字段"),
                                (b'[]', b'[{"x":1,"x":2}]', "版本模板")):
            with self.subTest(note=note):
                self.prepare(old, new)
                report = self.compare()
                self.assertIsNone(report["json_diff"])
                self.assertIn(note, report["json_note"])
                self.assertEqual(report["raw_diff"]["kind"], "changes")
                self.assertEqual(self.active.read_bytes(), old)

    def test_preview_or_read_time_change_rejected(self):
        self.prepare()
        snapshot = self.engine.preview_config_version("福建农职")["snapshot"]
        self.template.write_bytes(b'[]')
        with self.assertRaisesRegex(SyncError, "变化"):
            self.compare(snapshot)
        real = bundles._comparison_bytes
        def change(path, expected, cancel):
            value = real(path, expected, cancel)
            if path == self.template:
                self.active.write_bytes(b'[{"changed":true}]')
            return value
        with patch.object(bundles, "_comparison_bytes", side_effect=change):
            with self.assertRaisesRegex(SyncError, "变化"):
                self.compare()

    def test_unfinished_transaction_is_not_recovered(self):
        self.prepare()
        atomic_json(self.engine.journal, {"pending": True})
        with patch.object(self.engine, "recover") as recover:
            with self.assertRaisesRegex(SyncError, "未完成"):
                self.compare()
            recover.assert_not_called()
        self.assertTrue(self.engine.journal.exists())

    def test_incomplete_bundle_can_compare_its_valid_file(self):
        self.prepare()
        (self.template.parent / "TrainOverviewInfo_福建农职.json").unlink()
        preview = self.engine.preview_config_version("福建农职")
        self.assertFalse(preview["valid"])
        self.assertEqual(self.compare(preview["snapshot"])["status"], "内容不同")

    def test_large_file_limits_and_cancellation(self):
        self.prepare(new=json.dumps(["x" * (1024 * 1024)]).encode())
        report = self.compare()
        self.assertEqual(report["raw_diff"]["kind"], "limited")
        self.assertIsNone(report["json_diff"])
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.engine.compare_config_file("福建农职", "TrainTaskInfo.json", cancel=cancel)

    def test_non_config_name_rejected(self):
        self.prepare()
        with self.assertRaises(SyncError):
            self.engine.compare_config_file("福建农职", "../other.json")

    @unittest.skipUnless(sys.platform == "linux", "Linux symlinks")
    def test_symlink_sources_or_active_are_rejected(self):
        self.prepare()
        self.active.unlink()
        self.active.symlink_to(self.template)
        with self.assertRaises(SyncError):
            self.compare()
        self.active.unlink()
        self.active.write_bytes(b'[]')
        self.template.unlink()
        self.template.symlink_to(self.active)
        with self.assertRaises(SyncError):
            self.compare()
