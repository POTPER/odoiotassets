#!/usr/bin/env python3
"""RK3588 YOLO26 safety-harness detection. Python 3.8+."""

import argparse
import importlib
import json
import logging
import platform
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('safety-harness')
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='RK3588 YOLO26 安全带识别（仅显示和统计 Harness）')
    parser.add_argument('--model', type=Path, default=ROOT / 'model/safety-harness-rk3588.rknn')
    parser.add_argument('--source', default='41', help='摄像头编号、/dev/videoN、图片、视频或 RTSP')
    parser.add_argument('--imgsz', type=int, nargs=2, default=[640, 640], metavar=('H', 'W'),
                        help='无模型说明文件时的输入高宽；必须与模型一致，默认640 640')
    parser.add_argument('--harness-class', type=int, default=0, help='安全带原始类别ID，截图对应0')
    parser.add_argument('--conf', type=float, default=0.5)
    parser.add_argument('--iou', type=float, default=0.45, help='raw 输出的 NMS IoU 阈值')
    parser.add_argument('--max-det', type=int, default=100)
    parser.add_argument('--output-format', choices=['auto', 'ultralytics_raw', 'end2end', 'rockchip_yolo26'], default='auto')
    parser.add_argument('--core', choices=['auto', '0', '1', '2', 'all'], default='auto')
    parser.add_argument('--width', type=int, default=640, help='摄像头采集宽度')
    parser.add_argument('--height', type=int, default=480, help='摄像头采集高度')
    parser.add_argument('--show', action='store_true', help='本地窗口预览，需要图形桌面')
    parser.add_argument('--udp', action='store_true', help='使用现有火焰项目分片协议发送标注 JPEG')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--image-port', type=int, default=8088)
    parser.add_argument('--jpeg-quality', type=int, default=80)
    parser.add_argument('--output', type=Path, default=ROOT / 'output')
    parser.add_argument('--max-frames', type=int, default=0, help='0=持续运行')
    parser.add_argument('--check', action='store_true', help='检查文件、依赖和配置，不执行NPU推理')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.conf <= 1 or not 0 <= args.iou <= 1:
        parser.error('conf 和 iou 必须在0..1之间')
    if min(args.imgsz + [args.width, args.height, args.max_det]) <= 0 or args.max_frames < 0:
        parser.error('输入尺寸、采集尺寸、max-det须为正整数，max-frames须非负')
    if args.harness_class < 0:
        parser.error('harness-class须非负')
    if not 1 <= args.jpeg_quality <= 100 or not 1 <= args.image_port <= 65535:
        parser.error('jpeg-quality须为1..100，端口须为1..65535')
    return args


def validate_harness(labels, class_id):
    if not 0 <= class_id < len(labels):
        raise ValueError('安全带类别ID {} 超出模型类别范围 {}'.format(class_id, labels))
    if labels[class_id].casefold().strip() not in ('harness', 'safety-harness', 'safety_harness', 'safety harness', '安全带'):
        raise ValueError('ID {} 对应 {}，不是 Harness；请核对 labels 和 --harness-class。'.format(class_id, labels[class_id]))


def harness_results(detections, class_id):
    # Keep original IDs; Helmet is never treated as an unworn worker.
    return [item for item in detections if item.class_id == class_id]


def check_environment(args):
    print('系统: {} {} | Python: {}'.format(platform.system(), platform.machine(), platform.python_version()))
    healthy = platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64')
    if not healthy:
        print('[未通过] RKNN 推理需要 RK3588 Linux ARM64。')
    for name in ('numpy', 'cv2', 'rknnlite.api'):
        try:
            module = importlib.import_module(name)
            print('[正常] {} {}'.format(name, getattr(module, '__version__', '')))
        except Exception as exc:
            healthy = False
            print('[未通过] {}: {}'.format(name, exc))
    try:
        from detector import _input_size, _resolve_model, read_metadata, resolve_labels, verify_model_hash
        path = _resolve_model(args.model)
        if path.suffix.lower() != '.rknn':
            raise ValueError('板端入口需要 .rknn 模型。')
        meta = read_metadata(path)
        labels = resolve_labels(meta, model_path=path)
        validate_harness(labels, args.harness_class)
        hash_verified = verify_model_hash(path, meta)
        size = _input_size(meta.get('input_size', meta.get('imgsz', meta.get('args', {}).get('imgsz', args.imgsz))))
        print('[正常] 模型: {} ({}字节)'.format(path, path.stat().st_size))
        print('类别顺序: {} | 仅识别ID {} | 输入高宽: {}'.format(labels, args.harness_class, size))
        print('输出格式: {} | 输出形状: {} | RKNN编译器: {}'.format(
            meta.get('output_format', args.output_format), meta.get('output_shapes', '首帧确认'),
            meta.get('compiler_version', '未知')))
        if hash_verified:
            print('[正常] 模型SHA256与配套配置一致。')
        if not meta.get('input_size') and not meta.get('imgsz') and not meta.get('args', {}).get('imgsz'):
            print('[待确认] 输入尺寸使用 --imgsz 默认/指定值，请与模型导出信息核对。')
    except Exception as exc:
        healthy = False
        print('[未通过] 模型/配置: {}'.format(exc))
    print('检查不加载 NPU；实际兼容性需要执行一张图片验证。')
    return 0 if healthy else 1


