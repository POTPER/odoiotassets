import ctypes
import time
import socket
import os
import json
import math
from PIL import Image
import numpy as np

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


# 播放播放器内置mp3文件
# 参数1：模块地址
# 参数2：内置文件名称
# 参数3：volumn声音大小

smartSensorlib.PlayLocalFile.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_int
]
smartSensorlib.PlayLocalFile.restype = ctypes.c_int


# 停止播放
# 参数1：模块地址

smartSensorlib.StopPlay.argtypes = [
    ctypes.c_int
]
smartSensorlib.StopPlay.restype = ctypes.c_int

# 在线播放，播放客户端本地文件
# 参数1：模块地址
# 参数1：模块地址
# 参数2：文件名称
# 参数3：volumn声音大小
# 参数4：是否需要上传文件，第一次需要上传，之后不用上传
smartSensorlib.PlayOnline.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_int,
     ctypes.c_int
]
smartSensorlib.PlayOnline.restype = ctypes.c_int


class Mp3Player(object):
    def __init__(self, modIndex):
        self.modIndex = modIndex

    def PlayLocalFile(self,filename,volumn):
        smartSensorlib.PlayLocalFile(self.modIndex,filename,volumn)
    def StopPlay(self):
        smartSensorlib.StopPlay(self.modIndex)
    def PlayOnline(self,filename,volumn,needtransferfile):
        smartSensorlib.PlayOnline(self.modIndex,filename,volumn,needtransferfile)