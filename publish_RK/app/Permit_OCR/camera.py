"""预览摄像头并按键采集用于 OCR 的画面。"""

from __future__ import annotations

import os
import re
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from numpy import ndarray

    from demo import RecognitionSession


WINDOW = "Permit OCR"
PREVIEW_WIDTH = 480
SCAN_MESSAGES = {
    "ready": ("空格 扫描整张卡    R 清空    Q / Esc 退出", "Space: Scan full card   R: Clear   Q / Esc: Quit"),
    "scanning": ("正在识别整张卡…", "Reading the full card..."),
    "clearing": ("表格已清空，正在结束识别…", "Form cleared. Finishing OCR..."),
    "reset": ("表格已清空    空格扫描整张卡", "Form cleared. Space: scan full card"),
    "failed": ("识别失败    按空格重拍整张卡", "OCR failed. Space: rescan full card"),
}


@dataclass
class ScanJob:
    source: str
    frame: ndarray
    future: Future
    discarded: bool = False


@lru_cache(maxsize=8)
def _preview_background(height, latest_y, scan_status):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from capture_result import chinese_font

    image = Image.new("RGB", (PREVIEW_WIDTH, height), (37, 42, 34))
    draw = ImageDraw.Draw(image)
    font = chinese_font()
    chinese_message, english_message = SCAN_MESSAGES[scan_status]
    if font:
        heading = font.font_variant(size=22)
        title, latest = "实时摄像头", "最近一次扫描"
        controls = chinese_message
    else:
        font = heading = ImageFont.load_default()
        title, latest = "Live camera", "Latest scan"
        controls = english_message
    draw.text((12, 6), title, font=heading, fill=(245, 248, 242))
    draw.text((12, 32), controls, font=font, fill=(207, 219, 197))
    if latest_y is not None:
        draw.text((12, latest_y), latest, font=font, fill=(207, 219, 197))
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def _place_photo(canvas, photo, top, height):
    import cv2

    source_height, source_width = photo.shape[:2]
    scale = min((PREVIEW_WIDTH - 24) / source_width, height / source_height)
    width = max(1, round(source_width * scale))
    fitted_height = max(1, round(source_height * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    fitted = cv2.resize(photo, (width, fitted_height), interpolation=interpolation)
    left = (PREVIEW_WIDTH - width) // 2
    y = top + (height - fitted_height) // 2
    canvas[y:y + fitted_height, left:left + width] = fitted


def _preview(frame: ndarray, form: ndarray, marked: Optional[ndarray], *, scan_status="ready") -> ndarray:
    import numpy as np

    height, form_width = form.shape[:2]
    available = height - 70
    live_height = round(available * 0.56) if marked is not None else available
    latest_y = 58 + live_height + 8 if marked is not None else None
    canvas = np.empty((height, PREVIEW_WIDTH + form_width, 3), dtype=np.uint8)
    canvas[:, :PREVIEW_WIDTH] = _preview_background(height, latest_y, scan_status)
    canvas[:, PREVIEW_WIDTH:] = form
    _place_photo(canvas, frame, 58, live_height)
    if latest_y is not None:
        _place_photo(canvas, marked, latest_y + 23, height - latest_y - 32)
    return canvas


def _window_visible(cv2) -> bool:
    try:
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) > 0
    except cv2.error:
        return False


def run_camera(source: str, session: RecognitionSession) -> None:
    """显示实时画面、最近一次标注图和整张卡的填写状态。"""
    import cv2

    device = re.fullmatch(r"(?:/dev/video)?([0-9]+)", source)
    if device is None:
        raise RuntimeError("摄像头输入应为设备编号或 /dev/videoN")
    if sys.platform.startswith("linux") and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
        raise RuntimeError("请在 Linux 图形桌面的终端中运行摄像头预览")

    index = int(device[1])
    camera = None
    window_opened = False
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="permit-ocr")
    job = None
    idle_status = "ready"
    try:
        camera = cv2.VideoCapture(index)
        if not camera.isOpened():
            device_name = f"/dev/video{index}" if sys.platform.startswith("linux") else source
            raise RuntimeError(f"无法打开摄像头 {device_name}，请检查设备编号、权限和占用情况")
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        ok, frame = camera.read()
        if not ok or frame is None or not frame.size:
            # 部分设备的默认采集模式可用，但无法输出请求的 1080p 画面。
            camera.release()
            camera = cv2.VideoCapture(index)
            ok, frame = camera.read()
            if not ok or frame is None or not frame.size:
                raise RuntimeError(f"摄像头 {source} 无法输出画面，请检查设备是否被占用")

        form = session.form_image()
        marked = None
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        window_opened = True
        height, form_width = form.shape[:2]
        scale = min(1.0, 1000 / (PREVIEW_WIDTH + form_width), 560 / height)
        cv2.resizeWindow(WINDOW, round((PREVIEW_WIDTH + form_width) * scale), round(height * scale))
        can_check_visibility = getattr(cv2, "currentUIFramework", lambda: "")() != "WAYLAND"
        window_was_visible = False
        capture_index = 0
        print("摄像头已打开。在预览窗口按空格抓拍，按 Q 或 Esc 退出。", flush=True)
        while True:
            scan_status = idle_status
            if job is not None:
                scan_status = "clearing" if job.discarded else "scanning"
            cv2.imshow(WINDOW, _preview(frame, form, marked, scan_status=scan_status))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if can_check_visibility:
                visible = _window_visible(cv2)
                if window_was_visible and not visible:
                    break
                window_was_visible = visible
            if key == ord(" ") and job is None:
                capture_index += 1
                session.reset()
                marked = None
                form = session.form_image()
                snapshot = frame.copy()
                scan_source = f"camera:{source}#{capture_index}"
                job = ScanJob(scan_source, snapshot, worker.submit(session.analyze, snapshot))
            elif key in (ord("r"), ord("R")):
                session.reset()
                marked = None
                form = session.form_image()
                idle_status = "reset"
                if job is not None:
                    job.discarded = True
                    job.future.cancel()

            if job is not None and job.future.done():
                # 写表格和历史在主线程完成，已经换卡的抓拍可在这里丢弃。
                if not job.discarded:
                    try:
                        analysis = job.future.result()
                    except Exception as exc:
                        print(f"本次 OCR 识别失败。{exc}", file=sys.stderr, flush=True)
                        idle_status = "failed"
                    else:
                        marked = session.capture(job.source, job.frame, analysis=analysis)
                        form = session.form_image()
                        idle_status = "ready"
                job = None

            ok, frame = camera.read()
            if not ok or frame is None or not frame.size:
                raise RuntimeError(f"无法从摄像头 {source} 读取画面")
    except cv2.error as exc:
        raise RuntimeError(f"摄像头采集或预览失败，请检查 OpenCV 图形界面支持。{exc}") from exc
    finally:
        if job is not None:
            job.future.cancel()
        try:
            if camera is not None:
                with suppress(cv2.error):
                    camera.release()
            if window_opened:
                with suppress(cv2.error):
                    cv2.destroyWindow(WINDOW)
        finally:
            worker.shutdown()


if __name__ == "__main__":
    from demo import main

    raise SystemExit(main())