def draw_results(frame, detections, total_ms, fps):
    import cv2
    for item in detections:
        x1, y1, x2, y2 = item.box
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 0), 2)
        cv2.putText(frame, 'Harness {:.2f}'.format(item.confidence), (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 35), (30, 30, 30), -1)
    cv2.putText(frame, 'Harness: {} | AI: {:.0f}ms | loop: {:.1f}FPS'.format(len(detections), total_ms, fps),
                (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)


def make_report(detector, detections, source, frame_index):
    return {'model': str(detector.model_path), 'source': source, 'frame_index': frame_index,
            'labels': detector.labels, 'harness_count': len(detections), 'count_unit': 'detection_boxes',
            'timing_ms': detector.last_timing, 'output_shapes': detector.last_output_shapes,
            'output_format': detector.last_output_format,
            'detections': [{'class_id': item.class_id, 'label': detector.labels[item.class_id],
                            'confidence': item.confidence, 'box': list(item.box)} for item in detections]}


def run(args):
    import cv2
    import numpy as np
    from detector import Detector

    detector = cap = sender = None
    handlers = {}
    stopping = [False]

    def stop(_signum, _frame):
        stopping[0] = True

    source_path = Path(args.source)
    is_image = source_path.suffix.lower() in IMAGE_SUFFIXES
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, stop)
        if args.model.suffix.lower() != '.rknn' and not args.model.is_dir():
            raise ValueError('板端入口需要 .rknn 模型。')
        detector = Detector(args.model, imgsz=args.imgsz, output_format=args.output_format,
                            core=args.core, conf=args.conf, iou=args.iou, max_det=args.max_det)
        validate_harness(detector.labels, args.harness_class)
        detector.set_classes([args.harness_class])
        LOG.info('仅识别安全带：ID=%d，完整类别=%s，模型输入=%s',
                 args.harness_class, detector.labels, detector.input_size)
        LOG.info('预处理：RGB uint8 NHWC，等比例补边，/255须已编入RKNN；请与导出配置核对。')
        if args.udp:
            from io_helpers import UdpImageSender
            sender = UdpImageSender(args.host, args.image_port)
        if is_image:
            if not source_path.is_file():
                raise ValueError('图片不存在：{}'.format(source_path))
            image = cv2.imdecode(np.frombuffer(source_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError('无法解码图片：{}'.format(source_path))
        else:
            source = int(args.source) if args.source.isdecimal() else args.source
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                raise RuntimeError('无法打开输入：{}'.format(args.source))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if isinstance(source, int) or args.source.startswith('/dev/video'):
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        index, fps, last_log, last_udp_error = 0, 0.0, 0.0, float('-inf')
        if not args.show and not args.udp and not is_image:
            LOG.info('当前仅输出检测日志；需要画面可加 --show 或 --udp。')
        while not stopping[0]:
            started = time.perf_counter()
            if is_image:
                frame = image.copy()
            else:
                ok, frame = cap.read()
                if not ok or frame is None:
                    if source_path.is_file() and index > 0:
                        LOG.info('视频读取结束，已处理%d帧', index)
                        break
                    raise RuntimeError('输入取帧失败：{}'.format(args.source))
            detections = harness_results(detector.predict(frame), args.harness_class)
            index += 1
            draw_results(frame, detections, detector.last_timing['total_ms'], fps)
            if is_image or sender is not None:
                ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
                if not ok:
                    raise RuntimeError('JPEG 编码失败')
                if sender is not None:
                    try:
                        sender.send(jpeg.tobytes())
                    except OSError as exc:
                        if time.monotonic() - last_udp_error >= 3:
                            LOG.warning('UDP发送失败：%s', exc)
                            last_udp_error = time.monotonic()
                if is_image:
                    args.output.mkdir(parents=True, exist_ok=True)
                    path = args.output / (source_path.stem + '_harness.jpg')
                    path.write_bytes(jpeg.tobytes())
                    path.with_suffix('.json').write_text(json.dumps(make_report(detector, detections, args.source, index),
                                                                    ensure_ascii=False, indent=2), encoding='utf-8')
                    LOG.info('已保存：%s 和同名JSON', path)
            if is_image or time.monotonic() - last_log >= 1:
                LOG.info('帧=%d 安全带目标=%d AI=%.1fms loop=%.1fFPS',
                         index, len(detections), detector.last_timing['total_ms'], fps)
                last_log = time.monotonic()
            if args.show:
                cv2.imshow('RK3588 Safety Harness', frame)
                if cv2.waitKey(1) & 0xff in (ord('q'), 27, ord(' ')):
                    break
            fps = 1.0 / max(time.perf_counter() - started, 1e-9)
            if is_image or (args.max_frames and index >= args.max_frames):
                break
    finally:
        for resource in (cap, sender, detector):
            if resource is not None:
                try:
                    resource.release() if resource is cap else resource.close()
                except Exception:
                    LOG.exception('释放资源失败')
        if args.show:
            cv2.destroyAllWindows()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    try:
        if args.check:
            return check_environment(args)
        run(args)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        LOG.error('%s', exc, exc_info=args.debug)
        return 1


if __name__ == '__main__':
    sys.exit(main())
