"""Run Rockchip YOLO26 one2one detection through RKNNLite on RK3588."""

import argparse
import json
import re
import sys
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np


APP_DIR = Path(__file__).resolve().parent
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_metadata(model_path, expected_labels):
    if model_path.suffix.lower() != ".rknn" or not model_path.is_file() or not model_path.stat().st_size:
        raise ValueError(f"需要有效的 .rknn 模型文件：{model_path}")
    path = model_path.with_suffix(".json")
    if not path.is_file():
        raise ValueError(f"缺少模型类别与输入配置：{path}。请从转换环境一并复制同名 JSON。")
    metadata = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict):
        raise ValueError("模型 JSON 必须是对象。")
    if (metadata.get("output_format") != "rockchip_yolo26"
            or metadata.get("box_format") != "xyxy"
            or metadata.get("normalized_boxes", False)):
        raise ValueError("请用仓库的 prepare_model.py 生成 YOLO26 one2one 双输出 RKNN 模型。")
    labels = metadata.get("labels")
    if (not isinstance(labels, list) or not all(isinstance(name, str) for name in labels)
            or len(labels) != len(expected_labels)
            or metadata.get("num_classes") != len(labels)
            or {name.strip().casefold() for name in labels}
            != {name.casefold() for name in expected_labels}):
        raise ValueError(f"此入口需要类别 {', '.join(expected_labels)}，模型类别为 {labels!r}。")
    size = metadata.get("input_size")
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
        raise ValueError("模型 JSON 的 input_size 必须为 [高, 宽]。")
    indices = (metadata.get("boxes_output"), metadata.get("scores_output"))
    if any(type(index) is not int for index in indices) or set(indices) != {0, 1}:
        raise ValueError("模型 JSON 的 boxes_output 与 scores_output 必须分别为 0、1。")
    color = metadata.get("letterbox_color", 114)
    if type(color) is not int or not 0 <= color <= 255:
        raise ValueError("模型 JSON 的 letterbox_color 必须为 0 到 255 的整数。")
    return metadata


def preprocess(frame, input_size, color):
    height, width = frame.shape[:2]
    input_h, input_w = input_size
    ratio = min(input_w / width, input_h / height)
    resized_w = max(1, round(width * ratio))
    resized_h = max(1, round(height * ratio))
    left = (input_w - resized_w) // 2
    top = (input_h - resized_h) // 2
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((input_h, input_w, 3), color, dtype=np.uint8)
    canvas[top:top + resized_h, left:left + resized_w] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    # RKNN conversion embeds the /255 normalization.
    shift = np.array([left, top] * 2, dtype=np.float32)
    scale = np.array([width / resized_w, height / resized_h] * 2, dtype=np.float32)
    return rgb[None], shift, scale


def output_rows(value, channels, name):
    value = np.asarray(value)
    if value.ndim == 3 and value.shape[0] == 1:
        value = value[0]
    if value.ndim != 2 or value.shape[0] != channels or value.shape[1] == 0:
        raise ValueError(f"{name} 输出形状为 {value.shape}，预期 (1, {channels}, N)。")
    if not np.issubdtype(value.dtype, np.floating):
        raise ValueError(f"{name} 输出应为 RKNNLite 反量化后的浮点数，实际为 {value.dtype}。")
    return value.T.astype(np.float32, copy=False)


def predict(runtime, metadata, frame, confidence):
    image, shift, scale = preprocess(frame, metadata["input_size"], metadata.get("letterbox_color", 114))
    outputs = runtime.inference(inputs=[image], data_format=["nhwc"])
    if not isinstance(outputs, (list, tuple)) or len(outputs) != 2:
        raise RuntimeError("RKNN 推理需要返回 YOLO26 的 boxes 和 scores 两个输出。")
    boxes = output_rows(outputs[metadata["boxes_output"]], 4, "boxes")
    scores = output_rows(outputs[metadata["scores_output"]], metadata["num_classes"], "scores")
    if len(boxes) != len(scores):
        raise ValueError("YOLO26 boxes 和 scores 的候选框数量不同。")
    if not np.isfinite(scores).all() or scores.min() < -0.01 or scores.max() > 1.01:
        raise ValueError("YOLO26 scores 应为 sigmoid 概率。")
    class_ids = scores.argmax(axis=1)
    probabilities = scores[np.arange(len(scores)), class_ids]
    valid = np.flatnonzero((probabilities >= confidence) & np.isfinite(boxes).all(axis=1))
    order = valid[np.argsort(-probabilities[valid], kind="stable")]
    height, width = frame.shape[:2]
    mapped = (boxes[order] - shift) * scale
    mapped = np.rint(mapped.clip(0, [width - 1, height - 1] * 2)).astype(np.int32)
    visible = (mapped[:, 2] > mapped[:, 0]) & (mapped[:, 3] > mapped[:, 1])
    # The one2one head uses confidence filtering and TopK.
    order = order[visible][:300]
    return zip(mapped[visible][:300], probabilities[order], class_ids[order])


