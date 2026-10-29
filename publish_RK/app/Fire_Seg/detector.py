"""YOLO26 detection through RKNNLite or ONNX Runtime, without YOLOv5 helpers."""

import ast
import hashlib
import json
import logging
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np


LOG = logging.getLogger(__name__)
FORMATS = {"auto": "auto", "raw": "ultralytics_raw", "ultralytics": "ultralytics_raw",
           "ultralytics_raw": "ultralytics_raw", "end2end": "end2end",
           "ultralytics_end2end": "end2end", "rockchip_yolo26": "rockchip_yolo26"}


@dataclass(frozen=True)
class Detection:
    box: Tuple[int, int, int, int]
    confidence: float
    class_id: int


@dataclass(frozen=True)
class Letterbox:
    original_size: Tuple[int, int]
    resized_size: Tuple[int, int]
    padding: Tuple[int, int]


def _parsed(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value


def normalize_labels(value):
    value = _parsed(value)
    if isinstance(value, dict):
        try:
            indexed = {int(key): name for key, name in value.items()}
        except (ValueError, TypeError) as exc:
            raise ValueError("类别字典必须以从 0 开始的整数为键。") from exc
        if sorted(indexed) != list(range(len(indexed))):
            raise ValueError("类别编号必须从 0 开始且连续。")
        value = [indexed[index] for index in range(len(indexed))]
    if (not isinstance(value, (list, tuple)) or not value or
            any(not isinstance(name, str) or not name.strip() for name in value)):
        raise ValueError("类别名必须是非空字符串列表；请提供模型 metadata 或 --labels。")
    return [name.strip() for name in value]


def resolve_labels(metadata, labels=None, model_path=None):
    """Keep model class IDs; never infer fire/smoke order from a filename."""
    metadata = metadata or {}
    if not isinstance(metadata, dict):
        raise ValueError('模型类别配置必须是字典。')
    names = labels
    if names is None:
        names = metadata.get('labels')
    if names is None:
        names = metadata.get('names')
    if names is None:
        directory = Path(model_path).parent if model_path is not None else Path('model')
        location = Path(model_path) if model_path is not None else directory
        raise ValueError('模型 {} 未找到类别名称。请复制导出时的 metadata.yaml 到目录 {}，'
                         '或创建按真实类别ID顺序排列的 labels.txt（每行一个名称），'
                         '也可用 --labels 按顺序指定；不能从模型文件名判断火焰类别。'.format(location, directory))
    return normalize_labels(names)


def _input_size(value):
    value = _parsed(value)
    if isinstance(value, int) and not isinstance(value, bool):
        value = (value, value)
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(size) is not int or size <= 0 for size in value)):
        raise ValueError("模型输入尺寸必须是正整数 [height, width]。")
    return tuple(value)


def _detect_task(metadata):
    args = _parsed(metadata.get("args", {}))
    if args is not None and not isinstance(args, dict):
        raise ValueError("模型 metadata.args 必须是字典。")
    if "args" in metadata:
        metadata["args"] = args or {}
    for task in (metadata.get("task"), (args or {}).get("task")):
        if task is not None and str(task).lower() != "detect":
            raise ValueError("仅支持 YOLO26 目标检测，不支持 {} 分割/姿态等任务。".format(task))


def read_metadata(model_path):
    """Read directory metadata, then model-specific metadata; preserve class IDs."""
    model_path = Path(model_path)
    directory = model_path if model_path.is_dir() else model_path.parent
    metadata = {}
    paths = [directory / 'metadata.yml', directory / 'metadata.yaml', directory / 'metadata.json']
    if not model_path.is_dir():
        paths.extend(model_path.with_suffix(suffix) for suffix in ('.yml', '.yaml', '.json'))
    for path in dict.fromkeys(paths):
        if not path.is_file():
            continue
        with path.open(encoding='utf-8-sig') as stream:
            if path.suffix.lower() == '.json':
                value = json.load(stream)
            else:
                try:
                    import yaml
                except ImportError as exc:
                    raise RuntimeError('读取 {} 需要 PyYAML，请先安装 PyYAML。'.format(path)) from exc
                value = yaml.safe_load(stream)
        if not isinstance(value, dict):
            raise ValueError('模型说明文件必须包含字典：{}'.format(path))
        _detect_task(value)
        metadata.update(value)
        LOG.debug('已读取模型说明：%s', path)
    if metadata.get('labels') is None and metadata.get('names') is None:
        for filename in ('labels.txt', 'classes.txt'):
            path = directory / filename
            if path.is_file():
                lines = path.read_text(encoding='utf-8-sig').splitlines()
                metadata['labels'] = normalize_labels([line.strip() for line in lines if line.strip()])
                LOG.debug('已读取类别列表：%s', path)
                break
    _detect_task(metadata)
    return metadata


