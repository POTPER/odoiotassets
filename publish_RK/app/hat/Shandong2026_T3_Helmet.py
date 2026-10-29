#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
# 标准库负责计时、线程、队列、图像缓冲区访问与网络通信。
import ctypes
import csv
import logging
import math
import os
import re
import socket
import struct
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Thread, Lock, Event

# OpenCV 与 NumPy 处理图像，配套接口调用实训箱的模型、设备及原有通信协议。
import cv2
import numpy as np
from CHYoloModule import *
from SensorModule import *
from SensorModule import smartSensorlib as sensor_driver
from UdpPackage import *

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==================== 02 用户设置 ====================

# ==================== 考试任务：安全帽佩戴检测 ====================
# 某施工项目开展智能建造安全管理试点，在“施工入口01”设置安全帽识别终端，
# 并安排“安全帽佩戴检测”调试工作。终端通过检测框和蜂鸣器辅助工作人员辨识人员佩戴情况，
# 项目部约定以纯绿色框标识安全帽，以纯红色框标识未戴帽头部。
#
# 单人测试时，未戴帽人员能够触发提示，戴帽人员不会触发。但多人通行时，
# 画面虽已识别出两类人员，蜂鸣器却保持静音。项目部要求排查这一漏报：
# 只要存在未戴帽人员，就应发出提示，不受其他人员佩戴情况影响；
# 仅有戴帽人员或画面无人时保持静音。
#
# 现由你使用实训箱完成模拟调试，现场管理人员将分别查看无人、仅戴帽、仅未戴帽及两类人员同时出现的表现。
# 确认检测框颜色符合约定、混合场景不再漏报后，将运行记录与同次程序归档，供后续复核。

# ====================================================
# 请阅读顶部任务背景，在本分区调整检测配色及联动判断，并验证运行效果。
# !!!!!!!!!!!!!!!!!!!! 检查项：请查找 TODO 1 和 TODO 2 !!!!!!!!!!!!!!!!!!!!
# TODO 1：按任务要求设置安全帽、未戴帽头部的检测框及标签背景颜色。
# TODO 2：检查并调整示例判断，解决两类人员同时出现时的提示漏报，并逐项验证四种场景。
# 当前示例可以运行；请依据任务要求检查并完善检测配色和联动判断。
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# 以下为示例信息，请填写个人信息，并依据顶部任务背景修改项目和位置。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "实验",
    "监测点位": "实训区",
}

# >>>>>>>>>>>>>>>>>>>> TODO 1：检测配色设置区 >>>>>>>>>>>>>>>>>>>>
# 按顶部任务要求设置安全帽、未戴帽头部的检测框及标签背景颜色；两者使用同一类别配色。
# 使用BGR（蓝、绿、红）顺序，每个数值为0至255的整数；标签文字由系统自动选择深浅。
# 以下保留原来的蓝色示例，需学生按任务要求修改，保存并重启后生效。
COLOR_HEAD = (255, 216, 128)  # head：未戴帽头部，淡蓝色
COLOR_HAT = (160, 60, 0)  # hat：安全帽，深蓝色
# <<<<<<<<<<<<<<<<<<<< TODO 1：设置区结束 <<<<<<<<<<<<<<<<<<<<<<


# >>>>>>>>>>>>>>>>>>>> TODO 2：功能检查区 >>>>>>>>>>>>>>>>>>>>
# 编写位置：在下方control_buzzer(...)函数内编写联动判断。
# 下方仅提供待完善的基础示例，并非完整答案。
# 请依据题目核对已有判断条件，解决混合场景漏报，并保留无人及仅戴帽场景的静音处理。
#
# 推荐使用语法：
# if / else：条件判断。
# >：大于；==：等于。
# and：逻辑与，两个条件均为 True 时结果为 True。
#
# 可调用变量：
# hat_count：本次检测到的安全帽数量，整数；大于0表示有安全帽目标。
# head_count：本次检测到的未戴帽头部数量，整数；大于0表示有未戴帽目标，不代表画面总人数。
# 系统在每次识别成功后自动传入这两个变量；实训前应核对模型类别与实物佩戴情况一致。
#
# 可调用接口：
# buzzer.beep()：请求提示音；条件持续达到确认时间后，由后台按配置执行单组或循环鸣叫。
# buzzer.reset()：请求静音，停止后续循环；正在执行的一组按原流程结束。
# 每次函数调用必须且只能执行一个接口，不需要返回值，也不需要编写循环、等待或底层驱动操作。
#
def control_buzzer(hat_count, head_count):
    # >>>>>>>>>>>>>>>>>>>> TODO 2：功能检查区 >>>>>>>>>>>>>>>>>>>>
    # 请依据任务背景调整下方判断，并分别验证无人、仅戴帽、仅未戴帽及两类同时出现的响应。
    if head_count > 0 and hat_count == 0:
        buzzer.beep()
    else:
        buzzer.reset()
    # <<<<<<<<<<<<<<<<<<<< TODO 2：修改区结束 <<<<<<<<<<<<<<<<<<<<<<


# ==================== 03 系统配置 ====================
# 以下为实训箱调试参数，本次任务通常无需修改。
# 请求分辨率不代表设备一定支持，以终端日志中的实际采集尺寸为准。
# 检测配色见“02 用户设置”；模型、设备和通信参数在本分区维护。

# 模型与类别顺序
# 模型路径相对于启动目录；从本目录启动，类别名称及顺序必须与所选RKNN模型一致。
MODEL_PATH = './model/hat_rk3588_fp.rknn'
CLASS_NAMES = ['head', 'hat', 'black']
COLOR_BLACK = (80, 80, 80)  # black：模型第三类，灰色，不属于本题配色考点。

# 蜂鸣器与实验归档
# 系统在后台执行鸣叫，用户判断函数无需编写循环或等待。
# 一组由多声短鸣构成，组内静音与组间静音分别设置；本题通常无需调整。
ENABLE_BUZZER = True  # False关闭设备联动，仅运行安全帽识别。
BUZZER_MODULE_INDEX = 2  # 蜂鸣器模块编号。
BUZZER_REPEAT = True  # True循环提示，False单组提示。
BEEP_REPEAT_INTERVAL = 1.0  # 一组结束到下一组开始之间的静音时间，秒。
DETECTION_CONFIRM_TIME = 0.3  # 响应条件持续成立的确认时间，秒。
DETECTION_RESET_TIME = 1.0  # 单组模式下，条件持续不成立后的复位时间，秒。
BEEP_COUNT = 2  # 每组鸣叫次数。
BEEP_DURATION = 0.2  # 每声持续时间，秒。
BEEP_INTERVAL = 0.1  # 两声之间的静音时间，秒。
# 成果保存到当前用户桌面/成果输出/考试编号/项目名称，每次运行新建CSV及实际入口源码副本。
# 主CSV汇总无人、仅戴帽、仅未戴帽、两类同时出现四种场景，未完成项保留“未验证”。
# 程序请求与实际声音应分别核对；现有汇总表中的核验结果不能代替现场听音及配色检查。

# 处理性能与停止方式
OPENCV_THREADS = 1  # OpenCV 图像处理线程数
UDP_SEND_TIMEOUT = 0.2  # UDP 发送超时，秒
ENABLE_WINDOW_KEYS = False  # 默认 Ctrl+C 停止；存在本地窗口时可开启 Q/ESC 检查

# 可选云台控制
use_ptz = 0  # 0 关闭，1 开启；关闭时跳过控制线程和目标方向计算
ptzModIndex = 17  # 云台模块编号
ptzSpeed = 5  # 云台速度，1 至 5
OFFSET_TRED = 50  # 目标偏离画面中心的触发距离，像素

# 蜂鸣器原厂 PWM 参数：保留引脚 12 及原驱动调用顺序，与上方鸣叫节奏分开维护。
BUZZER_PIN = 12
BUZZER_PWM_CHANNEL = 0
BUZZER_PWM_SPEED_MODE = 1
BUZZER_PWM_TIMER = 0
BUZZER_PWM_RESOLUTION = 10
BUZZER_PWM_FREQUENCY = 1000
BUZZER_PWM_ON_DUTY = 1000
BUZZER_SCAN_WAIT = 2.0  # 等待共享驱动的模块扫描完成，秒
BUZZER_RESULT_TIMEOUT = 1.0  # 超过此时间无新的有效判断，不再循环鸣叫，秒
CSV_RECORD_INTERVAL = 1.0  # 后台核验采样间隔上限，秒；数量或判断变化、控制动作即时提交
CSV_QUEUE_SIZE = 512  # 后台文件写入队列上限，避免磁盘写入阻塞识别

