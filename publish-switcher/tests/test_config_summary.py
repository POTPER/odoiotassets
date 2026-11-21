import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sync
from test_config_versions import write_bundle
from tools.packaging.legacy.core import Engine, SyncError, atomic_json, scan
from publish_switcher.configuration.visibility import validate_policy, resolve_version
from publish_switcher.configuration import versions as config_versions


class ConfigSummaryTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def active(self, payload):
        for name, raw in payload.items():
            (self.target / name).write_bytes(raw)

    def test_optional_metadata_roundtrips_without_overriding_directory_identity(self):
        payload = write_bundle(self.target, "课堂目录")
        self.active(payload)
        atomic_json(self.target / "config/versions.json", {"versions": {"课堂目录": {
            "display_name": "课堂版", "release_version": "v1.2.0", "updated_at": "2026-11-20 12:34:56",
            "description": "教学配置", "order": -1}}})
        before = scan(self.target)
        summary = Engine(self.target).config_summary(user_only=True)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["current_label"], "配置版本：课堂版")
        self.assertEqual(summary["read_state"], "ready")
        row = summary["versions"][0]
        self.assertTrue(row["active"])
        self.assertEqual(row["version"], "课堂目录")
        self.assertEqual(row["release_version"], "v1.2.0")
        self.assertEqual(row["updated_at"], "2026-11-20 12:34:56")
        self.assertEqual(scan(self.target), before)

    def test_old_policy_and_missing_metadata_remain_supported(self):
        write_bundle(self.target, "教学")
        atomic_json(self.target / "config/versions.json", {"rules": [], "versions": {"教学": {"order": 3}}})
        summary = Engine(self.target).config_summary(user_only=True)
        self.assertEqual(summary["versions"][0]["release_version"], "")
        self.assertEqual(summary["versions"][0]["updated_at"], "")
        self.assertEqual(summary["versions"][0]["description"], "")
        self.assertEqual(summary["read_state"], "missing")
        self.assertEqual(summary["current_name"], "自定义／未识别")
        self.assertFalse(summary["versions"][0]["active"])

    def test_hidden_current_and_multiple_matches_do_not_leak_hidden_names(self):
        payload = write_bundle(self.target, "F内部")
        self.active(payload)
        write_bundle(self.target, "普通")
        engine = Engine(self.target)
        summary = engine.config_summary(user_only=True)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["current_name"], "实施配置")
        self.assertNotIn("F内部", json.dumps(summary, ensure_ascii=False))
        for version in ("公开一", "公开二"):
            write_bundle(self.target, version)
            for name, raw in payload.items():
                (self.target / "config" / version / name).write_bytes(raw)
        summary = engine.config_summary(user_only=True)
        self.assertIn("匹配多个版本", summary["current_name"])
        self.assertEqual({v["version"] for v in summary["versions"] if v["active"]}, {"公开一", "公开二"})
        self.assertNotIn("F内部", summary["current_name"])

    def test_invalid_json_and_schema_are_not_marked_readable_or_active(self):
        payload = write_bundle(self.target)
        self.active(payload)
        for raw in (b"{broken", b"{}", b"\xff\xfe"):
            (self.target / "TrainTaskInfo.json").write_bytes(raw)
            summary = Engine(self.target).config_summary(user_only=True)
            self.assertEqual(summary["read_state"], "invalid")
            self.assertFalse(summary["versions"][0]["active"])
            self.assertTrue(summary["issues"])

    @unittest.skipUnless(os.name == "posix", "requires symlinks")
    def test_active_symlink_cannot_be_reported_readable(self):
        payload = write_bundle(self.target)
        self.active(payload)
        path = self.target / "TrainTaskInfo.json"
        path.unlink()
        path.symlink_to(self.target / "config/赛事版本1/TrainTaskInfo.json")
        self.assertEqual(Engine(self.target).config_summary(user_only=True)["read_state"], "invalid")

    def test_invalid_metadata_is_rejected_and_engineer_can_still_inspect(self):
        write_bundle(self.target)
        for field, value in (("release_version", 10), ("description", "x"*513), ("updated_at", "bad\ntime")):
            policy = {"versions": {"赛事版本1": {field: value}}}
            with self.assertRaises(SyncError):
                validate_policy(policy)
        atomic_json(self.target / "config/versions.json", {"versions": {"赛事版本1": {"release_version": 10}}})
        with self.assertRaises(SyncError):
            Engine(self.target).config_summary(user_only=True)
        self.assertEqual(len(Engine(self.target).config_summary()["versions"]), 1)

    def test_empty_catalog_and_changes_during_reading_are_reported_honestly(self):
        summary = Engine(self.target).config_summary(user_only=True)
        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["versions"], [])
        self.active(write_bundle(self.target))
        original = Path.read_bytes
        def changing(path):
            value = original(path)
            if path == self.target / "TrainOverviewInfo.json":
                (self.target / "TrainTaskInfo.json").write_bytes(b"[] modified externally")
            return value
        with patch.object(Path, "read_bytes", changing):
            summary = Engine(self.target).config_summary(user_only=True)
        self.assertEqual(summary["read_state"], "invalid")
        self.assertFalse(any(v["active"] for v in summary["versions"]))

    def test_policy_change_while_reading_requires_refresh(self):
        write_bundle(self.target)
        original = config_versions.list_versions
        def changed(engine, *args, **kwargs):
            value = original(engine, *args, **kwargs)
            atomic_json(self.target / "config/versions.json", {"default_user_visible": False})
            return value
        with patch("publish_switcher.configuration.versions.list_versions", side_effect=changed), self.assertRaisesRegex(SyncError, "规则发生变化"):
            Engine(self.target).config_summary(user_only=True)
