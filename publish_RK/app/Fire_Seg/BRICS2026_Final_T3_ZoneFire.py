#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
# 标准库负责参数读取、计时、日志、退出信号、路径与队列访问。
import argparse
import importlib
import json
import logging
import platform
import signal
import sys
import time
from pathlib import Path
from queue import Empty
from dataclasses import replace
import math

# 配套模块负责实验归档、声音请求与中文区域绘制；导入时不打开硬件。
from zone_teaching_support import ZoneCommands, ZoneSession, ZoneOverlay, PermitWindow, validate_display

# ==================== 02 用户设置 ====================

# ==================== 考试任务：施工现场分区动火预警 ====================
# 某房屋建筑工程正处于主体结构施工阶段。项目部将本次工作定名为“分区动火预警调试”，
# 选取“施工现场监控点01”开展模拟测试，验证不同施工区域的火焰识别、动火授权时效及蜂鸣器联动功能。
#
# 该监控点覆盖钢筋加工区、临时作业区和材料堆放区，三个区域分别位于同一监控画面的左侧、中部和右侧。
# 钢筋加工区本次安排焊接作业，已办理相应动火审批；临时作业区未安排动火作业；
# 材料堆放区存放木模板、保温材料等可燃物，禁止动火。
#
# 为便于现场辨识，三个区域的范围框及名称背景应分别设置为：
# 钢筋加工区使用纯绿色，临时作业区使用纯黄色，材料堆放区使用纯红色。
#
# 项目部要求根据作业区域和动火授权状态，实现以下预警功能：
# 1. 钢筋加工区：授权有效期间识别到作业火焰时，蜂鸣器保持静音；
#    授权失效后识别到火焰时，发出“提示音1”。
# 2. 临时作业区：识别到火焰时，蜂鸣器发出“提示音2”。
# 3. 材料堆放区：识别到火焰时，蜂鸣器发出“警报音”，其他区域的动火审批不得免除该区警报。
#
# 现由你使用实训箱及相关配件完成模拟调试。应分别验证材料区、临时作业区，
# 以及钢筋区授权有效和授权失效两个时段的识别与报警表现，完成四项成果记录，
# 并提交程序源码及CSV数据记录文件。

# ====================================================
# 请阅读顶部任务背景，在本分区调整区域配色及联动判断，并验证运行效果。
# !!!!!!!!!!!!!!!!!!!! 检查项：请查找 TODO 1 和 TODO 2 !!!!!!!!!!!!!!!!!!!!
# TODO 1：按任务要求设置三个区域的范围框及底部区域名称背景颜色。
# TODO 2：检查并调整示例判断，补全三个区域及钢筋区授权前后的处理，并逐项验证。
# 当前示例可以运行；请依据任务要求检查并完善区域配色和联动判断。
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# 以下为示例信息，请填写个人信息，并依据顶部任务背景修改项目和位置。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "实验",
    "监测点位": "实训区",
}

# >>>>>>>>>>>>>>>>>>>> TODO 1：区域配色设置区 >>>>>>>>>>>>>>>>>>>>
# 按顶部任务要求设置三个区域的范围框及底部名称背景颜色；火焰检测框配色不在此处修改。
# 使用BGR（蓝、绿、红）顺序，每个数值为0至255的整数；标签文字由系统自动选择深浅。
# 以下默认沿用原来的蓝色，需学生按任务要求修改，保存并重启后生效。
COLOR_REBAR_AREA = (255, 128, 0)          # 左侧：钢筋加工区
COLOR_TEMPORARY_WORK_AREA = (255, 128, 0) # 中间：临时作业区
COLOR_MATERIAL_AREA = (255, 128, 0)       # 右侧：材料堆放区
# <<<<<<<<<<<<<<<<<<<< TODO 1：设置区结束 <<<<<<<<<<<<<<<<<<<<<<



# >>>>>>>>>>>>>>>>>>>> TODO 2：功能检查区 >>>>>>>>>>>>>>>>>>>>
# 编写位置：在下方control_buzzer(...)函数内编写联动判断。
# 下方仅提供待完善的基础示例，并非完整答案。
# 请依据题目核对已有判断条件和声音接口，按需修改并补全缺少的处理，不能只追加分支而忽略现有示例。

# 推荐使用语法：
# 使用 Python 的 if / elif / else 编写条件判断。
# and：逻辑与，表示“并且”；连接的两个条件都为 True 时，整体条件才为 True。
# not：逻辑非，对布尔值取反；not True 为 False，not False 为 True。
# 写法示例：条件1 and 条件2，表示两个条件必须同时满足。

# 可调用变量：
# material_fire_count：右侧材料堆放区的火焰数量，整数；大于0表示该区有火焰。
# rebar_fire_count：左侧钢筋加工区的火焰数量，整数；大于0表示该区有火焰。
# temporary_work_fire_count：中间临时作业区的火焰数量，整数；大于0表示该区有火焰。
# permit_valid：系统提供的钢筋区限时授权状态，布尔值。
# True 表示授权有效，False 表示授权已到期；Python 布尔值首字母大写。
# 首帧推理成功后开始计时，默认授权60秒；未满60秒为 True，达到60秒时自动切换为 False，之后不自动续期。

# 可调用接口：
# buzzer.alarm()：请求警报音。
# buzzer.notice()：请求提示音1。
# buzzer.notice2()：请求提示音2。
# buzzer.reset()：请求静音、停止后续循环；正在执行的一组按原流程结束。

