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

# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")

#GPIO 输出初始化
smartSensorlib.GpioOutInit.argtypes = [ctypes.c_int, ctypes.c_int]
smartSensorlib.GpioOutInit.restype = ctypes.c_int
#设置GPIO电平
smartSensorlib.GpioSetLevel.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
smartSensorlib.GpioSetLevel.restype = ctypes.c_int


