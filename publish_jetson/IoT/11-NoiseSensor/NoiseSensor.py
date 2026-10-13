import time
import socket
import os
import json
import math
from UdpPackage import *
from RS232Module import *


TX_PIN = 22
RX_PIN = 23




class NoiseSensor(object):
    def __init__(self, modIndex,comIndex):
        self.existing_data = []
        self.modIndex = modIndex
        self.comIndex = comIndex
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器
        ret = smartSensorlib.RS232Init(self.modIndex, self.comIndex, TX_PIN, RX_PIN, 115200, 0, 8,1)
        if ret <0 :
            raise ValueError("mod disconnect") 
    def SendAscIIData(self, data, size):
        ret = smartSensorlib.RS232ModSendAscIIData(self.modIndex, self.comIndex, size,data)
        if ret <0 :
            raise ValueError("mod disconnect") 
    def SendHexData(self, data, size):
        ret = smartSensorlib.RS232ModSendHexData(self.modIndex, self.comIndex,size, data)
        if ret <0 :
            raise ValueError("mod disconnect") 
    def ReadAscIIData(self, data, size,timeout):
        ret = smartSensorlib.RS232ModReadAscIIData(self.modIndex, self.comIndex, size, data,timeout)
        if ret <0 :
            raise ValueError("mod disconnect") 
    def ReadHexData(self, data, size,timeout):
        ret = smartSensorlib.RS232ModReadHexData(self.modIndex, self.comIndex, size, data,timeout)
        if ret <0 :
            raise ValueError("mod disconnect") 
    def WriteReadHexData(self, readsize,readdata,sendsize,sendata,timeout):
        ret = smartSensorlib.RS232ModWriteReadHexData(self.modIndex, self.comIndex, readsize, readdata,sendsize,sendata,timeout)
        return ret
    
    def WriteReadASCIIData(self, readsize,readdata,sendsize,sendata,timeout):
        ret = smartSensorlib.RS232ModWriteReadHexData(self.modIndex, self.comIndex, readsize, readdata,sendsize,sendata,timeout)
        return ret
            
    def uninit(self):
        ret = smartSensorlib.RS232Uninit(self.modIndex, self.comIndex)
        if ret <0 :
            raise ValueError("mod disconnect")     
    def _generate_crc16(data):
        """生成 Modbus CRC16 校验码"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    