# 摄像头与采集模式
CAMERA_INDEX = 41  # 摄像头设备编号
FRAME_WIDTH = 1920  # 请求采集宽度，像素
FRAME_HEIGHT = 1080  # 请求采集高度，像素
CAMERA_MODE_FALLBACKS = [(1280, 720), (640, 480)]  # 请求失败后依次尝试；每次核对实际帧尺寸
USE_MJPEG = True  # 请求 MJPEG 采集格式

# 识别阈值与重复框处理
BOX_THRESH = 0.35  # 模型候选框阈值
NMS_THRESH = 0.5  # 驱动非极大值抑制阈值
CONFIDENCE_VAL = 0.5  # 最终显示的置信度阈值
REMOVE_DUPLICATES = True  # 是否执行额外重框过滤
DUPLICATE_IOU = 0.5  # 同类框去重阈值
CROSS_CLASS_IOU = 0.75  # head/hat 高度重叠时去重的阈值

# 输入增强与回传画面
ENHANCE_INPUT = False  # 默认关闭，开启后增加亮度对比度处理
CLAHE_CLIP_LIMIT = 1.5  # 输入增强强度，仅增强开启时生效
PREVIEW_LONG_EDGE = 720  # 预览最长边，像素；只缩小，不放大
JPEG_QUALITY = 60  # JPEG 质量，越高数据量越大
BOX_LINE_WIDTH = 4  # 最终预览上的框线宽，像素
LABEL_FONT_SCALE = 0.9  # 检测标签字体比例
LABEL_LINE_WIDTH = 2  # 检测标签字线宽，像素

# 原协议通信参数
DEST_ADDR = ('127.0.0.1', 8088)  # 图像接收地址
DEST_ADDR_INFO = ('127.0.0.1', 8089)  # 识别数量接收地址
max_packet_size = 60000  # 单个数据片上限，不含16字节包头

# ==================== 04 运行状态与资源 ====================
# 以下对象和变量由程序维护，收集声音请求、记录连接、缓存、线程与分包状态，无需在实训中修改。

# 联动请求接口：收集用户判断，由 BuzzerLink 的后台线程执行设备控制。
class BuzzerCommands:
    # 每次用户判断只能提交一个响应，接口本身不等待、不直接开关蜂鸣器。
    def __init__(self):
        self.condition = None
        self.calls = 0

    def beep(self):
        self.condition = True
        self.calls += 1

    def reset(self):
        self.condition = False
        self.calls += 1


def evaluate_buzzer_rule(hat_count, head_count):
    # 清除上次请求并调用用户函数，漏写或重复调用接口时报告错误。
    buzzer.condition = None
    buzzer.calls = 0
    control_buzzer(hat_count, head_count)
    if buzzer.calls != 1:
        raise ValueError('control_buzzer 的每个分支必须调用一次 buzzer.beep() 或 buzzer.reset()')
    return buzzer.condition


# 旧异步接口状态仅用于兼容；当前视频主流程使用函数内的容量为1的队列。
PREVIEW_MAX_WIDTH = 0  # 不做预览缩放，减少额外处理
dest_addr = DEST_ADDR
dest_addr2 = DEST_ADDR_INFO
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
control_lock = Lock()
global_id = 0
global_id_lock = Lock()
_frame_queue = Queue(maxsize=3)
_parse_thread = None
_parse_video = False
_AIParseResult = []
_ai_result_lock = Lock()
_parseing = False
_parse_state_lock = Lock()
_send_queue = Queue(maxsize=3)
_send_thread = None
_send_running = False
destImage = 0
letter_box = 0
modWidth = 0
modHeight = 0
modChannel = 0
bQuant = 0
_output_metadata = None
_output_metadata_key = None
last_direction = 0
_control_running = False
control_flags = 8
modules = None
experiment_log = None
buzzer = BuzzerCommands()  # 提供给顶部用户函数的条件请求接口，不是底层驱动
_control_thread = None
modStatus = 0

# -------------------- 实验归档与 CSV 汇总 --------------------
# 在桌面的“成果输出”目录内按考试编号、项目名称归档，文件名包含项目、考试编号、日期和时分秒。
def safe_path_component(text):
    # 清理路径分隔符和文件名非法字符，避免考试编号或位置变成其他目录。
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip(' .')
    cleaned = cleaned[:80].rstrip(' .') or "未命名"
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if cleaned.split('.')[0].upper() in reserved:
        cleaned = "_" + cleaned
    return cleaned

def find_desktop():
    # 使用运行程序的当前用户桌面，支持 Linux 中文和自定义桌面路径。
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


