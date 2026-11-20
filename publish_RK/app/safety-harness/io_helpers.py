"""Optional JPEG UDP transport matching the existing vision applications."""

import socket
import struct

HEADER = struct.Struct('<IIII')
PAYLOAD_SIZE = 60000


class UdpImageSender:
    def __init__(self, host='127.0.0.1', port=8088):
        self.address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.group_id = 0

    def send(self, jpeg):
        if not jpeg:
            raise ValueError('JPEG不能为空')
        self.group_id = (self.group_id + 1) & 0xffffffff
        count = (len(jpeg) + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
        for index in range(count):
            part = jpeg[index * PAYLOAD_SIZE:(index + 1) * PAYLOAD_SIZE]
            packet = HEADER.pack(self.group_id, count, index, len(part)) + part
            if self.socket.sendto(packet, self.address) != len(packet):
                raise OSError('UDP数据包发送不完整')

    def close(self):
        self.socket.close()
