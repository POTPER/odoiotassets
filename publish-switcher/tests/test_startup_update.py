import logging
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import atomic_json, read_json
from publish_switcher.repositories.generate import generate
from publish_switcher.repositories.source import Source
from publish_switcher.sync.engine import Engine
from publish_switcher.updates import release, startup, unified


class StartupUpdateTests(unittest.TestCase):
    def setUp(self):
        handler = logging.NullHandler()
        logger = logging.getLogger("publish-switcher")
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.install = self.base / "tool"
        self.install.mkdir()
        self.target = self.base / "publish"
        self.target.mkdir()
        self.state = release.update_state(self.install)
        self.current = "2026.11.21.5"
        self.sources = [{"url": url, "branch": "main"} for url in (
            "https://gitee.com/potper/odoiotassets", "https://github.com/POTPER/odoiotassets",
        )]
        self.events = []

    def update(self, **options):
        values = dict(
            install=self.install, current=self.current, target=str(self.target), repositories=self.sources,
            presets=[], extensions=[".py", ".json"], release_url=release.DEFAULT_UPDATE_URL,
            profile_id="rk", sync_permissions=False, cancel=threading.Event(),
            settings_path=self.base / "settings.json", event=self.events.append,
        )
        values.update(options)
        return startup.run_startup_update(**values)

    def test_failover_pins_both_updates_and_keeps_integrity_errors_terminal(self):
        def reject_first(url, _, __, repositories):
            attempts.append((url, repositories))
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
            return {"version": self.current}, False

        attempts = []
        with patch.object(release, "check_release", side_effect=reject_first), \
                patch.object(unified, "discover", side_effect=SyncError("文件校验失败")) as discover:
            result = self.update()
        self.assertFalse(result["success"])
        self.assertEqual([entry[1] for entry in attempts], [[self.sources[0]], [self.sources[1]]])
        self.assertIn("raw.githubusercontent.com", attempts[-1][0])
        self.assertEqual(discover.call_args.args[0], [self.sources[1]])
        self.assertEqual(result["local_target"], str(self.target.resolve()))
        self.assertIn("文件校验失败", result["error"])

    def test_required_version_missing_target_and_pending_transaction_block_local_use(self):
        failure = OSError("offline")
        with patch.object(release, "check_release", side_effect=failure):
            self.assertIn("local_target", self.update())
            required = self.state / "required.json"
            atomic_json(required, {"version": "2099.1"})
            blocked = self.update()
            self.assertNotIn("local_target", blocked)
            self.assertIn("必更", blocked["local_error"])
            required.unlink()
            missing = self.update(target=str(self.base / "missing"))
            self.assertNotIn("local_target", missing)
            atomic_json(self.state / "pending.json", {"phase": "unknown"})
            self.assertNotIn("local_target", self.update())

    def test_missing_publish_allows_program_update_and_resume(self):
        target = self.base / "missing"
        new_version = "2099.1"
        remote = {"version": new_version, "size": 1}
        with patch.object(release, "check_release", return_value=(remote, True)), \
                patch.object(release, "prepare_online") as prepare, patch.object(unified, "discover") as discover:
            result = self.update(target=str(target))
        prepare.assert_called_once()
        discover.assert_not_called()
        self.assertFalse(target.exists())
        self.assertTrue(result["success"])
        self.assertTrue(result["publish_skipped"])
        self.assertTrue(result["restart"])
        self.assertIn("connected", [event["phase"] for event in self.events])
        self.assertNotIn("target", result)

        atomic_json(self.state / "combined-update.json", dict(result, phase="complete", program="更新成功"))
        with patch.object(release, "check_release") as check:
            resumed = startup.resume_startup_update(self.install, new_version, str(target), None)
        check.assert_not_called()
        self.assertTrue(resumed["success"])
        self.assertFalse(resumed["restart"])
        self.assertNotIn("target", resumed)

    def test_strict_publish_update_reports_unique_downloads_and_skips_unchanged(self):
        origin = self.base / "origin"
        origin.mkdir()
        task = "TrainTaskInfo.json"
        files = {"main.py": b"print('updated')\n", "copy.py": b"print('updated')\n", task: b'[{"updated": true}]'}
        for name, content in files.items():
            (origin / name).write_bytes(content)
        (self.target / task).write_bytes(b"[]")
        (self.target / "removed.py").write_bytes(b"")
        repo = self.base / "repository"
        manifest = read_json(generate(origin, repo, "rk", "RK", "1", extensions=[".py", ".json"]))
        source = Source(local=repo)
        with patch.object(release, "check_release", return_value=({"version": self.current}, False)), \
                patch.object(unified, "discover", return_value=[{"source": source, "manifest": manifest}]):
            self.assertTrue(self.update()["success"])
            transfers = [value for value in self.events if value["phase"] == "publish-download"]
            total = len(files[task]) + len(files["main.py"])
            self.assertTrue(transfers)
            self.assertEqual(transfers[-1]["received"], total)
            self.assertTrue(all(event["total"] == total and event["received"] <= total for event in transfers))
            self.assertEqual((self.target / task).read_bytes(), files[task])
            self.assertFalse((self.target / "removed.py").exists())
            self.events.clear()
            self.assertEqual(self.update()["publish"], "已是最新版")
            self.assertFalse(any(event["phase"] == "publish-download" for event in self.events))

    def test_startup_recovers_publish_moved_to_backup_before_checking_network(self):
        engine = Engine(self.target)
        (self.target / "kept.py").write_bytes(b"previous")
        self.target.rename(engine.state / "backups" / "interrupted")
        stage = engine.state / "stage-interrupted"
        stage.mkdir()
        atomic_json(engine.journal, dict(phase="prepared", backup="interrupted", stage=stage.name,
                                         had_target=True, old_state=None, new_state={}))

        def unavailable(url, *args, **kwargs):
            self.assertEqual((self.target / "kept.py").read_bytes(), b"previous")
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)

        with patch.object(release, "check_release", side_effect=unavailable) as check:
            result = self.update()
        self.assertEqual(check.call_count, 2)
        self.assertEqual(result["local_target"], str(self.target.resolve()))
        self.assertFalse(engine.journal.exists())
        self.assertFalse(stage.exists())

    def test_cancel_at_handoff_when_publish_has_no_changes(self):
        cancel = threading.Event()

        def event(value):
            if value["phase"] == "prepared":
                cancel.set()

        origin = self.base / "origin"
        origin.mkdir()
        for directory in (origin, self.target):
            (directory / "main.py").write_bytes(b"pass\n")
        repo = self.base / "repository"
        manifest = read_json(generate(origin, repo, "rk", "RK", "1", extensions=[".py"]))
        remote = {"version": "2026.11.21.6", "size": 1}
        with patch.object(release, "check_release", return_value=(remote, True)) as check, \
                patch.object(release, "prepare_online"), \
                patch.object(unified, "discover", return_value=[{"source": Source(local=repo), "manifest": manifest}]):
            result = self.update(cancel=cancel, event=event)
        self.assertTrue(result["cancelled"])
        self.assertFalse(result["restart"])
        self.assertFalse(result["retry_source"])
        self.assertEqual(result["program"], "未安装")
        check.assert_called_once()

    def test_resume_reads_result_without_a_second_update(self):
        record = self.state / "combined-update.json"
        atomic_json(record, dict(phase="complete", success=True, program_version=self.current, restart=True))
        result = startup.resume_startup_update(self.install, self.current, str(self.target), None)
        self.assertTrue(result["success"])
        self.assertFalse(result["restart"])
        atomic_json(record, dict(phase="failed", success=False, error="启动探测失败"))
        atomic_json(self.state / "required.json", {"version": "2099.1"})
        result = startup.resume_startup_update(self.install, self.current, str(self.target), None)
        self.assertEqual(result["error"], "启动探测失败")
        self.assertNotIn("local_target", result)
