#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
# 标准库负责参数读取、驱动调用、计时、文件归档及状态上报。
import argparse
import ctypes
import csv
import json
import math
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

# ==================== 02 用户设置 ====================

# ==================== 考试任务：终端温度监测 ====================
# 某施工项目开展智能建造环境监测试点。材料存放区的木质模板、金属配件存在受潮变形、锈蚀等风险，
# 项目部拟自动采集环境温湿度，为现场巡查和问题追溯提供参考。
#
# 本次调试定名为“终端温度监测”，监测点为“材料存放区01”。每2秒采集一次温湿度数据，
# 连续采集5次有效数据。温度高于25℃时标记“温度超标”，等于或低于25℃时视为温度正常。
# 每次采集均保存采集时间、监测位置、测量结果及温度判别标记。
#
# 现由你使用实训箱中的温湿度传感器完成模拟调试，按上述要求配置程序，检查采集间隔、数据记录及温度判别结果，
# 完成后提交本次CSV运行记录和同次程序源码，供复核归档。

# ====================================================
# TODO：阅读顶部任务背景，填写实验信息并设置温度目标值、监测间隔。
# 当前示例可以运行，请检查配置及监测结果；湿度目标值和程序逻辑沿用现有设置。
# 完成5次有效采集后按Ctrl+C停止，提交同次CSV及自动保存的Python源码。

experiment_info = {
    "考试编号": "考号",
    "项目名称": "温湿度监测",
    "项目位置": "物联实训箱01",
}

# >>>>>>>>>>>>>>>>>>>> TODO：监测参数设置区 >>>>>>>>>>>>>>>>>>>>
degrees_sensor_target_value = 35  # 温度目标值，单位°C。
monitoring_interval = 1  # 监测间隔，秒/次。
# <<<<<<<<<<<<<<<<<<<< TODO：设置区结束 <<<<<<<<<<<<<<<<<<<<<<

# ==================== 03 系统配置 ====================
# 以下为湿度判别、实训箱驱动与通信参数，本次任务通常无需修改。
humidity_sensor_target_value = 80  # 湿度目标值，单位 %RH
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

# ==================== 04 实验信息与 CSV 历史记录 ====================
# 默认保存到当前用户桌面/成果输出/考试编号/项目名称，每次运行新建CSV及同次入口源码。
# CSV记录实际测量值、目标值和超标标记；离线及读取失败的数据不参与超标判断。

def safe_path_component(text):

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip(' .')
    cleaned = cleaned[:80].rstrip(' .') or "未命名"
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if cleaned.split('.')[0].upper() in reserved:
        cleaned = "_" + cleaned
    return cleaned


def find_desktop():

    home = Path.home()
    if os.name == "nt":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
            return Path(os.path.expandvars(value))
        except OSError:
            pass
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        try:
            config = (config_home / "user-dirs.dirs").read_text(encoding="utf-8")
            for line in config.splitlines():
                if line.strip().startswith("XDG_DESKTOP_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    value = value.replace("${HOME}", str(home)).replace("$HOME", str(home))
                    desktop = Path(value).expanduser()
                    if desktop.is_absolute():
                        return desktop
        except OSError:
            pass
    if (home / "桌面").is_dir():
        return home / "桌面"
    return home / "Desktop"


def exceeding_targets(temperature, humidity, online=True):

    if not online:
        return []
    exceeded = []
    if temperature > degrees_sensor_target_value:
        exceeded.append("温度超标")
    if humidity > humidity_sensor_target_value:
        exceeded.append("湿度超标")
    return exceeded


class CsvExperimentLog:

    FIELD_NAMES = [
        "采集时间", "模块编号",
        "温度(°C)", "湿度(%RH)", "温度目标值(°C)",
        "湿度目标值(%RH)", "监测间隔(秒/次)", "数据状态", "超标项目", "错误信息",
    ]

    def __init__(self, experiment, module_index, output_root=None):

        self.experiment = dict(experiment)
        for field in self.experiment:
            if not isinstance(field, str) or not field.strip():
                raise ValueError("自定义字段名必须为非空字符串")
            if field.strip() in self.FIELD_NAMES:
                raise ValueError(f"自定义字段与系统列重名：{field}")
        self.field_names = [self.FIELD_NAMES[0], *self.experiment, *self.FIELD_NAMES[1:]]
        self.module_index = module_index

        root = Path(output_root).expanduser() if output_root is not None else find_desktop() / "成果输出"
        person = str(self.experiment.get("考试编号") or "未命名").strip() or "未命名"
        # 归档名称取自用户设置中的“项目名称”。
        project = str(self.experiment.get("项目名称") or "未命名实验").strip() or "未命名实验"
        folder = root / safe_path_component(person) / safe_path_component(project)
        folder.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now()
        start_date = started_at.strftime("%Y%m%d")
        start_clock = started_at.strftime("%H%M%S")
        sequence = 1

        while True:
            suffix = "" if sequence == 1 else f"_{sequence}"
            self.file_path = folder / f"{safe_path_component(project)}_{safe_path_component(person)}_{start_date}{suffix}_{start_clock}.csv"
            self.code_path = self.file_path.with_suffix(".py")
            # CSV 和代码快照使用同一主体名称，任一文件已存在都换用新序号。
            if self.code_path.exists():
                sequence += 1
                continue
            try:
                handle = self.file_path.open("x", encoding="utf-8-sig", newline="")
                break
            except FileExistsError:
                sequence += 1

        with handle:
            csv.writer(handle).writerow(self.field_names)
        print(f"CSV 保存位置：{self.file_path}", flush=True)
        self.save_source_code()

    def save_source_code(self):
        # 保存本次运行文件的完整源码，便于与 CSV 对照核验配置及程序逻辑。
        try:
            source_bytes = Path(__file__).resolve().read_bytes()
            with self.code_path.open("xb") as handle:
                handle.write(source_bytes)
        except OSError as error:
            print(f"运行代码保存失败：{error}", file=sys.stderr, flush=True)
            self.record_error("保存运行代码失败", error)
        else:
            print(f"运行代码保存位置：{self.code_path}", flush=True)

    @staticmethod
    def spreadsheet_text(text):

        if isinstance(text, str) and text.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + text
        return text

    def append(self, temperature, humidity, online, error_message="", status=None):

        exceeded = exceeding_targets(temperature, humidity, online)
        reading_status = "超标" if exceeded else "正常"
        if not online:
            reading_status = "离线或读取失败"
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            *[self.spreadsheet_text(value) for value in self.experiment.values()],
            self.module_index,
            round(temperature, 2) if online else "",
            round(humidity, 2) if online else "",
            degrees_sensor_target_value, humidity_sensor_target_value, monitoring_interval,
            status or reading_status,
            "、".join(exceeded),
            self.spreadsheet_text(error_message),
        ]

        with self.file_path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(row)

    def record_error(self, stage, error):

        message = f"{stage}：{type(error).__name__}: {error}"
        try:
            self.append(None, None, False, error_message=message, status="错误")
        except OSError as write_error:
            print(f"错误信息无法写入 CSV：{write_error}；原始错误：{message}",
                  file=sys.stderr, flush=True)


