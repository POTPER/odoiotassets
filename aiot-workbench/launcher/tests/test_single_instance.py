from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp"))))))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.directory = self.base / '配置 space/instance'
        self.instances = []
        self.addCleanup(self.close_instances)

    def instance(self):
        instance = SingleInstance(self.directory)
        self.instances.append(instance)
        return instance

    def close_instances(self):
        for instance in self.instances:
            instance.close()

    def test_second_launch_activates_owner_and_does_not_hold_lock(self):
        owner, other = self.instance(), self.instance()
        self.assertTrue(owner.start_or_activate())
        self.assertFalse(other.start_or_activate())
        self.assertTrue(other.activation_succeeded)
        self.assertIsNone(other.stream)
        self.assertTrue(owner.activation_requested())
        self.assertFalse(owner.activation_requested())
        other.close()
        self.assertTrue(owner.endpoint.is_file())
        owner.close()
        self.assertTrue(self.instance().start_or_activate())

    def test_simultaneous_launches_elect_exactly_one_owner(self):
        instances = [self.instance() for _ in range(6)]
        barrier = threading.Barrier(len(instances))
        def start(instance):
            barrier.wait(timeout=5)
            return instance.start_or_activate()
        with ThreadPoolExecutor(max_workers=len(instances)) as pool:
            primary = list(pool.map(start, instances))
        self.assertEqual(primary.count(True), 1)
        self.assertTrue(all(instance.activation_succeeded for instance, owns in zip(instances, primary) if not owns))
        self.assertTrue(instances[primary.index(True)].activation_requested())

    def test_invalid_activation_token_cannot_trigger_window_commands(self):
        owner = self.instance()
        owner.start_or_activate()
        owner.request.write_text(json.dumps({'token': 'wrong', 'request_id': 'a' * 32}), encoding='utf-8')
        self.assertFalse(owner.activation_requested())

    def test_unresponsive_owner_never_creates_a_second_gui(self):
        owner, other = self.instance(), self.instance()
        owner.start_or_activate()
        with patch.object(other, '_activate_existing', return_value=False):
            self.assertFalse(other.start_or_activate(timeout=0.05))
        self.assertFalse(other.activation_succeeded)
        self.assertIsNone(other.stream)

    def test_crash_releases_os_lock_and_stale_metadata_does_not_block_restart(self):
        fixture = self.base / 'owner.py'
        fixture.write_text('import os,sys\n'
                           'sys.path.insert(0,' + repr(str(Path(__file__).resolve().parents[1])) + ')\n'
                           'from single_instance import SingleInstance\n'
                           'instance=SingleInstance(sys.argv[1])\n'
                           'assert instance.start_or_activate()\n'
                           'print("ready",flush=True)\n'
                           'sys.stdin.readline()\n'
                           'os._exit(0)\n', encoding='utf-8')
        process = subprocess.Popen([sys.executable, str(fixture), str(self.directory)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            endpoint = self.directory / 'window.json'
            old = json.loads(endpoint.read_text(encoding='utf-8'))
            process.communicate('\n', timeout=5)
            self.assertTrue(endpoint.exists())
            restarted = self.instance()
            self.assertTrue(restarted.start_or_activate())
            new = json.loads(endpoint.read_text(encoding='utf-8'))
            self.assertNotEqual(old['token'], new['token'])
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

    def test_duplicate_gui_entry_returns_success_without_creating_tk_or_starting_backend(self):
        import aiot_launcher
        self.instance().start_or_activate()
        output = io.StringIO()
        with patch('aiot_launcher.config_directory', return_value=self.directory.parent), \
                patch('aiot_launcher.run_window', side_effect=AssertionError('must not create a new GUI')), \
                patch('aiot_launcher.set_process_role'), contextlib.redirect_stdout(output):
            result = aiot_launcher.main([])
        self.assertEqual(result, 0)
        self.assertIn('已在运行', output.getvalue())


if __name__ == '__main__':
    unittest.main()