def annotate(frame, detections, labels, fall_id):
    fall_count = 0
    for (left, top, right, bottom), score, class_id in detections:
        is_fall = class_id == fall_id
        fall_count += int(is_fall)
        color = (0, 0, 255) if is_fall else (0, 180, 0)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, f"{labels[class_id]} {score:.2f}", (left, max(16, top - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    status = f"FALL DETECTED ({fall_count})" if fall_count else "NO FALL DETECTED"
    color = (0, 0, 255) if fall_count else (0, 180, 0)
    cv2.putText(frame, status, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    return status


def run_source(args, process, stack):
    source = Path(args.source)
    if source.suffix.lower() in IMAGE_SUFFIXES:
        frame = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"无法解码图片：{source}")
        print(process(frame), flush=True)
        if args.output is not None:
            ok, encoded = cv2.imencode(args.output.suffix.lower(), frame)
            if not ok:
                raise RuntimeError(f"无法编码标注图片：{args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(encoded.tobytes())
            print(f"已保存：{args.output}")
        if not args.no_show:
            cv2.imshow("YOLO26 Fall Detection", frame)
            cv2.waitKey(0)
        return

    device = re.fullmatch(r"(?:/dev/video)?([0-9]+)", args.source)
    capture = cv2.VideoCapture(int(device[1]) if device else args.source)
    stack.callback(capture.release)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开摄像头或视频：{args.source}")
    frames = 0
    previous = None
    while args.max_frames is None or frames < args.max_frames:
        ok, frame = capture.read()
        if not ok:
            if frames == 0 or device:
                raise RuntimeError(f"无法读取画面：{args.source}")
            break
        frames += 1
        status = process(frame)
        if status != previous:
            print(f"帧 {frames}  {status}", flush=True)
            previous = status
        if not args.no_show:
            cv2.imshow("YOLO26 Fall Detection", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                break


def run_demo(model_name, expected_labels, fall_label, argv=None):
    parser = argparse.ArgumentParser(description=f"RK3588 YOLO26 人员跌倒检测（{len(expected_labels)} 类）")
    parser.add_argument("--model", type=Path, default=APP_DIR / "model" / f"{model_name}.rknn",
                        help="RK3588 .rknn 文件，同目录需有同名 JSON")
    parser.add_argument("--source", default="41", help="摄像头编号、/dev/videoN、图片或视频（默认 41）")
    parser.add_argument("--conf", type=float, default=0.5, help="置信度阈值（默认 0.5）")
    parser.add_argument("--no-show", action="store_true", help="关闭预览窗口")
    parser.add_argument("--max-frames", type=int, help="摄像头或视频的最大处理帧数")
    parser.add_argument("--output", type=Path, help="保存单张图片的标注结果，例如 result.jpg")
    args = parser.parse_args(argv)
    if not 0 < args.conf <= 1:
        parser.error("--conf 必须大于 0 且不超过 1。")
    if args.max_frames is not None and args.max_frames <= 0:
        parser.error("--max-frames 必须为正整数。")
    if args.output is not None:
        source = Path(args.source)
        if source.suffix.lower() not in IMAGE_SUFFIXES or args.output.suffix.lower() not in IMAGE_SUFFIXES:
            parser.error("--output 需要图片输入与图片输出路径。")
        if source.resolve() == args.output.resolve():
            parser.error("--output 不能覆盖输入图片。")

    try:
        metadata = load_metadata(args.model, expected_labels)
        labels = [name.strip() for name in metadata["labels"]]
        fall_id = [name.casefold() for name in labels].index(fall_label)
        from rknnlite.api import RKNNLite

        with ExitStack() as stack:
            runtime = RKNNLite()
            stack.callback(runtime.release)
            code = runtime.load_rknn(str(args.model))
            if code != 0:
                raise RuntimeError(f"加载 RKNN 模型失败，返回码 {code}。")
            code = runtime.init_runtime(core_mask=RKNNLite.NPU_CORE_AUTO)
            if code != 0:
                raise RuntimeError(f"NPU 初始化失败，返回码 {code}，请检查 RKNN Runtime 和 NPU 驱动。")
            if not args.no_show:
                cv2.namedWindow("YOLO26 Fall Detection", cv2.WINDOW_NORMAL)
                stack.callback(cv2.destroyAllWindows)
            print(f"类别 {dict(enumerate(labels))}，跌倒 ID {fall_id}，阈值 {args.conf}", flush=True)

            def process(frame):
                detections = predict(runtime, metadata, frame, args.conf)
                return annotate(frame, detections, labels, fall_id)

            run_source(args, process, stack)
        return 0
    except KeyboardInterrupt:
        return 130
    except ImportError as exc:
        print(f"无法加载 RKNNLite，请安装与板端 Python 和 RKNN Runtime 匹配的官方包。{exc}", file=sys.stderr)
    except (ValueError, RuntimeError, OSError, cv2.error) as exc:
        print(f"错误：{exc}", file=sys.stderr)
    return 1
