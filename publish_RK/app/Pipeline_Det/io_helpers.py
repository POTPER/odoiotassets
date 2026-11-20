"""V14 JPEG/status UDP transport; importing opens no socket."""

import socket
import struct
import threading

MAX_PACKET_PAYLOAD = 60000
UDP_HEADER = struct.Struct("<IIII")


class UdpSender:
    """Send images and counts using the existing 16-byte packet header.

    The header is four unsigned little-endian integers: message group ID,
    packet count, zero-based packet index, and payload byte count.  A lock
    protects the ID and the entire message, including close(), so concurrent
    image and count sends cannot accidentally share an ID or a closed socket.
    Socket errors are deliberately propagated to the caller.
    """

    def __init__(self, host="127.0.0.1", image_port=8088, info_port=8089):
        for port in (image_port, info_port):
            if not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("UDP ports must be integers from 1 to 65535")
        self._image_address = (host, image_port)
        self._info_address = (host, info_port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(0.2)
        self._lock = threading.Lock()
        self._group_id = 0
        self._closed = False

    def _send(self, payload, address):
        payload = bytes(payload)
        if not payload:
            raise ValueError("Cannot send an empty UDP message")
        count = (len(payload) + MAX_PACKET_PAYLOAD - 1) // MAX_PACKET_PAYLOAD
        if count > 0xFFFFFFFF:
            raise ValueError("UDP message has too many packets")
        with self._lock:
            if self._closed:
                raise RuntimeError("UDP sender has been closed")
            self._group_id = (self._group_id + 1) & 0xFFFFFFFF
            group_id = self._group_id
            for index in range(count):
                offset = index * MAX_PACKET_PAYLOAD
                part = payload[offset:offset + MAX_PACKET_PAYLOAD]
                packet = UDP_HEADER.pack(group_id, count, index, len(part)) + part
                sent = self._socket.sendto(packet, address)
                if sent != len(packet):
                    raise OSError("Incomplete UDP datagram send")

    def send_image(self, jpeg_bytes):
        self._send(jpeg_bytes, self._image_address)

    def send_counts(self, first, second):
        """Send the existing UTF-8 ``first,second`` count payload."""
        self._send("{},{}".format(first, second).encode("utf-8"), self._info_address)

    def send_status(self, fire_present):
        """Keep the Fire_Seg receiver contract: UTF-8 有 / 无, no count list."""
        self._send(('有' if fire_present else '无').encode('utf-8'), self._info_address)

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._socket.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
