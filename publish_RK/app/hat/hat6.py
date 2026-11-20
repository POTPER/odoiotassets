# 安全帽视野对比试验版：在 hat 目录运行 python3 hat6.py。
# 基于 hat3：只调整绘制和预览，不裁切识别输入、不添加位置平滑。
# 固定摄像头位置，对比 hat2 与 hat3 中场景边缘的位置；像素数增加不等于视野扩大。

import ctypes
import logging
import socket
import time
from queue import Queue, Empty, Full
from threading import Thread, Lock, Event

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
# 请求较高的原生采集尺寸；不支持时以摄像头实际输出为准，不做假分辨率放大。
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
# 第一项由上方宽高指定；按实际帧尺寸确认，不将软件放大当作1080P采集。
CAMERA_MODE_FALLBACKS = [(1280, 720), (640, 480)]
USE_MJPEG = True
ENHANCE_INPUT = False  # 默认关闭增强以减少耗时；True 开启
CLAHE_CLIP_LIMIT = 1.5  # 温和增强亮度对比；过强可能放大噪声
REMOVE_DUPLICATES = True  # 改为 False 可单独对比图像增强的效果
DUPLICATE_IOU = 0.5
CROSS_CLASS_IOU = 0.75  # head/hat 几乎重合时保留置信度更高的一个
JPEG_QUALITY = 60
PREVIEW_MAX_WIDTH = 0  # 不做预览缩放，减少额外处理
PREVIEW_LONG_EDGE = 720  # 保留原预览最长边，等比例缩小，不补黑边
BOX_LINE_WIDTH = 4
LABEL_FONT_SCALE = 0.9
LABEL_LINE_WIDTH = 2
PREVIEW_FPS_LIMIT = 15  # 预览上限；实际识别帧率独立统计
RESULT_MAX_AGE = 0.3  # 历史结果超过此秒数不再绘制
OPENCV_THREADS = 1  # 避免多线程图像处理争抢处理器
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

def get_class_color(cls_id):
    """根据类别 id 返回检测框颜色。"""
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
                  COLOR_LABEL_BG, -1)
    cv2.putText(frame, item.name, (label_left + 4, label_top + text_height + 4),
                cv2.FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE, COLOR_LABEL_TEXT, LABEL_LINE_WIDTH, cv2.LINE_AA)


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


def prepare_preview(frame):
    if PREVIEW_MAX_WIDTH <= 0 or frame.shape[1] <= PREVIEW_MAX_WIDTH:
        return frame
    height = max(1, round(frame.shape[0] * PREVIEW_MAX_WIDTH / frame.shape[1]))
    return cv2.resize(frame, (PREVIEW_MAX_WIDTH, height), interpolation=cv2.INTER_AREA)


def fit_preview_output(frame):
    height, width = frame.shape[:2]
    scale = min(1.0, PREVIEW_LONG_EDGE / max(width, height))
    output_width = max(1, round(width * scale))
    output_height = max(1, round(height * scale))
    if (output_width, output_height) != (width, height):
        return cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_LINEAR)
    return frame


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


