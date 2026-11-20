"""施工许可证演示卡 OCR，支持本地图片和摄像头抓拍。"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from install import local_dependencies
from permit_fields import (
    PERMIT_NUMBER_FIELD, REQUIRED_FIELD_PATHS, TextBox, extract_fields, field_report,
)
from records import HISTORY_FILENAME, HISTORY_LOCK_FILENAME, lookup_or_register, write_json, write_output


DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_CAMERA = "0" if sys.platform == "win32" else "41"


@dataclass(frozen=True)
class EntryStatus:
    label: str
    filled: int = 0
    total: int = len(REQUIRED_FIELD_PATHS)
    entered_at: Optional[str] = None


class RecognitionSession:
    def __init__(self, engine, output):
        self.engine = engine
        self.output = output
        self.reset()

    def reset(self):
        self.readings = {}
        self.sources = []
        self.entry_status = EntryStatus("未扫描")

    def analyze(self, frame):
        """识别一帧并提取字段，供后台执行。"""
        results, _ = self.engine(frame, text_score=0.4)
        boxes = [TextBox(box, text, float(score)) for box, text, score in (results or [])]
        return boxes, extract_fields(boxes)

    def _set_readings(self, source, analysis):
        boxes, readings = analysis
        self.readings = readings
        self.sources = [{"来源": source, "文本框": [asdict(box) for box in boxes]}]
        return readings

    def recognize(self, source, frame):
        return self._set_readings(source, self.analyze(frame))

    def _update_entry(self, report):
        filled = sum(path in self.readings for path in REQUIRED_FIELD_PATHS)
        number = report[PERMIT_NUMBER_FIELD]
        if number:
            path = self.output.with_name(HISTORY_FILENAME)
            try:
                created, entered_at = lookup_or_register(path, number, report, filled == len(REQUIRED_FIELD_PATHS))
            except (OSError, RuntimeError) as exc:
                print(f"录入失败。{exc}", file=sys.stderr, flush=True)
                return EntryStatus("录入失败", filled)
            if created:
                print(f"已录入 {number}，历史记录保存在 {path.resolve()}", flush=True)
            if entered_at:
                label = "已录入" if created else "该编号已录入"
                return EntryStatus(label, filled, entered_at=entered_at)
        return EntryStatus("缺少必填项 · 待重拍" if self.readings else "未识别 · 请重拍", filled)

    def save(self, report=None, *, entry=None):
        # 要修改结构化 JSON 字段，请编辑 permit_fields.py 顶部的「代码编辑区」。
        if report is None:
            report = field_report(self.readings)
        result = {**report, "原始识别": self.sources}
        if entry is not None:
            result["录入状态"] = {
                "状态": entry.label, "必填已填写": entry.filled,
                "必填总数": entry.total, "录入时间": entry.entered_at,
            }
        write_json(self.output, result)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        print(f"结果已保存到 {self.output.resolve()}", flush=True)

    def form_image(self):
        from entry_form import render_form

        return render_form(field_report(self.readings), self.entry_status)

    def capture(self, source, frame, *, analysis=None):
        import cv2

        from capture_result import render_capture

        if analysis is None:
            analysis = self.analyze(frame)
        readings = self._set_readings(source, analysis)
        result_image, marked_photo = render_capture(frame, readings)
        encoded, data = cv2.imencode(".png", result_image)
        if not encoded:
            raise RuntimeError("无法生成抓拍标注图")

        report = field_report(self.readings)
        self.entry_status = self._update_entry(report)
        self.save(report, entry=self.entry_status)
        marked_path = self.output.with_name(f"{self.output.stem}-marked.png")
        write_output(marked_path, data.tobytes())
        print(f"标注图已保存到 {marked_path.resolve()}", flush=True)
        return marked_photo


def main(argv=None):
    parser = argparse.ArgumentParser(description="识别建筑工程施工许可证演示卡，默认打开摄像头")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--image", type=Path, help="包含整张卡面的图片")
    inputs.add_argument("--sample", action="store_true", help="识别随附的样图")
    inputs.add_argument(
        "--camera", nargs="?", const=DEFAULT_CAMERA, metavar="设备",
        help=f"从摄像头抓拍，默认设备为 {DEFAULT_CAMERA}",
    )
    parser.add_argument(
        "--output", type=Path, default=DEMO_DIR / "output" / "permit.json",
        help="保存 JSON 的路径，默认写入 Demo 的 output/permit.json",
    )
    args = parser.parse_args(argv)
    reserved_paths = {args.output.parent.joinpath(name).resolve() for name in (HISTORY_FILENAME, HISTORY_LOCK_FILENAME)}
    if not args.output.name or args.output.resolve() in reserved_paths:
        parser.error("请为识别结果指定独立的文件名，records.json 和 .records.lock 用于录入历史")
    image_path = DEMO_DIR / "sample.png" if args.sample else args.image
    camera_source = args.camera if args.camera is not None else DEFAULT_CAMERA

    deps = local_dependencies()
    if deps is not None:
        sys.path.insert(0, str(deps))
    try:
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        parser.exit(
            1,
            "无法加载 OCR 依赖。RK3588 离线安装请运行 python3 install.py。"
            f"联网安装请运行 python -m pip install -r requirements.txt。\n{exc}\n",
        )

    try:
        if image_path is None:
            print(f"正在启动摄像头 {camera_source}…", flush=True)
        session = RecognitionSession(RapidOCR(use_angle_cls=False), args.output)
        if image_path is None:
            from camera import run_camera

            run_camera(camera_source, session)
        else:
            if image_path.resolve() == args.output.resolve():
                raise RuntimeError("JSON 输出路径与输入图片相同")
            data = np.fromfile(image_path, dtype=np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
            if frame is None:
                raise RuntimeError(f"无法解码图片 {image_path}")
            session.recognize(str(image_path), frame)
            session.save()
    except (OSError, RuntimeError, cv2.error) as exc:
        parser.exit(1, f"识别失败。{exc}\n")
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
