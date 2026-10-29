#!/usr/bin/env python3
"""RK3588 deployment checks. Only explicit probes open an NPU or camera.

The default run reads system/model information and writes a JSON report. It
does not install packages, change system settings, send UDP, or move the PTZ.
Real probes run in separate processes with a hard timeout.
"""

import argparse
import ast
import logging
import ctypes.util
import datetime
import glob
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_MODEL = ROOT / "model/fire_yolo26.rknn"
LOG = logging.getLogger(__name__)
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")


def result(check_id, status, message, details=None):
    if status not in STATUSES:
        raise ValueError("Unknown check status: {}".format(status))
    return {"id": check_id, "status": status, "message": message, "details": details or {}}


def resolve_model(path):
    path = Path(path).expanduser().resolve()
    if path == DEFAULT_MODEL.resolve() and not path.exists() and path.parent.is_dir():
        candidates = sorted(path.parent.rglob('*.rknn'))
        if len(candidates) == 1:
            path = candidates[0]
            LOG.info('使用model目录中的唯一模型：%s', path)
    if path.is_dir():
        candidates = sorted(path.rglob('*.rknn'))
        if len(candidates) != 1:
            raise ValueError('导出目录中需要恰好一个RKNN文件，请用 --model 明确指定：{}'.format(path))
        path = candidates[0]
    if path.suffix.lower() != '.rknn':
        raise ValueError('部署入口只接受 .rknn 并使用RK3588 NPU；请先将ONNX或PT转换成RKNN。')
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('模型不存在或为空：{}。请放入真正的YOLO26导出文件；旧Fire_Seg模型无法靠改名升级。'.format(path))
    return path

