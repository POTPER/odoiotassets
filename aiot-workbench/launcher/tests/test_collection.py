import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector
import collection_config as overlay
import launcher_runtime as runtime
import session_cli
from gui_session import LauncherController
from core import Engine, atomic_json


class CollectionTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp"))))))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.publish = self.base / 'publish'
        self.target = self.publish / 'app/中文项目/target.py'
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'print("archive")\n')
        self.archive = self.base / 'archive'
        self.engine = Engine(self.publish)
        self.config = self.publish / 'TrainTaskInfo.json'
        self.original = json.dumps([{'TrainTaskId': 1, 'PythonExePath': sys.executable, 'note': 'original'}]).encode()
        self.config.write_bytes(self.original)

    def save(self):
        return collector.archive_script(self.publish, self.archive, ['-u', str(self.target), 'arg'])

    def test_snapshot_bytes_naming_empty_and_history(self):
        first = self.save()
        self.assertRegex(first.name, r'^中文项目_\d{8}_\d{6}_\d{6}\.py$')
        self.target.write_bytes(b'')
        second = self.save()
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b'print("archive")\n')
        self.assertEqual(second.read_bytes(), b'')

    def test_concurrent_runs_have_independent_complete_snapshots(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            paths = list(executor.map(lambda _: self.save(), range(12)))
        self.assertEqual(len(set(paths)), 12)
        self.assertTrue(all(path.read_bytes() == self.target.read_bytes() for path in paths))

    def test_argument_parsing_and_scope(self):
        for args in (['-u', 'target.py'], ['-BW', 'ignore', 'target.py'], ['-Xdev', 'target.py'],
                     ['--', 'target.py'], ['--check-hash-based-pycs', 'always', 'target.py']):
            self.assertEqual(collector.script_argument(args), 'target.py')
        for args in (['-c', 'print(1)', 'target.py'], ['-m', 'module', 'target.py'], ['-ummodule'], ['-']):
            self.assertIsNone(collector.script_argument(args))
        self.assertIsNone(collector.archive_script(self.publish, self.archive, ['other.py', str(self.target)]))
        outside = self.base / 'target.py'
        outside.write_text('pass')
        self.assertIsNone(collector.archive_script(self.publish, self.archive, [str(outside)]))
        for branch in ('IoT', 'iot'):
            target = self.publish / branch / 'module/target.py'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('pass')
            self.assertIsNotNone(collector.archive_script(self.publish, self.archive, [str(target)]))

    def test_failures_prevent_exec_and_return_125(self):
        for error in (PermissionError('denied'), OSError(28, 'disk full')):
            with patch('collector.archive_script', side_effect=error), patch('collector.os.execv') as execute, \
                    patch('launcher_runtime.config_directory', return_value=self.base / 'settings'), contextlib.redirect_stderr(io.StringIO()):
                code = collector.main(['--publish-dir', str(self.publish), '--archive-dir', str(self.archive),
                                       '--python', sys.executable, '--', str(self.target)])
            self.assertEqual(code, 125)
            execute.assert_not_called()

    def test_archive_exists_before_interpreter_receives_bad_source(self):
        for raw in (b'def broken(\n', b'import nonexistent_module_93765\n', b'raise RuntimeError("test")\n'):
            self.target.write_bytes(raw)
            def execute(executable, args):
                self.assertEqual(executable, sys.executable)
                self.assertTrue(any(path.read_bytes() == raw for path in self.archive.glob('*.py')))
                self.assertEqual(args[-1], 'original arg')
            with patch('collector.os.execv', side_effect=execute):
                collector.main(['--publish-dir', str(self.publish), '--archive-dir', str(self.archive),
                                '--python', sys.executable, '--', str(self.target), 'original arg'])

    def test_overlay_and_recovery_restore_exact_bytes(self):
        with self.engine.lock():
            overlay.prepare_overlay(self.engine, self.archive)
            data = json.loads(self.config.read_bytes())
            wrapper = Path(data[0]['PythonExePath'])
            self.assertTrue(wrapper.is_file())
            self.assertIn(str(self.archive), wrapper.read_text(encoding='utf-8'))
            overlay.recover_overlay(self.engine)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse((self.engine.state / 'collection-session.json').exists())

    def test_recovery_preserves_application_edits_and_repeated_recovery(self):
        with self.engine.lock():
            overlay.prepare_overlay(self.engine, self.archive)
            tasks = json.loads(self.config.read_bytes())
            tasks[0]['note'] = 'changed by AIoT'
            atomic_json(self.config, tasks)
            self.assertTrue(overlay.recover_overlay(self.engine))
            self.assertFalse(overlay.recover_overlay(self.engine))
        restored = json.loads(self.config.read_bytes())[0]
        self.assertEqual(restored['note'], 'changed by AIoT')
        self.assertEqual(restored['PythonExePath'], sys.executable)

    def test_session_restores_overlay_after_application_failure(self):
        (self.publish / 'AIotApp').write_text('print("mock")')
        (self.publish / 'AIotApp').chmod(0o755)
        # Collection uses the existing active task config, even with a broken
        # competition template and without the other two active JSON files.
        bundle = self.publish / 'config/赛事版本1'
        bundle.mkdir(parents=True)
        (bundle / 'TrainTaskInfo.json').write_bytes(b'{broken')
        code = 'import json;from pathlib import Path;p=Path(json.loads(Path("TrainTaskInfo.json").read_text())[0]["PythonExePath"]);assert p.is_file();raise RuntimeError("mock failure")'
        controller = runtime.SessionController(self.publish, self.base / 'logs', archive_dir=str(self.archive),
                                               collection_enabled=True)
        with patch('launcher_runtime.managed_command', return_value=[sys.executable, '-c', code]):
            controller.start()
            controller.thread.join(10)
        self.assertFalse(controller.thread.is_alive())
        self.assertEqual(self.config.read_bytes(), self.original)
        events = list(controller.events.queue)
        self.assertIsNotNone(events[-1][1]['error'])

    def test_json_cli_check_does_not_apply_configuration(self):
        (self.publish / 'AIotApp').write_text('print("mock")')
        (self.publish / 'AIotApp').chmod(0o755)
        bundle = self.publish / 'config/赛事版本1'
        bundle.mkdir(parents=True)
        for name, raw in (('TrainTaskInfo.json', self.original), ('TrainOverviewInfo.json', b'[]'),
                          ('CodeSampleTuorialInfo.json', b'[]')):
            (bundle / name).write_bytes(raw)
        output = io.StringIO()
        settings_path = self.base / 'settings.json'
        atomic_json(settings_path, {'publish_dir': str(self.publish), 'archive_dir': str(self.archive)})
        with contextlib.redirect_stdout(output), patch('sys.stdin', io.StringIO('')), \
                patch('launcher_runtime.config_directory', return_value=self.base / 'settings'):
            result = session_cli.main(['--publish-dir', str(self.publish), '--check', '--events-json',
                                       '--settings-file', str(settings_path)])
        self.assertEqual(result, 0, output.getvalue())
        event = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(event['event'], 'ready')
        self.assertIsNone(event['data']['error'])
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_cli_config_switch_defaults_and_overrides_without_templates(self):
        (self.publish / 'AIotApp').write_text('print("mock")')
        (self.publish / 'AIotApp').chmod(0o755)
        settings_path = self.base / 'settings.json'
        cases = (({}, [], 0),
                 ({'apply_config_enabled': True}, [], 0),
                 ({'apply_config_enabled': True}, ['--no-apply-config'], 0),
                 ({'apply_config_enabled': False}, ['--apply-config'], 1),
                 ({'apply_config_enabled': 'false'}, [], 1))
        for extra, flags, expected in cases:
            with self.subTest(settings=extra, flags=flags):
                atomic_json(settings_path, dict(publish_dir=str(self.publish), archive_dir=str(self.archive), **extra))
                output = io.StringIO()
                with contextlib.redirect_stdout(output), patch('sys.stdin', io.StringIO('')), \
                        patch('launcher_runtime.config_directory', return_value=self.base / 'settings'):
                    code = session_cli.main(['--publish-dir', str(self.publish), '--check', '--events-json',
                                             '--settings-file', str(settings_path)] + flags)
                self.assertEqual(code, expected, output.getvalue())
                result = json.loads(output.getvalue().splitlines()[-1])['data']
                if expected:
                    self.assertTrue(result['error'])
                    self.assertIn('必须为布尔值' if extra.get('apply_config_enabled') == 'false' else '赛事配置无效',
                                  result['error'])
                else:
                    self.assertIsNone(result['error'])
                self.assertEqual(self.config.read_bytes(), self.original)

    def test_cli_default_launch_does_not_prepare_collection(self):
        (self.publish / 'AIotApp').write_text('print("mock")')
        (self.publish / 'AIotApp').chmod(0o755)
        settings_path = self.base / 'settings.json'
        # Archive settings are unused when collection is disabled.
        atomic_json(settings_path, {'publish_dir': str(self.publish), 'archive_dir': None})
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch('launcher_runtime.config_directory', return_value=self.base / 'settings'), \
                patch('launcher_runtime.managed_command', return_value=[sys.executable, '-c', 'print("basic launch")']), \
                patch('collection_config.prepare_overlay', side_effect=AssertionError('collection must stay off')):
            code = session_cli.main(['--publish-dir', str(self.publish), '--settings-file', str(settings_path)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn('AIoT 已启动', output.getvalue())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse((self.engine.state / 'python-wrappers').exists())

    def test_gui_transport_retries_stop_in_the_same_backend_after_failure(self):
        fixture = self.base / 'fake_session.py'
        fixture.write_text('import json,sys\n'
                           'print(json.dumps({"event":"started","data":{"pid":123}}),flush=True)\n'
                           'assert sys.stdin.readline().strip()=="stop"\n'
                           'print(json.dumps({"event":"stop_failed","data":{"error":"busy"}}),flush=True)\n'
                           'assert sys.stdin.readline().strip()=="stop"\n'
                           'print(json.dumps({"event":"finished","data":{"error":None,"stopped":True}}),flush=True)\n', encoding='utf-8')
        controller = LauncherController(self.publish)
        with patch.object(controller, 'command', return_value=[sys.executable, str(fixture)]):
            controller.start()
            try:
                event, data = controller.events.get(timeout=5)
                self.assertEqual(event, 'started')
                self.assertFalse(controller.start())
                controller.request_stop()
                event, data = controller.events.get(timeout=5)
                self.assertEqual(event, 'stop_failed')
                self.assertTrue(controller.busy)
            finally:
                controller.request_stop()
                controller.thread.join(8)
        self.assertFalse(controller.thread.is_alive())
        event, data = controller.events.get(timeout=1)
        self.assertEqual(event, 'finished')
        self.assertTrue(data['stopped'])
        self.assertFalse(controller.busy)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux executable wrappers and exec semantics')
    def test_real_wrapper_failure_and_success(self):
        with self.engine.lock():
            overlay.prepare_overlay(self.engine, self.archive)
            wrapper = json.loads(self.config.read_bytes())[0]['PythonExePath']
        try:
            for raw, expected in ((b'print("ok")', 0), (b'broken(', 1), (b'import missing_917239', 1)):
                self.target.write_bytes(raw)
                result = subprocess.run([wrapper, '-u', str(self.target)], capture_output=True)
                self.assertEqual(result.returncode, expected)
            self.assertEqual(len(list(self.archive.glob('*.py'))), 3)
        finally:
            with self.engine.lock():
                overlay.recover_overlay(self.engine)


if __name__ == '__main__':
    unittest.main()
