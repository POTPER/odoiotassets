# -*- coding: utf-8 -*-
import time
import json
import os
import socket
import math
from SensorModule import *
from TiltSensor import TiltSensor
from UdpPackage import UdpPackage
import time

# --------------------------------------------------------------
# 参数设置区
# 用户可以根据自己的实验需求调整以下参数。
# --------------------------------------------------------------
SLEEP_TIME = 1                    # 读取频率（秒）
ANGLE_Y_TARGET_VALUE = 50         # Y轴目标值
ANGLE_Y_MAXIMUM_VALUE = 90        # Y轴最大值


#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#模块放置位置
modIndex = 13
#读超时时间,单位秒
READ_TIMER_OUT = 5
_tilesensor=None

# 传感器名称常量
SENSOR_NAME = "TileSensor"


# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

init_val = 0

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


def _save_data(sensor_values, frequencies, target_values, status_connection, status_communication, status_output):
    """保存传感器数据到文件并通过 UDP 发送"""
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.join(current_dir, 'student_data')
    file_path = os.path.join(data_dir, 'student_data.json')
    
    os.makedirs(data_dir, exist_ok=True)
    
    # 构建数据结构
    data = {
        "Name": SENSOR_NAME,
        "Answer": sensor_values,
        "Target_Value": target_values,
        "Output_Frequency": frequencies,
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
    print("传感器数据保存成功")

# --------------------------------------------------------------
# 系统核心功能模块
# --------------------------------------------------------------
def run_sensor(sensor):
    global modStatus,modIndex
    """持续读取传感器数据并保存"""
    send_count = 0
    sensor_name = "TiltSensor"
    frequencies = f"{SLEEP_TIME} s/次"
    
    if modStatus==0:
        #如果传感器不在线，再查询传感器是否在线
        if modules.isModReady(modIndex)==1:
            #如果模块在线，则连接模块
             ret = modules.modConnect(modIndex)
             if ret == 1:
                #连接成功
                modStatus = 1
                
        else:
            # 初始化失败，发送状态0，程序退出
            sensor_values = {"distance_mm": 0}
            _save_data(sensor_values, frequencies, target_values, 0, 0, 0)
            time.sleep(1.5)
            print("设备未连接，程序退出")
            return
    ret,diff_x, diff_y, diff_z = sensor.get_difference_from_zero()
    if ret == 0:
                # 初始化失败，发送状态0，程序退出
                sensor_values = {"distance_mm": 0}
                _save_data(sensor_values, frequencies, target_values, 0, 0, 0)
                time.sleep(1.5)
                print("设备连接断开，程序退出")
                return
    init_val =  diff_y   
    while True:
        # 获取与零点的差值（X, Y, Z）
        ret,diff_x, diff_y, diff_z = sensor.get_difference_from_zero()
        
        if ret == 0:
            # 初始化失败，发送状态0，程序退出
            sensor_values = {"distance_mm": 0}
            _save_data(sensor_values, frequencies, target_values, 0, 0, 0)
            time.sleep(1.5)
            print("设备连接断开，程序退出")
            return
        # 打印三轴数据
        print(f"相对角度 - X: {diff_x:.0f}度, Y: {diff_y:.0f}度, Z: {diff_z:.0f}度")

        #去皮
        diff_y = diff_y-init_val
        if abs(diff_y)<0.3:
            diff_y = 0
        # 只保存Y轴数据
        sensor_values = {"angleY": round(diff_y, 1)}
        target_values = {"angleYSensor": ANGLE_Y_TARGET_VALUE}
        maximum_values = {"angleYSensor": ANGLE_Y_MAXIMUM_VALUE}
        
        print(sensor_values)
        
        # 保存数据
        _save_data(
            sensor_values,
            frequencies,
            target_values,
            0,
            0,
            0
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
    
    _tilesensor = TiltSensor(modIndex)
    # 运行传感器读取
    try:

      run_sensor(_tilesensor)
    except KeyboardInterrupt:
        print("\n程序已停止")
    
    finally:
        _tilesensor.uninit()
