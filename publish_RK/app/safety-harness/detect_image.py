#!/usr/bin/env python3
"""Detect safety harnesses in one local image; never open a camera."""

import argparse
import json
import logging
import sys
from pathlib import Path

from safety_harness import IMAGE_SUFFIXES, ROOT, harness_results, make_report, validate_harness

# 可直接修改这两个路径，然后运行 python3 detect_image.py。
IMAGE_PATH = ROOT / 'test.jpg'
MODEL_PATH = ROOT / 'model/safety-harness-rk3588.rknn'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='单张图片安全带识别，输出标注图片和JSON；不打开摄像头')
    parser.add_argument('--image', type=Path, default=IMAGE_PATH, help='测试图片路径，默认脚本旁的test.jpg')
    parser.add_argument('--model', type=Path, default=MODEL_PATH)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/images', help='结果目录')
    parser.add_argument('--conf', type=float, default=0.5, help='置信度阈值，默认0.5')
    parser.add_argument('--iou', type=float, default=0.45)
    parser.add_argument('--core', choices=['auto', '0', '1', '2', 'all'], default='auto')
    parser.add_argument('--show', action='store_true', help='显示标注图片，按任意键关闭；需要桌面')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.conf <= 1 or not 0 <= args.iou <= 1:
        parser.error('conf 和 iou 必须在0..1之间')
    return args


def run(args):
    image_path = args.image.expanduser().resolve()
    if image_path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('只接受本地图片（jpg/png/bmp/webp/tif等），请用 --image 指定图片文件。')
    if not image_path.is_file():
        raise ValueError('图片不存在：{}。将测试图片放到脚本旁并命名为test.jpg，或使用 --image 指定。'.format(image_path))
    if args.model.suffix.lower() != '.rknn' and not args.model.is_dir():
        raise ValueError('此入口需要 .rknn 模型或包含模型的目录。')

    import cv2
    import numpy as np
    from detector import Detector

    frame = cv2.imdecode(np.frombuffer(image_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('图片解码失败：{}，请检查文件是否损坏。'.format(image_path))

    engine = None
    try:
        engine = Detector(args.model, core=args.core, conf=args.conf, iou=args.iou)
        validate_harness(engine.labels, 0)
        engine.set_classes([0])
        detections = harness_results(engine.predict(frame), 0)
        report = make_report(engine, detections, str(image_path), 1)
        report.update({'harness_detected': bool(detections),
                       'image_size': {'width': frame.shape[1], 'height': frame.shape[0]}})

        for item in detections:
            x1, y1, x2, y2 = item.box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 0), 2)
            cv2.putText(frame, 'Harness {:.2f}'.format(item.confidence), (x1, max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)
        cv2.putText(frame, 'Harness: {} | AI: {:.1f}ms'.format(len(detections), engine.last_timing['total_ms']),
                    (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)
        ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError('标注图片编码失败')
        output_dir = args.output.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        annotated_path = output_dir / (image_path.stem + '_harness.jpg')
        report_path = annotated_path.with_suffix('.json')
        annotated_path.write_bytes(jpeg.tobytes())
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        if engine is not None:
            engine.close()

    print('测试图片：{}'.format(image_path))
    print('安全带检测数量：{}'.format(len(detections)))
    if not detections:
        print('当前阈值下未检测到安全带目标。')
    for index, item in enumerate(detections, 1):
        print('  目标{}：Harness，置信度 {:.4f}，坐标 xyxy={}'.format(index, item.confidence, item.box))
    print('识别耗时：{:.1f} ms（预处理+推理+后处理）'.format(report['timing_ms']['total_ms']))
    print('标注图片：{}'.format(annotated_path))
    print('结果JSON：{}'.format(report_path))
    if args.show:
        try:
            cv2.imshow('Safety Harness - Image Test', frame)
            cv2.waitKey(0)
        finally:
            cv2.destroyAllWindows()
    return report


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(levelname)s %(message)s')
    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger(__name__).error('%s', exc, exc_info=args.debug)
        return 1


if __name__ == '__main__':
    sys.exit(main())
