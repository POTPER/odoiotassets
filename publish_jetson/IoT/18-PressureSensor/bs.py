# -*- coding: utf-8 -*-
from SensorModule import *
from PressureSensor import Pressure
import time

# --------------------------------------------------------------
# 参数设置区
# 用户可以根据自己的实验需求调整以下参数。
# --------------------------------------------------------------
SLEEP_TIME = 1                              # 读取频率（秒）
PRESSURE_TARGET_VALUE = 0                   # 压力目标数值
PRESSURE_MAXIMUM_VALUE = 0                  # 压力最大数值

#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#模块放置位置
modIndex = 15

ADC_CHNL = 0
BIT_WIDTH = 3

# --------------------------------------------------------------
# 系统核心功能模块
# --------------------------------------------------------------
def run_sensor(sensor):
    """持续读取传感器数据并保存"""
    send_count = 0
    sensor_name = "LiftingLoadSensor"
    frequencies = f"{SLEEP_TIME} s/次"
    
    while True:
        # 获取压力数据（已包含滤波和死区处理）
        pressure = sensor.get_sensor_data()
        
        if pressure is not None:
            print(f'CH5的当前压力值: {pressure}')
        
        # 构建保存数据
        sensor_values = {
            "LiftingLoadSensor": pressure if pressure is not None else 0,
        }
        target_values = {
            "LiftingLoadSensor": PRESSURE_TARGET_VALUE,
        }
        maximum_values = {
            "LiftingLoadSensor": PRESSURE_MAXIMUM_VALUE,
        }
        
        # 保存数据
        sensor.save_sensor_data_to_file(
            sensor_values=sensor_values,
            frequencies=frequencies,
            target_values=target_values,
            maximum_values=maximum_values,
            exceeding_limit_times=3,
            sensor_name=sensor_name,
            status_connection=1,
            status_communication=1,
            status_output=1
        )
        
        send_count += 1
        time.sleep(SLEEP_TIME)

# --------------------------------------------------------------
# 主程序入口
# --------------------------------------------------------------
if __name__ == "__main__":

    # 模块初始化
    modules = SensorModule()
    # 开始搜索模块
    modules.startScanSensors()
    # 连接继电器模块
    ret = modules.modConnect(modIndex)

    if ret<=0:
        modStatus=0
    else:
        modStatus=1
    # 初始化传感器
    sensor = Pressure(modIndex,ADC_CHNL,BIT_WIDTH)
    
    try:
        
        # 运行传感器读取
        run_sensor(sensor)
        
    except KeyboardInterrupt:
        print("\n程序已停止")
    finally:
        sensor.uninit()
