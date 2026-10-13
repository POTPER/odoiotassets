import ctypes
import time
import socket
import os
import json
import math
from UdpPackage import *
import socket
import math
import config
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


#ADS1115 I2C 地址 (ADDR 引脚接 GND 时为 0x48)
ADS1115_ADDRESS_GND = 0x48
ADS1115_ADDRESS_VDD =  0x49

# ADS1115 寄存器地址
ADS1115_REG_CONVERSION = 0x00  # 转换结果寄存器
ADS1115_REG_CONFIG     = 0x01  # 配置寄存器
ADS1115_REG_LO_THRESH  = 0x02  # 低阈值寄存器
ADS1115_REG_HI_THRESH  = 0x03  # 高阈值寄存器

# 配置寄存器位定义
ADS1115_CONFIG_OS_MASK  =  0x8000  # 操作状态/启动转换
ADS1115_CONFIG_OS_SINGLE=  0x8000  # 开始单次转换
ADS1115_CONFIG_OS_BUSY =   0x0000  # 正在转换中

# MUX: 输入通道选择
ADS1115_CONFIG_MUX_DIFF_0_1= 0x0000  #AIN0 - AIN1 (差分)
ADS1115_CONFIG_MUX_DIFF_0_3 =0x1000  # AIN0 - AIN3
ADS1115_CONFIG_MUX_DIFF_1_3 =0x2000  # AIN1 - AIN3
ADS1115_CONFIG_MUX_DIFF_2_3 =0x3000  # AIN2 - AIN3
ADS1115_CONFIG_MUX_SINGLE_0 =0x4000  #AIN0 (单端)
ADS1115_CONFIG_MUX_SINGLE_1= 0x5000  # AIN1
ADS1115_CONFIG_MUX_SINGLE_2= 0x6000  # AIN2
ADS1115_CONFIG_MUX_SINGLE_3= 0x7000  # AIN3

# PGA: 满量程范围
ADS1115_CONFIG_PGA_6_144V  =0x0000  # ±6.144V
ADS1115_CONFIG_PGA_4_096V  =0x0200  # ±4.096V
ADS1115_CONFIG_PGA_2_048V  =0x0400  # ±2.048V (默认)
ADS1115_CONFIG_PGA_1_024V = 0x0600  # ±1.024V
ADS1115_CONFIG_PGA_0_512V  =0x0800  # ±0.512V
ADS1115_CONFIG_PGA_0_256V  =0x0A00  # ±0.256V

# MODE: 工作模式
ADS1115_CONFIG_MODE_CONTIN =0x0000  # 连续转换模式
ADS1115_CONFIG_MODE_SINGLE =0x0100  # 单次转换模式 (默认)

# DR: 数据速率
ADS1115_CONFIG_DR_8SPS    =0x0000  # 8 SPS
ADS1115_CONFIG_DR_16SPS   =0x0020  # 16 SPS
ADS1115_CONFIG_DR_32SPS  = 0x0040  # 32 SPS
ADS1115_CONFIG_DR_64SPS   =0x0060  # 64 SPS
ADS1115_CONFIG_DR_128SPS  =0x0080  # 128 SPS (默认)
ADS1115_CONFIG_DR_250SPS  =0x00A0  # 250 SPS
ADS1115_CONFIG_DR_475SPS  =0x00C0  # 475 SPS
ADS1115_CONFIG_DR_860SPS  =0x00E0  # 860 SPS

# 比较器模式
ADS1115_CONFIG_COMP_MODE_TRAD =0x0000  # 传统比较器
ADS1115_CONFIG_COMP_MODE_WIND =0x0010  # 窗口比较器
ADS1115_CONFIG_COMP_POL_ACTLO =0x0000  # 低电平有效
ADS1115_CONFIG_COMP_POL_ACTHI =0x0008  # 高电平有效
ADS1115_CONFIG_COMP_LAT_NON   =0x0000  # 非锁存
ADS1115_CONFIG_COMP_LAT_LATCH =0x0004  # 锁存
ADS1115_CONFIG_COMP_QUE_1     =0x0000  # 1次转换后触发
ADS1115_CONFIG_COMP_QUE_2     =0x0001  # 2次转换后触发
ADS1115_CONFIG_COMP_QUE_4     =0x0002  # 4次转换后触发
ADS1115_CONFIG_COMP_QUE_DIS   =0x0003  # 禁用比较器

ADS1115_ADDR_LENGHT = 7  # AHT20地址长度
ADS1115_MASTER_FREQ_HZ = 100000  # I2C速率