class CsvExperimentLog:
    # 主表固定四种场景，以最新稳定结果覆盖；异常表追加保存，写入均在后台完成。
    SCENES = ('无人', '仅戴帽', '仅未戴帽', '戴帽与未戴帽同时出现')
    FIELD_NAMES = [
        '最近更新时间', '实验场景', '安全帽数量', '未戴帽头部数量',
        '预期响应', '程序响应', '核验结果', '累计核验次数', '累计不通过次数',
        '蜂鸣器联动启用', '循环提示启用', '蜂鸣器模块编号', '确认时间(秒)', '复位时间(秒)',
        '每组鸣叫次数', '每声持续时间(秒)', '组内静音时间(秒)', '组间静音时间(秒)',
    ]
    EVENT_FIELDS = [
        '记录时间', '记录序号', '实验累计毫秒', '安全帽数量', '未戴帽头部数量',
        '联动条件', '触发编号', '组内鸣叫序号', '动作', '执行结果', '蜂鸣器模块编号',
        '蜂鸣器联动启用', '循环提示启用', '组间静音时间(秒)', '确认时间(秒)', '复位时间(秒)', '每组鸣叫次数',
        '每声持续时间(秒)', '组内静音时间(秒)', '错误信息',
    ]

    def __init__(self, metadata, output_root=None):
        self.metadata = dict(metadata)
        for key in self.metadata:
            if not isinstance(key, str) or not key.strip() or key.strip() in set(self.FIELD_NAMES + self.EVENT_FIELDS):
                raise ValueError(f'实验信息字段名无效或与系统列重名：{key}')
        if not math.isfinite(CSV_RECORD_INTERVAL) or CSV_RECORD_INTERVAL <= 0:
            raise ValueError('CSV_RECORD_INTERVAL 必须为有限正数')
        if isinstance(CSV_QUEUE_SIZE, bool) or not isinstance(CSV_QUEUE_SIZE, int) or CSV_QUEUE_SIZE <= 0:
            raise ValueError('CSV_QUEUE_SIZE 必须为正整数')
        person = str(self.metadata.get('考试编号') or '未命名').strip() or '未命名'
        project = str(self.metadata.get('项目名称') or '未命名实验').strip() or '未命名实验'
        root = Path(output_root) if output_root is not None else find_desktop() / "成果输出"
        folder = root / safe_path_component(person) / safe_path_component(project)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now()
        sequence = 1
        while True:
            suffix = '' if sequence == 1 else f'_{sequence}'
            stem = f'{safe_path_component(project)}_{safe_path_component(person)}_{stamp:%Y%m%d}{suffix}_{stamp:%H%M%S}'
            self.file_path = folder / (stem + '.csv')
            self.code_path = folder / (stem + '.py')
            self.error_path = folder / (stem.rsplit('_', 1)[0] + '_异常_' + stamp.strftime('%H%M%S') + '.csv')
            if self.code_path.exists() or self.error_path.exists():
                sequence += 1
                continue
            try:
                self.handle = self.file_path.open('x', encoding='utf-8-sig', newline='')
                break
            except FileExistsError:
                sequence += 1
        self.field_names = [self.FIELD_NAMES[0], *self.metadata, *self.FIELD_NAMES[1:]]
        self.handle.close()
        self.rows = {scene: self.empty_row(scene) for scene in self.SCENES}
        self.candidate = None
        self.candidate_since = self.last_sample_time = None
        self.summary_write_failed = False
        self.save_summary()
        self.started = time.monotonic()
        self.queue = Queue(maxsize=CSV_QUEUE_SIZE)
        self.lock = Lock()
        self.stopped, self.failed = Event(), Event()
        self.sequence = self.dropped = 0
        self.thread = Thread(target=self.worker, name='experiment-csv', daemon=True)
        self.thread.start()
        logging.info('CSV 保存位置：%s', self.file_path)
        try:
            with self.code_path.open('xb') as handle:
                handle.write(Path(__file__).resolve().read_bytes())
        except Exception as error:
            self.record('保存运行代码', '失败', error=str(error))
            logging.exception('运行代码保存失败')

    @staticmethod
    def spreadsheet_text(value):
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return value

    @staticmethod
    def scene_for(hats, heads):
        # 按两类目标是否存在划分场景，人数变化不会增加新行。
        if heads > 0:
            return '戴帽与未戴帽同时出现' if hats > 0 else '仅未戴帽'
        return '仅戴帽' if hats > 0 else '无人'

    def empty_row(self, scene):
        # 启动时预建四行，未实际验证的场景不能计为通过。
        return {
            **self.metadata, '最近更新时间': '', '实验场景': scene,
            '安全帽数量': '', '未戴帽头部数量': '',
            '预期响应': '鸣叫提示' if scene in self.SCENES[2:] else '保持静音',
            '程序响应': '未验证', '核验结果': '未验证',
            '累计核验次数': 0, '累计不通过次数': 0,
            '蜂鸣器联动启用': '是' if ENABLE_BUZZER else '否',
            '循环提示启用': '是' if BUZZER_REPEAT else '否',
            '蜂鸣器模块编号': BUZZER_MODULE_INDEX,
            '确认时间(秒)': DETECTION_CONFIRM_TIME, '复位时间(秒)': DETECTION_RESET_TIME,
            '每组鸣叫次数': BEEP_COUNT, '每声持续时间(秒)': BEEP_DURATION,
            '组内静音时间(秒)': BEEP_INTERVAL, '组间静音时间(秒)': BEEP_REPEAT_INTERVAL,
        }

    def save_summary(self):
        # 写完临时文件后替换主表，避免读取到只有半张的汇总；主表始终只有四行。
        temporary = self.file_path.with_suffix('.csv.tmp')
        try:
            with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=self.field_names)
                writer.writeheader()
                writer.writerows({key: self.spreadsheet_text(value) for key, value in row.items()}
                                 for row in self.rows.values())
            os.replace(temporary, self.file_path)
            self.summary_write_failed = False
        finally:
            temporary.unlink(missing_ok=True)

    def append_error(self, event):
        # 仅异常追加，不把正常识别和每次开关重复写进汇总表。
        exists = self.error_path.exists()
        fields = [self.EVENT_FIELDS[0], *self.metadata, *self.EVENT_FIELDS[1:]]
        with self.error_path.open('a', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({key: self.spreadsheet_text(value) for key, value in event.items() if key in fields})

    def record(self, action, result, error='', hat_count='', head_count='', condition='', trigger_id='', beep='', sample_time=None):
        # 识别与控制线程只提交事件，后台负责筛选、核验和文件更新。
        if self.failed.is_set() or self.stopped.is_set():
            return
        with self.lock:
            self.sequence += 1
            row = dict(zip(self.EVENT_FIELDS, [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'), self.sequence,
                round((time.monotonic() - self.started) * 1000), hat_count, head_count,
                condition, trigger_id, beep, action, result, BUZZER_MODULE_INDEX,
                ENABLE_BUZZER, BUZZER_REPEAT, BEEP_REPEAT_INTERVAL, DETECTION_CONFIRM_TIME, DETECTION_RESET_TIME, BEEP_COUNT,
                BEEP_DURATION, BEEP_INTERVAL, error,
            ]))
            row.update(self.metadata)
            row['_sample_time'] = time.monotonic() if sample_time is None else sample_time
            try:
                self.queue.put_nowait(row)
            except Full:
                self.dropped += 1
                if self.dropped == 1:
                    logging.error('CSV 写入队列已满，部分记录将丢失；识别继续运行')

    def update_summary(self, event):
        # 预期响应按实验要求独立计算，不参与控制；与用户请求比较后填写核验结果。
        # 场景或判断发生变化时重新确认，短暂变化及识别失败不覆盖已有稳定结果。
        action = event['动作']
        hats, heads, condition = event['安全帽数量'], event['未戴帽头部数量'], event['联动条件']
        if action in ('识别与判断', '识别', '用户联动判断'):
            if event['执行结果'] != '识别成功' or not isinstance(condition, bool):
                self.candidate = None
                self.candidate_since = self.last_sample_time = None
                return False
            scene = self.scene_for(hats, heads)
            candidate = (scene, condition)
            now = event['_sample_time']
            gap_limit = max(CSV_RECORD_INTERVAL * 2, DETECTION_CONFIRM_TIME * 2, DETECTION_RESET_TIME)
            if candidate != self.candidate or (self.last_sample_time is not None and now - self.last_sample_time > gap_limit):
                self.candidate, self.candidate_since = candidate, now
            self.last_sample_time = now
            if now - self.candidate_since < DETECTION_CONFIRM_TIME:
                return False
            row = self.rows[scene]
            passed = condition == (heads > 0)
            row.update({'最近更新时间': event['记录时间'], '安全帽数量': hats, '未戴帽头部数量': heads,
                        '程序响应': '鸣叫提示' if condition else '保持静音',
                        '核验结果': '通过' if passed else '不通过'})
            row['累计核验次数'] += 1
            row['累计不通过次数'] += int(not passed)
            return True
        return False

    def worker(self):
        # 正常识别更新汇总，错误另存追加表；文件被占用时保留内存结果并尝试再次保存。
        try:
            while not self.stopped.is_set() or not self.queue.empty():
                try:
                    row = self.queue.get(timeout=0.1)
                except Empty:
                    continue
                if row['错误信息'] or row['执行结果'] in ('失败', '指令失败', '识别失败'):
                    self.append_error(row)
                if self.update_summary(row):
                    try:
                        self.save_summary()
                    except OSError:
                        if not self.summary_write_failed:
                            logging.exception('CSV 汇总更新失败，请关闭占用表格的程序；后续更新将重试')
                        self.summary_write_failed = True
            if self.dropped:
                self.append_error({'动作': '记录完整性', '执行结果': '记录丢失',
                                   '错误信息': f'CSV 队列已满，丢失 {self.dropped} 条记录'})
            self.save_summary()
        except Exception:
            self.failed.set()
            logging.exception('CSV 写入失败，识别与设备控制继续运行；记录可能不完整')

    def close(self):
        self.stopped.set()
        self.thread.join()


def record_experiment(action, result, **details):
    if experiment_log is not None:
        experiment_log.record(action, result, **details)


# ==================== 05 检测结果与标签绘制 ====================
# 保存类别、置信度和坐标，将模型结果映射到预览后绘制粗框及同色标签。

class detectResult:
    # RKNN 后处理返回的单个检测框。

    def __init__(self, left, top, right, bottom, propval, id):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.prop = propval
        self.id = id
        self.class_name = get_class_name(id)
        self.name = "{} {:.2f}".format(self.class_name, self.prop)

def get_class_name(cls_id):
    # 根据类别 id 返回显示名称。
    if 0 <= cls_id < len(CLASS_NAMES):
        return CLASS_NAMES[cls_id]
    return "unknown"

def get_class_color(cls_id):
    # 根据类别 id 返回检测框颜色。
    if cls_id == 0:
        return COLOR_HEAD
    if cls_id == 1:
        return COLOR_HAT
    return COLOR_BLACK

def preview_detection(item, scale_x, scale_y):
    return detectResult(round(item.left * scale_x), round(item.top * scale_y),
                        round(item.right * scale_x), round(item.bottom * scale_y), item.prop, item.id)

def draw_detect_result(frame, item):
    # 在线性缩小后的预览上绘制，线宽和文字大小不会随采集分辨率变化。
    box_color = get_class_color(item.id)
    blue, green, red = box_color
    brightness = 0.114 * blue + 0.587 * green + 0.299 * red
    text_color = (30, 30, 30) if brightness >= 160 else (255, 255, 255)
    left, top, right, bottom = (int(round(value)) for value in
                                (item.left, item.top, item.right, item.bottom))
    cv2.rectangle(frame, (left, top), (right, bottom), box_color, BOX_LINE_WIDTH)
    (text_width, text_height), baseline = cv2.getTextSize(
        item.name, cv2.FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE, LABEL_LINE_WIDTH)
    label_height = text_height + baseline + 8
    label_left = max(0, min(left, frame.shape[1] - text_width - 8))
    label_top = top - label_height if top >= label_height else top
    label_top = max(0, min(label_top, frame.shape[0] - label_height))
    cv2.rectangle(frame, (label_left, label_top),
                  (min(frame.shape[1] - 1, label_left + text_width + 8), label_top + label_height),
                  box_color, -1)
    cv2.putText(frame, item.name, (label_left + 4, label_top + text_height + 4),
                cv2.FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE, text_color, LABEL_LINE_WIDTH, cv2.LINE_AA)

def fit_preview_output(frame):
    height, width = frame.shape[:2]
    scale = min(1.0, PREVIEW_LONG_EDGE / max(width, height))
    output_width = max(1, round(width * scale))
    output_height = max(1, round(height * scale))
    if (output_width, output_height) != (width, height):
        return cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_LINEAR)
    return frame

