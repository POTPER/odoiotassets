import ctypes
import time
import socket
import os
import json
import math
import numpy as np
from UdpPackage import *

dest_addr = ("127.0.0.1", 8088)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

global_id = 0
max_packet_size = 1000


# 传感器模块信息
class tModInf(ctypes.Structure):
    _fields_ = [
        ("nModType", ctypes.c_int),
        ("nModState", ctypes.c_int),
        ("servport", ctypes.c_int),
        ("sModIP", ctypes.c_char * 64),
        ("sModVer", ctypes.c_char * 64),
    ]


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")


# I2C初始化
# 参数1：模块地址
# 参数2：SCL pin 序号
# 参数3：SDA PIN 序号
# 参数4：I2C传感器地址长度
# 参数5：通讯速率
# 参数6：传感器I2C地址
smartSensorlib.I2CInit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.I2CInit.restype = ctypes.c_int


# I2C读数据
# 参数1：模块地址
# 参数2：addr
# 参数3：addrbytenum
# 参数4：bytenum字节数
# 参数5：bigendian
# 参数6：data
smartSensorlib.I2CRead.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.I2CRead.restype = ctypes.c_int

# I2C写数据
# 参数1：模块地址
# 参数2：addr
# 参数3：addrbytenum字节数
# 参数4：bytenum字节数
# 参数5：bigendian
# 参数6：data
smartSensorlib.I2CWrite.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.I2CWrite.restype = ctypes.c_int

smartSensorlib.I2CUninit.argtypes = [ctypes.c_int]
smartSensorlib.I2CUninit.restype = ctypes.c_int


class BH170Sensor(object):
    def __init__(self, modIndex,sclpin,sdapin,addr,freq):
        self.modIndex = modIndex
        self.sclpin = sclpin
        self.sdapin = sdapin
        self.i2caddr = addr
        self.freq = freq
        self._distanceMode = 0
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器

    def uninit(self):
        ret = smartSensorlib.I2CUninit(self.modIndex) 
        if ret <0 :
            raise ValueError("mod disconnect")    
    def init(self):
        # 初始化I2C
        ret= smartSensorlib.I2CInit(
            self.modIndex,
            self.sclpin,
            self.sdapin,
            8,
            self.freq,
            self.i2caddr,
        )
        if ret <0 :
            return False
        return True
    def readData(self,registeraddr):
        regdata = (ctypes.c_ubyte * 3)()
        ret = smartSensorlib.I2CRead(self.modIndex, registeraddr,0, 2,0, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        LightData = (regdata[0]<<8|regdata[1])/1.2;
        return LightData
    def readregister(self,registeraddr):
        regdata = (ctypes.c_ubyte * 2)()
        ret = smartSensorlib.I2CRead(self.modIndex, registeraddr,1, 1,0, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        return regdata[0]
    def writebyte(self,regval):
        regdata = (ctypes.c_ubyte * 2)()
        regdata[0] = regval&0xff
        ret = smartSensorlib.I2CWrite(self.modIndex, regval,1, 0,0, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        return 0

    def writeregister(self,registeraddr,regval):
        regdata = (ctypes.c_ubyte * 2)()
        regdata[0] = regval&0xff
        ret = smartSensorlib.I2CWrite(self.modIndex, registeraddr,1, 1,0, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        return 0


    
