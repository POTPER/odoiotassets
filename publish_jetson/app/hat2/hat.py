import ctypes
import logging
import socket
import time
from collections import Counter, deque
from queue import Queue, Empty, Full
from threading import Thread, Lock

import cv2
import numpy as np

from CHYoloModule import *
from SensorModule import *
from UdpPackage import *

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# RKNN 推理阈值。
BOX_THRESH = 0.35
NMS_THRESH = 0.5
CONFIDENCE_VAL = 0.5

# 视频检测框稳定参数；数值越小，平滑越明显，但跟随运动会更慢。
BOX_SMOOTH_ALPHA = 0.45
TRACK_IOU_THRESHOLD = 0.3
TRACK_CONFIRM_FRAMES = 2  # 连续出现两帧后显示，过滤单帧误检
TRACK_HOLD_SECONDS = 0.2  # 短暂漏检保留框的最长时间
TRACK_MAX_MISSES = 2
CLASS_VOTE_FRAMES = 3  # 最近三次匹配结果投票，减少类别跳变

# 类别顺序必须和 RKNN 模型输出一致。
CLASS_NAMES = ['head', 'hat', 'black']

# OpenCV 使用 BGR：head 淡蓝色，hat 深蓝色，标签白底深字。
COLOR_HEAD = (255, 216, 128)
COLOR_HAT = (160, 60, 0)
COLOR_BLACK = (80, 80, 80)
COLOR_LABEL_BG = (255, 255, 255)
COLOR_LABEL_TEXT = (30, 30, 30)

# 摄像头、图像编码、模型路径和 UDP 目标配置。
CAMERA_INDEX = 41
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
JPEG_QUALITY = 70
MODEL_PATH = './model/hat_rk3588_fp.rknn'
DEST_ADDR = ('127.0.0.1', 8088)
DEST_ADDR_INFO = ('127.0.0.1', 8089)
dest_addr = DEST_ADDR
dest_addr2 = DEST_ADDR_INFO
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
control_lock = Lock()

# UDP 分包状态。
max_packet_size = 60000
global_id = 0
global_id_lock = Lock()

# 异步 AI 识别状态。
_frame_queue = Queue(maxsize=3)
_parse_thread = None
_parse_video = False
_AIParseResult = []
_ai_result_lock = Lock()
_parseing = False
_parse_state_lock = Lock()

# 异步图片发送队列。
_send_queue = Queue(maxsize=3)
_send_thread = None
_send_running = False

# RKNN 图像缓存和模型属性。
destImage = 0
letter_box = 0


modWidth = 0
modHeight = 0
modChannel = 0
bQuant = 0
last_direction = 0   
_control_running = False
control_flags = 8
modules = None
_control_thread = None

# 云台控制配置。
ptzModIndex = 17
modStatus = 0
# 云台控制速度：1-5。
ptzSpeed = 5

use_ptz = 0

# 目标偏离画面中心超过该像素阈值后才触发云台移动。
OFFSET_TRED = 50

class detectResult:
    """RKNN 后处理返回的单个检测框。"""

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
    """根据类别 id 返回显示名称。"""
    if 0 <= cls_id < len(CLASS_NAMES):
        return CLASS_NAMES[cls_id]
    return "unknown"


def box_iou(first, second):
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    area_a = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    area_b = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