def render_detected_frame(raw, results, detection_ok, fps):
    # 只接收与 raw 同次推理的结果；缩放预览后同步映射框坐标。
    # 同帧顺序处理：推理已经结束，预览可直接绘制，无需再复制图像。
    preview = fit_preview_output(raw)
    scale_x = preview.shape[1] / raw.shape[1]
    scale_y = preview.shape[0] / raw.shape[0]
    if detection_ok:
        for item in results:
            draw_detect_result(preview, preview_detection(item, scale_x, scale_y))
    return preview

# ==================== 06 摄像头连接与采集模式 ====================
# 按设置依次尝试采集模式，确认能够读到有效图像，并核对真实宽高。

def open_camera():
    # 每种模式重新打开设备；以实际读到非空帧为准，不能只检查 isOpened。
    modes = []
    requested_sizes = [(FRAME_WIDTH, FRAME_HEIGHT)] + CAMERA_MODE_FALLBACKS
    for width, height in requested_sizes:
        modes.append((width, height, USE_MJPEG))
    modes.extend([(640, 480, False), (None, None, False)])
    attempts = [(cv2.CAP_V4L2, mode) for mode in dict.fromkeys(modes)]
    # 自动后端只使用设备默认模式，避免 GStreamer 连续设置属性破坏管线。
    attempts.append((cv2.CAP_ANY, (None, None, False)))
    for backend, (width, height, mjpeg) in attempts:
        cap = None
        accepted = False
        try:
            logging.info("Trying camera %s: backend=%s, size=%s, MJPEG=%s",
                         CAMERA_INDEX, backend, f'{width}x{height}' if width else 'default', mjpeg)
            cap = cv2.VideoCapture(CAMERA_INDEX, backend)
            if not cap.isOpened():
                continue
            if width is not None:
                if mjpeg:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                # 不强制设置帧率或缓冲区，保留此模式由设备协商出的参数。
            for _ in range(3):
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    actual_height, actual_width = frame.shape[:2]
                    if width is not None and (actual_width, actual_height) != (width, height):
                        logging.warning("Requested %sx%s but received %sx%s; trying next mode",
                                        width, height, actual_width, actual_height)
                        break
                    logging.info("Camera ready: actual frame %sx%s, backend=%s, aspect %.3f",
                                 actual_width, actual_height, backend, actual_width / actual_height)
                    if (actual_width, actual_height) != (FRAME_WIDTH, FRAME_HEIGHT):
                        logging.warning("1080P capture not active; fallback is %sx%s",
                                        actual_width, actual_height)
                    logging.info("Compare scene edges with hat2 at the same camera position; no crop or digital zoom")
                    accepted = True
                    return cap, frame
            logging.warning("No valid frame in this mode; trying fallback")
        except Exception:
            logging.exception("Camera mode failed; trying fallback")
        finally:
            if cap is not None and not accepted:
                cap.release()
    logging.error("All camera modes failed; check device index, USB connection and camera occupancy")
    return None, None

# ==================== 07 同帧视频处理流水线 ====================
# 采集、推理和输出并行；原图、检测框和统计作为同一任务传递，避免错帧。

def enqueue_latest(queue, value):
    # 返回是否丢弃了旧任务；图像和结果作为一个任务整体替换。
    dropped = False
    while True:
        try:
            queue.put_nowait(value)
            return dropped
        except Full:
            try:
                queue.get_nowait()
                dropped = True
            except Empty:
                pass

def publish_detected_frame(job, fps, encode_params):
    # job 内的原图、框和统计来自同一次推理，禁止分开读取共享的最新结果。
    captured, raw, status, heads, hats, results = job
    started = time.perf_counter()
    preview = render_detected_frame(raw, results, status == 0, fps)
    render_time = time.perf_counter() - started
    started = time.perf_counter()
    ok, encoded = cv2.imencode('.jpg', preview, encode_params)
    encode_time = time.perf_counter() - started
    if not ok:
        logging.warning("Preview JPEG encoding failed")
        return False, render_time, encode_time, 0.0
    started = time.perf_counter()
    info_ok = send_msginfo(f'{hats},{heads}'.encode('utf-8'))
    # memoryview 直接访问编码缓冲区，避免整张 JPEG 的 tobytes 复制。
    image_ok = send(memoryview(encoded))
    return info_ok and image_ok, render_time, encode_time, time.perf_counter() - started

