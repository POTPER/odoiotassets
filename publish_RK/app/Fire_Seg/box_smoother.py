"""Same-class IoU association and adaptive EMA, based on hat4.BoxSmoother.

Only coordinates are filtered. Missing detections never create historical
boxes, and current confidence, class IDs and detection count are preserved.
"""

import math

import numpy as np

from detector import Detection


class BoxSmoother:
    REFERENCE_FPS = 30.0

    def __init__(self, alpha=0.4, match_iou=0.25, max_gap=0.3):
        if not math.isfinite(alpha) or not 0 < alpha <= 1:
            raise ValueError('smooth alpha 必须在 (0,1]。')
        if not math.isfinite(match_iou) or not 0 < match_iou <= 1:
            raise ValueError('smooth IoU 必须在 (0,1]。')
        if not math.isfinite(max_gap) or max_gap <= 0:
            raise ValueError('smooth max gap 必须为有限正数。')
        self.alpha, self.match_iou, self.max_gap = alpha, match_iou, max_gap
        self.reset()

    def reset(self):
        self._boxes = np.empty((0, 4), dtype=np.float64)
        self._classes = np.empty(0, dtype=np.int64)
        self._updated = None
        self._frame_size = None

    def update(self, detections, now, frame_size):
        if not math.isfinite(now):
            raise ValueError('平滑时间必须是有限数。')
        frame_size = tuple(frame_size)
        if len(frame_size) != 2 or min(frame_size) <= 0:
            raise ValueError('平滑画面尺寸必须为正整数 (height,width)。')
        if (self._frame_size != frame_size or self._updated is None or
                now <= self._updated or now - self._updated > self.max_gap):
            self.reset()
        elapsed = (now - self._updated) if self._updated is not None else 1 / self.REFERENCE_FPS
        current = np.asarray([item.box for item in detections], dtype=np.float64).reshape(-1, 4)
        classes = np.asarray([item.class_id for item in detections], dtype=np.int64)
        filtered = current.copy()
        if len(current) and len(self._boxes):
            # Vectorized pairwise IoU keeps matching inexpensive on ARM CPUs.
            upper = np.maximum(current[:, None, :2], self._boxes[None, :, :2])
            lower = np.minimum(current[:, None, 2:], self._boxes[None, :, 2:])
            extent = np.maximum(lower - upper, 0)
            intersection = extent[:, :, 0] * extent[:, :, 1]
            current_size = current[:, 2:] - current[:, :2]
            previous_size = self._boxes[:, 2:] - self._boxes[:, :2]
            union = (np.prod(current_size, axis=1)[:, None] +
                     np.prod(previous_size, axis=1)[None, :] - intersection)
            overlaps = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
            valid = (overlaps >= self.match_iou) & (classes[:, None] == self._classes[None, :])
            matches = [(float(overlaps[i, j]), int(i), int(j)) for i, j in np.argwhere(valid)]
            used, previous_used = set(), set()
            for _, index, old_index in sorted(matches, key=lambda match: (-match[0], match[1], match[2])):
                if index in used or old_index in previous_used:
                    continue
                used.add(index)
                previous_used.add(old_index)
                old = self._boxes[old_index]
                movement = np.max(np.abs((current[index, :2] + current[index, 2:] - old[:2] - old[2:]) / 2))
                size_change = np.max(np.abs(current_size[index] - previous_size[old_index]))
                size = max(1.0, float(np.max(previous_size[old_index])))
                # Follow motion or growing fire quickly, rather than dragging
                # a heavily smoothed rectangle behind the actual detection.
                fast = movement > size * 0.15 or size_change > size * 0.25
                base = max(self.alpha, 0.8) if fast else self.alpha
                weight = 1 - (1 - base) ** (elapsed * self.REFERENCE_FPS)
                filtered[index] = old + weight * (current[index] - old)
        # Preserve subpixel history; rounding every EMA update causes sticking.
        self._boxes, self._classes = filtered, classes
        self._updated, self._frame_size = now, frame_size
        return [Detection(tuple(int(round(value)) for value in box), item.confidence, item.class_id)
                for box, item in zip(filtered, detections)]
