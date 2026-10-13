# 摄像头视野对比：在 hat 目录运行 python3 hat9.py，按 Ctrl+C 提前停止。
# 保持镜头位置、角度、焦距和场景不变，比较不同模式下四周能看到哪些物体。
# 本程序不运行AI、不裁切、不放大；分辨率更高不代表视野一定更大。
# 原始PNG及测试记录保存到本文件同目录的 camera_view_tests 下。

# ==================== 01 导入与用户设置 ====================
import argparse
import csv
from datetime import datetime
import logging
from pathlib import Path
import socket
import struct
import time

import cv2

CAMERA_INDEX = 41
TEST_MODES = [(640, 480), (800, 600), (1280, 720), (1920, 1080)]
SECONDS_PER_MODE = 8
WARMUP_FRAMES = 5
USE_MJPEG = True
PREVIEW_LONG_EDGE = 720
JPEG_QUALITY = 60
PREVIEW_FPS_LIMIT = 15
UDP_DESTINATION = ('127.0.0.1', 8088)
UDP_CHUNK_SIZE = 60000
CSV_FIELDS = ['请求尺寸', '实际尺寸', '模式状态', '原图文件', '采集帧数', '测试时长(秒)', '错误信息']


# ==================== 02 原比例预览与原协议发送 ====================
def resize_preview(frame):
    height, width = frame.shape[:2]
    ratio = min(1.0, PREVIEW_LONG_EDGE / max(width, height))
    size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    if size == (width, height):
        return frame.copy()
    return cv2.resize(frame, size, interpolation=cv2.INTER_LINEAR)


def send_preview(sock, payload, group_id):
    data = memoryview(payload).cast('B')
    count = (len(data) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE
    for index in range(count):
        chunk = data[index * UDP_CHUNK_SIZE:(index + 1) * UDP_CHUNK_SIZE]
        header = struct.pack('<IIII', group_id, count, index, len(chunk))
        sock.sendto(header + chunk.tobytes(), UDP_DESTINATION)


# ==================== 03 单模式测试 ====================
def test_mode(camera_index, width, height, seconds, output_dir, sock, group_id):
    requested = f'{width}x{height}'
    record = dict(zip(CSV_FIELDS, [requested, '', '无法采集', '', 0, 0, '']))
    cap = None
    started = None
    failure_messages = []
    logging.info('Testing requested mode %s; keep camera and scene fixed', requested)
    try:
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError('Cannot open camera')
        if USE_MJPEG:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        frame = None
        for _ in range(WARMUP_FRAMES):
            ok, candidate = cap.read()
            if ok and candidate is not None and candidate.size > 0:
                frame = candidate
        if frame is None:
            raise RuntimeError('No valid camera frame in this mode')
        actual_height, actual_width = frame.shape[:2]
        actual = f'{actual_width}x{actual_height}'
        record['实际尺寸'] = actual
        record['模式状态'] = '尺寸匹配' if (actual_width, actual_height) == (width, height) else '设备替代尺寸'
        logging.info('Requested %s, actual %s: %s', requested, actual, record['模式状态'])
        snapshot = output_dir / f'request_{requested}_actual_{actual}.png'
        # 在绘字前保存原始图像，真实尺寸不受预览缩放和接收端显示方式影响。
        try:
            if not cv2.imwrite(str(snapshot), frame):
                raise OSError('PNG write returned false')
            record['原图文件'] = snapshot.name
        except Exception as exc:
            failure_messages.append(f'Snapshot save failed: {exc}')
            logging.exception('Could not save raw snapshot')
        started = time.monotonic()
        next_send = started
        network_warning = False
        while time.monotonic() - started < seconds:
            if frame is None:
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError('Camera stream stopped')
            if frame.shape[:2] != (actual_height, actual_width):
                raise RuntimeError('Frame dimensions changed during test')
            record['采集帧数'] += 1
            now = time.monotonic()
            if now >= next_send:
                next_send = now + 1 / PREVIEW_FPS_LIMIT
                preview = resize_preview(frame)
                remaining = max(0, seconds - (now - started))
                cv2.putText(preview, f'REQ:{requested} ACT:{actual}', (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
                cv2.putText(preview, f'VIEW TEST / NO AI  {remaining:.1f}s', (10, 56),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
                ok, encoded = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if not ok:
                    raise RuntimeError('Preview JPEG encoding failed')
                group_id = (group_id + 1) & 0xffffffff
                try:
                    send_preview(sock, encoded, group_id)
                except OSError as exc:
                    if not network_warning:
                        failure_messages.append(f'UDP preview failed: {exc}')
                        logging.warning('UDP preview failed; raw image test continues: %s', exc)
                        network_warning = True
            frame = None
    except KeyboardInterrupt:
        record['模式状态'] = '用户停止'
        raise
    except Exception as exc:
        record['模式状态'] = '测试失败'
        failure_messages.append(str(exc))
        logging.warning('Mode %s failed: %s', requested, exc)
    finally:
        if started is not None:
            record['测试时长(秒)'] = round(time.monotonic() - started, 3)
        record['错误信息'] = '; '.join(failure_messages)
        try:
            if cap is not None:
                cap.release()
        finally:
            # 每次模式结束立即落盘，提前停止时也保留已完成结果。
            with (output_dir / 'mode_results.csv').open('a', encoding='utf-8-sig', newline='') as output:
                csv.DictWriter(output, fieldnames=CSV_FIELDS).writerow(record)
    return group_id


# ==================== 04 程序入口 ====================
def main():
    parser = argparse.ArgumentParser(description='Compare camera field of view across capture modes; no AI inference')
    parser.add_argument('--camera', type=int, default=CAMERA_INDEX)
    parser.add_argument('--seconds', type=float, default=SECONDS_PER_MODE)
    args = parser.parse_args()
    if not 0 < args.seconds < float('inf'):
        parser.error('--seconds must be finite and positive')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    cv2.setNumThreads(1)
    output_dir = Path(__file__).resolve().parent / 'camera_view_tests' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / 'mode_results.csv').open('w', encoding='utf-8-sig', newline='') as output:
        csv.DictWriter(output, fieldnames=CSV_FIELDS).writeheader()
    logging.info('Results directory: %s', output_dir)
    logging.info('Stop other camera programs before testing; keep position, angle and focus unchanged')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            group_id = 0
            for width, height in TEST_MODES:
                group_id = test_mode(args.camera, width, height, args.seconds, output_dir, sock, group_id)
    except KeyboardInterrupt:
        logging.info('Test stopped; completed images and records preserved')
    logging.info('Compare objects at the image edges in the raw PNGs; matching dimensions do not prove native sensor resolution')


if __name__ == '__main__':
    main()
