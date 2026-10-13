import ctypes
import time
from SensorModule import *
from NoiseSensor import *
# --------------------------------------------------------------
# 系统核心功能模块

SLEEP_TIME = 1  # 采集间隔时间（秒）
NOISE_TARGET_VALUE = 50  # 噪声目标值（分贝）
modIndex = 11  # 模块地址

# --------------------------------------------------------------


# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0


#模块有一个可用串口通道，2
com_index = 2
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

def _save_data(sensor_values, frequencies, target_values):
    """保存传感器数据到文件并通过 UDP 发送"""
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.join(current_dir, 'student_data')
    file_path = os.path.join(data_dir, 'student_data.json')

    os.makedirs(data_dir, exist_ok=True)

    data = {
        "Name": "NoiseSensor",
        "Answer": sensor_values,
        "Target_Value": target_values,
        "Output_Frequency": frequencies,
        "Status": {
            "Connection_Status": 1,
            "Communication_Status": 1,
            "Output_Status": 1
        }
    }
    print(data)

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
    print("传感器数据保存成功")
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
    # 定义继电器模块，模块编号位5
    controller = NoiseSensor(modIndex,com_index)

    try:
        print("程序正在运行......")
        print("请观察操作台上执行模块的状态变化")
        while True:
            #01 02 00 00 00 00 78 0A
            readbuffer = (ctypes.c_ubyte * 8)()
            buffer = (ctypes.c_ubyte * 8)()
            buffer[0] = 0x01
            buffer[1] = 0x02
            buffer[2] = 0x00
            buffer[3] = 0x00
            buffer[4] = 0x00
            buffer[5] = 0x00
            buffer[6] = 0x78
            buffer[7] = 0x0A
            ret = controller.WriteReadHexData(8,readbuffer,8,buffer,1)

            if ret > 0:
                decibel = readbuffer[3]
                sensor_values = {"noise_decibel": decibel}
                target_values = {"NoiseSensor": NOISE_TARGET_VALUE}
                frequencies = f"{SLEEP_TIME} s/次"
                _save_data(sensor_values, frequencies,target_values)
                
            else:
                print("读分贝值失败")
            
            time.sleep(SLEEP_TIME)
    
    except KeyboardInterrupt:
        # 如果出现键盘中断（Ctrl+C），执行清理工作
        print("Ctrl+C detected. Cleaning up RS232 and exiting...")  # 打印提示消息
        controller.uninit();
        modules.modDisconnect(5)
        modules.uninit()
        exit(0)  # 退出程序
    finally:
        # 确保在退出时清理 GPIO 口，以防止程序异常退出
        controller.uninit();
        modules.modDisconnect(5)
        modules.uninit()
