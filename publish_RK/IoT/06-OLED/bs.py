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
from OLEDSensor import *
from PIL import Image, ImageDraw, ImageFont

from UdpPackage import UdpPackage

# --------------------------------------------------------------
# 系统核心功能模块（无需修改）
# --------------------------------------------------------------

# 传感器名称常量
SENSOR_NAME = "OLED"

SCL_PIN = 22
SDA_PIN = 23
#模块位置
modIndex = 6
#模块状态，0：不在线，1：在线
modStatus = 0

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

#屏幕的显示尺寸
SCREEN_WIDTH =128
SCREEN_HEIGHT = 64


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

def run_oled(modules,sensor,display_interval):
    global modStatus,modIndex
    """运行OLED显示循环"""
    frequency = f"{display_interval} s/次"
    target_values = {"OLED_Status": "-"}
    
    if modStatus==0:
        #如果传感器不在线，再查询传感器是否在线
        if modules.isModReady(modIndex)==1:
            #如果模块在线，则连接模块
             ret = modules.modConnect(modIndex)
             if ret == 1:
                #连接成功
                modStatus = 1
                #重新初始化温湿度模块
                sensor.reinit()

    # 1. 尝试初始化OLED，判断是否连接
    if modStatus==0:
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"OLED_Status": "关闭", "Display_Content": "无"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    # 2. 初始化成功，保存第一次数据（状态1）
    sensor_values = {"OLED_Status": "开启", "Display_Content": "初始化"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print("请观察 OLED 显示屏的状态变化")
    print(f"切换间隔: {display_interval} 秒")
    print("-" * 30)

    # 创建文字图像
    image1 = Image.new('1', (SCREEN_WIDTH, SCREEN_HEIGHT), "WHITE")
    draw = ImageDraw.Draw(image1)
    font = ImageFont.truetype('Font.ttf', 20)
    font10 = ImageFont.truetype('Font.ttf', 13)
    
    # 绘制边框
    draw.line([(0, 0), (127, 0)], fill=0)
    draw.line([(0, 0), (0, 63)], fill=0)
    draw.line([(0, 63), (127, 63)], fill=0)
    draw.line([(127, 0), (127, 63)], fill=0)
    
    # 绘制文本
    draw.text((10, 10), 'Happy New Year', font=font10, fill=0)
    draw.text((26, 30), '新年快乐', font=font, fill=0)
    image1 = image1.rotate(180)
    
    # 创建图片图像
    image2 = Image.new('1', (SCREEN_WIDTH, SCREEN_HEIGHT), 255)
    bmp = Image.open('pic.bmp')
    image2.paste(bmp, (0, 10))
    image2 = image2.rotate(180)
    
    # 4. 开始循环显示
    while True:
        sensor.drawBitmap(0,0,128,64,image1)
        sensor_values = {"OLED_Status": "开启", "Display_Content": "文字"}
        _save_data(sensor_values, frequency, target_values, 1, 1, 1)
        time.sleep(display_interval)
        
        sensor.drawBitmap(0,0,128,64,image2)
        sensor_values = {"OLED_Status": "开启", "Display_Content": "图片"}
        _save_data(sensor_values, frequency, target_values, 1, 1, 1)
        time.sleep(display_interval)
    



# --------------------------------------------------------------
# 参数设置区
# --------------------------------------------------------------
if __name__ == '__main__':
    
    DISPLAY_INTERVAL = 2  # 显示切换间隔（秒）
    
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
    
    #初始化温湿度模块
    sensor = SSD1306Lcd(modIndex,SCL_PIN,SDA_PIN)

    try:
        run_oled(modules,sensor,DISPLAY_INTERVAL)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{DISPLAY_INTERVAL} s/次"
        target_values = {"OLED_Status": "-"}
        sensor_values = {"OLED_Status": "关闭", "Display_Content": "无"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序已停止")
    
    finally:
        sensor.uninit()
        modules.modDisconnect(modIndex)
        modules.uninit()
