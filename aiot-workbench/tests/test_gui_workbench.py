import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "launcher"))


class WorkbenchGuiTests(unittest.TestCase):
    def test_home_shortcut_and_isolated_engineer_panel(self):
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as exc:
            self.skipTest("Tk desktop unavailable: " + str(exc))
        root.withdraw()
        from workbench_ui import WorkbenchWindow
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "publish"
            target.mkdir()
            settings = base / "settings.json"
            settings.write_text(json.dumps({"publish_dir": str(target)}), encoding="utf-8")
            controller = Mock(publish=target, thread=None, events=queue.Queue())
            ui = WorkbenchWindow(root, controller, settings={"publish_dir": str(target)}, settings_path=settings)
            try:
                ui.handle_event("ready", {"error": None})
                self.assertTrue(root.bind("<Control-Shift-F12>"))
                self.assertEqual(ui.start_button.label, "启动")
                self.assertEqual(ui.exit_button.label, "停止")
                self.assertEqual(ui.update_button.label, "程序更新")
                self.assertEqual(ui.canvas.coords(ui.settings_item)[0], 16)
                self.assertEqual(ui.canvas.coords(ui.start_item)[1], ui.canvas.coords(ui.exit_item)[1])
                child = Mock()
                child.poll.return_value = None
                ui.update_checked = True
                with patch("workbench_ui.subprocess.Popen", return_value=child) as launch:
                    ui.open_engineer()
                command = launch.call_args.args[0]
                self.assertEqual(Path(command[1]), ROOT / "engineer_entry.py")
                self.assertEqual(command[2:], ["--hosted", str(settings), "engineer"])
                self.assertEqual(launch.call_args.kwargs["env"]["AIOT_WORKBENCH_HOST_PID"], str(os.getpid()))
                ui.start()
                controller.start.assert_not_called()
                ui.close()
                self.assertFalse(ui.destroyed)
                ui.engineer_process = None
                ui.update_checked = False
                ui.open_updates()
                self.assertTrue(ui.update_dialog.winfo_exists())
                self.assertEqual(str(ui.apply_btn["state"]), "disabled")
            finally:
                ui.engineer_process = None
                ui.destroy()


if __name__ == "__main__":
    unittest.main()