def verify_model_hash(model_path, metadata):
    """Reject a sidecar for a different model; hash only once at startup."""
    expected = metadata.get('source_model_sha256')
    if expected is None:
        return False
    if (not isinstance(expected, str) or len(expected) != 64 or
            any(character not in '0123456789abcdefABCDEF' for character in expected)):
        raise ValueError('source_model_sha256 必须是64位十六进制SHA256。')
    digest = hashlib.sha256()
    with Path(model_path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected.lower():
        raise ValueError('模型SHA256与说明文件不匹配：{}。请一起复制模型及其对应配置。'.format(model_path))
    return True


def preprocess(frame, input_size, color=114):
    if (not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3 or
            frame.dtype != np.uint8 or frame.shape[0] <= 0 or frame.shape[1] <= 0):
        raise ValueError("输入必须是非空的 uint8 三通道 BGR 图像。")
    target_h, target_w = _input_size(input_size)
    if type(color) is not int or not 0 <= color <= 255:
        raise ValueError("letterbox 填充颜色必须是 0..255 的整数。")
    height, width = frame.shape[:2]
    ratio = min(target_w / float(width), target_h / float(height))
    new_w = max(1, min(target_w, int(round(width * ratio))))
    new_h = max(1, min(target_h, int(round(height * ratio))))
    left, top = (target_w - new_w) // 2, (target_h - new_h) // 2
    resized = (frame if (new_h, new_w) == (height, width) else
               cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR))
    if (new_h, new_w) == (target_h, target_w):
        canvas = resized
    else:
        canvas = np.full((target_h, target_w, 3), color, dtype=np.uint8)
        canvas[top:top + new_h, left:left + new_w] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(rgb[None]), Letterbox((height, width), (new_h, new_w), (left, top))


def _format(value):
    try:
        return FORMATS[value]
    except (KeyError, TypeError):
        raise ValueError("未知输出格式 {}，请选择 auto/ultralytics_raw/end2end/rockchip_yolo26。".format(value))


def _arrays(outputs):
    if not isinstance(outputs, (list, tuple)) or not outputs:
        raise ValueError("模型没有返回有效输出。")
    arrays = [np.asarray(value) for value in outputs]
    for value in arrays:
        if not np.issubdtype(value.dtype, np.floating):
            raise ValueError("模型输出必须为已反量化的浮点数，当前为 {}。".format(value.dtype))
        if not np.isfinite(value).all():
            raise ValueError("模型输出包含 NaN 或无穷值。")
    return arrays


def _output_format(arrays, num_classes, requested):
    requested = _format(requested)
    if requested != "auto":
        return requested
    if len(arrays) == 2:
        return "rockchip_yolo26"
    if len(arrays) != 1:
        raise ValueError("不支持 {} 个输出；旧 YOLOv5 三尺度模型或分割模型不能用于此后端。".format(len(arrays)))
    shape = arrays[0].shape
    if len(shape) != 3 or shape[0] != 1:
        raise ValueError("单输出必须为 (1,4+C,N) 或 (1,N,6)，实际为 {}。".format(shape))
    raw = shape[1] == 4 + num_classes and shape[2] > 0
    end2end = shape[2] == 6
    if raw and end2end:
        raise ValueError("输出形状 {} 有歧义（包括 6x6 情况）；请显式指定 --output-format。".format(shape))
    if raw:
        return "ultralytics_raw"
    if end2end:
        return "end2end"
    raise ValueError("输出 {} 与 {} 个类别不匹配；不支持分割掩码或旧检测头。".format(shape, num_classes))


