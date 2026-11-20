from pathlib import Path
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import SyncError
from running_aiot import find_running_aiot, stop_existing_aiot


class RunningAiotTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp"))))))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.publish = self.base / 'publish space'
        self.publish.mkdir()
        self.proc = self.base / 'proc'
        self.proc.mkdir()
        self.links = {}

    def process(self, pid, executable, args=(), state='S', name='AIotApp', parent=1, started=100):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        fields = [state, str(parent)] + ['0'] * 17 + [str(started)]
        (directory / 'stat').write_text('{} ({} (worker)) {}'.format(pid, name, ' '.join(fields)), encoding='utf-8')
        (directory / 'comm').write_text(name, encoding='utf-8')
        (directory / 'cmdline').write_bytes(('\0'.join(str(arg) for arg in args) + '\0').encode('utf-8'))
        self.links[str(directory / 'exe')] = str(executable)
        self.links[str(directory / 'cwd')] = str(self.publish)

    def detect(self, ignored=()):
        with patch('running_aiot.os.readlink', side_effect=lambda path: self.links[str(path)]):
            return find_running_aiot(self.publish, ignored, self.proc)

    def test_matches_actual_deployment_binary_not_just_name_cwd_or_arguments(self):
        self.process(10001, self.publish / 'AIotApp')
        self.process(10002, self.base / 'other-publish/AIotApp')
        self.process(10003, self.base / 'bin/python3', ['python3', str(self.publish / 'target.py')], name='python3')
        self.process(10004, self.base / 'bin/bash', ['bash', str(self.publish / 'StartApp.sh')], name='bash')
        self.assertEqual(self.detect(), [10001])
        self.assertEqual(self.detect((10001,)), [])

    def test_dotnet_host_and_deleted_executable_are_detected_but_zombies_are_ignored(self):
        self.process(10001, self.publish / 'AIotApp', state='Z')
        self.process(10002, str(self.publish / 'AIotApp') + ' (deleted)')
        self.process(10003, self.base / 'bin/dotnet', ['dotnet', 'AIotApp.dll'], name='dotnet')
        self.process(10004, self.base / 'bin/dotnet', ['dotnet', str(self.base / 'other/AIotApp.dll')], name='dotnet')
        self.assertEqual(self.detect(), [10002, 10003])

    def test_exit_during_scan_is_ignored_and_permission_failure_is_reported(self):
        self.process(10001, self.publish / 'AIotApp')
        def disappeared(path):
            raise FileNotFoundError()
        with patch('running_aiot.os.readlink', side_effect=disappeared):
            self.assertEqual(find_running_aiot(self.publish, proc_root=self.proc), [])
        with patch('running_aiot.os.readlink', side_effect=PermissionError()), self.assertRaisesRegex(SyncError, '无法检查'):
            find_running_aiot(self.publish, proc_root=self.proc)

    def mark_exited(self, pid, sig):
        path = self.proc / str(pid) / 'stat'
        text = path.read_text(encoding='utf-8')
        path.write_text(text.replace(') S ', ') Z '), encoding='utf-8')

    def stop(self, **kwargs):
        with patch('running_aiot.os.readlink', side_effect=lambda path: self.links[str(path)]):
            return stop_existing_aiot(self.publish, proc_root=self.proc, **kwargs)

    def test_stop_targets_only_verified_aiot_and_descendants_not_terminal_siblings(self):
        self.process(700001, self.publish / 'AIotApp', parent=200)
        self.process(700002, self.base / 'python3', name='python3', parent=700001)
        self.process(700003, self.base / 'camera-worker', name='camera', parent=700002)
        self.process(700004, self.base / 'bash', name='bash', parent=200)
        self.process(700005, self.base / 'other-publish/AIotApp', parent=200)
        with patch('running_aiot.os.kill', side_effect=self.mark_exited) as kill:
            result = self.stop()
        self.assertEqual([call.args[0] for call in kill.call_args_list], [700001, 700002, 700003])
        self.assertTrue(all(call.args[1] == signal.SIGTERM for call in kill.call_args_list))
        self.assertEqual(result, {'stopped_pids': [700001, 700002, 700003], 'remaining_pids': []})
        self.assertIn(') S ', (self.proc / '700004/stat').read_text())
        self.assertIn(') S ', (self.proc / '700005/stat').read_text())

    def test_stop_escalates_only_survivors_after_grace_period(self):
        self.process(700001, self.publish / 'AIotApp')
        def stubborn(pid, sig):
            if int(sig) == 9:
                self.mark_exited(pid, sig)
        with patch('running_aiot.os.kill', side_effect=stubborn) as kill, \
                patch('running_aiot.signal.SIGKILL', 9, create=True), \
                patch('running_aiot.signal.Signals', side_effect=lambda sig: SimpleNamespace(name=str(sig))):
            result = self.stop(timeout=0)
        self.assertEqual([int(call.args[1]) for call in kill.call_args_list], [int(signal.SIGTERM), 9])
        self.assertEqual(result['remaining_pids'], [])

    def test_reused_root_pid_before_selection_is_preserved(self):
        self.process(700001, self.publish / 'AIotApp')
        scans = []
        def scan(*args, **kwargs):
            result = find_running_aiot(*args, **kwargs)
            scans.append(1)
            if len(scans) == 2:
                self.process(700001, self.publish / 'AIotApp', started=101)
            return result
        with patch('running_aiot.find_running_aiot', side_effect=scan), patch('running_aiot.os.kill') as kill:
            result = self.stop()
        kill.assert_not_called()
        self.assertEqual(result, {'stopped_pids': [], 'remaining_pids': [700001]})

    def test_reused_pid_after_term_is_not_force_killed(self):
        self.process(700001, self.publish / 'AIotApp')
        def replaced(pid, sig):
            self.process(pid, self.publish / 'AIotApp', started=101)
        with patch('running_aiot.os.kill', side_effect=replaced) as kill:
            result = self.stop(timeout=0)
        kill.assert_called_once_with(700001, signal.SIGTERM)
        self.assertEqual(result['remaining_pids'], [700001])

    def test_stop_permission_error_reports_failure_without_signalling_other_apps(self):
        self.process(700001, self.publish / 'AIotApp')
        self.process(700002, self.base / 'other/AIotApp')
        with patch('running_aiot.os.kill', side_effect=PermissionError()) as kill:
            with self.assertRaisesRegex(SyncError, '没有权限停止'):
                self.stop()
        kill.assert_called_once_with(700001, signal.SIGTERM)

    @unittest.skipUnless(sys.platform == 'linux', 'Needs real Linux /proc and executables')
    def test_real_external_process_can_be_stopped_without_killing_shared_terminal_group(self):
        binary = self.publish / 'AIotApp'
        shutil.copy2('/bin/bash', binary)
        process = subprocess.Popen([str(binary), '-c', 'sleep 30 & wait'], cwd=self.publish,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 3
            while process.pid not in find_running_aiot(self.publish) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn(process.pid, find_running_aiot(self.publish))
            self.assertEqual(os.getpgid(process.pid), os.getpgrp())
            result = stop_existing_aiot(self.publish)
            process.wait(timeout=3)
            self.assertIn(process.pid, result['stopped_pids'])
            self.assertEqual(find_running_aiot(self.publish), [])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == '__main__':
    unittest.main()
