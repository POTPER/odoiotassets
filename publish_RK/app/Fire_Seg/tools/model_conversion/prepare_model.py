#!/usr/bin/env python3
"""V20 conversion reference for Rockchip one2one box/score branches.

Run on a separate x86_64 Linux conversion host with compatible RKNN-Toolkit2.
Use a local trained fire detector. This reference does not convert the current
single-output model automatically and does not install packages or fetch weights.
Read README.md in this directory before use. No conversion was performed while
preparing the V20 teaching materials.
"""

import argparse
import ast
import json
import os
import platform
import re
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "converted" / "fire_yolo26.rknn"
LETTERBOX_COLOR = 114


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--weights", type=Path,
                        help="Local YOLO26 detection .pt file; no automatic download.")
    source.add_argument("--onnx", type=Path,
                        help="Use an existing ONNX instead of exporting --weights.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output .rknn path; a .json sidecar is also written.")
    parser.add_argument("--imgsz", type=int, default=640,
                        help="Square input size, a positive multiple of 32 (default: 640).")
    parser.add_argument("--quantize", action="store_true",
                        help="Build INT8 using real deployment images; default is FP16.")
    parser.add_argument("--dataset", type=Path,
                        help="INT8 calibration list, one image per line; paths relative to this list.")
    parser.add_argument("--outputs", nargs=2, metavar=("TENSOR_A", "TENSOR_B"),
                        help="Explicit ONNX output tensor/node names, in desired RKNN output order.")
    parser.add_argument("--labels", type=Path,
                        help="Class names as a JSON list/indexed dict, or one name per text line.")
    args = parser.parse_args(argv)
    if args.imgsz <= 0 or args.imgsz % 32:
        parser.error("--imgsz must be a positive multiple of 32.")
    if args.quantize and args.dataset is None:
        parser.error("--quantize requires --dataset with real deployment images.")
    if args.dataset is not None and not args.quantize:
        parser.error("--dataset is only used with --quantize.")
    if args.output.suffix.lower() != ".rknn":
        parser.error("--output must end in .rknn.")
    return args


def require_file(path, description):
    path = path.expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("{} is missing or empty: {}".format(description, path))
    return path


def normalize_labels(value):
    if isinstance(value, dict):
        converted = {int(key): name for key, name in value.items()}
        if sorted(converted) != list(range(len(converted))):
            raise ValueError("Class IDs must be contiguous and start at 0.")
        value = [converted[index] for index in range(len(converted))]
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("Labels must be a nonempty list or an indexed dictionary.")
    if any(not isinstance(name, str) or not name.strip() for name in value):
        raise ValueError("Every class label must be a nonempty string.")
    return [name.strip() for name in value]


def load_labels(path):
    text = require_file(path, "Labels file").read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        return normalize_labels(json.loads(text))
    return normalize_labels([line.strip() for line in text.splitlines()
                             if line.strip() and not line.lstrip().startswith("#")])


def labels_from_metadata(model):
    metadata = {item.key: item.value for item in model.metadata_props}
    if "names" not in metadata:
        return None
    try:
        value = json.loads(metadata["names"])
    except (ValueError, TypeError):
        value = ast.literal_eval(metadata["names"])
    return normalize_labels(value)


def export_onnx(weights, imgsz):
    weights = require_file(weights, "Weights file (obtain the .pt file first)")
    if weights.suffix.lower() != ".pt":
        raise ValueError("--weights must be a local .pt file; use --onnx for ONNX.")
    # Ultralytics otherwise attempts to install missing export dependencies.
    os.environ["YOLO_AUTOINSTALL"] = "False"
    try:
        import ultralytics.utils
        ultralytics.utils.AUTOINSTALL = False
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Install a YOLO26-capable Ultralytics and PyTorch environment first.") from exc
    detector = YOLO(str(weights))
    if detector.task != "detect":
        raise ValueError("Only YOLO26 axis-aligned detection weights are supported.")
    head = detector.model.model[-1]
    if (getattr(head, "one2one_cv2", None) is None or
            getattr(head, "one2one_cv3", None) is None or
            getattr(head, "reg_max", None) != 1):
        raise ValueError("Expected the YOLO26 one2one detection head (reg_max=1).")
    head.end2end = True
    if not head.end2end:
        raise ValueError("The installed head cannot enable one2one inference.")
    names = normalize_labels(detector.names)
    # Export ONNX with one2one selected so branch provenance can be verified.
    # nms=False is essential, and simplification can erase that provenance.
    exported = detector.export(format="onnx", imgsz=imgsz, batch=1, dynamic=False,
                               simplify=False, opset=12, device="cpu", half=False,
                               nms=False)
    return require_file(Path(exported), "Exported ONNX"), names


