from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher_process as identity


class LauncherProcessTests(unittest.TestCase):
    def setUp(self):
        folder = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp"))))))
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def test_linux_names_are_short_and_distinct_from_task_interpreters(self):
        for role, name in identity.ROLE_NAMES.items():
            libc = Mock()
            libc.prctl.return_value = 0
            with patch.object(identity.sys, 'platform', 'linux'), patch.object(identity.ctypes, 'CDLL', return_value=libc):
                identity.set_process_role(role)
            libc.prctl.assert_called_once_with(15, name.encode('ascii'), 0, 0, 0)
            self.assertLessEqual(len(name.encode('ascii')), 15)
            self.assertNotIn('python', name)

    def test_virtualenv_keeps_its_selected_interpreter(self):
        with patch.object(identity.sys, 'platform', 'linux'), patch.object(identity.sys, 'prefix', 'virtual-env'), \
                patch.object(identity.sys, 'base_prefix', 'system-env'):
            result = identity.install_interpreters(self.base)
        self.assertTrue(all(value == sys.executable for value in result.values()))
        self.assertFalse((self.base / 'runtime').exists())

    def test_desktop_selects_its_sibling_gui_interpreter(self):
        desktop = self.base / identity.ROLE_NAMES['desktop']
        gui = self.base / identity.ROLE_NAMES['gui']
        gui.write_bytes(b'test fixture')
        with patch.object(identity.sys, 'executable', str(desktop)), patch.object(identity.os.path, 'samefile', return_value=True):
            self.assertEqual(identity.interpreter_for('gui'), str(gui))

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux /proc and interpreter symlinks')
    def test_only_task_process_is_selected_by_python_cleanup_not_launcher_roles(self):
        aliases = identity.install_interpreters(self.base / 'config')
        module_dir = str(Path(identity.__file__).resolve().parent)
        worker = self.base / 'worker.py'
        worker.write_text('import sys\nfrom pathlib import Path\n'
                          'sys.path.insert(0,' + repr(module_dir) + ')\n'
                          'from launcher_process import set_process_role\n'
                          'if sys.argv[1] != "task": set_process_role(sys.argv[1])\n'
                          'print(Path("/proc/self/comm").read_text().strip(),flush=True)\n'
                          'sys.stdin.readline()\n', encoding='utf-8')
        children = []
        try:
            for role in ('desktop', 'gui', 'session', 'task'):
                executable = sys.executable if role == 'task' else aliases[role]
                process = subprocess.Popen([executable, str(worker), role], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                children.append(process)
                name = process.stdout.readline().strip()
                self.assertEqual(name, identity.ROLE_NAMES[role] if role != 'task' else Path(sys.executable).name[:15])
            # Reproduce name-based cleanup, restricted to the PIDs created by this test.
            # Never use system-wide pkill/killall in tests.
            for process in children:
                name = (Path('/proc') / str(process.pid) / 'comm').read_text().strip()
                if name.startswith('python'):
                    os.kill(process.pid, signal.SIGTERM)
            self.assertLess(children[-1].wait(timeout=3), 0)
            self.assertTrue(all(process.poll() is None for process in children[:-1]))
        finally:
            for process in children:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
