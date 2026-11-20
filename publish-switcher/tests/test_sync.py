import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
from core import Engine, Source, SyncError, Cancelled, atomic_json, digest, load_profile, scan, validate_manifest
from generate import generate
REAL_ASSERT_STOPPED = core.assert_stopped


class SyncTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).resolve().parent / ".tmp")))
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.target = self.base / "publish"
        self.repo = self.base / "repository"
        self.source.mkdir()
        self.target.mkdir()
        (self.source / "app/hat").mkdir(parents=True)
        (self.source / "空目录").mkdir()
        (self.source / "app/hat/hat30.py").write_bytes(b"print('new')\n")
        (self.source / "AIotApp").write_bytes(b"binary-placeholder-for-test-not-real-app")
        for name in ("TrainTaskInfo.json", "TrainOverviewInfo.json", "CodeSampleTuorialInfo.json"):
            (self.source / name).write_bytes('[{"":null,"名称":"原样保留"}]'.encode())
        (self.target / "app/hat").mkdir(parents=True)
        (self.target / "app/hat/hat20.py").write_bytes(b"old script")
        (self.target / "AIotApp").write_bytes(b"")
        (self.target / "student_data").mkdir()
        (self.target / "student_data/result.json").write_bytes(b"runtime result")
        (self.target / "app.log").write_bytes(b"log")
        self.process_guard = patch("core.assert_stopped")
        self.process_guard.start()
        self.addCleanup(self.process_guard.stop)

    def build(self):
        generate(self.source, self.repo, "competition", "比赛版", "1.0", executable=["app/hat/hat30.py"])
        source = Source(local=self.repo)
        profile = json.loads((self.repo / "catalog.json").read_text(encoding="utf-8"))["profiles"][0]
        return source, load_profile(source, profile)

    def test_strict_apply_restore_and_redo(self):
        source, manifest = self.build()
        old = scan(self.target)
        engine = Engine(self.target)
        preview = engine.preview(manifest)
        self.assertIn(("删除", "student_data/result.json"), preview["changes"])
        result = engine.apply(manifest, source)
        self.assertTrue((self.target / "app.log").exists())
        self.assertFalse((self.target / "app/hat/hat20.py").exists())
        self.assertFalse((self.target / "空目录").exists())
        self.assertEqual((self.target / "AIotApp").read_bytes(), b"")
        self.assertEqual(scan(engine.state / "backups" / result["backup"]), old)
        new = scan(self.target)
        self.assertEqual(engine.preview(manifest)["changes"], [])
        self.assertEqual(engine.preview(manifest)["download_bytes"], 0)
        engine.restore()
        self.assertEqual(scan(self.target), old)
        engine.restore()
        self.assertEqual(scan(self.target), new)

    def test_json_bytes_and_executable_modes(self):
        source, manifest = self.build()
        Engine(self.target).apply(manifest, source)
        self.assertEqual((self.source / "CodeSampleTuorialInfo.json").read_bytes(),
                         (self.target / "CodeSampleTuorialInfo.json").read_bytes())
        if os.name == "posix":
            self.assertTrue((self.target / "app/hat/hat30.py").stat().st_mode & stat.S_IXUSR)

    def test_download_integrity_failure_keeps_target(self):
        source, manifest = self.build()
        original = scan(self.target)
        entry = next(e for e in manifest["entries"] if e["path"] == "app/hat/hat30.py")
        (self.repo / entry["source"]).write_bytes(b"bad")
        with self.assertRaises(SyncError):
            Engine(self.target).apply(manifest, source)
        self.assertEqual(scan(self.target), original)

    def test_network_failure_keeps_target(self):
        source, manifest = self.build()
        original = scan(self.target)
        with patch.object(Source, "download", side_effect=OSError("network down")):
            with self.assertRaises(OSError):
                Engine(self.target).apply(manifest, source)
        self.assertEqual(scan(self.target), original)

    def test_cancel_keeps_target(self):
        source, manifest = self.build()
        original = scan(self.target)
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            Engine(self.target).apply(manifest, source, event)
        self.assertEqual(scan(self.target), original)

    def test_disk_space_failure_keeps_target(self):
        source, manifest = self.build()
        original = scan(self.target)
        with patch("core.shutil.disk_usage", return_value=shutil._ntuple_diskusage(100, 100, 0)):
            with self.assertRaises(SyncError):
                Engine(self.target).apply(manifest, source)
        self.assertEqual(scan(self.target), original)

    def test_rename_failure_rolls_back(self):
        source, manifest = self.build()
        engine = Engine(self.target)
        old = scan(self.target)
        rename = os.rename
        def fail_install(src, dst):
            if Path(src).name.startswith("stage-") and Path(dst) == self.target:
                raise PermissionError("injected install failure")
            return rename(src, dst)
        with patch("core.os.rename", side_effect=fail_install):
            with self.assertRaises(PermissionError):
                engine.apply(manifest, source)
        self.assertEqual(scan(self.target), old)
        self.assertFalse(engine.journal.exists())

    def test_restore_failure_preserves_last_backup(self):
        source, manifest = self.build()
        engine = Engine(self.target)
        original = scan(self.target)
        info = engine.apply(manifest, source)
        current = scan(self.target)
        rename = os.rename
        def fail_restore(src, dst):
            if Path(src).name.startswith("stage-") and Path(dst) == self.target:
                raise PermissionError("injected restore failure")
            return rename(src, dst)
        with patch("core.os.rename", side_effect=fail_restore):
            with self.assertRaises(PermissionError):
                engine.restore()
        self.assertEqual(scan(self.target), current)
        self.assertEqual(scan(engine.state / "backups" / info["backup"]), original)
        engine.restore()
        self.assertEqual(scan(self.target), original)

    def test_offline_reuses_local_then_cache(self):
        source, manifest = self.build()
        engine = Engine(self.target)
        engine.apply(manifest, source)
        # All resources are now cached. Remove an installed file and make origin unavailable.
        (self.target / "app/hat/hat30.py").unlink()
        shutil.rmtree(self.repo)
        self.assertTrue(engine.profiles())
        with patch.object(Source, "download", side_effect=AssertionError("offline download")):
            engine.apply(manifest, source)
        self.assertTrue((self.target / "app/hat/hat30.py").is_file())

    def test_identical_files_do_not_download(self):
        source, manifest = self.build()
        engine = Engine(self.target)
        engine.apply(manifest, source)
        shutil.rmtree(engine.state / "objects")
        (engine.state / "objects").mkdir()
        with patch.object(Source, "download", side_effect=AssertionError("unnecessary download")):
            engine.apply(manifest, source)

    def test_only_py_json_download_and_ignored_resources_survive_restore(self):
        (self.target / "local-model.rknn").write_bytes(b"local model")
        (self.source / "remote-model.rknn").write_bytes(b"remote model")
        source, manifest = self.build()
        engine = Engine(self.target)
        preview = engine.preview(manifest)
        self.assertIn(("仅提示：本机缺失，不下载", "remote-model.rknn"), preview["notices"])
        self.assertNotIn(("删除", "local-model.rknn"), preview["changes"])
        download = source.download
        locations = []
        def track(location, *args):
            locations.append(location)
            return download(location, *args)
        with patch.object(source, "download", side_effect=track):
            engine.apply(manifest, source)
        self.assertTrue(locations)
        self.assertTrue(all(Path(location).suffix in (".py", ".json") for location in locations))
        self.assertFalse((self.target / "remote-model.rknn").exists())
        self.assertEqual((self.target / "local-model.rknn").read_bytes(), b"local model")
        (self.target / "local-model.rknn").unlink()
        (self.target / "local-model.rknn").write_bytes(b"new local model")
        engine.restore()
        self.assertEqual((self.target / "local-model.rknn").read_bytes(), b"new local model")
        self.assertTrue((self.target / "app.log").exists())

    def test_legacy_empty_binary_blocker_is_ignored(self):
        source, manifest = self.build()
        manifest["blocked_reason"] = "旧版本提示空模型"
        Engine(self.target).apply(manifest, source)
        self.assertEqual((self.target / "AIotApp").read_bytes(), b"")

    def test_recover_interruption_before_and_after_install(self):
        for installed in (False, True):
            with self.subTest(installed=installed):
                engine = Engine(self.target)
                old = scan(self.target)
                backup = engine.state / "backups" / "crash"
                stage = engine.state / "stage-crash"
                stage.mkdir()
                (stage / "new").write_bytes(b"new")
                atomic_json(engine.journal, {"phase": "prepared", "backup": "crash", "stage": "stage-crash",
                                            "had_target": True, "old_state": None, "new_state": {}})
                os.rename(self.target, backup)
                if installed:
                    os.rename(stage, self.target)
                self.assertTrue(engine.startup_recover())
                self.assertEqual(scan(self.target), old)
                self.assertFalse(engine.journal.exists())

    def test_recover_committed_finalizes_state(self):
        engine = Engine(self.target)
        backup = engine.state / "backups" / "committed"
        os.rename(self.target, backup)
        self.target.mkdir()
        (self.target / "new").write_bytes(b"committed")
        info = {"id": "new", "version": "1", "backup": "committed"}
        atomic_json(engine.journal, {"phase": "committed", "backup": "committed", "stage": "stage-gone",
                                    "had_target": True, "old_state": None, "new_state": info})
        engine.startup_recover()
        self.assertTrue((self.target / "new").exists())
        self.assertEqual(core.read_json(engine.current), info)

    def test_crash_restore_before_journal_returns_backup(self):
        source, manifest = self.build()
        engine = Engine(self.target)
        old = scan(self.target)
        info = engine.apply(manifest, source)
        backup = engine.state / "backups" / info["backup"]
        stage = engine.state / "restore-crash"
        atomic_json(engine.state / "restore-source.json", {"backup": info["backup"], "stage": stage.name})
        os.rename(backup, stage)
        engine.startup_recover()
        self.assertEqual(scan(backup), old)

    def test_crash_restore_after_install_keeps_both_versions(self):
        source, manifest = self.build()
        engine = Engine(self.target)
        old = scan(self.target)
        info = engine.apply(manifest, source)
        new = scan(self.target)
        original_backup = engine.state / "backups" / info["backup"]
        stage = engine.state / "restore-crash"
        rollback_backup = engine.state / "backups" / "restore-crash-backup"
        atomic_json(engine.state / "restore-source.json", {"backup": info["backup"], "stage": stage.name})
        os.rename(original_backup, stage)
        atomic_json(engine.journal, {"phase": "prepared", "backup": rollback_backup.name, "stage": stage.name,
                                    "had_target": True, "old_state": info, "new_state": {}})
        os.rename(self.target, rollback_backup)
        os.rename(stage, self.target)
        engine.startup_recover()
        self.assertEqual(scan(self.target), new)
        self.assertEqual(scan(original_backup), old)

    def test_zero_byte_requires_explicit_allow(self):
        (self.source / "empty.py").touch()
        with self.assertRaises(SyncError):
            self.build()
        self.assertFalse(self.repo.exists())
        generate(self.source, self.repo, "test", "test", "1", allow_empty=["empty.py"])

    def test_invalid_paths_and_missing_parents(self):
        source, manifest = self.build()
        for path in ("../oops", "/etc/passwd", "a/../../oops", "C:/oops", "a\\b"):
            bad = json.loads(json.dumps(manifest))
            bad["entries"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(SyncError):
                validate_manifest(bad)
        bad = json.loads(json.dumps(manifest))
        bad["entries"] = [e for e in bad["entries"] if e["path"] != "app"]
        with self.assertRaises(SyncError):
            validate_manifest(bad)

    def test_manifest_tamper(self):
        source, manifest = self.build()
        profile = core.read_json(self.repo / "catalog.json")["profiles"][0]
        (self.repo / profile["manifest"]).write_text("{}", encoding="utf-8")
        with self.assertRaises(SyncError):
            load_profile(source, profile)

    def test_symlink_validation(self):
        source, manifest = self.build()
        for links in ([{"path": "escape", "type": "symlink", "target": "../outside"}],
                      [{"path": "a", "type": "symlink", "target": "b"}, {"path": "b", "type": "symlink", "target": "a"}],
                      [{"path": "missing", "type": "symlink", "target": "not-found"}]):
            bad = json.loads(json.dumps(manifest))
            bad["entries"].extend(links)
            with self.assertRaises(SyncError):
                validate_manifest(bad)

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks and modes require Linux")
    def test_symlink_and_permissions_roundtrip(self):
        os.symlink("app/hat/hat30.py", self.source / "current.py")
        os.symlink("AIotApp", self.target / "local-link")
        old_root_mode = stat.S_IMODE(self.target.stat().st_mode)
        old_app_mode = stat.S_IMODE((self.target / "app").stat().st_mode)
        os.chmod(self.source / "app", 0o750)
        os.chmod(self.source, 0o750)
        source, manifest = self.build()
        Engine(self.target).apply(manifest, source)
        self.assertFalse((self.target / "current.py").exists())
        self.assertEqual(os.readlink(self.target / "local-link"), "AIotApp")
        self.assertEqual(stat.S_IMODE((self.target / "app").stat().st_mode), old_app_mode)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), old_root_mode)

    def test_running_process_blocks_apply(self):
        source, manifest = self.build()
        original = scan(self.target)
        with patch("core.assert_stopped", side_effect=SyncError("running")):
            with self.assertRaises(SyncError):
                Engine(self.target).apply(manifest, source)
        self.assertEqual(scan(self.target), original)

    def test_external_release_not_copied(self):
        generate(self.source, self.repo, "test", "test", "1", external={"AIotApp": "https://example.com/AIotApp"})
        manifest = core.read_json(self.repo / "profiles/test/1/manifest.json")
        entry = next(e for e in manifest["entries"] if e["path"] == "AIotApp")
        self.assertEqual(entry["source"], "https://example.com/AIotApp")
        self.assertFalse((self.repo / "profiles/test/1/resources/AIotApp").exists())

    def test_generator_copies_only_scripts_and_json(self):
        (self.source / "model.rknn").touch()
        source, manifest = self.build()
        self.assertFalse((self.repo / "profiles/competition/1.0/resources/AIotApp").exists())
        self.assertFalse((self.repo / "profiles/competition/1.0/resources/model.rknn").exists())
        self.assertTrue((self.repo / "profiles/competition/1.0/resources/app/hat/hat30.py").exists())

    def test_http_stream_download_checks_hash(self):
        source = Source()
        payload = b"network payload"
        expected = hashlib.sha256(payload).hexdigest()
        with patch("core.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(payload)
            source.download("https://example.com/file", self.base / "download", len(payload), expected, None, lambda n: None)
        self.assertEqual((self.base / "download").read_bytes(), payload)

    def test_cancel_mid_download_removes_partial_file(self):
        source = Source()
        event = threading.Event()
        payload = b"x" * (2 * 1024 * 1024)
        with patch("core.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(payload)
            with self.assertRaises(Cancelled):
                source.download("https://example.com/file", self.base / "cancelled", len(payload),
                                hashlib.sha256(payload).hexdigest(), event, lambda n: event.set())
        self.assertFalse((self.base / "cancelled").exists())
        self.assertFalse(list(self.base.glob("*.part-*")))

    @unittest.skipUnless(sys.platform == "linux", "Requires Linux /proc")
    def test_real_linux_process_detection(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=self.target)
        try:
            with self.assertRaises(SyncError) as caught:
                REAL_ASSERT_STOPPED(self.target)
            self.assertIn(str(proc.pid), str(caught.exception))
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_commit_pin_and_encoded_paths(self):
        responses = [b'{"default_branch":"main"}', json.dumps({"ref": "refs/heads/main", "object": {"type": "commit", "sha": "a" * 40}}).encode()]
        with patch.object(Source, "fetch_bytes", side_effect=responses):
            source = Source.github("https://github.com/example/resources.git")
        self.assertEqual(source.repo, "resources")
        self.assertIn("/" + "a" * 40 + "/", source.url("resources/中文.py"))
        self.assertIn("%E4", source.url("resources/中文.py"))

    def test_operation_lock_excludes_other_engine(self):
        engine = Engine(self.target)
        with engine.lock():
            with self.assertRaises(SyncError):
                with Engine(self.target).lock():
                    pass


if __name__ == "__main__":
    unittest.main()