def _cf(value, channels, label):
    if value.ndim != 3 or value.shape[0] != 1 or value.shape[1] != channels or value.shape[2] <= 0:
        raise ValueError("{} 应为 (1,{},N)，实际为 {}；请核对类别数与输出索引。".format(label, channels, value.shape))
    return value[0].T.astype(np.float32, copy=False)


def _probabilities(scores):
    if scores.size and (scores.min() < -0.001 or scores.max() > 1.001):
        raise ValueError("置信度不在 [0,1]，请确认是 sigmoid 概率而非未解码检测头。")


def _class_nms(boxes, scores, class_ids, threshold, max_det):
    order = np.argsort(-scores, kind="stable")
    keep = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size and len(keep) < max_det:
        index, rest = int(order[0]), order[1:]
        keep.append(index)
        if not rest.size:
            break
        upper = np.maximum(boxes[index, :2], boxes[rest, :2])
        lower = np.minimum(boxes[index, 2:], boxes[rest, 2:])
        size = np.maximum(lower - upper, 0)
        overlap = size[:, 0] * size[:, 1]
        union = areas[index] + areas[rest] - overlap
        ious = np.divide(overlap, union, out=np.zeros_like(overlap), where=union > 0)
        order = rest[~((class_ids[rest] == class_ids[index]) & (ious > threshold))]
    return np.asarray(keep, dtype=np.int64)


def postprocess(outputs, transform, num_classes, confidence=0.5, iou=0.45, max_det=100,
                output_format="auto", normalized_boxes=False, input_size=(640, 640),
                boxes_output=None, scores_output=None, keep_classes=None):
    if type(num_classes) is not int or num_classes <= 0:
        raise ValueError("num_classes 必须为正整数。")
    arrays = _arrays(outputs)
    kind = _output_format(arrays, num_classes, output_format)
    return _postprocess_arrays(arrays, transform, num_classes, confidence, iou, max_det,
                               kind, normalized_boxes, input_size, boxes_output, scores_output, keep_classes)


