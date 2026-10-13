# -*- coding: utf-8 -*-
from SensorModule import *
from WindDirectionSensor import WindDirection
import time
# --------------------------------------------------------------
# 系统核心功能模块

sleep_time = 1
windDirection_sensor_target_value = 0
windDirection_sensor_maximum_value = 0
modIndex = 15  # 模块地址

# --------------------------------------------------------------


# 传感器名称常量
SENSOR_NAME = "WindDirectionSensor"

TX_PIN = 23
RX_PIN = 22

#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
wind_direction_sensor=None
# 定义方向转换函数
def get_wind_direction_name(degree):
    if 0 <= degree < 22.5:
        return "北 (N)"
    elif 22.5 <= degree < 45:
        return "东北偏北 (NBNE)"
    elif 45 <= degree < 67.5:
        return "东北 (NE)"
    elif 67.5 <= degree < 90:
        return "东偏北 (EBNE)"
    elif 90 <= degree < 112.5:
        return "东 (E)"
    elif 112.5 <= degree < 135:
        return "东南偏东 (SEB)"
    elif 135 <= degree < 157.5:
        return "东南 (SE)"
    elif 157.5 <= degree < 180:
        return "南偏东 (SBSE)"
    elif 180 <= degree < 202.5:
        return "南 (S)"
    elif 202.5 <= degree < 225:
        return "南偏西 (SBSE)"
    elif 225 <= degree < 247.5:
        return "西南 (SW)"
    elif 247.5 <= degree < 270:
        return "西偏南 (WBSS)"
    elif 270 <= degree < 292.5:
        return "西 (W)"
    elif 292.5 <= degree < 315:
        return "西北偏西 (WNW)"
    elif 315 <= degree < 337.5:
        return "西北 (NW)"
    elif 337.5 <= degree < 360:
        return "北偏西 (NBW)"
    else:
        return "未知方向"

def run_sensor(sensor, sleep_time, target_value, maximum_value):
    """运行传感器采集循环"""
    frequency = f"{sleep_time} s/次"
    target_values = {"WindDirectionSensor": target_value}
    maximum_values = {"WindDirectionSensor": maximum_value}
    exceeding_limit_times = 3
    
    # 1. 启动时尝试读取一次，判断是否连接
    result = sensor.get_wind_direction()
    
    if result is None:
        # 读不到数据，发送状态0，程序退出
        sensor_values = {"Wind_Direction": "未知方向"}
        sensor.save_sensor_data_to_file(
            sensor_values, frequency, target_values, maximum_values,
            exceeding_limit_times, SENSOR_NAME,
            0, 0, 0
        )
        print("设备未连接，程序退出")
        return
    
    # 2. 读到数据，保存第一次数据（状态1）
    direction_degree = result[0] / 100
    direction = get_wind_direction_name(direction_degree)
    print(f'当前风向: {direction} (度数: {direction_degree})')
    sensor_values = {"Wind_Direction": f"{direction} {direction_degree}°"}
    sensor.save_sensor_data_to_file(
        sensor_values, frequency, target_values, maximum_values,
        exceeding_limit_times, SENSOR_NAME,
        1, 1, 1
    )
    
    print("程序正在运行...")
    print(f"采集间隔: {sleep_time} 秒")
    print(f"目标值: {target_value}")
    print("-" * 30)
    
    # 3. 开始循环读取数据
    while True:
        time.sleep(sleep_time)
        result = sensor.get_wind_direction()
        
        if result is None:
            # 读不到数据，设备断开，发送状态0
            print("检测到设备断开!")
            sensor_values = {"Wind_Direction": "未知方向"}
            sensor.save_sensor_data_to_file(
                sensor_values, frequency, target_values, maximum_values,
                exceeding_limit_times, SENSOR_NAME,
                0, 0, 0
            )
            print("程序停止")
            break
        
        # 读取成功，保存数据，状态为1
        direction_degree = result[0] / 100
        direction = get_wind_direction_name(direction_degree)
        print(f'当前风向: {direction} (度数: {direction_degree})')
        sensor_values = {"Wind_Direction": f"{direction} {direction_degree}°"}
        sensor.save_sensor_data_to_file(
            sensor_values, frequency, target_values, maximum_values,
            exceeding_limit_times, SENSOR_NAME,
            1, 1, 1
        )

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
        wind_direction_sensor = WindDirection(modIndex,com_index,TX_PIN,RX_PIN)
        
        run_sensor(wind_direction_sensor, sleep_time, windDirection_sensor_target_value, windDirection_sensor_maximum_value)

    except KeyboardInterrupt:
        print("\n用户中断程序")
    except ValueError:
        print("\n设备断开连接")
        
    finally:
        wind_direction_sensor.uninit()