# 蜂鸣器联动使用独立线程，只接收触发信号，不阻塞图像推理和回传。
# 共用 SensorModule 已初始化的驱动；联动失败关闭自身，视频识别继续运行。
class BuzzerLink:
    def __init__(self, driver, recorder=None):
        if not isinstance(BUZZER_REPEAT, bool):
            raise ValueError('BUZZER_REPEAT 必须为 True 或 False')
        if isinstance(BEEP_COUNT, bool) or not isinstance(BEEP_COUNT, int) or BEEP_COUNT <= 0:
            raise ValueError('BEEP_COUNT 必须为正整数')
        if isinstance(BUZZER_MODULE_INDEX, bool) or not isinstance(BUZZER_MODULE_INDEX, int) or BUZZER_MODULE_INDEX < 0:
            raise ValueError('BUZZER_MODULE_INDEX 必须为非负整数')
        for name, value, allow_zero in (
            ('DETECTION_CONFIRM_TIME', DETECTION_CONFIRM_TIME, False),
            ('DETECTION_RESET_TIME', DETECTION_RESET_TIME, False),
            ('BEEP_DURATION', BEEP_DURATION, False),
            ('BEEP_INTERVAL', BEEP_INTERVAL, True),
            ('BEEP_REPEAT_INTERVAL', BEEP_REPEAT_INTERVAL, False),
            ('BUZZER_RESULT_TIMEOUT', BUZZER_RESULT_TIMEOUT, False),
            ('BUZZER_SCAN_WAIT', BUZZER_SCAN_WAIT, True),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
                raise ValueError(f'{name} 必须为有限的' + ('非负数' if allow_zero else '正数'))
        self.driver = driver
        self.record = recorder or (lambda *args, **kwargs: None)
        self.last_record_state = None
        self.last_record_time = None
        self.trigger_id = 0
        self.context = {}
        self.beep = 0
        self.repeat_active = False
        self.last_valid_update = 0.0
        self.latest_counts = (0, 0)
        self.stopped, self.pending = Event(), Event()
        self.lock = Lock()
        self.ready = self.busy = self.latched = False
        self.present_since = self.absent_since = self.last_sample = None
        self.thread = Thread(target=self.worker, name='buzzer-link', daemon=True)

    @staticmethod
    def checked(result, action):
        if result < 0:
            raise RuntimeError(f'{action}失败，驱动返回值：{result}')

    def switch(self, enabled):
        action = '开启蜂鸣器' if enabled else '关闭蜂鸣器'
        try:
            self.checked(self.driver.PwmSetDuty(
                BUZZER_MODULE_INDEX, BUZZER_PWM_CHANNEL, BUZZER_PWM_SPEED_MODE,
                BUZZER_PWM_ON_DUTY if enabled else 0), '设置蜂鸣器占空比')
            self.checked(self.driver.PwmStart(
                BUZZER_MODULE_INDEX, BUZZER_PWM_SPEED_MODE, BUZZER_PWM_CHANNEL), '应用蜂鸣器开关')
        except Exception as error:
            self.record(action, '指令失败', error=str(error), beep=self.beep, **self.context)
            raise
        self.record(action, '驱动指令成功', beep=self.beep, **self.context)

    def record_detection(self, status, hats, heads, condition, now):
        # 数量或响应变化立即提交；持续状态定期采样，满足确认时间后再更新汇总表。
        state = (status, hats, heads, condition)
        if state != self.last_record_state or self.last_record_time is None or now - self.last_record_time >= min(CSV_RECORD_INTERVAL, DETECTION_CONFIRM_TIME):
            self.record('识别与判断', '识别成功' if status == 0 else '识别失败',
                        hat_count=hats if status == 0 else '', head_count=heads if status == 0 else '',
                        condition=condition, error='' if status == 0 else f'识别状态码：{status}', sample_time=now)
            self.last_record_state, self.last_record_time = state, now

    def update(self, status, hat_count, head_count, now):
        if self.stopped.is_set():
            self.record_detection(status, hat_count, head_count, '联动已停用', now)
            return
        # 失败帧及长时间采集空缺打断连续计时，不能当作目标离开。
        if self.last_sample is not None and now - self.last_sample > max(DETECTION_CONFIRM_TIME, DETECTION_RESET_TIME):
            self.present_since = self.absent_since = None
        self.last_sample = now
        if status != 0:
            with self.lock:
                self.repeat_active = False
            self.record_detection(status, hat_count, head_count, '未判断', now)
            self.present_since = self.absent_since = None
            return
        try:
            present = evaluate_buzzer_rule(hat_count, head_count)
            if not isinstance(present, bool):
                raise ValueError('联动请求必须为有效的开关条件')
        except Exception as error:
            # 唤醒控制线程立即退出并清理；不在识别线程中等待蜂鸣器关闭。
            logging.exception('用户联动判断执行失败，已停用蜂鸣器联动，视频识别继续运行')
            self.record('用户联动判断', '失败', error=f'{type(error).__name__}: {error}',
                        hat_count=hat_count, head_count=head_count, condition='判断失败')
            self.stopped.set()
            self.pending.set()
            return
        self.record_detection(status, hat_count, head_count, present, now)
        with self.lock:
            self.last_valid_update = time.monotonic()
            self.latest_counts = (hat_count, head_count)
        if not present:
            with self.lock:
                if self.repeat_active and BUZZER_REPEAT:
                    self.record('停止循环提示', '当前一组完成后停止', hat_count=hat_count,
                                head_count=head_count, condition=False)
                self.repeat_active = False
            self.present_since = None
            if self.absent_since is None:
                self.absent_since = now
            if now - self.absent_since >= DETECTION_RESET_TIME:
                if self.latched:
                    self.record('联动复位', '等待下一次触发', hat_count=hat_count, head_count=head_count, condition=False)
                self.latched = False
            return
        self.absent_since = None
        if self.present_since is None:
            self.present_since = now
        if (self.latched and (not BUZZER_REPEAT or self.repeat_active)) or now - self.present_since < DETECTION_CONFIRM_TIME:
            return
        with self.lock:
            if not self.ready or self.stopped.is_set():
                return
            self.latched = True
            self.repeat_active = True
            if self.busy:
                if BUZZER_REPEAT:
                    return
                self.record('触发忽略', '未执行', hat_count=hat_count, head_count=head_count,
                            condition=True, error='蜂鸣器正在执行上一组鸣叫，不排队补鸣')
                return
            self.busy = True
            self.trigger_id += 1
            self.context = dict(hat_count=hat_count, head_count=head_count, condition=True, trigger_id=self.trigger_id)
            self.record('联动触发', '已提交', **self.context)
            self.pending.set()

    def start(self):
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.pending.set()
        if self.thread.ident is not None:
            # 等待关闭、停止 PWM 和断开连接完成后，主程序才能注销共享驱动。
            self.thread.join()

    def worker(self):
        connection_attempted = pwm_attempted = False
        try:
            for name, count in (('PWNMInit', 7), ('PwmSetDuty', 4), ('PwmStart', 3), ('PwmStop', 3)):
                function = getattr(self.driver, name)
                function.argtypes = [ctypes.c_int] * count
                function.restype = ctypes.c_int
            if self.stopped.wait(BUZZER_SCAN_WAIT):
                return
            if self.driver.isModReady(BUZZER_MODULE_INDEX) != 1:
                raise RuntimeError(f'蜂鸣器模块 {BUZZER_MODULE_INDEX} 未在线')
            connection_attempted = True
            if self.driver.connectToMod(BUZZER_MODULE_INDEX) <= 0:
                raise RuntimeError('蜂鸣器模块连接失败')
            pwm_attempted = True
            self.checked(self.driver.PWNMInit(
                BUZZER_MODULE_INDEX, BUZZER_PWM_CHANNEL, BUZZER_PIN, BUZZER_PWM_SPEED_MODE,
                BUZZER_PWM_TIMER, BUZZER_PWM_RESOLUTION, BUZZER_PWM_FREQUENCY), '蜂鸣器 PWM 初始化')
            self.switch(False)
            with self.lock:
                self.ready = True
            self.record('蜂鸣器初始化', '驱动指令成功')
            logging.info('蜂鸣器联动就绪：使用顶部 control_buzzer 判断，模块 %s', BUZZER_MODULE_INDEX)
            next_repeat_at = None
            while not self.stopped.is_set():
                with self.lock:
                    timeout = max(0.0, next_repeat_at - time.monotonic()) if (
                        BUZZER_REPEAT and self.repeat_active and next_repeat_at is not None) else None
                requested = self.pending.wait(timeout)
                self.pending.clear()
                if self.stopped.is_set():
                    break
                with self.lock:
                    if BUZZER_REPEAT and (not self.repeat_active or
                            time.monotonic() - self.last_valid_update > BUZZER_RESULT_TIMEOUT):
                        if self.repeat_active:
                            self.record('停止循环提示', '判断结果已过期', error='没有新的有效识别判断')
                        self.repeat_active = False
                        self.busy = False
                        next_repeat_at = None
                        continue
                    if not requested:
                        self.trigger_id += 1
                        hats, heads = self.latest_counts
                        self.context = dict(hat_count=hats, head_count=heads,
                                            condition=True, trigger_id=self.trigger_id)
                        self.record('循环触发', '已提交', **self.context)
                    self.busy = True
                for beep in range(BEEP_COUNT):
                    self.beep = beep + 1
                    self.switch(True)
                    interrupted = self.stopped.wait(BEEP_DURATION)
                    self.switch(False)
                    if interrupted:
                        break
                    if beep + 1 < BEEP_COUNT and self.stopped.wait(BEEP_INTERVAL):
                        break
                if not self.stopped.is_set():
                    logging.info('蜂鸣器提示指令执行成功：%s 声', BEEP_COUNT)
                    self.record('提示完成', '驱动指令成功', **self.context)
                with self.lock:
                    self.busy = False
                # 间隔从当前组结束计时，处理延迟后不追赶补鸣。
                next_repeat_at = time.monotonic() + BEEP_REPEAT_INTERVAL
        except Exception as error:
            logging.exception('蜂鸣器联动停止，视频识别继续运行')
            self.record('蜂鸣器联动', '失败', error=f'{type(error).__name__}: {error}', **self.context)
        finally:
            self.stopped.set()
            with self.lock:
                self.ready = False
                self.busy = False
            # 每项清理独立尝试，前一项失败不跳过后一项。
            actions = []
            if pwm_attempted:
                actions.extend([
                    ('关闭蜂鸣器', lambda: self.switch(False)),
                    ('停止蜂鸣器 PWM', lambda: self.checked(self.driver.PwmStop(
                        BUZZER_MODULE_INDEX, BUZZER_PWM_SPEED_MODE, BUZZER_PWM_CHANNEL), '停止 PWM')),
                ])
            if connection_attempted:
                actions.append(('断开蜂鸣器', lambda: self.checked(
                    self.driver.disconnectToMod(BUZZER_MODULE_INDEX), '断开蜂鸣器')))
            for name, action in actions:
                try:
                    action()
                    self.record(name, '驱动指令成功', **self.context)
                except Exception as error:
                    logging.exception('%s失败', name)
                    self.record(name, '指令失败', error=str(error), **self.context)


def run_live_video(cap, first_frame, clahe):
    stopped, capture_done = Event(), Event()
    frames, outputs = Queue(maxsize=1), Queue(maxsize=1)
    stats_lock = Lock()
    stats = dict(captured=0, ai=0, sent=0, output_jobs=0, dropped_input=0, dropped_output=0,
                 prepare=0.0, detect=0.0, render=0.0, encode=0.0, send=0.0, ai_fps=0.0)
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]

    def capture_worker():
        frame = first_frame
        try:
            while not stopped.is_set():
                if frame is None:
                    ok, frame = cap.read()
                    if not ok or frame is None or frame.size == 0:
                        logging.error("Camera frame read failed")
                        record_experiment('摄像头采集', '失败', error='无法读取摄像头帧')
                        break
                dropped = enqueue_latest(frames, (time.monotonic(), frame))
                with stats_lock:
                    stats['captured'] += 1
                    stats['dropped_input'] += int(dropped)
                frame = None
        except Exception as error:
            logging.exception("Capture worker failed")
            record_experiment('摄像头采集', '失败', error=str(error))
        finally:
            capture_done.set()

    def output_worker():
        try:
            while not stopped.is_set() or not outputs.empty():
                try:
                    job = outputs.get(timeout=0.1)
                except Empty:
                    continue
                with stats_lock:
                    fps = stats['ai_fps']
                ok, render_cost, encode_cost, send_cost = publish_detected_frame(job, fps, encode_params)
                with stats_lock:
                    stats['sent'] += int(ok)
                    stats['output_jobs'] += 1
                    stats['render'] += render_cost
                    stats['encode'] += encode_cost
                    stats['send'] += send_cost
        except Exception as error:
            logging.exception("Output worker failed")
            record_experiment('画面回传', '失败', error=str(error))
            stopped.set()

    reader = Thread(target=capture_worker, daemon=True)
    sender = Thread(target=output_worker, daemon=True)
    rgb_buffer = None
    window_start = time.monotonic()
    previous = stats.copy()
    buzzer_link = None
    last_csv_state, last_csv_time = None, float('-inf')
    try:
        if ENABLE_BUZZER:
            buzzer_link = BuzzerLink(sensor_driver, record_experiment)
            buzzer_link.start()
        cv2.setNumThreads(OPENCV_THREADS)
        udp_socket.settimeout(UDP_SEND_TIMEOUT)
        if use_ptz == 1:
            start_control_thread()
        reader.start()
        sender.start()
        logging.info("Same-frame pipeline enabled: latest input, matched image/results, background JPEG/UDP")
        while not stopped.is_set():
            try:
                captured, frame = frames.get(timeout=0.1)
            except Empty:
                if capture_done.is_set():
                    break
                continue
            src_img, status = None, -1
            heads = hats = 0
            results = []
            prepare_cost = detect_cost = 0.0
            try:
                started = time.perf_counter()
                image = enhance_detection_frame(frame, clahe)
                if rgb_buffer is None or rgb_buffer.shape != image.shape:
                    rgb_buffer = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                else:
                    cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=rgb_buffer)
                height, width, _ = rgb_buffer.shape
                src_img = getImageFromVideoFrame(width, height, rgb_buffer.nbytes, IMAGE_FORMAT_RGB888,
                                                rgb_buffer.ctypes.data_as(ctypes.c_char_p))
                prepare_cost = time.perf_counter() - started
                started = time.perf_counter()
                status, heads, hats, results = detect(src_img)
                detect_cost = time.perf_counter() - started
            except Exception as error:
                logging.exception("Video detection failed")
                record_experiment('视频识别', '失败', error=f'{type(error).__name__}: {error}')
            finally:
                if src_img:
                    releaseImg(src_img)
            if status != 0:
                heads = hats = 0
                results = []
            if buzzer_link is not None:
                buzzer_link.update(status, hats, heads, time.monotonic())
            elif experiment_log is not None:
                # 关闭蜂鸣器时仍记录识别结果，明确标记未执行联动判断。
                now = time.monotonic()
                state = (status, hats, heads)
                if state != last_csv_state or now - last_csv_time >= CSV_RECORD_INTERVAL:
                    record_experiment('识别', '识别成功' if status == 0 else '识别失败',
                                      hat_count=hats if status == 0 else '', head_count=heads if status == 0 else '',
                                      condition='联动未启用')
                    last_csv_state, last_csv_time = state, now
            # 相机不再改写此帧；输出线程独占绘制，推理线程继续处理另一张图。
            dropped = enqueue_latest(outputs, (captured, frame, status, heads, hats, tuple(results)))
            with stats_lock:
                stats['ai'] += 1
                stats['dropped_output'] += int(dropped)
                stats['prepare'] += prepare_cost
                stats['detect'] += detect_cost
            elapsed = time.monotonic() - window_start
            if elapsed >= 3:
                with stats_lock:
                    snapshot = stats.copy()
                    stats['ai_fps'] = (snapshot['ai'] - previous['ai']) / elapsed
                count = max(1, snapshot['ai'] - previous['ai'])
                output_count = max(1, snapshot['output_jobs'] - previous['output_jobs'])
                logging.info("AI %.1f FPS, sent %.1f FPS, capture %.1f FPS; prepare %.1f ms, detect %.1f ms; "
                             "output render/encode/send %.1f/%.1f/%.1f ms per frame; dropped input/output %s/%s",
                             count / elapsed, (snapshot['sent'] - previous['sent']) / elapsed,
                             (snapshot['captured'] - previous['captured']) / elapsed,
                             (snapshot['prepare'] - previous['prepare']) * 1000 / count,
                             (snapshot['detect'] - previous['detect']) * 1000 / count,
                             (snapshot['render'] - previous['render']) * 1000 / output_count,
                             (snapshot['encode'] - previous['encode']) * 1000 / output_count,
                             (snapshot['send'] - previous['send']) * 1000 / output_count,
                             snapshot['dropped_input'] - previous['dropped_input'],
                             snapshot['dropped_output'] - previous['dropped_output'])
                previous, window_start = snapshot, time.monotonic()
            if ENABLE_WINDOW_KEYS and cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q'), 27):
                break
    except KeyboardInterrupt:
        logging.info("User stopped video")
        record_experiment('视频停止', '用户停止')
    finally:
        stopped.set()
        if buzzer_link is not None:
            buzzer_link.close()
        if reader.ident is not None:
            reader.join(timeout=1)
        try:
            cap.release()
        finally:
            if reader.is_alive():
                reader.join(timeout=0.5)
            if sender.ident is not None:
                sender.join(timeout=1)
            try:
                stop_control_thread()
            finally:
                cv2.destroyAllWindows()

