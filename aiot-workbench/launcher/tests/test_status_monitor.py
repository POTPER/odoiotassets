from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from status_monitor import ProcessStatusMonitor


class StatusMonitorTests(unittest.TestCase):
    def test_idle_external_start_and_exit_are_sampled_without_restarting_launcher(self):
        monitor = ProcessStatusMonitor('/test/publish', interval=0.01)
        with patch('status_monitor.find_running_aiot', side_effect=[[], [123], [], RuntimeError('scan failed')]):
            monitor.start()
            samples = [monitor.events.get(timeout=2) for _ in range(4)]
            monitor.close()
            monitor.wait()
        self.assertEqual([sample['pids'] for sample in samples[:3]], [[], [123], []])
        self.assertEqual(samples[-1]['error'], 'scan failed')
        self.assertTrue(all(isinstance(sample['sample_started'], float) for sample in samples))
        self.assertFalse(monitor.thread.is_alive())

    def test_close_interrupts_wait_and_start_is_idempotent(self):
        monitor = ProcessStatusMonitor('/test/publish', interval=60)
        with patch('status_monitor.find_running_aiot', return_value=[]):
            monitor.start()
            first = monitor.thread
            monitor.start()
            monitor.events.get(timeout=2)
            monitor.close()
            monitor.wait()
        self.assertIs(monitor.thread, first)
        self.assertFalse(first.is_alive())
        with self.assertRaises(queue.Empty):
            monitor.events.get_nowait()
