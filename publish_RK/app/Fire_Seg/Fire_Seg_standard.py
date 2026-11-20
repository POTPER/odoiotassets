#!/usr/bin/env python3
# ==================== 工程场景：地下综合管廊电力舱火情监测 ====================
# 某市地下综合管廊已投入运行，运维中心在电力舱设置固定视频监测点，
# 从左到右覆盖电缆接头区、配电设备区和检修通道区，开展火情识别与蜂鸣器联动调试。
# 电缆接头区用于观察接头周边火焰，配电设备区用于观察设备附近火焰，
# 检修通道区用于观察人员巡检通行范围内的火焰。正常运行期间三个区域均不应出现明火。
# 任意一个区域或多个区域识别到火焰时，立即请求警报音；本帧没有达到门槛的火焰时请求静音。
# 本场景按区域记录火情，不设动火审批或授权倒计时。
# 三个区域的范围框和底部中文名称背景依次为蓝色、青色、绿色；火焰识别框使用红色。
# 置信度达到50%才显示并参与联动，低分仅在内部匹配；首帧即提交结果，不额外等待。
# CSV固定记录三个监测区域的识别与警报情况，并保存本次运行入口源码。
# 运行：python3 standard.py；只检查环境：python3 standard.py --check。
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
import csv
import shutil
from datetime import datetime
from functools import lru_cache
from queue import Queue
from threading import Event, Lock, Thread

# 配套模块负责实验归档、声音请求与中文区域绘制；导入时不打开硬件。
from zone_teaching_support import ZoneCommands, ZoneBuzzer, ZoneOverlay, SOUND_NAMES
from teaching_support import ExperimentLog, TeachingSession, find_desktop, safe_name

# ==================== 02 项目信息与区域联动 ====================
runtime_info = {
    "设备编号": "GL-FIRE-01",
    "项目名称": "电力舱火情监测调试",
    "监测点位": "管廊监控点01",
}

# BGR顺序为蓝、绿、红；范围框与区域名称背景使用相同颜色。
COLOR_CABLE_JOINT_AREA = (255, 128, 0)       # 左侧：电缆接头区，蓝色
COLOR_POWER_EQUIPMENT_AREA = (255, 255, 0)  # 中间：配电设备区，青色
COLOR_MAINTENANCE_PASSAGE_AREA = (0, 180, 0) # 右侧：检修通道区，绿色


def control_buzzer(cable_joint_fire_count, power_equipment_fire_count, maintenance_passage_fire_count):
    # 系统传入本帧三个监测区域的高置信度火焰数量。
    # or表示任意一个条件成立即可；多个区域同时有火时也只提交一次警报请求。
    if cable_joint_fire_count > 0 or power_equipment_fire_count > 0 or maintenance_passage_fire_count > 0:
        buzzer.alarm()
    else:
        buzzer.reset()


# ==================== 03 系统配置 ====================
# 按现场实训设备调整采集、NPU、预览、通信和声音参数。
# 请求分辨率不代表设备一定支持，以终端日志中的实际采集尺寸为准。

# 路径与日志
# 路径以本文件所在目录为基准，避免从其他目录启动时找不到模型或字体。
ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('zonefire_standard')
DEFAULT_MODEL = ROOT / 'model/fire_yolo26.rknn'
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

# 模型与类别顺序
# 模型路径相对于本文件；类别名称从配套模型说明中读取，必须与训练时的类别顺序一致。
# 当前模型为fire、smoke两类，系统仅处理fire；不要通过删除标签来改变类别编号。
MODEL_PATH = ROOT / 'model/fire_yolo26.rknn'

# 摄像头与NPU推理
# 达到高置信度阈值的火焰显示红色；低分仅用于内部续跟，不绘制、不计数、不触发声音或成果记录。
CAMERA_INDEX = 41  # 摄像头设备编号
NPU_CORE = 'auto'  # auto自动选择；也可选0、1、2、all
FRAME_WIDTH, FRAME_HEIGHT = 1920, 1080  # 请求采集宽度、高度，像素；不支持时按原流程回退
CONFIDENCE_HIGH = 0.5  # 检测框显示、报警判断和成果记录共用的高置信度阈值
CONFIDENCE_LOW = 0.25  # 已有火焰目标的内部匹配阈值，低分结果不显示

