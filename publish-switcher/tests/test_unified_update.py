import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sync
from core import Engine, Source, SyncError, scan, operation_lock
import tool_update
import unified_update as combined


class UnifiedUpdateTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp
    build = test_sync.SyncTests.build

    def fixture(self):
        handler = logging.NullHandler()
        logging.getLogger("publish-switcher").addHandler(handler)
        self.addCleanup(logging.getLogger("publish-switcher").removeHandler, handler)
        self.install = self.base / "switcher"
        self.install.mkdir()
        (self.install / "old.py").write_bytes(b"original tool")
        source, manifest = self.build()
        manifest["id"] = "rk"
        self.manifest = manifest
        self.item = {"source": source, "manifest": manifest}
        self.current = "2026.11.20.6"
        self.release = {"version": self.current, "notes": "same"}
        self.newer = False
        self.discovery = patch("unified_update.discover", return_value=[self.item]).start()
        self.check = patch("tool_update.check_release", side_effect=lambda *args, **kwargs: (self.release, self.newer)).start()
        self.addCleanup(patch.stopall)

    def update(self, **kwargs):
        values = dict(install=self.install, current=self.current, target=str(self.target), repositories=[],
                      presets=[], extensions=[".py", ".json"], release_url="https://example.org/update.json")
        values.update(kwargs)
        return combined.run_update(**values)

    def new_program(self):
        package = self.base / "tool.zip"
        version = "2026.11.20.9"
        with zipfile.ZipFile(package, "w") as archive:
            for name in tool_update.REQUIRED_FILES:
                value = "VERSION = {!r}\n".format(version) if name == "version.py" else ""
                if name == "switcher.py":
                    value = "print({!r})\n".format("Publish Switcher " + version)
                archive.writestr("publish-switcher/" + name, value)
        self.release = dict(version=version, notes="new", schema_version=1, product="publish-switcher",
                            url="https://example.org/tool.zip", package_file="tool.zip", size=package.stat().st_size,
                            sha256=hashlib.sha256(package.read_bytes()).hexdigest())
        self.newer = True
        mock = patch("tool_update.remote_file", return_value=(Source(local=self.base), "tool.zip"))
        mock.start()
        self.addCleanup(mock.stop)

    def test_one_click_selects_rk_strictly_and_preserves_other_formats(self):
        self.fixture()
        events = []
        result = self.update(event=events.append)
        self.assertTrue(result["success"])
        self.assertEqual(result["publish"], "更新成功")
        self.assertEqual(result["program"], "已是最新版")
        self.assertFalse(result["restart"])
        self.discovery.assert_called_once()
        self.assertEqual(self.discovery.call_args.kwargs["profile"], "rk")
        self.assertFalse((self.target / "app/hat/hat20.py").exists())
        self.assertTrue((self.target / "app/hat/hat30.py").exists())
        self.assertFalse((self.target / "student_data/result.json").exists())
        self.assertEqual((self.target / "AIotApp").read_bytes(), b"")
        self.assertEqual((self.target / "app.log").read_bytes(), b"log")
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), (self.source / "TrainTaskInfo.json").read_bytes())
        self.assertTrue(any(event["phase"] == "publish-commit" and not event["cancellable"] for event in events))
        state = json.loads((tool_update.update_state(self.install) / "combined-update.json").read_text())
        self.assertTrue(state["success"])
        self.assertEqual(state["target"], str(self.target.resolve()))

    def test_already_current_still_checks_both_and_never_redownloads(self):
        self.fixture()
        self.assertTrue(self.update()["success"])
        with patch.object(Source, "download", side_effect=AssertionError("should reuse")):
            result = self.update()
        self.assertEqual(result["publish"], "已是最新版")
        self.assertEqual(self.check.call_count, 2)
        self.assertEqual(self.discovery.call_count, 2)

    def test_both_updates_prepare_tool_then_publish_then_external_install(self):
        self.fixture()
        self.new_program()
        result = self.update()
        self.assertTrue(result["success"])
        self.assertTrue(result["restart"])
        self.assertEqual((self.install / "old.py").read_bytes(), b"original tool")
        self.assertTrue((self.target / "app/hat/hat30.py").exists())
        tool_update.commit_update(self.install)
        self.assertEqual(tool_update.package_version(self.install / "version.py"), self.release["version"])

    def test_only_tool_update_also_works(self):
        self.fixture()
        self.assertTrue(self.update()["success"])
        self.new_program()
        result = self.update()
        self.assertTrue(result["restart"])
        self.assertEqual(result["publish"], "已是最新版")
        tool_update.recover_update(self.install)

    def test_selected_empty_resource_blocks_before_tool_download(self):
        self.fixture()
        self.new_program()
        entry = next(e for e in self.manifest["entries"] if e["path"].endswith("hat30.py"))
        entry.update(size=0, sha256=hashlib.sha256(b"").hexdigest())
        before = scan(self.target)
        with patch("tool_update.prepare_online") as prepare:
            result = self.update()
        self.assertFalse(result["success"])
        self.assertIn("为空", result["error"])
        prepare.assert_not_called()
        self.assertEqual(scan(self.target), before)

    def test_program_download_failure_leaves_publish_untouched(self):
        self.fixture()
        self.new_program()
        before = scan(self.target)
        with patch("tool_update.prepare_online", side_effect=OSError("network failure")):
            result = self.update()
        self.assertFalse(result["success"])
        self.assertEqual(scan(self.target), before)

    def test_publish_download_failure_discards_prepared_tool(self):
        self.fixture()
        self.new_program()
        entry = next(e for e in self.manifest["entries"] if e["path"].endswith("hat30.py"))
        (self.repo / entry["source"]).write_bytes(b"corrupt payload")
        before = scan(self.target)
        result = self.update()
        self.assertFalse(result["success"])
        self.assertEqual(scan(self.target), before)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original tool")
        self.assertFalse((tool_update.update_state(self.install) / "pending.json").exists())

    def test_cancel_after_tool_prepared_discards_it_and_keeps_publish(self):
        self.fixture()
        self.new_program()
        cancel = threading.Event()
        prepare = tool_update.prepare_online
        before = scan(self.target)

        def cancelled(*args, **kwargs):
            value = prepare(*args, **kwargs)
            cancel.set()
            return value

        with patch("tool_update.prepare_online", side_effect=cancelled):
            result = self.update(cancel=cancel)
        self.assertTrue(result["cancelled"])
        self.assertEqual(scan(self.target), before)
        self.assertFalse((tool_update.update_state(self.install) / "pending.json").exists())

    def test_space_permission_and_running_process_fail_before_download(self):
        self.fixture()
        before = scan(self.target)
        for failure in ("没有权限", "publish 仍被程序使用"):
            with patch.object(Engine, "preflight", side_effect=SyncError(failure)):
                result = self.update()
            self.assertIn(failure, result["error"])
        with patch("unified_update.shutil.disk_usage") as space:
            space.return_value.free = 0
            self.assertIn("磁盘空间不足", self.update()["error"])
        self.assertEqual(scan(self.target), before)
        self.check.assert_not_called()

    def test_local_changes_while_preparing_require_fresh_check(self):
        self.fixture()
        self.new_program()
        prepare = tool_update.prepare_online

        def changed(*args, **kwargs):
            value = prepare(*args, **kwargs)
            (self.target / "new-local.py").write_bytes(b"new user code")
            return value

        with patch("tool_update.prepare_online", side_effect=changed):
            result = self.update()
        self.assertFalse(result["success"])
        self.assertIn("本地文件发生变化", result["error"])
        self.assertEqual((self.target / "new-local.py").read_bytes(), b"new user code")

    def test_publish_commit_failure_rolls_back_and_retry_reuses_cache(self):
        self.fixture()
        before = scan(self.target)
        rename = os.rename

        def fail_stage(source, destination):
            if Path(source).name.startswith("stage-") and Path(destination) == self.target:
                raise OSError("directory switch interrupted")
            return rename(source, destination)

        with patch("core.os.rename", side_effect=fail_stage):
            result = self.update()
        self.assertFalse(result["success"])
        self.assertEqual(scan(self.target), before)
        with patch.object(Source, "download", side_effect=AssertionError("cache should be reused")):
            self.assertTrue(self.update()["success"])

    def test_tool_helper_or_probe_failure_keeps_successful_publish(self):
        self.fixture()
        self.new_program()
        result = self.update()
        publish = scan(self.target)
        with patch("tool_update.launch_update_helper", side_effect=OSError("helper failed")):
            with self.assertRaises(OSError):
                combined.start_restart(self.install, result)
        self.assertEqual(result["publish"], "更新成功")
        self.assertFalse(result["success"])
        self.assertEqual(scan(self.target), publish)
        result = self.update()
        with patch("tool_update.subprocess.run") as probe:
            probe.return_value.returncode = 1
            probe.return_value.stderr = "probe failed"
            with self.assertRaises(tool_update.UpdateError):
                tool_update.commit_update(self.install)
        self.assertEqual(scan(self.target), publish)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original tool")

    def test_missing_or_nested_paths_stop_and_custom_profile_is_used(self):
        self.fixture()
        self.assertFalse(self.update(target=str(self.base / "missing"))["success"])
        nested = self.install / "publish"
        nested.mkdir()
        self.assertIn("互相包含", self.update(target=str(nested))["error"])
        self.assertIn("设置文件", self.update(settings_path=self.target / "settings.json")["error"])
        result = self.update(profile_id="jetson")
        self.assertTrue(result["success"])
        self.assertEqual(self.discovery.call_args.kwargs["profile"], "jetson")

    def test_default_hyphen_path_before_underscore_and_saved_path_is_authoritative(self):
        first, second = self.base / "linux-arm64/publish", self.base / "linux_arm64/publish"
        second.mkdir(parents=True)
        defaults = (str(first), str(second))
        self.assertEqual(combined.resolve_target(defaults=defaults), second.resolve())
        first.mkdir(parents=True)
        self.assertEqual(combined.resolve_target(defaults=defaults), first.resolve())
        self.assertEqual(combined.resolve_target(str(second), defaults), second.resolve())
        with self.assertRaises(SyncError):
            combined.resolve_target(str(self.base / "nonexistent"), defaults)

    def test_second_operation_cannot_overwrite_first_operation_summary(self):
        self.fixture()
        state = tool_update.update_state(self.install)
        summary = state / "combined-update.json"
        summary.write_bytes(b"original summary")
        with operation_lock(state / "combined.lock"):
            result = self.update()
        self.assertFalse(result["success"])
        self.assertEqual(summary.read_bytes(), b"original summary")

    def test_external_helper_records_combined_success_and_failure(self):
        self.fixture()
        self.new_program()
        result = self.update()
        state = tool_update.update_state(self.install)
        with patch("tool_update.launch_update_helper"):
            combined.start_restart(self.install, result)
        with patch.object(sys, "argv", ["helper", "--apply", str(self.install)]), \
                patch("tool_update.os.chdir"), \
                patch("tool_update.os.execv", side_effect=RuntimeError("relaunch intercepted")):
            with self.assertRaisesRegex(RuntimeError, "relaunch intercepted"):
                tool_update.helper_main()
        saved = json.loads((state / "combined-update.json").read_text())
        self.assertTrue(saved["success"])
        self.assertEqual(saved["program"], "更新成功")
        # Prepare another upgrade against the retained fixture, then fail its probe.
        self.newer = True
        result = self.update()
        with patch("tool_update.launch_update_helper"):
            combined.start_restart(self.install, result)
        with patch.object(sys, "argv", ["helper", "--apply", str(self.install)]), \
                patch("tool_update.subprocess.run") as probe, patch("tool_update.os.chdir"), \
                patch("tool_update.os.execv", side_effect=RuntimeError("relaunch intercepted")):
            probe.return_value.returncode = 1
            probe.return_value.stderr = "simulated probe failure"
            with self.assertRaisesRegex(RuntimeError, "relaunch intercepted"):
                tool_update.helper_main()
        saved = json.loads((state / "combined-update.json").read_text())
        self.assertFalse(saved["success"])
        self.assertEqual(saved["publish"], "已是最新版")
        self.assertIn("恢复旧版", saved["program"])
        self.assertIn("simulated probe failure", saved["error"])
        self.assertIn("恢复旧版", combined.last_helper_error(self.install))

    def test_next_click_recovers_a_prepared_tool_left_by_abnormal_exit(self):
        self.fixture()
        self.new_program()
        result = self.update()
        self.assertTrue(result["restart"])
        state, pending, old_stage, backup = tool_update.pending_paths(self.install)
        self.assertTrue(old_stage.is_dir())
        # Simulate losing the GUI after publish completed but before starting the helper.
        result = self.update()
        self.assertTrue(result["success"])
        self.assertEqual(result["publish"], "已是最新版")
        self.assertFalse(old_stage.exists())
        self.assertEqual((self.install / "old.py").read_bytes(), b"original tool")
        self.assertTrue((state / "pending.json").is_file())
        tool_update.recover_update(self.install)
