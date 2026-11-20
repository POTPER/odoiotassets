"""Read-only status worker; owns no Tk objects or process-control callbacks."""
from pathlib import Path
import queue
import threading
import time

from running_aiot import find_running_aiot


class ProcessStatusMonitor:
    def __init__(self, publish, interval=1.0):
        self.publish = Path(publish)
        self.interval = interval
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            sample = {'sample_started': time.monotonic(), 'pids': [], 'error': None}
            try:
                sample['pids'] = find_running_aiot(self.publish)
            except Exception as exc:
                sample['error'] = str(exc)
            self.events.put(sample)
            if self.stop.wait(self.interval):
                return

    def close(self):
        self.stop.set()

    def wait(self):
        if self.thread is not None:
            self.thread.join()