def control_buzzer(material_fire_count, rebar_fire_count, temporary_work_fire_count, permit_valid):
    # >>>>>>>>>>>>>>>>>>>> TODO 2：功能检查区 >>>>>>>>>>>>>>>>>>>>
    # 请依据任务背景调整或补全下方代码，覆盖三个区域及钢筋区授权前后的响应。
    if material_fire_count > 1:
        buzzer.notice()
    else:
        buzzer.reset()
    # <<<<<<<<<<<<<<<<<<<< TODO 2：修改区结束 <<<<<<<<<<<<<<<<<<<<<<

# ==================== 03 系统配置 ====================
# 以下为实训箱调试参数，本次任务通常无需修改。
# 请求分辨率不代表设备一定支持，以终端日志中的实际采集尺寸为准。
# 钢筋区授权时长在本系统配置区调整；区域颜色见“02 用户设置”。

# 路径与日志
# 路径以本文件所在目录为基准，避免从其他目录启动时找不到模型或字体。
ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('fire_yolo26_v20')
DEFAULT_MODEL = ROOT / 'model/fire_yolo26.rknn'
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

# 模型与类别顺序
# 模型路径相对于本文件；类别名称从配套模型说明中读取，必须与训练时的类别顺序一致。
# 当前模型为fire、smoke两类，系统仅处理fire；不要通过删除标签来改变类别编号。
MODEL_PATH = ROOT / 'model/fire_yolo26.rknn'

# 钢筋区实际授权时长（便于完成测试，不作为区域配色考点）
# 可改为有限正数，单位秒；留足授权期间展示火焰的时间，保存并重启生效。
PERMIT_DURATION = 60

# 摄像头与NPU推理
# 高置信度火焰显示红色，低置信度实测续跟显示黄色；低分结果不触发声音，本帧漏检立即无框。
CAMERA_INDEX = 41  # 摄像头设备编号
NPU_CORE = 'auto'  # auto自动选择；也可选0、1、2、all
FRAME_WIDTH, FRAME_HEIGHT = 1920, 1080  # 请求采集宽度、高度，像素；不支持时按原流程回退
CONFIDENCE_HIGH = 0.5  # 新目标发现与报警统计的高置信度阈值
CONFIDENCE_LOW = 0.25  # 已有火焰目标的实测续跟阈值，低分不触发报警

# 区域范围与中文显示
# 画面固定按宽度三等分；左侧钢筋加工区，中间临时作业区，右侧材料堆放区。
# 区域中文在各框底部居中显示，名称由左至右排列，字体使用包内指定文件。
REGION_NAMES = ("钢筋加工区", "临时作业区", "材料堆放区")  # 左、中、右显示名称
FONT_PATH = ROOT / 'Arial-Unicode.ttf'  # 中文字体，需与代码一起部署
SHOW_REGIONS = True  # 显示三区范围框和底部名称
SHOW_AUTH_STATUS = True  # 显示配置区域的当次授权状态
SHOW_STATS = True  # 显示火焰数量、推理耗时和帧率
REGION_LINE_WIDTH = 2  # 区域框线宽，像素
REGION_FONT_SIZE = 28  # 区域名称最大字号
REGION_TEXT_COLOR = (255, 255, 255)  # 授权状态文字颜色；底部名称自动选择深色或白色
REGION_BOTTOM_MARGIN = 12  # 底部文字边距，预览画面像素
REGION_STATUS_FONT_SIZE = 18  # 授权状态最大字号
AUTH_STATUS_POSITION = (6, 40)  # 授权状态左上角位置，预览画面像素

# 识别框、标签与回传画面
# 检测框与标签背景共用颜色；标签显示当前帧实际置信度，文字按背景亮度自动选色。
COLOR_FIRE_HIGH = (0, 0, 255)  # 高置信度火焰，红色
COLOR_FIRE_LOW = (0, 210, 255)  # 低置信度实测续跟，黄色
BOX_LINE_WIDTH = 2  # 识别框线宽，像素
LABEL_FONT_SCALE = 0.6  # 识别标签字体比例
LABEL_LINE_WIDTH = 1  # 识别标签文字线宽，像素
BRIGHT_LABEL_TEXT = (30, 30, 30)  # 浅色标签背景上的深色文字
DARK_LABEL_TEXT = (255, 255, 255)  # 深色标签背景上的白色文字
STATS_POSITION = (10, 25)  # 统计信息位置，预览画面像素
STATS_FONT_SCALE = 0.55  # 统计信息字体比例
STATS_TEXT_COLOR = (255, 255, 0)  # 统计文字颜色
STATS_LINE_WIDTH = 2  # 统计文字线宽
PREVIEW_LONG_EDGE = 720  # 视频预览最长边，像素；只缩小不放大，0保持原尺寸
JPEG_QUALITY = 60  # JPEG质量，1至100；越高数据量越大

# 蜂鸣器与实验归档
# 系统在后台执行鸣叫，用户判断函数无需编写循环或等待。
# 三种分区声音沿用配套模块SOUND_PATTERNS：警报音三声、提示音一声、提示音2两声。
# BEEP通用节奏参数保留以兼容原支持模块，分区声音以SOUND_PATTERNS为准。
ENABLE_BUZZER = True  # False关闭设备联动，识别和软件核验继续运行
BUZZER_MODULE_INDEX = 2  # 蜂鸣器模块编号
BUZZER_REPEAT = True  # True循环提示，False单组提示
DETECTION_CONFIRM_TIME = 0.3  # 响应条件持续成立的确认时间，秒
DETECTION_RESET_TIME = 1.0  # 单组模式下，条件持续不成立后的复位时间，秒
BEEP_COUNT = 2  # 通用每组鸣叫次数
BEEP_DURATION = 0.2  # 通用每声持续时间，秒
BEEP_INTERVAL = 0.1  # 通用组内静音时间，秒
BEEP_REPEAT_INTERVAL = 1.0  # 通用组间静音时间，秒
BUZZER_SCAN_WAIT = 2.0  # 等待驱动完成模块扫描，秒
BUZZER_RESULT_TIMEOUT = 1.0  # 超过此时间无有效判断，不再启动下一组，秒
SENSOR_LIB = ROOT / 'libSmartSensorDriver.so'  # 配套传感器驱动动态库
RESULTS_DIR = None  # None按当前用户桌面归档；可改为实验专用目录

