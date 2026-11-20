import hashlib
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Engine, Source, SyncError, Cancelled
from file_compare import comparison_self_test, diagnose_file, format_report, text_reason, text_diff, format_diff


class FileCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target, self.remote = self.base / "publish", self.base / "remote"
        self.target.mkdir()
        self.remote.mkdir()
        self.engine, self.source = Engine(self.target), Source(local=self.remote)

    def setup_file(self, local=b"print('ok')\r\n", remote=b"print('ok')\n", git=False):
        (self.remote / "sample.py").write_bytes(remote)
        if local is not None:
            (self.target / "sample.py").write_bytes(local)
            os.chmod(self.target / "sample.py", 0o644)
        entry = {"path": "sample.py", "source": "sample.py", "type": "file", "mode": "0644", "size": len(remote)}
        entry["git_sha1" if git else "sha256"] = hashlib.sha1(b"blob " + str(len(remote)).encode() + b"\0" + remote).hexdigest() if git else hashlib.sha256(remote).hexdigest()
        self.manifest = {"schema_version": 1, "id": "rk", "name": "RK", "version": "test", "entries": [entry]}
        return entry

    def test_exact_hashes_and_newline_explanation_without_writes(self):
        self.setup_file(git=True)
        before = (self.target / "sample.py").read_bytes()
        report = diagnose_file(self.engine, self.manifest, self.source, "sample.py")
        self.assertEqual(report["status"], "内容不同")
        self.assertEqual(report["reason"], "仅换行不同（CRLF / LF）")
        self.assertEqual(report["remote"]["sha256"], hashlib.sha256(b"print('ok')\n").hexdigest())
        self.assertIn("Git blob SHA-1", format_report(report))
        self.assertEqual((self.target / "sample.py").read_bytes(), before)
        self.assertFalse(list(self.engine.state.glob("diagnose-*")))
        self.assertFalse(list((self.engine.state / "objects").iterdir()))

    def test_bom_is_distinguished_from_real_content_changes(self):
        self.assertEqual(text_reason(b"\xef\xbb\xbfhello\n", b"hello\n"), "仅 UTF-8 BOM 不同")
        self.assertEqual(text_reason(b"\xef\xbb\xbfhello\r\n", b"hello\n"), "仅 UTF-8 BOM 和换行不同")
        self.assertIn("其他差异", text_reason(b"print('a')\n", b"print('b')\n"))
        self.assertIn("不是有效 UTF-8", text_reason(b"\xff", b"x"))

    def test_missing_and_identical_files(self):
        self.setup_file(local=None)
        self.assertEqual(diagnose_file(self.engine, self.manifest, self.source, "sample.py")["status"], "新增")
        self.assertFalse((self.target / "sample.py").exists())
        (self.target / "sample.py").write_bytes(b"print('ok')\n")
        os.chmod(self.target / "sample.py", 0o644)
        self.assertEqual(diagnose_file(self.engine, self.manifest, self.source, "sample.py")["status"], "相同")

    @unittest.skipUnless(os.name == "posix", "Linux permissions")
    def test_permissions_only_have_identical_hashes(self):
        self.setup_file(local=b"print('ok')\n")
        os.chmod(self.target / "sample.py", 0o755)
        report = diagnose_file(self.engine, self.manifest, self.source, "sample.py")
        self.assertEqual(report["status"], "权限不同")
        self.assertEqual(report["local"]["sha256"], report["remote"]["sha256"])
        self.assertEqual((report["local"]["mode"], report["remote"]["mode"]), ("0755", "0644"))

    def test_offline_requires_verified_cache(self):
        entry = self.setup_file()
        with self.assertRaisesRegex(SyncError, "离线"):
            diagnose_file(self.engine, self.manifest, self.source, "sample.py", offline=True)
        self.engine._object(entry).write_bytes((self.remote / "sample.py").read_bytes())
        with patch.object(Source, "download", side_effect=AssertionError("must not download")):
            report = diagnose_file(self.engine, self.manifest, self.source, "sample.py", offline=True)
        self.assertEqual(report["origin"], "已校验缓存")

    def test_corrupt_remote_fails_and_temp_is_removed(self):
        self.setup_file()
        (self.remote / "sample.py").write_bytes(b"corrupted")
        with self.assertRaises(SyncError):
            diagnose_file(self.engine, self.manifest, self.source, "sample.py")
        self.assertEqual((self.target / "sample.py").read_bytes(), b"print('ok')\r\n")
        self.assertFalse(list(self.engine.state.glob("diagnose-*")))

    def test_unsafe_path_and_cancel(self):
        self.setup_file()
        with self.assertRaises(SyncError):
            diagnose_file(self.engine, self.manifest, self.source, "../outside.py")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            diagnose_file(self.engine, self.manifest, self.source, "sample.py", cancel=cancel)

    def test_pending_transaction_blocks_read_only_diagnostic(self):
        self.setup_file()
        self.engine.journal.write_text("{}")
        with self.assertRaisesRegex(SyncError, "未完成"):
            diagnose_file(self.engine, self.manifest, self.source, "sample.py")
        self.assertEqual((self.target / "sample.py").read_bytes(), b"print('ok')\r\n")
        self.assertTrue(self.engine.journal.exists())

    @unittest.skipUnless(os.name == "posix", "Linux symbolic links")
    def test_linked_path_is_rejected(self):
        self.setup_file()
        (self.target / "sample.py").unlink()
        (self.target / "sample.py").symlink_to(self.remote / "sample.py")
        with self.assertRaisesRegex(SyncError, "符号链接"):
            diagnose_file(self.engine, self.manifest, self.source, "sample.py")

    def test_packaged_samples_self_test_is_isolated(self):
        (self.target / "sentinel.json").write_bytes(b"untouched")
        report = comparison_self_test()
        self.assertIn("全部 6 项通过", report)
        self.assertIn("仅换行不同", report)
        self.assertEqual((self.target / "sentinel.json").read_bytes(), b"untouched")

    def test_detailed_diff_has_correct_direction_context_and_line_numbers(self):
        self.setup_file(local=b"first\nlocal value\nlast\n", remote=b"first\nremote value\nlast\n")
        report = diagnose_file(self.engine, self.manifest, self.source, "sample.py")
        diff = report["diff"]
        deleted = next(row for row in diff["rows"] if row["kind"] == "delete")
        added = next(row for row in diff["rows"] if row["kind"] == "add")
        self.assertEqual((deleted["text"], deleted["old_line"], deleted["new_line"]), ("-local value", 2, None))
        self.assertEqual((added["text"], added["old_line"], added["new_line"]), ("+remote value", None, 2))
        self.assertEqual((diff["added"], diff["deleted"]), (1, 1))
        self.assertTrue(any(r["kind"] == "context" and r["text"] == " first" for r in diff["rows"]))
        self.assertIn("@@", format_report(report))
        self.assertNotIn("local value", format_report(report, include_diff=False))
        self.assertEqual((self.target / "sample.py").read_bytes(), b"first\nlocal value\nlast\n")

    def test_multiple_hunks_retain_actual_line_numbers(self):
        old = ["line {}".format(i) for i in range(1, 31)]
        new = list(old)
        new[1], new[24] = "changed second", "changed twenty-fifth"
        diff = text_diff("\n".join(old).encode(), "\n".join(new).encode(), "file.py")
        self.assertEqual(len([r for r in diff["rows"] if r["kind"] == "hunk"]), 2)
        self.assertEqual([r["new_line"] for r in diff["rows"] if r["kind"] == "add"], [2, 25])

    def test_missing_and_local_only_files_show_additions_or_deletions(self):
        self.setup_file(local=None, remote=b"new line\n")
        diff = diagnose_file(self.engine, self.manifest, self.source, "sample.py")["diff"]
        self.assertEqual((diff["added"], diff["deleted"]), (1, 0))
        self.assertEqual(diff["rows"][0]["text"], "--- /dev/null")
        (self.target / "extra.py").write_bytes(b"local only\n")
        diff = diagnose_file(self.engine, self.manifest, self.source, "extra.py")["diff"]
        self.assertEqual((diff["added"], diff["deleted"]), (0, 1))
        self.assertEqual(diff["rows"][1]["text"], "+++ /dev/null")

    def test_bom_and_newline_only_do_not_appear_as_full_file_changes(self):
        diff = text_diff(b"\xef\xbb\xbfhello\r\n", b"hello\n", "file.py")
        self.assertEqual(diff["kind"], "format_only")
        self.assertIn("BOM", diff["note"])
        self.assertEqual(diff["rows"], [])

    def test_no_final_newline_and_header_like_source_lines(self):
        diff = text_diff(b"--- old", b"+++ new\n", "file.py")
        self.assertEqual((diff["added"], diff["deleted"]), (1, 1))
        self.assertTrue(any(r["kind"] == "note" and "No newline" in r["text"] for r in diff["rows"]))
        self.assertTrue(any(r["kind"] == "add" and r["text"] == "++++ new" for r in diff["rows"]))

    def test_binary_large_inputs_and_output_truncation_are_explicit(self):
        import file_compare
        self.assertEqual(text_diff(b"\xff", b"x", "file.py")["kind"], "binary")
        self.assertEqual(text_diff(b"\x00", b"x", "file.py")["kind"], "binary")
        self.assertEqual(text_diff(b"x" * (file_compare.DIFF_INPUT_LIMIT + 1), b"x", "file.py")["kind"], "limited")
        self.assertEqual(text_diff(b"x\n" * (file_compare.DIFF_LINE_LIMIT + 1), b"x", "file.py")["kind"], "limited")
        self.assertEqual(text_diff(b"x\n" * file_compare.DIFF_LINE_LIMIT + b"x", b"x", "file.py")["kind"], "limited")
        with patch("file_compare.DIFF_OUTPUT_LINES", 5):
            diff = text_diff(b"a\nb\nc\nd\n", b"e\nf\ng\nh\n", "file.py")
        self.assertTrue(diff["truncated"])
        self.assertIn("截断", diff["note"])
        self.assertLessEqual(len(diff["rows"]), 5)
        with patch("file_compare.DIFF_OUTPUT_LINES", 4):
            diff = text_diff(b"no final newline", b"new content\n", "file.py")
        self.assertTrue(diff["truncated"])
        self.assertLessEqual(len(diff["rows"]), 4)

    def test_terminal_colors_and_source_escape_characters(self):
        diff = text_diff(b"local\n", b"remote\x1b[2J\n", "file.py")
        plain, colored = format_diff(diff), format_diff(diff, color=True)
        self.assertNotIn("\x1b", plain)
        self.assertIn("\\x1b[2J", plain)
        self.assertIn("\x1b[31m-local", colored)
        self.assertIn("\x1b[32m+remote", colored)
