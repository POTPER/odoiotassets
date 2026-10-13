import struct


class UdpPackage:
    """UDP数据包封装类"""
    
    def __init__(self, group_id: int, num: int, index: int, length: int, data: bytes) -> None:
        self.group_id = group_id
        self.num = num
        self.index = index
        self.data_length = length
        self.data = data

    def to_net_bytes(self) -> bytes:
        """将数据包转换为网络字节序"""
        header = struct.pack('<4I', self.group_id, self.num, self.index, self.data_length)
        return header + self.data
    
    # 保留旧方法名以保持向后兼容
    def toNetBytes(self) -> bytes:
        return self.to_net_bytes()
