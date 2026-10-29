"""Fire-only association. Motion estimates help matching, never create boxes."""

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True)
class DisplayBox:
    box: Tuple[int, int, int, int]
    confidence: float
    class_id: int
    track_id: int
    state: str  # detected / low; both are current model observations.


@dataclass(frozen=True)
class TrackingResult:
    display: tuple
    observed: tuple  # Only current high-confidence model detections.


@dataclass
class _Track:
    track_id: int
    raw: np.ndarray
    filtered: np.ndarray
    velocity: np.ndarray
    seen: float
    hits: int = 1


class FireTracker:
    def __init__(self, fire_class, high_conf=0.5, low_conf=0.25, hold=0.3,
                 alpha=0.4, match_iou=0.25, max_tracks=100):
        if not 0 <= low_conf <= high_conf <= 1:
            raise ValueError('跟踪阈值须满足 0 <= track-conf <= conf <= 1。')
        if not math.isfinite(hold) or hold <= 0:
            raise ValueError('跟踪匹配历史间隔必须为有限正数。')
        if not 0 < alpha <= 1 or not 0 < match_iou <= 1:
            raise ValueError('平滑系数与匹配IoU必须在 (0,1]。')
        if type(max_tracks) is not int or max_tracks <= 0:
            raise ValueError('跟踪上限必须为正整数。')
        self.fire_class, self.high_conf, self.low_conf = fire_class, high_conf, low_conf
        self.hold, self.alpha, self.match_iou, self.max_tracks = hold, alpha, match_iou, max_tracks
        self._tracks, self._next_id = {}, 1
        self._time = self._size = None

    def reset(self):
        self._tracks.clear()
        self._time = self._size = None

    @staticmethod
    def _center(box):
        return (box[:2] + box[2:]) / 2

    def _predict(self, track, now):
        shift = track.velocity * (now - track.seen) if track.hits >= 2 else np.zeros(2)
        return track.raw + np.tile(shift, 2)

    @staticmethod
    def _in_frame(box, size):
        center = FireTracker._center(box)
        return 0 <= center[0] < size[1] and 0 <= center[1] < size[0]

    def _associate(self, track_ids, indices, candidates, predicted):
        pairs = []
        for tid in track_ids:
            old = predicted[tid]
            size = old[2:] - old[:2]
            diagonal = max(1.0, float(np.linalg.norm(size)))
            for index in indices:
                box = np.asarray(candidates[index].box, dtype=float)
                ratio = (box[2:] - box[:2]) / size
                if np.any(ratio < 0.5) or np.any(ratio > 2):
                    continue
                distance = float(np.linalg.norm(self._center(box) - self._center(old))) / diagonal
                intersection = float(np.prod(np.maximum(0, np.minimum(box[2:], old[2:]) - np.maximum(box[:2], old[:2]))))
                union = float(np.prod(size) + np.prod(box[2:] - box[:2]) - intersection)
                overlap = intersection / union if union > 0 else 0
                if overlap >= self.match_iou or distance <= 0.75:
                    priority = (0, -overlap, distance) if overlap >= self.match_iou else (1, distance, -overlap)
                    pairs.append((priority, tid, index))
        assigned, used_tracks, used_boxes = [], set(), set()
        for _, tid, index in sorted(pairs):
            if tid not in used_tracks and index not in used_boxes:
                assigned.append((tid, index))
                used_tracks.add(tid)
                used_boxes.add(index)
        return assigned

    def _observe(self, track, item, now):
        box = np.asarray(item.box, dtype=float)
        dt = now - track.seen
        measured_velocity = (self._center(box) - self._center(track.raw)) / dt
        track.velocity = 0.5 * track.velocity + 0.5 * measured_velocity
        size = max(1.0, float(np.max(track.raw[2:] - track.raw[:2])))
        movement = float(np.max(np.abs(self._center(box) - self._center(track.raw))))
        growth = float(np.max(np.abs((box[2:] - box[:2]) - (track.raw[2:] - track.raw[:2]))))
        base = max(self.alpha, 0.8) if movement > size * 0.15 or growth > size * 0.25 else self.alpha
        weight = 1 - (1 - base) ** (dt * 30)
        track.filtered += weight * (box - track.filtered)
        track.raw, track.seen, track.hits = box, now, track.hits + 1

    def _display(self, track, box, size, confidence, state):
        box = np.asarray(box).copy()
        box[[0, 2]] = box[[0, 2]].clip(0, size[1] - 1)
        box[[1, 3]] = box[[1, 3]].clip(0, size[0] - 1)
        box = tuple(int(round(value)) for value in box)
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        return DisplayBox(box, confidence, self.fire_class, track.track_id, state)

    def update(self, detections, now, frame_size):
        size = tuple(frame_size)
        if not math.isfinite(now) or len(size) != 2 or min(size) <= 0:
            raise ValueError('跟踪时间和画面尺寸无效。')
        if self._size != size or (self._time is not None and now <= self._time):
            self.reset()
        self._time, self._size = now, size
        candidates = [d for d in detections if d.class_id == self.fire_class and
                      math.isfinite(d.confidence) and d.confidence >= self.low_conf and
                      np.isfinite(d.box).all() and d.box[2] > d.box[0] and d.box[3] > d.box[1] and
                      self._in_frame(np.asarray(d.box, dtype=float), size)]
        high = [i for i, d in enumerate(candidates) if d.confidence >= self.high_conf]
        low = [i for i, d in enumerate(candidates) if d.confidence < self.high_conf]
        observed = tuple(candidates[i] for i in high)
        predicted = {}
        for tid, track in list(self._tracks.items()):
            box = self._predict(track, now)
            if now - track.seen > self.hold or not self._in_frame(box, size):
                del self._tracks[tid]
            else:
                predicted[tid] = box
        matched = self._associate(list(predicted), high, candidates, predicted)
        used_tracks = {tid for tid, _ in matched}
        matched += self._associate([tid for tid in predicted if tid not in used_tracks], low, candidates, predicted)
        used_tracks = {tid for tid, _ in matched}
        used_boxes = {index for _, index in matched}
        display = []
        for tid, index in matched:
            track, item = self._tracks[tid], candidates[index]
            self._observe(track, item, now)
            display.append(self._display(track, track.filtered, size, item.confidence,
                                         'detected' if item.confidence >= self.high_conf else 'low'))
        for index in high:
            if index in used_boxes:
                continue
            if len(self._tracks) >= self.max_tracks:
                stale = [tid for tid in self._tracks if tid not in used_tracks]
                if not stale:
                    continue
                del self._tracks[min(stale, key=lambda tid: self._tracks[tid].seen)]
            box = np.asarray(candidates[index].box, dtype=float)
            tid = self._next_id
            self._next_id += 1
            track = _Track(tid, box, box.copy(), np.zeros(2), now)
            self._tracks[tid] = track
            used_tracks.add(tid)
            display.append(self._display(track, box, size, candidates[index].confidence, 'detected'))
        # Unmatched tracks may remain briefly for reassociation, but never
        # contribute a displayed box. No current observation means no box.
        return TrackingResult(tuple(d for d in display if d is not None), observed)