# 区域范围与中文显示
# 画面按宽度三等分；左侧电缆接头区，中间配电设备区，右侧检修通道区。
# 区域中文在各框底部居中显示，名称由左至右排列，字体使用包内指定文件。
REGION_NAMES = ("电缆接头区", "配电设备区", "检修通道区")  # 左、中、右显示名称
FONT_PATH = ROOT / 'Arial-Unicode.ttf'  # 中文字体，需与代码一起部署
SHOW_REGIONS = True  # 显示三区范围框和底部名称
SHOW_STATS = True  # 显示火焰数量、推理耗时和帧率
REGION_LINE_WIDTH = 2  # 区域框线宽，像素
REGION_FONT_SIZE = 28  # 区域名称最大字号
REGION_BOTTOM_MARGIN = 12  # 底部文字边距，预览画面像素

# 识别框、标签与回传画面
# 检测框与标签背景共用颜色；标签显示当前帧实际置信度，文字按背景亮度自动选色。
COLOR_FIRE_HIGH = (0, 0, 255)  # 高置信度火焰，红色
COLOR_FIRE_LOW = (0, 210, 255)  # 保留配套模块的低分颜色配置；当前不显示低分框
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
DETECTION_CONFIRM_TIME = 0.0  # 0表示首帧立即提交成果和声音请求，不额外等待；后台执行写入和声音
DETECTION_RESET_TIME = 1.0  # 单组模式下，条件持续不成立后的复位时间，秒
BEEP_COUNT = 2  # 通用每组鸣叫次数
BEEP_DURATION = 0.2  # 通用每声持续时间，秒
BEEP_INTERVAL = 0.1  # 通用组内静音时间，秒
BEEP_REPEAT_INTERVAL = 1.0  # 通用组间静音时间，秒
BUZZER_SCAN_WAIT = 2.0  # 等待驱动完成模块扫描，秒
BUZZER_RESULT_TIMEOUT = 1.0  # 超过此时间无有效判断，不再启动下一组，秒
SENSOR_LIB = ROOT / 'libSmartSensorDriver.so'  # 配套传感器驱动动态库
RESULTS_DIR = None  # None按当前用户桌面归档；可改为实验专用目录

# 本标准版不启用云台，避免与蜂鸣器共用驱动生命周期。


# ==================== 04 运行状态与配置校验 ====================