class SmokeSensor(object):
    def __init__(self, modIndex,sclpin,sdapin):
        self.modIndex = modIndex
        self.sclpin = sclpin
        self.sdapin = sdapin
        self.config_reg  = ADS1115_CONFIG_OS_SINGLE | ADS1115_CONFIG_MUX_SINGLE_0 | ADS1115_CONFIG_PGA_4_096V | ADS1115_CONFIG_MODE_SINGLE |ADS1115_CONFIG_DR_128SPS | ADS1115_CONFIG_COMP_QUE_DIS

        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器
        # 初始化I2C
        smartSensorlib.I2CInit(
            self.modIndex,
            self.sclpin,
            self.sdapin,
            ADS1115_ADDR_LENGHT,
            ADS1115_MASTER_FREQ_HZ,
            ADS1115_ADDRESS_GND,
        )
        self.ads1115Config()
    def reinit(self):
        smartSensorlib.I2CInit(
            self.modIndex,
            self.sclpin,
            self.sdapin,
            ADS1115_ADDR_LENGHT,
            ADS1115_MASTER_FREQ_HZ,
            ADS1115_ADDRESS_GND,
        )
        self.ads1115Config()
    def ads1115Config(self):
        buffer = (ctypes.c_ubyte * 3)()
        buffer[0] =ADS1115_REG_CONFIG
        buffer[1] = (self.config_reg>>8)&0xff
        buffer[2] = (self.config_reg)&0xff
        ret = smartSensorlib.I2CWrite(self.modIndex, ADS1115_REG_CONFIG,1, 3,0, buffer)
        if ret < 0:
            raise ValueError("mod disconnect")
    def get_lsb_voltage(self,pga):
        if (pga & 0x0E00 == ADS1115_CONFIG_PGA_6_144V) :
            return 187.5
        elif (pga & 0x0E00 == ADS1115_CONFIG_PGA_4_096V): 
            return 125.5
        elif (pga & 0x0E00 == ADS1115_CONFIG_PGA_2_048V):
            return 62.5
        elif (pga & 0x0E00 == ADS1115_CONFIG_PGA_1_024V):
            return 31.25
        elif (pga & 0x0E00 == ADS1115_CONFIG_PGA_0_512V):
            return 15.625
        elif (pga & 0x0E00 == ADS1115_CONFIG_PGA_0_256V):
            return 7.8125
        return 0.0
    def singleReadVol(self):
        config = (self.config_reg & ~ADS1115_CONFIG_MODE_CONTIN) | ADS1115_CONFIG_MODE_SINGLE | ADS1115_CONFIG_OS_SINGLE
        buffer = (ctypes.c_ubyte * 3)()
        buffer[0] = ADS1115_REG_CONFIG
        buffer[1] = (self.config_reg>>8)&0xff
        buffer[2] = (self.config_reg)&0xff
        ret = smartSensorlib.I2CWrite(self.modIndex, ADS1115_REG_CONFIG,1, 3,0, buffer)
        if ret < 0:
            raise ValueError("mod disconnect")
        time.sleep(1)
        regdata = (ctypes.c_ubyte * 2)()
        ret = smartSensorlib.I2CRead(self.modIndex, ADS1115_REG_CONVERSION,1, 2,0, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        raw_value = (regdata[0] << 8) | regdata[1];
        lsb_uv =self.get_lsb_voltage(self.config_reg)
        voltage = raw_value * lsb_uv / 1000000.0-0.05;
        return round(voltage,2)
    
    def uninit(self):
        smartSensorlib.I2CUninit(self.modIndex)

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

    def send_data(self, command_frame, max_retry=3):
        retry = 0
        complete_data = b''
        while retry < max_retry:
            self.ser.write(bytearray(command_frame))
            # 持续读取数据直到收到完整的消息
            while True:
                received_data = self.ser.read(1)  # 一次读取一个字节
                if not received_data:
                    break  # 如果没有数据，退出循环
                complete_data += received_data
                if received_data == b'V':
                    # 如果收到'V'，则认为接收到完整消息
                    break
            if b'V' in complete_data:
                # 如果接收到'V'，则完成消息接收
                break
            retry += 1
            time.sleep(1)  # 等待一段时间后重试
        if b'V' in complete_data:
            return complete_data
        else:
            print(f"{self.name} 没有接收到完整的消息")
            return None

    def get_sensor_data(self):
       
        try:
            # 将字符串转换为浮点数
            value = self.singleReadVol()
            # 转换为真实烟雾浓度值
            # 传感器特性：无烟雾时低电压(0.1-0.3V)，有烟雾时高电压(~5V)
            # 检测范围：300-10000 ppm
            if value <= config.VOLTAGE_BASELINE:
                # 低于基准电压，认为无烟雾，显示最小检测值以下
                smoke_concentration = 0
            else:
                # 线性映射：电压从基准值到最大值 -> 浓度从最小值到最大值
                smoke_concentration = config.SMOKE_CONC_MIN + ((value - config.VOLTAGE_BASELINE) / (config.VOLTAGE_MAX - config.VOLTAGE_BASELINE)) * (config.SMOKE_CONC_MAX - config.SMOKE_CONC_MIN) / config.SMOKE_GAIN
                # 限制在有效范围内
                smoke_concentration = max(config.SMOKE_CONC_MIN, min(smoke_concentration, config.SMOKE_CONC_MAX))
            print(f"ADC电压值: {value}V, 烟雾浓度值: {smoke_concentration}")
        except ValueError as e:
            raise ValueError("mod disconnect")
        
        return smoke_concentration

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

    def save_sensor_data_to_file(self, sensor_values, frequencies, target_values, maximum_values, exceeding_limit_times, sensor_names, status_connection, status_communication, status_output):
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
        data["Name"] = sensor_names
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