def infer_fire_class(labels, explicit=None):
    if explicit is not None:
        if explicit < 0 or explicit >= len(labels):
            raise ValueError('--fire-class 超出类别范围，实际标签为 {}'.format(labels))
        return explicit
    aliases = {'fire', 'flame', 'flames', '火', '火焰'}
    matches = [i for i, name in enumerate(labels) if name.strip().casefold() in aliases]
    if len(matches) != 1:
        raise ValueError('无法唯一确定火焰类别：{}。请核对训练标签后用 --fire-class 指定，程序不会默认把第0类当成火。'.format(labels))
    return matches[0]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="RK3588 检查工具：默认只读检查，不启动 NPU 或摄像头；仅写入 JSON 报告。")
    parser.add_argument("--model", type=Path, default=ROOT / "model/fire_yolo26.rknn")
    parser.add_argument("--labels", nargs="+", help="按真实训练类别 ID 顺序填写，不能凭文件名猜测。")
    parser.add_argument("--fire-class", type=int)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--output-format", choices=["auto", "ultralytics_raw", "end2end", "rockchip_yolo26"], default="auto")
    coordinates = parser.add_mutually_exclusive_group()
    coordinates.add_argument("--normalized-boxes", dest="normalized_boxes", action="store_true")
    coordinates.add_argument("--pixel-boxes", dest="normalized_boxes", action="store_false")
    parser.set_defaults(normalized_boxes=None)
    parser.add_argument("--core", choices=["auto", "0", "1", "2", "all"], default="auto")
    parser.add_argument("--npu-test", action="store_true", help="明确请求 NPU 加载、真实图片推理与计时；不回退 CPU。")
    parser.add_argument("--image", type=Path, default=ROOT / "testimg/fire1.jpg")
    parser.add_argument("--warmup", type=int, default=3, help="首次推理之后的额外预热次数，默认 3。")
    parser.add_argument("--runs", type=int, default=10, help="预热后计时次数，默认 10。")
    parser.add_argument("--camera", help="明确请求打开指定编号或 /dev/videoN，并且只读取一帧。")
    parser.add_argument("--list-cameras", action="store_true", help="详细列出设备清单；不会打开摄像头。")
    parser.add_argument("--json", type=Path, default=ROOT / "output/device_check.json", help="结构化报告保存路径。")
    parser.add_argument("--timeout", type=float, default=30, help="每个真实探测子进程的独立超时秒数。")
    parser.add_argument("--_probe", choices=["npu", "camera"], help=argparse.SUPPRESS)
    parser.add_argument("--_request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.imgsz <= 0 or args.imgsz % 32:
        parser.error("--imgsz 必须是 32 的正整数倍")
    if args.warmup < 0 or args.runs <= 0:
        parser.error("--warmup 必须非负，--runs 必须为正整数")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout 必须是有限正数")
    if args.fire_class is not None and args.fire_class < 0:
        parser.error("--fire-class 必须非负")
    if args.camera is not None:
        try:
            camera_source(args.camera)
        except ValueError as exc:
            parser.error(str(exc))
    if args._probe is not None and (args._request is None or args._result is None):
        parser.error("内部探测入口必须指定请求与结果文件")
    return args


def _read_text(path, limit=4096):
    try:
        with Path(path).open("rb") as stream:
            return stream.read(limit).decode("utf-8", errors="replace").strip(), None
    except OSError as exc:
        return None, str(exc)


def check_system():
    checks = [result("python", "PASS" if sys.version_info >= (3, 8) else "FAIL",
                     "Python {}；脚本要求 Python 3.8 或更新版本。".format(platform.python_version()),
                     {"executable": sys.executable, "version": sys.version})]
    linux_arm = platform.system() == "Linux" and platform.machine().lower() in ("aarch64", "arm64")
    checks.append(result("platform", "PASS" if linux_arm else "FAIL",
                         "系统为 {} {}；NPU 部署要求 Linux ARM64。".format(platform.system(), platform.machine()),
                         {"system": platform.system(), "machine": platform.machine(), "release": platform.release()}))
    compatible, errors = [], []
    for path in ("/proc/device-tree/compatible", "/sys/firmware/devicetree/base/compatible"):
        text, error = _read_text(path)
        if text:
            compatible = [item for item in text.split("\x00") if item]
            break
        errors.append({"path": path, "error": error})
    model, _ = _read_text("/proc/device-tree/model")
    rk3588 = any("rk3588" in item.lower() for item in compatible)
    checks.append(result("board_identity", "PASS" if rk3588 else "WARN",
                         "设备树确认 RK3588 系列。" if rk3588 else "未从可读设备树确认 RK3588；不根据 CPU 架构猜测芯片型号。",
                         {"compatible": compatible, "model": model, "read_errors": errors}))
    return checks


def _module_version(module, distributions):
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    for distribution in distributions:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "未知（模块可导入）"


def check_dependencies():
    checks = []
    modules = [("numpy", ["numpy"], True), ("cv2", ["opencv-python", "opencv-python-headless"], True),
               ("PIL", ["Pillow"], True),
               ("yaml", ["PyYAML"], False), ("rknnlite.api", ["rknn-toolkit-lite2"], True)]
    for name, distributions, required in modules:
        try:
            module = importlib.import_module(name)
            checks.append(result("dependency." + name, "PASS", "{} 可导入。".format(name),
                                 {"version": _module_version(module, distributions), "module_path": getattr(module, "__file__", None)}))
        except Exception as exc:
            checks.append(result("dependency." + name, "FAIL" if required else "WARN",
                                 "{} 无法导入：{}{}".format(name, exc, "；仅 YAML 元数据需要 PyYAML。" if not required else ""),
                                 {"exception_type": type(exc).__name__}))
    checks.append(result("board_dependency_scope", "PASS",
                         "此 RKNN 板端入口不需要 Ultralytics、PyTorch 或 ONNX Runtime；导出环境与板端运行环境分开。",
                         {"not_required_on_board": ["ultralytics", "torch", "onnxruntime"],
                          "note": "默认检查只导入依赖，没有创建 Detector 或初始化 NPU。"}))
    return checks


def stream_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_model(args):
    checks = []
    try:
        model = resolve_model(args.model)
        checks.append(result("model_file", "PASS", "RKNN 文件存在且非空。",
                             {"path": str(model), "bytes": model.stat().st_size,
                              "note": "文件后缀和库名称不能证明模型架构或识别能力。"}))
    except Exception as exc:
        return [result("model_file", "FAIL", str(exc)),
                result("model_metadata", "SKIP", "模型文件检查失败，未验证类别配置。"),
                result("model_hash", "SKIP", "模型文件检查失败，未计算绑定哈希。")]
    try:
        import detector
        original = Path(args.model).expanduser()
        metadata = detector.read_metadata(original) if original.is_dir() and original.resolve() != model.parent else {}
        metadata.update(detector.read_metadata(model))
        labels = detector.resolve_labels(metadata, args.labels, model)
        fire_class = infer_fire_class(labels, args.fire_class)
        classes = metadata.get("num_classes")
        if classes is not None and (type(classes) is not int or classes != len(labels)):
            raise ValueError("num_classes 与最终类别名称数量不一致。")
        export_args = metadata.get("args") or {}
        size = detector._input_size(metadata.get("input_size", metadata.get("imgsz", export_args.get("imgsz", args.imgsz))))
        configured_format = detector._format(args.output_format if args.output_format != "auto" else metadata.get("output_format", "auto"))
        target = metadata.get("target_platform")
        if target is not None:
            targets = [target] if isinstance(target, str) else target
            if (not isinstance(targets, (list, tuple)) or not targets or
                    any(not isinstance(item, str) for item in targets) or
                    "rk3588" not in [item.lower() for item in targets]):
                raise ValueError("模型 target_platform={} 与当前 RK3588 部署目标不匹配。".format(target))
        checks.append(result("model_metadata", "PASS", "类别顺序与火焰类别配置有效；真实输出结构仍须实际推理验证。",
                             {"labels": labels, "num_classes": len(labels), "fire_class": fire_class,
                              "input_size": list(size), "output_format": configured_format,
                              "normalized_boxes_override": args.normalized_boxes,
                              "metadata_output_shapes": metadata.get("output_shapes"),
                              "metadata_precision": metadata.get("precision"), "core": args.core}))
        checks.append(result("model_input_size", "PASS" if list(size) == [640, 640] else "WARN",
                             "模型配置输入为 {}；当前默认部署尺寸为 640×640。".format(list(size)),
                             {"input_size": list(size), "fallback_imgsz": args.imgsz,
                              "source": "metadata" if any(key in metadata for key in ("input_size", "imgsz")) or "imgsz" in export_args else "--imgsz fallback"}))
    except Exception as exc:
        checks.append(result("model_metadata", "FAIL", "模型配置检查失败：{}".format(exc),
                             {"exception_type": type(exc).__name__}))
        # A JSON-bound hash remains independently checkable if imports/labels fail.
        metadata = {}
        sidecar = model.with_suffix(".json")
        try:
            if sidecar.is_file():
                with sidecar.open(encoding="utf-8-sig") as stream:
                    value = json.load(stream)
                if isinstance(value, dict):
                    metadata = value
        except Exception as error:
            checks.append(result("model_sidecar_read", "WARN", "无法额外读取 JSON 哈希配置：{}".format(error)))
    expected = metadata.get("source_model_sha256")
    if expected is None:
        checks.append(result("model_hash", "WARN", "没有 source_model_sha256；无法确认旁车元数据是否绑定当前模型。"))
    else:
        try:
            if not isinstance(expected, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None:
                raise ValueError("source_model_sha256 必须为 64 位十六进制 SHA256。")
            verifier = getattr(sys.modules.get("detector"), "verify_model_hash", None)
            if verifier is not None:
                if not verifier(model, metadata):
                    raise ValueError("模型哈希校验未完成。")
                actual = expected.lower()
            else:
                actual = stream_sha256(model)
                if actual != expected.lower():
                    raise ValueError("模型 SHA256 不匹配；请重新核对模型与元数据，不能沿用旧类别说明。")
            checks.append(result("model_hash", "PASS", "模型 SHA256 与旁车绑定值一致。",
                                 {"sha256": actual, "read_mode": "streamed"}))
        except Exception as exc:
            checks.append(result("model_hash", "FAIL", str(exc), {"expected_sha256": expected}))
    return checks


def check_runtime_library():
    try:
        found = ctypes.util.find_library("rknnrt")
        error = None
    except Exception as exc:
        found, error = None, str(exc)
    candidates = ["/usr/lib/librknnrt.so", "/usr/lib64/librknnrt.so", "/usr/local/lib/librknnrt.so",
                  "/usr/lib/aarch64-linux-gnu/librknnrt.so", "/lib/aarch64-linux-gnu/librknnrt.so"]
    candidates.extend(str(Path(directory) / "librknnrt.so")
                      for directory in os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep) if directory)
    existing = []
    for item in dict.fromkeys(candidates):
        path = Path(item)
        try:
            if path.is_file():
                existing.append({"path": item, "resolved_path": str(path.resolve()), "readable": os.access(str(path), os.R_OK)})
        except OSError:
            continue
    return result("runtime_library", "PASS" if found or existing else "WARN",
                  "找到 RKNN Runtime 候选库；尚未执行或核实兼容性。" if found or existing else
                  "常见路径未发现 librknnrt；可能位于供应商或 wheel 私有目录，请核对板端安装。",
                  {"find_library": found, "paths": existing, "lookup_error": error, "loaded_via_ctypes": False})


def list_camera_devices():
    devices = []
    for name in sorted(glob.glob("/dev/video*"), key=lambda item: (len(item), item)):
        path = Path(name)
        if re.fullmatch(r"video\d+", path.name) is None:
            continue
        label, error = _read_text(Path("/sys/class/video4linux") / path.name / "name")
        try:
            character = stat.S_ISCHR(path.stat().st_mode)
        except OSError:
            character = None
        devices.append({"path": name, "name": label, "name_read_error": error,
                        "readable": os.access(name, os.R_OK), "writable": os.access(name, os.W_OK),
                        "character_device": character})
    return devices


def camera_inventory_result():
    devices = list_camera_devices()
    paths = [device["path"] for device in devices]
    if not paths:
        message = "未列出 /dev/video*；默认摄像头 41 不存在，摄像头读取未验证。"
    elif "/dev/video41" not in paths:
        message = "默认摄像头 41 不存在；实际设备：{}。需明确选择并读取验证，不能猜测哪个是采集节点。".format(", ".join(paths))
    else:
        message = "已列出视频设备；节点存在不等于可采集图像，尚未打开摄像头。"
    return result("camera_inventory", "PASS" if "/dev/video41" in paths else "WARN", message,
                  {"devices": devices, "opened": False, "capture_capability_verified": False})


def check_npu_evidence():
    nodes = sorted(set(glob.glob("/dev/rknpu*") + glob.glob("/dev/dri/renderD*")))
    node_details = [{"path": name, "readable": os.access(name, os.R_OK), "writable": os.access(name, os.W_OK)} for name in nodes]
    checks = [result("npu_device_nodes", "WARN" if not nodes else "PASS",
                     "发现候选设备节点，但不能据此证明 NPU 已正常执行。" if nodes else
                     "未发现常见 NPU/DRM 节点；设备命名和权限因镜像而异，不能据此断定硬件损坏。",
                     {"nodes": node_details})]
    patterns = ["/sys/class/devfreq/*npu*/cur_freq", "/sys/class/devfreq/*npu*/load",
                "/sys/kernel/debug/rknpu/load", "/sys/kernel/debug/rknpu/version"]
    evidence = []
    for pattern in patterns:
        paths = glob.glob(pattern)
        if not paths and "*" not in pattern:
            paths = [pattern]
        for name in paths:
            text, error = _read_text(name)
            evidence.append({"path": name, "value": text, "error": error})
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        label, _ = _read_text(Path(zone) / "type")
        if label and any(word in label.lower() for word in ("npu", "soc")):
            text, error = _read_text(Path(zone) / "temp")
            evidence.append({"path": str(Path(zone) / "temp"), "sensor": label, "value": text, "error": error,
                             "note": "SoC 传感器不一定是 NPU 独立温度。"})
    readable = any(item["value"] is not None for item in evidence)
    checks.append(result("npu_readonly_evidence", "PASS" if readable else "WARN",
                         "已采集可读的频率/负载/温度证据；不代表本程序已执行 NPU。" if readable else
                         "没有可读的 NPU 频率/负载/温度证据；可能受权限或镜像限制，不要求切换 root。",
                         {"evidence": evidence, "npu_execution_verified": False}))
    return checks


def camera_source(value):
    value = str(value)
    if value.isdecimal():
        return int(value)
    if re.fullmatch(r"/dev/video\d+", value):
        return value
    raise ValueError("--camera 仅接受非负编号或 /dev/videoN，例如 --camera 41。")


def timing_statistics(samples):
    values = sorted(float(value) for value in samples)
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("计时样本必须是非空的有限非负数。")
    def percentile(fraction):
        location = (len(values) - 1) * fraction
        lower, upper = int(math.floor(location)), int(math.ceil(location))
        return values[lower] + (values[upper] - values[lower]) * (location - lower)
    return {"mean": sum(values) / len(values), "p50": percentile(0.5), "p95": percentile(0.95),
            "min": values[0], "max": values[-1], "count": len(values)}


def probe_npu(request):
    """Only called by an explicitly requested, independently timed worker."""
    import cv2
    from detector import Detector
    model = resolve_model(Path(request["model"]))
    image_path = Path(request["image"])
    if not image_path.is_file():
        raise ValueError("NPU 测试图片不存在：{}".format(image_path))
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("无法读取 NPU 测试图片：{}".format(image_path))
    backend = None
    try:
        started = time.perf_counter()
        original = Path(request["model"])
        backend = Detector(original if original.is_dir() else model, labels=request.get("labels"),
                           imgsz=request.get("imgsz", 640), output_format=request.get("output_format", "auto"),
                           normalized_boxes=request.get("normalized_boxes"), core=request.get("core", "auto"))
        init_ms = (time.perf_counter() - started) * 1000
        if backend.backend != "rknn":
            raise RuntimeError("NPU 测试拒绝非 RKNN 后端，禁止回退 CPU。")
        fire_class = infer_fire_class(backend.labels, request.get("fire_class"))
        def predict_once():
            start = time.perf_counter()
            detections = backend.predict(image)
            total = (time.perf_counter() - start) * 1000
            timing = getattr(backend, "last_timing", {}) or {}
            runtime_ms = timing.get("inference_ms")
            if runtime_ms is not None:
                runtime_ms = float(runtime_ms)
                if not math.isfinite(runtime_ms) or runtime_ms < 0:
                    raise RuntimeError("后端返回了无效运行调用计时。")
            return {"pipeline_ms": total, "runtime_call_ms": runtime_ms, "detections": len(detections)}
        first = predict_once()
        warmup, runs = int(request.get("warmup", 3)), int(request.get("runs", 10))
        if warmup < 0 or runs <= 0:
            raise ValueError("warmup 必须非负，runs 必须为正数。")
        for _ in range(warmup):
            predict_once()
        measurements = [predict_once() for _ in range(runs)]
        pipeline = timing_statistics([item["pipeline_ms"] for item in measurements])
        runtime_samples = [item["runtime_call_ms"] for item in measurements]
        runtime = timing_statistics(runtime_samples) if all(value is not None for value in runtime_samples) else None
        return result("npu_probe", "PASS", "已通过 RKNNLite 完成真实图片推理与预热后计时；没有回退 CPU。",
                      {"backend": "rknn", "model": str(model), "image": str(image_path), "core": request.get("core", "auto"),
                       "labels": list(backend.labels), "fire_class": fire_class,
                       "input_size": list(backend.input_size), "init_ms": init_ms,
                       "first": first, "warmup_after_first": warmup, "runs": runs,
                       "steady_state": {"runtime_call_ms": runtime, "pipeline_ms": pipeline},
                       "measurements": measurements,
                       "output_shapes": getattr(backend, "last_output_shapes", None),
                       "output_format": getattr(backend, "last_output_format", None) or backend.output_format,
                       "note": "pipeline 包括 CPU 预处理和后处理；runtime_call 是 RKNNLite.inference 的墙钟时间，"
                               "不是驱动纯硬件时钟。通过仅代表此图片可执行，不证明准确率或全部算子都在 NPU。"})
    finally:
        if backend is not None:
            backend.close()


def probe_camera(request):
    import cv2
    source = camera_source(request["camera"])
    capture = None
    try:
        started = time.perf_counter()
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise RuntimeError("摄像头无法打开：{}".format(request["camera"]))
        ok, frame = capture.read()  # Exactly one read; the parent enforces a hard timeout.
        shape = getattr(frame, "shape", ())
        if not ok or frame is None or len(shape) < 2 or min(shape[:2]) <= 0:
            raise RuntimeError("摄像头已打开但没有成功读取有效帧：{}".format(request["camera"]))
        return result("camera_probe", "PASS", "指定摄像头成功打开并读取一帧。",
                      {"source": request["camera"], "frame_shape": list(shape),
                       "open_and_read_ms": (time.perf_counter() - started) * 1000, "frames_read": 1,
                       "note": "没有验证长期稳定性、帧率或其它摄像头节点。"})
    finally:
        if capture is not None:
            capture.release()


def _text_tail(value, length=8000):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return (value or "")[-length:]


def run_isolated_probe(kind, request, timeout, runner=None):
    """Use files for structured output so native stdout cannot corrupt JSON."""
    runner = runner or subprocess.run
    try:
        with tempfile.TemporaryDirectory(prefix="fire_device_probe_") as temporary:
            request_path, result_path = Path(temporary) / "request.json", Path(temporary) / "result.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, str(Path(__file__).resolve()), "--_probe", kind,
                       "--_request", str(request_path), "--_result", str(result_path)]
            try:
                completed = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                                   text=True, encoding="utf-8", errors="replace", check=False)
            except subprocess.TimeoutExpired as exc:
                return result(kind + "_probe", "FAIL", "{} 探测超过 {} 秒，子进程已被终止；不回退 CPU。".format(kind, timeout),
                              {"timed_out": True, "timeout_seconds": timeout,
                               "stdout": _text_tail(exc.stdout), "stderr": _text_tail(exc.stderr)})
            logs = {"returncode": completed.returncode, "stdout": _text_tail(completed.stdout),
                    "stderr": _text_tail(completed.stderr), "timeout_seconds": timeout}
            try:
                with result_path.open(encoding="utf-8") as stream:
                    payload = json.load(stream)
                if (not isinstance(payload, dict) or payload.get("status") not in STATUSES or
                        not isinstance(payload.get("details"), dict)):
                    raise ValueError("子进程结果结构无效")
                payload["id"] = kind + "_probe"
                payload["details"]["worker"] = logs
                if completed.returncode != 0:
                    payload["status"] = "FAIL"
                    payload["message"] = "探测子进程退出失败：{}".format(payload.get("message", completed.returncode))
                if payload["status"] != "PASS":
                    payload["status"] = "FAIL"
                return payload
            except (ValueError, OSError) as exc:
                return result(kind + "_probe", "FAIL", "未收到有效探测结果：{}".format(exc), logs)
    except Exception as exc:
        return result(kind + "_probe", "FAIL", "无法启动隔离探测：{}".format(exc), {"exception_type": type(exc).__name__})