def tensor_shape(value_info):
    dimensions = value_info.type.tensor_type.shape.dim
    return tuple(int(dim.dim_value) if dim.HasField("dim_value") else None
                 for dim in dimensions)


def graph_maps(model):
    producers = {}
    for node in model.graph.node:
        for name in node.output:
            if name in producers:
                raise ValueError("ONNX contains duplicate tensor name: {}".format(name))
            producers[name] = node
    values = {value.name: value for value in
              list(model.graph.input) + list(model.graph.value_info) + list(model.graph.output)}
    return producers, values


def ancestor_names(tensor, producers):
    pending, seen, names = [tensor], set(), []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        node = producers.get(name)
        if node is not None:
            names.append(node.name)
            pending.extend(node.input)
    return names


def verify_one2one(tensor, kind, producers):
    names = ancestor_names(tensor, producers)
    required = "one2one_cv3" if kind == "scores" else "one2one_cv2"
    scopes, tokens_by_name = set(), []
    for name in names:
        tokens = [part for part in re.split(r"[/.]+", name) if part]
        tokens_by_name.append(tokens)
        for index, token in enumerate(tokens):
            if token == required:
                scopes.add(tuple(tokens[:index]))
    if not scopes:
        raise ValueError("{}: cannot prove {} provenance from ONNX node/weight names. "
                         "Re-export with simplify=False and one2one enabled; --outputs "
                         "cannot bypass this validation.".format(tensor, required))
    # A backbone also contains cv2/cv3 names; only reject those in the same head scope.
    for tokens in tokens_by_name:
        for scope in scopes:
            index = len(scope)
            if (tuple(tokens[:index]) == scope and len(tokens) > index and
                    tokens[index] in ("cv2", "cv3")):
                raise ValueError("{} also depends on the one2many head.".format(tensor))


def unwrap_node(tensor, producers):
    node = producers.get(tensor)
    while node is not None and node.op_type in ("Identity", "Cast"):
        node = producers.get(node.input[0])
    return node


def verify_xyxy(tensor, producers):
    node = unwrap_node(tensor, producers)
    if node is None or node.op_type != "Mul":
        raise ValueError("{}: expected decoded boxes multiplied by pixel strides.".format(tensor))
    for source in node.input:
        concat = unwrap_node(source, producers)
        if concat is None or concat.op_type != "Concat" or len(concat.input) != 2:
            continue
        axes = [attribute.i for attribute in concat.attribute if attribute.name == "axis"]
        corners = [unwrap_node(name, producers) for name in concat.input]
        if (axes == [1] and all(corner is not None for corner in corners) and
                [corner.op_type for corner in corners] == ["Sub", "Add"]):
            return
    raise ValueError("{}: cannot prove xyxy decode (Concat(Sub, Add) * stride). "
                     "Raw regression or xywh outputs are not supported.".format(tensor))