# ==================== 08 输入增强与重复框过滤 ====================
# 可选增强不改变坐标；同类框按重叠程度过滤，head/hat 仅在高度重叠时互斥。

def enhance_detection_frame(frame, clahe):
    # 只调整亮度通道，保持尺寸和位置不变，输出画面仍使用原始图像。
    if clahe is None:
        return frame
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

def detection_iou(first, second):
    width = max(0, min(first.right, second.right) - max(first.left, second.left))
    height = max(0, min(first.bottom, second.bottom) - max(first.top, second.top))
    intersection = width * height
    area_a = max(0, first.right - first.left) * max(0, first.bottom - first.top)
    area_b = max(0, second.right - second.left) * max(0, second.bottom - second.top)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0

def remove_duplicate_boxes(results):
    if not REMOVE_DUPLICATES:
        return results
    kept = []
    for item in sorted(results, key=lambda value: value.prop, reverse=True):
        if item.right <= item.left or item.bottom <= item.top:
            continue
        duplicate = False
        for previous in kept:
            if item.id == previous.id:
                threshold = DUPLICATE_IOU
            elif {item.id, previous.id} == {0, 1}:
                threshold = CROSS_CLASS_IOU
            else:
                continue
            if detection_iou(item, previous) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept

# ==================== 09 识别统计与图像发送 ====================
# 保留原有小端16字节分包头；发送失败记录到终端，输出线程不无限等待。

def send_udp_payload(payload, destination):
    global global_id
    view = memoryview(payload).cast('B')
    with global_id_lock:
        global_id = (global_id + 1) & 0xffffffff
        group = global_id
    count = (len(view) + max_packet_size - 1) // max_packet_size
    try:
        for index in range(count):
            part = view[index * max_packet_size:(index + 1) * max_packet_size]
            header = struct.pack('<IIII', group, count, index, len(part))
            if hasattr(udp_socket, 'sendmsg'):
                udp_socket.sendmsg([header, part], [], 0, destination)
            else:
                udp_socket.sendto(header + part.tobytes(), destination)
        return True
    except OSError:
        logging.exception("UDP send failed")
        return False

def send_msginfo(msginfo_bytes):
    return send_udp_payload(msginfo_bytes, dest_addr2)

def send(img_bytes):
    return send_udp_payload(img_bytes, dest_addr)

# ==================== 10 可选云台控制 ====================
# 仅在开启云台时运行；根据目标相对画面中心的位置决定移动方向。

def set_control_flags(direction):
    global control_flags
    with control_lock:
        control_flags = direction

def get_control_flags():
    with control_lock:
        return control_flags

def update_control_from_target(center_x, center_y, frame_width, frame_height):
    global control_flags
    frame_center_x = frame_width / 2.0
    frame_center_y = frame_height / 2.0
    dx = center_x - frame_center_x
    dy = center_y - frame_center_y

    if abs(dx) <= OFFSET_TRED and abs(dy) <= OFFSET_TRED:
        target_direction = 8
    elif dx > OFFSET_TRED:
        if dy > OFFSET_TRED:
            target_direction = 4
        elif dy < -OFFSET_TRED:
            target_direction = 5
        else:
            target_direction = 0
    elif dx < -OFFSET_TRED:
        if dy > OFFSET_TRED:
            target_direction = 6
        elif dy < -OFFSET_TRED:
            target_direction = 7
        else:
            target_direction = 1
    else:
        if dy > OFFSET_TRED:
            target_direction = 3
        else:
            target_direction = 2

    with control_lock:
        if last_direction == 8:
            control_flags = target_direction
        elif last_direction != target_direction:
            control_flags = 8