# 本教学版固定不启用云台，避免与蜂鸣器共用驱动生命周期。


# ==================== 04 运行状态与配置校验 ====================
# 以下对象由系统维护，保存中文图层缓存并收集声音请求，无需在实训中修改。
_zone_overlay = None  # 中文区域图层按实际画面尺寸缓存
buzzer = ZoneCommands()  # 提交模式请求的接口；不是底层驱动

# 区域统计：使用原图坐标判断火焰中心，分界点归右侧，避免重复计数。
# 参数results由识别流程提供，只包含本帧高置信度火焰；frame_size为原图的高、宽。
def count_fire_regions(results, frame_size):
    # results由系统提供，仅包含本帧高置信度火焰；坐标为原图像素。
    width = frame_size[1]
    rebar_count = temporary_work_count = material_count = 0
    for fire in results:
        x1, y1, x2, y2 = fire.box
        # 使用原图坐标计算火焰框中心。
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        # 按画面三等分归类，分界点归右侧，避免重复计数。
        if not (0 <= center_x < width and 0 <= center_y < frame_size[0]):
            continue
        if center_x < width // 3:
            rebar_count += 1
        elif center_x < 2 * width // 3:
            temporary_work_count += 1
        else:
            material_count += 1
    return material_count, rebar_count, temporary_work_count


# 配置采集与启动校验：记录本次实际设置，预先检查中文字体与参数。
def permit_enabled():
    # 本题固定为钢筋区的一次限时授权；保留接口，不读取学生作答文字。
    return True


def display_config():
    result = {key: globals()[key] for key in (
        'REGION_NAMES','FONT_PATH','SHOW_REGIONS','SHOW_AUTH_STATUS','SHOW_STATS',
        'REGION_LINE_WIDTH','REGION_FONT_SIZE','REGION_TEXT_COLOR',
        'REGION_BOTTOM_MARGIN','REGION_STATUS_FONT_SIZE',
        'AUTH_STATUS_POSITION','COLOR_FIRE_HIGH','COLOR_FIRE_LOW','BOX_LINE_WIDTH',
        'LABEL_FONT_SCALE','LABEL_LINE_WIDTH','BRIGHT_LABEL_TEXT','DARK_LABEL_TEXT',
        'STATS_POSITION','STATS_FONT_SCALE','STATS_TEXT_COLOR','STATS_LINE_WIDTH',
        'PREVIEW_LONG_EDGE','JPEG_QUALITY','FRAME_WIDTH','FRAME_HEIGHT')}
    result['REGION_COLORS'] = (COLOR_REBAR_AREA, COLOR_TEMPORARY_WORK_AREA, COLOR_MATERIAL_AREA)
    result['PERMIT_VALID'] = permit_enabled()
    result['PERMIT_REGION'] = '钢筋加工区'
    return result


def get_zone_overlay():
    global _zone_overlay
    if _zone_overlay is None:
        _zone_overlay = ZoneOverlay(FONT_PATH, display_config())
    return _zone_overlay


def teaching_config(enabled):
    PermitWindow(permit_enabled(), PERMIT_DURATION)  # 校验时长，不开始计时。
    validate_display(display_config())
    for key in ('BOX_LINE_WIDTH','LABEL_LINE_WIDTH','STATS_LINE_WIDTH'):
        if type(globals()[key]) is not int or globals()[key] <= 0:
            raise ValueError(key+'必须为正整数。')
    for key in ('LABEL_FONT_SCALE','STATS_FONT_SCALE'):
        if not math.isfinite(globals()[key]) or globals()[key] <= 0:
            raise ValueError(key+'必须为有限正数。')
    get_zone_overlay()  # 启动时验证字体与Pillow，避免后台输出才报错。
    for name, color in (('COLOR_FIRE_HIGH', COLOR_FIRE_HIGH), ('COLOR_FIRE_LOW', COLOR_FIRE_LOW)):
        if not isinstance(color, (tuple, list)) or len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
            raise ValueError('{} 必须是三个0..255整数的BGR颜色。'.format(name))
    return {'ENABLE_BUZZER': enabled, 'BUZZER_MODULE_INDEX': BUZZER_MODULE_INDEX,
            'BUZZER_REPEAT': BUZZER_REPEAT, 'CONFIRM_TIME': DETECTION_CONFIRM_TIME,
            'RESET_TIME': DETECTION_RESET_TIME, 'BEEP_COUNT': BEEP_COUNT,
            'BEEP_DURATION': BEEP_DURATION, 'BEEP_INTERVAL': BEEP_INTERVAL,
            'BEEP_REPEAT_INTERVAL': BEEP_REPEAT_INTERVAL, 'SCAN_WAIT': BUZZER_SCAN_WAIT,
            'RESULT_TIMEOUT': BUZZER_RESULT_TIMEOUT, 'SENSOR_LIB': str(SENSOR_LIB),
            'COLOR_FIRE_HIGH': COLOR_FIRE_HIGH, 'COLOR_FIRE_LOW': COLOR_FIRE_LOW,
            'FONT_PATH': str(FONT_PATH),
            'PERMIT_REGION': '钢筋加工区', 'PERMIT_VALID': permit_enabled(), 'PERMIT_DURATION': PERMIT_DURATION, 'REGION_ORDER': list(REGION_NAMES), 'DISPLAY': display_config()}


