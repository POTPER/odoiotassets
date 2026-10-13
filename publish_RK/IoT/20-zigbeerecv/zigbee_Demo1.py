import ctypes
import time
from queue import Queue
from threading import Thread,Lock
from SensorModule import *
from zigbeeSensor import *
from GpioController import *
from VoiceSensor import *
# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

# 传感器名称常量
SENSOR_NAME = "ZigbeeBroadcast"

TX_PIN = 22
RX_PIN = 23
RST_PIN = 25
#模块状态，0：不在线，1：在线
ModStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#模块放置位置
ModIndex = 14
recvMod = None

sendText = "hello\r\n"
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





def sensor_init():
    global sendMod,recvMod
    try:
        recvMod.init()
        print("模块初始化完成")
        return True
    except Exception as e:
        print(f"模块初始化失败: {e}")
        return False


def sensor_cleanup():
    global sendMod,recvMod
    sendMod.uninit()


def run_zigbee_recv(recvmod,sleep_time,str):
    frequency = f"{sleep_time} s/次"
    target_values = {"RecvStatus": 0}
    maximum_values = {"RecvStatus": 0}
    exceeding_limit_times = 3

    # 1. 尝试初始化语音模块，判断是否连接
    if not sensor_init():
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"Zigbee_Status": "失败"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    while True:
        print("start to recv")
        readbuffer = (ctypes.c_ubyte * 20)()
        ret = recvmod.readAsciiData(7,readbuffer,1)
        print(ret)
        if ret > 0 :
            buffer_str = bytes(readbuffer).decode('ascii', errors='ignore').rstrip('\x00')
            print("zigbee recv data:")
            if sendText== buffer_str:
                sensor_values = {"RecvStatus": 1}
                _save_data(sensor_values, frequency, target_values, 1, 1, 1)
            else:
                sensor_values = {"RecvStatus": buffer_str}
                _save_data(sensor_values, frequency, target_values, 1, 1, 1)
        else:
            sensor_values = {"RecvStatus": "接收超时"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
        time.sleep(5)

if __name__ == "__main__":
    SLEEP_TIME = 5  # 发送间隔时间（秒）
    
    text_gbk = bytes(sendText, 'gbk')

    # 模块初始化
    modules = SensorModule()
    # 开始搜索模块
    modules.startScanSensors()
    # 连接发送模块
    ret = modules.modConnect(ModIndex)

    if ret<=0:
        ModStatus=0
    else:
        ModStatus=1

    # 连接接收模块
    ret = modules.modConnect(ModIndex)

    if ret<=0:
        recvModStatus=0
    else:
        recvModStatus=1
    recvMod = ZigbeeSensor(ModIndex,com_index,TX_PIN,RX_PIN,RST_PIN)
    try:
       run_zigbee_recv(recvMod,SLEEP_TIME,text_gbk)
    
    except KeyboardInterrupt:
        # 如果出现键盘中断（Ctrl+C），执行清理工作
        print("Ctrl+C detected. Cleaning up RS232 and exiting...")  # 打印提示消息

        modules.modDisconnect(ModIndex)
        modules.uninit()
        exit(0)  # 退出程序
    finally:
        # 确保在退出时清理 GPIO 口，以防止程序异常退出
        recvMod.uninit();
        modules.modDisconnect(ModIndex)
        modules.uninit()
