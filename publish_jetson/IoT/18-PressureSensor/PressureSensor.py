# -*- coding: utf-8 -*-
"""
压力传感器驱动模块
提供ADC数据读取、滤波处理及数据保存功能
"""
import time
import json
import os
import socket
import math

from UdpPackage import UdpPackage
from SensorModule import *
import ctypes


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
# --------------------------------------------------------------
# UDP 通信配置
# --------------------------------------------------------------
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0


# adcinit
#参数1：模块地址
#参数2：通道：，值【0：GPIO32,1:GPIO33]
#参数3：原始转换位宽，0：ADC_BITWIDTH9,1:ADC_BITWIDTH10,2:ADC_BITWIDTH11,3:ADC_BITWIDTH12,4:ADC_BITWIDTH13,
smartSensorlib.AdcInit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int
]
smartSensorlib.AdcInit.restype = ctypes.c_int
# adcuninit
#参数1：模块地址
#参数2：通道：，值【0：GPIO32,1:GPIO33]
smartSensorlib.AdcUnInit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.AdcUnInit.restype = ctypes.c_int

# adc read
#参数1：模块地址
#参数2：通道：，值【0：GPIO32,1:GPIO33]
#参数3：电压值，point
smartSensorlib.AdcRead.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int)
]
smartSensorlib.AdcRead.restype = ctypes.c_int

m1_20g = 20
m2_2kg= 2000
#下面时测量值
VOLTAGE1_20g=3100
VOLTAGE2_2kG = 0

class Pressure:
    """压力传感器类"""
    
    def __init__(self, modIndex,chnl,bitwidth):
        self.modIndex = modIndex
        self.chnl = chnl
        self.bitwidth = bitwidth
        ret = smartSensorlib.AdcInit(self.modIndex,self.chnl,self.bitwidth)
    def uninit(self):
        ret = smartSensorlib.AdcUnInit(self.modIndex,self.chnl)

    # --------------------------------------------------------------
    # UDP 通信方法
    # --------------------------------------------------------------
    def _send_udp(self, data_bytes):
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

    #FSR402传感器的有效测量范围是20g~1kg，在有效区间内，电压值和FSR402的电阻的倒数成正比，
    #没有压力时，FSR402电压近乎无穷大，压力越大，阻值越小
    #在本测试用例，我们只测量有效范围内的压力值
    #假设线性关系公式：m = uXk+b,则k = (m2-m1)/(u2-u1),b=m1-((m2-m1)/(u2-u1))*u1
    def _compute_pressure_value(self, voltage):
        if voltage > VOLTAGE1_20g:
            return 0
        elif voltage<VOLTAGE2_2kG:
            return 0
        
        k = (m2_2kg-m1_20g)/(VOLTAGE2_2kG-VOLTAGE1_20g)
        b = m1_20g - k*VOLTAGE1_20g
        pressure = k*voltage + b

        return pressure
    # --------------------------------------------------------------
    # 数据读取方法,读取的是原始的电压分压值
    # --------------------------------------------------------------
    def _read_single_voltage(self):
        """单次读取原始压力值（内部方法）"""
        voltage = ctypes.c_int()

        ret = smartSensorlib.AdcRead(self.modIndex,self.chnl,ctypes.byref(voltage))
        if ret < 0:
                return None
        
        return voltage.value
    def _get_sensor_data_raw(self, samples=3):
        """获取原始压力数据（滑动平均滤波）
        
        Args:
            samples: 采样次数，默认3次取平均
        
        原理说明：
        ADC采集存在随机噪声，单次读数会有波动。通过多次采样取平均值，
        可以有效抑制随机噪声，提高测量稳定性。采样次数越多越稳定，
        但响应速度会变慢，3次是精度和速度的平衡点。
        """
        readings = []
        for _ in range(samples):
            val = self._read_single_voltage()
            if val is not None:
                readings.append(val)
            time.sleep(0.02)  # 采样间隔20ms
        voltage_agv  = sum(readings) / len(readings)

        pressure = self._compute_pressure_value(voltage_agv)
        return pressure

    def get_sensor_data(self, dead_zone=0.5):
        """获取去皮后的压力数据（带滤波和死区处理）
        
        Args:
            dead_zone: 死区阈值，小于此值的读数视为0（默认0.5）
        
        Returns:
            float: 压力值，保留2位小数
        
        原理说明：
        1. 滑动平均滤波：多次采样取平均，消除随机噪声
        2. 去皮偏移：减去初始零点偏移量
        3. 死区处理：微小波动（如0.1~0.3）视为零，避免显示抖动
        
        死区阈值设为0.5是因为：
        - ADC噪声约±0.1~0.3，设0.5可完全覆盖
        - 对于压力测量，0.5的误差在可接受范围内
        """
        pressure = self._get_sensor_data_raw()
        
        if pressure is not None:
            #pressure = pressure - self._pressure_offset
            # 死区处理：小于阈值的波动视为0
            if abs(pressure) < dead_zone:
                pressure = 0
            # 保留2位小数，避免浮点数精度问题
            pressure = round(pressure, 2)
            print(f"CH5的当前压力值: {pressure}")
        
        return pressure

    # --------------------------------------------------------------
    # 数据保存方法
    # --------------------------------------------------------------
    def _add_status(self, data, connection, communication, output):
        """添加传感器状态信息"""
        data["Status"] = {
            "Connection_Status": connection,
            "Communication_Status": communication,
            "Output_Status": output,
        }

    def save_sensor_data_to_file(self, sensor_values, frequencies, target_values,
                                  maximum_values, exceeding_limit_times, sensor_name,
                                  status_connection, status_communication, status_output):
        """保存传感器数据到文件并通过 UDP 发送"""
        current_dir = os.path.dirname(__file__)
        data_dir = os.path.join(current_dir, 'student_data')
        file_path = os.path.join(data_dir, 'student_data.json')
        
        # 确保目录存在
        os.makedirs(data_dir, exist_ok=True)
        
        # 构建数据
        data = {
            "Exceeding_Limit_Times": exceeding_limit_times,
            "Name": sensor_name,
            "Answer": sensor_values,
            "Target_Value": target_values,
            "Maximum_Value": maximum_values,
            "Output_Frequency": frequencies,
        }
        self._add_status(data, status_connection, status_communication, status_output)
        
        # 读取现有数据
        existing_data = []
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            try:
                with open(file_path, 'r') as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = []
        
        # 保留最近 5 条
        if len(existing_data) >= 5:
            existing_data = existing_data[1:]
        existing_data.append(data)
        
        # 写入文件
        with open(file_path, 'w') as f:
            json.dump(existing_data, f, indent=4)
        
        # UDP 发送
        self._send_udp(json.dumps(existing_data).encode('utf-8'))
        print("压力数据保存成功")
