import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from UdpPackage import UdpPackage, buildUdpPackages


class UdpPackageTest(unittest.TestCase):
    def test_to_net_bytes_uses_little_endian_header(self):
        packet = UdpPackage(1, 2, 3, 4, b"data")

        self.assertEqual(
            packet.toNetBytes(),
            b"\x01\x00\x00\x00"
            b"\x02\x00\x00\x00"
            b"\x03\x00\x00\x00"
            b"\x04\x00\x00\x00"
            b"data",
        )

    def test_build_udp_packages_splits_on_packet_size(self):
        packets = buildUdpPackages(b"abcdef", group_id=7, max_packet_size=2)

        self.assertEqual(len(packets), 3)
        self.assertEqual([packet.groupId for packet in packets], [7, 7, 7])
        self.assertEqual([packet.num for packet in packets], [3, 3, 3])
        self.assertEqual([packet.index for packet in packets], [0, 1, 2])
        self.assertEqual([packet.dataLength for packet in packets], [2, 2, 2])
        self.assertEqual([packet.data for packet in packets], [b"ab", b"cd", b"ef"])

    def test_build_udp_packages_keeps_remainder_packet(self):
        packets = buildUdpPackages(b"abcde", group_id=9, max_packet_size=2)

        self.assertEqual(len(packets), 3)
        self.assertEqual([packet.dataLength for packet in packets], [2, 2, 1])
        self.assertEqual([packet.data for packet in packets], [b"ab", b"cd", b"e"])

    def test_build_udp_packages_rejects_invalid_packet_size(self):
        with self.assertRaises(ValueError):
            buildUdpPackages(b"abc", group_id=1, max_packet_size=0)


if __name__ == "__main__":
    unittest.main()
