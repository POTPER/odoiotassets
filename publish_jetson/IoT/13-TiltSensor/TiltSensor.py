import ctypes
import time
import socket
import os
import json
import math
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


# lis2dh12Init初始化
# 参数1：模块地址
# 参数2：SCL pin 序号
# 参数3：SDA PIN 序号
# 参数4：传感器I2C地址
# 参数5：通讯速率
smartSensorlib.lis2dh12Init.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.lis2dh12Init.restype = ctypes.c_int


# lis2dh12读数据
# 参数1：模块地址
# 参数2：addr
# 参数3：addrbytenum
# 参数4：bytenum字节数
# 参数5：bigendian
# 参数6：data
smartSensorlib.readLis2dh12Angel.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_float),
    ctypes.POINTER(ctypes.c_float),
    ctypes.POINTER(ctypes.c_float),
]
smartSensorlib.readLis2dh12Angel.restype = ctypes.c_int

# lis2dh12
# 参数1：模块地址
smartSensorlib.unLis2dh12Init.argtypes = [
    ctypes.c_int,
]
smartSensorlib.unLis2dh12Init.restype = ctypes.c_int


#LIS2DH12TR,SA0/SDO 引脚电平 连接至 Vdd (高电平) 0x19 (7位地址),连接至 GND (低电平) 0x18 (7位地址)
LIS2DH12TR_ADDR = 0x19  # 设备ID寄存器地址

LIS2DH12TR_ADDR_LENGHT = 7  # 地址长度

# AHT20 pin脚定义
LIS2DH12TR_SDA_PIN = 22
LIS2DH12TR_SCL_PIN = 23

LIS2DH12TR_MASTER_FREQ_HZ = 400000  # I2C速率



class TiltSensor(object):
    def __init__(self, modIndex):
        self.modIndex = modIndex
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器

        print("start to read init LIS2DH12TR ")
        # 初始化I2C
        smartSensorlib.lis2dh12Init(
            self.modIndex,
            LIS2DH12TR_SCL_PIN,
            LIS2DH12TR_SDA_PIN,
            LIS2DH12TR_ADDR,
            LIS2DH12TR_MASTER_FREQ_HZ
        )

    def get_difference_from_zero(self):
        x = ctypes.c_float(1.0)
        y = ctypes.c_float(1.0)
        z = ctypes.c_float(1.0)
        ret = smartSensorlib.readLis2dh12Angel(self.modIndex,ctypes.byref(x),ctypes.byref(y),ctypes.byref(z))
        return ret,x.value,y.value,z.value
    
    def uninit(self):
        ret = smartSensorlib.unLis2dh12Init(self.modIndex)
        if ret < 0:
           raise ValueError("mod disconnect")
