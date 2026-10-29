#!/usr/bin/env python3
# ==================== 01 演示说明与设置 ====================
# 安全帽识别统计演示：读取摄像头、图片或视频，直接显示检测数量并保存识别记录和标注截图。
# 本入口为完整演示程序，使用现有RK3588模型及原厂推理接口。
# 运行：python3 BRICS2026_Final_Sample_hat.py
# 图片：python3 BRICS2026_Final_Sample_hat.py --source testimg/test1.jpg
# 输出：当前用户桌面/成果输出/安全帽识别演示/本次时间目录。

import argparse
import csv
import ctypes
import importlib.util
import json
import logging
import math
import os
import platform
import shutil
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / 'model/hat_rk3588_fp.rknn'
CAMERA_INDEX = 41
DEMO_SECONDS = 30
RECORD_INTERVAL = 1.0
CONFIDENCE = 0.5
CLASS_NAMES = ('head', 'hat', 'black')
# 演示配色：head橙色，hat青色，black灰色，按BGR顺序。
CLASS_COLORS = ((0, 165, 255), (255, 210, 0), (150, 150, 150))
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
LOG = logging.getLogger('helmet_demo')


# ==================== 02 结果与输出文件 ====================
@dataclass(frozen=True)
class Detection:
    class_id: int
    confidence: float
    box: tuple


def counts_for(detections):
    # 只统计本帧目标；没有人员跟踪，不累计人数，也不计算人员佩戴率。
    return tuple(sum(d.class_id == cls for d in detections) for cls in range(3))


def desktop_path():
    home = Path.home()
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                return Path(os.path.expandvars(winreg.QueryValueEx(key, 'Desktop')[0]))
        except OSError:
            pass
    else:
        path = Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'user-dirs.dirs'
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('XDG_DESKTOP_DIR='):
                    value = line.split('=', 1)[1].strip().strip('"').replace('${HOME}', str(home)).replace('$HOME', str(home))
                    if Path(value).is_absolute():
                        return Path(value)
        except OSError:
            pass
    return home / '桌面' if (home / '桌面').is_dir() else home / 'Desktop'