def run_live_video(cap, first_frame, clahe):
    stopped = Event()
    inference_queue = Queue(maxsize=1)
    preview_queue = Queue(maxsize=1)
    result_lock = Lock()
    state = {'results': [], 'time': 0.0, 'ai_fps': 0.0, 'preview_fps': 0.0}

    def capture_worker():
        frame = first_frame
        try:
            while not stopped.is_set():
                if frame is None:
                    ok, frame = cap.read()
                    if not ok or frame is None or frame.size == 0:
                        logging.error("Camera frame read failed")
                        break
                # 原图只读共享，绘图线程单独复制，避免影响推理。
                stamped = (time.monotonic(), frame)
                put_latest(inference_queue, stamped)
                put_latest(preview_queue, stamped)
                frame = None
        except Exception:
            logging.exception("Camera worker failed")
        finally:
            stopped.set()

    def preview_worker():
        next_send = 0.0
        window_start = time.monotonic()
        sent = 0
        try:
            while not stopped.is_set():
                try:
                    captured, raw = preview_queue.get(timeout=0.1)
                except Empty:
                    continue
                now = time.monotonic()
                if now < next_send:
                    continue
                next_send = now + 1.0 / PREVIEW_FPS_LIMIT
                with result_lock:
                    results = list(state['results'])
                    result_time = state['time']
                    ai_fps = state['ai_fps']
                    preview_fps = state['preview_fps']
                frame = fit_preview_output(raw).copy()
                scale_x = frame.shape[1] / raw.shape[1]
                scale_y = frame.shape[0] / raw.shape[0]
                age = now - result_time
                if age <= RESULT_MAX_AGE:
                    for item in results:
                        draw_detect_result(frame, preview_detection(item, scale_x, scale_y))
                cv2.putText(frame, f'VIDEO: {preview_fps:.1f} FPS  AI: {ai_fps:.1f} FPS',
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                cv2.putText(frame, f'HAT6 CAM:{raw.shape[1]}x{raw.shape[0]}',
                            (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2)
                if age > RESULT_MAX_AGE:
                    cv2.putText(frame, 'AI RESULT PENDING', (10, 100),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                elif any(item.id == 0 for item in results) and not any(item.id == 1 for item in results):
                    cv2.putText(frame, 'NO HAT DETECTED!', (10, 100),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                preview = frame
                ok, encoded = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    send(encoded.tobytes())
                    sent += 1
                elapsed = time.monotonic() - window_start
                if elapsed >= 2:
                    with result_lock:
                        state['preview_fps'] = sent / elapsed
                    window_start, sent = time.monotonic(), 0
        except Exception:
            logging.exception("Preview worker failed")
            stopped.set()

    reader = Thread(target=capture_worker, daemon=True)
    renderer = Thread(target=preview_worker, daemon=True)
    window_start = time.monotonic()
    processed = 0
    enhance_total = detect_total = 0.0
    try:
        cv2.setNumThreads(OPENCV_THREADS)
        start_control_thread()
        reader.start()
        renderer.start()
        logging.info("Latest-frame pipeline enabled; preview and AI rates are measured separately")
        while not stopped.is_set():
            try:
                captured, frame = inference_queue.get(timeout=0.1)
            except Empty:
                continue
            src_img = None
            ret = -1
            results = []
            headnum = hatnum = 0
            try:
                started = time.perf_counter()
                image = enhance_detection_frame(frame, clahe)
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                enhance_total += time.perf_counter() - started
                height, width, _ = rgb.shape
                src_img = getImageFromVideoFrame(width, height, rgb.nbytes, IMAGE_FORMAT_RGB888,
                                                rgb.ctypes.data_as(ctypes.c_char_p))
                started = time.perf_counter()
                ret, headnum, hatnum, results = detect(src_img)
                detect_total += time.perf_counter() - started
            except Exception:
                logging.exception("Video detection failed")
            finally:
                if src_img:
                    releaseImg(src_img)
            if ret != 0:
                headnum = hatnum = 0
                results = []
            with result_lock:
                state['results'] = results
                # 以采集时刻计算结果年龄，避免过时检测框长时间覆盖新画面。
                state['time'] = captured if ret == 0 else 0.0
            send_msginfo(f'{hatnum},{headnum}'.encode('utf-8'))
            processed += 1
            elapsed = time.monotonic() - window_start
            if elapsed >= 3:
                with result_lock:
                    state['ai_fps'] = processed / elapsed
                    video_fps = state['preview_fps']
                logging.info("AI %.1f FPS, preview %.1f FPS; prepare %.1f ms, detect %.1f ms; ENH=%s",
                             processed / elapsed, video_fps, enhance_total * 1000 / processed,
                             detect_total * 1000 / processed, ENHANCE_INPUT)
                window_start = time.monotonic()
                processed = 0
                enhance_total = detect_total = 0.0
            if cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q'), 27):
                break
    except KeyboardInterrupt:
        logging.info("User stopped video")
    finally:
        stopped.set()
        reader.join(timeout=1) if reader.ident is not None else None
        cap.release()
        renderer.join(timeout=1) if renderer.ident is not None else None
        stop_control_thread()
        cv2.destroyAllWindows()


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
            left =int( clamp(x1,0,modWidth) / letterbox_scale)
            top = int(clamp(y1,0,modHeight) / letterbox_scale)
            right =int( clamp(x2,0,modWidth) / letterbox_scale)
            bottom =int( clamp(y2,0,modHeight) / letterbox_scale)
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
        # 统计、绘制和云台选取统一使用去重后的结果。
        result = remove_duplicate_boxes(result)
        headnum = sum(item.id == 0 for item in result)
        hatnum = sum(item.id == 1 for item in result)
        max_face_sz = 0
        for item in result:
            if item.right - item.left > max_face_sz:
                max_face_sz = item.right - item.left
                center_face_x = (item.left + item.right) / 2.0
                center_face_y = (item.top + item.bottom) / 2.0
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
        cap, first_frame = open_camera()
        if cap is None:
            return
        clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)) if ENHANCE_INPUT else None
        run_live_video(cap, first_frame, clahe)
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
