import os
"""Exercise the real Tk widgets with a fake process controller."""
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

try:
    import tkinter as tk
except ImportError:
    tk = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiot_launcher import LauncherWindow


class FakeController:
    def __init__(self):
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.starts = 0

    def initialize(self):
        self.events.put(("ready", {"error": None}))

    def start(self):
        self.starts += 1
        self.stop_event.clear()
        return True

    def request_stop(self):
        self.stop_event.set()


@unittest.skipIf(tk is None, "Tkinter unavailable")
class LauncherGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.cleanup)
        self.background = Path(self.temp.name) / "background.png"
        self.controller = FakeController()
        self.ui = LauncherWindow(self.root, self.controller, self.background,
                                 settings={"publish_dir": str(Path(self.temp.name) / "publish")},
                                 settings_path=Path(self.temp.name) / "settings.json")
        self.ui.handle_event(*self.controller.events.get_nowait())

    def cleanup(self):
        import gc
        if not self.ui.destroyed:
            self.ui.destroy()
        if self.ui.results_panel is not None:
            self.ui.results_panel.wait()
        self.ui = None
        self.root = None
        gc.collect()

    def finish(self):
        self.ui.handle_event("finished", {"error": None, "stopped": True, "returncode": 0})

    def test_start_running_exit_returns_to_start_and_rejects_double_click(self):
        self.assertIsNone(self.ui.photo)
        self.assertEqual(self.ui.start_button.cget("text"), "启动")
        self.ui.start_button.invoke()
        self.ui.start_button.invoke()
        self.assertEqual(self.controller.starts, 1)
        self.ui.handle_event("started", None)
        self.assertEqual(self.ui.start_button.cget("text"), "运行中")
        self.assertEqual(str(self.ui.exit_button.cget("state")), "normal")
        self.ui.exit_button.invoke()
        self.assertTrue(self.controller.stop_event.is_set())
        self.assertEqual(str(self.ui.exit_button.cget("state")), "disabled")
        self.finish()
        self.assertEqual(self.ui.start_button.cget("text"), "启动")
        self.assertEqual(str(self.ui.start_button.cget("state")), "normal")
        self.assertFalse(self.ui.destroyed)

    def test_stable_keeps_launcher_visible_and_controls_available(self):
        self.ui.start()
        self.ui.handle_event("started", None)
        with patch.object(self.root, "iconify") as iconify:
            self.ui.handle_event("stable", None)
            iconify.assert_not_called()
        self.assertEqual(self.ui.start_button.cget("text"), "运行中")
        self.assertEqual(str(self.ui.exit_button.cget("state")), "normal")
        self.assertEqual(str(self.ui.results_button.cget("state")), "normal")
        self.ui.stop()
        with patch.object(self.root, "iconify") as iconify:
            self.ui.handle_event("stable", None)
            iconify.assert_not_called()

    def test_losing_focus_and_unmapping_do_not_stop_aiot_or_close_launcher(self):
        self.root.deiconify()
        self.root.update()
        self.ui.start()
        self.ui.handle_event("started", {"pid": 123})
        for _ in range(3):
            self.root.event_generate("<FocusOut>")
            self.root.event_generate("<KeyPress-Tab>", state=8)
            self.root.event_generate("<KeyRelease-Tab>", state=8)
            self.root.withdraw()
            self.root.update()
            self.root.deiconify()
            self.root.event_generate("<FocusIn>")
            self.root.update()
        self.assertFalse(self.ui.destroyed)
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.controller.stop_event.is_set())
        self.assertEqual(self.ui.start_button.cget("text"), "运行中")
        self.assertEqual(self.root.state(), "normal")
        self.finish()

    def test_repeated_launch_restores_running_window_without_restarting_aiot(self):
        from single_instance import SingleInstance
        directory = Path(self.temp.name) / 'instance'
        owner, repeated = SingleInstance(directory), SingleInstance(directory)
        try:
            self.assertTrue(owner.start_or_activate())
            self.ui.instance = owner
            self.ui.start()
            self.ui.handle_event('started', {'pid': 123})
            self.ui.settings['submission_enabled'] = True
            self.ui.results_dir = Path(self.temp.name) / '成果输出'
            self.ui.view_results()
            self.assertTrue(self.ui.results_panel.visible)
            self.root.withdraw()
            self.assertFalse(repeated.start_or_activate())
            with patch.object(self.root, 'focus_force') as focus:
                self.ui.poll()
            self.assertEqual(self.root.state(), 'normal')
            self.assertFalse(self.ui.results_panel.visible)
            self.assertEqual(self.ui.canvas.itemcget(self.ui.results_panel_item, 'state'), 'hidden')
            focus.assert_called_once_with()
            self.assertEqual(self.ui.start_button.cget('text'), '运行中')
            self.assertEqual(self.controller.starts, 1)
            self.assertFalse(self.controller.stop_event.is_set())
            self.finish()
        finally:
            self.ui.instance = None
            owner.close()
            repeated.close()

    def test_existing_settings_dialog_keeps_focus_when_launcher_is_activated(self):
        with patch('launcher_settings.request_settings_access', return_value=True):
            self.ui.open_settings()
        dialog = self.ui.settings_dialog
        with patch.object(dialog.window, 'focus_force') as dialog_focus, patch.object(self.root, 'focus_force') as root_focus:
            self.ui.activate()
        dialog_focus.assert_called_once_with()
        root_focus.assert_not_called()
        dialog.cancel()

    def test_activation_failure_keeps_processing_finished_event_and_reschedules_poll(self):
        self.ui.start()
        self.ui.handle_event('started', {'pid': 123})
        self.ui.instance = Mock()
        self.ui.instance.activation_requested.return_value = True
        self.controller.events.put(('finished', {'error': None, 'stopped': False, 'returncode': 0}))
        with patch.object(self.ui, 'activate', side_effect=tk.TclError('focus unavailable')), \
                patch.object(self.root, 'after', return_value='scheduled') as schedule, \
                patch.object(self.ui, 'audit') as log:
            self.ui.poll()
        self.assertFalse(self.ui.busy)
        self.assertEqual(self.ui.start_button.cget('text'), '启动')
        schedule.assert_called_once_with(50, self.ui.poll)
        self.assertTrue(any(call.args[0] == 'window-activation-error' for call in log.call_args_list))

    def test_unexpected_poll_error_is_logged_and_next_poll_is_scheduled(self):
        with patch.object(self.ui, 'poll_events', side_effect=RuntimeError('injected event error')), \
                patch.object(self.root, 'after', return_value='scheduled') as schedule, \
                patch.object(self.ui, 'audit') as log:
            self.ui.poll()
        schedule.assert_called_once_with(50, self.ui.poll)
        self.assertEqual(log.call_args.args[0], 'poll-error')
        self.assertFalse(self.ui.destroyed)

    def test_close_cancel_keeps_running_and_confirm_waits_for_cleanup(self):
        self.ui.start()
        self.ui.handle_event("started", None)
        with patch("tkinter.messagebox.askyesno", return_value=False):
            self.ui.close()
        self.assertFalse(self.controller.stop_event.is_set())
        self.assertFalse(self.ui.closing)
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.ui.close()
        self.assertTrue(self.controller.stop_event.is_set())
        self.assertFalse(self.ui.destroyed)
        self.finish()
        self.assertTrue(self.ui.destroyed)

    def test_failure_restores_controls_and_reports_log_location(self):
        self.ui.start()
        with patch.object(self.ui, 'report_error') as error:
            self.ui.handle_event("finished", {"error": "mock error", "logfile": "/tmp/mock.log"})
        self.assertEqual(error.call_args.args[1]['logfile'], '/tmp/mock.log')
        self.assertEqual(self.ui.start_button.cget("text"), "启动")
        self.assertEqual(str(self.ui.exit_button.cget("state")), "disabled")

    def test_initial_check_failure_shows_actual_cause_and_log(self):
        with patch.object(self.ui, 'report_error') as error:
            self.ui.handle_event("ready", {"error": "缺少 launcher.sh，请重新安装。", "logfile": "/tmp/check.log"})
        self.assertEqual(error.call_args.args[0], "启动器检查失败")
        self.assertIn("缺少 launcher.sh", error.call_args.args[1]['error'])
        self.assertEqual(error.call_args.args[1]['logfile'], '/tmp/check.log')
        self.assertEqual(self.ui.status.get(), "启动检查失败。")
        self.assertEqual(str(self.ui.start_button.cget("state")), "normal")

    def test_external_aiot_status_prevents_duplicates_and_returns_to_idle_after_exit(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.assertTrue(self.ui.external_running)
        self.assertEqual(self.ui.start_button.cget('text'), '运行中')
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'normal')
        self.ui.start()
        self.assertEqual(self.controller.starts, 0)
        self.assertFalse(self.controller.stop_event.is_set())
        self.ui.handle_event('ready', {'error': None})
        self.assertFalse(self.ui.external_running)
        self.assertFalse(self.ui.busy)
        self.assertEqual(self.ui.start_button.cget('text'), '启动')

    def test_closing_external_aiot_cancel_preserves_both_windows(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        with patch('tkinter.messagebox.askyesno', return_value=False):
            self.ui.close()
        self.ui.external_stop_controller.stop_existing.assert_not_called()
        self.assertFalse(self.controller.stop_event.is_set())
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.ui.destroyed)

    def test_closing_external_aiot_confirm_stops_then_exits_after_cleanup(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        with patch('tkinter.messagebox.askyesno', return_value=True) as confirm:
            self.ui.close()
        confirm.assert_called_once()
        self.ui.external_stop_controller.stop_existing.assert_called_once_with()
        self.assertFalse(self.ui.destroyed)
        self.assertTrue(self.ui.closing)
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertTrue(self.ui.destroyed)

    def test_closing_external_aiot_waits_for_initial_observer_to_finish(self):
        self.controller.busy = True
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        with patch('tkinter.messagebox.askyesno', return_value=True):
            self.ui.close()
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertTrue(self.controller.stop_event.is_set())
        self.assertFalse(self.ui.destroyed)
        self.controller.busy = False
        self.ui.handle_event('ready', {'error': None})
        self.assertTrue(self.ui.destroyed)

    def test_aiot_exit_during_close_confirmation_does_not_leave_window_stuck(self):
        self.ui.start()
        def finish_while_asking(*args, **kwargs):
            self.finish()
            return True
        with patch('tkinter.messagebox.askyesno', side_effect=finish_while_asking):
            self.ui.close()
        self.assertTrue(self.ui.destroyed)

    def test_external_detection_during_close_confirmation_stops_external_aiot(self):
        self.ui.start()
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        def detected_while_asking(*args, **kwargs):
            self.ui.handle_event('external_running', {'pids': [12345]})
            return True
        with patch('tkinter.messagebox.askyesno', side_effect=detected_while_asking):
            self.ui.close()
        self.ui.external_stop_controller.stop_existing.assert_called_once_with()
        self.assertFalse(self.ui.destroyed)
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertTrue(self.ui.destroyed)

    def test_external_detection_after_closing_began_stops_external_aiot(self):
        self.ui.start()
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.close(force=True)
        self.assertTrue(self.ui.closing)
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller.stop_existing.assert_called_once_with()
        self.ui.handle_event('finished', {'error': None})
        self.assertFalse(self.ui.destroyed)
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertTrue(self.ui.destroyed)

    def test_closing_idle_window_rechecks_for_external_launch_between_samples(self):
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        with patch('aiot_launcher.find_running_aiot', return_value=[12345]), \
                patch('tkinter.messagebox.askyesno', return_value=True):
            self.ui.close()
        self.ui.external_stop_controller.stop_existing.assert_called_once_with()
        self.assertFalse(self.ui.destroyed)
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertTrue(self.ui.destroyed)

    def test_stop_failure_while_closing_keeps_window_and_allows_retry(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.close(force=True)
        with patch.object(self.ui, 'report_error') as error:
            self.ui.handle_external_stop('finished', {'error': '无权限', 'logfile': '/tmp/stop.log'})
        self.assertEqual(error.call_args.args[1]['logfile'], '/tmp/stop.log')
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.ui.destroyed)
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'normal')
        self.ui.stop()
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertFalse(self.ui.destroyed)
        self.assertFalse(self.ui.busy)

    def test_managed_stop_failure_while_closing_keeps_controls_for_same_session_retry(self):
        self.ui.start()
        self.ui.handle_event('started', {'pid': 123})
        self.ui.close(force=True)
        failure = {'error': '任务仍在运行', 'logfile': '/tmp/stop.log'}
        with patch.object(self.ui, 'report_error') as error:
            self.ui.handle_event('stop_failed', failure)
        error.assert_called_once_with('AIoT 停止失败', failure)
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.ui.destroyed)
        self.assertTrue(self.ui.busy)
        self.assertEqual(str(self.ui.start_button.cget('state')), 'disabled')
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'normal')
        self.controller.stop_event.clear()  # Transport consumes the prior stop request.
        self.ui.close(force=True)
        self.assertTrue(self.controller.stop_event.is_set())
        self.assertFalse(self.ui.destroyed)
        self.finish()
        self.assertTrue(self.ui.destroyed)

    def test_terminal_error_during_close_reports_failure_and_keeps_window(self):
        self.ui.start()
        self.ui.close(force=True)
        failure = {'error': '启动会话提前结束'}
        with patch.object(self.ui, 'report_error') as error:
            self.ui.handle_event('finished', failure)
        error.assert_called_once_with('AIoT 停止失败', failure)
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.ui.destroyed)

    def test_new_external_instance_after_stop_keeps_window_open(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.close(force=True)
        with patch('tkinter.messagebox.showwarning') as warning:
            self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': [12346]})
        warning.assert_called_once()
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.ui.destroyed)
        self.assertEqual(self.ui.external_pids, [12346])

    def test_close_stop_dispatch_failure_does_not_leave_window_stuck(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.external_stop_controller.stop_existing.return_value = False
        with patch.object(self.ui, 'report_error') as error:
            self.ui.close(force=True)
        error.assert_called_once()
        self.assertFalse(self.ui.closing)
        self.assertFalse(self.ui.destroyed)

    def test_close_scan_failure_preserves_window_and_reports_reason(self):
        with patch('aiot_launcher.find_running_aiot', side_effect=OSError('proc unavailable')), \
                patch.object(self.ui, 'report_error') as error:
            self.ui.close()
        self.assertIn('proc unavailable', error.call_args.args[1]['error'])
        self.assertFalse(self.ui.destroyed)

    def status_sample(self, pids=(), error=None, started=None):
        self.ui.handle_process_status({'sample_started': time.monotonic() if started is None else started,
                                       'pids': list(pids), 'error': error})

    def test_external_launch_after_idle_updates_controls_and_exit_restores_start(self):
        self.status_sample([12345])
        self.assertTrue(self.ui.external_running)
        self.assertEqual(self.ui.start_button.cget('text'), '运行中')
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'normal')
        self.ui.start()
        self.assertEqual(self.controller.starts, 0)
        self.status_sample()
        self.assertFalse(self.ui.busy)
        self.assertEqual(self.ui.start_button.cget('text'), '启动')
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'disabled')

    def test_status_samples_cannot_override_owned_lifecycle_config_or_newer_state(self):
        self.status_sample([12345], started=self.ui.status_epoch - 1)
        self.assertFalse(self.ui.external_running)
        self.ui.config_busy = True
        self.status_sample([12345])
        self.assertFalse(self.ui.external_running)
        self.ui.config_busy = False
        self.ui.start()
        self.status_sample([12345])
        self.assertFalse(self.ui.external_running)
        self.assertEqual(self.ui.start_button.cget('text'), '启动中…')
        self.ui.handle_event('started', None)
        self.status_sample()
        self.assertEqual(self.ui.start_button.cget('text'), '运行中')
        self.assertTrue(self.ui.busy)

    def test_status_check_error_blocks_duplicates_and_recovers_on_next_scan(self):
        self.status_sample(error='permission denied')
        self.assertEqual(str(self.ui.start_button.cget('state')), 'disabled')
        self.status_sample()
        self.assertEqual(str(self.ui.start_button.cget('state')), 'normal')
        self.status_sample([12345])
        self.status_sample(error='permission denied')
        self.assertTrue(self.ui.external_running)
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'normal')

    def test_explicit_stop_of_external_aiot_disables_repeats_and_recovers(self):
        self.status_sample([12345])
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.external_stop_controller.stop_existing.return_value = True
        self.ui.stop()
        self.ui.stop()
        self.ui.external_stop_controller.stop_existing.assert_called_once_with()
        self.assertFalse(self.controller.stop_event.is_set())
        self.assertEqual(self.ui.start_button.cget('text'), '停止中…')
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'disabled')
        self.status_sample()
        self.assertTrue(self.ui.external_stopping)
        self.ui.handle_external_stop('finished', {'error': None, 'remaining_pids': []})
        self.assertFalse(self.ui.busy)
        self.assertEqual(self.ui.start_button.cget('text'), '启动')

    def test_stop_failure_restores_retry_and_reports_log(self):
        self.status_sample([12345])
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.stop()
        with patch.object(self.ui, 'report_error') as error:
            self.ui.handle_external_stop('finished', {'error': '无权限', 'logfile': '/tmp/stop.log'})
        self.assertEqual(error.call_args.args[1]['logfile'], '/tmp/stop.log')
        self.assertTrue(self.ui.external_running)
        self.assertFalse(self.ui.external_stopping)
        self.assertEqual(str(self.ui.exit_button.cget('state')), 'normal')

    def test_closing_during_explicit_external_stop_waits_for_its_completion(self):
        self.status_sample([12345])
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.stop()
        self.ui.close()
        self.assertFalse(self.ui.destroyed)
        self.ui.handle_external_stop('finished', {'error': None})
        self.assertTrue(self.ui.destroyed)

    def test_initial_observer_exit_cannot_reset_controls_while_stop_still_running(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.ui.stop()
        self.ui.handle_event('ready', {'error': None})
        self.assertTrue(self.ui.external_stopping)
        self.assertEqual(self.ui.start_button.cget('text'), '停止中…')
        self.ui.handle_external_stop('finished', {'error': None})
        self.assertEqual(self.ui.start_button.cget('text'), '启动')

    def test_stop_completion_waits_for_existing_observer_and_handles_new_instances(self):
        self.ui.handle_event('external_running', {'pids': [12345]})
        self.ui.external_stop_controller = Mock(events=queue.Queue())
        self.controller.busy = True
        self.ui.stop()
        self.ui.handle_external_stop('finished', {'error': None})
        self.assertTrue(self.ui.busy)
        self.controller.busy = False
        self.ui.handle_event('ready', {'error': None})
        self.status_sample([12346])
        self.assertTrue(self.ui.external_running)
        self.assertEqual(self.ui.external_pids, [12346])

    def test_status_worker_queue_and_shutdown_are_integrated(self):
        monitor = Mock(events=queue.Queue())
        self.ui.status_monitor = monitor
        monitor.events.put({'sample_started': time.monotonic(), 'pids': [12345], 'error': None})
        self.ui.poll_events()
        self.assertTrue(self.ui.external_running)
        self.ui.destroy()
        monitor.close.assert_called_once_with()

    def test_window_opens_with_python38_font_api_and_default_family(self):
        from tkinter import font
        self.ui.destroy()
        self.root = tk.Tk()
        self.root.withdraw()
        original = font.nametofont
        # CPython 3.8 nametofont accepts only the font name, without root.
        def python38_nametofont(name):
            return original(name)
        with patch("tkinter.font.nametofont", side_effect=python38_nametofont), \
                patch("tkinter.font.families", return_value=()):
            self.ui = LauncherWindow(self.root, FakeController(), self.background)
        self.ui.handle_event(*self.ui.controller.events.get_nowait())
        self.assertEqual(self.ui.start_button.cget("state"), "normal")
        self.assertIn("TkDefaultFont", self.root.tk.splitlist(self.root.tk.call("font", "names")))

    def test_background_can_be_added_or_corrupt_without_blocking_controls(self):
        self.ui.destroy()
        # Generate a tiny valid fixture using Tk's own PNG writer.
        self.root = tk.Tk()
        self.root.withdraw()
        photo = tk.PhotoImage(master=self.root, width=2, height=2)
        photo.put("#123456", to=(0, 0, 2, 2))
        photo.write(str(self.background), format="png")
        self.ui = LauncherWindow(self.root, FakeController(), self.background)
        self.assertIsNotNone(self.ui.photo)
        self.ui.destroy()
        self.background.write_bytes(b"bad image")
        self.root = tk.Tk()
        self.root.withdraw()
        self.ui = LauncherWindow(self.root, FakeController(), self.background)
        self.ui.handle_event(*self.ui.controller.events.get_nowait())
        self.assertIsNone(self.ui.photo)
        self.assertEqual(str(self.ui.start_button.cget("state")), "normal")

    def test_window_is_fixed_and_buttons_fit_over_background(self):
        self.root.geometry("640x400")
        self.root.deiconify()
        self.root.update()
        self.assertEqual(tuple(map(int, self.root.resizable())), (0, 0))
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (1100, 620))
        self.assertGreater(self.ui.exit_button.winfo_rootx(), self.ui.start_button.winfo_rootx())
        self.assertGreater(self.ui.results_button.winfo_rootx(), self.ui.exit_button.winfo_rootx())
        self.assertLessEqual(self.ui.exit_button.winfo_rootx() + self.ui.exit_button.winfo_width(),
                             self.root.winfo_rootx() + self.root.winfo_width())
        self.assertLessEqual(self.ui.exit_button.winfo_rooty() + self.ui.exit_button.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())

    def test_settings_preview_cancel_and_save_do_not_change_running_state(self):
        import json
        from launcher_style import palette
        self.ui.start()
        self.ui.handle_event("started", None)
        with patch("launcher_settings.request_settings_access", return_value=True):
            self.ui.open_settings()
        dialog = self.ui.settings_dialog
        dialog.theme_buttons[1].invoke()
        self.assertEqual(self.ui.theme, "light")
        self.assertEqual(self.ui.canvas.cget("background"), palette("light")["bg"])
        self.assertEqual(self.ui.start_button.cget("text"), "运行中")
        dialog.cancel_button.invoke()
        self.assertEqual(self.ui.theme, "dark")
        self.assertFalse(self.ui.settings_path.exists())
        with patch("launcher_settings.request_settings_access", return_value=True):
            self.ui.open_settings()
        dialog = self.ui.settings_dialog
        folder = Path(self.temp.name).resolve() / "成果目录 space"
        dialog.directory.set(str(folder))
        dialog.theme_buttons[1].invoke()
        dialog.save_button.invoke()
        self.assertFalse(dialog.window.winfo_exists())
        saved = json.loads(self.ui.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], "light")
        self.assertEqual(self.ui.results_dir, folder)
        self.assertFalse(self.controller.stop_event.is_set())
        self.assertEqual(str(self.ui.results_button.cget("state")), "normal")

    def open_question_settings(self):
        self.ui.config_controller = Mock(events=queue.Queue(), thread=None)
        self.ui.config_controller.list_configs.return_value = True
        self.ui.config_controller.replace_config.return_value = True
        with patch("launcher_settings.request_settings_access", return_value=True):
            self.ui.open_settings()
        self.root.update_idletasks()
        return self.ui.settings_dialog

    def test_question_tab_lists_valid_and_invalid_and_only_replace_button_applies(self):
        dialog = self.open_question_settings()
        panel = dialog.config_panel
        self.assertEqual([dialog.notebook.tab(tab, "text") for tab in dialog.notebook.tabs()], ["常规", "切换赛题"])
        dialog.notebook.select(panel)
        self.root.update()
        self.ui.config_controller.list_configs.assert_called_once_with()
        self.ui.handle_config_event("finished", {
            "error": None, "current": "配置版本：自定义／未识别", "versions": [
                {"version": "无效赛题", "valid": False, "issues": ["缺少 TrainTaskInfo.json"]},
                {"version": "中文赛题 2", "valid": True, "issues": []}]})
        self.assertIn("未识别", panel.current.get())
        panel.table.selection_set("0")
        panel.selection_changed()
        self.assertIn("缺少", panel.message.get())
        self.assertEqual(str(panel.replace_button.cget("state")), "disabled")
        panel.table.selection_set("1")
        panel.selection_changed()
        self.ui.config_controller.replace_config.assert_not_called()
        panel.replace_button.invoke()
        self.assertTrue(self.ui.config_busy)
        self.assertEqual(panel.message.get(), "正在替换…")
        panel.replace_button.invoke()
        self.ui.config_controller.replace_config.assert_called_once_with("中文赛题 2")
        self.ui.start()
        self.assertEqual(self.controller.starts, 0)
        dialog.cancel()
        dialog.save()
        self.assertTrue(dialog.window.winfo_exists())
        self.ui.handle_config_event("finished", {"error": None, "current": "配置版本：中文赛题 2", "version": "中文赛题 2"})
        self.assertFalse(self.ui.config_busy)
        self.assertEqual(panel.message.get(), "已切换：中文赛题 2")
        self.assertIn("中文赛题 2", panel.current.get())
        self.assertEqual(str(self.ui.start_button.cget("state")), "normal")
        dialog.cancel()
        self.assertFalse(self.ui.settings_path.exists())

    def test_question_switch_blocked_while_aiot_runs_and_errors_allow_retry(self):
        self.ui.start()
        dialog = self.open_question_settings()
        panel = dialog.config_panel
        dialog.notebook.select(panel)
        self.root.update()
        self.assertIn("停止 AIoT", panel.message.get())
        panel.refresh_button.invoke()
        panel.clear_button.invoke()
        self.assertFalse(self.ui.clear_task_data())
        self.ui.config_controller.clear_task_data.assert_not_called()
        self.assertFalse(self.ui.replace_config("赛题"))
        self.ui.config_controller.list_configs.assert_not_called()
        self.finish()
        self.root.update()
        panel.refresh_button.invoke()
        self.assertTrue(self.ui.config_busy)
        self.ui.handle_config_event("finished", {"error": "另一个工具正在操作 publish。"})
        self.assertIn("另一个", panel.message.get())
        self.assertEqual(str(panel.refresh_button.cget("state")), "normal")
        self.assertFalse(self.ui.config_busy)
        dialog.cancel()

    def test_clear_button_cleans_without_selection_and_blocks_duplicate_operations(self):
        dialog = self.open_question_settings()
        panel = dialog.config_panel
        self.assertEqual(panel.clear_button.cget("text"), "清除")
        self.assertEqual(str(panel.clear_button.cget("state")), "normal")
        panel.clear_button.invoke()
        panel.clear_button.invoke()
        self.ui.config_controller.clear_task_data.assert_called_once_with()
        self.ui.config_controller.replace_config.assert_not_called()
        self.assertTrue(self.ui.config_busy)
        self.assertEqual(panel.message.get(), "正在清除…")
        self.assertEqual(str(panel.refresh_button.cget("state")), "disabled")
        self.ui.handle_config_event("finished", {"error": None, "current": "配置版本：原赛题",
                                                   "cleanup": {"target_files": 4, "student_data_dirs": 3}})
        self.assertFalse(self.ui.config_busy)
        self.assertIn("target.py 4 个", panel.message.get())
        self.assertEqual(str(panel.clear_button.cget("state")), "normal")
        self.assertEqual(panel.current.get(), "当前赛题：原赛题")
        dialog.cancel()

    def test_close_waits_for_question_transaction_without_stopping_backend(self):
        dialog = self.open_question_settings()
        self.ui.load_configs()
        self.ui.close(force=True)
        self.assertTrue(self.ui.closing)
        self.assertFalse(self.ui.destroyed)
        self.ui.config_controller.request_stop.assert_not_called()
        self.ui.handle_config_event("finished", {"error": None, "versions": [], "current": "配置版本：自定义／未识别"})
        self.assertTrue(self.ui.destroyed)

    def test_settings_tabs_and_buttons_fit_fixed_window_and_follow_theme(self):
        from launcher_style import palette
        self.root.deiconify()
        dialog = self.open_question_settings()
        self.root.update()
        bottom = dialog.window.winfo_rooty() + dialog.window.winfo_height()
        self.assertLessEqual(dialog.save_button.winfo_rooty() + dialog.save_button.winfo_height(), bottom)
        dialog.theme_buttons[1].invoke()
        self.assertEqual(dialog.config_panel.cget("background"), palette("light")["bg"])
        dialog.cancel()

    def test_both_settings_pages_keep_equal_size_and_visible_footers_at_different_dpi(self):
        from launcher_settings import SettingsDialog
        self.root.deiconify()
        original_scaling = self.root.tk.call("tk", "scaling")
        def inside(widget, window):
            self.assertTrue(widget.winfo_ismapped(), str(widget))
            self.assertGreater(widget.winfo_width(), 1)
            self.assertGreater(widget.winfo_height(), 1)
            self.assertGreaterEqual(widget.winfo_rootx(), window.winfo_rootx())
            self.assertGreaterEqual(widget.winfo_rooty(), window.winfo_rooty())
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 window.winfo_rootx() + window.winfo_width())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 window.winfo_rooty() + window.winfo_height())
        try:
            for scaling in (1.0, 1.5, 2.0):
                with self.subTest(scaling=scaling):
                    self.root.tk.call("tk", "scaling", scaling)
                    replace = Mock()
                    dialog = SettingsDialog(self.root, self.ui.results_dir, "dark", self.ui.family, Mock(), Mock(),
                                             on_config_refresh=Mock(), on_config_replace=replace)
                    try:
                        self.root.update()
                        window_size = (dialog.window.winfo_width(), dialog.window.winfo_height())
                        page_size = (dialog.body.winfo_width(), dialog.body.winfo_height())
                        inside(dialog.save_button, dialog.window)
                        inside(dialog.cancel_button, dialog.window)
                        self.assertGreaterEqual(dialog.actions.winfo_rooty(),
                                                dialog.submission_row.winfo_rooty() + dialog.submission_row.winfo_height())
                        panel = dialog.config_panel
                        panel.receive("list", {"error": None, "current": "配置版本：自定义／未识别",
                                                "versions": [{"version": "测试赛题", "valid": True, "issues": []}]})
                        for _ in range(2):
                            dialog.notebook.select(panel)
                            self.root.update()
                            self.assertEqual((panel.winfo_width(), panel.winfo_height()), page_size)
                            inside(panel.table, dialog.window)
                            inside(panel.refresh_button, dialog.window)
                            inside(panel.clear_button, dialog.window)
                            inside(panel.replace_button, dialog.window)
                            self.assertLessEqual(panel.refresh_button.winfo_rootx() + panel.refresh_button.winfo_width(),
                                                 panel.clear_button.winfo_rootx())
                            self.assertLessEqual(panel.clear_button.winfo_rootx() + panel.clear_button.winfo_width(),
                                                 panel.replace_button.winfo_rootx())
                            self.assertLessEqual(panel.table.winfo_rooty() + panel.table.winfo_height(), panel.note.winfo_rooty())
                            self.assertLessEqual(panel.note.winfo_rooty() + panel.note.winfo_height(), panel.actions.winfo_rooty())
                            self.assertEqual(panel.replace_button.cget("text"), "确认替换")
                            dialog.notebook.select(dialog.body)
                            self.root.update()
                            self.assertEqual((dialog.window.winfo_width(), dialog.window.winfo_height()), window_size)
                        dialog.notebook.select(panel)
                        panel.table.selection_set("0")
                        self.root.update()
                        panel.replace_button.invoke()
                        replace.assert_called_once_with("测试赛题")
                    finally:
                        dialog.cancel()
        finally:
            self.root.tk.call("tk", "scaling", original_scaling)

    def test_settings_tab_dimensions_do_not_change_when_selected_or_unselected(self):
        from tkinter import ttk
        self.root.deiconify()
        dialog = self.open_question_settings()
        dialog.config_panel.loaded = True
        def tab_widths():
            widths = [0, 0]
            for x in range(dialog.notebook.winfo_width()):
                try:
                    index = dialog.notebook.index("@{},10".format(x))
                except tk.TclError:
                    continue
                widths[index] += 1
            return widths
        for theme in ("dark", "light"):
            dialog.apply_theme(theme)
            style = ttk.Style(dialog.window)
            for option in ("padding", "expand", "font"):
                self.assertEqual(style.lookup("Settings.TNotebook.Tab", option, ("selected",)),
                                 style.lookup("Settings.TNotebook.Tab", option, ("!selected",)))
            dialog.notebook.select(dialog.body)
            self.root.update()
            baseline = tab_widths()
            self.assertTrue(all(width > 0 for width in baseline))
            for tab in (dialog.config_panel, dialog.body, dialog.config_panel):
                dialog.notebook.select(tab)
                self.root.update()
                self.assertEqual(tab_widths(), baseline)
        dialog.cancel()

    def test_results_button_defaults_to_system_file_manager_while_running(self):
        import time
        folder = Path(self.temp.name).resolve() / "成果"
        folder.mkdir()
        (folder / "result.txt").write_text("result")
        self.ui.results_dir = folder
        self.ui.start()
        self.ui.handle_event("started", None)
        with patch("aiot_launcher.open_results_directory") as open_folder:
            self.ui.results_button.invoke()
            deadline = time.monotonic() + 3
            while self.ui.opening_results and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.02)
        open_folder.assert_called_once_with(folder)
        self.assertIsNone(self.ui.results_panel)
        self.assertEqual(self.ui.start_button.cget("text"), "运行中")
        self.assertEqual(str(self.ui.results_button.cget("state")), "normal")

    def test_browser_selects_and_submits_files_without_stopping_aiot(self):
        import time
        folder, target = Path(self.temp.name).resolve() / "成果", Path(self.temp.name).resolve() / "提交"
        folder.mkdir()
        (folder / "result.txt").write_bytes(b"result")
        (folder / "子目录").mkdir()
        (folder / "子目录/结果.py").write_bytes(b"not executed")
        with patch("launcher_settings.request_settings_access", return_value=True):
            self.ui.open_settings()
        dialog = self.ui.settings_dialog
        self.assertFalse(dialog.submission_enabled.get())
        dialog.directory.set(str(folder))
        dialog.submission_toggle.invoke()
        dialog.submission_dir.set(str(target))
        dialog.save_button.invoke()
        self.assertTrue(self.ui.settings["submission_enabled"])
        self.ui.start()
        self.ui.handle_event("started", None)
        self.ui.view_results()
        panel = self.ui.results_panel
        deadline = time.monotonic() + 3
        while not panel.rows and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.02)
        panel.toggle("result.txt")
        panel.navigate("子目录")
        deadline = time.monotonic() + 3
        while "子目录/结果.py" not in panel.rows and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.02)
        panel.toggle("子目录/结果.py")
        self.assertEqual(panel.selected, {"result.txt", "子目录/结果.py"})
        self.root.update_idletasks()
        self.assertEqual(panel.submit_button.winfo_manager(), "pack")
        self.assertLessEqual(panel.footer.winfo_reqwidth(), 908 - 48)
        with patch("results_panel.messagebox.showerror") as show_error:
            panel.submit_button.invoke()
            self.assertTrue(panel.submitting)
            deadline = time.monotonic() + 5
            while panel.submitting and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.02)
        self.assertFalse(show_error.called, str(show_error.call_args))
        self.assertFalse(panel.submitting)
        self.assertEqual((target / "result.txt").read_bytes(), b"result")
        self.assertEqual((target / "子目录/结果.py").read_bytes(), b"not executed")
        self.assertEqual((folder / "result.txt").read_bytes(), b"result")
        self.assertEqual(self.ui.start_button.cget("text"), "运行中")
        self.assertFalse(self.controller.stop_event.is_set())
        self.ui.save_settings(str(folder), "dark", False, str(target))
        self.assertFalse(panel.visible)
        self.assertEqual(self.ui.canvas.itemcget(self.ui.results_panel_item, "state"), "hidden")
        with patch("aiot_launcher.open_results_directory") as open_folder:
            self.ui.view_results()
            deadline = time.monotonic() + 3
            while self.ui.opening_results and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.02)
        open_folder.assert_called_once_with(folder)

    def test_settings_cancel_or_denied_does_not_open_panel(self):
        for allowed in (False, None):
            with self.subTest(allowed=allowed), \
                    patch("launcher_settings.request_settings_access", return_value=allowed), \
                    patch("launcher_settings.SettingsDialog") as panel:
                self.ui.settings_button.invoke()
                panel.assert_not_called()
                self.assertIsNone(self.ui.settings_dialog)
                self.assertFalse(self.ui.settings_auth_active)
                self.assertEqual(str(self.ui.results_button.cget("state")), "normal")

    def test_settings_requires_password_again_after_panel_closes(self):
        with patch("launcher_settings.request_settings_access", side_effect=[True, False]) as request:
            self.ui.settings_button.invoke()
            self.ui.settings_dialog.cancel_button.invoke()
            self.ui.settings_button.invoke()
        self.assertEqual(request.call_count, 2)
        self.assertFalse(self.ui.settings_dialog.window.winfo_exists())

    def test_password_prompt_masks_input_rejects_wrong_and_accepts_root(self):
        from launcher_settings import SettingsPasswordDialog, request_settings_access
        observed = {}
        def dismiss():
            for child in self.root.winfo_children():
                if isinstance(child, SettingsPasswordDialog):
                    child.cancel()
        def submit():
            dialogs = [child for child in self.root.winfo_children() if isinstance(child, SettingsPasswordDialog)]
            if not dialogs:
                return
            dialog = dialogs[0]
            try:
                dialog.auth_parent = Mock(winfo_viewable=Mock(return_value=True),
                                          winfo_rootx=Mock(return_value=130), winfo_rooty=Mock(return_value=100),
                                          winfo_width=Mock(return_value=1100), winfo_height=Mock(return_value=620))
                dialog.center()
                dialog.update_idletasks()
                observed["center_x"] = dialog.winfo_rootx() + dialog.winfo_width() / 2
                observed["center_y"] = dialog.winfo_rooty() + dialog.winfo_height() / 2
                observed["mask"] = dialog.entry.cget("show")
                dialog.entry.insert(0, "ROOT")
                dialog.ok()
                observed["wrong_stays_open"] = bool(dialog.winfo_exists())
                if dialog.winfo_exists():
                    observed["error"] = dialog.error.get()
                    observed["cleared"] = dialog.entry.get()
                    dialog.entry.insert(0, "root")
                    dialog.ok()
            except Exception as exc:
                observed["exception"] = str(exc)
                dismiss()
        safety = self.root.after(3000, dismiss)
        self.root.after(50, submit)
        allowed = request_settings_access(self.root, self.ui.theme, self.ui.family)
        self.root.after_cancel(safety)
        self.assertNotIn("exception", observed)
        self.assertTrue(allowed)
        self.assertEqual(observed["mask"], "*")
        self.assertTrue(observed["wrong_stays_open"])
        self.assertTrue(observed["error"])
        self.assertEqual(observed["cleared"], "")
        self.assertAlmostEqual(observed["center_x"], 130 + 550, delta=30)
        self.assertAlmostEqual(observed["center_y"], 100 + 310, delta=30)

    def test_background_fills_right_pane_without_extra_titles(self):
        self.ui.destroy()
        self.root = tk.Tk()
        self.root.withdraw()
        fixture = tk.PhotoImage(master=self.root, width=1362, height=930)
        fixture.put("#303030", to=(0, 0, 1362, 930))
        for color, box in (("#ff0000", (0, 0, 96, 96)), ("#00ff00", (1266, 0, 1362, 96)),
                           ("#0000ff", (0, 834, 96, 930)), ("#ffffff", (1266, 834, 1362, 930))):
            fixture.put(color, to=box)
        fixture.write(str(self.background), format="png")
        # Reproduce the older ImageTk reverse-conversion hook failing on Linux.
        # The GUI must read the PNG directly and keep high-quality rendering.
        with patch("PIL.ImageTk.getimage", side_effect=tk.TclError('invalid command name "PyImagingPhotoGet"')):
            self.ui = LauncherWindow(self.root, FakeController(), self.background)
            self.ui.canvas.render(1100, 620)
            self.ui.apply_theme("light")
            self.ui.apply_theme("dark")
        image = self.ui.canvas.cover
        self.assertEqual((image.width(), image.height()), (908, 620))
        item = self.ui.canvas.find_withtag("content-background")[0]
        self.assertEqual(self.ui.canvas.coords(item), [192.0, 0.0])
        self.assertEqual(self.ui.canvas._source_pixels.size, (1362, 930))
        pixel = tuple(self.root.tk.call(str(image), "get", 400, 250))
        self.assertTrue(16 < pixel[0] < 48)
        from PIL import ImageTk
        colors = {color for _, color in ImageTk.getimage(image).convert("RGB").getcolors(908 * 620)}
        for channel in range(3):
            self.assertTrue(any(color[channel] > 70 and all(color[channel] > 2 * color[other]
                                for other in range(3) if other != channel) for color in colors))
        self.assertTrue(any(min(color) > 80 for color in colors))
        labels = [self.ui.canvas.itemcget(item, "text") for item in self.ui.canvas.find_all()
                  if self.ui.canvas.type(item) == "text"]
        for item in self.ui.canvas.find_all():
            if self.ui.canvas.type(item) == "rectangle":
                self.assertEqual(self.ui.canvas.itemcget(item, "stipple"), "")
        self.assertIn("物联传感技术应用", labels)
        self.assertNotIn("金砖赛事版本", labels)
        self.assertNotIn("就绪", labels)
        self.assertEqual(self.root.title(), "2026金砖赛事-物联传感技术应用")

    def test_broken_pillow_tk_bridge_reports_error_instead_of_pixelating(self):
        from launcher_style import image_photo
        from PIL import Image
        from core import SyncError
        with patch("PIL.ImageTk.PhotoImage", side_effect=tk.TclError("bridge unavailable")), \
                self.assertRaisesRegex(SyncError, "高清图片组件不可用"):
            image_photo(Image.new("RGBA", (4, 4)), self.root)


if __name__ == "__main__":
    unittest.main()
