"""Latest-frame capture and matched output jobs, adapted from hat20.py.

NPU inference stays in the caller. Each worker exclusively owns its resource
cleanup, including when a native read or publish callback outlives close().
"""

import logging
import re
import time
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread


LOG = logging.getLogger(__name__)


def _valid_frame(frame):
    shape = getattr(frame, "shape", ())
    return (frame is not None and getattr(frame, "size", 0) > 0 and
            len(shape) >= 2 and shape[0] > 0 and shape[1] > 0)


def open_camera(source, width, height):
    """Open only the requested local device and return a verified first frame.

    Each resolution gets a fresh V4L2 connection and an MJPG request. A device
    that substitutes another resolution is retried through the fallback list;
    the final default modes accept the actual dimensions without resizing.
    Ownership of the successful capture transfers to the caller.
    """
    if isinstance(source, str) and source.isdecimal():
        source = int(source)
    if not ((type(source) is int and source >= 0) or
            (isinstance(source, str) and re.fullmatch(r"/dev/video\d+", source))):
        raise ValueError("摄像头必须是非负编号或 /dev/videoN；此函数不打开视频文件或网络流。")
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ValueError("摄像头请求宽高必须为正整数。")
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("摄像头采集需要 OpenCV。") from exc
    modes = list(dict.fromkeys([(width, height), (1280, 720), (640, 480), (None, None)]))
    attempts = [(cv2.CAP_V4L2, size) for size in modes]
    attempts.append((cv2.CAP_ANY, (None, None)))
    failures = []
    for backend, (requested_w, requested_h) in attempts:
        capture, accepted = None, False
        mode = "default" if requested_w is None else "{}x{} MJPG".format(requested_w, requested_h)
        try:
            LOG.info("尝试摄像头 %s：backend=%s mode=%s", source, backend, mode)
            capture = cv2.VideoCapture(source, backend)
            if not capture.isOpened():
                failures.append("backend={} {}: 无法打开".format(backend, mode))
                continue
            if requested_w is not None:
                capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, requested_w)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, requested_h)
            # A bounded number of reads allows a device to discard startup noise.
            for _ in range(3):
                ok, frame = capture.read()
                if not ok or not _valid_frame(frame):
                    continue
                actual_h, actual_w = frame.shape[:2]
                if requested_w is not None and (actual_w, actual_h) != (requested_w, requested_h):
                    failures.append("backend={} {}: 实际{}x{}".format(backend, mode, actual_w, actual_h))
                    LOG.warning("请求 %sx%s，实际 %sx%s；尝试下一采集模式", requested_w, requested_h, actual_w, actual_h)
                    break
                LOG.info("摄像头已就绪：设备=%s 实际=%sx%s backend=%s", source, actual_w, actual_h, backend)
                if (actual_w, actual_h) != (width, height):
                    LOG.warning("采集使用回退尺寸 %sx%s，没有软件放大为请求尺寸", actual_w, actual_h)
                accepted = True
                return capture, frame
            else:
                failures.append("backend={} {}: 没有有效首帧".format(backend, mode))
        except Exception as exc:
            failures.append("backend={} {}: {}".format(backend, mode, exc))
            LOG.warning("摄像头模式失败，尝试下一模式：%s", exc)
        finally:
            if capture is not None and not accepted:
                try:
                    capture.release()
                except Exception:
                    LOG.exception("释放失败的摄像头连接时出错")
    raise RuntimeError("摄像头 {} 的所有采集模式失败；没有改用其它设备。{}".format(source, "; ".join(failures)))


def _replace_latest(queue, value):
    """Single producer; the consumer may empty the queue between attempts."""
    discarded = 0
    while True:
        try:
            queue.put_nowait(value)
            return discarded
        except Full:
            try:
                queue.get_nowait()
                discarded += 1
            except Empty:
                pass


def _discard_pending(queue):
    discarded = 0
    while True:
        try:
            queue.get_nowait()
            discarded += 1
        except Empty:
            return discarded