class DetectionStabilizer:
    # 仅稳定视频输出，不改变模型、驱动和单张图片检测结果。
    def __init__(self):
        self.tracks = []

    def reset(self):
        self.tracks.clear()

    def update(self, detections, now):
        self.tracks = [track for track in self.tracks
                       if track['misses'] == 0 or now - track['seen'] <= TRACK_HOLD_SECONDS]
        boxes = [(item.left, item.top, item.right, item.bottom) for item in detections]
        candidates = []
        for index, track in enumerate(self.tracks):
            for other, item in enumerate(detections):
                # head 与 hat 允许在同一目标上切换；black 单独匹配。
                if item.id == track['class'] or {item.id, track['class']} <= {0, 1}:
                    overlap = box_iou(track['box'], boxes[other])
                    if overlap >= TRACK_IOU_THRESHOLD:
                        candidates.append((overlap, index, other))
        matched_tracks, matched_detections = set(), set()
        for _, index, other in sorted(candidates, reverse=True):
            if index in matched_tracks or other in matched_detections:
                continue
            matched_tracks.add(index)
            matched_detections.add(other)
            track, item = self.tracks[index], detections[other]
            track['box'] = tuple(old + BOX_SMOOTH_ALPHA * (new - old)
                                 for old, new in zip(track['box'], boxes[other]))
            track['votes'].append(item.id)
            counts = Counter(track['votes'])
            # 票数相同优先保持原类别。
            track['class'] = max(counts, key=lambda value: (counts[value], value == track['class']))
            track['hits'] = track['hits'] + 1 if track['misses'] == 0 else 1
            track['confirmed'] |= track['hits'] >= TRACK_CONFIRM_FRAMES
            track.update(seen=now, misses=0, confidence=item.prop)
        for index, track in enumerate(self.tracks):
            if index not in matched_tracks:
                track['misses'] += 1
                track['hits'] = 0
        for index, item in enumerate(detections):
            if index not in matched_detections:
                self.tracks.append(dict(box=boxes[index], votes=deque([item.id], maxlen=CLASS_VOTE_FRAMES),
                                        **{'class': item.id}, hits=1, misses=0, seen=now,
                                        confirmed=TRACK_CONFIRM_FRAMES <= 1, confidence=item.prop))
        self.tracks = [track for track in self.tracks
                       if track['misses'] <= TRACK_MAX_MISSES
                       and (track['misses'] == 0 or now - track['seen'] <= TRACK_HOLD_SECONDS)]
        results = []
        for track in self.tracks:
            if not track['confirmed']:
                continue
            item = detectResult(*(int(round(value)) for value in track['box']),
                                track['confidence'], track['class'])
            item.observed = track['misses'] == 0
            if not item.observed:
                item.name += ' HOLD'
            results.append(item)
        return results

def get_class_color(cls_id):
    """根据类别 id 返回检测框颜色。"""
    if cls_id == 0:
        return COLOR_HEAD
    if cls_id == 1:
        return COLOR_HAT
    return COLOR_BLACK

