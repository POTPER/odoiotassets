#!/usr/bin/env python3
"""Recognize Harness targets in Ubuntu desktop pixels, without camera input."""

import argparse
import hashlib
import importlib
import json
import logging
import math
import os
import platform
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from safety_harness import ROOT, draw_results, harness_results, make_report, validate_harness

LOG = logging.getLogger('screen-harness')
BUNDLED_MSS = ROOT / 'vendor/mss-9.0.2-py3-none-any.whl'
BUNDLED_MSS_SHA256 = '685fa442cc96d8d88b4eb7aadbcccca7b858e789c9259b603e1ef0e435b60425'


def load_mss():
    """Use an installed MSS or load the verified pure-Python wheel offline."""
    try:
        return importlib.import_module('mss')
    except ModuleNotFoundError as exc:
        if exc.name != 'mss':
            raise
        if not BUNDLED_MSS.is_file():
            raise RuntimeError('缺少MSS。请将最新项目的vendor文件夹一起复制到板子，'
                               '或运行 python3 -m pip install -r requirements-screen.txt') from exc
    if hashlib.sha256(BUNDLED_MSS.read_bytes()).hexdigest() != BUNDLED_MSS_SHA256:
        raise RuntimeError('内置MSS依赖校验失败，请重新复制vendor文件夹。')
    path = str(BUNDLED_MSS.resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    importlib.invalidate_caches()
    module = importlib.import_module('mss')
    LOG.info('已加载项目内置MSS，无需pip安装。')
    return module


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='识别桌面屏幕中的安全带，不使用摄像头（Ubuntu X11/Xorg）')
    parser.add_argument('--model', type=Path, default=ROOT / 'model/safety-harness-rk3588.rknn')
    parser.add_argument('--monitor', type=int, default=1, help='显示器编号，默认1；0=全部显示器')
    parser.add_argument('--region', nargs=4, type=int, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'),
                        help='仅捕获指定屏幕区域，全局像素坐标；覆盖monitor选择')
    parser.add_argument('--list-monitors', action='store_true', help='列出显示器，不加载模型')
    parser.add_argument('--interval', type=float, default=0.2, help='两次捕获的最小间隔秒数，默认0.2')
    parser.add_argument('--conf', type=float, default=0.5)
    parser.add_argument('--iou', type=float, default=0.45)
    parser.add_argument('--core', choices=['auto', '0', '1', '2', 'all'], default='auto')
    parser.add_argument('--once', action='store_true', help='只识别一次屏幕，保存结果后退出')
    parser.add_argument('--max-frames', type=int, default=0, help='处理指定帧数后退出，0=持续运行')
    parser.add_argument('--show', action='store_true', help='显示标注预览；请将预览窗口放在捕获区域外')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/screen')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args(argv)
    if args.monitor < 0 or args.max_frames < 0:
        parser.error('monitor和max-frames必须非负')
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error('interval必须为有限非负数')
    if not 0 <= args.conf <= 1 or not 0 <= args.iou <= 1:
        parser.error('conf和iou必须在0..1之间')
    if args.region and (args.region[2] <= 0 or args.region[3] <= 0):
        parser.error('region的宽高必须为正数')
    return args


def validate_session():
    if platform.system() == 'Linux':
        if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland' or os.environ.get('WAYLAND_DISPLAY'):
            raise RuntimeError('当前为Wayland会话。此屏幕捕获入口需要X11/Xorg；'
                               '请在Ubuntu登录界面选择“Ubuntu on Xorg”后运行。')
        if not os.environ.get('DISPLAY'):
            raise RuntimeError('未找到桌面DISPLAY。请在RK3588 Ubuntu桌面中的终端运行，纯SSH会话无法直接捕获桌面。')


def select_region(monitors, monitor, region):
    if not monitors or len(monitors) < 2:
        raise ValueError('未检测到可捕获的显示器。')
    if region is None:
        if not 0 <= monitor < len(monitors):
            raise ValueError('显示器{}不存在，请用 --list-monitors 查看。'.format(monitor))
        return dict(monitors[monitor])
    left, top, width, height = region
    bounds = monitors[0]
    if (width <= 0 or height <= 0 or left < bounds['left'] or top < bounds['top'] or
            left + width > bounds['left'] + bounds['width'] or
            top + height > bounds['top'] + bounds['height']):
        raise ValueError('捕获区域超出桌面范围：{}。请用 --list-monitors 查看像素范围。'.format(region))
    return {'left': left, 'top': top, 'width': width, 'height': height}