# ==================== 05 启动参数与环境检查 ====================
# 直接运行时使用顶部设置；命令行参数用于设备调试，覆盖本次运行的默认值。
# 环境检查只读取依赖、模型和字体，不启动NPU或蜂鸣器。
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='YOLO26 V20 火焰教学版：仅RKNN模型，使用RK3588 NPU推理，兼容原 Fire_Seg 接口')
    parser.add_argument('--model', type=Path, default=MODEL_PATH, help='YOLO26 .rknn 或含单个RKNN的导出目录；必须使用NPU')
    parser.add_argument('--source', default=str(CAMERA_INDEX), help='摄像头编号、/dev/video41、图片、视频、RTSP地址')
    parser.add_argument('--labels', nargs='+', help='缺少模型元数据时，按训练类别ID顺序填写，如 --labels fire smoke')
    parser.add_argument('--fire-class', type=int, help='火焰类别ID；默认在模型标签中匹配fire/flame/火焰')
    parser.add_argument('--imgsz', type=int, default=640, help='没有元数据的RKNN输入尺寸，默认640')
    parser.add_argument('--output-format', choices=['auto', 'ultralytics_raw', 'end2end', 'rockchip_yolo26'], default='auto')
    parser.add_argument('--boxes-output', type=int, help='Rockchip双输出坐标分支索引，0或1')
    parser.add_argument('--scores-output', type=int, help='Rockchip双输出分数分支索引，0或1')
    coordinates = parser.add_mutually_exclusive_group()
    coordinates.add_argument('--normalized-boxes', action='store_true', dest='normalized_boxes', help='坐标按输入宽高归一化，适配没有元数据的INT8导出')
    coordinates.add_argument('--pixel-boxes', action='store_false', dest='normalized_boxes', help='明确使用像素坐标')
    parser.set_defaults(normalized_boxes=None)
    parser.add_argument('--conf', type=float, default=CONFIDENCE_HIGH)
    parser.add_argument('--iou', type=float, default=0.45, help='原始输出按类别NMS的IoU阈值')
    parser.add_argument('--max-det', type=int, default=100)
    parser.add_argument('--track-conf', type=float, default=CONFIDENCE_LOW, help='已有火焰目标续跟的最低置信度，默认0.25')
    parser.add_argument('--track-max-gap', '--track-hold', dest='track_max_gap', type=float, default=0.3,
                        help='历史轨迹可参与匹配的最长间隔，默认0.3秒；不补画漏检框，旧参数名track-hold兼容')
    parser.add_argument('--no-track', action='store_true', help='关闭短时跟踪，恢复V3检测和平滑流程')
    parser.add_argument('--no-smooth', action='store_true', help='关闭视频稳框，直接使用当前帧原始检测框')
    parser.add_argument('--smooth-alpha', type=float, default=0.4, help='视频坐标平滑系数，默认0.4；越小越稳，跟随延迟越大')
    parser.add_argument('--smooth-iou', type=float, default=0.25, help='同类框跨帧匹配的最小IoU，默认0.25')
    parser.add_argument('--smooth-max-gap', type=float, default=0.3, help='超过此间隔重置稳框，单位秒，默认0.3')
    parser.add_argument('--core', choices=['auto', '0', '1', '2', 'all'], default=NPU_CORE, help='RK3588 NPU核心：自动、单个核心或三个核心')
    parser.add_argument('--width', type=int, default=FRAME_WIDTH, help='摄像头请求宽度，默认1920；不支持时回退')
    parser.add_argument('--height', type=int, default=FRAME_HEIGHT, help='摄像头请求高度，默认1080；不支持时回退')
    parser.add_argument('--sync', action='store_true', help='使用同步取帧/输出，便于对比；默认实时流使用hat20同帧流水线')
    parser.add_argument('--preview-size', type=int, default=PREVIEW_LONG_EDGE, help='视频回传/预览最长边，默认720，只缩小；0保持原尺寸')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--image-port', type=int, default=8088)
    parser.add_argument('--info-port', type=int, default=8089)
    parser.add_argument('--no-udp', action='store_true')
    parser.add_argument('--jpeg-quality', type=int, default=JPEG_QUALITY)
    parser.add_argument('--show', action='store_true', help='有桌面时打开本地预览，按q/空格/Esc退出')
    parser.add_argument('--output', type=Path, default=ROOT / 'output_v20', help='静态图片的火焰标注JPEG和JSON保存目录，默认output_v20')
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--ptz', action='store_true', help='V20教学版不支持云台，此参数会明确报错')
    parser.add_argument('--ptz-lib', type=Path, default=ROOT / 'libSmartSensorDriver.so')
    parser.add_argument('--ptz-module', type=int, default=17)
    parser.add_argument('--ptz-speed', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--deadzone', type=int, default=50)
    parser.add_argument('--invert-x', action='store_true')
    parser.add_argument('--invert-y', action='store_true')
    parser.add_argument('--check', action='store_true', help='仅检查系统、依赖及模型文件，不运行NPU')
    parser.add_argument('--no-buzzer', action='store_true', help='关闭真实蜂鸣器，但仍核验学生判断并归档')
    parser.add_argument('--results-dir', type=Path, default=RESULTS_DIR, help='成果输出根目录，默认用户桌面/成果输出')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.conf <= 1 or not 0 <= args.iou <= 1:
        parser.error('--conf/--iou 必须在0..1之间')
    if not 0 <= args.track_conf <= 1:
        parser.error('--track-conf 必须在0..1之间')
    if (not args.no_track and Path(args.source).suffix.lower() not in IMAGE_EXTENSIONS
            and args.track_conf > args.conf):
        parser.error('启用视频跟踪时 --track-conf 不能大于 --conf')
    if not math.isfinite(args.track_max_gap) or args.track_max_gap <= 0:
        parser.error('--track-max-gap 必须为有限正数')
    if not 0 < args.smooth_alpha <= 1 or not 0 < args.smooth_iou <= 1:
        parser.error('--smooth-alpha/--smooth-iou 必须在 (0,1]')
    if not 0 < args.smooth_max_gap < float('inf'):
        parser.error('--smooth-max-gap 必须为有限正数')
    if args.imgsz <= 0 or args.imgsz % 32:
        parser.error('--imgsz 必须是32的正整数倍')
    if min(args.width, args.height, args.max_det) <= 0 or args.max_frames < 0 or args.deadzone < 0:
        parser.error('宽、高、max-det必须为正数，max-frames/deadzone必须非负')
    if args.preview_size < 0:
        parser.error('--preview-size 必须非负')
    if args.fire_class is not None and args.fire_class < 0:
        parser.error('--fire-class 必须非负')
    if not 1 <= args.jpeg_quality <= 100:
        parser.error('--jpeg-quality 必须在1..100之间')
    if not all(1 <= value <= 65535 for value in (args.image_port, args.info_port)):
        parser.error('UDP端口必须在1..65535之间')
    if (args.boxes_output is None) != (args.scores_output is None):
        parser.error('--boxes-output 与 --scores-output 需要一起提供')
    if args.boxes_output is not None and {args.boxes_output, args.scores_output} != {0, 1}:
        parser.error('双输出的两个索引必须分别为0和1')
    if args.ptz:
        parser.error('V20教学版不启用云台；需要云台时请使用V4。')
    return args


def resolve_model(path):
    path = Path(path).expanduser().resolve()
    if path == DEFAULT_MODEL.resolve() and not path.exists() and path.parent.is_dir():
        candidates = sorted(path.parent.rglob('*.rknn'))
        if len(candidates) == 1:
            path = candidates[0]
            LOG.info('使用model目录中的唯一模型：%s', path)
    if path.is_dir():
        candidates = sorted(path.rglob('*.rknn'))
        if len(candidates) != 1:
            raise ValueError('导出目录中需要恰好一个RKNN文件，请用 --model 明确指定：{}'.format(path))
        path = candidates[0]
    if path.suffix.lower() != '.rknn':
        raise ValueError('部署入口只接受 .rknn 并使用RK3588 NPU；请先将ONNX或PT转换成RKNN。')
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('模型不存在或为空：{}。请放入真正的YOLO26导出文件；旧Fire_Seg模型无法靠改名升级。'.format(path))
    return path


def infer_fire_class(labels, explicit=None):
    if explicit is not None:
        if explicit < 0 or explicit >= len(labels):
            raise ValueError('--fire-class 超出类别范围，实际标签为 {}'.format(labels))
        return explicit
    aliases = {'fire', 'flame', 'flames', '火', '火焰'}
    matches = [i for i, name in enumerate(labels) if name.strip().casefold() in aliases]
    if len(matches) != 1:
        raise ValueError('无法唯一确定火焰类别：{}。请核对训练标签后用 --fire-class 指定，程序不会默认把第0类当成火。'.format(labels))
    return matches[0]


def check_environment(args):
    healthy = True
    model = None
    print('Python: {}\n系统: {} {}'.format(sys.version.split()[0], platform.system(), platform.machine()))
    try:
        model = resolve_model(args.model)
        print('模型: {} ({} bytes)'.format(model, model.stat().st_size))
    except ValueError as exc:
        healthy = False
        print('[未通过] {}'.format(exc))
    if platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        healthy = False
        print('[未通过] RKNN需要在RK3588 Linux ARM64板子上运行。')
    print('执行后端要求：RKNNLite -> RK3588 NPU，核心选择={}'.format(args.core))
    for name in ('numpy', 'cv2', 'yaml', 'rknnlite.api'):
        try:
            module = importlib.import_module(name)
            print('[正常] {} {}'.format(name, getattr(module, '__version__', '')))
        except Exception as exc:
            healthy = False
            print('[未通过] {}: {}'.format(name, exc))
    if model is not None:
        try:
            from detector import read_metadata, resolve_labels, verify_model_hash
            original = args.model.expanduser()
            metadata = read_metadata(original) if original.is_dir() and original.resolve() != model.parent else {}
            metadata.update(read_metadata(model))
            if verify_model_hash(model, metadata):
                print('[正常] 模型SHA256与说明文件匹配')
            labels = resolve_labels(metadata, args.labels, model)
            fire_class = infer_fire_class(labels, args.fire_class)
            if metadata.get('num_classes') is not None and metadata['num_classes'] != len(labels):
                raise ValueError('num_classes 与类别名称数量不一致。')
            print('[正常] 类别顺序：{}；火焰类别ID={}'.format(labels, fire_class))
        except Exception as exc:
            healthy = False
            print('[未通过] 模型类别配置：{}'.format(exc))
    if args.ptz and not args.ptz_lib.is_file():
        healthy = False
        print('[未通过] 云台驱动不存在：{}'.format(args.ptz_lib))
    try:
        get_zone_overlay()
        print('[正常] Pillow与指定字体：{}'.format(FONT_PATH))
    except Exception as exc:
        healthy = False
        print('[未通过] {}'.format(exc))
    print('检查未执行NPU或蜂鸣器，实际输出格式将在首次识别时验证。')
    return 0 if healthy else 1


# ==================== 06 识别画面绘制 ====================
# 识别框与当前图像一同缩放，保证预览画面和原图统计对应同一个位置。
# 高分、低分使用各自颜色；区域名称使用指定中文字体绘制。
def draw_results(frame, detections, labels, fire_class, inference_ms, fps, observed_count=None):
    import cv2
    fire_count = observed_count if observed_count is not None else sum(
        d.class_id == fire_class and getattr(d, 'state', 'detected') == 'detected' for d in detections)
    for item in detections:
        left, top, right, bottom = item.box
        tracking = getattr(item, 'state', 'detected') != 'detected'
        color = COLOR_FIRE_LOW if tracking else COLOR_FIRE_HIGH
        label = labels[item.class_id].encode('ascii', errors='replace').decode('ascii')
        cv2.rectangle(frame, (left, top), (right, bottom), color, BOX_LINE_WIDTH)
        text = '{} {:.0%}'.format(label, item.confidence)
        (text_w, text_h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE, LABEL_LINE_WIDTH)
        label_x = max(0, min(left, frame.shape[1] - text_w - 8))
        label_y = max(0, min(top - text_h - baseline - 8, frame.shape[0] - text_h - baseline - 8))
        cv2.rectangle(frame, (label_x, label_y),
                      (min(frame.shape[1] - 1, label_x + text_w + 8), label_y + text_h + baseline + 8), color, -1)
        brightness = .114*color[0] + .587*color[1] + .299*color[2]
        text_color = BRIGHT_LABEL_TEXT if brightness >= 160 else DARK_LABEL_TEXT
        cv2.putText(frame, text, (label_x + 4, label_y + text_h + 4), cv2.FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE, text_color, LABEL_LINE_WIDTH, cv2.LINE_AA)
    if SHOW_STATS:
        cv2.putText(frame, 'Fire: {} ({}) | detect {:.1f}ms | loop {:.1f}FPS'.format('YES' if fire_count else 'NO', fire_count, inference_ms, fps),
                    STATS_POSITION, cv2.FONT_HERSHEY_SIMPLEX, STATS_FONT_SCALE, STATS_TEXT_COLOR, STATS_LINE_WIDTH)


def render_preview(frame, detections, labels, fire_class, inference_ms, fps, long_edge, observed_count=None, permit_state=None):
    """hat20-style same-frame rendering; scale boxes with their own image."""
    import cv2
    height, width = frame.shape[:2]
    scale = min(1.0, long_edge / max(height, width)) if long_edge else 1.0
    if scale < 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
        scale_x, scale_y = frame.shape[1] / width, frame.shape[0] / height
        detections = [replace(d, box=(round(d.box[0] * scale_x), round(d.box[1] * scale_y),
                                      round(d.box[2] * scale_x), round(d.box[3] * scale_y))) for d in detections]
    draw_results(frame, detections, labels, fire_class, inference_ms, fps, observed_count)
    get_zone_overlay().apply(frame, permit_enabled() if permit_state is None else permit_state.valid,
                             None if permit_state is None else '钢筋加工区：'+permit_state.text)
    return frame


# ==================== 07 视频识别与联动 ====================
# NPU在主线程推理，采集和回传保留最新完整帧；声音和CSV由配套后台模块处理。
# 取帧或推理失败停止处理，不作为无火场景参与核验；退出时释放线程和设备资源。
def run(args, lesson):
    import cv2
    from box_smoother import BoxSmoother
    from fire_tracker import FireTracker
    from detector import Detector
    from io_helpers import UdpSender
    from video_pipeline import LatestFrames, LatestOutput, open_camera

    cv2.setNumThreads(1)
    model = resolve_model(args.model)
    detector = sender = ptz = capture = None
    reader = output_worker = None
    first_frame = None
    video_fps = 0.0
    completed = False
    stopping = [False]
    previous_handlers = {}

    def stop(_signum, _frame):
        stopping[0] = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop)
    try:
        source_path = Path(args.source)
        is_image = source_path.suffix.lower() in IMAGE_EXTENSIONS
        tracking_enabled = not is_image and not args.no_track
        original = args.model.expanduser()
        model_input = original if original.is_dir() else model
        detector = Detector(model_input, labels=args.labels, imgsz=args.imgsz, output_format=args.output_format,
                            normalized_boxes=args.normalized_boxes, core=args.core, conf=args.track_conf if tracking_enabled else args.conf, iou=args.iou,
                            max_det=args.max_det, boxes_output=args.boxes_output, scores_output=args.scores_output)
        if detector.backend != 'rknn':
            raise RuntimeError('部署入口必须使用RKNNLite NPU后端，禁止切换到CPU推理。')
        LOG.info('推理后端：RKNNLite -> RK3588 NPU；核心选择=%s', args.core)
        labels = detector.labels
        fire_class = infer_fire_class(labels, args.fire_class)
        configure_classes = getattr(detector, 'set_classes', None)
        if callable(configure_classes):
            configure_classes([fire_class])
        else:
            # 兼容没有类别筛选接口的旧版检测模块，入口仍会在后续处理前过滤火焰。
            LOG.warning('detector.py 为旧版，使用入口火焰过滤。建议同步更新 detector.py，'
                        '使类别筛选在 max-det 数量限制前完成。')
        LOG.info('V20 仅识别火焰；烟雾不参与绘制、统计、发送或云台控制')
        LOG.info('标签顺序=%s；火焰类别=%s (ID=%d)', labels, labels[fire_class], fire_class)
        if not args.no_udp:
            LOG.info('成功识别后：%s:%d发送JPEG，%s:%d发送有/无。推理错误不会报告为无火。',
                     args.host, args.image_port, args.host, args.info_port)
        if not args.no_udp:
            sender = UdpSender(args.host, args.image_port, args.info_port)
        is_live = not is_image and not source_path.is_file()
        tracker = FireTracker(fire_class, args.conf, args.track_conf, args.track_max_gap,
                              1.0 if args.no_smooth else args.smooth_alpha, args.smooth_iou, args.max_det) if tracking_enabled else None
        if tracker is not None:
            LOG.info("稳框关联已开启：发现>=%.2f，低分续跟>=%.2f，匹配历史<=%.2fs；当前帧漏检立即无框",
                     args.conf, args.track_conf, args.track_max_gap)
        smoother = None if is_image or args.no_smooth or tracker is not None else BoxSmoother(
            args.smooth_alpha, args.smooth_iou, args.smooth_max_gap)
        if smoother is not None:
            LOG.info('视频稳框已开启：同类IoU匹配，平滑=%.2f，匹配IoU=%.2f，重置间隔=%.2fs',
                     args.smooth_alpha, args.smooth_iou, args.smooth_max_gap)
        if is_image:
            if not source_path.is_file():
                raise ValueError('图片不存在：{}'.format(source_path.resolve()))
            image = cv2.imread(str(source_path))
            if image is None:
                raise RuntimeError('无法读取图片：{}'.format(source_path))
        else:
            source = int(args.source) if args.source.isdecimal() else args.source
            if isinstance(source, int) or args.source.startswith('/dev/video'):
                capture, first_frame = open_camera(source, args.width, args.height)
            else:
                capture = cv2.VideoCapture(source)
            if not capture.isOpened():
                raise RuntimeError('无法打开输入 {}；请核对摄像头编号、权限或视频地址。'
                                   '请检查设备节点，或用 --source /dev/videoN 指定摄像头。'.format(args.source))
            if source_path.is_file():
                file_rate = capture.get(cv2.CAP_PROP_FPS)
                video_fps = file_rate if math.isfinite(file_rate) and file_rate > 0 else 0.0
            LOG.info('输入=%s，实际画面=%.0fx%.0f', args.source, capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if is_live and not args.sync:
                reader = LatestFrames(capture, first_frame)
                reader.start()
                capture, first_frame = None, None  # 摄像头交由采集线程释放。
        lesson.start()
        permit_window = PermitWindow(permit_enabled(), PERMIT_DURATION)
        last_log = udp_error_time = 0.0
        count = 0
        fps = 0.0

        def send_result(udp, jpeg, present):
            nonlocal udp_error_time
            try:
                udp.send_status(present)
                udp.send_image(jpeg)
            except OSError as exc:
                now = time.monotonic()
                if now - udp_error_time >= 3:
                    LOG.warning('UDP发送失败，继续识别：%s', exc)
                    udp_error_time = now

        if reader is not None and sender is not None and not args.show:
            live_sender = sender

            def publish(job):
                # 图像及其对应检测框作为同一个输出任务传递，避免错帧叠框。
                raw, results, observed, cost, job_fps, job_permit = job
                preview = render_preview(raw, results, labels, fire_class, cost, job_fps, args.preview_size, len(observed), job_permit)
                ok, encoded = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
                if not ok:
                    raise RuntimeError('标注图片JPEG编码失败')
                send_result(live_sender, encoded.tobytes(), bool(observed))

            output_worker = LatestOutput(publish, on_close=live_sender.close)
            output_worker.start()
            sender = None  # 套接字交由输出线程关闭，异常时也由该线程清理。
            LOG.info('hat20同帧流水线：只保留最新输入/输出，JPEG与UDP在后台执行')
        while not stopping[0]:
            loop_start = time.perf_counter()
            if output_worker is not None and output_worker.error is not None:
                raise RuntimeError('后台画面回传失败：{}'.format(output_worker.error)) from output_worker.error
            if is_image:
                frame = image.copy()
                captured = time.monotonic()
            elif reader is not None:
                try:
                    captured, frame = reader.get(timeout=0.1)
                except Empty:
                    if reader.done.is_set():
                        raise RuntimeError('摄像头或网络流读取停止：{}'.format(reader.error or '没有有效帧'))
                    continue
            else:
                if first_frame is not None:
                    ok, frame, first_frame = True, first_frame, None
                else:
                    ok, frame = capture.read()
                if not ok or frame is None or frame.size == 0:
                    if source_path.is_file():
                        LOG.info('视频文件读取结束')
                        break
                    raise RuntimeError('摄像头或网络流读取失败；停止识别并释放云台。')
                captured = time.monotonic()
            if video_fps:
                captured = count / video_fps
            inference_start = time.perf_counter()
            # 推理失败直接报告异常，不能转换为空结果或“无火”。
            detections = [d for d in detector.predict(frame) if d.class_id == fire_class]
            inference_ms = (time.perf_counter() - inference_start) * 1000
            smooth_started = time.perf_counter()
            candidate_count = len(detections)
            if tracker is not None:
                tracked = tracker.update(detections, captured, frame.shape[:2])
                # 兼容性防护：忽略旧模块可能返回的无当前置信度预测框。
                detections = [d for d in tracked.display if d.confidence is not None]
                fire_detections = list(tracked.observed)
            else:
                detections = [d for d in detections if d.confidence >= args.conf]
                if smoother is not None:
                    detections = smoother.update(detections, captured, frame.shape[:2])
                fire_detections = detections
            smooth_ms = (time.perf_counter() - smooth_started) * 1000
            material_count, rebar_count, temporary_work_count = count_fire_regions(fire_detections, frame.shape[:2])
            # 使用真实单调时钟，不使用视频时间戳，不因有火或无火而重新计时。
            permit_state = permit_window.snapshot()
            lesson.update_regions(material_count, rebar_count, temporary_work_count,
                                  sum(getattr(d, 'state', 'detected') == 'low' for d in detections), permit_state.valid)
            fire_present = bool(fire_detections)
            if ptz is not None:
                target = max(fire_detections, key=lambda d: d.box[2] - d.box[0], default=None)
                ptz.update(None if target is None else target.box, frame.shape[1], frame.shape[0])
            if output_worker is not None:
                output_worker.submit((frame, tuple(detections), tuple(fire_detections), inference_ms, fps, permit_state))
            if sender is not None or args.show or is_image:
                frame = render_preview(frame, detections, labels, fire_class, inference_ms, fps,
                                       0 if is_image else args.preview_size, len(fire_detections), permit_state)
            jpeg = None
            if sender is not None or is_image:
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
                if not ok:
                    raise RuntimeError('标注图片JPEG编码失败')
                jpeg = encoded.tobytes()
            if sender is not None:
                send_result(sender, jpeg, fire_present)
            count += 1
            now = time.monotonic()
            if is_image or now - last_log >= 1:
                LOG.info('帧=%d 火焰=%s 火焰数=%d 检测总数=%d 检测总耗时=%.1fms 稳框=%.1fms 循环=%.1fFPS',
                         count, '有' if fire_present else '无', len(fire_detections), len(detections), inference_ms, smooth_ms, fps)
                if tracker is not None:
                    LOG.info('候选=%d 高分实测=%d 低分实测=%d', candidate_count, len(fire_detections),
                             sum(d.state == 'low' for d in detections))
                if reader is not None:
                    LOG.info('当前帧处理延迟=%.0fms 丢弃旧输入=%d 旧输出=%d',
                             (time.monotonic() - captured) * 1000, reader.dropped,
                             output_worker.dropped if output_worker is not None else 0)
                LOG.info('钢筋加工区=%d 临时作业区=%d 材料区=%d 授权有效=%s 剩余=%d秒',
                         rebar_count, temporary_work_count, material_count, permit_state.valid, permit_state.remaining)
                last_log = now
            if is_image:
                args.output.mkdir(parents=True, exist_ok=True)
                destination = args.output / (source_path.stem + '_yolo26_v20.jpg')
                destination.write_bytes(jpeg)
                report = {'version': 20, 'recognition': 'fire_only', 'model': str(model), 'labels': labels, 'fire_class': fire_class,
                          'fire_present': fire_present, 'fire_count': len(fire_detections),
                          'permit_valid': permit_state.valid, 'permit_remaining_seconds': permit_state.remaining, 'regions': {'rebar': rebar_count, 'temporary_work': temporary_work_count, 'material': material_count}, 'inference_ms': inference_ms,
                          'timing_ms': getattr(detector, 'last_timing', {}),
                          'detections': [{'box': list(d.box), 'class_id': d.class_id, 'label': labels[d.class_id], 'confidence': d.confidence} for d in detections]}
                destination.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                LOG.info('已保存标注图片和JSON：%s', destination)
            if args.show:
                cv2.imshow('YOLO26 V20 Fire', frame)
                if (cv2.waitKey(0 if is_image else 1) & 0xff) in (ord('q'), 27, ord(' ')):
                    break
            elapsed = time.perf_counter() - loop_start
            fps = 1.0 / elapsed if elapsed > 0 else 0.0
            if is_image or (args.max_frames and count >= args.max_frames):
                break
        completed = True
    except Exception as exc:
        lesson.fail('识别或采集异常', exc)
        raise
    finally:
        lesson.stop()  # 先停止后续鸣叫，再等待视频线程与文件归档。
        # NPU由主线程使用；摄像头、输出线程各自释放资源，避免运行中被提前关闭。
        shutdown_error = None
        if ptz is not None:
            try:
                ptz.close()
            except Exception:
                LOG.exception('云台停止失败')
            ptz = None
        for worker in (reader, output_worker):
            if worker is not None:
                try:
                    ended = worker.close() if worker is reader else worker.close(discard=not completed)
                    if worker is output_worker and not ended:
                        shutdown_error = RuntimeError('后台画面输出尚未结束；其资源由输出线程保留并释放。')
                except Exception as exc:
                    LOG.exception('视频流水线停止失败')
                    shutdown_error = exc
        if output_worker is not None and output_worker.error is not None:
            shutdown_error = output_worker.error
        for name, resource in (('云台', ptz), ('摄像头', capture), ('UDP', sender), ('模型', detector)):
            if resource is not None:
                try:
                    resource.release() if name == '摄像头' else resource.close()
                except Exception:
                    LOG.exception('%s释放失败', name)
        if args.show:
            cv2.destroyAllWindows()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if completed and shutdown_error is not None:
            raise RuntimeError('视频流水线停止时发现错误：{}'.format(shutdown_error)) from shutdown_error


# ==================== 08 程序入口 ====================
# 启动时保存实际运行入口源码；停止时完成设备清理和CSV落盘。
def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    lesson = None
    try:
        if args.check:
            return check_environment(args)
        config = teaching_config(ENABLE_BUZZER and not args.no_buzzer)
        LOG.info('V20 学生版：实际授权固定为钢筋区；时长=%s秒；到期后不自动续期', PERMIT_DURATION)
        lesson = ZoneSession(experiment_info, config, __file__, control_buzzer, buzzer, args.results_dir)
        run(args, lesson)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if lesson is not None:
            lesson.fail('运行异常', exc)
        LOG.error('%s', exc, exc_info=args.debug)
        LOG.error('可先运行 --check 或添加 --debug 查看完整信息。')
        return 1
    finally:
        if lesson is not None:
            lesson.close()


if __name__ == '__main__':
    sys.exit(main())