def output_kind(tensor, producers, values, float_types):
    info = values.get(tensor)
    if info is None:
        raise ValueError("No inferred shape for output {}.".format(tensor))
    shape = tensor_shape(info)
    if (len(shape) != 3 or shape[0] not in (None, 1) or
            shape[1] is None or shape[1] <= 0 or
            (shape[2] is not None and shape[2] <= 0)):
        raise ValueError("{} must have rank 3, batch 1, and a known positive channel "
                         "count; inferred shape is {}.".format(tensor, shape))
    if info.type.tensor_type.elem_type not in float_types:
        raise ValueError("{} must be a floating point ONNX output.".format(tensor))
    producer = unwrap_node(tensor, producers)
    if producer is not None and producer.op_type == "Sigmoid":
        kind = "scores"
    elif producer is not None and producer.op_type == "Mul" and shape[1] == 4:
        kind = "boxes"
        verify_xyxy(tensor, producers)
    else:
        raise ValueError("{} is neither sigmoid scores nor decoded xyxy boxes.".format(tensor))
    verify_one2one(tensor, kind, producers)
    return kind, shape


def probe_output_shapes(model, outputs, shapes, producers, values, input_name, imgsz):
    """Resolve symbolic output dimensions by running only the verified branches.

    A static Ultralytics input does not guarantee that ONNX shape inference can
    propagate the batch/anchor dimensions through every Reshape. Keep semantic
    validation independent of that limitation, then check the actual arrays.
    """
    try:
        import numpy as np
        import onnx
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("ONNX Runtime is required to verify symbolic output dimensions. "
                           "Install numpy and onnxruntime in the conversion environment.") from exc
    needed, pending = set(), list(outputs)
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        node = producers.get(name)
        if node is not None:
            pending.extend(node.input)
    probe = onnx.ModelProto()
    probe.CopyFrom(model)
    # Prune the end2end TopK tail, rather than adding intermediate tensors as
    # extra outputs and evaluating unrelated postprocessing as well.
    del probe.graph.node[:]
    probe.graph.node.extend(node for node in model.graph.node
                            if any(name in needed for name in node.output))
    del probe.graph.initializer[:]
    probe.graph.initializer.extend(item for item in model.graph.initializer if item.name in needed)
    del probe.graph.value_info[:]
    probe.graph.value_info.extend(item for item in model.graph.value_info if item.name in needed)
    del probe.graph.output[:]
    probe.graph.output.extend(values[name] for name in outputs)
    try:
        options = ort.SessionOptions()
        options.log_severity_level = 3
        session = ort.InferenceSession(probe.SerializeToString(), sess_options=options,
                                       providers=["CPUExecutionProvider"])
        arrays = session.run(list(outputs), {
            input_name: np.zeros((1, 3, imgsz, imgsz), dtype=np.float32)})
    except Exception as exc:
        raise RuntimeError("ONNX Runtime could not verify the truncated YOLO26 outputs: {}".format(exc)) from exc
    if len(arrays) != len(outputs):
        raise ValueError("ONNX Runtime returned an unexpected number of outputs.")
    verified = []
    for name, inferred, array in zip(outputs, shapes, arrays):
        if array.dtype not in (np.dtype("float16"), np.dtype("float32")):
            raise ValueError("{} probe output must be floating point, got {}.".format(name, array.dtype))
        actual = tuple(int(size) for size in array.shape)
        if (len(actual) != 3 or actual[0] != 1 or actual[1] != inferred[1] or actual[2] <= 0 or
                any(known is not None and known != measured
                    for known, measured in zip(inferred, actual))):
            raise ValueError("{} probe shape {} disagrees with expected (1,{},N) / inferred {}.".format(
                name, actual, inferred[1], inferred))
        if not np.isfinite(array).all():
            raise ValueError("{} probe produced NaN or infinite values.".format(name))
        verified.append(actual)
    print("Verified symbolic ONNX output shapes with CPU inference: {}".format(list(zip(outputs, verified))))
    return verified


