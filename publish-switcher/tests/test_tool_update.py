import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_switcher.updates import bootstrap as updater
from tools.packaging.legacy.core import Source
from tools.build_update import distribution_files


class ProgramUpdateTests(unittest.TestCase):
    def test_source_layout_maps_to_legacy_paths_in_distribution(self):
        root = Path(__file__).resolve().parents[1]
        entries = dict(distribution_files(root))
        self.assertEqual(entries["install.sh"], root / "install/install.sh")
        self.assertEqual(entries["tool_update.py"], root / "publish_switcher/updates/bootstrap.py")
        self.assertEqual(entries["version.py"], root / "publish_switcher/version.py")
        self.assertEqual(entries["ui_assets.py"], root / "tools/packaging/legacy/ui_assets.py")
        self.assertTrue(all(entries[name].is_file() for name in updater.REQUIRED_FILES))
        self.assertFalse(any(name.startswith(("tools/", "tests/", "release/", "install/")) for name in entries))
        self.assertIn("icons/swicher-256.png", entries)

    def setUp(self):
        root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.install = self.base / "工具目录"
        self.install.mkdir()
        (self.install / "old.py").write_bytes(b"original")
        self.package = self.base / "publish-switcher.zip"
        self.version = "2026.11.20.9"

    def release(self, extra=()):
        with zipfile.ZipFile(self.package, "w") as archive:
            for name in updater.REQUIRED_FILES:
                value = "VERSION = {!r}\n".format(self.version) if name == "version.py" else ""
                if name == "switcher.py":
                    value = "print({!r})\n".format("Publish Switcher " + self.version)
                archive.writestr("publish-switcher/" + name, value)
            for name, value in extra:
                archive.writestr(name, value)
        return {"schema_version": 1, "product": "publish-switcher", "version": self.version,
                "url": "https://example.org/publish-switcher.zip", "package_file": self.package.name,
                "size": self.package.stat().st_size, "sha256": hashlib.sha256(self.package.read_bytes()).hexdigest()}

    def prepare(self, release=None):
        return updater.prepare_package(self.install, release or self.release(), self.package, "2026.11.20.1")

    def test_preparation_then_atomic_install_keeps_old_backup(self):
        record = self.prepare()
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")
        updater.commit_update(self.install)
        state = updater.update_state(self.install)
        self.assertEqual((state / record["backup"] / "old.py").read_bytes(), b"original")
        self.assertEqual(updater.package_version(self.install / "version.py"), self.version)
        self.assertFalse((state / "pending.json").exists())

    def test_selected_github_downloads_package_from_github_even_if_metadata_names_gitee(self):
        release = self.release()
        release["url"] = "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/publish-switcher.zip"
        release["mirror_repositories"] = [{"url": "https://github.com/POTPER/odoiotassets", "branch": "main"}]
        with patch("publish_switcher.updates.release.remote_file", return_value=(Source(local=self.base), self.package.name)) as locate:
            updater.prepare_online(self.install, release, "2026.11.20.1", None, lambda size: None)
        locate.assert_called_once_with("https://raw.githubusercontent.com/POTPER/odoiotassets/main/publish-switcher/release/publish-switcher.zip")
        updater.recover_update(self.install)

    def test_bad_checksum_and_version_mismatch_leave_original_untouched(self):
        release = self.release()
        release["sha256"] = "0" * 64
        with self.assertRaisesRegex(updater.UpdateError, "SHA-256"):
            self.prepare(release)
        release = self.release()
        release["version"] = "2026.11.20.10"
        with self.assertRaisesRegex(updater.UpdateError, "版本不一致"):
            self.prepare(release)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")
        self.assertFalse((updater.update_state(self.install) / "pending.json").exists())

    def test_space_or_download_failure_does_not_change_installed_tool(self):
        release = self.release()
        with patch("publish_switcher.updates.bootstrap.shutil.disk_usage") as space:
            space.return_value.free = 0
            with self.assertRaisesRegex(updater.UpdateError, "磁盘空间不足"):
                self.prepare(release)
        with patch("publish_switcher.updates.release.remote_file", return_value=(Source(local=self.base), "publish-switcher.zip")), \
                patch.object(Source, "download", side_effect=OSError("network interruption")):
            with self.assertRaises(OSError):
                updater.prepare_online(self.install, release, "2026.11.20.1", None, lambda size: None)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")
        self.assertFalse((updater.update_state(self.install) / "pending.json").exists())

    def test_invalid_zip_paths_and_links_are_blocked(self):
        bad_separator = zipfile.ZipInfo("placeholder")
        bad_separator.filename = "publish-switcher/x\\escape.py"
        for name in ("publish-switcher/../../escape.py", "/publish-switcher/a.py",
                     bad_separator, "publish-switcher/CORE.py"):
            with self.subTest(name=name):
                release = self.release([(name, "bad")])
                with self.assertRaises(updater.UpdateError):
                    self.prepare(release)
        link = zipfile.ZipInfo("publish-switcher/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(updater.UpdateError):
            self.prepare(self.release([(link, "elsewhere")]))

    def test_install_failure_rolls_back_whole_directory(self):
        record = self.prepare()
        original = os.replace
        def fail_stage(source, destination):
            if Path(source).name == record["stage"] and Path(destination) == self.install:
                raise OSError("simulated rename error")
            return original(source, destination)
        with patch("publish_switcher.updates.bootstrap.os.replace", side_effect=fail_stage):
            with self.assertRaisesRegex(OSError, "simulated"):
                updater.commit_update(self.install)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")
        self.assertFalse((updater.update_state(self.install) / "pending.json").exists())

    def test_failed_new_version_probe_restores_old_code(self):
        release = self.release()
        with patch("publish_switcher.updates.bootstrap.subprocess.run") as probe:
            probe.return_value.returncode = 1
            probe.return_value.stderr = "import failure"
            self.prepare(release)
            with self.assertRaisesRegex(updater.UpdateError, "启动校验失败"):
                updater.commit_update(self.install)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")

    def test_startup_recovers_interrupted_directory_rename(self):
        record = self.prepare()
        state = updater.update_state(self.install)
        os.replace(self.install, state / record["backup"])
        # The recovery record may still say prepared if power was lost just after rename.
        updater.recover_update(self.install)
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")
        self.assertFalse((state / record["stage"]).exists())

    def test_external_bootstrap_recovers_when_main_entry_is_missing(self):
        (self.install / "switcher.py").write_text("print('original-launch-restored')\n", encoding="utf-8")
        record = self.prepare()
        state = updater.update_state(self.install)
        bootstrap = state / "bootstrap.py"
        bootstrap.write_bytes(Path(updater.__file__).read_bytes())
        os.replace(self.install, state / record["backup"])
        result = subprocess.run([sys.executable, str(bootstrap), "--launch", str(self.install)],
                                cwd=self.base, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("original-launch-restored", result.stdout)
        self.assertTrue((self.install / "old.py").exists())

    def test_remote_check_persists_mandatory_version_and_blocks_old_offline_package(self):
        release = self.release()
        (self.base / "update.json").write_text(json.dumps(release), encoding="utf-8")
        with patch("publish_switcher.updates.release.remote_file", return_value=(Source(local=self.base), "update.json")):
            actual, newer = updater.check_release("https://example.org/update.json", self.install, "2026.11.20.1")
        self.assertTrue(newer)
        self.assertEqual(actual["version"], self.version)
        self.version = "2026.11.20.2"
        with self.assertRaisesRegex(updater.UpdateError, "低于已知"):
            self.prepare(self.release())

    def test_offline_metadata_and_runtime_lock(self):
        release = self.release()
        manifest = self.base / "switcher-update.json"
        manifest.write_text(json.dumps(release), encoding="utf-8")
        updater.prepare_offline(self.install, manifest, "2026.11.20.1")
        updater.recover_update(self.install)
        with updater.instance_lock(self.install):
            with self.assertRaises(updater.UpdateError):
                with updater.instance_lock(self.install):
                    self.fail("must be exclusive")
        self.assertEqual((self.install / "old.py").read_bytes(), b"original")
