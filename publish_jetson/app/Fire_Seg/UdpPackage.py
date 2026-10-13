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
        print(" "+str(self.groupId)+"=="+str(self.num)+"=="+str(self.index)+"=="+str(self.dataLength))
        return b1 + b2 + b3 + b4 + self.data