def inspect_onnx(onnx_path, imgsz, requested):
    try:
        import onnx
    except ImportError as exc:
        raise RuntimeError("Install onnx in the conversion environment first.") from exc
    model = onnx.load(str(onnx_path))
    onnx.checker.check_model(model)
    try:
        model = onnx.shape_inference.infer_shapes(model, strict_mode=True, data_prop=True)
    except Exception as exc:
        raise ValueError("ONNX shape inference failed; export a static model with simplify=False.") from exc
    initializer_names = {item.name for item in model.graph.initializer}
    inputs = [item for item in model.graph.input if item.name not in initializer_names]
    expected = (1, 3, imgsz, imgsz)
    if len(inputs) != 1 or tensor_shape(inputs[0]) != expected:
        actual = [(item.name, tensor_shape(item)) for item in inputs]
        raise ValueError("Expected one NCHW input {}, got {}.".format(expected, actual))
    if inputs[0].type.tensor_type.elem_type != onnx.TensorProto.FLOAT:
        raise ValueError("Expected a float32 ONNX input with RGB values normalized to [0,1].")
    producers, values = graph_maps(model)
    float_types = (onnx.TensorProto.FLOAT, onnx.TensorProto.FLOAT16)
    if requested:
        outputs = []
        for name in requested:
            if name not in producers:
                matches = [node for node in model.graph.node if node.name == name]
                if len(matches) != 1 or len(matches[0].output) != 1:
                    raise ValueError("ONNX tensor/node does not uniquely exist: {}".format(name))
                name = matches[0].output[0]
            outputs.append(name)
    else:
        candidates = {"scores": [], "boxes": []}
        for name, node in producers.items():
            if node.op_type not in ("Sigmoid", "Mul"):
                continue
            try:
                kind, shape = output_kind(name, producers, values, float_types)
            except ValueError:
                continue
            candidates[kind].append(name)
        if any(len(items) != 1 for items in candidates.values()):
            interesting = [name for name, node in producers.items()
                           if node.op_type in ("Sigmoid", "Mul") and name in values and
                           len(tensor_shape(values[name])) == 3]
            raise ValueError("Could not uniquely select one2one outputs. Verified candidates: {}. "
                             "Rank-3 Sigmoid/Mul tensors: {}. Inspect the graph and use "
                             "--outputs SCORE_TENSOR BOX_TENSOR, or re-export without "
                             "simplification.".format(candidates, interesting))
        outputs = [candidates["scores"][0], candidates["boxes"][0]]
    kinds, shapes = zip(*(output_kind(name, producers, values, float_types) for name in outputs))
    if sorted(kinds) != ["boxes", "scores"]:
        raise ValueError("--outputs must contain exactly one scores tensor and one boxes tensor.")
    scores_index, boxes_index = kinds.index("scores"), kinds.index("boxes")
    if any(size is None for shape in shapes for size in shape):
        shapes = probe_output_shapes(model, outputs, shapes, producers, values, inputs[0].name, imgsz)
    if shapes[scores_index][2] != shapes[boxes_index][2]:
        raise ValueError("Boxes and scores must contain the same number of anchors.")
    return model, outputs, list(shapes), scores_index, boxes_index


