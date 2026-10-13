import ctypes


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")

# PWM初始化
#参数1：modIndex,模块地址
#参数2：pwmchnl,0~15，0~7，支持高速模式和低速模式，8~15支持低速模式
#参数3：pin脚
#参数4：speedmod，0：高速模式，1：低速模式
#参数5：timerindex,时间定时器，0，1，2
#参数6：分辨率，1~20位
#参数7：频率
#
smartSensorlib.PWNMInit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.PWNMInit.restype = ctypes.c_int

# 设置duty
#参数1：modIndex,模块地址
#参数2：pwmchnl,0~15，0~7，支持高速模式和低速模式，8~15支持低速模式
#参数3：速度模式：0：高速模式，1：低速模式
#参数4：duty，根据res设置，如res=10，则表示duty最大值时1024
smartSensorlib.PwmSetDuty.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.PwmSetDuty.restype = ctypes.c_int

# 设置Freq
#参数1：modIndex,模块地址
#参数2：speedmod，0：高速模式，1：低速模式
#参数3：timerindex,时间定时器，0，1，2
#参数7：频率
smartSensorlib.PwmSetFreq.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.PwmSetFreq.restype = ctypes.c_int

# Pwm 开始
#参数1：modIndex,模块地址
#参数2：speedmod，0：高速模式，1：低速模式
#参数2：pwmchnl,0~15，0~7，支持高速模式和低速模式，8~15支持低速模式
smartSensorlib.PwmStart.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.PwmStart.restype = ctypes.c_int

# Pwm 停止
#参数1：modIndex,模块地址
#参数2：speedmod，0：高速模式，1：低速模式
#参数2：pwmchnl,0~15，0~7，支持高速模式和低速模式，8~15支持低速模式
smartSensorlib.PwmStop.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.PwmStop.restype = ctypes.c_int