def draw_detect_result(frame, item):
    """绘制检测框和白底深字的识别标签。"""
    box_color = get_class_color(item.id)
    cv2.rectangle(frame, (item.left, item.top), (item.right, item.bottom), box_color, 2)
    label_size = cv2.getTextSize(item.name, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
    label_top = max(item.top - label_size[1] - 5, 0)
    cv2.rectangle(frame, (item.left, label_top), (item.left + label_size[0], item.top), COLOR_LABEL_BG, -1)
    cv2.putText(frame, item.name, (item.left, max(item.top - 5, 0)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_LABEL_TEXT, 2)

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
        
#异步AI识别视频数据
def _async_AIParse_worker():
    """后台消费视频帧，执行 RKNN 检测并缓存最新识别结果。"""
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
#开始异步视频分析
def start_async_parsingthread():
    """启动异步 AI 识别线程。"""
    global _parse_thread, _parse_video
    if _parse_thread is None or not _parse_thread.is_alive():
        _parse_video = True
        logging.info("start ai parse thread")
        _parse_thread = Thread(target=_async_AIParse_worker, daemon=True)
        _parse_thread.start()

def stop_async_parsingthread():
    """停止异步 AI 识别线程。"""
    global _parse_video
    _parse_video = False
    if _parse_thread:
        try:
            _frame_queue.put_nowait(None)
        except Full:
            pass
        _parse_thread.join(timeout=1)
#异步发送图片数据
def send_video_frame_async(img_bytes):
    """把视频帧放入 AI 识别队列，队列满时丢弃当前帧。"""
    try:
        _frame_queue.put_nowait(img_bytes)
    except Full:
        pass
    except Exception:
        logging.exception("failed to enqueue frame for AI parsing")
     
def _async_send_worker():
    """后台发送 JPEG 图像 UDP 分包。"""
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
    """启动异步 UDP 图像发送线程。"""
    global _send_thread, _send_running
    if _send_thread is None or not _send_thread.is_alive():
        _send_running = True
        _send_thread = Thread(target=_async_send_worker, daemon=True)
        _send_thread.start()

def stop_async_sender():
    """停止异步 UDP 图像发送线程。"""
    global _send_running
    _send_running = False
    if _send_thread:
        try:
            _send_queue.put_nowait(None)
        except Full:
            pass
        _send_thread.join(timeout=1)
        
def send_msginfo(msginfo_bytes):
    """发送检测统计信息，格式保持 hatnum,headnum。"""
    #print( msginfo_bytes)
    try:
        packets = getUdpPackages(msginfo_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr2)
    except Exception:
        logging.exception("failed to send UDP message info")
def getUdpPackages(bytes_data):
    """为一段数据生成带递增分组 id 的 UDP 分包。"""
    global global_id
    with global_id_lock:
        global_id += 1
        packet_group_id = global_id
    return buildUdpPackages(bytes_data, packet_group_id, max_packet_size)

class detResultBox:
    """低层后处理检测框数据结构。"""

    def __init__(self, left, top,right,bottom,prop,cls_id):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.prop = prop
        self.cls_id = cls_id
def send_async(img_bytes):
    """把编码后的图像放入异步 UDP 发送队列。"""
    try:
        _send_queue.put_nowait(img_bytes)
    except Full:
        pass
    except Exception:
        logging.exception("failed to enqueue frame for UDP sending")
def send(img_bytes):
    """同步发送一张图片的 UDP 分包。"""
    try:
        packets = getUdpPackages(img_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr)
    except Exception:
        logging.exception("failed to send UDP image")
def convert_image_buffer_to_cv2(virtaddr,width,height,size,fmt):
    """把底层图像缓存转换为 OpenCV BGR 图像。"""
    #print("convert_image_buffer_to_cv2 width="+str(width)+"height="+str(height)+"size="+str(size))
    buffer_bytes = ctypes.string_at(virtaddr, size)
    buffer_array = np.frombuffer(buffer_bytes, dtype=np.uint8)
    img = buffer_array.reshape((height, width, 3))
    if fmt == IMAGE_FORMAT_RGB888:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        raise ValueError(f"Unsupported image format: {fmt}")
    img = img.copy()
    return img
def _async_control_worker():
    """异步控制工作线程"""
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
                    #连接温湿度模块
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
    """启动控制线程"""
    global _control_thread, _control_running
    if _control_thread is None or not _control_thread.is_alive():
        _control_running = True
        _control_thread = Thread(target=_async_control_worker, daemon=True)
        _control_thread.start()
        logging.info("control thread started")

def stop_control_thread():
    """停止控制线程"""
    global _control_running
    _control_running = False
    if _control_thread:
        _control_thread.join(timeout=1)
        logging.info("control thread stopped")

def detect(src_img):
    """执行 RKNN 推理，返回状态、head 数量、hat 数量和检测结果列表。"""
    global control_flags
    #数据
    max_face_sz = 0
    center_face_x=0
    center_face_y = 0

    hatnum = 0
    headnum = 0
    outputs = 0
    ret = convertImageWithLetterbox(src_img,destImage,letter_box,114)
    if ret==-1:
        return -1,0,0,[]
    #设置inputattr
    ret = setRknnInput(0,RKNN_TENSOR_UINT8,RKNN_TENSOR_NHWC,modWidth,modHeight,modChannel,destImage)
    if ret == -1:
        return -1,0,0,[]
    #开始推理
    ret = startRknnRun()
    if ret==-1:
        return -1,0,0,[]
    #初始化输出,参数是是否需要量化
    outputs = initOutputsObj(bQuant)
    if outputs==0:
        return -1,0,0,[]
    #获取推理结果
    ret = getRknnOutpus(outputs)
    if ret == -1:
        releaseRknnOutput(outputs)
        return -1,0,0,[]
    validCount = 0
    initProcessOutputData();
    result = []
    x_pad = getLetterBoxXPad(letter_box)
    y_pad = getLetterBoxYPad(letter_box)
    letterbox_scale = getLetterBoxScale(letter_box)
    frame_center_x = (getImageWidth(src_img) or FRAME_WIDTH) / 2.0
    frame_center_y = (getImageHeight(src_img) or FRAME_HEIGHT) / 2.0
    for i in range(3):
        zp = getOutputZp(i)
        scale = getOutputScale(i)
        grid_h = getOutputAttrDim(i,2)
        grid_w = getOutputAttrDim(i,3)
        stride = int(modWidth / grid_h)
        if bQuant == 0:
            validCount+=StartProcessFp32(i,outputs,grid_h,grid_w,modHeight,modWidth,stride,BOX_THRESH)
        else:
            validCount+=StartProcessI8(i,outputs,grid_h,grid_w,modHeight,modWidth,stride,BOX_THRESH,zp,scale)
    StartNms(validCount,NMS_THRESH)
    if validCount>0:
        for j in range(validCount):
            
            if getIndexArray(j) == -1:
                continue
            n = getIndexArray(j);
            id = getClassId(n)
            
            x1 = getFilterBoxes(n * 4 + 0) - x_pad
            y1 = getFilterBoxes(n * 4 + 1) - y_pad
            x2 = x1 + getFilterBoxes(n * 4 + 2)
            y2 = y1 + getFilterBoxes(n * 4 + 3)
            obj_conf = getObjProbs(j)
            # 先还原到原图坐标，再按原图边界裁剪，避免 padding 边缘框越界。
            left = int(clamp(x1 / letterbox_scale, 0, getImageWidth(src_img)))
            top = int(clamp(y1 / letterbox_scale, 0, getImageHeight(src_img)))
            right = int(clamp(x2 / letterbox_scale, 0, getImageWidth(src_img)))
            bottom = int(clamp(y2 / letterbox_scale, 0, getImageHeight(src_img)))
            if right <= left or bottom <= top:
                continue
            if obj_conf>CONFIDENCE_VAL:
                result.append(detectResult(left,top,right,bottom,obj_conf,id))
                if(max_face_sz<right-left):
                    max_face_sz = right-left
                    center_face_x =left+ (right-left)/2.0
                    center_face_y = top+(bottom -top)/2.0
                if id == 0:
                    headnum+=1
                elif id == 1:
                    hatnum+=1
        if max_face_sz>0:
            if center_face_x - frame_center_x >OFFSET_TRED :
                if center_face_y - frame_center_y>OFFSET_TRED:
                    #人脸在右下位置，如果云台停止状态，则控制云台朝右下运动，
                    #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(4)
                    elif last_direction!=4:
                        set_control_flags(8)
                #人脸在右上位置，如果云台停止状态，则控制云台朝右上运动，
                #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                elif frame_center_y-center_face_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始转动
                        set_control_flags(5)
                    elif last_direction!=5:
                        set_control_flags(8)
                #人脸在右边位置，如果云台停止状态，则控制云台朝右运动，
                #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                else:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(0)
                    elif last_direction!=0:
                        set_control_flags(8)
            elif frame_center_x-center_face_x>OFFSET_TRED:
                #人脸在左下位置，如果云台停止状态，则控制云台朝左下运动，
                #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                if center_face_y - frame_center_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(6)
                    elif last_direction!=6:
                        set_control_flags(8)
                elif frame_center_y-center_face_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(7)
                    elif last_direction!=7:
                        set_control_flags(8)
                else:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(1)
                    elif last_direction!=1:
                        set_control_flags(8)
            else:
                if center_face_y - frame_center_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(3)
                    elif last_direction!=3:
                        set_control_flags(8)
                elif frame_center_y-center_face_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        set_control_flags(2)
                    elif last_direction!=2:
                        set_control_flags(8)
                else:
                    if  last_direction!=8:
                        set_control_flags(8)
        else:
            if  last_direction!=8:
                set_control_flags(8)
    releaseRknnOutput(outputs)
    return 0,headnum,hatnum,result
def initYoloModel(model_path):
     ret = modInit(model_path.encode('utf-8'))
     if ret != 0:
         print("mod init failed")
         return -1;
     readRknnInputAndOutputAttr()
            
     return ret
def uninitYolodModel():
    return uninitlib()    
def check_input_type(input_path):
    """根据输入类型处理单张图片或摄像头视频流。"""
    if input_path.endswith(('.jpg', '.png', '.jpeg', '.bmp')):
        #print('Inference: ', input_path)
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
        global _parseing,_AIParseResult
        stabilizer = DetectionStabilizer()
        cap = cv2.VideoCapture(CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 减少摄像头缓冲区
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)  # 降低分辨率
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        #启动云台控制线程
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        start_control_thread()
        # 启动异步发送线程
        start_async_sender()
        #启动异步AI视频分析
        logging.info("AI parsing uses synchronous video mode")
        # 帧率统计
        prev_time = time.time()
        fps = 0.0
        fps_smooth = 0.0
        detect_fps_smooth = 0.0
        detect_ms_smooth = 0.0
        frame_count = 0
        
        # JPEG编码参数
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        # 预热模型
        while True:
            ret, frame = cap.read()
            if not ret:
                print('无法读取摄像头帧')
                break
            src_img = None
            ret_detect = -1
            headnum = 0
            hatnum = 0
            results = []
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channel = frame.shape
                data_size = frame.nbytes
                src_img = getImageFromVideoFrame(width,height,data_size,IMAGE_FORMAT_RGB888,frame_rgb.ctypes.data_as(ctypes.c_char_p))
                detect_start_time = time.time()
                ret_detect,headnum,hatnum,results=detect(src_img)
                detect_cost = time.time() - detect_start_time
                if detect_cost > 0:
                    detect_ms = detect_cost * 1000.0
                    detect_fps = 1.0 / detect_cost
                    detect_ms_smooth = 0.9 * detect_ms_smooth + 0.1 * detect_ms
                    detect_fps_smooth = 0.9 * detect_fps_smooth + 0.1 * detect_fps
            except Exception:
                logging.exception("sync video detect failed")
            finally:
                if src_img:
                    releaseImg(src_img)
            if ret_detect != 0:
                # 推理失败立即清空，不能用上一帧结果伪装本帧识别成功。
                stabilizer.reset()
                results = []
            else:
                results = stabilizer.update(results, time.monotonic())
            headnum = sum(item.id == 0 and item.observed for item in results)
            hatnum = sum(item.id == 1 and item.observed for item in results)
            send_msginfo(bytes(str(hatnum) + ',' + str(headnum), encoding='utf-8'))
            no_hat_detected = headnum > 0 and hatnum == 0
            for item in results:
                draw_detect_result(frame, item)
            # 计算实时帧率
            curr_time = time.time()
            fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
            prev_time = curr_time
            fps_smooth = 0.9 * fps_smooth + 0.1 * fps
            
            # 在图像上显示帧率
            fps_text = f'FPS: {fps_smooth:.1f}'
            detect_fps_text = f'DET: {detect_fps_smooth:.1f} FPS / {detect_ms_smooth:.1f} ms'
            cv2.putText(frame, fps_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(frame, detect_fps_text, (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
            if no_hat_detected:
                cv2.putText(frame, "NO HAT DETECTED!", (10, 105), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            frame_count += 1
            if frame_count % 30 == 0:
                logging.info("detect fps %.1f, detect ms %.1f", detect_fps_smooth, detect_ms_smooth)
            _, img_encoded = cv2.imencode('.jpg', frame, encode_params)
            send_async(img_encoded.tobytes())
            key  = cv2.waitKey(1) & 0xFF
            
            # 退出条件
            if key == ord('q') or key == ord('Q') or key == 27:  # Q 或 ESC
                print("退出程序")
                break
        stop_async_sender()
        stop_async_parsingthread()
        cap.release()
        cv2.destroyAllWindows()
    else:
        print('输入非正确格式，重新输入！')

if __name__ == '__main__':
    
    is_video = True
    img_path = 'testimg/test1.jpg'
    # 模块初始化
    modules = SensorModule()
    # 开始搜索模块
    modules.startScanSensors()
    # 连接继电器模块
    ret = modules.modConnect(ptzModIndex)
    if ret<=0:
        print("主控模块连接失败")
    else:
        print("主控模块连接正常")
    model_path = MODEL_PATH
    initYoloModel(model_path)
    fmt = getInputAttrFmt(0)
    if fmt == RKNN_TENSOR_NCHW:
        #model is NCHW input fmt
        modWidth = getInputAttrDim(0,3)
        modHeight = getInputAttrDim(0,2)
        modChannel = getInputAttrDim(0,1)
    else:
        #model is NHWC input fmt
        modWidth = getInputAttrDim(0,2)
        modHeight = getInputAttrDim(0,1)
        modChannel = getInputAttrDim(0,3)
    bQuant = isQuant()
    #初始化用户推理的数据数据，图像数据的格式是RGB888格式
    destImage = initInferenceImg(modWidth,IMAGE_FORMAT_RGB888,modHeight)
    #初始化letterbox,返回letterbox句柄
    letter_box = initLetterBox()
    if is_video:
        check_input_type('video')
    else:
        check_input_type(img_path)
    releaseLetterBox(letter_box)
    releaseImg(destImage)
    uninitYolodModel()
    stop_async_parsingthread()
    stop_control_thread()
    modules.modDisconnect(ptzModIndex)
    modules.uninit()
