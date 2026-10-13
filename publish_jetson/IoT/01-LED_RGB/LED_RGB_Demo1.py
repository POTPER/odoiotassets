import ctypes
import time
import socket
import os
import json
import math
from SensorModule import *

# GPIO 输出初始化
smartSensorlib.GpioOutInit.argtypes = [ctypes.c_int, ctypes.c_int]
smartSensorlib.GpioOutInit.restype = ctypes.c_int
# 设置GPIO电平
smartSensorlib.GpioSetLevel.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
smartSensorlib.GpioSetLevel.restype = ctypes.c_int

from UdpPackage import UdpPackage
# --------------------------------------------------------------
# 系统核心功能模块

SLEEP_TIME = 2  # LED 切换间隔（秒）
modIndex = 1  # 模块地址

# --------------------------------------------------------------



# 传感器名称常量
SENSOR_NAME = "LED_RGB"

# LED 引脚定义（BOARD 模式）
PIN_LED_R = 23  #  - 红色
PIN_LED_G = 25  #  - 绿色
PIN_LED_B = 22  #  - 蓝色

#模块状态
modStatus = 0
LED_PINS = [PIN_LED_R, PIN_LED_G, PIN_LED_B]

# UDP 通信配置
UDP_DEST_ADDR = ("127.0.0.1", 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0


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
            _global_packet_id, num_packets, i, end - start, data_bytes[start:end]
        )
        _udp_socket.sendto(packet.toNetBytes(), UDP_DEST_ADDR)


def _save_data(
    sensor_values,
    frequency,
    target_values,
    status_connection,
    status_communication,
    status_output,
):
    """保存传感器数据到文件并通过 UDP 发送"""
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.join(current_dir, "student_data")
    file_path = os.path.join(data_dir, "student_data.json")

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
            "Output_Status": status_output,
        },
    }

    existing_data = []
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        try:
            with open(file_path, "r") as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            print("11111")
            existing_data = []

    if len(existing_data) >= 5:
        existing_data = existing_data[1:]
    existing_data.append(data)

    with open(file_path, "w") as f:
        json.dump(existing_data, f, indent=4)

    _send_udp(json.dumps(existing_data).encode("utf-8"))
    print("数据保存成功")


def led_on(pin):
    global PIN_LED_R,PIN_LED_G,PIN_LED_B,modIndex
    """点亮指定 LED

    Args:
        pin: LED 引脚号（PIN_LED_R, PIN_LED_G, PIN_LED_B）
    """
    if pin == 0:
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_R, 1)
    elif pin == 1:
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_G, 1)
    else:
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_B, 1)
    return ret

def led_off(pin):
    global PIN_LED_R,PIN_LED_G,PIN_LED_B,modIndex
    """熄灭指定 LED

    Args:
        pin: LED 引脚号
    """
    ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_R, 0)
    if ret <0:
        return ret
    ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_G, 0)
    if ret<0:
        return ret
    ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_B, 0)
    if ret<0:
        return ret

    return 1

def led_init():
    global PIN_LED_R,PIN_LED_G,PIN_LED_B,modIndex
    """初始化 LED GPIO，返回是否成功"""
    try:
        ret = smartSensorlib.GpioOutInit(modIndex, PIN_LED_R)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.GpioOutInit(modIndex, PIN_LED_G)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.GpioOutInit(modIndex, PIN_LED_B)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_R, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_G, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret =smartSensorlib.GpioSetLevel(modIndex, PIN_LED_B, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        return True
    except Exception as e:
        print(f"LED 初始化失败: {e}")
        return False


def led_cleanup():
    global PIN_LED_R,PIN_LED_G,PIN_LED_B,modIndex
    """清理 GPIO"""
    try:
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_R, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_G, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
        ret = smartSensorlib.GpioSetLevel(modIndex, PIN_LED_B, 0)
        if (ret < 0 ):
            raise ValueError("mod disconnect")
    except:
        pass


def run_led(sleep_time):
    global modStatus,modIndex,modStatus
    """运行LED循环"""
    frequency = f"{sleep_time} s/次"
    target_values = {"LED_Color": "RGB循环"}

     # 1. 检查模块状态
    if modStatus==0:
        # 初始化失败，发送状态0，程序退出
        frequency = f"{SLEEP_TIME} s/次"
        target_values = {"LED_Color": "-"}
        sensor_values = {"LED_Color": "未知", "LED_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        print("设备未连接，程序退出")
        return
    
    # 1. 尝试初始化GPIO，判断是否连接
    if not led_init():
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"LED_Color": "未知", "LED_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)  # 等待UDP发送完成
        print("设备未连接，程序退出")
        return

    # 2. 初始化成功，保存第一次数据（状态1）
    color_names = ["红色", "绿色", "蓝色"]
    current_led = 0
    sensor_values = {"LED_Color": color_names[current_led], "LED_Status": "开启"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)

    print("程序正在运行...")
    print("请观察 RGB LED 的颜色变化")
    print(f"切换间隔: {sleep_time} 秒")
    print("-" * 30)

    # 3. 开始循环控制LED
    while True:
        # 点亮当前 LED
        ret = led_on(current_led)
        if ret < 0:
            # 初始化失败，发送状态0，程序退出
            frequency = f"{SLEEP_TIME} s/次"
            target_values = {"LED_Color": "-"}
            sensor_values = {"LED_Color": "未知", "LED_Status": "关闭"}
            _save_data(sensor_values, frequency, target_values, 0, 0, 0)
            print("设备断开连接，程序退出")
            return
        print(f"当前颜色: {color_names[current_led]}")

        # 保存当前状态
        sensor_values = {
            "LED_Color": color_names[current_led],
            "LED_Status": "开启",
        }
        _save_data(sensor_values, frequency, target_values, 1, 1, 1)

        time.sleep(sleep_time)

        # 熄灭当前 LED，切换到下一个
        ret = led_off(current_led)
        if ret < 0:
            # 初始化失败，发送状态0，程序退出
            frequency = f"{SLEEP_TIME} s/次"
            target_values = {"LED_Color": "-"}
            sensor_values = {"LED_Color": "未知", "LED_Status": "关闭"}
            _save_data(sensor_values, frequency, target_values, 0, 0, 0)
            print("设备断开连接，程序退出")
            return
        current_led = (current_led + 1) % len(LED_PINS)




if __name__ == "__main__":

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
        run_led(SLEEP_TIME)

    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        frequency = f"{SLEEP_TIME} s/次"
        target_values = {"LED_Color": "-"}
        sensor_values = {"LED_Color": "未知", "LED_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)  # 等待UDP发送完成
        print("程序已停止")

    finally:
        led_cleanup()
