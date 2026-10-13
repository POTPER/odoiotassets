import time
import socket
import os
import json
import math
from UdpPackage import *
from PWMController import *

INA_PIN = 12
INB_PIN = 13

from UdpPackage import *

dest_addr = ("127.0.0.1", 8088)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

global_id = 0
max_packet_size = 1000


class MotorController(object):
    def __init__(self, modIndex):
        self.existing_data = []
        self.modIndex = modIndex
       
        ret = smartSensorlib.PWNMInit(self.modIndex, 0, INA_PIN, 1, 0, 10, 1000)
        if ret <0 :
            raise ValueError("mod disconnect")
        ret = smartSensorlib.PWNMInit(self.modIndex, 1, INB_PIN, 1, 1, 10, 1000)
        if ret <0 :
            raise ValueError("mod disconnect")
    def SetDuty(self, chnl, duty):
        ret = smartSensorlib.PwmSetDuty(self.modIndex, chnl, 1, duty)
        if ret <0 :
            raise ValueError("mod disconnect")
    def Start(self, chnl):
        ret = smartSensorlib.PwmStart(self.modIndex, 1, chnl)
        if ret <0 :
            raise ValueError("mod disconnect")
    def Stop(self, chnl):
        ret = smartSensorlib.PwmStop(self.modIndex, 1, chnl)
        if ret <0 :
            raise ValueError("mod disconnect")
    def send_msginfo(self, msginfo_bytes):
        packets = self.getUdpPackages(msginfo_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr)

    def getUdpPackages(self, bytes_data):
        global global_id
        global_id += 1  # 递增全局变量
        packets = []
        length = len(bytes_data)
        num_packets = math.ceil(length / max_packet_size)
        for i in range(num_packets):
            start = i * max_packet_size
            end = min(start + max_packet_size, len(bytes_data))
            packet = UdpPackage(
                global_id, num_packets, i, end - start, bytes_data[start:end]
            )

            packets.append(packet)
        return packets

    def save_sensor(self):
        data_to_save = 1  # 要保存的数据
        # 获取当前执行脚本的当前路径
        current_directory = os.path.dirname(__file__)

        # 构建目标文件的完整路径
        file_path = os.path.join(current_directory, "student_data", "student_data.json")

        # 确保'student_data'文件夹存在，如果不存在则创建
        if not os.path.exists("student_data"):
            os.makedirs("student_data")
        # 保存传感器数据到 JSON 文件中

        # 检查文件是否存在且可写
        if os.path.exists(file_path) and os.access(file_path, os.W_OK):
            self.existing_data = []  # 初始化 existing_data 变量
            try:
                with open(file_path, "r") as file:
                    self.existing_data = json.load(file)
            except json.JSONDecodeError:
                self.existing_data = []  # 如果JSON格式错误，则将数据清空

        # 如果现有数据条目数量超过 5，仅保留最新的 5 条数据
        if len(self.existing_data) >= 5:
            self.existing_data = self.existing_data[1:]

        # 将新数据添加到数据列表中
        self.existing_data.append(data_to_save)

        # 将更新后的数据重新写入到 JSON 文件中
        with open(file_path, "w") as file:
            json.dump(self.existing_data, file, indent=4)
        self.send_msginfo(bytes(json.dumps(self.existing_data), encoding="utf-8"))
        print("Number saved successfully.")  # 打印保存成功的消息
