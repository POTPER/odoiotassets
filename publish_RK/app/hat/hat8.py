# 安全帽视野对比试验版：在 hat 目录运行 python3 hat8.py。
# 同帧流水线：采集与发送并行，画面、检测结果、统计始终整组传递，不混用历史框。
# 固定摄像头位置，对比 hat2 与 hat3 中场景边缘的位置；像素数增加不等于视野扩大。

import ctypes
import logging
import socket
import struct
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

# OpenCV 使用 BGR：标签背景与对应检测框同色，文字按背景亮度选择黑白。
COLOR_HEAD = (255, 216, 128)
COLOR_HAT = (160, 60, 0)
COLOR_BLACK = (80, 80, 80)

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
UDP_SEND_TIMEOUT = 0.2  # 输出阻塞时超时，不无限等待
ENABLE_WINDOW_KEYS = False  # 默认用 Ctrl+C 停止；有本地窗口时可开启 Q/ESC 检查
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
_output_metadata = None
_output_metadata_key = None
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
                        break
                dropped = enqueue_latest(frames, (time.monotonic(), frame))
                with stats_lock:
                    stats['captured'] += 1
                    stats['dropped_input'] += int(dropped)
                frame = None
        except Exception:
            logging.exception("Capture worker failed")
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
        except Exception:
            logging.exception("Output worker failed")
            stopped.set()

    reader = Thread(target=capture_worker, daemon=True)
    sender = Thread(target=output_worker, daemon=True)
    rgb_buffer = None
    window_start = time.monotonic()
    previous = stats.copy()
    try:
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
            except Exception:
                logging.exception("Video detection failed")
            finally:
                if src_img:
                    releaseImg(src_img)
            if status != 0:
                heads = hats = 0
                results = []
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
    finally:
        stopped.set()
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
    return send_udp_payload(img_bytes, dest_addr)


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
    """执行 RKNN 推理，返回状态、head 数量、hat 数量和检测结果列表。"""
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
    try:
        #获取推理结果
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
