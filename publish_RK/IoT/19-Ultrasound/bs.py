# -*- coding: utf-8 -*-
"""
激光测距传感器模块演示程序（VL53L0X）
实现激光测距数据采集与上报
"""
import time
import json
import os
import socket
import math
from SensorModule import *
from UltrasoundSensor import *
from UdpPackage import UdpPackage


# 传感器名称常量
SENSOR_NAME = "UltrasoundSensor"

#模块地址
modIndex = 15

#模块状态，0：不在线，1：在线
modStatus = 0
TX_PIN = 23
RX_PIN = 22

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 2000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

#读超时时间,单位秒
READ_TIMER_OUT = 1
# 测量范围常量

_sensor = None
#模块有一个可用串口通道，2
com_index = 2
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


def sensor_init():
    """初始化超声波测距传感器，返回是否成功"""
    global _sensor
    try:

        _sensor = UltrasoundSensor(modIndex,com_index,TX_PIN,RX_PIN)
        
        _sensor.init()

        print("超声波测距传感器初始化完成")
        return True
    except Exception as e:
        print(f"超声波测距传感器初始化失败: {e}")
        return False


def sensor_read():
    """读取超声波测距传感器数据，返回距离值（mm）或 None（读取失败）"""
    if _sensor is None:
        return None
    
    try:
        send_buffer = (ctypes.c_ubyte * 2)()
        recv_buffer = (ctypes.c_ubyte * 4)()
        #发送0XA0读取距离，返回三个字节，BYTE_H，BYTE_M，BYTE_L，输出距离为：(（BYTE_H<<16）+（BYTE_M<<8）+ BYTE_L)/1000
        #单位 mm
        send_buffer[0] = 0xa0
        
        ret = _sensor.SendHexDataAndReadData(send_buffer,1,recv_buffer,4,READ_TIMER_OUT)
        
        # 处理无效值：太近（遮挡）或太远（超出范围）

        if ret < 0 :
            print("recv ret="+str(ret))
            return None
        distance = (recv_buffer[1]<<8 |recv_buffer[2])

        return distance
    except Exception as e:
        print(f"读取距离失败: {e}")
        return None


def sensor_cleanup():
    """清理传感器资源"""
    global _sensor
    if _sensor:
        try:
            _sensor.uninit()
            print("传感器已关闭")
        except Exception as e:
            print(f"关闭传感器失败: {e}")


def run_sensor(modules,sleep_time, target_value):
    global modStatus
    """运行传感器采集循环"""
    frequency = f"{sleep_time} s/次"
    target_values = {"distance_mm": target_value}
    print("run_sensor"+str(modStatus))
    if modStatus==0:
        #如果传感器不在线，再查询传感器是否在线
        if modules.isModReady(modIndex)==1:
            #如果模块在线，则连接模块
             ret = modules.modConnect(modIndex)
             if ret == 1:
                #连接成功
                modStatus = 1
                #重新初始化温湿度模块
                sensor_cleanup()
        else:
            # 初始化失败，发送状态0，程序退出
            sensor_values = {"distance_mm": 0}
            _save_data(sensor_values, frequency, target_values, 0, 0, 0)
            time.sleep(1.5)
            print("设备未连接，程序退出")
            return
    
    # 1. 尝试初始化传感器，判断是否连接
    if not sensor_init():
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"distance_mm": 0}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    # 2. 尝试读取一次数据
    distance = sensor_read()
    
    if distance is None:
        # 读不到数据，发送状态0，程序退出
        sensor_values = {"distance_mm": 0}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    # 3. 读到数据，保存第一次数据（状态1）
    if distance == 0:
        print("距离: 0 mm (遮挡或超出范围)")
    else:
        print(f"距离: {distance} mm ({distance / 10:.1f} cm)")
    sensor_values = {"distance_mm": distance}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print("请观察超声波测距传感器的数据变化")
    print(f"采集间隔: {sleep_time} 秒")
    print("-" * 30)
    
    # 4. 开始循环读取数据
    while True:
        time.sleep(sleep_time)
        distance = sensor_read()
        
        if distance is None:
            # 读不到数据，设备断开，发送状态0
            print("检测到设备断开111!")
            sensor_values = {"distance_mm": 0}
            _save_data(sensor_values, frequency, target_values, 0, 0, 0)
            time.sleep(1.5)
            print("程序停止")
            break
        
        # 读取成功，保存数据，状态为1
        if distance == 0:
            print("距离: 0 mm (遮挡或超出范围)")
        else:
            print(f"距离: {distance} mm ({distance / 10:.1f} cm)")
        sensor_values = {"distance_mm": distance}
        _save_data(sensor_values, frequency, target_values, 1, 1, 1)


# --------------------------------------------------------------
# 参数设置区
# --------------------------------------------------------------
if __name__ == '__main__':
    
    SLEEP_TIME = 1           # 采样间隔（秒）
    LASER_TARGET_VALUE = 50  # 目标值
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
        run_sensor(modules,SLEEP_TIME, LASER_TARGET_VALUE)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{SLEEP_TIME} s/次"
        target_values = {"distance_mm": LASER_TARGET_VALUE}
        sensor_values = {"distance_mm": 0}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序已停止")
    
    finally:
        sensor_cleanup()
