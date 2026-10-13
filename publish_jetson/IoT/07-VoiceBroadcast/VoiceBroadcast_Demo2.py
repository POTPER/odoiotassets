import ctypes
import time
from SensorModule import *
from VoiceSensor import *

# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id = 0

# 传感器名称常量
SENSOR_NAME = "VoiceBroadcast"

TX_PIN = 22
RX_PIN = 23

#模块状态，0：不在线，1：在线
modStatus = 0

#模块有一个可用串口通道，2
com_index = 2
#模块放置位置
modIndex = 7
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
def voice_init(sensor):

    try:
        sensor.init()
        print("语音播报模块初始化完成")
        return True
    except Exception as e:
        print(f"语音播报模块初始化失败: {e}")
        return False


def voice_cleanup(sensor):
    sensor.uninit()

def run_voice(sensor,volume, sleep_time,str):
    """运行语音播报"""
    frequency = "手动控制"
    
    target_values = {"Voice_Status": "-"}
    
    if modStatus==0:
         # 初始化失败，发送状态0，程序退出
        sensor_values = {"Voice_Status": "关闭", "Action": "无"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    # 1. 尝试初始化语音模块，判断是否连接
    if not voice_init(sensor):
        # 初始化失败，发送状态0，程序退出
        sensor_values = {"Voice_Status": "关闭", "Action": "无"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("设备未连接，程序退出")
        return
    
    # 2. 初始化成功，保存第一次数据（状态1）
    sensor_values = {"Voice_Status": "关闭", "Action": "初始化"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    print("程序正在运行...")
    print("请观察语音播报模块的状态变化")
    print("-" * 30)
    
    # 3. 设置音量
    
    print(f"设置音量: {VOLUME}")
    #发送”<V>”+音量等级 设置音量播报，可设置1-4级音量，设置音量为3。系统默认为4，为最高音量。
    #settingstr=f"<V>{volume}"
    #sSettingStrGbk = bytes(settingstr, 'gbk')
    #controller.SendAscIIData(sSettingStrGbk,len(sSettingStrGbk))
    #sensor_values = {"Voice_Status": "关闭", "Action": f"设置音量{volume}"}
    #_save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    # 4. 播放音频
    print("播放")
    controller.SendAscIIData(str,len(str))
    sensor_values = {"Voice_Status": "开启", "Action": "播放"}
    _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    time.sleep(sleep_time)

if __name__ == "__main__":
    SLEEP_TIME = 3  # 采集间隔时间（秒）
    VOLUME = 4  # 声音大小
    text = "无线模块组网完成"
    text_gbk = bytes(text, 'gbk')
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
    controller = VoiceSensor(modIndex,com_index,TX_PIN,RX_PIN)

    try:
       run_voice(controller,VOLUME, SLEEP_TIME,text_gbk)
    
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