def safe_cell(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


class DemoRecorder:
    FIELDS = ('记录时间', '输入源', '帧序号', '头部目标数', '安全帽目标数', '其他目标数',
              '最高置信度', '推理耗时(ms)', '处理结果', '错误信息')

    def __init__(self, output_root, source, entry_path=__file__):
        base = Path(output_root) if output_root is not None else desktop_path() / '成果输出/安全帽识别演示'
        self.folder = base / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.folder.mkdir(parents=True, exist_ok=False)
        self.csv_path = self.folder / '识别记录.csv'
        self.image_path = self.folder / 'result.jpg'
        self.summary_path = self.folder / 'summary.json'
        self.source = str(source)
        self.last_recorded_frame = 0
        self.frame_count = self.record_count = self.error_count = 0
        self.peaks = [0, 0, 0]
        self.started_at = datetime.now().isoformat(timespec='seconds')
        self.last_error = ''
        shutil.copyfile(entry_path, self.folder / Path(entry_path).name)
        with self.csv_path.open('x', encoding='utf-8-sig', newline='') as stream:
            csv.writer(stream).writerow(self.FIELDS)
        self.finish('运行中')
        LOG.info('本次演示输出目录：%s', self.folder)

    def observe(self, frame_number, detections):
        self.frame_count = frame_number
        self.peaks = [max(old, now) for old, now in zip(self.peaks, counts_for(detections))]

    def record(self, frame_number, detections, inference_ms, jpeg):
        counts = counts_for(detections)
        confidence = max((d.confidence for d in detections), default=None)
        row = [datetime.now().isoformat(timespec='milliseconds'), safe_cell(self.source), frame_number,
               *counts, '' if confidence is None else round(confidence, 4), round(inference_ms, 2), '识别成功', '']
        with self.csv_path.open('a', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerow(row)
        temporary = self.image_path.with_suffix('.jpg.tmp')
        temporary.write_bytes(jpeg)
        temporary.replace(self.image_path)
        self.record_count += 1
        self.last_recorded_frame = frame_number

    def error(self, message, frame_number=''):
        self.error_count += 1
        self.last_error = str(message)
        with self.csv_path.open('a', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerow([datetime.now().isoformat(timespec='milliseconds'), safe_cell(self.source),
                                        frame_number, '', '', '', '', '', '处理异常', safe_cell(self.last_error)])

    def finish(self, status):
        summary = {'演示名称': '安全帽识别统计演示', '状态': status, '输入源': self.source,
                   '开始时间': self.started_at, '更新时间': datetime.now().isoformat(timespec='seconds'),
                   '成功处理帧数': self.frame_count, '有效记录数': self.record_count,
                   '单帧头部目标数峰值': self.peaks[0], '单帧安全帽目标数峰值': self.peaks[1],
                   '单帧其他目标数峰值': self.peaks[2], '异常记录数': self.error_count,
                   '最近错误': self.last_error, '记录文件': self.csv_path.name,
                   '结果截图': self.image_path.name if self.image_path.is_file() else None,
                   '统计口径': '各类检测目标的单帧数量；未跟踪人员，不代表累计人数或佩戴率'}
        temporary = self.summary_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(self.summary_path)


# ==================== 03 RK3588 模型适配 ====================
def load_native_api():
    # 原接口按相对路径加载.so，仅在导入接口期间切换目录，随后立即恢复。
    # 本演示不导入比赛入口或设备控制模块。
    previous = Path.cwd()
    try:
        os.chdir(str(ROOT))
        spec = importlib.util.spec_from_file_location('_helmet_demo_native', ROOT / 'CHYoloModule.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(str(previous))


class NativeDetector:
    def __init__(self, model_path, confidence, api_factory=load_native_api):
        self.model_path, self.confidence = Path(model_path), confidence
        self.api_factory = api_factory
        self.api = None
        self.model_attempted = False
        self.destination = self.letterbox = None

    @staticmethod
    def checked(code, name):
        if code < 0:
            raise RuntimeError('{}失败：{}'.format(name, code))

    def start(self):
        self.api = a = self.api_factory()
        self.model_attempted = True
        result = a.modInit(str(self.model_path.resolve()).encode('utf-8'))
        if result != 0:
            raise RuntimeError('模型加载失败：{}'.format(result))
        self.checked(a.readRknnInputAndOutputAttr(), '读取模型属性')
        layout = a.getInputAttrFmt(0)
        if layout == a.RKNN_TENSOR_NCHW:
            self.height, self.width, self.channels = (a.getInputAttrDim(0, i) for i in (2, 3, 1))
        elif layout == a.RKNN_TENSOR_NHWC:
            self.height, self.width, self.channels = (a.getInputAttrDim(0, i) for i in (1, 2, 3))
        else:
            raise ValueError('不支持的模型输入布局：{}'.format(layout))
        if self.width <= 0 or self.height != self.width or self.channels != 3:
            raise ValueError('当前原厂模型适配要求正方形三通道输入')
        self.quantized = a.isQuant()
        if self.quantized not in (0, 1):
            raise ValueError('模型量化属性无效')
        self.metadata = []
        for index in range(3):
            gh, gw = a.getOutputAttrDim(index, 2), a.getOutputAttrDim(index, 3)
            if gh <= 0 or gw <= 0 or self.width % gw:
                raise ValueError('模型输出网格无效')
            zp, scale = (a.getOutputZp(index), a.getOutputScale(index)) if self.quantized else (0, 1.0)
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError('模型量化比例无效')
            self.metadata.append((gh, gw, self.width // gw, zp, scale))
        self.destination = a.initInferenceImg(self.width, a.IMAGE_FORMAT_RGB888, self.height)
        if not self.destination:
            raise RuntimeError('模型输入缓冲区创建失败')
        self.letterbox = a.initLetterBox()
        if not self.letterbox:
            raise RuntimeError('等比例图像预处理初始化失败')

    def infer(self, frame, cv2):
        a = self.api
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = a.getImageFromVideoFrame(width, height, rgb.nbytes, a.IMAGE_FORMAT_RGB888,
                                        rgb.ctypes.data_as(ctypes.c_char_p))
        if not image:
            raise RuntimeError('输入帧转换失败')
        outputs = None
        try:
            self.checked(a.convertImageWithLetterbox(image, self.destination, self.letterbox, 114), '图像预处理')
            self.checked(a.setRknnInput(0, a.RKNN_TENSOR_UINT8, a.RKNN_TENSOR_NHWC,
                                       self.width, self.height, self.channels, self.destination), '设置模型输入')
            self.checked(a.startRknnRun(), '模型推理')
            outputs = a.initOutputsObj(self.quantized)
            if not outputs:
                raise RuntimeError('推理输出缓冲区创建失败')
            self.checked(a.getRknnOutpus(outputs), '读取模型输出')
            a.initProcessOutputData()
            count = 0
            for i, (gh, gw, stride, zp, scale) in enumerate(self.metadata):
                if self.quantized:
                    value = a.StartProcessI8(i, outputs, gh, gw, self.height, self.width, stride, 0.35, zp, scale)
                else:
                    value = a.StartProcessFp32(i, outputs, gh, gw, self.height, self.width, stride, 0.35)
                self.checked(value, '解析检测候选')
                count += value
            a.StartNms(count, 0.5)
            xpad, ypad = a.getLetterBoxXPad(self.letterbox), a.getLetterBoxYPad(self.letterbox)
            scale = a.getLetterBoxScale(self.letterbox)
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError('图像缩放比例无效')
            result = []
            for j in range(count):
                index = a.getIndexArray(j)
                if index < 0:
                    continue
                score = a.getObjProbs(j)
                cls = a.getClassId(index)
                if cls not in range(3) or not math.isfinite(score) or not self.confidence <= score <= 1:
                    continue
                x, y, w, h = (a.getFilterBoxes(index * 4 + i) for i in range(4))
                coordinates = ((x - xpad) / scale, (y - ypad) / scale,
                               (x + w - xpad) / scale, (y + h - ypad) / scale)
                if not all(math.isfinite(v) for v in coordinates):
                    continue
                left, top, right, bottom = coordinates
                box = (max(0, min(width - 1, left)), max(0, min(height - 1, top)),
                       max(0, min(width - 1, right)), max(0, min(height - 1, bottom)))
                if box[2] > box[0] and box[3] > box[1]:
                    result.append(Detection(cls, score, box))
            return result
        finally:
            try:
                if outputs:
                    a.releaseRknnOutput(outputs)
            finally:
                a.releaseImg(image)

    def close(self):
        errors = []
        if self.api is None:
            return errors
        actions = []
        if self.letterbox:
            actions.append(('释放预处理', lambda: self.api.releaseLetterBox(self.letterbox)))
        if self.destination:
            actions.append(('释放模型图像', lambda: self.api.releaseImg(self.destination)))
        if self.model_attempted:
            actions.append(('卸载模型', self.api.uninitlib))
        for name, action in actions:
            try:
                action()
            except Exception as exc:
                errors.append('{}：{}'.format(name, exc))
        self.api = None
        return errors


# ==================== 04 标注画面及原协议回传 ====================
def render_frame(frame, detections, frame_number, inference_ms, cv2):
    height, width = frame.shape[:2]
    scale = min(1.0, 720.0 / max(width, height))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    preview = cv2.resize(frame, size) if size != (width, height) else frame.copy()
    sx, sy = preview.shape[1] / width, preview.shape[0] / height
    for detection in detections:
        left, top, right, bottom = detection.box
        left, right = round(left * sx), round(right * sx)
        top, bottom = round(top * sy), round(bottom * sy)
        color = CLASS_COLORS[detection.class_id]
        cv2.rectangle(preview, (left, top), (right, bottom), color, 2)
        label = '{} {:.2f}'.format(CLASS_NAMES[detection.class_id], detection.confidence)
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        lx = max(0, min(left, preview.shape[1] - tw - 8))
        ly = max(th + 7, min(top, preview.shape[0] - baseline - 2))
        cv2.rectangle(preview, (lx, ly - th - 6), (min(preview.shape[1] - 1, lx + tw + 8), ly + baseline), color, -1)
        cv2.putText(preview, label, (lx + 4, ly - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    heads, hats, other = counts_for(detections)
    # 统计条放在画面下方，检测框保持原图对应关系。
    view = cv2.copyMakeBorder(preview, 0, 68, 0, 0, cv2.BORDER_CONSTANT, value=(32, 25, 18))
    y = preview.shape[0]
    cv2.putText(view, 'HELMET VISION DEMO | Frame {}'.format(frame_number), (10, y + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(view, 'head: {}   hat: {}   other: {}   inference: {:.1f} ms'.format(heads, hats, other, inference_ms),
                (10, y + 51), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 225, 130), 1, cv2.LINE_AA)
    return view


class PreviewSender:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.socket = None
        self.group = 0

    def _send(self, payload, port):
        self.group = (self.group + 1) & 0xffffffff
        count = math.ceil(len(payload) / 60000)
        for index in range(count):
            chunk = payload[index * 60000:(index + 1) * 60000]
            self.socket.sendto(struct.pack('<4I', self.group, count, index, len(chunk)) + chunk, ('127.0.0.1', port))

    def send(self, jpeg, counts):
        if not self.enabled:
            return
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(0.2)
        heads, hats, _ = counts
        self._send('{},{}'.format(hats, heads).encode('utf-8'), 8089)
        self._send(jpeg, 8088)

    def close(self):
        if self.socket is not None:
            self.socket.close()


# ==================== 05 输入及环境检查 ====================
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='完整的安全帽识别统计演示：画面、计数、CSV和结果截图')
    parser.add_argument('--source', default=str(CAMERA_INDEX), help='摄像头编号、图片或本地视频，默认41')
    parser.add_argument('--model', type=Path, default=MODEL_PATH, help='RK3588模型路径')
    parser.add_argument('--duration', type=float, default=DEMO_SECONDS, help='视频演示秒数，默认30；0持续至手动停止')
    parser.add_argument('--record-interval', type=float, default=RECORD_INTERVAL, help='CSV记录间隔，默认1秒')
    parser.add_argument('--confidence', type=float, default=CONFIDENCE, help='显示目标的最低置信度，默认0.5')
    parser.add_argument('--output-dir', type=Path, help='输出根目录；每次运行建立独立时间目录')
    parser.add_argument('--show', action='store_true', help='额外打开OpenCV预览窗口，Q或ESC结束')
    parser.add_argument('--no-udp', action='store_true', help='关闭本机画面回传，仍保存本地结果')
    parser.add_argument('--check', action='store_true', help='仅静态检查环境，不运行模型或摄像头、不生成成果')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error('--duration必须为有限非负数')
    if not math.isfinite(args.record_interval) or args.record_interval <= 0:
        parser.error('--record-interval必须为有限正数')
    if not math.isfinite(args.confidence) or not 0 < args.confidence <= 1:
        parser.error('--confidence必须大于0且不超过1')
    return args


def check_environment(args):
    for name in ('cv2', 'numpy'):
        if importlib.util.find_spec(name) is None:
            raise RuntimeError('缺少Python依赖：{}'.format(name))
    for path in (Path(__file__), ROOT / 'CHYoloModule.py', ROOT / 'libCHYoloV5.so', args.model):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('配套文件缺失或为空：{}'.format(path))
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
    LOG.info('文件与Python依赖检查通过；当前系统：%s %s', platform.system(), platform.machine())
    LOG.info('模型和原厂动态库需在匹配的RK3588 Linux环境运行；本次未加载模型或连接摄像头')
    return 0


def open_capture(source, live, cv2):
    modes = [(1280, 720, True), (640, 480, False), (None, None, False)] if live else [(None, None, False)]
    for width, height, mjpeg in modes:
        capture = None
        accepted = False
        try:
            capture = cv2.VideoCapture(source)
            if not capture.isOpened():
                continue
            if width is not None:
                if mjpeg:
                    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            for _ in range(3 if live else 1):
                ok, frame = capture.read()
                if ok and frame is not None and frame.size:
                    LOG.info('实际输入尺寸：%dx%d', frame.shape[1], frame.shape[0])
                    accepted = True
                    return capture, frame
        finally:
            if capture is not None and not accepted:
                capture.release()
    raise RuntimeError('输入无法读取，请检查摄像头编号、设备占用或视频文件')


# ==================== 06 演示流程 ====================
def run_demo(args, detector_factory=NativeDetector):
    # 先创建输出目录，加载或采集失败时也尽可能留下真实错误记录。
    recorder = DemoRecorder(args.output_dir, args.source)
    detector = capture = None
    sender = PreviewSender(not args.no_udp)
    stopped = Event()
    handlers = {}
    pending = None
    status, exit_code = '已完成', 0
    cv2 = None

    def flush_pending():
        if pending is not None and recorder.last_recorded_frame != pending[0]:
            recorder.record(*pending)

    def record_error(error):
        LOG.error('%s', error)
        try:
            recorder.error(str(error))
        except OSError:
            LOG.exception('异常记录无法写入')

    try:
        import cv2
        import numpy as np
        cv2.setNumThreads(1)
        for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
            signum = getattr(signal, name, None)
            if signum is not None:
                handlers[signum] = signal.signal(signum, lambda *_: stopped.set())
        source = int(args.source) if str(args.source).isdigit() else str(Path(args.source).resolve())
        live = isinstance(source, int)
        is_image = not live and Path(source).suffix.lower() in IMAGE_EXTENSIONS
        if not live and not Path(source).is_file():
            raise FileNotFoundError('输入文件不存在：{}'.format(source))
        if is_image:
            frame = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None or not frame.size:
                raise RuntimeError('图片无法解码')
        else:
            capture, frame = open_capture(source, live, cv2)
        detector = detector_factory(args.model, args.confidence)
        detector.start()
        started = time.monotonic()
        last_recorded = float('-inf')
        udp_failed = False
        while not stopped.is_set():
            if not is_image and args.duration and time.monotonic() - started >= args.duration:
                break
            began = time.perf_counter()
            detections = detector.infer(frame, cv2)
            inference_ms = (time.perf_counter() - began) * 1000
            if stopped.is_set():
                break
            number = recorder.frame_count + 1
            view = render_frame(frame, detections, number, inference_ms, cv2)
            ok, encoded = cv2.imencode('.jpg', view, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError('结果画面JPEG编码失败')
            jpeg = encoded.tobytes()
            recorder.observe(number, detections)
            pending = (number, detections, inference_ms, jpeg)
            now = time.monotonic()
            if now - last_recorded >= args.record_interval:
                flush_pending()
                recorder.finish('运行中')
                last_recorded = now
                LOG.info('帧%d：头部目标=%d，安全帽目标=%d，其他目标=%d，推理=%.1fms',
                         number, *counts_for(detections), inference_ms)
            try:
                sender.send(jpeg, counts_for(detections))
            except OSError as exc:
                if not udp_failed:
                    record_error('UDP回传失败，本地记录继续：{}'.format(exc))
                udp_failed = True
                sender.enabled = False
            if args.show:
                cv2.imshow('Helmet Vision Demo', view)
                if cv2.waitKey(1) & 0xff in (ord('q'), 27):
                    stopped.set()
            if is_image or stopped.is_set():
                break
            ok, frame = capture.read()
            if not ok or frame is None or not frame.size:
                if live:
                    raise RuntimeError('摄像头采集断开，未将无效帧作为零目标记录')
                break  # 本地视频正常结束。
        if stopped.is_set():
            status = '用户停止'
    except KeyboardInterrupt:
        status = '用户停止'
    except Exception as exc:
        status, exit_code = '失败', 1
        record_error('{}：{}'.format(type(exc).__name__, exc))
    finally:
        try:
            flush_pending()
        except Exception as exc:
            status, exit_code = '失败', 1
            record_error('最后一次结果保存失败：{}'.format(exc))
        if capture is not None:
            try:
                capture.release()
            except Exception as exc:
                status, exit_code = '失败', 1
                record_error('释放输入失败：{}'.format(exc))
        if detector is not None:
            try:
                for error in detector.close():
                    status, exit_code = '失败', 1
                    record_error(error)
            except Exception as exc:
                status, exit_code = '失败', 1
                record_error('模型清理失败：{}'.format(exc))
        try:
            sender.close()
            if args.show and cv2 is not None:
                cv2.destroyAllWindows()
        except Exception as exc:
            record_error('预览资源清理失败：{}'.format(exc))
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        recorder.finish(status)
    LOG.info('%s：处理%d帧，保存%d条有效记录；结果目录：%s',
             status, recorder.frame_count, recorder.record_count, recorder.folder)
    return exit_code


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    try:
        return check_environment(args) if args.check else run_demo(args)
    except Exception as exc:
        LOG.error('演示启动或结果归档失败：%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
