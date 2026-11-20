import copy
import io
import os
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
from core import Engine, Source, SyncError, Cancelled, atomic_json, read_json, scan
from assets_sync import AssetsEngine, format_details
from generate import generate
import test_sync


class AssetsTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def build_assets(self):
        assets = self.source / "Assets"
        assets.mkdir()
        for name, raw in (("same.png", b"same"), ("different.png", b"BBBB"), ("missing.avi", b"video-data"), ("placeholder.png", b"real-image")):
            (assets / name).write_bytes(raw)
        local = self.target / "Assets"
        local.mkdir()
        for name, raw in (("same.png", b"same"), ("different.png", b"AAAA"), ("extra.txt", b"local-only"), ("placeholder.png", b"")):
            (local / name).write_bytes(raw)
        generate(self.source, self.repo, "rk", "RK", "1")
        self.manifest = read_json(self.repo / "profiles/rk/1/manifest.json")
        self.origin = Source(local=self.repo)
        self.engine = AssetsEngine(self.target)
        return self.engine.preview_assets(self.manifest)

    def test_hash_comparison_and_missing_only_download(self):
        preview = self.build_assets()
        rows = {r["path"]: r for r in preview["comparison"]}
        self.assertEqual(rows["Assets/different.png"]["status"], "内容不同")
        self.assertEqual(rows["Assets/same.png"]["status"], "相同")
        self.assertEqual(rows["Assets/placeholder.png"]["status"], "本地空文件")
        self.assertEqual(preview["changes"], [("新增", "Assets/missing.avi")])
        self.assertEqual(preview["download_bytes"], len(b"video-data"))
        self.assertIn("sha256", format_details(self.engine, self.manifest, self.origin, rows["Assets/different.png"]))
        before = {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        ordinary = Engine(self.target)
        record = {"id": "py", "version": "old", "backup": "keep-python-json-record"}
        atomic_json(ordinary.current, record)
        self.engine.download_missing(self.manifest, self.origin, expected_actual=preview["actual"])
        for p, raw in before.items():
            self.assertEqual(p.read_bytes(), raw)
        self.assertEqual((self.target / "Assets/missing.avi").read_bytes(), b"video-data")
        self.assertEqual(read_json(ordinary.current), record)
        self.assertEqual(read_json(self.engine.current)["scope"], "assets")

    def test_generator_packs_assets_without_other_binary_files(self):
        self.build_assets()
        self.assertTrue((self.repo / "profiles/rk/1/resources/Assets/missing.avi").is_file())
        self.assertFalse((self.repo / "profiles/rk/1/resources/AIotApp").exists())

    def test_cached_resource_reused_offline_and_no_repeated_download(self):
        self.build_assets()
        self.engine.download_missing(self.manifest, self.origin)
        (self.target / "Assets/missing.avi").unlink()
        preview = self.engine.preview_assets(self.manifest)
        self.assertEqual(preview["download_bytes"], 0)
        with patch.object(self.origin, "download", side_effect=AssertionError("No network or copy needed")):
            self.engine.download_missing(self.manifest, self.origin, expected_actual=preview["actual"], offline=True)
        self.assertTrue((self.target / "Assets/missing.avi").exists())

    def test_incomplete_offline_cache_rejects_without_partial_apply(self):
        self.build_assets()
        before = scan(self.target)
        with patch.object(self.origin, "download", side_effect=AssertionError("Must never download offline")):
            with self.assertRaisesRegex(SyncError, "离线"):
                self.engine.download_missing(self.manifest, self.origin, offline=True)
        self.assertEqual(scan(self.target), before)

    def test_checksum_failure_or_cancel_preserves_original(self):
        self.build_assets()
        before = scan(self.target)
        entry = next(e for e in self.manifest["entries"] if e["path"] == "Assets/missing.avi")
        payload = self.repo / entry["source"]
        payload.write_bytes(b"bad-data!!")
        with self.assertRaises(SyncError):
            self.engine.download_missing(self.manifest, self.origin)
        self.assertEqual(scan(self.target), before)
        payload.write_bytes(b"video-data")
        cancel = threading.Event()
        real = self.origin.download
        def cancelling(location, dest, size, expected, event, progress):
            def tick(n):
                progress(n)
                cancel.set()
            return real(location, dest, size, expected, event, tick)
        with patch.object(self.origin, "download", side_effect=cancelling):
            with self.assertRaises(Cancelled):
                self.engine.download_missing(self.manifest, self.origin, cancel=cancel)
        self.assertEqual(scan(self.target), before)
        self.assertFalse(list(self.engine.state.glob("stage-*")))

    def test_space_permissions_and_running_program_block_download(self):
        self.build_assets()
        before = scan(self.target)
        for name, value in (("disk", SimpleNamespace(free=0)), ("program", None)):
            context = patch("core.shutil.disk_usage", return_value=value) if name == "disk" else patch("core.assert_stopped", side_effect=SyncError("running"))
            with context, patch.object(self.origin, "download") as download:
                with self.assertRaises(SyncError):
                    self.engine.download_missing(self.manifest, self.origin)
                download.assert_not_called()
        with patch("core.os.access", return_value=False):
            with self.assertRaisesRegex(SyncError, "权限"):
                self.engine.download_missing(self.manifest, self.origin)
        self.assertEqual(scan(self.target), before)

    def test_preview_change_rejected_even_when_file_size_is_same(self):
        preview = self.build_assets()
        (self.target / "Assets/same.png").write_bytes(b"edit")
        with self.assertRaisesRegex(SyncError, "重新检查"):
            self.engine.download_missing(self.manifest, self.origin, expected_actual=preview["actual"])
        self.assertFalse((self.target / "Assets/missing.avi").exists())

    def test_no_changes_does_not_download_or_make_backup(self):
        self.build_assets()
        (self.target / "Assets/missing.avi").write_bytes(b"existing different")
        with patch.object(self.origin, "download") as download:
            result = self.engine.download_missing(self.manifest, self.origin)
            download.assert_not_called()
        self.assertTrue(result["unchanged"])
        self.assertFalse(self.engine.current.exists())

    def test_git_blob_hash_and_external_https_resource(self):
        self.build_assets()
        manifest = copy.deepcopy(self.manifest)
        for entry in manifest["entries"]:
            if entry["type"] == "file":
                entry.pop("sha256", None)
        resource = next(e for e in manifest["entries"] if e["path"] == "Assets/missing.avi")
        resource["source"] = "https://example.com/releases/missing.avi"
        with patch("core.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"video-data")
            self.engine.download_missing(manifest, self.origin)
        self.assertEqual((self.target / "Assets/missing.avi").read_bytes(), b"video-data")

    def test_remote_empty_file_blocked_unless_allowed(self):
        self.build_assets()
        empty = self.source / "Assets/empty.png"
        empty.touch()
        output = self.base / "empty-repository"
        with self.assertRaisesRegex(SyncError, "零字节"):
            generate(self.source, output, "rk", "RK", "empty")
        generate(self.source, output, "rk", "RK", "empty", allow_empty=["Assets/empty.png"])
        manifest = read_json(output / "profiles/rk/empty/manifest.json")
        manifest["allowed_empty"] = []
        self.assertIn("为空", self.engine.preview_assets(manifest)["blocker"])
        manifest["allowed_empty"] = ["Assets/empty.png"]
        self.engine.download_missing(manifest, Source(local=output))
        self.assertEqual((self.target / "Assets/empty.png").stat().st_size, 0)

    def test_lfs_pointer_is_not_deployed_as_resource(self):
        self.build_assets()
        pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 999999999\n"
        path = self.source / "Assets/pointer.avi"
        path.write_bytes(pointer)
        output = self.base / "lfs-repository"
        generate(self.source, output, "rk", "RK", "lfs")
        manifest = read_json(output / "profiles/rk/lfs/manifest.json")
        before = scan(self.target)
        with self.assertRaisesRegex(SyncError, "LFS 指针"):
            self.engine.download_missing(manifest, Source(local=output))
        self.assertEqual(scan(self.target), before)

    def test_commit_failure_rolls_back_and_shared_engine_recovers_interruption(self):
        self.build_assets()
        before = scan(self.target)
        original = os.rename
        count = 0
        def fail_second(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("switch failed")
            return original(src, dst)
        with patch("core.os.rename", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "switch failed"):
                self.engine.download_missing(self.manifest, self.origin)
        self.assertEqual(scan(self.target), before)
        stage = self.engine.state / "stage-assets-interrupted"
        stage.mkdir()
        backup = self.engine.state / "backups/assets-interrupted"
        atomic_json(self.engine.journal, {"phase": "prepared", "stage": stage.name, "backup": backup.name, "had_target": True,
                                        "old_state": None, "new_state": {"scope": "assets"}})
        self.target.rename(backup)
        self.assertFalse(self.target.exists())
        Engine(self.target).startup_recover()
        self.assertEqual(scan(self.target), before)
        self.assertFalse(self.engine.journal.exists())

    @unittest.skipUnless(os.name == "posix", "Linux inode and mode preservation")
    def test_existing_assets_keep_inode_and_permissions(self):
        self.build_assets()
        local = self.target / "Assets/same.png"
        local.chmod(0o777)
        before = local.stat()
        self.engine.download_missing(self.manifest, self.origin)
        after = local.stat()
        self.assertEqual(after.st_ino, before.st_ino)
        self.assertEqual(after.st_uid, before.st_uid)
        self.assertEqual(after.st_mode, before.st_mode)

    @unittest.skipUnless(os.name == "posix", "Linux symlinks")
    def test_symlink_parent_conflict_never_writes_outside_publish(self):
        self.build_assets()
        import shutil
        shutil.rmtree(self.target / "Assets")
        outside = self.base / "outside"
        outside.mkdir()
        (self.target / "Assets").symlink_to(outside, target_is_directory=True)
        preview = self.engine.preview_assets(self.manifest)
        self.assertIn("冲突", preview["blocker"])
        with self.assertRaisesRegex(SyncError, "冲突"):
            self.engine.download_missing(self.manifest, self.origin)
        self.assertFalse(list(outside.iterdir()))

    def test_missing_publish_rejected(self):
        with self.assertRaisesRegex(SyncError, "目录不存在"):
            AssetsEngine(self.base / "wrong-publish")

    def test_python_json_restore_does_not_undo_assets_download(self):
        self.build_assets()
        ordinary = Engine(self.target)
        ordinary.apply(self.manifest, self.origin)
        record = read_json(ordinary.current)
        self.engine.download_missing(self.manifest, self.origin)
        self.assertEqual(read_json(ordinary.current), record)
        ordinary.restore()
        self.assertTrue((self.target / "app/hat/hat20.py").exists())
        self.assertEqual((self.target / "Assets/missing.avi").read_bytes(), b"video-data")

    def test_committed_assets_journal_finalized_without_changing_python_record(self):
        self.build_assets()
        ordinary = Engine(self.target)
        record = {"id": "python-json", "version": "old"}
        atomic_json(ordinary.current, record)
        result = self.engine.download_missing(self.manifest, self.origin)
        self.engine.current.unlink()
        atomic_json(self.engine.journal, {"phase": "committed", "stage": "stage-already-moved", "backup": result["backup"],
                                        "had_target": True, "old_state": None, "new_state": result})
        ordinary.startup_recover()
        self.assertEqual(read_json(ordinary.current), record)
        self.assertEqual(read_json(self.engine.current), result)
        self.assertFalse(self.engine.journal.exists())

    def test_offline_cache_disappearing_never_falls_back_to_network(self):
        self.build_assets()
        self.engine.download_missing(self.manifest, self.origin)
        (self.target / "Assets/missing.avi").unlink()
        entry = next(e for e in self.manifest["entries"] if e["path"] == "Assets/missing.avi")
        real = self.engine.apply
        def invalidate(*args, **kwargs):
            self.engine._object(entry).unlink()
            return real(*args, **kwargs)
        with patch.object(self.engine, "apply", side_effect=invalidate), patch.object(self.origin, "download") as download:
            with self.assertRaisesRegex(SyncError, "离线"):
                self.engine.download_missing(self.manifest, self.origin, offline=True)
            download.assert_not_called()
        self.assertFalse((self.target / "Assets/missing.avi").exists())
