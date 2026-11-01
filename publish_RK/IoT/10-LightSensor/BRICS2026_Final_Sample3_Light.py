#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 光照与RGB灯色联动演示。

# ==================== 01 程序依赖 ====================
from pathlib import Path

from light_rgb_support import launch


# ==================== 02 系统设置 ====================
ROOT = Path(__file__).resolve().parent

experiment_info = {
    '考试编号': '演示',
    '项目名称': '光感灯色联动',
    '监测点位': '演示点01',
}

LOW_LIGHT_LUX = 80
HIGH_LIGHT_LUX = 300
SLEEP_TIME = 1
SAMPLE_COUNT = 0  # 0持续运行，Ctrl+C停止。

LIGHT_MODULE_INDEX = 10
LED_MODULE_INDEX = 1
LED_PINS = (23, 25, 22)  # 红、绿、蓝。
LED_ON_LEVEL = 1
SCL_PIN = 22
SDA_PIN = 23
I2C_ADDRESS = 0x23
I2C_FREQUENCY = 100000
SCAN_WAIT = 2.0
SENSOR_SETTLE_TIME = 0.2
SENSOR_LIB = ROOT / 'libSmartSensorDriver.so'
DATA_PATH = ROOT / 'student_data/student_data.json'
UDP_DEST_ADDR = ('127.0.0.1', 8088)
ENABLE_UDP = True


# ==================== 03 配置读取 ====================
def system_config():
    config = {key: globals()[key] for key in (
        'LOW_LIGHT_LUX', 'HIGH_LIGHT_LUX', 'SLEEP_TIME', 'SAMPLE_COUNT',
        'LIGHT_MODULE_INDEX', 'LED_MODULE_INDEX', 'LED_PINS', 'LED_ON_LEVEL',
        'SCL_PIN', 'SDA_PIN', 'I2C_ADDRESS', 'I2C_FREQUENCY', 'SCAN_WAIT',
        'SENSOR_SETTLE_TIME', 'SENSOR_LIB', 'DATA_PATH', 'UDP_DEST_ADDR', 'ENABLE_UDP')}
    config['LIGHT_TARGET_VALUE'] = LOW_LIGHT_LUX  # 原光照回传接口。
    return config


# ==================== 04 程序入口 ====================
# 运行：python3 BRICS2026_Final_Sample3_Light.py
def main(argv=None):
    return launch(experiment_info, system_config(), __file__, argv)


if __name__ == '__main__':
    raise SystemExit(main())