def _async_control_worker():
    # 异步控制工作线程
    global _control_running,last_direction,control_flags,modStatus,use_ptz
    with control_lock:
        last_direction = 4
    
    while _control_running:
        try:
            # 获取当前方向
            current_direction = get_control_flags()
            # 只有方向改变时才发送命令
            if modules is not None and modStatus==0:
                if modules.isModReady(ptzModIndex)==1:
                    # 云台模块恢复在线后尝试重新连接。
                    ret = modules.modConnect(ptzModIndex)
                    if ret == 1:
                        modStatus = 1
            with control_lock:
                previous_direction = last_direction
            if current_direction != previous_direction:
                if use_ptz==1:
                    ret = modules.PtzControl(current_direction,ptzSpeed)
                    if ret<0:
                        modStatus = 0
                with control_lock:
                    last_direction = current_direction
            
            # 控制发送频率，避免过快发送
            time.sleep(0.05)
            
        except Exception:
            logging.exception("control thread failed")
            time.sleep(0.1)

def start_control_thread():
    # 启动控制线程
    global _control_thread, _control_running
    if _control_thread is None or not _control_thread.is_alive():
        _control_running = True
        _control_thread = Thread(target=_async_control_worker, daemon=True)
        _control_thread.start()
        logging.info("control thread started")

def stop_control_thread():
    # 停止控制线程
    global _control_running
    _control_running = False
    if _control_thread:
        _control_thread.join(timeout=1)
        logging.info("control thread stopped")

def update_ptz_from_results(results, src_img):
    # 关闭云台时不查询图像尺寸、不选择目标，也不更新方向。
    if use_ptz != 1:
        return
    if not results:
        set_control_flags(8)
        return
    target = max(results, key=lambda item: item.right - item.left)
    update_control_from_target((target.left + target.right) / 2.0,
                               (target.top + target.bottom) / 2.0,
                               getImageWidth(src_img) or FRAME_WIDTH,
                               getImageHeight(src_img) or FRAME_HEIGHT)

# ==================== 11 模型属性缓存与推理 ====================
# 缓存固定输出属性；保持模型预处理、推理和后处理规则，可靠释放原生输出句柄。

def reset_output_metadata():
    global _output_metadata, _output_metadata_key
    _output_metadata = None
    _output_metadata_key = None

def get_output_metadata():
    # 固定模型的输出网格和量化参数不随帧变化，首次读取后复用。
    global _output_metadata, _output_metadata_key
    key = (modWidth, modHeight, bQuant)
    if _output_metadata is not None and _output_metadata_key == key:
        return _output_metadata
    metadata = []
    for index in range(3):
        grid_h = getOutputAttrDim(index, 2)
        grid_w = getOutputAttrDim(index, 3)
        if grid_h <= 0 or grid_w <= 0:
            raise RuntimeError('Invalid model output dimensions')
        stride = int(modWidth / grid_h)
        # 非量化模型不读取用不到的量化参数。
        zp = getOutputZp(index) if bQuant != 0 else 0
        scale = getOutputScale(index) if bQuant != 0 else 1.0
        metadata.append((grid_h, grid_w, stride, zp, scale))
    _output_metadata = tuple(metadata)
    _output_metadata_key = key
    return _output_metadata

def detect(src_img):
    # 执行 RKNN 推理，返回状态、head 数量、hat 数量和检测结果列表。
    hatnum = 0
    headnum = 0
    outputs = 0
    ret = convertImageWithLetterbox(src_img,destImage,letter_box,114)
    if ret==-1:
        return -1,0,0,[]
    # 配置当前图像的模型输入属性。
    ret = setRknnInput(0,RKNN_TENSOR_UINT8,RKNN_TENSOR_NHWC,modWidth,modHeight,modChannel,destImage)
    if ret == -1:
        return -1,0,0,[]
    # 执行模型推理。
    ret = startRknnRun()
    if ret==-1:
        return -1,0,0,[]
    # 根据模型量化类型初始化输出缓冲区。
    outputs = initOutputsObj(bQuant)
    if outputs==0:
        return -1,0,0,[]
    try:
        # 获取底层后处理结果，转换为 Python 检测框。
        ret = getRknnOutpus(outputs)
        if ret == -1:
            return -1,0,0,[]
        validCount = 0
        initProcessOutputData();
        result = []
        x_pad = getLetterBoxXPad(letter_box)
        y_pad = getLetterBoxYPad(letter_box)
        letterbox_scale = getLetterBoxScale(letter_box)
        for i, (grid_h, grid_w, stride, zp, scale) in enumerate(get_output_metadata()):
            if bQuant == 0:
                validCount+=StartProcessFp32(i,outputs,grid_h,grid_w,modHeight,modWidth,stride,BOX_THRESH)
            else:
                validCount+=StartProcessI8(i,outputs,grid_h,grid_w,modHeight,modWidth,stride,BOX_THRESH,zp,scale)
        StartNms(validCount,NMS_THRESH)
        if validCount>0:
            for j in range(validCount):
            
                n = getIndexArray(j)
                if n == -1:
                    continue
                # 沿用原置信度判定，在跨库读取框坐标前排除不会显示的候选。
                obj_conf = getObjProbs(j)
                if not obj_conf > CONFIDENCE_VAL:
                    continue
                id = getClassId(n)
            
                x1 = getFilterBoxes(n * 4 + 0) - x_pad
                y1 = getFilterBoxes(n * 4 + 1) - y_pad
                x2 = x1 + getFilterBoxes(n * 4 + 2)
                y2 = y1 + getFilterBoxes(n * 4 + 3)
                left =int( clamp(x1,0,modWidth) / letterbox_scale)
                top = int(clamp(y1,0,modHeight) / letterbox_scale)
                right =int( clamp(x2,0,modWidth) / letterbox_scale)
                bottom =int( clamp(y2,0,modHeight) / letterbox_scale)
                result.append(detectResult(left,top,right,bottom,obj_conf,id))
            # 统计、绘制和云台选取统一使用去重后的结果。
            result = remove_duplicate_boxes(result)
            headnum = sum(item.id == 0 for item in result)
            hatnum = sum(item.id == 1 for item in result)
        update_ptz_from_results(result, src_img)
        return 0,headnum,hatnum,result
    finally:
        releaseRknnOutput(outputs)

def initYoloModel(model_path):
     reset_output_metadata()
     ret = modInit(model_path.encode('utf-8'))
     if ret != 0:
         print("mod init failed")
         return -1;
     readRknnInputAndOutputAttr()
            
     return ret

def uninitYolodModel():
    reset_output_metadata()
    return uninitlib()

# ==================== 12 图片与视频入口 ====================
# 支持单张测试图片或实时摄像头；当前程序入口默认使用实时视频。

def check_input_type(input_path):
    # 根据输入类型处理单张图片或摄像头视频流。
    if input_path.endswith(('.jpg', '.png', '.jpeg', '.bmp')):
        src_img = readImage(input_path.encode('utf-8'))
        if src_img == 0:
            print('打开文件失败，请重试！')
            return -1,0,0
        try:
            ret,headnum,hatnum,results=detect(src_img)
        finally:
            releaseImg(src_img)
        
        img0 = cv2.imread(input_path)
        if ret == 0:
            for item in results:
                draw_detect_result(img0, item)
        send_msginfo(bytes(str(hatnum) + ',' + str(headnum), encoding='utf-8'))
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        _, img_encoded = cv2.imencode('.jpg', img0, encode_params)
        send(img_encoded.tobytes())
        
        
    elif input_path == 'video':
        cap, first_frame = open_camera()
        if cap is None:
            record_experiment('摄像头连接', '失败', error='所有采集模式均无法读取有效帧')
            return
        clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)) if ENHANCE_INPUT else None
        run_live_video(cap, first_frame, clahe)
    else:
        print('输入非正确格式，重新输入！')

# ==================== 13 原版本兼容接口 ====================
# 保留原接口供其他调用方使用；当前同帧视频主流程不启动这些旧异步识别和发送线程。

