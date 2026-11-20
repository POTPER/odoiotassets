"""RK3588 YOLO26 钢筋检测示例。"""

import argparse
import json
import logging
import re
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK = "Rebar detection"
CLASSES = {"rebar"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
COLORS = ((0, 200, 255), (255, 180, 0), (0, 220, 0),
          (220, 60, 220), (70, 100, 255), (255, 220, 20))
LOG = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="RK3588 YOLO26 钢筋计数")
    parser.add_argument("--model", type=Path, default=ROOT / "model",
                        help=".rknn、.onnx 或只含一个 RKNN 的目录")
    parser.add_argument("--source", default="41", help="摄像头编号、/dev/videoN、图片或视频")
    parser.add_argument("--conf", type=float, default=0.5, help="最低检测置信度")
    parser.add_argument("--iou", type=float, default=0.45, help="原始输出的同类 NMS 阈值")
    parser.add_argument("--max-det", type=int, default=300, help="每帧最多保留的目标数")
    parser.add_argument("--detail", action="store_true", help="增加重叠分块推理，补查密集小钢筋")
    parser.add_argument("--imgsz", type=int, default=640, help="缺少输入尺寸元数据时使用的边长")
    parser.add_argument("--core", choices=["auto", "0", "1", "2", "all"], default="auto")
    parser.add_argument("--output", type=Path, default=ROOT / "output", help="单图标注 JPEG 和 JSON 目录")
    parser.add_argument("--show", action="store_true", help="打开本地预览，按 Q 或 Esc 退出")
    parser.add_argument("--host", default="127.0.0.1", help="视频画面 UDP 接收端")
    parser.add_argument("--no-udp", action="store_true", help="关闭视频画面和状态的 UDP 回传")
    parser.add_argument("--max-frames", type=int, default=0, help="视频处理帧数上限，0 表示不限")
    args = parser.parse_args(argv)
    if not 0 <= args.conf <= 1 or not 0 <= args.iou <= 1:
        parser.error("--conf 和 --iou 必须在 0 到 1 之间")
    if args.max_det <= 0 or args.imgsz <= 0 or args.max_frames < 0:
        parser.error("--max-det、--imgsz 必须为正数，--max-frames 必须为非负数")
    return args


def annotate(frame, detector, *, show_detection_text=True):
    import cv2

    detections = detector.predict(frame)
    counts = dict.fromkeys(detector.labels, 0)
    rows = []
    for item in detections:
        x1, y1, x2, y2 = item.box
        name = detector.labels[item.class_id]
        counts[name] += 1
        rows.append({"class_id": item.class_id, "label": name,
                     "confidence": item.confidence, "box": list(item.box)})
        color = COLORS[item.class_id]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        if show_detection_text:
            cv2.putText(frame, f"{name} {item.confidence:.2f}", (x1, max(15, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
    summary = f"{TASK} | Count: {len(rows)} | AI: {detector.last_timing['total_ms']:.1f} ms"
    for color, thickness in (((0, 0, 0), 3), ((255, 255, 255), 1)):
        cv2.putText(frame, summary, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    color, thickness, cv2.LINE_AA)
    return counts, rows


def encode_jpeg(frame):
    import cv2

    ok, data = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("标注画面 JPEG 编码失败")
    return data.tobytes()


def run_image(source, args, detector):
    import cv2
    import numpy as np

    data = np.fromfile(source, dtype=np.uint8)
    if not data.size:
        raise ValueError(f"图片为空：{source}")
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"无法解码图片：{source}")
    counts, rows = annotate(frame, detector)
    report = {"source": str(source), "model": str(detector.model_path), "backend": detector.backend,
              "counts": counts, "detections": rows, "output_format": detector.last_output_format,
              "output_shapes": detector.last_output_shapes, "timing": detector.last_timing}
    args.output.mkdir(parents=True, exist_ok=True)
    image_path = args.output / f"{source.stem}_yolo26.jpg"
    report_path = image_path.with_suffix(".json")
    image_path.write_bytes(encode_jpeg(frame))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("数量 %s，结果已保存至 %s 和 %s", counts, image_path, report_path)
    if args.show:
        cv2.imshow(TASK, frame)
        cv2.waitKey(0)


def run_video(args, detector, resources):
    import cv2
    from io_helpers import UdpSender

    device = re.fullmatch(r"(?:/dev/video)?([0-9]+)", args.source)
    source = int(device[1]) if device else args.source
    capture = cv2.VideoCapture(source)
    resources.callback(capture.release)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开输入 {args.source}，请检查摄像头编号、权限或视频路径")
    sender = None if args.no_udp else resources.enter_context(UdpSender(args.host))
    frames = 0
    while not args.max_frames or frames < args.max_frames:
        ok, frame = capture.read()
        if not ok or frame is None or not frame.size:
            if not frames or device:
                raise RuntimeError(f"无法从 {args.source} 读取画面")
            break
        counts, rows = annotate(frame, detector, show_detection_text=device is None)
        frames += 1
        if frames == 1 or frames % 30 == 0:
            LOG.info("第 %d 帧 · %s", frames, counts)
        if sender is not None:
            sender.send_image(encode_jpeg(frame))
            sender.send_status(bool(rows))
        if args.show:
            cv2.imshow(TASK, frame)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), ord("Q"), 27):
                break
    LOG.info("共处理 %d 帧", frames)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        import cv2
        from detector import Detector, _resolve_model
    except ImportError as exc:
        LOG.error("请先准备 OpenCV 和 NumPy。%s", exc)
        return 1
    try:
        with ExitStack() as resources:
            model = args.model
            if model.resolve() == ROOT / "model":
                try:
                    model = _resolve_model(model)
                except ValueError as exc:
                    raise ValueError(f"{exc} 请把 RKNN 和导出配置放入 {args.model}，或用 --model 指定文件") from exc
            detector = Detector(model, imgsz=args.imgsz, core=args.core, conf=args.conf,
                                iou=args.iou, max_det=args.max_det, detail=args.detail)
            resources.callback(detector.close)
            if len(detector.labels) != len(CLASSES) or set(detector.labels) != CLASSES:
                raise ValueError(f"该示例需要类别 {sorted(CLASSES)}，模型实际类别为 {detector.labels}")
            LOG.info("类别 ID 映射 %s，输入尺寸 %s，最低置信度 %.2f",
                     dict(enumerate(detector.labels)), detector.input_size, args.conf)
            if args.detail:
                LOG.info("精细模式已开启：整帧与重叠分块推理，合并后计数")
            if args.show:
                cv2.namedWindow(TASK, cv2.WINDOW_NORMAL)
                resources.callback(cv2.destroyWindow, TASK)
            source = Path(args.source).expanduser()
            if source.suffix.lower() in IMAGE_SUFFIXES:
                run_image(source, args, detector)
            else:
                run_video(args, detector, resources)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, cv2.error) as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