class ScreenSource:
    def __init__(self, monitor=1, region=None):
        self.monitor, self.requested_region = monitor, region
        self.capture = None

    def __enter__(self):
        validate_session()
        mss = load_mss()
        try:
            self.capture = mss.mss()
            self.monitors = self.capture.monitors
            self.region = select_region(self.monitors, self.monitor, self.requested_region)
            return self
        except BaseException:
            if self.capture is not None:
                self.capture.close()
            raise

    def grab(self):
        import cv2
        import numpy as np
        screenshot = np.asarray(self.capture.grab(self.region))
        if screenshot.ndim != 3 or screenshot.shape[2] != 4:
            raise RuntimeError('屏幕捕获未返回BGRA图像。')
        return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

    def __exit__(self, *_exc):
        self.capture.close()


def screen_report(engine, detections, region, frame_index):
    report = make_report(engine, detections, 'desktop-screen', frame_index)
    report.update({'source_type': 'screen', 'capture_region': dict(region),
                   'harness_detected': bool(detections),
                   'image_size': {'width': region['width'], 'height': region['height']},
                   'coordinate_system': 'box=截图内xyxy像素；screen_box=桌面全局xyxy像素'})
    for item in report['detections']:
        x1, y1, x2, y2 = item['box']
        item['screen_box'] = [x1 + region['left'], y1 + region['top'],
                              x2 + region['left'], y2 + region['top']]
    return report


def save_result(frame, report, output):
    import cv2
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / ('screen_{}_harness.jpg'.format(datetime.now().strftime('%Y%m%d_%H%M%S_%f')))
    ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError('屏幕结果图片编码失败')
    path.write_bytes(jpeg.tobytes())
    path.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    LOG.info('已保存标注屏幕及结果JSON：%s', path)
    return path


def run(args, stop_event=None):
    import cv2
    stop_event = stop_event if stop_event is not None else threading.Event()
    engine = None
    last_frame = last_report = None
    try:
        with ScreenSource(args.monitor, args.region) as screen:
            if args.list_monitors:
                for index, item in enumerate(screen.monitors):
                    print('{}: {} left={}, top={}, width={}, height={}'.format(
                        index, '全部显示器' if index == 0 else '显示器',
                        item['left'], item['top'], item['width'], item['height']))
                return None
            if args.model.suffix.lower() != '.rknn' and not args.model.is_dir():
                raise ValueError('屏幕识别入口需要.rknn模型。')
            from detector import Detector
            engine = Detector(args.model, core=args.core, conf=args.conf, iou=args.iou)
            validate_harness(engine.labels, 0)
            engine.set_classes([0])
            LOG.info('屏幕捕获区域：%s，安全带类别ID=0；Ctrl+C停止并保存最后一帧。', screen.region)
            if args.show:
                LOG.info('预览窗口中按q/Esc停止，按s保存当前结果；请将预览窗口放到捕获区域外。')
            count, fps, last_log = 0, 0.0, float('-inf')
            while not stop_event.is_set():
                started = time.perf_counter()
                frame = screen.grab()
                detections = harness_results(engine.predict(frame), 0)
                count += 1
                report = screen_report(engine, detections, screen.region, count)
                draw_results(frame, detections, engine.last_timing['total_ms'], fps)
                last_frame, last_report = frame, report
                if time.monotonic() - last_log >= 1 or args.once:
                    LOG.info('屏幕帧=%d 安全带目标=%d AI=%.1fms 循环=%.1fFPS',
                             count, len(detections), engine.last_timing['total_ms'], fps)
                    for item in report['detections']:
                        LOG.info('Harness 置信度=%.4f 桌面坐标=%s', item['confidence'], item['screen_box'])
                    last_log = time.monotonic()
                if args.show:
                    cv2.imshow('Desktop Screen - Harness', frame)
                    key = cv2.waitKey(1) & 0xff
                    if key in (ord('q'), 27):
                        break
                    if key == ord('s'):
                        save_result(frame, report, args.output)
                if args.once or (args.max_frames and count >= args.max_frames):
                    break
                stop_event.wait(max(0.0, args.interval - (time.perf_counter() - started)))
                fps = 1.0 / max(time.perf_counter() - started, 1e-9)
    finally:
        # NPU work is synchronous: close only after the active call returns.
        try:
            if engine is not None:
                engine.close()
        finally:
            if args.show:
                cv2.destroyAllWindows()
    # Errors propagate rather than saving an older frame as the failed result.
    if last_frame is not None:
        save_result(last_frame, last_report, args.output)
    return last_report


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    stop_event = threading.Event()
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_unused: stop_event.set())
        run(args, stop_event)
        return 0
    except Exception as exc:
        LOG.error('%s', exc, exc_info=args.debug)
        return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    sys.exit(main())
