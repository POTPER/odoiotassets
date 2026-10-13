# -*- coding: utf-8 -*-
from SensorModule import *
from WindSpeedSensor import WindSpeed
import time

# 传感器名称常量
SENSOR_NAME = "WindSpeedSensor"
_sensor=None

TX_PIN = 23
RX_PIN = 22

#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#模块放置位置
modIndex = 15
wind_speed_sensor=None

# --------------------------------------------------------------
# 系统核心功能模块
# 此部分代码负责处理实验无关的固定参数和基础功能，参数设置固定，无需用户更改。
# 该模块通过调用预设的函数，完成数据的基础处理和结果的初步计算。
# --------------------------------------------------------------
def run_sensor(sensor, sleep_time, target_value, maximum_value):
    """运行传感器采集循环"""
    frequency = f"{sleep_time} s/次"
    target_values = {"WindSpeed": target_value}
    maximum_values = {"WindSpeed": maximum_value}
    exceeding_limit_times = 3
    
    # 1. 启动时尝试读取一次，判断是否连接
    result = sensor.get_wind_speed()
    
    if result is None:
        # 读不到数据，发送状态0，程序退出
        sensor_values = {"WindSpeed": 0}
        sensor.save_sensor_data_to_file(
            sensor_values, frequency, target_values, maximum_values,
            exceeding_limit_times, SENSOR_NAME,
            0, 0, 0  # status_connection=0, status_communication=0, status_output=0
        )
        print("设备未连接，程序退出")
        return
    
    # 2. 读到数据，保存第一次数据（状态1）
    wind_speed = result[0]
    sensor_values = {"WindSpeed": wind_speed}
    sensor.save_sensor_data_to_file(
        sensor_values, frequency, target_values, maximum_values,
        exceeding_limit_times, SENSOR_NAME,
        1, 1, 1  # status_connection=1, status_communication=1, status_output=1
    )
    
    print("程序正在运行...")
    print(f"采集间隔: {sleep_time} 秒")
    print(f"目标值: {target_value}")
    print("-" * 30)
    
    # 3. 开始循环读取数据
    while True:
        time.sleep(sleep_time)
        result = sensor.get_wind_speed()
        
        if result is None:
            # 读不到数据，设备断开，发送状态0
            print("检测到设备断开!")
            sensor_values = {"WindSpeed": 0}
            sensor.save_sensor_data_to_file(
                sensor_values, frequency, target_values, maximum_values,
                exceeding_limit_times, SENSOR_NAME,
                0, 0, 0  # status_connection=0, status_communication=0, status_output=0
            )
            print("程序停止")
            break
        
        # 读取成功，保存数据，状态为1
        wind_speed = result[0]  # 从列表中取值
        sensor_values = {"WindSpeed": wind_speed}
        sensor.save_sensor_data_to_file(
            sensor_values, frequency, target_values, maximum_values,
            exceeding_limit_times, SENSOR_NAME,
            1, 1, 1  # status_connection=1, status_communication=1, status_output=1
        )

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
        wind_speed_sensor = WindSpeed(modIndex,com_index,TX_PIN,RX_PIN)
        run_sensor(wind_speed_sensor, sleep_time, windSpeed_sensor_target_value, windSpeed_sensor_maximum_value)
    except ValueError:
        print("\n设备断开连接")
    except KeyboardInterrupt:
        print("\n用户中断程序")
    finally:
        wind_speed_sensor.uninit()