def _postprocess_arrays(arrays, transform, num_classes, confidence, iou, max_det,
                        kind, normalized_boxes, input_size, boxes_output, scores_output, keep_classes=None):
    if type(num_classes) is not int or num_classes <= 0:
        raise ValueError("num_classes 必须为正整数。")
    if not 0 <= confidence <= 1 or not 0 <= iou <= 1 or type(max_det) is not int or max_det <= 0:
        raise ValueError("置信度/IoU 必须在 0..1，max_det 必须为正整数。")
    if kind == "rockchip_yolo26":
        if len(arrays) != 2:
            raise ValueError("rockchip_yolo26 需要且仅需要 scores 与 xyxy boxes 两个输出。")
        if boxes_output is None and scores_output is None:
            if num_classes == 4:
                raise ValueError("4 类模型的 boxes/scores 形状相同，必须明确指定两个输出索引。")
            boxes = [i for i, value in enumerate(arrays) if value.ndim == 3 and value.shape[1] == 4]
            scores = [i for i, value in enumerate(arrays) if value.ndim == 3 and value.shape[1] == num_classes]
            if len(boxes) != 1 or len(scores) != 1 or boxes[0] == scores[0]:
                raise ValueError("无法确定 boxes/scores 分支；请检查模型类别数或指定输出索引。")
            boxes_output, scores_output = boxes[0], scores[0]
        if (type(boxes_output) is not int or type(scores_output) is not int or
                {boxes_output, scores_output} != {0, 1}):
            raise ValueError("boxes_output 与 scores_output 必须分别为 0、1。")
        boxes = _cf(arrays[boxes_output], 4, "boxes")
        class_scores = _cf(arrays[scores_output], num_classes, "scores")
        if len(boxes) != len(class_scores):
            raise ValueError("boxes 与 scores 候选点数量不一致。")
        _probabilities(class_scores)
        class_ids = class_scores.argmax(axis=1)
        scores = class_scores[np.arange(len(class_scores)), class_ids]
    elif kind == "ultralytics_raw":
        if len(arrays) != 1:
            raise ValueError("ultralytics_raw 需要单个 (1,4+C,N) 输出。")
        raw = _cf(arrays[0], 4 + num_classes, "raw")
        boxes = raw[:, :4].copy()
        class_scores = raw[:, 4:]
        _probabilities(class_scores)
        class_ids = class_scores.argmax(axis=1)
        scores = class_scores[np.arange(len(class_scores)), class_ids]
        boxes = np.column_stack((boxes[:, :2] - boxes[:, 2:] / 2,
                                 boxes[:, :2] + boxes[:, 2:] / 2))
    else:
        if len(arrays) != 1 or arrays[0].ndim != 3 or arrays[0].shape[0] != 1 or arrays[0].shape[2] != 6:
            raise ValueError("end2end 需要单个 (1,N,6) 的 xyxy,score,class_id 输出。")
        raw = arrays[0][0].astype(np.float32, copy=False)
        boxes, scores = raw[:, :4], raw[:, 4]
        _probabilities(scores)
        # Ignore padding rows below the confidence threshold before checking IDs.
        valid = scores >= confidence
        ids = raw[valid, 5]
        if np.any(ids != np.rint(ids)) or np.any(ids < 0) or np.any(ids >= num_classes):
            raise ValueError("end2end 输出类别编号不是有效的整数，或超过 labels 范围。")
        boxes, scores = boxes[valid], scores[valid]
        class_ids = ids.astype(np.int64)
    boxes = boxes.astype(np.float32, copy=True)
    if normalized_boxes:
        height, width = _input_size(input_size)
        boxes *= np.array([width, height, width, height], dtype=np.float32)
    valid = ((scores >= confidence) & (boxes[:, 2] > boxes[:, 0]) &
             (boxes[:, 3] > boxes[:, 1]))
    if keep_classes is not None:
        valid &= np.isin(class_ids, tuple(keep_classes))
    boxes, scores, class_ids = boxes[valid], scores[valid], class_ids[valid]
    original_h, original_w = _input_size(transform.original_size)
    resized_h, resized_w = _input_size(transform.resized_size)
    pad_x, pad_y = transform.padding
    shift = np.array([pad_x, pad_y, pad_x, pad_y], dtype=np.float32)
    scale = np.array([original_w / resized_w, original_h / resized_h] * 2, dtype=np.float32)
    mapped = (boxes - shift) * scale
    mapped[:, [0, 2]] = mapped[:, [0, 2]].clip(0, original_w - 1)
    mapped[:, [1, 3]] = mapped[:, [1, 3]].clip(0, original_h - 1)
    mapped = np.rint(mapped).astype(np.int64)
    # Padding-only and rounded-zero-area boxes must not consume max_det or
    # suppress a visible detection. Keep model coordinates for IoU semantics.
    visible = (mapped[:, 2] > mapped[:, 0]) & (mapped[:, 3] > mapped[:, 1])
    boxes, scores, class_ids, mapped = boxes[visible], scores[visible], class_ids[visible], mapped[visible]
    order = (_class_nms(boxes, scores, class_ids, iou, max_det) if kind == "ultralytics_raw"
             else np.argsort(-scores, kind="stable")[:max_det])
    result = []
    for index in order:
        integer_box = tuple(int(value) for value in mapped[index])
        result.append(Detection(integer_box, float(scores[index]), int(class_ids[index])))
    return result


def _resolve_model(path):
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        candidates = [item for item in path.rglob("*") if item.is_file() and item.suffix.lower() == ".rknn"]
        if len(candidates) != 1:
            raise ValueError("RKNN 目录必须恰有一个 .rknn 文件，实际找到 {} 个。".format(len(candidates)))
        path = candidates[0]
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("模型文件不存在或为空：{}。".format(path))
    if path.suffix.lower() not in (".rknn", ".onnx"):
        raise ValueError("模型必须为 .rknn/.onnx，或包含单个 .rknn 的目录。")
    return path


