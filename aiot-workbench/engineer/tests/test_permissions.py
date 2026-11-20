import hashlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Engine, Source, SyncError


@unittest.skipUnless(os.name == "posix", "Linux file permissions")
class PermissionPolicyTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", tempfile.gettempdir()))
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target, self.remote = self.base / "publish", self.base / "remote"
        self.target.mkdir()
        self.remote.mkdir()
        self.original = b"print('original')\n"
        (self.target / "script.py").write_bytes(self.original)
        os.chmod(self.target / "script.py", 0o777)
        self.engine, self.source = Engine(self.target), Source(local=self.remote)
        self.guard = patch("core.assert_stopped")
        self.guard.start()
        self.addCleanup(self.guard.stop)

    @staticmethod
    def mode(path):
        return stat.S_IMODE(path.stat().st_mode)

    def manifest(self, changed=False, new=False):
        (self.remote / "script.py").write_bytes(b"print('updated')\n" if changed else self.original)
        if new:
            (self.remote / "new.py").write_bytes(b"print('new')\n")
        return {"schema_version": 1, "id": "rk", "version": "1", "entries": [
            {"type": "file", "path": p.name, "source": p.name, "mode": "0755" if p.name == "new.py" else "0644",
             "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(self.remote.iterdir())]}

    def test_default_permission_difference_is_green_noop(self):
        manifest = self.manifest()
        preview = self.engine.preview(manifest)
        self.assertEqual(preview["comparison"][0]["status"], "内容相同")
        self.assertEqual(preview["comparison"][0]["strict"], "不变")
        self.assertIn("0777 / 0644（保留本地）", preview["comparison"][0]["permissions"])
        self.assertEqual(preview["changes"], [])
        with patch.object(self.source, "download", side_effect=AssertionError("must not download")):
            result = self.engine.apply(manifest, self.source)
        self.assertTrue(result["unchanged"])
        self.assertEqual(self.mode(self.target / "script.py"), 0o777)
        self.assertFalse(list((self.engine.state / "backups").iterdir()))

    def test_content_replacement_preserves_old_mode_new_file_uses_repository(self):
        manifest = self.manifest(changed=True, new=True)
        (self.target / "model.bin").write_bytes(b"model")
        os.chmod(self.target / "model.bin", 0o600)
        result = self.engine.apply(manifest, self.source)
        self.assertEqual((self.target / "script.py").read_bytes(), b"print('updated')\n")
        self.assertEqual(self.mode(self.target / "script.py"), 0o777)
        self.assertEqual(self.mode(self.target / "new.py"), 0o755)
        self.assertEqual(self.mode(self.target / "model.bin"), 0o600)
        backup = self.engine.state / "backups" / result["backup"]
        self.assertEqual(self.mode(backup / "script.py"), 0o777)
        self.assertEqual((backup / "script.py").read_bytes(), self.original)

    def test_explicit_sync_reuses_bytes_and_restore_recovers_permissions(self):
        manifest = self.manifest()
        preview = self.engine.preview(manifest, sync_permissions=True)
        self.assertEqual(preview["comparison"][0]["status"], "权限不同")
        self.assertEqual(preview["download_bytes"], 0)
        with patch.object(self.source, "download", side_effect=AssertionError("must reuse bytes")):
            self.engine.apply(manifest, self.source, sync_permissions=True)
        self.assertEqual(self.mode(self.target / "script.py"), 0o644)
        self.assertEqual((self.target / "script.py").read_bytes(), self.original)
        self.engine.restore()
        self.assertEqual(self.mode(self.target / "script.py"), 0o777)

    def test_incremental_skips_existing_even_with_permission_sync(self):
        manifest = self.manifest(changed=True, new=True)
        self.engine.apply(manifest, self.source, mode="incremental", sync_permissions=True)
        self.assertEqual((self.target / "script.py").read_bytes(), self.original)
        self.assertEqual(self.mode(self.target / "script.py"), 0o777)
        self.assertEqual(self.mode(self.target / "new.py"), 0o755)

    def test_permission_change_after_preview_requires_new_check(self):
        manifest = self.manifest(changed=True)
        preview = self.engine.preview(manifest)
        os.chmod(self.target / "script.py", 0o700)
        with self.assertRaisesRegex(SyncError, "重新检查"):
            self.engine.apply(manifest, self.source, expected_actual=preview["actual"])
        self.assertEqual(self.mode(self.target / "script.py"), 0o700)
        self.assertEqual((self.target / "script.py").read_bytes(), self.original)

    def test_download_failure_preserves_original_bytes_and_permissions(self):
        manifest = self.manifest(changed=True)
        with patch.object(self.source, "download", side_effect=OSError("network failed")):
            with self.assertRaises(OSError):
                self.engine.apply(manifest, self.source)
        self.assertEqual((self.target / "script.py").read_bytes(), self.original)
        self.assertEqual(self.mode(self.target / "script.py"), 0o777)
