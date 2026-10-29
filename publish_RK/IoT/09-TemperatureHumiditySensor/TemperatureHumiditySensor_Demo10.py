# 温湿度采集程序：读取 AHT20，保存 JSON，并通过 UDP 上报。
# 运行：python3 TemperatureHumiditySensor_Demo10.py；按 Ctrl+C 停止。

# ==================== 01 标准库导入 ====================
# 提供命令行参数、驱动调用、JSON 处理、网络通信和计时功能。
import argparse
import ctypes
import json
import math
import socket
import sys
import time
from pathlib import Path

# ==================== 02 用户设置 ====================
# 在此修改温度目标值、湿度目标值和监测间隔。
# 目标值仅用于保存和上报，不改变传感器实际读数。
degrees_sensor_target_value = 0  # 温度目标值，单位 °C
humidity_sensor_target_value = 0  # 湿度目标值，单位 %RH
sleep_time = 1  # 监测间隔，单位秒；1 表示目标为每秒采集一次

# ==================== 03 文件路径与通信常量 ====================
# 指定驱动和数据文件位置、UDP 接收地址、历史数量及等待时间。
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000  # 每个 UDP 分包的数据长度，不含 16 字节包头
HISTORY_SIZE = 5
SENSOR_NAME = "TempHumitySensor"  # 保留原协议中的名称拼写
SCAN_WAIT_SECONDS = 2
MEASUREMENT_WAIT_SECONDS = 1

smartSensorlib = None

# ==================== 04 驱动加载 ====================
# 加载原厂动态库，声明 Python 调用底层驱动时使用的参数类型。
def load_driver():
    # 加载脚本同目录的驱动，并声明原厂函数的参数类型。
    global smartSensorlib
    smartSensorlib = ctypes.CDLL(str(DRIVER_PATH))

    smartSensorlib.SmartSensorLibInit.argtypes = []
    smartSensorlib.SmartSensorLibUnInit.argtypes = []
    smartSensorlib.startScanSensors.argtypes = []
    smartSensorlib.startScanSensors.restype = ctypes.c_int
    for name in ("connectToMod", "disconnectToMod", "isModReady"):
        function = getattr(smartSensorlib, name)
        function.argtypes = [ctypes.c_int]
        function.restype = ctypes.c_int

    smartSensorlib.I2CInit.argtypes = [ctypes.c_int] * 6
    smartSensorlib.I2CInit.restype = ctypes.c_int
    for name in ("I2CRead", "I2CWrite"):
        function = getattr(smartSensorlib, name)
        function.argtypes = [ctypes.c_int] * 5 + [ctypes.POINTER(ctypes.c_ubyte)]
        function.restype = ctypes.c_int
    smartSensorlib.I2CUninit.argtypes = [ctypes.c_int]
    smartSensorlib.I2CUninit.restype = ctypes.c_int


# ==================== 05 模块连接管理 ====================
# 负责初始化驱动、发现模块、检查在线状态、连接和断开模块。
class SensorModule:
    # 封装模块发现、连接和释放；方法名沿用原厂示例。

    def __init__(self):
        smartSensorlib.SmartSensorLibInit()

    def startScanSensors(self):
        return smartSensorlib.startScanSensors()

    def isModReady(self, modIndex):
        return smartSensorlib.isModReady(modIndex)

    def modConnect(self, modIndex):
        return smartSensorlib.connectToMod(modIndex)

    def modDisconnect(self, modIndex):
        return smartSensorlib.disconnectToMod(modIndex)

    def uninit(self):
        smartSensorlib.SmartSensorLibUnInit()


# ==================== 06 AHT20 硬件参数 ====================
# 定义 I²C 设备地址、SDA/SCL 引脚及温湿度原始值的换算基数。
AHT20_ADDR = 0x38
AHT20_SDA_PIN = 23
AHT20_SCL_PIN = 22
AHT20_RESOLUTION = 0x100000