def prepare_preview(frame):
    if PREVIEW_MAX_WIDTH <= 0 or frame.shape[1] <= PREVIEW_MAX_WIDTH:
        return frame
    height = max(1, round(frame.shape[0] * PREVIEW_MAX_WIDTH / frame.shape[1]))
    return cv2.resize(frame, (PREVIEW_MAX_WIDTH, height), interpolation=cv2.INTER_AREA)

def put_latest(queue, value):
    # 队列只保留最新帧，处理不过来时丢弃旧帧。
    try:
        queue.put_nowait(value)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(value)
        except Full:
            pass

def set_parseing(value):
    global _parseing
    with _parse_state_lock:
        _parseing = value

def is_parseing():
    with _parse_state_lock:
        return _parseing

def set_ai_results(results):
    global _AIParseResult
    with _ai_result_lock:
        _AIParseResult = list(results)

def get_ai_results_snapshot():
    with _ai_result_lock:
        return list(_AIParseResult)

def _async_AIParse_worker():
    # 后台消费视频帧，执行 RKNN 检测并缓存最新识别结果。
    global _parse_video
    while _parse_video:
        frame = None
        src_img = None
        try:
            frame = _frame_queue.get(timeout=0.1)
            if frame is None:
                break
            set_parseing(True)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            data_size = frame.nbytes
            src_img = getImageFromVideoFrame(width,height,data_size,IMAGE_FORMAT_RGB888,frame_rgb.ctypes.data_as(ctypes.c_char_p))
            ret,headnum,hatnum,results=detect(src_img)
            if ret == 0:
                set_ai_results(results)
            else:
                set_ai_results([])
            send_msginfo(bytes(str(hatnum) + ',' + str(headnum), encoding='utf-8'))
        except Empty:
            continue
        except Exception:
            logging.exception("AI parse worker failed")
            set_ai_results([])
        finally:
            if src_img:
                releaseImg(src_img)
            if frame is not None:
                _frame_queue.task_done()
            set_parseing(False)

def start_async_parsingthread():
    # 启动异步 AI 识别线程。
    global _parse_thread, _parse_video
    if _parse_thread is None or not _parse_thread.is_alive():
        _parse_video = True
        logging.info("start ai parse thread")
        _parse_thread = Thread(target=_async_AIParse_worker, daemon=True)
        _parse_thread.start()

def stop_async_parsingthread():
    # 停止异步 AI 识别线程。
    global _parse_video
    _parse_video = False
    if _parse_thread:
        try:
            _frame_queue.put_nowait(None)
        except Full:
            pass
        _parse_thread.join(timeout=1)

def send_video_frame_async(img_bytes):
    # 把视频帧放入 AI 识别队列，队列满时丢弃当前帧。
    try:
        _frame_queue.put_nowait(img_bytes)
    except Full:
        pass
    except Exception:
        logging.exception("failed to enqueue frame for AI parsing")

def _async_send_worker():
    # 后台发送 JPEG 图像 UDP 分包。
    global _send_running
    while _send_running:
        img_bytes = None
        try:
            img_bytes = _send_queue.get(timeout=0.1)
            if img_bytes is None:
                break
            packets = getUdpPackages(img_bytes)
            for packet in packets:
                udp_socket.sendto(packet.toNetBytes(), dest_addr)
        except Empty:
            continue
        except Exception:
            logging.exception("async UDP sender failed")
        finally:
            if img_bytes is not None:
                _send_queue.task_done()

def start_async_sender():
    # 启动异步 UDP 图像发送线程。
    global _send_thread, _send_running
    if _send_thread is None or not _send_thread.is_alive():
        _send_running = True
        _send_thread = Thread(target=_async_send_worker, daemon=True)
        _send_thread.start()

def stop_async_sender():
    # 停止异步 UDP 图像发送线程。
    global _send_running
    _send_running = False
    if _send_thread:
        try:
            _send_queue.put_nowait(None)
        except Full:
            pass
        _send_thread.join(timeout=1)

def getUdpPackages(bytes_data):
    # 为一段数据生成带递增分组 id 的 UDP 分包。
    global global_id
    with global_id_lock:
        global_id += 1
        packet_group_id = global_id
    return buildUdpPackages(bytes_data, packet_group_id, max_packet_size)

class detResultBox:
    # 低层后处理检测框数据结构。

    def __init__(self, left, top,right,bottom,prop,cls_id):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.prop = prop
        self.cls_id = cls_id

def send_async(img_bytes):
    # 把编码后的图像放入异步 UDP 发送队列。
    try:
        _send_queue.put_nowait(img_bytes)
    except Full:
        pass
    except Exception:
        logging.exception("failed to enqueue frame for UDP sending")

def convert_image_buffer_to_cv2(virtaddr,width,height,size,fmt):
    # 把底层图像缓存转换为 OpenCV BGR 图像。
    buffer_bytes = ctypes.string_at(virtaddr, size)
    buffer_array = np.frombuffer(buffer_bytes, dtype=np.uint8)
    img = buffer_array.reshape((height, width, 3))
    if fmt == IMAGE_FORMAT_RGB888:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        raise ValueError(f"Unsupported image format: {fmt}")
    img = img.copy()
    return img

# ==================== 14 初始化、运行与清理 ====================
# 初始化设备及模型，建立推理缓冲区；运行结束后释放模型、图像与模块连接。
# 运行：在本目录执行 python3 Shandong2026_T3_Helmet.py，默认通过摄像头完成四种场景验证。
# 运行前保存用户设置，结束后提交本次CSV汇总表及同目录自动保存的Python入口源码。
# 依赖OpenCV、NumPy、配套接口及动态库，以及model目录中的RKNN模型。

if __name__ == '__main__':
    is_video = True
    img_path = 'testimg/test1.jpg'
    model_attempted = False
    module_connection_attempted = False
    try:
        experiment_log = CsvExperimentLog(experiment_info)
    except Exception:
        logging.exception('实验文件创建失败，请检查实验信息和桌面写入权限')
        raise
    try:
        record_experiment('程序启动', '开始')
        # 模块初始化
        modules = SensorModule()
        # 开始搜索模块
        modules.startScanSensors()
        # 连接配置的实训箱设备模块
        module_connection_attempted = True
        ret = modules.modConnect(ptzModIndex)
        if ret<=0:
            print("主控模块连接失败")
        else:
            print("主控模块连接正常")
        model_path = MODEL_PATH
        model_attempted = True
        initYoloModel(model_path)
        fmt = getInputAttrFmt(0)
        if fmt == RKNN_TENSOR_NCHW:
            # NCHW 布局按批次、通道、高度、宽度排列。
            modWidth = getInputAttrDim(0,3)
            modHeight = getInputAttrDim(0,2)
            modChannel = getInputAttrDim(0,1)
        else:
            # NHWC 布局按批次、高度、宽度、通道排列。
            modWidth = getInputAttrDim(0,2)
            modHeight = getInputAttrDim(0,1)
            modChannel = getInputAttrDim(0,3)
        bQuant = isQuant()
        # 初始化推理图像缓冲区，格式为 RGB888
        destImage = initInferenceImg(modWidth,IMAGE_FORMAT_RGB888,modHeight)
        # 创建模型输入等比例缩放及填充所需的 letterbox 句柄。
        letter_box = initLetterBox()
        if is_video:
            check_input_type('video')
        else:
            check_input_type(img_path)
    except KeyboardInterrupt:
        record_experiment('程序停止', '用户停止')
    except Exception as error:
        record_experiment('程序运行', '失败', error=f'{type(error).__name__}: {error}')
        logging.exception('程序运行失败')
    finally:
        # 清理操作逐项尝试；先停止工作线程，最后注销共享驱动并排空 CSV 队列。
        actions = [('停止旧识别线程', stop_async_parsingthread), ('停止云台线程', stop_control_thread)]
        if letter_box:
            actions.append(('释放 letterbox', lambda: releaseLetterBox(letter_box)))
        if destImage:
            actions.append(('释放推理图像', lambda: releaseImg(destImage)))
        if model_attempted:
            actions.append(('卸载模型', uninitYolodModel))
        if modules is not None:
            if module_connection_attempted:
                actions.append(('断开主控模块', lambda: modules.modDisconnect(ptzModIndex)))
            actions.append(('注销设备驱动', modules.uninit))
        actions.append(('关闭 UDP', udp_socket.close))
        for name, action in actions:
            try:
                result = action()
                if isinstance(result, int) and result < 0:
                    raise RuntimeError(f'返回值：{result}')
            except Exception as error:
                record_experiment(name, '失败', error=str(error))
                logging.exception('%s失败', name)
        record_experiment('程序结束', '结束')
        experiment_log.close()