# ==================== 05 驱动加载 ====================

def load_driver():

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


# ==================== 06 模块连接管理 ====================

class SensorModule:


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


# ==================== 07 AHT20 硬件参数 ====================

AHT20_ADDR = 0x38
AHT20_SDA_PIN = 23
AHT20_SCL_PIN = 22
AHT20_RESOLUTION = 0x100000


# ==================== 08 温湿度采集 ====================

class AHT20:


    def __init__(self, module_index):
        self.module_index = module_index
        self.reinit()

    def reinit(self):

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


# ==================== 09 数据保存与 UDP 上报 ====================

class SensorDataOutput:


    def __init__(self, experiment, module_index, output_root=None, csv_log=None):
        self.csv_log = csv_log if csv_log is not None else CsvExperimentLog(experiment, module_index, output_root)
        self.file_path = DATA_PATH
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.group_id = 0

    @staticmethod
    def build_record(temperature, humidity, online):

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
            "Output_Frequency": f"{monitoring_interval} 秒/次",
            "Exceeding_Target": exceeding_targets(temperature, humidity, online),
        }

    def load_history(self):

        if not self.file_path.exists():
            return []
        try:
            history = json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return history if isinstance(history, list) else []

    @staticmethod
    def clean_history(history):

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

            targets = record.get("Target_Value")
            if isinstance(targets, dict):
                cleaned_record["Target_Value"] = {
                    key: value
                    for key, value in targets.items()
                    if key in ("degrees value", "humidity value")
                }
            if "Output_Frequency" in record:
                cleaned_record["Output_Frequency"] = record["Output_Frequency"]
            if isinstance(record.get("Exceeding_Target"), list):
                cleaned_record["Exceeding_Target"] = record["Exceeding_Target"]
            cleaned.append(cleaned_record)
        return cleaned

    def send_history(self, history):

        payload = json.dumps(history).encode("utf-8")
        self.group_id = (self.group_id + 1) % (1 << 32)
        packet_count = (len(payload) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE

        for packet_index in range(packet_count):
            start = packet_index * UDP_CHUNK_SIZE
            chunk = payload[start:start + UDP_CHUNK_SIZE]

            header_fields = (self.group_id, packet_count, packet_index, len(chunk))
            header = b"".join(value.to_bytes(4, "little") for value in header_fields)
            self.udp_socket.sendto(header + chunk, UDP_DESTINATION)

    def save(self, temperature, humidity, online, error_message=""):

        try:
            self.csv_log.append(temperature, humidity, online, error_message=error_message)
        except OSError as error:
            print(f"CSV 写入失败：{error}", file=sys.stderr, flush=True)

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


# ==================== 10 数据输出异常处理 ====================

def save_reading(output, temperature, humidity, online, error_message=""):

    try:
        output.save(temperature, humidity, online, error_message=error_message)
    except OSError as error:
        print("保存或发送数据失败：{}".format(error), file=sys.stderr, flush=True)
        output.csv_log.record_error("JSON 保存或 UDP 上报失败", error)


# ==================== 11 连接资源释放 ====================

def release_connection(modules, sensor, mod_index, csv_log):

    try:
        if sensor is not None:
            sensor.uninit()
    except (RuntimeError, OSError) as error:
        print("释放传感器失败：{}".format(error), file=sys.stderr)
        csv_log.record_error("释放传感器失败", error)
    try:
        modules.modDisconnect(mod_index)
    except (RuntimeError, OSError) as error:
        print("断开模块失败：{}".format(error), file=sys.stderr)
        csv_log.record_error("断开模块失败", error)


# ==================== 12 采集主流程 ====================

def run_sensor(experiment, mod_index=9, output_root=None):


    csv_log = CsvExperimentLog(experiment, mod_index, output_root)
    output = None
    modules = None
    sensor = None
    connected = False
    stage = "检查监测间隔"
    try:
        valid_interval = (
            isinstance(monitoring_interval, (int, float))
            and math.isfinite(monitoring_interval)
            and monitoring_interval > 0
        )
        if not valid_interval:
            raise RuntimeError("监测间隔 monitoring_interval 必须是有限的正数，单位秒/次")
        sampling_interval = monitoring_interval
        for name, target in (("温度", degrees_sensor_target_value), ("湿度", humidity_sensor_target_value)):
            if not isinstance(target, (int, float)) or not math.isfinite(target):
                raise RuntimeError(f"{name}目标值必须是有限数值")
        if sampling_interval < MEASUREMENT_WAIT_SECONDS:
            print("提示：监测间隔为设定值，实际间隔不短于至少 1 秒的硬件测量耗时。", flush=True)
        stage = "加载驱动"
        load_driver()
        stage = "初始化数据输出"
        output = SensorDataOutput(experiment, mod_index, output_root, csv_log=csv_log)
        stage = "初始化或扫描模块"
        modules = SensorModule()
        modules.startScanSensors()
        time.sleep(SCAN_WAIT_SECONDS)
        stage = "采集运行"
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
                exceeded = exceeding_targets(temperature, humidity)
                label = "、".join(exceeded) if exceeded else "正常"
                print(
                    f"温度：{temperature:.2f} °C    湿度：{humidity:.2f} %RH    状态：{label}",
                    flush=True,
                )
                save_reading(output, temperature, humidity, True)
            except (RuntimeError, OSError) as error:
                print("{}，稍后重试。".format(error), file=sys.stderr, flush=True)
                release_connection(modules, sensor, mod_index, csv_log)
                sensor = None
                connected = False

                save_reading(
                    output, 0, 0, False,
                    error_message=f"{type(error).__name__}: {error}",
                )
                time.sleep(max(1.0, sampling_interval))
                continue


            elapsed = time.monotonic() - started
            time.sleep(max(0.0, sampling_interval - elapsed))
    except KeyboardInterrupt:
        print("\n已停止采集。", flush=True)
    except Exception as error:

        csv_log.record_error(stage, error)
        raise
    finally:
        try:
            if modules is not None:
                release_connection(modules, sensor, mod_index, csv_log)
                modules.uninit()
        except Exception as error:
            csv_log.record_error("退出时释放驱动失败", error)
            raise
        finally:
            if output is not None:
                try:
                    output.close()
                except OSError as error:
                    csv_log.record_error("关闭 UDP 连接失败", error)
                    print(f"关闭 UDP 连接失败：{error}", file=sys.stderr)


# ==================== 13 命令行入口 ====================

def main(default_module=9):
    parser = argparse.ArgumentParser(
        description="温湿度教学实验：使用文件顶部的实验设置，自动创建目录并保存 CSV"
    )
    parser.add_argument("--module", type=int, default=default_module, help="模块地址")
    parser.add_argument("--output-dir", type=Path, help="保存根目录，默认当前用户桌面下的“成果输出”目录；其下按考试编号和项目名称建目录")
    args = parser.parse_args()
    try:
        if not isinstance(experiment_info, dict):
            raise ValueError("用户设置中的 experiment_info 必须是字典")
        experiment = dict(experiment_info)
        run_sensor(experiment, args.module, args.output_dir)
    except KeyboardInterrupt:
        print("\n已取消实验。")
        return 0
    except Exception as error:
        print(
            f"运行失败：{type(error).__name__}: {error}；请检查 CSV 错误记录及运行环境。",
            file=sys.stderr,
        )
        return 1
    return 0


# ==================== 14 程序启动 ====================
# 在本目录运行：python3 BRICS2026_Shandong_T1_Temp.py
# 先保存用户设置再启动，完成监测后按Ctrl+C停止并检查归档文件。
if __name__ == "__main__":
    sys.exit(main())