class Detector:
    def __init__(self, model_path, labels=None, imgsz=640, output_format="auto",
                 normalized_boxes=None, core="auto", conf=0.5, iou=0.45, max_det=100,
                 boxes_output=None, scores_output=None):
        self.runtime = self.session = None
        self._logged_shapes = False
        self.last_timing = {}
        self.last_output_shapes = []
        self.last_output_format = None
        self.classes = None
        self.model_path = _resolve_model(model_path)
        requested_path = Path(model_path).expanduser().resolve()
        self.metadata = (read_metadata(requested_path)
                         if requested_path.is_dir() and requested_path != self.model_path.parent else {})
        self.metadata.update(read_metadata(self.model_path))
        self.model_hash_verified = verify_model_hash(self.model_path, self.metadata)
        actual_names = None
        self.backend = "onnx" if self.model_path.suffix.lower() == ".onnx" else "rknn"
        try:
            if self.backend == "onnx":
                try:
                    import onnxruntime as ort
                except ImportError as exc:
                    raise RuntimeError("ONNX CPU 推理需要 onnxruntime，请先安装。") from exc
                self.session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
                model_metadata = {key: _parsed(value) for key, value in
                                  self.session.get_modelmeta().custom_metadata_map.items()}
                _detect_task(model_metadata)
                actual_names = model_metadata.get("names", model_metadata.get("labels"))
                self.metadata.update(model_metadata)
                inputs = self.session.get_inputs()
                if len(inputs) != 1:
                    raise ValueError("ONNX 必须只有一个 NCHW 图像输入。")
                spec = inputs[0]
                shape = spec.shape
                if (len(shape) != 4 or any(type(size) is not int or size <= 0 for size in shape) or
                        shape[0] != 1 or shape[1] != 3):
                    raise ValueError("ONNX 仅支持静态 batch=1、三通道 NCHW 输入，实际为 {}。".format(shape))
                types = {"tensor(float)": np.float32, "tensor(float16)": np.float16}
                if spec.type not in types:
                    raise ValueError("ONNX 输入必须为 float32/float16，实际为 {}。".format(spec.type))
                self.input_name, self.input_dtype = spec.name, types[spec.type]
                self.input_size = (shape[2], shape[3])
            else:
                args = self.metadata.get("args", {})
                self.input_size = _input_size(self.metadata.get("input_size",
                                                    self.metadata.get("imgsz", args.get("imgsz", imgsz))))
            _detect_task(self.metadata)
            self.metadata.setdefault("args", {})
            names = labels if labels is not None else actual_names
            self.labels = resolve_labels(self.metadata, names, self.model_path)
            classes = self.metadata.get("num_classes")
            if classes is not None and (type(classes) is not int or classes != len(self.labels)):
                raise ValueError("metadata.num_classes 与最终 labels 数量不一致。")
            requested = _format(output_format)
            self.output_format = _format(self.metadata.get("output_format", "auto")) if requested == "auto" else requested
            args = self.metadata["args"]
            # Ultralytics normalizes this branch specifically for INT8 RKNN
            # export; an ordinary ONNX export still uses pixel coordinates.
            quantized_raw = self.backend == "rknn" and args.get("quantize") == 8
            self.normalized_boxes = (bool(normalized_boxes) if normalized_boxes is not None else
                                     bool(self.metadata.get("normalized_boxes", quantized_raw)))
            self._normalized_raw_only = (normalized_boxes is None and
                                         "normalized_boxes" not in self.metadata and quantized_raw)
            self.boxes_output = boxes_output if boxes_output is not None else self.metadata.get("boxes_output")
            self.scores_output = scores_output if scores_output is not None else self.metadata.get("scores_output")
            self.conf, self.iou, self.max_det = conf, iou, max_det
            if not 0 <= conf <= 1 or not 0 <= iou <= 1 or type(max_det) is not int or max_det <= 0:
                raise ValueError("置信度/IoU 必须在 0..1，max_det 必须为正整数。")
            self.color = self.metadata.get("letterbox_color", 114)
            if type(self.color) is not int or not 0 <= self.color <= 255:
                raise ValueError("letterbox_color 必须是 0..255 整数。")
            self.metadata.update({"labels": list(self.labels), "num_classes": len(self.labels),
                                  "input_size": list(self.input_size)})
            if self.backend == "rknn":
                self._init_rknn(core)
        except BaseException:
            try:
                self.close()
            except Exception:
                LOG.exception("初始化失败后释放推理资源也发生错误")
            raise

    def _init_rknn(self, core):
        if platform.system() != "Linux" or platform.machine().lower() not in ("aarch64", "arm64"):
            raise RuntimeError("RKNNLite 推理需要 Linux ARM64 的 RK3588，请在板子上运行部署入口。")
        try:
            from rknnlite.api import RKNNLite
        except ImportError as exc:
            raise RuntimeError("请安装与板端 Python、ARM64 及 librknnrt 匹配的 rknn-toolkit-lite2。") from exc
        cores = {"auto": "NPU_CORE_AUTO", "0": "NPU_CORE_0", "1": "NPU_CORE_1",
                 "2": "NPU_CORE_2", "all": "NPU_CORE_0_1_2"}
        if str(core) not in cores:
            raise ValueError("core 必须为 auto/0/1/2/all。")
        self.runtime = RKNNLite()
        code = self.runtime.load_rknn(str(self.model_path))
        if code != 0:
            raise RuntimeError("加载 RKNN 失败，返回 {}；请核对模型目标与运行库版本。".format(code))
        code = self.runtime.init_runtime(core_mask=getattr(RKNNLite, cores[str(core)]))
        if code != 0:
            raise RuntimeError("初始化 NPU 失败，返回 {}；请检查驱动与 librknnrt。".format(code))
        LOG.info("RK3588 NPU初始化成功：RKNNLite，核心=%s，模型=%s", core, self.model_path)

    def set_classes(self, class_ids):
        """Filter decoded classes before NMS/TopK without changing model labels."""
        if class_ids is None:
            self.classes = None
            return
        class_ids = tuple(class_ids)
        if (not class_ids or any(type(value) is not int or not 0 <= value < len(self.labels)
                                 for value in class_ids)):
            raise ValueError('识别类别必须是模型范围内的非空整数ID列表。')
        self.classes = class_ids

    def predict(self, frame):
        self.last_timing = {}
        started = time.perf_counter()
        data, transform = preprocess(frame, self.input_size, self.color)
        if self.backend == "onnx":
            if self.session is None:
                raise RuntimeError("Detector 已关闭。")
            tensor = np.ascontiguousarray(data.transpose(0, 3, 1, 2), dtype=self.input_dtype)
            tensor /= self.input_dtype(255.0)
            prepared = time.perf_counter()
            outputs = self.session.run(None, {self.input_name: tensor})
        else:
            if self.runtime is None:
                raise RuntimeError("Detector 已关闭。")
            # RKNNLite returns dequantized float arrays by default. Integer
            # arrays are rejected below; no guessed scale/zero-point is used.
            prepared = time.perf_counter()
            outputs = self.runtime.inference(inputs=[data], data_format=["nhwc"])
        inferred = time.perf_counter()
        arrays = _arrays(outputs)
        self.last_output_shapes = [list(value.shape) for value in arrays]
        if not self._logged_shapes:
            LOG.info("首次推理输出：%s", [(value.shape, str(value.dtype)) for value in arrays])
            self._logged_shapes = True
        kind = _output_format(arrays, len(self.labels), self.output_format)
        normalized = self.normalized_boxes and (not self._normalized_raw_only or kind == "ultralytics_raw")
        result = _postprocess_arrays(arrays, transform, len(self.labels), self.conf, self.iou, self.max_det,
                                     kind, normalized, self.input_size, self.boxes_output, self.scores_output, self.classes)
        finished = time.perf_counter()
        self.last_output_format = kind
        # inference_ms measures the API call, including transfers/conversions;
        # it is not a measurement of pure NPU kernel time.
        self.last_timing = {'preprocess_ms': (prepared - started) * 1000,
                            'inference_ms': (inferred - prepared) * 1000,
                            'postprocess_ms': (finished - inferred) * 1000,
                            'total_ms': (finished - started) * 1000}
        return result

    def close(self):
        self.session = None
        if self.runtime is not None:
            runtime, self.runtime = self.runtime, None
            runtime.release()
