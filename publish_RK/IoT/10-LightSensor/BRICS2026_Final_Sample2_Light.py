#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 光照数据采集演示。

# ==================== 01 程序依赖 ====================
from pathlib import Path

from light_teaching_support import launch


# ==================== 02 系统设置 ====================
ROOT = Path(__file__).resolve().parent

experiment_info = {
    '考试编号': '演示',
    '项目名称': '光照采集',
    '监测点位': '演示点01',
}

LIGHT_TARGET_VALUE = 50
SLEEP_TIME = 1
SAMPLE_COUNT = 10

LIGHT_MODULE_INDEX = 10
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
def teaching_config():
    return {key: globals()[key] for key in (
        'SLEEP_TIME', 'LIGHT_TARGET_VALUE', 'SAMPLE_COUNT', 'LIGHT_MODULE_INDEX',
        'SCL_PIN', 'SDA_PIN', 'I2C_ADDRESS', 'I2C_FREQUENCY',
        'SCAN_WAIT', 'SENSOR_SETTLE_TIME', 'SENSOR_LIB',
        'DATA_PATH', 'UDP_DEST_ADDR', 'ENABLE_UDP')}


# ==================== 04 程序入口 ====================
# 运行：python3 BRICS2026_Final_Sample2_Light.py
def main(argv=None):
    return launch(experiment_info, teaching_config(), __file__, argv, description='光照数据采集演示')


if __name__ == '__main__':
    raise SystemExit(main())
