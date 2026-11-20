import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sync
import config_versions as bundles
from core import Engine, SyncError, atomic_json
from config_versions import CONFIG_NAMES


def write_bundle(target, name="赛事版本1", suffix=""):
    directory = Path(target) / "config" / name
    directory.mkdir(parents=True, exist_ok=True)
    raw = {}
    for active in CONFIG_NAMES:
        payload = ('\ufeff[ {"version": "' + name + '", "file": "' + active + '"} ]\r\n').encode("utf-8")
        (directory / (Path(active).stem + suffix + ".json")).write_bytes(payload)
        raw[active] = payload
    return raw


class ConfigVersionTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def old_configs(self):
        old = {name: ('[{"old":"' + name + '"}]').encode() for name in CONFIG_NAMES}
        for name, raw in old.items():
            (self.target / name).write_bytes(raw)
        return old

    def assert_active(self, raw):
        for name, data in raw.items():
            if data is None:
                self.assertFalse((self.target / name).exists())
            else:
                self.assertEqual((self.target / name).read_bytes(), data)

    def test_dynamic_discovery_suffixes_and_empty_folders(self):
        write_bundle(self.target, "福建农职", "_福建农职")
        write_bundle(self.target, "赛事版本1")
        for name in ("标准交付", "教学版本1"):
            (self.target / "config" / name).mkdir()
        (self.target / "config/TrainTaskInfo_old.json").write_bytes(b"[]")
        items = {p["version"]: p for p in Engine(self.target).list_config_versions()}
        self.assertEqual(set(items), {"福建农职", "赛事版本1", "标准交付", "教学版本1"})
        self.assertTrue(items["福建农职"]["valid"])
        self.assertFalse(items["标准交付"]["valid"])
        self.assertEqual(len(items["标准交付"]["issues"]), 3)
        os.rename(self.target / "config/赛事版本1", self.target / "config/重命名版本")
        self.assertIn("重命名版本", [p["version"] for p in Engine(self.target).list_config_versions()])

    def test_apply_three_bytes_preserves_sources_and_other_files(self):
        new, old = write_bundle(self.target, "福建农职", "_福建农职"), self.old_configs()
        engine = Engine(self.target)
        preview = engine.preview_config_version("福建农职")
        result = engine.activate_config_version("福建农职", expected_snapshot=preview["snapshot"])
        self.assert_active(new)
        for name in CONFIG_NAMES:
            self.assertEqual((Path(result["backup"]) / name).read_bytes(), old[name])
            self.assertEqual((self.target / "config/福建农职" / (Path(name).stem + "_福建农职.json")).read_bytes(), new[name])
        self.assertEqual((self.target / "app.log").read_bytes(), b"log")
        self.assertTrue((self.target / "student_data/result.json").exists())
        self.assertEqual(engine.task_config_status(), "配置版本：福建农职")

    def test_uppercase_extension_and_no_suffix(self):
        write_bundle(self.target)
        path = self.target / "config/赛事版本1/TrainOverviewInfo.json"
        os.rename(path, path.with_suffix(".JSON"))
        self.assertTrue(Engine(self.target).preview_config_version("赛事版本1")["valid"])

    def test_duplicate_does_not_prefer_exact_name(self):
        write_bundle(self.target)
        (self.target / "config/赛事版本1/TrainTaskInfo_backup.json").write_bytes(b"[]")
        old = self.old_configs()
        engine = Engine(self.target)
        self.assertIn("冲突", " ".join(engine.preview_config_version("赛事版本1")["issues"]))
        with self.assertRaises(SyncError):
            engine.activate_config_version("赛事版本1")
        self.assert_active(old)

    def test_missing_and_invalid_json_do_not_change_active(self):
        write_bundle(self.target)
        old = self.old_configs()
        path = self.target / "config/赛事版本1/TrainOverviewInfo.json"
        for bad in (None, b"", b"{broken", b"42"):
            if bad is None:
                path.unlink()
            else:
                path.write_bytes(bad)
            with self.subTest(bad=bad), self.assertRaises(SyncError):
                Engine(self.target).activate_config_version("赛事版本1")
            self.assert_active(old)

    def test_unreadable_version_has_reason(self):
        write_bundle(self.target)
        original = Path.iterdir
        def denied(path):
            if path.name == "赛事版本1":
                raise PermissionError("test unreadable directory")
            return original(path)
        with patch.object(Path, "iterdir", denied):
            item = Engine(self.target).list_config_versions()[0]
        self.assertFalse(item["valid"])
        self.assertIn("unreadable", item["issues"][0])

    def test_changed_source_or_active_after_preview_is_rejected(self):
        write_bundle(self.target)
        old = self.old_configs()
        engine = Engine(self.target)
        preview = engine.preview_config_version("赛事版本1")
        (self.target / "config/赛事版本1/TrainOverviewInfo.json").write_bytes(b"[]")
        with self.assertRaisesRegex(SyncError, "重新检查"):
            engine.activate_config_version("赛事版本1", expected_snapshot=preview["snapshot"])
        self.assert_active(old)
        preview = engine.preview_config_version("赛事版本1")
        (self.target / "TrainTaskInfo.json").write_bytes(b"[]")
        with self.assertRaisesRegex(SyncError, "重新检查"):
            engine.activate_config_version("赛事版本1", expected_snapshot=preview["snapshot"])

    def test_change_during_preparation_does_not_commit(self):
        write_bundle(self.target)
        old = self.old_configs()
        writer = bundles._write_file
        def changing(path, raw, mode):
            writer(path, raw, mode)
            if path.parent.name.startswith("config-stage-"):
                (self.target / "config/赛事版本1/TrainOverviewInfo.json").write_bytes(b"[]")
        with patch("config_versions._write_file", side_effect=changing):
            with self.assertRaisesRegex(SyncError, "重新检查"):
                Engine(self.target).activate_config_version("赛事版本1")
        self.assert_active(old)

    def test_second_replace_failure_restores_whole_set(self):
        write_bundle(self.target)
        old = self.old_configs()
        replace = os.replace
        def failing(src, dest):
            if Path(src).parent.name.startswith("config-stage-") and Path(src).name == CONFIG_NAMES[1]:
                raise PermissionError("injected second replacement failure")
            return replace(src, dest)
        with patch("config_versions.os.replace", side_effect=failing):
            with self.assertRaises(PermissionError):
                Engine(self.target).activate_config_version("赛事版本1")
        self.assert_active(old)
        self.assertFalse((Engine(self.target).state / "config-transaction.json").exists())

    def test_failure_removes_files_that_originally_did_not_exist(self):
        write_bundle(self.target)
        old = self.old_configs()
        (self.target / CONFIG_NAMES[0]).unlink()
        old[CONFIG_NAMES[0]] = None
        replace = os.replace
        def failing(src, dest):
            if Path(src).parent.name.startswith("config-stage-") and Path(src).name == CONFIG_NAMES[2]:
                raise OSError("injected last failure")
            return replace(src, dest)
        with patch("config_versions.os.replace", side_effect=failing):
            with self.assertRaises(OSError):
                Engine(self.target).activate_config_version("赛事版本1")
        self.assert_active(old)

    def pending(self, count, committed=False):
        engine = Engine(self.target)
        preview = engine.preview_config_version("赛事版本1")
        token = "crash-" + str(count)
        backup = engine.state / "config-backups" / token
        backup.mkdir(parents=True)
        stage = engine.state / ("config-stage-crash-" + str(count))
        stage.mkdir()
        for name in CONFIG_NAMES:
            if preview["snapshot"]["active"][name]["exists"]:
                (backup / name).write_bytes((self.target / name).read_bytes())
            (stage / name).write_bytes((self.target / "config/赛事版本1" / name).read_bytes())
        data = {"schema_version": 1, "phase": "committed" if committed else "prepared", "token": token,
                "stage": stage.name, "version": "赛事版本1", "old": preview["snapshot"]["active"]}
        for name in CONFIG_NAMES[:count]:
            os.replace(stage / name, self.target / name)
        atomic_json(engine.state / "config-transaction.json", data)
        return engine, backup

    def test_startup_recovers_interrupted_bundle_at_each_phase(self):
        write_bundle(self.target)
        old = self.old_configs()
        for count in (0, 1, 2, 3):
            with self.subTest(replacements=count):
                engine, backup = self.pending(count)
                self.assertTrue(engine.startup_recover())
                self.assert_active(old)
                self.assertFalse(engine.startup_recover())

    def test_committed_transaction_is_finalized_without_rollback(self):
        new = write_bundle(self.target)
        self.old_configs()
        engine, backup = self.pending(3, committed=True)
        engine.startup_recover()
        self.assert_active(new)

    def test_missing_backup_blocks_recovery_before_partial_restore(self):
        write_bundle(self.target)
        old = self.old_configs()
        engine, backup = self.pending(1)
        (backup / CONFIG_NAMES[2]).unlink()
        before = {n: (self.target / n).read_bytes() for n in CONFIG_NAMES}
        with self.assertRaisesRegex(SyncError, "备份不完整"):
            engine.startup_recover()
        self.assert_active(before)
        (backup / CONFIG_NAMES[2]).write_bytes(old[CONFIG_NAMES[2]])
        engine.startup_recover()
        self.assert_active(old)

    def test_current_version_uses_all_files_and_handles_multiple_matches(self):
        raw = write_bundle(self.target, "版本甲")
        directory = self.target / "config/版本乙"
        directory.mkdir()
        for name, data in raw.items():
            (directory / name).write_bytes(data)
        engine = Engine(self.target)
        engine.activate_config_version("版本甲")
        status = engine.task_config_status()
        self.assertIn("多个版本", status)
        self.assertIn("版本甲", status)
        self.assertIn("版本乙", status)
        (self.target / CONFIG_NAMES[1]).write_bytes(b"[]")
        self.assertIn("自定义", engine.task_config_status())

    def test_old_single_config_commands_and_path_escape_are_rejected(self):
        engine = Engine(self.target)
        with self.assertRaisesRegex(SyncError, "config apply"):
            engine.activate_competition()
        with self.assertRaises(SyncError):
            engine.activate_config("old.json", "TrainTaskInfo.json")
        with self.assertRaises(SyncError):
            engine.activate_config_version("../outside")

    @unittest.skipUnless(sys.platform == "linux", "Requires POSIX symlinks")
    def test_symlink_config_version_and_source_are_rejected(self):
        write_bundle(self.target)
        engine = Engine(self.target)
        (self.target / "config/link").symlink_to(self.target / "config/赛事版本1", target_is_directory=True)
        self.assertFalse(next(p for p in engine.list_config_versions() if p["version"] == "link")["valid"])
        path = self.target / "config/赛事版本1/TrainTaskInfo.json"
        path.unlink()
        path.symlink_to(self.source / "TrainTaskInfo.json")
        with self.assertRaises(SyncError):
            engine.activate_config_version("赛事版本1")
