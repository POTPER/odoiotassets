# -*- coding: utf-8 -*-
"""
单路继电器模块演示程序
实现继电器开关控制效果
"""

import time
import json
import os
import socket
import math
from SensorModule import *
from RelayController import *
from UdpPackage import UdpPackage
# --------------------------------------------------------------
# 系统核心功能模块

ON_DURATION = 1       # 继电器开启持续时间（秒）
LOOP_DELAY = 2        # 循环间隔时间（秒）
modIndex = 3  # 模块地址

# --------------------------------------------------------------



# 传感器名称常量
SENSOR_NAME = "RelayModule"


# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

#继电器状态
relay_state = 0
#模块状态
modStatus = 0
_controller=None
#继电器的引脚
RELAY_CONTROLLER_PIN = 25

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
            with open(file_path, 'r') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = []
    
    if len(existing_data) >= 5:
        existing_data = existing_data[1:]
    existing_data.append(data)
    
    with open(file_path, 'w') as f:
        json.dump(existing_data, f, indent=4)
    
    _send_udp(json.dumps(existing_data).encode('utf-8'))
    print(f"数据保存成功: {sensor_values}, 状态: Connection={status_connection}, Communication={status_communication}, Output={status_output}")


def relay_on():
    global _controller
    """打开继电器（高电平触发）"""
    ret = _controller.control(1)
    if (ret < 0 ):
            raise ValueError("mod disconnect")

def relay_off():
    global _controller
    """关闭继电器"""
    ret = _controller.control(0)
    if (ret < 0 ):
            raise ValueError("mod disconnect")

def relay_init():
    global _controller
    """初始化继电器 GPIO，返回是否成功"""
    try:
        _controller = RelayController(modIndex)
        print("继电器初始化完成")
        return True
    except Exception as e:
        print(f"继电器初始化失败: {e}")
        return False


def run_relay(on_duration, loop_delay):
    global modStatus,modIndex
    """运行继电器循环"""
    frequency = f"{loop_delay} s/次"
    target_values = {"Relay_Status": "-"}
    
    # 1. 尝试初始化GPIO，判断是否连接
    if not relay_init():
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"Relay_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    # 2. 初始化成功，保存第一次数据（状态1）
    sensor_values = {"Relay_Status": "关闭"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print("请观察继电器的状态变化")
    print(f"循环间隔: {loop_delay} 秒")
    print("-" * 30)
    
   
    while True:
        if modStatus==0:
            #如果传感器不在线，再查询传感器是否在线
            if modules.isModReady(modIndex)==1:
                #如果模块在线，则连接模块
                ret = modules.modConnect(modIndex)
                if ret == 1:
                    #连接成功
                    modStatus = 1
                    #重新初始化模块
            else:
                sensor_values = {"Relay_Status": "关闭"}
                _save_data(sensor_values, frequency, target_values, 0, 0, 0)
                time.sleep(1.5)
                print("设备未连接，程序退出")
                return 
        
        # 开启继电器
        relay_on()
        sensor_values = {"Relay_Status": "开启"}
        _save_data(sensor_values, frequency, target_values, 1, 1, 1)
        time.sleep(on_duration)
        
        # 关闭继电器
        relay_off()
        sensor_values = {"Relay_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 1, 1, 1)
        
        time.sleep(loop_delay)
    
    


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
    try:
        run_relay(ON_DURATION, LOOP_DELAY)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{LOOP_DELAY} s/次"
        target_values = {"Relay_Status": "-"}
        sensor_values = {"Relay_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序已停止")
    
    finally:
        modules.modDisconnect(modIndex)
        modules.uninit()
