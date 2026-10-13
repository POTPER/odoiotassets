import struct
import unittest

import numpy as np

from plate_core import (
    LatestQueue,
    PlateResult,
    ResultStabilizer,
    UdpPacketizer,
    decode_ctc,
    expanded_crop_bounds,
)


def ctc_tensor(indices, class_count):
    tensor = np.zeros((1, class_count, len(indices)), dtype=np.float32)
    for timestep, index in enumerate(indices):
        tensor[0, index, timestep] = 1.0
    return tensor


class DecodeTests(unittest.TestCase):
    CHARS = ("A", "B", "-")

    def test_keeps_first_character(self):
        result = decode_ctc(ctc_tensor([0, 2], 3), self.CHARS)[0]
        self.assertEqual(result.text, "A")
        self.assertEqual(result.indices, (0,))

    def test_collapses_consecutive_duplicates(self):
        result = decode_ctc(ctc_tensor([0, 0, 2], 3), self.CHARS)[0]
        self.assertEqual(result.text, "A")

    def test_blank_allows_repeated_character(self):
        result = decode_ctc(ctc_tensor([0, 2, 0], 3), self.CHARS)[0]
        self.assertEqual(result.text, "AA")

    def test_all_blank_returns_empty_result(self):
        result = decode_ctc(ctc_tensor([2, 2, 2], 3), self.CHARS)[0]
        self.assertEqual(result.text, "")
        self.assertEqual(result.confidence, 0.0)

    def test_empty_timesteps_are_supported(self):
        result = decode_ctc(np.empty((1, 3, 0)), self.CHARS)[0]
        self.assertEqual(result.text, "")

    def test_rejects_mismatched_class_count(self):
        with self.assertRaises(ValueError):
            decode_ctc(np.empty((1, 4, 1)), self.CHARS)


class CropTests(unittest.TestCase):
    def test_expands_and_clips_xyxy_box(self):
        bounds = expanded_crop_bounds((5, 5, 25, 15), (20, 30, 3))
        self.assertEqual(bounds, (4, 4, 26, 16))

    def test_clips_to_image_edges(self):
        bounds = expanded_crop_bounds((0, 0, 20, 10), (10, 20, 3))
        self.assertEqual(bounds, (0, 0, 20, 10))

    def test_rejects_zero_area_and_tiny_boxes(self):
        self.assertIsNone(expanded_crop_bounds((10, 10, 10, 20), (30, 30, 3)))
        self.assertIsNone(expanded_crop_bounds((1, 1, 5, 3), (30, 30, 3)))


class QueueTests(unittest.TestCase):
    def test_full_queue_drops_oldest_and_keeps_latest(self):
        queue = LatestQueue(maxsize=2)
        queue.put_latest("old")
        queue.put_latest("middle")
        queue.put_latest("latest")
        self.assertEqual(queue.dropped, 1)
        self.assertEqual(queue.queue.get_nowait(), "middle")
        self.assertEqual(queue.queue.get_nowait(), "latest")


class StabilizerTests(unittest.TestCase):
    @staticmethod
    def result(text):
        return PlateResult((1, 2, 30, 12), 0, 0.9, text, 0.8)

    def test_requires_multiple_votes_and_retains_short_miss(self):
        stabilizer = ResultStabilizer(window_size=3, min_votes=2, max_missed=1)
        self.assertEqual(stabilizer.update([self.result("京A12345")]), ())
        stable = stabilizer.update([self.result("京A12345")])
        self.assertEqual(stable[0].text, "京A12345")
        self.assertEqual(stabilizer.update(()), stable)
        self.assertEqual(stabilizer.update(()), ())

    def test_duplicate_detections_in_one_frame_are_one_vote(self):
        stabilizer = ResultStabilizer(window_size=3, min_votes=2, max_missed=1)
        duplicate = self.result("京A12345")
        self.assertEqual(stabilizer.update([duplicate, duplicate]), ())


class PacketTests(unittest.TestCase):
    def test_multi_packet_header_and_payload(self):
        packetizer = UdpPacketizer(max_packet_size=3)
        encoded = [packet.toNetBytes() for packet in packetizer.packetize(b"abcdefg")]
        self.assertEqual(len(encoded), 3)
        first_header = struct.unpack("<IIII", encoded[0][:16])
        self.assertEqual(first_header, (1, 3, 0, 3))
        self.assertEqual(encoded[0][16:], b"abc")
        self.assertEqual(encoded[2][16:], b"g")

    def test_message_packetizer_has_independent_ids(self):
        image = UdpPacketizer(60000)
        message = UdpPacketizer(5)
        self.assertEqual(image.packetize(b"x")[0].groupId, 1)
        self.assertEqual(message.packetize(b"x")[0].groupId, 1)

    def test_uint32_group_id_wraps(self):
        packetizer = UdpPacketizer(5, initial_group_id=0xFFFFFFFF)
        self.assertEqual(packetizer.packetize(b"x")[0].groupId, 0)

    def test_empty_payload_creates_no_packets(self):
        self.assertEqual(UdpPacketizer(5).packetize(b""), [])


if __name__ == "__main__":
    unittest.main()
