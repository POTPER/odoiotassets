# -*- coding: utf-8 -*-
"""
OLED 显示模块演示程序
实现 OLED 屏幕文字和图片显示
"""

import time
import json
import os
import socket
import math
import signal
import sys
from SensorModule import *
from PlayerSensor import *


from UdpPackage import UdpPackage

# --------------------------------------------------------------
# 系统核心功能模块（无需修改）
# --------------------------------------------------------------

# 传感器名称常量
SENSOR_NAME = "Mp3Player"

#模块位置
modIndex = 15
#模块状态，0：不在线，1：在线
modStatus = 0

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

_player=None

_needTransferFile = 1

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

def run_player(modules,play_interval):
    global modStatus,modIndex,_player,_needTransferFile
    frequency = f"{play_interval} s/次"
    target_values = {"Player_Status": "-"}
    
    if modStatus==0:
        #如果传感器不在线，再查询传感器是否在线
        if modules.isModReady(modIndex)==1:
            #如果模块在线，则连接模块
            ret = modules.modConnect(modIndex)
            if ret == 1:
                #连接成功
                modStatus = 1
            else:
                sensor_values = {"Player_Status": "关闭", "Display_Content": "无"}
                _save_data(sensor_values, frequency, target_values, 0, 0, 0)
                time.sleep(1.5)
                print("设备未连接，程序退出")
                return 

    _player = Mp3Player(modIndex)
    # 2. 初始化成功，保存第一次数据（状态1）
    sensor_values = {"Player_Status": "开启", "Display_Content": "初始化"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print(f"切换间隔: {play_interval} 秒")
    print("-" * 30)

    # 4. 开始循环显示
    #播放播放器内置文件
    filename = "00001.mp3"
    filename_gbk = bytes(filename, 'gbk')
    localfilename = "adf_music.mp3"
    local_filename_gbk = bytes(localfilename, 'gbk')

    _player.PlayLocalFile(filename_gbk,100)
    time.sleep(10)
    _player.StopPlay()
    #time.sleep(1)
    #print("start to playonline")
    #播放本地文件
    #_player.PlayOnline(local_filename_gbk,100,_needTransferFile)
    #if(_needTransferFile==1):
    #   _needTransferFile=0
    #time.sleep(play_interval)
    



# --------------------------------------------------------------
# 参数设置区
# --------------------------------------------------------------
if __name__ == '__main__':
    
    PLAYER_INTERVAL = 10  # 显示切换间隔（秒）
    
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
        run_player(modules,PLAYER_INTERVAL)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{PLAYER_INTERVAL} s/次"
        target_values = {"Player_Status": "-"}
        sensor_values = {"Player_Status": "关闭", "Display_Content": "无"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序已停止")
    
    finally:
        modules.modDisconnect(modIndex)
        modules.uninit()