def _worker_main(args):
    try:
        with args._request.open(encoding="utf-8") as stream:
            request = json.load(stream)
        payload = probe_npu(request) if args._probe == "npu" else probe_camera(request)
    except Exception as exc:
        payload = result(args._probe + "_probe", "FAIL", str(exc),
                         {"exception_type": type(exc).__name__, "traceback": traceback.format_exc()[-8000:]})
    try:
        args._result.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print("探测结果写入失败：{}".format(exc), file=sys.stderr)
        return 1
    return 0 if payload["status"] == "PASS" else 1


def _request(args):
    return {"model": str(args.model.expanduser().resolve()), "labels": args.labels,
            "fire_class": args.fire_class, "imgsz": args.imgsz, "output_format": args.output_format,
            "normalized_boxes": args.normalized_boxes, "core": args.core,
            "image": str(args.image.expanduser().resolve()), "warmup": args.warmup,
            "runs": args.runs, "camera": args.camera}


def check_teaching_assets():
    checks=[]
    required=('Arial-Unicode.ttf','libSmartSensorDriver.so','fire_yolo26_v20.py',
              'fire_yolo26_v20_answer.py','zone_teaching_support.py','teaching_support.py',
              'detector.py','fire_tracker.py','box_smoother.py','video_pipeline.py','io_helpers.py')
    for name in required:
        path=ROOT/name
        exists=path.is_file() and path.stat().st_size>0
        # Answer code is optional on a student-only deployment.
        status='PASS' if exists else ('WARN' if name=='fire_yolo26_v20_answer.py' else 'FAIL')
        checks.append(result('asset.'+name,status,'{}：{}'.format(name,'存在' if exists else '缺失或为空')))
        if exists and name.endswith('.py'):
            try:
                ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
                checks.append(result('syntax.'+name,'PASS','{} 语法检查通过，未执行代码。'.format(name)))
            except (SyntaxError,UnicodeError) as exc:
                checks.append(result('syntax.'+name,'FAIL','{} 语法或编码异常：{}'.format(name,exc)))
    try:
        from PIL import ImageFont
        ImageFont.truetype(str(ROOT/'Arial-Unicode.ttf'),18)
        checks.append(result('font_load','PASS','指定中文字体可加载，未开启摄像头或蜂鸣器。'))
    except Exception as exc:
        checks.append(result('font_load','FAIL','字体加载失败：{}'.format(exc)))
    return checks