# ==================== 07 温湿度采集 ====================
# 初始化 I²C，发送测量指令，等待结果并换算出温度和相对湿度。
class AHT20:
    # 触发一次测量，并将原始数据换算为温度和相对湿度。

    def __init__(self, module_index):
        self.module_index = module_index
        self.reinit()

    def reinit(self):
        # 保留原厂示例的地址长度、引脚、速率和调用参数。
        result = smartSensorlib.I2CInit(
            self.module_index,
            AHT20_SCL_PIN,
            AHT20_SDA_PIN,
            7,  # 原厂驱动使用的地址长度参数
            100000,  # I²C 通信速率，Hz
            AHT20_ADDR,
        )
        if result < 0:
            raise RuntimeError("温湿度传感器初始化失败")

    def readTempAndHumi(self):
        command = (ctypes.c_ubyte * 2)(0x33, 0x00)
        result = smartSensorlib.I2CWrite(self.module_index, 0xAC, 1, 2, 0, command)
        if result < 0:
            raise RuntimeError("发送测量指令失败")

        # 保留原有的 1 秒测量等待，避免改变硬件时序。
        time.sleep(MEASUREMENT_WAIT_SECONDS)
        data = (ctypes.c_ubyte * 7)()
        result = smartSensorlib.I2CRead(self.module_index, 0x71, 1, 7, 0, data)
        if result < 0:
            raise RuntimeError("读取温湿度失败")

        humidity_raw = (data[1] << 12) | (data[2] << 4) | (data[3] >> 4)
        temperature_raw = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
        humidity = humidity_raw / AHT20_RESOLUTION * 100
        temperature = temperature_raw / AHT20_RESOLUTION * 200 - 50
        return 1, temperature, humidity

    def uninit(self):
        return smartSensorlib.I2CUninit(self.module_index)


