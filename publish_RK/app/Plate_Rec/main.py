"""Real-time RKNN license plate detection, recognition and UDP streaming."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from det import Detection
from plate_core import (
    CHARS,
    LatestQueue,
    PlateResult,
    RecognitionResult,
    ResultStabilizer,
    UdpPacketizer,
    decode_ctc,
    expanded_crop_bounds,
)
from rknn_executor import RKNN_model_container


LOG = logging.getLogger("plate_rec")


@dataclass(frozen=True)
class AppConfig:
    input_source: str = "video"
    camera_index: int = 41
    camera_width: int = 1280
    camera_height: int = 720
    jpeg_quality: int = 70
    image_scale: float = 0.4
    image_host: str = "127.0.0.1"
    image_port: int = 8088
    message_host: str = "127.0.0.1"
    message_port: int = 8089
    frame_queue_size: int = 3
    send_queue_size: int = 3
    vote_window: int = 3
    vote_minimum: int = 2
    retain_missed_frames: int = 2
    debug_images: bool = False
    debug_dir: str = "."
    det_model: str = "./model/det.rknn"
    rec_model: str = "./model/rec.rknn"
    font_path: str = "./lib/Arial.Unicode.ttf"


class Recognition:
    def __init__(self, model_path: str, npu_core: int):
        self.CHARS = list(CHARS)
        self.model = RKNN_model_container(model_path, npu_core)

    def predict(self, image: np.ndarray) -> RecognitionResult:
        if image is None or image.size == 0:
            return RecognitionResult("", 0.0, ())
        resized = cv2.resize(image, (94, 24))
        outputs = self.model.run([np.expand_dims(resized, 0)])
        if not outputs:
            return RecognitionResult("", 0.0, ())
        decoded = decode_ctc(outputs[0], self.CHARS)
        return decoded[0] if decoded else RecognitionResult("", 0.0, ())

    def decode(self, predictions: np.ndarray):
        results = decode_ctc(predictions, self.CHARS)
        return [result.text for result in results], [list(result.indices) for result in results]

    def release(self) -> None:
        self.model.release()


class PlatePipeline:
    def __init__(self, config: AppConfig):
        self.config = config
        self.detection = Detection(config.det_model, 1)
        self.recognition = Recognition(config.rec_model, 0)

    def predict(self, frame: np.ndarray) -> tuple[PlateResult, ...]:
        boxes, classes, scores = self.detection.predict(frame)
        if boxes is None:
            return ()

        results = []
        class_count = len(self.detection.CLASSES)
        for box, class_value, score in zip(boxes, classes, scores):
            class_id = int(class_value)
            if class_id < 0 or class_id >= class_count:
                LOG.warning("忽略非法检测类别: %s", class_id)
                continue
            bounds = expanded_crop_bounds(box, frame.shape)
            if bounds is None:
                continue
            x1, y1, x2, y2 = bounds
            recognition = self.recognition.predict(frame[y1:y2, x1:x2])
            results.append(
                PlateResult(
                    box_xyxy=(x1, y1, x2, y2),
                    class_id=class_id,
                    detection_score=float(score),
                    text=recognition.text,
                    recognition_confidence=recognition.confidence,
                )
            )
        return tuple(results)

    def release(self) -> None:
        self.detection.model.release()
        self.recognition.release()


class PlateApplication:
    def __init__(self, config: AppConfig):
        self.config = config
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.image_address = (config.image_host, config.image_port)
        self.message_address = (config.message_host, config.message_port)
        self.image_packetizer = UdpPacketizer(60000)
        self.message_packetizer = UdpPacketizer(5)
        self.frame_queue = LatestQueue(config.frame_queue_size)
        self.send_queue = LatestQueue(config.send_queue_size)
        self.stop_event = threading.Event()
        self.result_lock = threading.Lock()
        self.results: tuple[PlateResult, ...] = ()
        self.pipeline: PlatePipeline | None = None
        self.workers: list[threading.Thread] = []
        self.annotation_font = self._load_annotation_font()

    def _load_annotation_font(self):
        try:
            return ImageFont.truetype(self.config.font_path, 30)
        except OSError:
            LOG.warning("无法加载中文字体 %s，视频中将不绘制车牌文字", self.config.font_path)
            return None

    def send_packets(self, packetizer: UdpPacketizer, data: bytes, address) -> None:
        try:
            for packet in packetizer.packetize(data):
                self.socket.sendto(packet.toNetBytes(), address)
        except OSError:
            LOG.exception("UDP 发送失败: %s", address)

    def send_message(self, text: str) -> None:
        self.send_packets(self.message_packetizer, text.encode("utf-8"), self.message_address)

    def enqueue_frame(self, frame: np.ndarray) -> None:
        self.frame_queue.put_latest(frame.copy())

    def enqueue_encoded_image(self, data: bytes) -> None:
        self.send_queue.put_latest(data)

    def _recognition_worker(self) -> None:
        stabilizer = ResultStabilizer(
            self.config.vote_window,
            self.config.vote_minimum,
            self.config.retain_missed_frames,
        )
        while not self.stop_event.is_set():
            try:
                frame = self.frame_queue.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                assert self.pipeline is not None
                raw_results = self.pipeline.predict(frame)
                stable_results = stabilizer.update(raw_results)
                with self.result_lock:
                    self.results = stable_results
                self.send_message(",".join(result.text for result in stable_results))
            except (ValueError, RuntimeError, cv2.error):
                LOG.exception("车牌推理失败")
            except Exception:
                LOG.exception("识别线程出现未预期错误")
            finally:
                self.frame_queue.queue.task_done()

    def _sender_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                data = self.send_queue.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self.send_packets(self.image_packetizer, data, self.image_address)
            finally:
                self.send_queue.queue.task_done()

    def start_workers(self) -> None:
        self.workers = [
            threading.Thread(target=self._recognition_worker, name="plate-recognition", daemon=True),
            threading.Thread(target=self._sender_worker, name="udp-sender", daemon=True),
        ]
        for worker in self.workers:
            worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        for worker in self.workers:
            worker.join(timeout=5.0)
        workers_stopped = all(not worker.is_alive() for worker in self.workers)
        if not workers_stopped:
            LOG.error("工作线程未能及时退出；为避免并发释放，跳过 RKNN 资源回收")
        if self.pipeline is not None and workers_stopped:
            self.pipeline.release()
            self.pipeline = None
        self.socket.close()

    def snapshot_results(self) -> tuple[PlateResult, ...]:
        with self.result_lock:
            return self.results

    def annotate(self, frame: np.ndarray) -> None:
        results = self.snapshot_results()
        for result in results:
            x1, y1, x2, y2 = result.box_xyxy
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
        if not results or self.annotation_font is None:
            return

        # OpenCV's built-in fonts cannot render Chinese. Convert only when
        # there is a stable result and draw UTF-8 plate text with PIL.
        pil_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_frame)
        for result in results:
            x1, y1, _, _ = result.box_xyxy
            text_y = max(0, y1 - 34)
            draw.text(
                (x1, text_y),
                result.text,
                font=self.annotation_font,
                fill=(255, 0, 0),
                stroke_width=1,
                stroke_fill=(255, 255, 255),
            )
        frame[:] = cv2.cvtColor(np.asarray(pil_frame), cv2.COLOR_RGB2BGR)

    def run_video(self) -> int:
        capture = cv2.VideoCapture(self.config.camera_index)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height)
        if not capture.isOpened():
            LOG.error("无法打开摄像头: %s", self.config.camera_index)
            capture.release()
            return 2

        self.start_workers()
        previous = time.monotonic()
        smooth_fps = 0.0
        report_at = previous + 5.0
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality]
        try:
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    LOG.error("无法读取摄像头帧")
                    return 3
                self.enqueue_frame(frame)
                self.annotate(frame)

                now = time.monotonic()
                instant_fps = 1.0 / max(now - previous, 1e-6)
                previous = now
                smooth_fps = 0.9 * smooth_fps + 0.1 * instant_fps
                cv2.putText(
                    frame, f"FPS: {smooth_fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA,
                )
                encoded_ok, encoded = cv2.imencode(".jpg", frame, encode_params)
                if encoded_ok:
                    self.enqueue_encoded_image(encoded.tobytes())

                if now >= report_at:
                    LOG.info(
                        "FPS %.1f，识别队列丢帧 %d，发送队列丢帧 %d",
                        smooth_fps, self.frame_queue.dropped, self.send_queue.dropped,
                    )
                    report_at = now + 5.0
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    return 0
        finally:
            capture.release()
            cv2.destroyAllWindows()

    def run_image(self, path: str) -> int:
        image = cv2.imread(path)
        if image is None:
            LOG.error("无法读取图片: %s", path)
            return 2
        assert self.pipeline is not None
        results = self.pipeline.predict(image)
        with self.result_lock:
            self.results = results

        pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_image)
        font = ImageFont.truetype(self.config.font_path, 30)
        for result in results:
            x1, y1, x2, y2 = result.box_xyxy
            draw.rectangle(((x1, y1), (x2, y2)), outline=(255, 0, 0), width=2)
            draw.text((x1, y2), result.text, font=font, fill=(255, 0, 0))

        width = max(1, int(pil_image.width * self.config.image_scale))
        height = max(1, int(pil_image.height * self.config.image_scale))
        resized = pil_image.resize((width, height), Image.Resampling.LANCZOS)
        output = cv2.cvtColor(np.asarray(resized), cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(
            ".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality]
        )
        if ok:
            self.send_packets(self.image_packetizer, encoded.tobytes(), self.image_address)
        self.send_message(",".join(result.text for result in results))

        if self.config.debug_images:
            debug_dir = Path(self.config.debug_dir)
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_dir / "plate_result.jpg"), output)
        LOG.info("车牌识别结果: %s", ",".join(result.text for result in results) or "未识别")
        return 0

    def run(self) -> int:
        self.pipeline = PlatePipeline(self.config)
        if self.config.input_source == "video":
            return self.run_video()
        return self.run_image(self.config.input_source)


def parse_args() -> AppConfig:
    parser = argparse.ArgumentParser(description="RKNN 车牌识别")
    parser.add_argument("input", nargs="?", default="video", help="图片路径，或 video")
    parser.add_argument("--camera-index", type=int, default=41)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--jpeg-quality", type=int, choices=range(1, 101), default=70)
    parser.add_argument("--image-host", default="127.0.0.1")
    parser.add_argument("--image-port", type=int, default=8088)
    parser.add_argument("--message-host", default="127.0.0.1")
    parser.add_argument("--message-port", type=int, default=8089)
    parser.add_argument("--det-model", default="./model/det.rknn")
    parser.add_argument("--rec-model", default="./model/rec.rknn")
    parser.add_argument("--debug-images", action="store_true")
    parser.add_argument("--debug-dir", default=".")
    args = parser.parse_args()
    return AppConfig(
        input_source=args.input,
        camera_index=args.camera_index,
        camera_width=args.width,
        camera_height=args.height,
        jpeg_quality=args.jpeg_quality,
        image_host=args.image_host,
        image_port=args.image_port,
        message_host=args.message_host,
        message_port=args.message_port,
        det_model=args.det_model,
        rec_model=args.rec_model,
        debug_images=args.debug_images,
        debug_dir=args.debug_dir,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s",
    )
    config = parse_args()
    for model_path in (config.det_model, config.rec_model):
        if not Path(model_path).is_file():
            LOG.error("模型文件不存在: %s", model_path)
            return 2

    application = PlateApplication(config)
    try:
        return application.run()
    except KeyboardInterrupt:
        LOG.info("收到退出信号")
        return 0
    finally:
        application.stop()


if __name__ == "__main__":
    raise SystemExit(main())
