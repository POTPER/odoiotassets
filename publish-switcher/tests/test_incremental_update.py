import copy
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from publish_switcher.common.errors import Cancelled, SyncError
from publish_switcher.repositories.source import Source
from publish_switcher.updates import release
from publish_switcher.updates.package import REQUIRED_FILES


class IncrementalUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.install = self.base / "tool"
        self.install.mkdir()
        self.remote = self.base / "remote"
        self.remote.mkdir()
        self.version = "2026.11.26.2"
        contents = {name: b"" for name in REQUIRED_FILES}
        contents.update({"version.py": b"VERSION = '2026.11.26.2'\n",
                         "switcher.py": b"print('Publish Switcher 2026.11.26.2')\n",
                         "main.py": b"print('new')\n", "copy.py": b"print('new')\n",
                         "debs/dependency.deb": b"unchanged dependency" * 100000})
        files = []
        for name, content in contents.items():
            digest = hashlib.sha256(content).hexdigest()
            (self.remote / digest).write_bytes(content)
            files.append(dict(path=name, sha256=digest, size=len(content), mode=0o644))
            local = self.install / name
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
        for name in ("main.py", "copy.py"):
            (self.install / name).write_bytes(b"old\n")
        (self.install / "obsolete.py").write_bytes(b"obsolete\n")
        self.metadata = dict(schema_version=1, product="publish-switcher", version=self.version,
                             url="https://example.org/package.zip", size=1, sha256="0" * 64,
                             files_url="https://example.org/objects/", files=files)
        self.downloads = []
        self.plans = []
        self.progress = []
        self.cancel = threading.Event()
        self.source = Source(local=self.remote)
        real_download = self.source.download

        def download(location, *args, **kwargs):
            self.downloads.append(location)
            return real_download(location, *args, **kwargs)

        self.source.download = download
        locate = patch.object(release, "remote_file", side_effect=lambda url: (self.source, url.rsplit("/", 1)[-1]))
        locate.start()
        self.addCleanup(locate.stop)

    def prepare(self, **options):
        return release.prepare_online(self.install, self.metadata, "2026.11.26.1", self.cancel,
                                      self.progress.append, on_plan=self.plans.append, **options)

    def test_changed_objects_only_reuses_debs_and_removes_obsolete_on_commit(self):
        record = self.prepare()
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(self.plans, [len(b"print('new')\n")])
        self.assertEqual(sum(self.progress), self.plans[0])
        self.assertTrue((self.install / "obsolete.py").exists())
        self.assertEqual((self.install / "main.py").read_bytes(), b"old\n")
        state = release.update_state(self.install)
        self.assertFalse((state / record["stage"] / "obsolete.py").exists())
        release.commit_update(self.install)
        self.assertFalse((self.install / "obsolete.py").exists())
        self.assertEqual((self.install / "main.py").read_bytes(), b"print('new')\n")
        self.assertEqual((state / record["backup"] / "main.py").read_bytes(), b"old\n")

    def test_retry_reuses_verified_cache_after_cancellation(self):
        real_download = self.source.download

        def cancel_after_download(*args, **kwargs):
            real_download(*args, **kwargs)
            self.cancel.set()

        with patch.object(self.source, "download", side_effect=cancel_after_download):
            with self.assertRaises(Cancelled):
                self.prepare()
        state = release.update_state(self.install)
        self.assertFalse((state / "pending.json").exists())
        self.assertFalse(list(state.glob("stage-*")))
        self.cancel.clear()
        self.prepare()
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(self.plans[-1], 0)

    def test_file_objects_use_the_selected_repository_channel(self):
        self.metadata["files_url"] = "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/objects/"
        self.metadata["mirror_repositories"] = [{"url": "https://github.com/POTPER/odoiotassets", "branch": "main"}]
        addresses = []

        def locate(url):
            addresses.append(url)
            return self.source, url.rsplit("/", 1)[-1]

        with patch.object(release, "remote_file", side_effect=locate):
            self.prepare()
        self.assertEqual(len(addresses), 1)
        self.assertTrue(addresses[0].startswith(
            "https://raw.githubusercontent.com/POTPER/odoiotassets/main/publish-switcher/release/objects/"))

    def test_corrupt_object_stops_before_commit_and_keeps_current_files(self):
        digest = next(entry["sha256"] for entry in self.metadata["files"] if entry["path"] == "main.py")
        (self.remote / digest).write_bytes(b"corrupt")
        with self.assertRaises(SyncError):
            self.prepare()
        self.assertEqual((self.install / "main.py").read_bytes(), b"old\n")
        state = release.update_state(self.install)
        self.assertFalse((state / "pending.json").exists())
        self.assertFalse(list(state.glob("stage-*")))

    def test_probe_failure_rolls_back_incremental_install(self):
        self.prepare()
        with patch("publish_switcher.updates.bootstrap.subprocess.run") as probe:
            probe.return_value.returncode = 1
            probe.return_value.stderr = "simulated failure"
            with self.assertRaises(release.UpdateError):
                release.commit_update(self.install)
        self.assertEqual((self.install / "main.py").read_bytes(), b"old\n")
        self.assertTrue((self.install / "obsolete.py").exists())

    def test_invalid_or_incomplete_manifest_is_rejected_before_download(self):
        for path in ("../outside.py", "/absolute.py", "main.py/child", "MAIN.py"):
            metadata = copy.deepcopy(self.metadata)
            entry = dict(metadata["files"][-1], path=path)
            metadata["files"].append(entry)
            with self.subTest(path=path), self.assertRaises(release.UpdateError):
                release.prepare_online(self.install, metadata, "2026.11.26.1", self.cancel, self.progress.append)
        self.assertFalse(self.downloads)

