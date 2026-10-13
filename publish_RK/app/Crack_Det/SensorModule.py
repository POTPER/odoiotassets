import ctypes
import time


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

# 声明库函数

# 库初始化
smartSensorlib.SmartSensorLibUnInit.argtypes = ()
smartSensorlib.SmartSensorLibInit.argtypes = ()

# 开始搜索设备
smartSensorlib.startScanSensors.argtypes = ()
smartSensorlib.startScanSensors.restype = ctypes.c_int

# 云台控制
#参数：0：ptzturnleft,1:ptzturnright,2:ptzturnup,3:ptzturndown,4:ptzturnleftup,5:ptzturnleftdown,6:ptzturnrightup,7:ptzturnrightdown,8:ptzstop
#参数：speed，1~5，5最快，1：最慢
smartSensorlib.ptzControl.argtypes = [ctypes.c_int,ctypes.c_int]
smartSensorlib.ptzControl.restype = ctypes.c_int


# 连接模块
smartSensorlib.connectToMod.argtypes = [ctypes.c_int]
smartSensorlib.connectToMod.restype = ctypes.c_int
# 断开模块连接
smartSensorlib.disconnectToMod.argtypes = [ctypes.c_int]
smartSensorlib.disconnectToMod.restype = ctypes.c_int
#判断模块是否在线
smartSensorlib.isModReady.argtypes = [ctypes.c_int]
smartSensorlib.isModReady.restype = ctypes.c_int


array_size = 16
points_array = (tModInf * array_size)()


class SensorModule(object):
    def __init__(self):
        # 第一步，库初始化
        smartSensorlib.SmartSensorLibInit()
    def isModReady(self, modIndex):
        return smartSensorlib.isModReady(modIndex)
    def startScanSensors(self):
        result = smartSensorlib.startScanSensors()
        return result

    def PtzControl(self, dir,speed):
        return smartSensorlib.ptzControl(dir,speed)

    def modConnect(self, modIndex):
        return smartSensorlib.connectToMod(modIndex)

    def modDisconnect(self, modIndex):
        return smartSensorlib.disconnectToMod(modIndex)
    def uninit(self):
        # 模块注销
        smartSensorlib.SmartSensorLibUnInit()
