import math


class UdpPackage:
    def __init__(self, group_id, num, index, length, data):
        self.groupId = group_id
        self.num = num
        self.index = index
        self.dataLength = length
        self.data = data

    def toNetBytes(self):
        endian = 'little'
        b1 = self.groupId.to_bytes(length=4, byteorder=endian, signed=False)
        b2 = self.num.to_bytes(length=4, byteorder=endian, signed=False)
        b3 = self.index.to_bytes(length=4, byteorder=endian, signed=False)
        b4 = self.dataLength.to_bytes(length=4, byteorder=endian, signed=False)
        return b1 + b2 + b3 + b4 + self.data


def buildUdpPackages(bytes_data, group_id, max_packet_size):
    if max_packet_size <= 0:
        raise ValueError("max_packet_size must be positive")

    packets = []
    length = len(bytes_data)
    num_packets = math.ceil(length / max_packet_size)
    for i in range(num_packets):
        start = i * max_packet_size
        end = min(start + max_packet_size, length)
        packets.append(UdpPackage(group_id, num_packets, i, end - start, bytes_data[start:end]))
    return packets
