# -*- coding: utf-8 -*-
"""
光照传感器模块演示程序（OPT3001）
实现光照强度数据采集与上报
"""
import json
import math
import os
import socket
import time
from typing import Dict, List, Any, Tuple, Optional

from UdpPackage import UdpPackage
from SensorModule import *
from BH170Sensor import *
# --------------------------------------------------------------
# 系统核心功能模块

SLEEP_TIME = 1  # 采集间隔时间（秒）
LIGHT_TARGET_VALUE = 50  # 光照目标值
modIndex = 10  # 模块地址

# --------------------------------------------------------------



#模块状态，0：不在线，1：在线
modStatus = 0
SCL_PIN = 22
SDA_PIN = 23
#BH1750_ADDR_LO 是 0x23，BH1750_ADDR_HI 是 0x5C（取决于模块ADDR引脚电平）
BH170_ADDR_LOW = 0x23 
BH170_MASTER_FREQ_HZ = 100000  # I2C速率

# 低光照阈值（传感器底噪过滤，低于此值视为0 lux）
LOW_LIGHT_THRESHOLD: float = 10.0

# UDP 通信配置
UDP_DEST_ADDR: Tuple[str, int] = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE: int = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id: int = 0


_Sensor = None

def _send_udp(data_bytes: bytes) -> None:
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


def _save_data(sensor_values: Dict[str, float], frequencies: str, target_values: Dict[str, float]) -> None:
    """保存传感器数据到文件并通过 UDP 发送"""
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.join(current_dir, 'student_data')
    file_path = os.path.join(data_dir, 'student_data.json')
    
    os.makedirs(data_dir, exist_ok=True)
    
    data: Dict[str, Any] = {
        "Name": "LightSensor",
        "Answer": sensor_values,
        "Target_Value": target_values,
        "Output_Frequency": frequencies,
        "Status": {
            "Connection_Status": 1,
            "Communication_Status": 1,
            "Output_Status": 1
        }
    }
    
    existing_data: List[Dict[str, Any]] = []
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            pass
    
    existing_data = existing_data[1:] if len(existing_data) >= 5 else existing_data
    existing_data.append(data)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)
    
    _send_udp(json.dumps(existing_data).encode('utf-8'))
    print("传感器数据保存成功")

def sensor_init() -> bool:
    """初始化光照传感器"""
    global _Sensor
    try:
        _Sensor = BH170Sensor(modIndex,SCL_PIN,SDA_PIN,BH170_ADDR_LOW,BH170_MASTER_FREQ_HZ)
        _Sensor.init()
        #power on
        _Sensor.writebyte(0x01)
        #
        time.sleep(0.2)
        #H- resolution mode
        _Sensor.writebyte(0x10)
        print("光照传感器初始化完成")
        return True
    except Exception as e:
        print(f"光照传感器初始化失败: {e}")
        return False


def sensor_read() -> float:
    """
    读取光照传感器数据，返回光照强度（lux）
    
    说明：
    - 返回值保留两位小数
    - 低于 LOW_LIGHT_THRESHOLD 的值视为 0 lux（底噪过滤）
    """
    if _Sensor is None:
        return 0.0
    
    
    lux = _Sensor.readData(0)
    
    # 底噪过滤：低于阈值视为 0
    if lux < LOW_LIGHT_THRESHOLD:
        return 0.0
    
    # 保留两位小数
    return round(lux, 2)


def sensor_cleanup() -> None:
    """清理 I2C 资源"""
    global _Sensor
    if _Sensor is not None:
        _Sensor.uninit()
        print("I2C 已关闭")


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
            
            print("设备未连接，程序退出")
            exit(1)      
    if not sensor_init():
        print("传感器初始化失败，程序退出")
        exit(1)
    
    # 启动时先发送一次数据
    lux = sensor_read()
    sensor_values = {"light_lux": round(lux, 2)}
    target_values = {"LightSensor": LIGHT_TARGET_VALUE}
    frequencies = f"{SLEEP_TIME} s/次"
    _save_data(sensor_values, frequencies, target_values)
    
    try:
        print("程序正在运行...")
        print("请观察光照传感器的数据变化")
        print("-" * 30)
        
        while True:
            lux = sensor_read()
            
            print(f"光照强度: {lux:.2f} lux")
            
            sensor_values = {"light_lux": round(lux, 2)}
            target_values = {"LightSensor": LIGHT_TARGET_VALUE}
            frequencies = f"{SLEEP_TIME} s/次"
            
            _save_data(sensor_values, frequencies, target_values)
            
            time.sleep(SLEEP_TIME)
    
    except KeyboardInterrupt:
        print("\n程序已停止")
    
    finally:
        sensor_cleanup()