def build_report(args):
    checks = []
    for check_id, function in (("system_check", check_system), ("dependency_check", check_dependencies),
                               ("model_check", lambda: inspect_model(args)), ("teaching_assets", check_teaching_assets), ("runtime_check", check_runtime_library),
                               ("camera_inventory", camera_inventory_result), ("npu_evidence", check_npu_evidence)):
        try:
            value = function()
            checks.extend(value if isinstance(value, list) else [value])
        except Exception as exc:
            checks.append(result(check_id, "FAIL", "检查发生错误，但继续汇总：{}".format(exc),
                                 {"exception_type": type(exc).__name__}))
    request = _request(args)
    checks.append(run_isolated_probe("npu", request, args.timeout) if args.npu_test else
                  result("npu_probe", "SKIP", "未指定 --npu-test；没有加载模型到 NPU，也没有验证真实推理。"))
    checks.append(run_isolated_probe("camera", request, args.timeout) if args.camera is not None else
                  result("camera_probe", "SKIP", "未指定 --camera；没有打开摄像头，NPU 通过也不代表摄像头通过。"))
    counts = {status: sum(item["status"] == status for item in checks) for status in STATUSES}
    overall = "FAIL" if counts["FAIL"] else "WARN" if counts["WARN"] else "PASS"
    return {"schema_version": 1, "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": overall, "summary": counts, "configuration": request, "results": checks,
            "limitations": ["默认结果没有验证真实 NPU 或摄像头，需查看对应 probe 项。",
                            "工具不会安装依赖、修改系统设置、发送 UDP 或驱动云台。",
                            "真实推理通过不代表识别准确率，运行调用耗时也不是纯 NPU 硬件时钟。"]}


def main(argv=None):
    args = parse_args(argv)
    if args._probe is not None:
        return _worker_main(args)
    report = build_report(args)
    for item in report["results"]:
        print("[{}] {}".format(item["status"], item["message"]))
        if args.list_cameras and item["id"] == "camera_inventory":
            for device in item["details"].get("devices", []):
                print("  {} | {} | read={} write={}".format(device["path"], device["name"] or "名称不可读",
                                                            device["readable"], device["writable"]))
        if item["id"] == "npu_probe" and item["status"] == "PASS":
            details = item["details"]
            print("  init_ms={:.2f}; 首次={}；预热后={}".format(details["init_ms"], details["first"], details["steady_state"]))
    try:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print("[FAIL] 无法保存 JSON 报告：{}".format(exc), file=sys.stderr)
        return 1
    print("所选检查总体结果：{}；JSON 报告：{}".format(report["status"], args.json.resolve()))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
