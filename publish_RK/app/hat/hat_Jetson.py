#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全帽检测与蜂鸣器控制实验
当检测到安全帽时，蜂鸣器会响起
"""

import argparse
import cv2
import os
from pathlib import Path
import glob
import shutil
import torch
import time
import torchvision
import random
import numpy as np
import socket
import math
import json

# GPIO控制模块
try:
    import Jetson.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("警告: Jetson.GPIO模块未找到，蜂鸣器功能将被禁用")
    GPIO_AVAILABLE = False

# 导入UDP通信模块
try:
    from UdpPackage import *
except ImportError:
    print("警告: UdpPackage模块未找到，UDP通信功能将被禁用")
    UDP_AVAILABLE = False
else:
    UDP_AVAILABLE = True

# 设备配置
device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

# GPIO引脚配置
ACTIVE_BUZZER = 31  # J41_BOARD_PIN16

# LED RGB引脚配置
LEDR = 13  # J41_BOARD_PIN13 红色LED
LEDG = 15  # J41_BOARD_PIN15 绿色LED
LEDB = 18  # J41_BOARD_PIN18 蓝色LED

# 蜂鸣器控制开关配置
BUZZER_ENABLED = False  # 蜂鸣器启用开关，默认为False（不启用）

# LED控制开关配置
LED_ENABLED = False  # LED启用开关，默认为False（不启用）

# UDP通信配置
dest_addr = ('127.0.0.1', 8088)
dest_addr2 = ('127.0.0.1', 8089)
if UDP_AVAILABLE:
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

max_packet_size = 60000
max_packet_size2 = 5
global_id = 0
global_id2 = 0

# 蜂鸣器控制函数
def init_buzzer():
    """初始化蜂鸣器GPIO"""
    if GPIO_AVAILABLE:
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(ACTIVE_BUZZER, GPIO.OUT, initial=GPIO.LOW)
        print("蜂鸣器初始化完成")
    else:
        print("GPIO不可用，蜂鸣器功能禁用")

# LED控制函数
def init_led():
    """初始化LED RGB GPIO"""
    if GPIO_AVAILABLE:
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(LEDR, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(LEDG, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(LEDB, GPIO.OUT, initial=GPIO.LOW)
        print("LED RGB初始化完成")
    else:
        print("GPIO不可用，LED功能禁用")

def led_off():
    """关闭所有LED"""
    if GPIO_AVAILABLE and LED_ENABLED:
        GPIO.output(LEDR, GPIO.LOW)
        GPIO.output(LEDG, GPIO.LOW)
        GPIO.output(LEDB, GPIO.LOW)
        print("LED已关闭")
    elif not LED_ENABLED:
        print("LED已禁用，跳过关闭操作")

def led_red():
    """设置LED为红色（检测到head时使用）"""
    if GPIO_AVAILABLE and LED_ENABLED:
        GPIO.output(LEDR, GPIO.HIGH)
        GPIO.output(LEDG, GPIO.LOW)
        GPIO.output(LEDB, GPIO.LOW)
        print("LED设置为红色 - 检测到头部")
    elif not LED_ENABLED:
        print("LED已禁用，跳过红色设置")

def led_green():
    """设置LED为绿色（检测到hat时使用）"""
    if GPIO_AVAILABLE and LED_ENABLED:
        GPIO.output(LEDR, GPIO.LOW)
        GPIO.output(LEDG, GPIO.HIGH)
        GPIO.output(LEDB, GPIO.LOW)
        print("LED设置为绿色 - 检测到安全帽")
    elif not LED_ENABLED:
        print("LED已禁用，跳过绿色设置")

def set_led_enabled(enabled):
    """设置LED启用状态
    
    Args:
        enabled (bool): True为启用LED，False为禁用LED
    """
    global LED_ENABLED
    LED_ENABLED = enabled
    status = "启用" if enabled else "禁用"
    print(f"LED已{status}")
    if not enabled:
        led_off()  # 禁用时关闭所有LED

def get_led_status():
    """获取当前LED启用状态
    
    Returns:
        bool: True表示启用，False表示禁用
    """
    return LED_ENABLED

def buzzer_on():
    """打开蜂鸣器"""
    if GPIO_AVAILABLE and BUZZER_ENABLED:  # 检查GPIO可用性和蜂鸣器启用状态
        GPIO.output(ACTIVE_BUZZER, GPIO.HIGH)
        print("蜂鸣器响起")
    elif not BUZZER_ENABLED:
        print("蜂鸣器已禁用，不会响起")

def buzzer_off():
    """关闭蜂鸣器"""
    if GPIO_AVAILABLE and BUZZER_ENABLED:  # 检查GPIO可用性和蜂鸣器启用状态
        GPIO.output(ACTIVE_BUZZER, GPIO.LOW)
        print("蜂鸣器关闭")

def buzzer_beep_twice():
    """蜂鸣器发出两声短鸣叫"""
    if not BUZZER_ENABLED:
        print("蜂鸣器已禁用，跳过鸣叫")
        return
        
    if GPIO_AVAILABLE:
        for i in range(2):
            buzzer_on()
            time.sleep(0.2)  # 短鸣0.2秒
            buzzer_off()
            if i < 1:  # 两声之间的间隔
                time.sleep(0.1)
        print("蜂鸣器发出两声短鸣叫")

def set_buzzer_enabled(enabled):
    """设置蜂鸣器启用状态
    
    Args:
        enabled (bool): True为启用蜂鸣器，False为禁用蜂鸣器
    """
    global BUZZER_ENABLED
    BUZZER_ENABLED = enabled
    status = "启用" if enabled else "禁用"
    print(f"蜂鸣器已{status}")

def get_buzzer_status():
    """获取当前蜂鸣器启用状态
    
    Returns:
        bool: True表示启用，False表示禁用
    """
    return BUZZER_ENABLED

def cleanup_gpio():
    """清理GPIO资源"""
    if GPIO_AVAILABLE:
        # 清理前先关闭所有LED
        if LED_ENABLED:
            led_off()
        GPIO.cleanup()
        print("GPIO资源已清理")

# UDP通信函数
def getUdpPackages(bytes_data):
    global global_id
    global_id += 1
    packets = []
    length = len(bytes_data)
    num_packets = math.ceil(length / max_packet_size)
    for i in range(num_packets):
        start = i * max_packet_size
        end = min(start + max_packet_size, len(bytes_data))
        packet = UdpPackage(global_id, num_packets, i, end - start, bytes_data[start:end])
        packets.append(packet)
    return packets

def send_msginfo(msginfo_bytes):
    if UDP_AVAILABLE:
        packets = getUdpPackages(msginfo_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr2)

def send(img_bytes):
    if UDP_AVAILABLE:
        packets = getUdpPackages(img_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr)

def image_to_byte_array(image_path):
    with open(image_path, 'rb') as image_file:
        image_data = image_file.read()
    return image_data

# 图像处理函数
def clip_coords(boxes, img_shape):
    boxes[:, 0].clamp_(0, img_shape[1])  # x1
    boxes[:, 1].clamp_(0, img_shape[0])  # y1
    boxes[:, 2].clamp_(0, img_shape[1])  # x2
    boxes[:, 3].clamp_(0, img_shape[0])  # y2

def scale_coords(img1_shape, coords, img0_shape, ratio_pad=None):
    if ratio_pad is None:
        gain = max(img1_shape) / max(img0_shape)
        pad = (img1_shape[1] - img0_shape[1] * gain) / 2, (img1_shape[0] - img0_shape[0] * gain) / 2
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    coords[:, [0, 2]] -= pad[0]
    coords[:, [1, 3]] -= pad[1]
    coords[:, :4] /= gain
    clip_coords(coords, img0_shape)
    return coords

def letterbox2(img, new_shape=(640, 640), color=(114, 114, 114), auto=True, scaleFill=False, scaleup=True):
    shape = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:
        r = min(r, 1.0)

    ratio = r, r
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    if auto:
        dw, dh = np.mod(dw, 64), np.mod(dh, 64)
    elif scaleFill:
        dw, dh = 0.0, 0.0
        new_unpad = new_shape
        ratio = new_shape[0] / shape[1], new_shape[1] / shape[0]

    dw /= 2
    dh /= 2

    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, ratio, (dw, dh)

def xywh2xyxy(x):
    y = torch.zeros_like(x) if isinstance(x, torch.Tensor) else np.zeros_like(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y

def non_max_suppression(prediction, conf_thres=0.1, iou_thres=0.6, merge=False, classes=None, agnostic=False):
    """简化的NMS实现"""
    nc = prediction[0].shape[1] - 5
    xc = prediction[..., 4] > conf_thres
    
    output = [None] * prediction.shape[0]
    for xi, x in enumerate(prediction):
        x = x[xc[xi]]
        if not x.shape[0]:
            continue
            
        x[:, 5:] *= x[:, 4:5]
        box = xywh2xyxy(x[:, :4])
        
        conf, j = x[:, 5:].max(1, keepdim=True)
        x = torch.cat((box, conf, j.float()), 1)[conf.view(-1) > conf_thres]
        
        if not x.shape[0]:
            continue
            
        c = x[:, 5:6] * (0 if agnostic else 4096)
        boxes, scores = x[:, :4] + c, x[:, 4]
        i = torchvision.ops.nms(boxes, scores, iou_thres)
        output[xi] = x[i]
        
    return output

def plot_one_box(x, img, color=None, label=None, line_thickness=None):
    tl = line_thickness or round(0.002 * (img.shape[0] + img.shape[1]) / 2) + 1
    color = color or [random.randint(0, 255) for _ in range(3)]
    c1, c2 = (int(x[0]), int(x[1])), (int(x[2]), int(x[3]))
    cv2.rectangle(img, c1, c2, color, thickness=tl, lineType=cv2.LINE_AA)
    if label:
        tf = max(tl - 1, 1)
        t_size = cv2.getTextSize(label, 0, fontScale=tl / 3, thickness=tf)[0]
        c2 = c1[0] + t_size[0], c1[1] - t_size[1] - 3
        cv2.rectangle(img, c1, c2, color, -1, cv2.LINE_AA)
        cv2.putText(img, label, (c1[0], c1[1] - 2), 0, tl / 3, [225, 255, 255], thickness=tf, lineType=cv2.LINE_AA)

# 安全帽检测函数
def detect_hat(img0, model):
    """检测安全帽"""
    img = letterbox2(img0, new_shape=640)[0]
    img = img[:, :, ::-1].transpose(2, 0, 1)
    img = np.ascontiguousarray(img)
    
    img = torch.from_numpy(img).to(device)
    img = img.half() if device.type != 'cpu' else img.float()
    img /= 255.0
    if img.ndimension() == 3:
        img = img.unsqueeze(0)
    
    t0 = time.time()
    pred = model(img, augment=False)[0]
    print('检测耗时: (%.3fs)' % (time.time() - t0))
    
    conf_thres = 0.5
    iou_thres = 0.5
    
    pred = non_max_suppression(pred, conf_thres, iou_thres)
    
    results = []
    for i, det in enumerate(pred):
        if det is not None and len(det):
            det[:, :4] = scale_coords(img.shape[2:], det[:, :4], img0.shape).round()
            results.append(det)
    
    return results

def main():
    """主函数"""
    # 初始化蜂鸣器和LED
    init_buzzer()
    init_led()
    
    # 加载模型
    weights_path = os.path.join(os.path.dirname(__file__), 'hat_v1.2.pt')
    if not os.path.exists(weights_path):
        print(f"模型文件未找到: {weights_path}")
        print("请确保模型文件存在")
        return
    
    try:
        model = torch.load(weights_path, map_location=device)['model']
        model.to(device).eval()
        if device.type != 'cpu':
            model.half()
        print("模型加载成功")
    except Exception as e:
        print(f"模型加载失败: {e}")
        return
    
    # 类别名称和颜色
    names = ['hat', 'head', 'black']
    colors = [[255, 0, 0], [255, 180, 0], [0, 0, 0]]
    
    # 打开摄像头
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print('无法打开摄像头!')
        return
    
    print("开始检测...")
    print("按Ctrl+C退出")
    print(f"蜂鸣器状态: {'启用' if get_buzzer_status() else '禁用'}")
    print(f"LED状态: {'启用' if get_led_status() else '禁用'}")
    print("提示: 可以通过调用 set_buzzer_enabled(True) 启用蜂鸣器")
    print("提示: 可以通过调用 set_led_enabled(True) 启用LED")
    print("LED显示规则: 红色=检测到头部, 绿色=检测到安全帽")
    
    last_detection_time = 0
    detection_interval = 5.0  # 5秒检测间隔
    
    try:
        while True:
            ret, img0 = cap.read()
            if not ret:
                print('获取帧失败')
                break
            
            # 检测安全帽
            results = detect_hat(img0, model)
            
            hat_count = 0
            head_count = 0
            no_hat_detected = False
            
            # 处理检测结果
            for det in results:
                for *xyxy, conf, cls in det:
                    label = '%s %.2f' % (names[int(cls)], conf)
                    plot_one_box(xyxy, img0, label=label, color=colors[int(cls)], line_thickness=2)
                    
                    if int(cls) == 0:  # hat类别
                        hat_count += 1
                    elif int(cls) == 1:  # head类别
                        head_count += 1
            
            # 检测逻辑：有头部但没有安全帽时触发警报
            if head_count > 0 and hat_count == 0:
                no_hat_detected = True
            
            # LED控制逻辑
            if LED_ENABLED:
                if hat_count > 0:
                    # 检测到安全帽，显示绿色
                    led_green()
                elif head_count > 0:
                    # 检测到头部但没有安全帽，显示红色
                    led_red()
                else:
                    # 没有检测到任何目标，关闭LED
                    led_off()
            
            # 蜂鸣器控制逻辑（5秒间隔）
            current_time = time.time()
            
            if no_hat_detected and (current_time - last_detection_time) >= detection_interval:
                # 检测到未佩戴安全帽且超过间隔时间，发出两声短鸣叫
                buzzer_beep_twice()
                last_detection_time = current_time
                print(f"警告：检测到未佩戴安全帽！头部数量: {head_count}, 安全帽数量: {hat_count}")
            
            # 在图像上显示检测信息（用于调试，但不显示窗口）
            info_text = f"Hat: {hat_count}, Head: {head_count}"
            cv2.putText(img0, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            if no_hat_detected:
                cv2.putText(img0, "NO HAT DETECTED!", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            # 发送UDP消息（如果可用）
            if UDP_AVAILABLE:
                # 保存临时图像
                temp_img_path = 'temp_detection.jpg'
                cv2.imwrite(temp_img_path, img0)
                
                # 发送检测信息
                send_msginfo(bytes(str(hat_count) + ',' + str(head_count), encoding='utf-8'))
                
                # 发送图像
                send(image_to_byte_array(temp_img_path))
                
                # 删除临时文件
                if os.path.exists(temp_img_path):
                    os.remove(temp_img_path)
            
            # 不显示视频窗口，只在后台运行检测
            # 可以通过Ctrl+C退出程序
                
    except KeyboardInterrupt:
        print("\n检测到Ctrl+C，正在退出...")
    
    finally:
        # 清理资源
        if buzzer_active:
            buzzer_off()
        cleanup_gpio()
        cap.release()
        cv2.destroyAllWindows()
        print("程序已退出")

if __name__ == '__main__':
    main()