class StandardOverlay(ZoneOverlay):
    """Generic three-zone display; reuses only the compatible font measurement helper."""
    def __init__(self, font_path, display):
        self.font_path=Path(font_path).resolve()
        self.config=dict(display)
        names=self.config['REGION_NAMES']
        if not isinstance(names,(tuple,list)) or len(names)!=3 or len(set(names))!=3 or any(not isinstance(n,str) or not n.strip() for n in names):
            raise ValueError('REGION_NAMES必须提供三个不同的非空区域名称。')
        colors=self.config['REGION_COLORS']
        if len(colors)!=3 or any(not isinstance(c,(tuple,list)) or len(c)!=3 or any(type(v) is not int or not 0<=v<=255 for v in c) for c in colors):
            raise ValueError('区域颜色必须为三组BGR整数。')
        for key in ('REGION_LINE_WIDTH','REGION_FONT_SIZE'):
            if type(self.config[key]) is not int or self.config[key]<=0:
                raise ValueError(key+'必须为正整数。')
        if type(self.config['REGION_BOTTOM_MARGIN']) is not int or self.config['REGION_BOTTOM_MARGIN']<0:
            raise ValueError('REGION_BOTTOM_MARGIN必须为非负整数。')
        if type(self.config['SHOW_REGIONS']) is not bool:
            raise ValueError('SHOW_REGIONS必须为布尔值。')
        if not self.font_path.is_file():
            raise ValueError('缺少指定中文字体：'+str(self.font_path))
        from PIL import ImageFont
        ImageFont.truetype(str(self.font_path),24)
        self._layer(720,405)

    @lru_cache(maxsize=4)
    def _layer(self,width,height):
        from PIL import Image,ImageDraw,ImageFont
        import numpy as np
        c=self.config
        image=Image.new('RGBA',(width,height),(0,0,0,0))
        draw=ImageDraw.Draw(image)
        cuts=(0,width//3,2*width//3,width)
        rgba=lambda bgr:tuple(reversed(bgr))+(255,)
        self.last_label_bounds=[]
        if c['SHOW_REGIONS']:
            for index,name in enumerate(c['REGION_NAMES']):
                left,right=cuts[index],cuts[index+1]
                color=c['REGION_COLORS'][index]
                draw.rectangle((left+1,1,right-2,height-2),outline=rgba(color),width=c['REGION_LINE_WIDTH'])
                size=max(1,min(c['REGION_FONT_SIZE'],round(height*.07),(right-left-8)//len(name)))
                font=ImageFont.truetype(str(self.font_path),size)
                bbox=self._text_bbox(draw,name,font)
                tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
                margin=min(c['REGION_BOTTOM_MARGIN'],max(2,height//5))
                x=(left+right-1-tw)/2-bbox[0]
                y=max(2,height-margin-th)-bbox[1]
                draw.rectangle((max(left+2,int(x+bbox[0])-4),int(y+bbox[1])-3,
                                min(right-2,int(x+bbox[2])+4),min(height-2,int(y+bbox[3])+3)),fill=rgba(color))
                brightness=.114*color[0]+.587*color[1]+.299*color[2]
                text_color=c['BRIGHT_LABEL_TEXT'] if brightness>=128 else c['DARK_LABEL_TEXT']
                draw.text((x,y),name,font=font,fill=rgba(text_color))
                self.last_label_bounds.append((name,(x+bbox[0],y+bbox[1],x+bbox[2],y+bbox[3])))
        array=np.asarray(image)
        return np.ascontiguousarray(array[:,:,:3][:,:,::-1]),np.ascontiguousarray(array[:,:,3])

    def apply(self,frame):
        import cv2
        height,width=frame.shape[:2]
        if height<32 or width<24:
            raise ValueError('三区画面要求宽>=24、高>=32。')
        color,mask=self._layer(width,height)
        cv2.copyTo(color,mask,frame)
        return frame


class StandardLog(ExperimentLog):
    SCENES=REGION_NAMES
    METADATA_COLUMNS=('设备编号','项目名称','监测点位')
    COLUMNS=('监测区域','区域颜色（BGR）','是否识别到火焰','是否警报','警报类型')

    def __init__(self,metadata,config,entry_path,output_root=None):
        self.metadata={key:str(metadata.get(key,'')) for key in self.METADATA_COLUMNS}
        self.config=dict(config)
        base=Path(output_root) if output_root else find_desktop()/'成果输出'
        identity=safe_name(self.metadata['设备编号'])
        project=safe_name(self.metadata['项目名称'])
        self.folder=base/identity/project
        self.folder.mkdir(parents=True,exist_ok=True)
        stem='{}_{}_{}'.format(project,identity,datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.path=self.folder/(stem+'.csv')
        self.error_path=self.folder/(stem+'_异常.csv')
        self.code_path=self.folder/(stem+'.py')
        shutil.copyfile(entry_path,self.code_path)
        self.device='初始化中' if config['ENABLE_BUZZER'] else '未启用'
        self.rows={scene:self._empty_row(scene) for scene in self.SCENES}
        self._first_seen=[None]*3
        self._last=None
        self._queue,self._stop,self._lock=Queue(maxsize=512),Event(),Lock()
        self.dropped=0
        self._save()
        self._thread=Thread(target=self._worker,name='standard-fire-csv',daemon=True)
        self._thread.start()
        LOG.info('管廊成果CSV：%s；本次入口源码：%s',self.path,self.code_path)

    def _empty_row(self,scene):
        index=self.SCENES.index(scene)
        return {**self.metadata,'监测区域':scene,
                '区域颜色（BGR）':str(tuple(self.config['DISPLAY']['REGION_COLORS'][index])),
                '是否识别到火焰':'未验证','是否警报':'未验证','警报类型':'未验证'}

    def _save(self):
        fields=[*self.METADATA_COLUMNS,*self.COLUMNS]
        temporary=self.path.with_suffix('.csv.tmp')
        with temporary.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fields)
            writer.writeheader()
            writer.writerows({key:self._safe_cell(row.get(key,'')) for key in fields} for row in self.rows.values())
        temporary.replace(self.path)

    def _sample(self,data):
        counts,mode,now=data.get('counts'),data.get('mode'),data['now']
        if counts is None or len(counts)!=3 or mode not in SOUND_NAMES:
            self._first_seen=[None]*3
            self._last=None
            return
        if self._last is None or now<=self._last or now-self._last>self.config['RESULT_TIMEOUT']:
            self._first_seen=[None]*3
        self._last=now
        for index,count in enumerate(counts):
            if count<=0:
                self._first_seen[index]=None
                continue
            if self._first_seen[index] is None:
                self._first_seen[index]=now
            if now-self._first_seen[index]+1e-9<self.config['CONFIRM_TIME']:
                continue
            self.rows[self.SCENES[index]].update({'是否识别到火焰':'是',
                '是否警报':'否' if mode=='silent' else '是','警报类型':SOUND_NAMES[mode]})


class StandardSession(TeachingSession):
    LOG_CLASS=StandardLog
    BUZZER_CLASS=ZoneBuzzer

    def update_regions(self,cable_joint,power_equipment,maintenance_passage,now=None):
        now=time.monotonic() if now is None else now
        counts=(cable_joint,power_equipment,maintenance_passage)
        mode=None
        if not self._disabled:
            try:
                self.commands.clear()
                self.rule(*counts)
                if self.commands.calls!=1 or self.commands.mode not in SOUND_NAMES:
                    raise ValueError('每帧必须提交一次声音模式或静音请求。')
                mode=self.commands.mode
            except Exception as exc:
                self._disabled=True
                self.log.submit('error',action='管廊区域联动',error=str(exc))
                self.log.submit('device',status='联动停用：判断异常')
                self.stop()
                LOG.exception('区域判断异常，联动停用，识别继续运行')
        if self.buzzer is not None and mode is not None:
            self.buzzer.update(mode,now)
        state=(counts,mode)
        interval=min(.25,self.config['CONFIRM_TIME']) if self.config['CONFIRM_TIME']>0 else .25
        if state!=self._last_state or self._last_record is None or now-self._last_record>=interval:
            self.log.submit('sample',counts=counts,mode=mode,now=now)
            self._last_state,self._last_record=state,now



# 以下对象由系统维护，保存中文图层缓存并收集声音请求，由程序维护。
_zone_overlay = None  # 中文区域图层按实际画面尺寸缓存
buzzer = ZoneCommands()  # 提交模式请求的接口；不是底层驱动

# 区域统计：使用原图坐标判断火焰中心，分界点归右侧，避免重复计数。
# 参数results由识别流程提供，只包含本帧高置信度火焰；frame_size为原图的高、宽。
def count_fire_regions(results, frame_size):
    height, width = frame_size
    counts = [0, 0, 0]
    for fire in results:
        x1, y1, x2, y2 = fire.box
        center_x, center_y = (x1+x2)/2, (y1+y2)/2
        if not (0 <= center_x < width and 0 <= center_y < height):
            continue
        index = 0 if center_x < width//3 else 1 if center_x < 2*width//3 else 2
        counts[index] += 1
    return tuple(counts)


# 配置采集与启动校验：预先检查中文字体与参数。



def display_config():
    return {'REGION_NAMES': REGION_NAMES,
            'REGION_COLORS': (COLOR_CABLE_JOINT_AREA, COLOR_POWER_EQUIPMENT_AREA, COLOR_MAINTENANCE_PASSAGE_AREA),
            'REGION_LINE_WIDTH': REGION_LINE_WIDTH, 'REGION_FONT_SIZE': REGION_FONT_SIZE,
            'REGION_BOTTOM_MARGIN': REGION_BOTTOM_MARGIN, 'SHOW_REGIONS': SHOW_REGIONS,
            'BRIGHT_LABEL_TEXT': BRIGHT_LABEL_TEXT, 'DARK_LABEL_TEXT': DARK_LABEL_TEXT}


def get_zone_overlay():
    global _zone_overlay
    if _zone_overlay is None:
        _zone_overlay = StandardOverlay(FONT_PATH, display_config())
    return _zone_overlay


def runtime_config(enabled):
    for key in ('BOX_LINE_WIDTH','LABEL_LINE_WIDTH','STATS_LINE_WIDTH'):
        if type(globals()[key]) is not int or globals()[key] <= 0:
            raise ValueError(key+'必须为正整数。')
    for key in ('LABEL_FONT_SCALE','STATS_FONT_SCALE'):
        if not math.isfinite(globals()[key]) or globals()[key] <= 0:
            raise ValueError(key+'必须为有限正数。')
    for key in ('COLOR_FIRE_HIGH','COLOR_FIRE_LOW','BRIGHT_LABEL_TEXT','DARK_LABEL_TEXT','STATS_TEXT_COLOR'):
        color=globals()[key]
        if not isinstance(color,(tuple,list)) or len(color)!=3 or any(type(v) is not int or not 0<=v<=255 for v in color):
            raise ValueError(key+'必须为三个0..255整数的BGR颜色。')
    get_zone_overlay()
    return {'ENABLE_BUZZER': enabled, 'BUZZER_MODULE_INDEX': BUZZER_MODULE_INDEX,
            'BUZZER_REPEAT': BUZZER_REPEAT, 'CONFIRM_TIME': DETECTION_CONFIRM_TIME,
            'RESET_TIME': DETECTION_RESET_TIME, 'BEEP_COUNT': BEEP_COUNT,
            'BEEP_DURATION': BEEP_DURATION, 'BEEP_INTERVAL': BEEP_INTERVAL,
            'BEEP_REPEAT_INTERVAL': BEEP_REPEAT_INTERVAL, 'SCAN_WAIT': BUZZER_SCAN_WAIT,
            'RESULT_TIMEOUT': BUZZER_RESULT_TIMEOUT, 'SENSOR_LIB': str(SENSOR_LIB),
            'DISPLAY': display_config()}


# ==================== 05 启动参数与环境检查 ====================
# 直接运行时使用顶部设置；命令行参数用于设备调试，覆盖本次运行的默认值。
# 环境检查只读取依赖、模型和字体，不启动NPU或蜂鸣器。
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='管廊电力舱火情监测标准版：RK3588 NPU、三区有火即报警、首帧记录')
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
    parser.add_argument('--conf', type=float, default=CONFIDENCE_HIGH, help='显示、报警及记录的统一门槛，0.5至1.0')
    parser.add_argument('--iou', type=float, default=0.45, help='原始输出按类别NMS的IoU阈值')
    parser.add_argument('--max-det', type=int, default=100)
    parser.add_argument('--track-conf', type=float, default=CONFIDENCE_LOW, help='已有火焰目标续跟的最低置信度，默认0.25')
    parser.add_argument('--track-max-gap', '--track-hold', dest='track_max_gap', type=float, default=0.3,
                        help='历史轨迹可参与匹配的最长间隔，默认0.3秒；不补画漏检框，旧参数名track-hold兼容')
    parser.add_argument('--no-track', action='store_true', help='关闭短时关联，使用当前检测及坐标平滑流程')
    parser.add_argument('--no-smooth', action='store_true', help='关闭视频稳框，直接使用当前帧原始检测框')
    parser.add_argument('--smooth-alpha', type=float, default=0.4, help='视频坐标平滑系数，默认0.4；越小越稳，跟随延迟越大')
    parser.add_argument('--smooth-iou', type=float, default=0.25, help='同类框跨帧匹配的最小IoU，默认0.25')
    parser.add_argument('--smooth-max-gap', type=float, default=0.3, help='超过此间隔重置稳框，单位秒，默认0.3')
    parser.add_argument('--core', choices=['auto', '0', '1', '2', 'all'], default=NPU_CORE, help='RK3588 NPU核心：自动、单个核心或三个核心')
    parser.add_argument('--width', type=int, default=FRAME_WIDTH, help='摄像头请求宽度，默认1920；不支持时回退')
    parser.add_argument('--height', type=int, default=FRAME_HEIGHT, help='摄像头请求高度，默认1080；不支持时回退')
    parser.add_argument('--sync', action='store_true', help='使用同步取帧/输出，便于对比；默认实时流使用最新帧流水线')
    parser.add_argument('--preview-size', type=int, default=PREVIEW_LONG_EDGE, help='视频回传/预览最长边，默认720，只缩小；0保持原尺寸')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--image-port', type=int, default=8088)
    parser.add_argument('--info-port', type=int, default=8089)
    parser.add_argument('--no-udp', action='store_true')
    parser.add_argument('--jpeg-quality', type=int, default=JPEG_QUALITY)
    parser.add_argument('--show', action='store_true', help='有桌面时打开本地预览，按q/空格/Esc退出')
    parser.add_argument('--output', type=Path, default=ROOT / 'output_standard', help='静态图片的火焰标注JPEG和JSON保存目录，默认output_standard')
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--ptz', action='store_true', help='标准版不支持云台，此参数会明确报错')
    parser.add_argument('--ptz-lib', type=Path, default=ROOT / 'libSmartSensorDriver.so')
    parser.add_argument('--ptz-module', type=int, default=17)
    parser.add_argument('--ptz-speed', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--deadzone', type=int, default=50)
    parser.add_argument('--invert-x', action='store_true')
    parser.add_argument('--invert-y', action='store_true')
    parser.add_argument('--check', action='store_true', help='仅检查系统、依赖及模型文件，不运行NPU')
    parser.add_argument('--no-buzzer', action='store_true', help='关闭真实蜂鸣器，保留火情判断与成果记录')
    parser.add_argument('--results-dir', type=Path, default=RESULTS_DIR, help='成果输出根目录，默认用户桌面/成果输出')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args(argv)
    if not 0.5 <= args.conf <= 1:
        parser.error('--conf 必须在0.5..1之间，标准版不显示或记录低于50%的火焰。')
    if not 0 <= args.iou <= 1:
        parser.error('--iou 必须在0..1之间')
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
        parser.error('标准版不启用云台。')
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
# 只显示达到高置信度阈值的本帧火焰框；区域名称使用指定中文字体绘制。
def draw_results(frame, detections, labels, fire_class, inference_ms, fps, observed_count=None, min_confidence=CONFIDENCE_HIGH):
    import cv2
    detections = [d for d in detections if d.class_id == fire_class and d.confidence is not None
                  and d.confidence >= min_confidence]
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


def render_preview(frame, detections, labels, fire_class, inference_ms, fps, long_edge, observed_count=None, min_confidence=CONFIDENCE_HIGH):
    """Scale the current observations with their own image, then draw the three zones."""
    import cv2
    height, width = frame.shape[:2]
    scale = min(1.0, long_edge/max(height,width)) if long_edge else 1.0
    if scale < 1:
        frame = cv2.resize(frame,(max(1,round(width*scale)),max(1,round(height*scale))))
        sx,sy = frame.shape[1]/width,frame.shape[0]/height
        detections = [replace(d,box=(round(d.box[0]*sx),round(d.box[1]*sy),round(d.box[2]*sx),round(d.box[3]*sy))) for d in detections]
    draw_results(frame,detections,labels,fire_class,inference_ms,fps,observed_count,min_confidence)
    return get_zone_overlay().apply(frame)


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
        LOG.info('管廊标准版仅识别火焰；烟雾不参与显示、计数或联动')
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
            LOG.info("稳框关联已开启：显示/报警/记录>=%.2f，内部匹配>=%.2f，匹配历史<=%.2fs；低分及漏检不画框",
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
                raw, results, observed, cost, job_fps = job
                preview = render_preview(raw, results, labels, fire_class, cost, job_fps, args.preview_size, len(observed),
                                         min_confidence=args.conf)
                ok, encoded = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
                if not ok:
                    raise RuntimeError('标注图片JPEG编码失败')
                send_result(live_sender, encoded.tobytes(), bool(observed))

            output_worker = LatestOutput(publish, on_close=live_sender.close)
            output_worker.start()
            sender = None  # 套接字交由输出线程关闭，异常时也由该线程清理。
            LOG.info('最新帧流水线：只保留最新输入/输出，JPEG与UDP在后台执行')
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
                # 低分匹配仅保留在跟踪器内部，输出画面与高分验收使用同一门槛。
                detections = [d for d in tracked.display if d.confidence is not None and d.confidence >= args.conf]
                fire_detections = list(tracked.observed)
            else:
                detections = [d for d in detections if d.confidence >= args.conf]
                if smoother is not None:
                    detections = smoother.update(detections, captured, frame.shape[:2])
                fire_detections = detections
            smooth_ms = (time.perf_counter() - smooth_started) * 1000
            cable_joint_count, power_equipment_count, maintenance_passage_count = count_fire_regions(fire_detections, frame.shape[:2])
            lesson.update_regions(cable_joint_count, power_equipment_count, maintenance_passage_count)
            fire_present = bool(fire_detections)
            if ptz is not None:
                target = max(fire_detections, key=lambda d: d.box[2] - d.box[0], default=None)
                ptz.update(None if target is None else target.box, frame.shape[1], frame.shape[0])
            if output_worker is not None:
                output_worker.submit((frame, tuple(detections), tuple(fire_detections), inference_ms, fps))
            if sender is not None or args.show or is_image:
                frame = render_preview(frame, detections, labels, fire_class, inference_ms, fps,
                                       0 if is_image else args.preview_size, len(fire_detections),
                                       min_confidence=args.conf)
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
                LOG.info('电缆接头区=%d 配电设备区=%d 检修通道区=%d',
                         cable_joint_count, power_equipment_count, maintenance_passage_count)
                last_log = now
            if is_image:
                args.output.mkdir(parents=True, exist_ok=True)
                destination = args.output / (source_path.stem + '_standard.jpg')
                destination.write_bytes(jpeg)
                report = {'version': 'standard', 'scenario': 'utility_tunnel_power_compartment', 'recognition': 'fire_only', 'model': str(model), 'labels': labels, 'fire_class': fire_class,
                          'fire_present': fire_present, 'fire_count': len(fire_detections),
                          'regions': {'cable_joint': cable_joint_count, 'power_equipment': power_equipment_count, 'maintenance_passage': maintenance_passage_count}, 'inference_ms': inference_ms,
                          'timing_ms': getattr(detector, 'last_timing', {}),
                          'detections': [{'box': list(d.box), 'class_id': d.class_id, 'label': labels[d.class_id], 'confidence': d.confidence} for d in detections]}
                destination.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                LOG.info('已保存标注图片和JSON：%s', destination)
            if args.show:
                cv2.imshow('Utility Tunnel Fire Standard', frame)
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
        config = runtime_config(ENABLE_BUZZER and not args.no_buzzer)
        LOG.info('管廊电力舱标准版：全区域有火即报警，额外确认时间=%s秒', DETECTION_CONFIRM_TIME)
        lesson = StandardSession(runtime_info, config, __file__, control_buzzer, buzzer, args.results_dir)
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
