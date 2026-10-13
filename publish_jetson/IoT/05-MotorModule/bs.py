import ctypes
import time
from SensorModule import *
from MotorController import *
import signal
import time
import sys
# --------------------------------------------------------------
# 系统核心功能模块（无需修改）
# --------------------------------------------------------------
modIndex = 5

# 传感器名称常量
SENSOR_NAME = "MotorModule"


# UDP 通信配置
UDP_DEST_ADDR = ('127.0.0.1', 8088)
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


def motor_on(controller):
    """打开电机"""
    controller.SetDuty(0, 0)
    controller.SetDuty(1, 1023)
    controller.Start(0)
    controller.Start(1)


def motor_off(controller):
    """关闭电机"""
    controller.SetDuty(0, 0)
    controller.SetDuty(1, 0)
    controller.Start(0)
    controller.Start(1)


def run_motor(controller,on_time, loop_delay):
    """运行电机循环"""
    
    frequency = f"{loop_delay} s/次"
    target_values = {"Motor_Status": "-"}
    
    
    print("程序正在运行...")
    print("请观察电机模块的状态变化")
    print(f"循环间隔: {loop_delay} 秒")
    print("-" * 30)
    
    motor_on(controller)
    
    # 3. 开始循环控制电机
    try:
        while True:
            motor_off(controller)
            
            time.sleep(loop_delay)
            
            # 开启电机
            motor_on(controller)
            print("电机开启")
            sensor_values = {"Motor_Status": "开启"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
            time.sleep(on_time)
            
            # 关闭电机
            motor_off(controller)
            print("电机关闭")
            sensor_values = {"Motor_Status": "关闭"}
            _save_data(sensor_values, frequency, target_values, 1, 1, 1)
    
    except Exception as e:
        motor_off(controller)
        print(f"检测到设备异常: {e}")
        sensor_values = {"Motor_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序停止")


def graceful_shutdown(signum, frame):
    global controller,modIndex
    print("recv kill event")
    motor_off(controller)
    modules.modDisconnect(modIndex)
    modules.uninit()
    sys.exit(0)



# --------------------------------------------------------------
# 参数设置区
# --------------------------------------------------------------
if __name__ == '__main__':
    
    MOTOR_ON_TIME = 5   # 电机运行时间（秒）
    LOOP_DELAY = 5       # 循环间隔时间（秒）
    # 注册信号处理器
    signal.signal(signal.SIGTERM, graceful_shutdown)
    # 也可以捕获 SIGINT (Ctrl+C)，让行为一致
    signal.signal(signal.SIGINT, graceful_shutdown)
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
    
    controller = MotorController(modIndex)
    
    try:
        run_motor(controller,MOTOR_ON_TIME, LOOP_DELAY)
    
    except KeyboardInterrupt:
        # 用户打断程序，发送状态0
        print("\n用户中断程序")
        motor_off(controller)
        frequency = f"{LOOP_DELAY} s/次"
        target_values = {"Motor_Status": "-"}
        sensor_values = {"Motor_Status": "关闭"}
        _save_data(sensor_values, frequency, target_values, 0, 0, 0)
        time.sleep(1.5)
        print("程序已停止")
    
    finally:
        motor_off(controller)
        controller.Stop(0)
        controller.Stop(1)
        modules.modDisconnect(modIndex)
        modules.uninit()
