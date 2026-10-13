import ctypes
import time
import socket
import os
import json
import math
from UdpPackage import *


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")

#GPIO 输出初始化
#参数1：模块位置
#参数2：pin脚
#参数3：pullup
#参数4：pulldown
#参数5：intr_type
smartSensorlib.GpioInInit.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
smartSensorlib.GpioInInit.restype = ctypes.c_int
#获取GPIO电平
smartSensorlib.GpioGetLevel.argtypes = [ctypes.c_int, ctypes.c_int]
smartSensorlib.GpioGetLevel.restype = ctypes.c_int

class INIOController(object):
    def __init__(self, modIndex,pinindex):
        self.existing_data = []
        self.modIndex = modIndex
        self.pinIndex = pinindex
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器
        
    def Init(self,pullup,pulldown,intrflag):
        return smartSensorlib.GpioInInit(self.modIndex,self.pinIndex,pullup,pulldown,intrflag)
    
    def getLevel(self):
        return smartSensorlib.GpioGetLevel(self.modIndex,self.pinIndex)

   
    