import ctypes


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")

# RS232初始化
smartSensorlib.RS232Init.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int
]
smartSensorlib.RS232Init.restype = ctypes.c_int
# rs232发送ascii数据
smartSensorlib.RS232ModSendAscIIData.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
     ctypes.POINTER(ctypes.c_char),
]
smartSensorlib.RS232ModSendAscIIData.restype = ctypes.c_int

# RS232发送hex数据
smartSensorlib.RS232ModSendHexData.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.RS232ModSendHexData.restype = ctypes.c_int

# RS232读取ascii数据
smartSensorlib.RS232ModReadAscIIData.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_int,
]
smartSensorlib.RS232ModReadAscIIData.restype = ctypes.c_int

# RS232读hex数据
smartSensorlib.RS232ModReadHexData.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_int,
]
smartSensorlib.RS232ModReadHexData.restype = ctypes.c_int

# RS232发送并接收HEX数据
smartSensorlib.RS232ModWriteReadHexData.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_int,
]
smartSensorlib.RS232ModReadHexData.restype = ctypes.c_int


# RS232发送并接收ASCII数据
smartSensorlib.RS232ModWriteReadAscIIData.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_int,
]
smartSensorlib.RS232ModWriteReadAscIIData.restype = ctypes.c_int

# RS232注销
smartSensorlib.RS232Uninit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.RS232Uninit.restype = ctypes.c_int
