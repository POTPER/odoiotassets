import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_identity import LAUNCH_METADATA, child_environment, configure_launcher_window


class DesktopIdentityTests(unittest.TestCase):
    def test_children_get_display_and_runtime_environment_without_launcher_identity(self):
        original = {key: 'launcher-owned-value' for key in LAUNCH_METADATA}
        session = {'DISPLAY': ':0', 'WAYLAND_DISPLAY': 'wayland-0', 'XAUTHORITY': '/tmp/xauth',
                   'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/bus', 'PATH': '/usr/bin',
                   'LANG': 'zh_CN.UTF-8', 'LIBGL_ALWAYS_SOFTWARE': '1', 'CUSTOM_RUNTIME': 'keep'}
        original.update(session)
        snapshot = dict(original)
        result = child_environment(original)
        self.assertEqual(result, session)
        self.assertEqual(original, snapshot)

    def test_x11_launcher_is_a_normal_independent_window(self):
        root = Mock()
        root.tk.call.return_value = 'x11'
        configure_launcher_window(root)
        root.wm_attributes.assert_called_once_with('-type', 'normal')
        root.wm_transient.assert_called_once_with('')
        root.wm_group.assert_called_once_with('')

    def test_other_window_systems_do_not_receive_x11_attributes(self):
        for system in ('win32', 'aqua'):
            root = Mock()
            root.tk.call.return_value = system
            configure_launcher_window(root)
            root.wm_attributes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
