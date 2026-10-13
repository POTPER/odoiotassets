# -*- coding: utf-8 -*-
"""
UDP 数据包封装模块
用于将数据分包发送
"""


class UdpPackage:
    """UDP 数据包类"""
    
    def __init__(self, group_id, num, index, length, data):
        """初始化 UDP 数据包
        
        Args:
            group_id: 数据包组 ID
            num: 总包数
            index: 当前包索引
            length: 数据长度
            data: 数据内容
        """
        self.group_id = group_id
        self.num = num
        self.index = index
        self.data_length = length
        self.data = data

    def toNetBytes(self):
        """转换为网络字节序"""
        endian = 'little'
        b1 = self.group_id.to_bytes(length=4, byteorder=endian, signed=False)
        b2 = self.num.to_bytes(length=4, byteorder=endian, signed=False)
        b3 = self.index.to_bytes(length=4, byteorder=endian, signed=False)
        b4 = self.data_length.to_bytes(length=4, byteorder=endian, signed=False)
        return b1 + b2 + b3 + b4 + self.data