def calibration_dataset(dataset_path, directory, imgsz):
    """Use the same square letterbox/114 preprocessing as live inference."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("INT8 calibration preprocessing requires opencv-python.") from exc
    dataset_path = require_file(dataset_path, "Calibration image list")
    images = []
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        source = Path(entry).expanduser()
        if not source.is_absolute():
            source = dataset_path.parent / source
        source = require_file(source, "Calibration image on line {}".format(line_number))
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Unreadable calibration image: {}".format(source))
        height, width = image.shape[:2]
        ratio = min(imgsz / float(height), imgsz / float(width))
        resized = (int(round(width * ratio)), int(round(height * ratio)))
        image = cv2.resize(image, resized, interpolation=cv2.INTER_LINEAR)
        dw, dh = (imgsz - resized[0]) / 2.0, (imgsz - resized[1]) / 2.0
        image = cv2.copyMakeBorder(image, int(round(dh - 0.1)), int(round(dh + 0.1)),
                                   int(round(dw - 0.1)), int(round(dw + 0.1)),
                                   cv2.BORDER_CONSTANT, value=(LETTERBOX_COLOR,) * 3)
        target = directory / "calibration_{:06d}.png".format(len(images))
        if image.shape != (imgsz, imgsz, 3) or not cv2.imwrite(str(target), image):
            raise RuntimeError("Failed to prepare calibration image: {}".format(source))
        images.append(str(target.resolve()))
    if not images:
        raise ValueError("Calibration dataset contains no images.")
    result = directory / "calibration.txt"
    result.write_text("\n".join(images) + "\n", encoding="utf-8")
    print("Prepared {} real calibration images with letterbox padding 114.".format(len(images)))
    return result


def check_result(result, operation, allow_none=False):
    if result != 0 and not (allow_none and result is None):
        raise RuntimeError("{} failed (return code {}).".format(operation, result))


def convert(onnx_path, outputs, output, quantize, dataset, imgsz):
    try:
        from rknn.api import RKNN
    except ImportError as exc:
        raise RuntimeError("Install RKNN-Toolkit2 on the x86_64 Linux conversion host first.") from exc
    rknn = RKNN(verbose=False)
    try:
        check_result(rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]],
                                 target_platform="rk3588", float_dtype="float16",
                                 quant_img_RGB2BGR=False), "RKNN config", allow_none=True)
        check_result(rknn.load_onnx(model=str(onnx_path), outputs=outputs), "RKNN load_onnx")
        with tempfile.TemporaryDirectory(prefix="yolo26_calibration_") as temporary:
            calibration = (calibration_dataset(dataset, Path(temporary), imgsz)
                           if quantize else None)
            build_args = {"do_quantization": quantize}
            if calibration is not None:
                build_args["dataset"] = str(calibration)
            check_result(rknn.build(**build_args), "RKNN build")
        check_result(rknn.export_rknn(str(output)), "RKNN export_rknn")
        require_file(output, "Exported RKNN")
    finally:
        rknn.release()


def main(argv=None):
    args = parse_args(argv)
    try:
        if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
            raise RuntimeError("Run conversion on x86_64 Linux with RKNN-Toolkit2; "
                               "copy the resulting .rknn and .json to RK3588 afterward.")
        if args.onnx is not None:
            onnx_path, labels = require_file(args.onnx, "ONNX model"), None
        else:
            onnx_path, labels = export_onnx(args.weights, args.imgsz)
        model, outputs, shapes, scores_index, boxes_index = inspect_onnx(
            onnx_path, args.imgsz, args.outputs)
        if args.labels is not None:
            labels = load_labels(args.labels)
        elif labels is None:
            labels = labels_from_metadata(model)
        num_classes = shapes[scores_index][1]
        if labels is None:
            raise ValueError("No class labels in metadata. Pass --labels with the real training class order.")
        if len(labels) != num_classes:
            raise ValueError("{} labels do not match {} score channels.".format(len(labels), num_classes))
        output = args.output.expanduser().resolve()
        if output.exists() or output.with_suffix(".json").exists():
            raise ValueError("Output or sidecar already exists; choose a new --output path.")
        output.parent.mkdir(parents=True, exist_ok=True)
        print("RKNN output order: {}".format(list(zip(outputs, shapes))))
        print("Use a trained fire/smoke detector; a generic COCO model is not a fire detector.")
        convert(onnx_path, outputs, output, args.quantize, args.dataset, args.imgsz)
        metadata = {
            "input_size": [args.imgsz, args.imgsz], "input_layout": "NHWC",
            "input_dtype": "uint8", "color_order": "RGB", "normalization": "embedded_mean0_std255",
            "labels": labels, "num_classes": num_classes,
            "output_format": "rockchip_yolo26", "box_format": "xyxy",
            "boxes_output": boxes_index, "scores_output": scores_index,
            "output_names": outputs, "output_shapes": [list(shape) for shape in shapes],
            "output_dequantization": "runtime_float", "one2one": True, "nms": False,
            "letterbox_color": LETTERBOX_COLOR, "normalized_boxes": False,
            "target_platform": "rk3588", "precision": "int8" if args.quantize else "fp16",
            "source_onnx": str(onnx_path),
        }
        sidecar = output.with_suffix(".json")
        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Saved {}\nSaved {}".format(output, sidecar))
        print("Inference must request dequantized floating point outputs, then apply confidence + TopK.")
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