class LatestFrames:
    """One unread frame at most; only the reader thread releases capture."""

    def __init__(self, capture, first_frame=None):
        self.capture = capture
        self.done = Event()
        self.error = None
        self.dropped = 0
        self._first_frame = first_frame
        self._queue = Queue(maxsize=1)
        self._stop = Event()
        self._lock = Lock()
        self._thread = None

    def start(self):
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("采集器已经关闭。")
            if self._thread is None:
                self._thread = Thread(target=self._run, name="fire-latest-capture", daemon=True)
                self._thread.start()
        return self

    def _run(self):
        frame, self._first_frame = self._first_frame, None
        try:
            while not self._stop.is_set():
                if frame is None:
                    ok, frame = self.capture.read()
                    if not ok or not _valid_frame(frame):
                        if not self._stop.is_set():
                            raise RuntimeError("摄像头读取失败，没有有效视频帧。")
                        break
                elif not _valid_frame(frame):
                    raise RuntimeError("摄像头首帧无效。")
                captured = time.monotonic()
                with self._lock:
                    if self._stop.is_set():
                        break
                    self.dropped += _replace_latest(self._queue, (captured, frame))
                frame = None
        except Exception as exc:
            self.error = exc
        finally:
            try:
                self.capture.release()
            except Exception as exc:
                if self.error is None:
                    self.error = exc
                LOG.exception("采集线程释放摄像头失败")
            finally:
                self.done.set()

    def get(self, timeout=0.1):
        return self._queue.get(timeout=timeout)

    def close(self):
        self._stop.set()
        with self._lock:
            if self._thread is None:
                # Even an unused capture is released by the same owner routine.
                self._thread = Thread(target=self._run, name="fire-latest-capture", daemon=True)
                self._thread.start()
            thread = self._thread
        if thread is not current_thread():
            thread.join(timeout=1.0)
        if thread.is_alive():
            LOG.warning("摄像头读取尚未返回；保留采集线程所有权，返回后由其释放设备")
        return not thread.is_alive()


class LatestOutput:
    """One pending whole job; a running callback is never interrupted.

    Jobs must already contain their matching image, detections, and status.
    The worker does no NPU work. on_close runs exactly once in its finally.
    """

    def __init__(self, publish, on_close=None):
        if not callable(publish) or (on_close is not None and not callable(on_close)):
            raise ValueError("publish/on_close 必须是可调用对象。")
        self.done = Event()
        self.error = None
        self.dropped = 0
        self._publish = publish
        self._on_close = on_close
        self._queue = Queue(maxsize=1)
        self._stop = Event()
        self._lock = Lock()
        self._discard = False
        self._thread = None

    def start(self):
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("输出器已经关闭。")
            if self._thread is None:
                self._thread = Thread(target=self._run, name="fire-latest-output", daemon=True)
                self._thread.start()
        return self

    def submit(self, job):
        with self._lock:
            if self.error is not None:
                raise RuntimeError("输出线程失败：{}".format(self.error)) from self.error
            if self._stop.is_set():
                raise RuntimeError("输出器已经关闭，无法提交画面。")
            if self._thread is None:
                raise RuntimeError("请先启动输出器。")
            self.dropped += _replace_latest(self._queue, job)

    def _run(self):
        try:
            while True:
                with self._lock:
                    if self._stop.is_set() and (self._discard or self._queue.empty()):
                        break
                try:
                    job = self._queue.get(timeout=0.1)
                except Empty:
                    continue
                with self._lock:
                    if self._stop.is_set() and self._discard:
                        self.dropped += 1
                        continue
                    # Claim under the same lock as close/submit; once claimed,
                    # this job may finish while close discards only pending jobs.
                self._publish(job)
        except Exception as exc:
            with self._lock:
                self.error = exc
                self._stop.set()
                self.dropped += _discard_pending(self._queue)
        finally:
            try:
                if self._on_close is not None:
                    self._on_close()
            except Exception as exc:
                with self._lock:
                    if self.error is None:
                        self.error = exc
                LOG.exception("输出线程清理资源失败")
            finally:
                self.done.set()

    def close(self, discard=False):
        with self._lock:
            self._stop.set()
            self._discard = self._discard or bool(discard)
            if self._discard:
                self.dropped += _discard_pending(self._queue)
            if self._thread is None:
                self._thread = Thread(target=self._run, name="fire-latest-output", daemon=True)
                self._thread.start()
            thread = self._thread
        if thread is not current_thread():
            thread.join(timeout=1.5)
        if thread.is_alive():
            LOG.warning("输出回调尚未完成；完成后由输出线程关闭其资源")
        return not thread.is_alive()
