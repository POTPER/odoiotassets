"""Pure-Python helpers for the plate recognition pipeline."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Lock
from typing import Iterable, Sequence

import numpy as np

from UdpPackage import UdpPackage

global_id = 0

CHARS = (
    "京", "沪", "津", "渝", "冀", "晋", "蒙", "辽", "吉", "黑",
    "苏", "浙", "皖", "闽", "赣", "鲁", "豫", "鄂", "湘", "粤",
    "桂", "琼", "川", "贵", "云", "藏", "陕", "甘", "青", "宁",
    "新",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "A", "B", "C", "D", "E", "F", "G", "H", "J", "K",
    "L", "M", "N", "P", "Q", "R", "S", "T", "U", "V",
    "W", "X", "Y", "Z", "I", "O", "-",
)


@dataclass(frozen=True)
class RecognitionResult:
    text: str
    confidence: float
    indices: tuple[int, ...]


@dataclass(frozen=True)
class PlateResult:
    box_xyxy: tuple[int, int, int, int]
    class_id: int
    detection_score: float
    text: str
    recognition_confidence: float


def decode_ctc(prediction: np.ndarray, chars: Sequence[str] = CHARS) -> list[RecognitionResult]:
    """Greedy CTC decode for a [batch, classes, timesteps] tensor."""
    values = np.asarray(prediction)
    if values.ndim != 3:
        raise ValueError(f"CTC output must have 3 dimensions, got {values.shape}")
    if values.shape[1] != len(chars):
        raise ValueError(
            f"CTC class count {values.shape[1]} does not match character count {len(chars)}"
        )

    blank = len(chars) - 1
    results: list[RecognitionResult] = []
    for sample in values:
        indices = np.argmax(sample, axis=0)
        if np.all((sample >= 0.0) & (sample <= 1.0)):
            probabilities = sample
        else:
            shifted = sample - np.max(sample, axis=0, keepdims=True)
            exp_values = np.exp(shifted)
            probabilities = exp_values / np.sum(exp_values, axis=0, keepdims=True)

        decoded: list[int] = []
        confidences: list[float] = []
        previous = blank
        for timestep, current_value in enumerate(indices):
            current = int(current_value)
            if current != blank and current != previous:
                if current < 0 or current >= len(chars):
                    raise ValueError(f"Invalid character index: {current}")
                decoded.append(current)
                confidences.append(float(probabilities[current, timestep]))
            previous = current

        text = "".join(chars[index] for index in decoded)
        confidence = float(np.mean(confidences)) if confidences else 0.0
        results.append(RecognitionResult(text, confidence, tuple(decoded)))
    return results


def expanded_crop_bounds(
    box_xyxy: Iterable[float],
    image_shape: Sequence[int],
    padding_x: float = 0.05,
    padding_y: float = 0.10,
    min_width: int = 8,
    min_height: int = 4,
) -> tuple[int, int, int, int] | None:
    """Expand and clip an xyxy box, returning None for invalid/tiny crops."""
    x1, y1, x2, y2 = (float(value) for value in box_xyxy)
    height, width = int(image_shape[0]), int(image_shape[1])
    box_width, box_height = x2 - x1, y2 - y1
    if box_width < min_width or box_height < min_height:
        return None

    dx, dy = box_width * padding_x, box_height * padding_y
    left = max(0, int(np.floor(x1 - dx)))
    top = max(0, int(np.floor(y1 - dy)))
    right = min(width, int(np.ceil(x2 + dx)))
    bottom = min(height, int(np.ceil(y2 + dy)))
    if right - left < min_width or bottom - top < min_height:
        return None
    return left, top, right, bottom


class LatestQueue:
    """Bounded queue which drops the oldest item instead of the newest."""

    def __init__(self, maxsize: int = 3):
        self.queue: Queue = Queue(maxsize=maxsize)
        self.dropped = 0
        self._lock = Lock()

    def put_latest(self, item) -> None:
        try:
            self.queue.put_nowait(item)
            return
        except Full:
            pass

        try:
            self.queue.get_nowait()
            self.queue.task_done()
        except Empty:
            pass
        with self._lock:
            self.dropped += 1
        self.queue.put_nowait(item)


class ResultStabilizer:
    """Short-window text voting with limited missed-frame retention."""

    def __init__(self, window_size: int = 3, min_votes: int = 2, max_missed: int = 2):
        self._history: deque[tuple[PlateResult, ...]] = deque(maxlen=window_size)
        self._min_votes = min_votes
        self._max_missed = max_missed
        self._missed = 0
        self._last_stable: tuple[PlateResult, ...] = ()

    def update(self, results: Sequence[PlateResult]) -> tuple[PlateResult, ...]:
        current = tuple(result for result in results if result.text)
        if not current:
            self._missed += 1
            if self._missed <= self._max_missed:
                return self._last_stable
            self._history.clear()
            self._last_stable = ()
            return ()

        self._missed = 0
        self._history.append(current)
        # Count a text at most once per frame so duplicate detections cannot
        # satisfy the multi-frame vote threshold by themselves.
        counts = Counter(
            text
            for frame in self._history
            for text in {result.text for result in frame}
        )
        accepted = {text for text, count in counts.items() if count >= self._min_votes}
        stable = tuple(result for result in current if result.text in accepted)
        if stable:
            self._last_stable = stable
        return self._last_stable


class UdpPacketizer:
    """Creates binary-compatible UDP packets with an independent uint32 id."""

    def __init__(self, max_packet_size: int, initial_group_id: int = 0):
        if max_packet_size <= 0:
            raise ValueError("max_packet_size must be positive")
        self.max_packet_size = max_packet_size
        self.group_id = initial_group_id & 0xFFFFFFFF
        self._lock = Lock()

    def packetize(self, data: bytes) -> list[UdpPackage]:
        global global_id
        if not data:
            return []
        with self._lock:
            self.group_id = global_id#(self.group_id + 1) & 0xFFFFFFFF
            global_id = global_id+1
            group_id = self.group_id
        count = (len(data) + self.max_packet_size - 1) // self.max_packet_size
        packets = []
        for index in range(count):
            start = index * self.max_packet_size
            chunk = data[start:start + self.max_packet_size]
            packets.append(UdpPackage(group_id, count, index, len(chunk), chunk))
        return packets
