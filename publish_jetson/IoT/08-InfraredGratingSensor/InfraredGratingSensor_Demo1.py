# -*- coding: utf-8 -*-
"""
红外光栅传感器模块演示程序
实现红外光栅遮挡状态检测与上报
"""
import json
import math
import os
import socket
import time

from SensorModule import *
from INIOController import *

from UdpPackage import UdpPackage
# --------------------------------------------------------------
# 系统核心功能模块

SLEEP_TIME = 0.1  # 采集间隔时间（秒），红外传感器响应快，可以高频采集
modIndex = 8  # 模块地址

# --------------------------------------------------------------



# 传感器名称常量
SENSOR_NAME = "InfraredGratingSensor"

modStatus = 0   #模块状态
ir_pin = 5  #gpio引脚

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0


def _send_udp(data_bytes):
    """通过 UDP 发送数据"""
    global _global_packet_id
    _global_packet_id += 1
    
    length = len(data_bytes)
    num_packets = math.ceil(length / UDP_MAX_PACKET_SIZE)
    
    for i in range(num_packets):
        start = i * UDP_MAX_PACKET_SIZE
        end = min(start + UDP_MAX_PACKET_SIZE, length)
        packet = UdpPackage(
            _global_packet_id, num_packets, i,
            end - start, data_bytes[start:end]
        )
        _udp_socket.sendto(packet.toNetBytes(), UDP_DEST_ADDR)


def _save_data(sensor_values, frequency, target_values, status_connection, status_communication, status_output):
    """保存传感器数据到文件并通过 UDP 发送"""
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.join(current_dir, 'student_data')
    file_path = os.path.join(data_dir, 'student_data.json')
    
    os.makedirs(data_dir, exist_ok=True)
    
    data = {
        "Name": SENSOR_NAME,
        "Answer": sensor_values,
        "Target_Value": target_values,
        "Output_Frequency": frequency,
        "Status": {
            "Connection_Status": status_connection,
            "Communication_Status": status_communication,
            "Output_Status": status_output
        }
    }
    
    existing_data = []
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = []
    
    if len(existing_data) >= 5:
        existing_data = existing_data[1:]
    existing_data.append(data)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)
    
    _send_udp(json.dumps(existing_data).encode('utf-8'))
    print(f"数据保存成功: {sensor_values}, 状态: Connection={status_connection}, Communication={status_communication}, Output={status_output}")


def sensor_init(sensor):
    """初始化红外光栅传感器 GPIO，返回是否成功"""
    try:
        #pulldown拉低模式
        sensor.Init(0,1,0)
        print(f"红外光栅传感器初始化完成")
        return True
    except Exception as e:
        print(f"红外光栅传感器初始化失败: {e}")
        return False


def sensor_read(sensor):
    """读取红外光栅传感器状态，返回 "正常" 或 "遮挡" """
    value = sensor.getLevel()
    return value
   


def run_sensor(sensor,sleep_time):
    """运行传感器采集循环"""
    frequency = f"{sleep_time} s/次"
    target_values = {"Grating_Status": "0"}
    
    # 1. 尝试初始化GPIO，判断是否连接
    if not sensor_init(sensor):
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"Grating_Status": "未知"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    # 2. 初始化成功，读取并保存第一次数据（状态1）
    status = sensor_read(sensor)
    sensor_values = {"Grating_Status": status}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print("请观察红外光栅传感器的状态变化")
    print(f"采集间隔: {sleep_time} 秒")
    print("-" * 30)
    
    # 3. 开始循环读取数据
    try:
        while True:
            time.sleep(sleep_time)
            ret = sensor_read(sensor)
            if ret < 0:
               sensor_values = {"Grating_Status": "失败"}
               _save_data(sensor_values, frequency, target_values, 0, 0, 0)
               time.sleep(1.5)
               print("设备未连接，程序退出")
               return
            status = "0"
            if ret == 1:
                status= "1"
            
            print(f"光栅状态: {status}")
            
            sensor_values = {"Grating_Status": status}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    except Exception as e:
        print(f"检测到设备异常: {e}")
        sensor_values = {"Grating_Status": "未知"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序停止")


if __name__ == '__main__':
    
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

    sensor = INIOController(modIndex,ir_pin)

    try:
        run_sensor(sensor,SLEEP_TIME)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{SLEEP_TIME} s/次"
        target_values = {"Grating_Status": "0"}
        sensor_values = {"Grating_Status": "未知"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序已停止")
    
    finally:
        modules.modDisconnect(modIndex)
        modules.uninit()
