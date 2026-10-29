import ctypes
import time
import socket
import os
import json
import math
from UdpPackage import *

dest_addr = ("127.0.0.1", 8088)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

global_id = 0
max_packet_size = 1000


# 传感器模块信息
class tModInf(ctypes.Structure):
    _fields_ = [
        ("nModType", ctypes.c_int),
        ("nModState", ctypes.c_int),
        ("servport", ctypes.c_int),
        ("sModIP", ctypes.c_char * 64),
        ("sModVer", ctypes.c_char * 64),
    ]


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")


# I2C初始化
# 参数1：模块地址
# 参数2：SCL pin 序号
# 参数3：SDA PIN 序号
# 参数4：I2C传感器地址长度
# 参数5：通讯速率
# 参数6：传感器I2C地址
smartSensorlib.I2CInit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.I2CInit.restype = ctypes.c_int


# I2C读数据
# 参数1：模块地址
# 参数2：addr
# 参数3：addrbytenum
# 参数3：bytenum字节数
# 参数4：data
smartSensorlib.I2CRead.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.I2CRead.restype = ctypes.c_int

# I2C写数据
# 参数1：模块地址
# 参数2：addr
#参数3：addrbytenum
# 参数4：bytenum字节数
# 参数5：data
smartSensorlib.I2CWrite.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.I2CWrite.restype = ctypes.c_int

smartSensorlib.I2CUninit.argtypes = [ctypes.c_int]
smartSensorlib.I2CUninit.restype = ctypes.c_int


AHT20_ADDR = 0x38  # 设备ID寄存器地址

AHT20_ADDR_LENGHT = 7  # AHT20地址长度

# AHT20 pin脚定义
AHT20_SDA_PIN = 23
AHT20_SCL_PIN = 22

AHT20_READ_ADDR = 0x71  # AHT20读地址，(0x38<<1)|0x01
AHT20_WRITE_ADDR = 0x70  # AHT20写地址,(0x38<<1)|0x0
AHT20_MASTER_FREQ_HZ = 100000  # I2C速率
AHT20_CMD_CALIBRATION = 0xBE
AHT20_CMD_CALIBRATION_ARG0 = 0x08
AHT20_CMD_CALIBRATION_ARG1 = 0x00
AHT20_CMD_TRIGGER = 0xAC
AHT20_CMD_TRIGGER_ARG0 = 0x33
AHT20_CMD_TRIGGER_ARG1 = 0x00
AHT20_CMD_RESET = 0xBA
AHT20_CMD_STATUS = 0x71
AHT20_RESOLUTION = 0x100000


class AHT20(object):
    def __init__(self, modIndex):
        self.modIndex = modIndex
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器

        print("start to read init aht20 mod")
        # 初始化I2C
        ret = smartSensorlib.I2CInit(
            self.modIndex,
            AHT20_SCL_PIN,
            AHT20_SDA_PIN,
            AHT20_ADDR_LENGHT,
            AHT20_MASTER_FREQ_HZ,
            AHT20_ADDR,
        )
        if ret <0 :
            raise ValueError("mod disconnect")
    def reinit(self):
        ret = smartSensorlib.I2CInit(
            self.modIndex,
            AHT20_SCL_PIN,
            AHT20_SDA_PIN,
            AHT20_ADDR_LENGHT,
            AHT20_MASTER_FREQ_HZ,
            AHT20_ADDR,
        )
        if ret <0 :
            raise ValueError("mod disconnect")
    def readTempAndHumi(self):
        # 初始化I2C之后需要等待1秒钟
        # time.sleep(1)
        # 开始测量
        buffer = (ctypes.c_ubyte * 3)()
        buffer[0] = AHT20_CMD_TRIGGER_ARG0
        buffer[1] = AHT20_CMD_TRIGGER_ARG1

        ret = smartSensorlib.I2CWrite(self.modIndex, AHT20_CMD_TRIGGER,1, 2,0, buffer)

        if ret < 0:
            return 0,0,0
        time.sleep(1)
        # 读取测量结果
        regdata = (ctypes.c_ubyte * 7)()

        ret = smartSensorlib.I2CRead(self.modIndex, AHT20_READ_ADDR,1, 7,0, regdata)

        if ret<0:
            raise ValueError("mod disconnect")

        HumiRaw = regdata[1]
        HumiRaw = (HumiRaw << 8) | regdata[2]
        HumiRaw = (HumiRaw << 4) | ((regdata[3] & 0xF0) >> 4)
        humi = HumiRaw / AHT20_RESOLUTION * 100
        TempRaw = regdata[3] & 0x0F
        TempRaw = (TempRaw << 8) | regdata[4]
        TempRaw = (TempRaw << 8) | regdata[5]
        temp = TempRaw / AHT20_RESOLUTION * 200 - 50
        print("temp=")
        print(temp)
        print("humi=")
        print(humi)
        return 1,temp, humi

    def uninit(self):
        ret= smartSensorlib.I2CUninit(self.modIndex)
        if ret<0:
            raise ValueError("mod disconnect")
    def send_msginfo(self, msginfo_bytes):
        packets = self.getUdpPackages(msginfo_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr)

    def add_sensor_status_data(
        self, data, connection_status, communication_status, output_status
    ):
        # 添加传感器状态数据
        if "Status" not in data:
            data["Status"] = {}
        data["Status"]["Connection_Status"] = connection_status
        data["Status"]["Communication_Status"] = communication_status
        data["Status"]["Output_Status"] = output_status

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

    def save_sensor_data_to_file(
        self,
        sensor_values,
        frequencies,
        target_values,
        maximum_values,
        exceeding_limit_times,
        sensor_name,
        status_connection,
        status_communication,
        status_output,
    ):
        # 获取当前执行脚本的当前路径
        current_directory = os.path.dirname(__file__)

        # 构建目标文件的完整路径
        file_path = os.path.join(current_directory, "student_data", "student_data.json")

        # 确保'student_data'文件夹存在
        if not os.path.exists("student_data"):
            os.makedirs("student_data")
        # 保存传感器数据至文件
        data = {}
        data["Exceeding_Limit_Times"] = exceeding_limit_times
        data["Name"] = sensor_name
        self.add_sensor_status_data(
            data, status_connection, status_communication, status_output
        )
        data["Answer"] = sensor_values
        data["Target_Value"] = target_values
        data["Maximum_Value"] = maximum_values
        data["Output_Frequency"] = frequencies

        existing_data = []
        try:
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                with open(file_path, "r") as file:
                    existing_data = json.load(file)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            existing_data = []

        if len(existing_data) >= 5:
            existing_data = existing_data[1:]
        existing_data.append(data)

        with open(file_path, "w") as file:
            json.dump(existing_data, file, indent=4)
        self.send_msginfo(bytes(json.dumps(existing_data), encoding="utf-8"))
        print("Sensor data saved successfully.")
