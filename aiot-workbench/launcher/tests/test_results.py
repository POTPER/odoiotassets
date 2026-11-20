from pathlib import Path
import os
import threading
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import SyncError
from results_files import list_results, copy_submission, SubmissionCancelled
from results_files import _fingerprint


class ResultsTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "成果"
        self.source.mkdir()
        self.target = self.base / "提交目标 space"
        (self.source / "中文目录").mkdir()
        (self.source / "中文目录/结果.txt").write_bytes(b"original\n")
        (self.source / "empty.py").write_bytes(b"")

    def test_disabled_submission_does_not_create_destination(self):
        with self.assertRaisesRegex(SyncError, "未开启"):
            copy_submission(self.source, self.target, ["empty.py"])
        self.assertFalse(self.target.exists())

    def test_windows_creation_time_variation_does_not_claim_source_changed(self):
        from types import SimpleNamespace
        metadata = dict(st_dev=1, st_ino=2, st_size=9, st_mtime_ns=12345)
        first = SimpleNamespace(**metadata, st_ctime_ns=12344)
        second = SimpleNamespace(**metadata, st_ctime_ns=12345)
        with patch("results_files.os.name", "nt"):
            self.assertEqual(_fingerprint(first), _fingerprint(second))
        with patch("results_files.os.name", "posix"):
            self.assertNotEqual(_fingerprint(first), _fingerprint(second))

    def test_list_and_nested_copy_preserve_sources_and_history(self):
        rows = list_results(self.source)
        self.assertEqual(rows[0]["kind"], "directory")
        self.assertEqual(list_results(self.source, "中文目录")[0]["relative"], "中文目录/结果.txt")
        files = ["中文目录/结果.txt", "empty.py"]
        first = copy_submission(self.source, self.target, files, enabled=True)
        second = copy_submission(self.source, self.target, files, enabled=True)
        self.assertEqual(first[0].read_bytes(), b"original\n")
        self.assertEqual(first[1].read_bytes(), b"")
        self.assertEqual(second[0], self.target / "中文目录/结果_2.txt")
        self.assertEqual(second[1], self.target / "empty_2.py")
        self.assertEqual((self.source / files[0]).read_bytes(), b"original\n")
        self.assertFalse(any(self.target.glob(".aiot-submit-*")))

    def test_escape_directories_and_missing_sources_are_rejected_before_copy(self):
        for files, target in ((["../outside.py"], self.target), (["missing.py"], self.target),
                              (["empty.py"], self.source), (["empty.py"], self.source / "inside"),
                              (["empty.py"], self.base)):
            with self.subTest(files=files, target=target), self.assertRaises(SyncError):
                copy_submission(self.source, target, files, enabled=True)
        self.assertFalse(self.target.exists())

    def test_batch_commit_failure_rolls_back_new_files_without_overwriting_history(self):
        self.target.mkdir()
        (self.target / "empty.py").write_bytes(b"existing")
        replace = os.replace
        def fail(src, dst):
            if Path(src).name == "1":
                raise PermissionError("injected commit failure")
            return replace(src, dst)
        with patch("results_files.os.replace", side_effect=fail), self.assertRaises(PermissionError):
            copy_submission(self.source, self.target, ["empty.py", "中文目录/结果.txt"], enabled=True)
        self.assertEqual((self.target / "empty.py").read_bytes(), b"existing")
        self.assertEqual(list(self.target.iterdir()), [self.target / "empty.py"])

    def test_cancellation_cleans_staged_files(self):
        cancel = threading.Event()
        with self.assertRaises(SubmissionCancelled):
            copy_submission(self.source, self.target, ["empty.py", "中文目录/结果.txt"], enabled=True, cancel=cancel,
                            progress=lambda *_: cancel.set())
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertTrue((self.source / "empty.py").exists())

    def test_legacy_unsafe_submission_is_rejected_before_creating_or_copying_files(self):
        publish = self.base / 'workspace/publish'
        for destination in (publish, publish / 'app/task/student_data', publish.parent):
            with self.subTest(destination=destination), self.assertRaisesRegex(SyncError, 'publish'):
                copy_submission(self.source, destination, ['empty.py'], enabled=True, publish_dir=publish)
            self.assertFalse(destination.exists())
        self.assertTrue((self.source / 'empty.py').exists())
        copied = copy_submission(self.source, self.target, ['empty.py'], enabled=True, publish_dir=publish)
        self.assertEqual(copied[0].read_bytes(), b'')

    def test_links_cannot_escape_results_or_redirect_submission(self):
        outside = self.base / "outside.txt"
        outside.write_bytes(b"private")
        try:
            (self.source / "link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("Symbolic links are unavailable")
        self.assertEqual(next(row for row in list_results(self.source) if row["name"] == "link.txt")["kind"], "link")
        with self.assertRaises(SyncError):
            copy_submission(self.source, self.target, ["link.txt"], enabled=True)
        self.target.mkdir()
        (self.target / "中文目录").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(SyncError):
            copy_submission(self.source, self.target, ["中文目录/结果.txt"], enabled=True)
        self.assertFalse((self.base / "结果.txt").exists())


if __name__ == "__main__":
    unittest.main()
