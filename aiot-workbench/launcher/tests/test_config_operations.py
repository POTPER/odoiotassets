import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_operations import configure_questions
from config_versions import CONFIG_NAMES
from core import Engine, SyncError, atomic_json
import session_cli
from gui_session import LauncherController


class ConfigOperationTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp"))))))
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.publish = self.base / 'publish space'
        self.bundle = self.publish / 'config/中文赛题 2'
        self.bundle.mkdir(parents=True)
        self.old, self.new = {}, {}
        for name in CONFIG_NAMES:
            self.old[name] = b'[{"old":true}]'
            self.new[name] = ('\ufeff[ {"question": "' + name + '"} ]\r\n').encode('utf-8')
            (self.publish / name).write_bytes(self.old[name])
            # Switcher supports descriptive suffixes and maps to standard names.
            (self.bundle / (Path(name).stem + '_赛题.json')).write_bytes(self.new[name])

    def active(self, expected):
        for name, raw in expected.items():
            self.assertEqual((self.publish / name).read_bytes(), raw)

    def task_files(self):
        targets = ['app/中文任务/target.py', 'app/中文任务/deep/target.py',
                   'IoT/传感任务/target.py', 'iot/another/target.py']
        directories = ['app/中文任务/student_data', 'IoT/传感任务/student_data', 'iot/another/nested/student_data']
        removed, protected = {}, {}
        for relative in targets:
            path = self.publish / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            removed[relative] = ('source ' + relative).encode('utf-8')
            path.write_bytes(removed[relative])
        for relative in directories:
            path = self.publish / relative
            (path / 'nested').mkdir(parents=True)
            for suffix in ('result.json', 'nested/target.py'):
                key = relative + '/' + suffix
                removed[key] = ('result ' + key).encode('utf-8')
                (self.publish / key).write_bytes(removed[key])
        for relative in ('target.py', 'student_data/result.json', 'config/target.py',
                         'config/student_data/keep.json', 'app/target.py', 'app/中文任务/example.py'):
            path = self.publish / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            protected[relative] = b'keep'
            path.write_bytes(protected[relative])
        return targets, directories, removed, protected

    def assert_files(self, files):
        for relative, raw in files.items():
            self.assertEqual((self.publish / relative).read_bytes(), raw, relative)

    def test_replace_cleans_only_generated_files_in_app_and_iot_tasks_with_backup(self):
        targets, directories, removed, protected = self.task_files()
        result = configure_questions(self.publish, self.bundle.name)
        self.active(self.new)
        for relative in targets + directories:
            self.assertFalse((self.publish / relative).exists(), relative)
        for relative, raw in removed.items():
            self.assertEqual((Path(result['backup']) / 'task-files' / relative).read_bytes(), raw)
        self.assert_files(protected)
        self.assertEqual(result['cleanup'], {'target_files': 4, 'student_data_dirs': 3})

    def test_clear_button_operation_does_not_replace_json_and_can_repeat(self):
        targets, directories, removed, protected = self.task_files()
        result = configure_questions(self.publish, clear_only=True)
        self.active(self.old)
        self.assert_files(protected)
        for relative in targets + directories:
            self.assertFalse((self.publish / relative).exists(), relative)
        self.assertEqual(result['cleanup'], {'target_files': 4, 'student_data_dirs': 3})
        repeated = configure_questions(self.publish, clear_only=True)
        self.assertEqual(repeated['cleanup'], {'target_files': 0, 'student_data_dirs': 0})
        self.assertIsNone(repeated['backup'])
        self.active(self.old)

    def test_invalid_question_does_not_clear_generated_files(self):
        _, _, removed, protected = self.task_files()
        next(self.bundle.glob('TrainTaskInfo*.json')).write_bytes(b'broken')
        with self.assertRaises(SyncError):
            configure_questions(self.publish, self.bundle.name)
        self.assert_files(removed)
        self.assert_files(protected)
        self.active(self.old)

    def test_configuration_failure_restores_generated_files_and_json_together(self):
        _, _, removed, protected = self.task_files()
        replace = os.replace
        def fail(source, target):
            if Path(source).parent.name.startswith('config-stage-') and Path(source).name == CONFIG_NAMES[1]:
                raise PermissionError('config failure after cleanup')
            return replace(source, target)
        with patch('config_versions.os.replace', side_effect=fail), self.assertRaises(PermissionError):
            configure_questions(self.publish, self.bundle.name)
        self.active(self.old)
        self.assert_files(removed)
        self.assert_files(protected)

    def test_clear_permission_failure_restores_previously_moved_files(self):
        _, _, removed, protected = self.task_files()
        replace = os.replace
        def fail(source, target):
            if Path(source) == self.publish / 'app/中文任务/student_data':
                raise PermissionError('cleanup denied')
            return replace(source, target)
        with patch('question_cleanup.os.replace', side_effect=fail), self.assertRaisesRegex(PermissionError, 'cleanup denied'):
            configure_questions(self.publish, clear_only=True)
        self.active(self.old)
        self.assert_files(removed)
        self.assert_files(protected)

    def test_interrupted_cleanup_recovers_before_next_start_or_query(self):
        from core import read_json
        _, _, removed, protected = self.task_files()
        replace = os.replace
        journal = Engine(self.publish).state / 'config-transaction.json'
        def fail(source, target):
            if Path(source) == self.publish / 'app/中文任务/student_data':
                raise PermissionError('cleanup interrupted')
            if 'task-files' in Path(source).parts:
                raise PermissionError('rollback interrupted')
            return replace(source, target)
        with patch('question_cleanup.os.replace', side_effect=fail), self.assertRaises(PermissionError):
            configure_questions(self.publish, clear_only=True)
        self.assertEqual(read_json(journal)['schema_version'], 2)
        # The normal launch preflight also calls Engine.startup_recover().
        Engine(self.publish).startup_recover()
        self.assertFalse(journal.exists())
        self.assert_files(removed)
        self.assert_files(protected)
        self.active(self.old)

    def test_linked_task_directory_does_not_clean_external_files(self):
        outside = self.base / 'external'
        outside.mkdir()
        (outside / 'target.py').write_bytes(b'keep external')
        root = self.publish / 'app'
        root.mkdir()
        link = root / 'linked-task'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are unavailable')
        configure_questions(self.publish, clear_only=True)
        self.assertEqual((outside / 'target.py').read_bytes(), b'keep external')

    def test_user_list_hides_invalid_bundles_and_reports_current_without_replacing(self):
        (self.publish / 'config/不完整').mkdir()
        result = configure_questions(self.publish)
        rows = {item['version']: item for item in result['versions']}
        self.assertTrue(rows['中文赛题 2']['valid'])
        self.assertNotIn('不完整', rows)
        self.assertIn('未识别', result['current'])
        self.active(self.old)
        self.bundle.rename(self.bundle.with_name('新名称'))
        self.assertIn('新名称', [row['version'] for row in configure_questions(self.publish)['versions']])

    def test_replace_exact_bytes_preserves_templates_and_backup_without_aiot(self):
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            result = configure_questions(self.publish, self.bundle.name)
        self.active(self.new)
        self.assertIn(self.bundle.name, result['current'])
        for name in CONFIG_NAMES:
            self.assertEqual((Path(result['backup']) / name).read_bytes(), self.old[name])
            self.assertEqual((self.bundle / (Path(name).stem + '_赛题.json')).read_bytes(), self.new[name])
        self.assertFalse((Engine(self.publish).state / 'collection-session.json').exists())

    def test_missing_invalid_conflicting_and_traversal_bundles_do_not_change_active(self):
        for version in ('missing', '../outside'):
            with self.assertRaises(SyncError):
                configure_questions(self.publish, version)
            self.active(self.old)
        file = next(self.bundle.glob('TrainTaskInfo*.json'))
        original = file.read_bytes()
        for raw in (b'invalid', b'{}'):
            file.write_bytes(raw)
            with self.assertRaises(SyncError):
                configure_questions(self.publish, self.bundle.name)
            self.active(self.old)
        file.write_bytes(original)
        (self.bundle / 'TrainTaskInfo_duplicate.json').write_bytes(b'[]')
        with self.assertRaisesRegex(SyncError, '冲突'):
            configure_questions(self.publish, self.bundle.name)
        self.active(self.old)

    def test_second_file_failure_rolls_back_whole_bundle(self):
        replace = os.replace
        def fail(source, target):
            if Path(source).parent.name.startswith('config-stage-') and Path(source).name == CONFIG_NAMES[1]:
                raise PermissionError('injected replacement failure')
            return replace(source, target)
        with patch('config_versions.os.replace', side_effect=fail), self.assertRaisesRegex(PermissionError, 'injected'):
            configure_questions(self.publish, self.bundle.name)
        self.active(self.old)
        self.assertFalse((Engine(self.publish).state / 'config-transaction.json').exists())

    def test_stale_overlay_is_restored_before_backup(self):
        import base64
        import hashlib
        engine = Engine(self.publish)
        original = self.old[CONFIG_NAMES[0]]
        patched = b'[{"PythonExePath":"temporary-wrapper"}]'
        (self.publish / CONFIG_NAMES[0]).write_bytes(patched)
        atomic_json(engine.state / 'collection-session.json', {
            'original': base64.b64encode(original).decode('ascii'),
            'patched_sha256': hashlib.sha256(patched).hexdigest(),
            'interpreters': {'temporary-wrapper': '/usr/bin/python3'}})
        result = configure_questions(self.publish, self.bundle.name)
        self.assertEqual((Path(result['backup']) / CONFIG_NAMES[0]).read_bytes(), original)
        self.assertFalse((engine.state / 'collection-session.json').exists())
        self.active(self.new)

    def test_shared_lock_and_running_program_block_replacement(self):
        with Engine(self.publish).lock(), self.assertRaisesRegex(SyncError, '另一个'):
            configure_questions(self.publish, self.bundle.name)
        with patch('core.assert_stopped', side_effect=SyncError('publish 仍被程序使用')), self.assertRaisesRegex(SyncError, '仍被'):
            configure_questions(self.publish, self.bundle.name)
        self.active(self.old)

    def test_cancel_before_replacement_and_signal_during_commit(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(SyncError):
            configure_questions(self.publish, self.bundle.name, cancel=stop)
        self.active(self.old)
        stop.clear()
        replace = os.replace
        def stopping(source, target):
            if Path(source).parent.name.startswith('config-stage-'):
                stop.set()
            return replace(source, target)
        with patch('config_versions.os.replace', side_effect=stopping):
            configure_questions(self.publish, self.bundle.name, cancel=stop)
        self.active(self.new)
        self.assertFalse((Engine(self.publish).state / 'config-transaction.json').exists())

    def test_failed_rollback_preserves_journal_and_next_operation_recovers(self):
        replace = os.replace
        def fail(source, target):
            if Path(source).parent.name.startswith('config-stage-') and Path(source).name == CONFIG_NAMES[1]:
                raise PermissionError('commit denied')
            if Path(source).name.startswith('rollback-'):
                raise PermissionError('rollback denied')
            return replace(source, target)
        with patch('config_versions.os.replace', side_effect=fail), self.assertRaises(PermissionError):
            configure_questions(self.publish, self.bundle.name)
        journal = Engine(self.publish).state / 'config-transaction.json'
        self.assertTrue(journal.exists())
        configure_questions(self.publish)
        self.assertFalse(journal.exists())
        self.active(self.old)

    def test_cli_json_and_terminal_interfaces_do_not_require_main_binary(self):
        for flags in (['--list-configs'], ['--replace-config', self.bundle.name], ['--clear-task-data']):
            output = io.StringIO()
            # GUI keeps stdin open; avoid a synthetic empty test pipe cancelling work.
            with contextlib.redirect_stdout(output), patch('session_cli.threading.Thread'), \
                    patch('launcher_runtime.config_directory', return_value=self.base / 'settings'):
                code = session_cli.main(['--publish-dir', str(self.publish), '--events-json'] + flags)
            self.assertEqual(code, 0, output.getvalue())
            event = json.loads(output.getvalue())
            self.assertEqual(event['event'], 'finished')
            self.assertIsNone(event['data']['error'])
            self.assertTrue(Path(event['data']['logfile']).is_file())
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('launcher_runtime.config_directory', return_value=self.base / 'settings'):
            self.assertEqual(session_cli.main(['--publish-dir', str(self.publish), '--list-configs']), 0)
        self.assertIn(self.bundle.name, output.getvalue())
        self.active(self.new)

    def test_gui_commands_preserve_current_configuration_and_quote_version_as_argument(self):
        (self.publish.parent / 'launcher.sh').write_text('#!/bin/bash\n')
        controller = LauncherController(self.publish)
        with patch('gui_session.os.name', 'posix'), patch('gui_session.shutil.which', return_value='/bin/bash'):
            command = controller.command(False, ('--replace-config', '中文赛题 $name'))
            self.assertIn('--no-apply-config', controller.command(False))
            self.assertEqual(command[-2:], ['--replace-config', '中文赛题 $name'])

    def test_real_gui_transport_queries_and_replaces_through_backend_process(self):
        controller = LauncherController(self.publish)
        def command(check, extra):
            return [sys.executable, session_cli.__file__, '--publish-dir', str(self.publish), '--events-json'] + list(extra)
        with patch.object(controller, 'command', side_effect=command), \
                patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.base / 'settings')}):
            for invoke in (controller.list_configs, lambda: controller.replace_config(self.bundle.name), controller.clear_task_data):
                self.assertTrue(invoke())
                controller.thread.join(10)
                self.assertFalse(controller.thread.is_alive())
                event, data = controller.events.get(timeout=1)
                self.assertEqual(event, 'finished')
                self.assertIsNone(data['error'])
                self.assertFalse(controller.busy)
        self.active(self.new)


if __name__ == '__main__':
    unittest.main()
