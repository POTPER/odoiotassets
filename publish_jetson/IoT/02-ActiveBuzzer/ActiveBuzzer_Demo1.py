# -*- coding: utf-8 -*-
"""
有源蜂鸣器模块演示程序
实现蜂鸣器短鸣效果
"""
import time
import json
import os
import socket
import math

from UdpPackage import UdpPackage
from SensorModule import *
from PWMController import *
# --------------------------------------------------------------
# 系统核心功能模块

BEEP_DURATION = 0.2   # 蜂鸣持续时间（秒）
BEEP_INTERVAL = 0.1   # 蜂鸣间隔时间（秒）
LOOP_DELAY = 5        # 循环间隔时间（秒）
modIndex = 2  # 模块地址

# --------------------------------------------------------------



# 传感器名称常量
SENSOR_NAME = "ActiveBuzzer"

# 蜂鸣器引脚定义（BOARD 模式）
PIN_BUZZER = 12  # J41_BOARD_PIN35

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0


#模块状态，0：不在线，1：在线
modStatus = 0


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
    
    # 构建数据结构
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


def buzzer_on():
    global modStatus,modIndex
    """打开蜂鸣器"""
    ret = smartSensorlib.PwmSetDuty(modIndex, 0, 1, 1000)
    if (ret < 0 ):
            print("连接断开，正在重连")
            ret = modules.modConnect(modIndex)
            if ret == 1:
                print("重连成功")
                ret = smartSensorlib.PwmSetDuty(modIndex, 0, 1, 1000)
    ret = smartSensorlib.PwmStart(modIndex, 1, 0)
    if (ret < 0 ):
            print("连接断开，正在重连")
            ret = modules.modConnect(modIndex)
            if ret == 1:
                print("重连成功")
                ret = smartSensorlib.PwmStart(modIndex, 1, 0)
def buzzer_off():
    global modStatus,modIndex
    """关闭蜂鸣器"""
    ret = smartSensorlib.PwmSetDuty(modIndex, 0, 1, 0)
    if (ret < 0 ):
            print("连接断开，正在重连")
            ret = modules.modConnect(modIndex)
            if ret == 1:
                print("重连成功")
                ret = smartSensorlib.PwmSetDuty(modIndex, 0, 1, 0)
    ret = smartSensorlib.PwmStart(modIndex, 1, 0)


def buzzer_init():
    global modStatus,modIndex
    """初始化蜂鸣器 GPIO，返回是否成功"""
    try:
        ret = smartSensorlib.PWNMInit(modIndex, 0, PIN_BUZZER, 1, 0, 10, 1000)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        return True
    except Exception as e:
        print(f"蜂鸣器初始化失败: {e}")
        return False


def buzzer_cleanup():
    """清理 GPIO"""
    try:
        ret = smartSensorlib.PwmSetDuty(modIndex, 0, 1, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.PwmStart(modIndex, 1, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.PwmStop(modIndex, 1, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
    except:
        pass


def run_buzzer(beep_duration, beep_interval, loop_delay):
    """运行蜂鸣器循环"""
    frequency = f"{loop_delay} s/次"
    target_values = {"Buzzer_Status": "-"}
    if modStatus==0:
         # 初始化失败，发送状态0，程序退出
        sensor_values = {"Buzzer_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)  # 等待UDP发送完成
        print("设备未连接，程序退出")
        return
    # 1. 尝试初始化GPIO，判断是否连接
    if not buzzer_init():
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"Buzzer_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)  # 等待UDP发送完成
        print("设备未连接，程序退出")
        return
    
    # 2. 初始化成功，保存第一次数据（状态1）
    sensor_values = {"Buzzer_Status": "关闭"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print("请观察蜂鸣器的状态变化")
    print(f"循环间隔: {loop_delay} 秒")
    print("-" * 30)
    
    # 3. 开始循环控制蜂鸣器
    try:
        while True:
            # 短鸣2声
            buzzer_on()
            sensor_values = {"Buzzer_Status": "开启"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
            time.sleep(beep_duration)
            
            buzzer_off()
            sensor_values = {"Buzzer_Status": "关闭"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
            time.sleep(beep_interval)
            
            buzzer_on()
            sensor_values = {"Buzzer_Status": "开启"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
            time.sleep(beep_duration)
            
            buzzer_off()
            sensor_values = {"Buzzer_Status": "关闭"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
            
            time.sleep(loop_delay)
    
    except Exception as e:
        # 运行过程中出错，发送状态0
        print(f"检测到设备异常: {e}")
        sensor_values = {"Buzzer_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)  # 等待UDP发送完成
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
    
    try:
        run_buzzer(BEEP_DURATION, BEEP_INTERVAL, LOOP_DELAY)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{LOOP_DELAY} s/次"
        target_values = {"Buzzer_Status": "-"}
        sensor_values = {"Buzzer_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)  # 等待UDP发送完成
        print("程序已停止")
    
    finally:
        buzzer_cleanup()