# ==================== 08 数据保存与 UDP 上报 ====================
# 生成包含读数、状态、目标值及频率的记录，保留最近五条并分包发送。
class SensorDataOutput:
    # 保存最近五条记录，并按照原协议分包发送到本机服务。

    def __init__(self):
        self.file_path = DATA_PATH
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.group_id = 0

    @staticmethod
    def build_record(temperature, humidity, online):
        # 生成一条记录：读数、状态、目标值和监测间隔。
        status = int(online)
        return {
            "Name": SENSOR_NAME,
            "Status": {
                "Connection_Status": status,
                "Communication_Status": status,
                "Output_Status": status,
            },
            "Answer": {
                "degrees_value": round(temperature, 2),
                "humidity_value": round(humidity, 2),
            },
            "Target_Value": {
                "degrees value": degrees_sensor_target_value,
                "humidity value": humidity_sensor_target_value,
            },
            "Output_Frequency": f"{sleep_time} s/次",
        }

    def load_history(self):
        # 文件不存在、内容损坏或格式不符时，从空列表开始。
        if not self.file_path.exists():
            return []
        try:
            history = json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return history if isinstance(history, list) else []

    @staticmethod
    def clean_history(history):
        # 检查最近四条记录，保留有效温湿度字段，为新记录留位。
        cleaned = []
        for record in history[-(HISTORY_SIZE - 1):]:
            if not isinstance(record, dict):
                continue
            readings = record.get("Answer")
            if not isinstance(readings, dict):
                continue

            cleaned_record = {
                "Name": record.get("Name", SENSOR_NAME),
                "Status": record.get("Status", {}),
                "Answer": {
                    key: value
                    for key, value in readings.items()
                    if key in ("degrees_value", "humidity_value")
                },
            }
            # 保留旧记录自身的设置，不用当前设置覆盖历史数据。
            targets = record.get("Target_Value")
            if isinstance(targets, dict):
                cleaned_record["Target_Value"] = {
                    key: value
                    for key, value in targets.items()
                    if key in ("degrees value", "humidity value")
                }
            if "Output_Frequency" in record:
                cleaned_record["Output_Frequency"] = record["Output_Frequency"]
            cleaned.append(cleaned_record)
        return cleaned

    def send_history(self, history):
        # 发送 JSON 列表；包头为四个小端、无符号 32 位整数。
        payload = json.dumps(history).encode("utf-8")
        self.group_id = (self.group_id + 1) % (1 << 32)
        packet_count = (len(payload) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE

        for packet_index in range(packet_count):
            start = packet_index * UDP_CHUNK_SIZE
            chunk = payload[start:start + UDP_CHUNK_SIZE]
            # 包头顺序：消息组编号、分包总数、分包序号、数据长度。
            header_fields = (self.group_id, packet_count, packet_index, len(chunk))
            header = b"".join(value.to_bytes(4, "little") for value in header_fields)
            self.udp_socket.sendto(header + chunk, UDP_DESTINATION)

    def save(self, temperature, humidity, online):
        # 先更新本地 JSON，再发送同一份历史记录。
        record = self.build_record(temperature, humidity, online)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        history = self.clean_history(self.load_history())
        history.append(record)

        self.file_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        self.send_history(history)

    def close(self):
        self.udp_socket.close()


# ==================== 09 数据输出异常处理 ====================
# 统一调用保存和发送功能，输出失败时提示错误并继续采集。
def save_reading(output, temperature, humidity, online):
    # 输出失败时报告错误，下一轮仍继续采集。
    try:
        output.save(temperature, humidity, online)
    except OSError as error:
        print("保存或发送数据失败：{}".format(error), file=sys.stderr, flush=True)


# ==================== 10 连接资源释放 ====================
# 依次释放传感器和模块连接，用于断线重试和程序退出。
def release_connection(modules, sensor, mod_index):
    # 释放传感器和模块；其中一步失败时仍继续清理。
    try:
        if sensor is not None:
            sensor.uninit()
    except (RuntimeError, OSError) as error:
        print("释放传感器失败：{}".format(error), file=sys.stderr)
    try:
        modules.modDisconnect(mod_index)
    except (RuntimeError, OSError) as error:
        print("断开模块失败：{}".format(error), file=sys.stderr)


# ==================== 11 采集主流程 ====================
# 检查监测间隔，扫描并连接模块，循环采集、上报，断线后重试。
def run_sensor(mod_index=9):
    # 扫描模块、循环采集；断线重连，Ctrl+C 后释放资源。
    valid_interval = (
        isinstance(sleep_time, (int, float))
        and math.isfinite(sleep_time)
        and sleep_time > 0
    )
    if not valid_interval:
        raise RuntimeError("监测间隔 sleep_time 必须是有限的正数")
    load_driver()

    output = SensorDataOutput()
    modules = None
    sensor = None
    connected = False
    try:
        modules = SensorModule()
        modules.startScanSensors()
        time.sleep(SCAN_WAIT_SECONDS)
        while True:
            started = time.monotonic()
            try:
                if not connected:
                    if modules.isModReady(mod_index) != 1:
                        raise RuntimeError("模块 {} 尚未在线".format(mod_index))
                    if modules.modConnect(mod_index) <= 0:
                        raise RuntimeError("模块连接失败")
                    sensor = AHT20(mod_index)
                    connected = True
                    print("模块 {} 已连接".format(mod_index), flush=True)

                result, temperature, humidity = sensor.readTempAndHumi()
                if result != 1:
                    raise RuntimeError("读取温湿度失败")
                print(
                    f"温度：{temperature:.2f} °C    湿度：{humidity:.2f} %RH",
                    flush=True,
                )
                save_reading(output, temperature, humidity, True)
            except (RuntimeError, OSError) as error:
                print("{}，稍后重试。".format(error), file=sys.stderr, flush=True)
                release_connection(modules, sensor, mod_index)
                sensor = None
                connected = False
                # 保留原程序离线时上报零值及离线状态的行为。
                save_reading(output, 0, 0, False)
                time.sleep(max(1.0, sleep_time))
                continue

            # 间隔包含测量耗时；硬件测量至少等待 1 秒，实际周期可能更长。
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, sleep_time - elapsed))
    except KeyboardInterrupt:
        print("\n已停止采集。", flush=True)
    finally:
        try:
            if modules is not None:
                release_connection(modules, sensor, mod_index)
                modules.uninit()
        finally:
            output.close()


# ==================== 12 命令行入口 ====================
# 解析模块地址参数并启动采集，启动失败时给出错误提示。
def main(default_module=9):
    parser = argparse.ArgumentParser(
        description="读取、保存并发送温湿度，支持目标值和监测频率设置"
    )
    parser.add_argument("--module", type=int, default=default_module, help="模块地址")
    args = parser.parse_args()
    try:
        run_sensor(args.module)
    except (RuntimeError, OSError) as error:
        print(
            f"启动失败：{error}；请确认 Linux 平台、驱动库及硬件连接。",
            file=sys.stderr,
        )
        return 1
    return 0


# ==================== 13 程序启动 ====================
# 仅在直接运行本文件时启动主流程。
if __name__ == "__main__":
    sys.exit(main())
