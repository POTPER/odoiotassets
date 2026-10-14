# -*- coding: utf-8 -*-
from SensorModule import *
from LiftingLoadSensor import LiftingLoadSensor
import time

# 传感器名称常量
SENSOR_NAME = "LiftingLoadSensor"
_sensor=None

TX_PIN = 23
RX_PIN = 22

#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#模块放置位置
modIndex = 15
lifting_load_sensor=None

# --------------------------------------------------------------
# 参数设置区
# 用户可以根据自己的实验需求调整以下参数。
# --------------------------------------------------------------
SLEEP_TIME = 1                    # 读取频率（秒）
TARGET_VALUE = 0                  # 目标值（克）
MAXIMUM_VALUE = 0                 # 最大值（克）

# --------------------------------------------------------------
# 系统核心功能模块
# 此部分代码负责处理实验无关的固定参数和基础功能，参数设置固定，无需用户更改。
# 该模块通过调用预设的函数，完成数据的基础处理和结果的初步计算。
# --------------------------------------------------------------
def run_sensor(sensor):
    """持续读取传感器数据并保存"""
    send_count = 0
    sensor_name = "LiftingLoadSensor"
    frequencies = f"{SLEEP_TIME} s/次"

    sensor.set_lifting_load_shelling()

    # 晃动阈值（超过此值认为是晃动产生的异常数据）
    SHAKE_THRESHOLD = 6000
    
    while True:
        # 读取吊重数据
        pressure_raw = sensor.get_lifting_load_pressure()[0]
        weight = round(pressure_raw / 10, 2)
        # 检测是否晃动（异常值）
        if weight > SHAKE_THRESHOLD:
            print("检测到晃动，请保持吊重静止")
            sensor_values = {"LiftingLoadSensor": "请保持吊重静止"}
        else:
            print(f'吊重 = {weight} g')
            sensor_values = {"LiftingLoadSensor": weight}
        
        # 构建数据
        target_values = {"LiftingLoadSensor": TARGET_VALUE}
        maximum_values = {"LiftingLoadSensor": MAXIMUM_VALUE}
        
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
# 实验核心模块
# 此部分用户将进行实验的主要操作，包括参数设置和实验过程监控。
# 请按照实验指导书的指示逐步进行，每个步骤都有相应的提示和帮助，如有疑问请参考教程。
# 注意：在此模块中，用户需要仔细阅读并理解每个操作的含义，以确保实验的正确进行。
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
    try:
# --------------------------------------------------------------
# 参数设置区
# 用户可以根据自己的实验需求调整以下参数。
# 请用户在了解每个参数含义后，根据实验需要进行合理设置。
# --------------------------------------------------------------       
        sleep_time = 1  # 设置频率为1秒
        windSpeed_sensor_target_value = 0  # 设置目标数值
        windSpeed_sensor_maximum_value = 0  # 设置最大数值
        lifting_load_sensor = LiftingLoadSensor(modIndex,com_index,TX_PIN,RX_PIN)
        run_sensor(lifting_load_sensor)
    except ValueError:
        print("\n设备断开连接")
    except KeyboardInterrupt:
        print("\n用户中断程序")
    finally:
        lifting_load_sensor.uninit()
