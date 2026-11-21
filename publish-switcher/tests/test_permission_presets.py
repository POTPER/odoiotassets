import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.packaging.legacy.core import Engine, SyncError
from publish_switcher.sync import permissions as presets


class PermissionPresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve() / "publish with spaces"
        self.target.mkdir()
        (self.target / "script.py").write_bytes(b"original")
        self.engine = Engine(self.target)
        with self.engine.lock():
            pass

    def root_apply(self, preset, run):
        identity = (self.target.stat().st_dev, self.target.stat().st_ino)
        with patch("publish_switcher.sync.permissions.sys.platform", "linux"), patch("publish_switcher.sync.permissions.os.geteuid", return_value=0, create=True), \
                patch("publish_switcher.sync.permissions.assert_stopped"), patch("publish_switcher.sync.permissions.subprocess.run", run), contextlib.redirect_stdout(io.StringIO()):
            presets.apply_as_root(self.target, preset, identity, caller_pid=12345)

    def test_command_presets_are_argv_and_root_precedes_777(self):
        commands = presets.commands(self.target, "root-and-777")
        self.assertEqual([c[0] for c in commands], ["chown", "chmod"])
        self.assertIn("-h", commands[0])
        self.assertIn("-P", commands[0])
        self.assertTrue(all(c[-2:] == ["--", str(self.target)] for c in commands))
        self.assertEqual(len(presets.commands(self.target, "root")), 1)
        self.assertEqual(presets.commands(self.target, "777")[0][0], "chmod")
        with self.assertRaises(SyncError):
            presets.commands(self.target, "arbitrary-command")

    def test_root_runner_only_invokes_fixed_commands_and_does_not_mutate_contents(self):
        from unittest.mock import Mock
        run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        self.root_apply("root-and-777", run)
        self.assertEqual([c.args[0][0] for c in run.call_args_list], ["chown", "chmod"])
        self.assertTrue(all(c.kwargs.get("shell", False) is False for c in run.call_args_list))
        self.assertEqual((self.target / "script.py").read_bytes(), b"original")

    def test_first_command_failure_does_not_continue_to_chmod(self):
        from unittest.mock import Mock
        run = Mock(return_value=subprocess.CompletedProcess([], 1, "", "permission failure"))
        with self.assertRaisesRegex(SyncError, "部分修改"):
            self.root_apply("root-and-777", run)
        run.assert_called_once()

    def test_second_failure_reports_partial_completion(self):
        from unittest.mock import Mock
        run = Mock(side_effect=[subprocess.CompletedProcess([], 0, "", ""), subprocess.CompletedProcess([], 1, "", "chmod failed")])
        with self.assertRaisesRegex(SyncError, "已完成 1 项"):
            self.root_apply("root-and-777", run)

    def test_wrong_identity_and_missing_target_are_rejected(self):
        with self.assertRaisesRegex(SyncError, "已被替换"):
            presets.checked_target(self.target, (-1, -1))
        with self.assertRaises(SyncError):
            presets.checked_target(self.target / "missing")
        with self.assertRaises(SyncError):
            presets.checked_target(Path.home())
        with self.assertRaises(SyncError):
            presets.checked_target(Path(__file__).resolve().parents[1])

    def test_mounts_and_pending_transactions_block_commands(self):
        from unittest.mock import Mock
        run = Mock()
        with patch("publish_switcher.sync.permissions.os.path.ismount", return_value=True):
            with self.assertRaisesRegex(SyncError, "挂载点"):
                self.root_apply("root", run)
        (self.engine.state / "config-transaction.json").write_bytes(b"{}")
        with self.assertRaisesRegex(SyncError, "未完成"):
            self.root_apply("root", run)
        run.assert_not_called()

    def test_nested_mount_is_rejected(self):
        from unittest.mock import Mock
        nested = self.target / "mounted"
        nested.mkdir()
        run = Mock()
        with patch("publish_switcher.sync.permissions.os.path.ismount", side_effect=lambda p: Path(p) == nested):
            with self.assertRaisesRegex(SyncError, "嵌套挂载点"):
                self.root_apply("777", run)
        run.assert_not_called()

    def test_gui_launcher_uses_polkit_no_password_and_maps_cancel(self):
        completed = subprocess.CompletedProcess([], 0, "preset done", "")
        with patch("publish_switcher.sync.permissions.sys.platform", "linux"), patch("publish_switcher.sync.permissions.os.geteuid", return_value=1000, create=True), \
                patch("publish_switcher.sync.permissions.shutil.which", return_value="/usr/bin/pkexec"), patch("publish_switcher.sync.permissions.subprocess.run", return_value=completed) as run:
            log = []
            result = presets.launch_preset(self.engine, "777", log.append)
            self.assertEqual(result["target"], str(self.target))
            self.assertEqual(run.call_args.args[0][0], "/usr/bin/pkexec")
            self.assertIn(str(self.target), run.call_args.args[0])
            self.assertNotIn("input", run.call_args.kwargs)
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertIn("preset done", log)
            run.return_value = subprocess.CompletedProcess([], 126, "", "")
            with self.assertRaisesRegex(SyncError, "授权已取消"):
                presets.launch_preset(self.engine, "777")

    def test_missing_pkexec_reports_installation_instruction(self):
        with patch("publish_switcher.sync.permissions.sys.platform", "linux"), patch("publish_switcher.sync.permissions.os.geteuid", return_value=1000, create=True), \
                patch("publish_switcher.sync.permissions.shutil.which", return_value=None), patch("publish_switcher.sync.permissions.subprocess.run") as run:
            with self.assertRaisesRegex(SyncError, "install.sh"):
                presets.launch_preset(self.engine, "root")
            run.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "Linux symbolic links")
    def test_symlink_root_rejected_and_internal_links_not_traversed(self):
        alias = self.target.with_name("alias")
        alias.symlink_to(self.target, target_is_directory=True)
        with self.assertRaisesRegex(SyncError, "符号链接"):
            presets.checked_target(alias)
        external = self.target.parent / "outside"
        external.mkdir()
        (external / "private").write_bytes(b"outside")
        (self.target / "linked").symlink_to(external, target_is_directory=True)
        # os.walk counts the link but does not enter the outside directory.
        self.assertEqual(presets._check_tree(self.target), 3)
        self.assertEqual((external / "private").read_bytes(), b"outside")
