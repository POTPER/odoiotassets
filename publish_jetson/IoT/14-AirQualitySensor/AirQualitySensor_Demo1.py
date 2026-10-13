# -*- coding: utf-8 -*-
"""
空气质量传感器模块演示程序
实现PM2.5、PM10、TSP数据采集与上报
"""
import time
import json
import os
import socket
import math
from SensorModule import *
from AirQualitySensor import *
from UdpPackage import UdpPackage
# --------------------------------------------------------------
# 系统核心功能模块

SLEEP_TIME = 1  # 采集间隔时间（秒）
PM25_TARGET_VALUE = 0  # PM2.5 目标值
PM10_TARGET_VALUE = 0  # PM10 目标值
TSP_TARGET_VALUE = 0  # TSP 目标值
modIndex = 14  # 模块地址

# --------------------------------------------------------------



# 传感器名称常量
SENSOR_NAME = "AirQuality"

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

TX_PIN = 22
RX_PIN = 23

#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#读超时时间,单位秒
READ_TIMER_OUT = 5
_airsensor=None


def initialize_sensor_module():
    """初始化并连接传感器模块"""
    global modules, modStatus

    modules = SensorModule()
    modules.startScanSensors()
    ret = modules.modConnect(modIndex)

    if ret <= 0:
        modStatus = 0
    else:
        modStatus = 1

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


def sensor_init():
    """初始化空气质量传感器串口"""
    global _airsensor
    
    _airsensor = AirQualitySensor(modIndex,com_index,TX_PIN,RX_PIN)
    _airsensor.init()
    #初始化，设置pm25为问询模式
    send_buffer = (ctypes.c_ubyte * 9)()
    recv_buffer = (ctypes.c_ubyte * 32)()
        
    send_buffer[0] = 0xff
    send_buffer[1] = 0x01
    send_buffer[2] = 0x03
    send_buffer[3] = 0x02
    send_buffer[4] = 0x00
    send_buffer[5] = 0x00
    send_buffer[6] = 0x00
    send_buffer[7] = 0x00
    send_buffer[8] = 0x05
    ret = _airsensor.SendHexDataAndReadData(send_buffer,9,recv_buffer,32,READ_TIMER_OUT)
    print("recv ret="+str(ret))

def sensor_read():
    global _airsensor
    send_buffer = (ctypes.c_ubyte * 9)()
    recv_buffer = (ctypes.c_ubyte * 32)()
     #发送hex编码，查询环境数据   
    send_buffer[0] = 0xff
    send_buffer[1] = 0x01
    send_buffer[2] = 0x07
    send_buffer[3] = 0x01
    send_buffer[4] = 0x00
    send_buffer[5] = 0x00
    send_buffer[6] = 0x00
    send_buffer[7] = 0x00
    send_buffer[8] = 0x07
    ret = _airsensor.SendHexDataAndReadData(send_buffer,9,recv_buffer,32,READ_TIMER_OUT)
    
    # 处理无效值：太近（遮挡）或太远（超出范围）
    #hex_values = [hex(x) for x in recv_buffer]
    #print(hex_values)
    if ret <= 0 :
        return None
    pm25 = (recv_buffer[6]<<8 )|recv_buffer[7]
    pm100 = (recv_buffer[8]<<8 )|recv_buffer[9]
    #tsp 许多地区长期监测发现，TSP 与 PM10 的比例通常在 1.2–2.0 之间
    #普通城市环境：TSP ≈ PM10 × 1.2~1.5
    #沙尘或粗颗粒较多时：可能达 1.5~2.0
    #估算公式：TSP≈PM10×k
    tsp = round(pm100*1.2,1)
    return pm25,pm100,tsp


def sensor_cleanup():
    """清理串口资源"""
    global _airsensor
    _airsensor.uninit()


def run_sensor(sleep_time, pm25_target, pm10_target, tsp_target):
    global modStatus,modIndex
    """运行传感器采集循环"""
    frequencies = f"{sleep_time} s/次"
    target_values = {
        "PM2.5_value": pm25_target,
        "PM10_value": pm10_target,
        "TSP_value": tsp_target
    }
    
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
        
    # 1. 启动时尝试读取一次，判断是否连接
    result = sensor_read()
    
    if result is None:
        # 读不到数据，发送状态0，程序退出
        sensor_values = {"PM2.5_value": 0, "PM10_value": 0, "TSP_value": 0}
        _save_data(sensor_values, frequencies, target_values, 0, 0, 0)
        time.sleep(sleep_time + 0.5)  # 等待UDP发送完成
        print("设备未连接，程序退出")
        return
    
    # 2. 读到数据，保存第一次数据（状态1）
    pm25, pm10, tsp = result
    print(f"PM2.5: {pm25}, PM10: {pm10}, TSP: {tsp}")
    sensor_values = {"PM2.5_value": pm25, "PM10_value": pm10, "TSP_value": tsp}
    _save_data(sensor_values, frequencies, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print(f"采集间隔: {sleep_time} 秒")
    print("-" * 30)
    
    # 3. 开始循环读取数据
    while True:
        time.sleep(sleep_time)
        result = sensor_read()
        
        if result is None:
            # 读不到数据，设备断开，发送状态0
            print("检测到设备断开!")
            sensor_values = {"PM2.5_value": 0, "PM10_value": 0, "TSP_value": 0}
            _save_data(sensor_values, frequencies, target_values, 0, 0, 0)
            time.sleep(sleep_time + 0.5)  # 等待UDP发送完成
            print("程序停止")
            break
        
        # 读取成功，保存数据，状态为1
        pm25, pm10, tsp = result
        print(f"PM2.5: {pm25}, PM10: {pm10}, TSP: {tsp}")
        sensor_values = {"PM2.5_value": pm25, "PM10_value": pm10, "TSP_value": tsp}
        _save_data(sensor_values, frequencies, target_values, 1, 1, 1)


if __name__ == '__main__':
    initialize_sensor_module()
    try:
        sensor_init()
        run_sensor(SLEEP_TIME, PM25_TARGET_VALUE, PM10_TARGET_VALUE, TSP_TARGET_VALUE)
    except KeyboardInterrupt:
        print("\n用户中断程序")
    finally:
        sensor_cleanup()
