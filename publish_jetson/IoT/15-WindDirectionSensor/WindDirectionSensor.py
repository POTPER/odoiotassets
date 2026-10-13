# -*- coding: utf-8 -*-
import time
import json
from datetime import datetime
import os

from UdpPackage import *
import socket
import  math
from RS232Module import *


dest_addr = ('127.0.0.1', 8088)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

max_packet_size = 1000
global_id = 0

READ_TIMER_OUT = 5

class WindDirection:
    def __init__(self, modIndex,comIndex,txpin,rxpin):
        self.modIndex = modIndex
        self.comIndex = comIndex
        self.txpin = txpin
        self.rxpin = rxpin
        
        ret = smartSensorlib.RS232Init(self.modIndex, self.comIndex, self.txpin, self.rxpin, 9600, 0, 8,1)
        if ret <0 :
            raise ValueError("mod disconnect")
        
    def uninit(self):
        smartSensorlib.RS232Uninit(self.modIndex, self.comIndex)    
    def send_msginfo(self,msginfo_bytes):
        packets = self.getUdpPackages(msginfo_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr)
            
    def getUdpPackages(self,bytes_data):
        global global_id
        global_id += 1 # µÝÔöÈ«ŸÖ±äÁ¿
        packets = []
        length=len(bytes_data)
        num_packets = math.ceil(length/ max_packet_size)
        for i in range(num_packets):
            start = i * max_packet_size
            end = min(start + max_packet_size, len(bytes_data))
            packet = UdpPackage(global_id, num_packets, i, end - start, bytes_data[start:end])

            packets.append(packet)
        return packets

    def SendHexDataAndReadData(self, senddata, size,readdata,readdatasize,timeout):
        ret = smartSensorlib.RS232ModWriteReadHexData(self.modIndex, self.comIndex, readdatasize,readdata,size,senddata,timeout)
        return ret
    def get_wind_speed(self):
            send_buffer = (ctypes.c_ubyte * 8)()
            recv_buffer = (ctypes.c_ubyte * 9)()
            send_buffer[0] = 0x01
            send_buffer[1] = 0x03
            send_buffer[2] = 0x00
            send_buffer[3] = 0x00
            send_buffer[4] = 0x00
            send_buffer[5] = 0x02
            send_buffer[6] = 0xC4
            send_buffer[7] = 0x0B
            for i in (1,2,3):
                ret = self.SendHexDataAndReadData(send_buffer,8,recv_buffer,9,READ_TIMER_OUT)
                if ret < 0:
                    raise ValueError("mod disconnect")
                elif ret>0:
                    wind_velocity_value = []
                    combined_value = (recv_buffer[3]<<8)|recv_buffer[4]
                    wind_velocity_value.append(combined_value)
                    return wind_velocity_value
            return None
    def get_wind_direction(self):
        send_buffer = (ctypes.c_ubyte * 8)()
        recv_buffer = (ctypes.c_ubyte * 9)()
        send_buffer[0] = 0x01
        send_buffer[1] = 0x03
        send_buffer[2] = 0x00
        send_buffer[3] = 0x00
        send_buffer[4] = 0x00
        send_buffer[5] = 0x02
        send_buffer[6] = 0xC4
        send_buffer[7] = 0x0B
        for i in (1,2,3):
            ret = self.SendHexDataAndReadData(send_buffer,8,recv_buffer,9,READ_TIMER_OUT)
            if ret < 0:
                raise ValueError("mod disconnect")
            elif ret>0:
                wind_direction_value = []
                combined_value = (recv_buffer[5]<<8)|recv_buffer[6]
                wind_direction_value.append(combined_value)
                return wind_direction_value
        return None

# 数据保存程序
    def save_sensor_data(self, sensor_data, date, address):
        # 获取当前执行脚本的当前路径
        current_directory = os.path.dirname(__file__)

        # 构建目标文件的完整路径
        file_path = os.path.join(current_directory, 'student_data', 'student_data.json')

        # 确保'student_data'文件夹存在
        if not os.path.exists('student_data'):
            os.makedirs('student_data')   

        try:
            with open(file_path, 'r') as file:
                existing_data = json.load(file)
        except FileNotFoundError:
            existing_data = []

        if len(existing_data) > 5:
            existing_data = existing_data[-5:]

        with open(file_path, 'w') as file:
            json.dump(existing_data, file, indent=4)

    def add_sensor_status_data(self, data, connection_status, communication_status, output_status):
        # 添加传感器状态数据
        if "Status" not in data:
            data["Status"] = {}
        data["Status"]["Connection_Status"] = connection_status
        data["Status"]["Communication_Status"] = communication_status
        data["Status"]["Output_Status"] = output_status

    def save_sensor_data_to_file(self, sensor_values, frequencies, target_values, maximum_values, exceeding_limit_times, sensor_name, status_connection, status_communication, status_output):
               # 获取当前执行脚本的当前路径
        current_directory = os.path.dirname(__file__)

        # 构建目标文件的完整路径
        file_path = os.path.join(current_directory, 'student_data', 'student_data.json')

        # 确保'student_data'文件夹存在
        if not os.path.exists('student_data'):
            os.makedirs('student_data')   
       # 保存传感器数据至文件
        data = {}
        data["Exceeding_Limit_Times"] = exceeding_limit_times
        data["Name"] = sensor_name
        self.add_sensor_status_data(data, status_connection, status_communication, status_output)
        data["Answer"] = sensor_values
        data["Target_Value"] = target_values
        data["Maximum_Value"] = maximum_values
        data["Output_Frequency"] = frequencies


        existing_data = []
        try:
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                with open(file_path, 'r') as file:
                    existing_data = json.load(file)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            existing_data = []

        if len(existing_data) >= 5:
            existing_data = existing_data[1:]
        existing_data.append(data)

        with open(file_path, 'w') as file:
            json.dump(existing_data, file, indent=4)
        self.send_msginfo(bytes(json.dumps(existing_data),encoding='utf-8'))
        print("Sensor data saved successfully.")
