#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 光照数据采集练习。

# ==================== 01 程序依赖 ====================
from pathlib import Path

# 导入时不加载.so或连接设备，Windows也可使用 --check 检查配置和文件。
from light_teaching_support import launch


# ==================== 02 用户设置 ====================
# >>>>>>>>>>>>>>>>>>>> TODO 1：基础信息 >>>>>>>>>>>>>>>>>>>>
# 将任务编号设置为“10”，任务名称设置为“光照传感器识别”。
experiment_info = {
    "任务编号": "任务xx",
    "任务名称": "实验10",
}
# <<<<<<<<<<<<<<<<<<<< TODO 1：结束 <<<<<<<<<<<<<<<<<<<<<<

# >>>>>>>>>>>>>>>>>>>> TODO 2：参数设置 >>>>>>>>>>>>>>>>>>>>
# 将光照目标值修改为100 lx，监测间隔修改为5秒/次。
LIGHT_TARGET_VALUE = 50  # 光照目标值，单位lx。
SLEEP_TIME = 1           # 监测间隔，秒/次。
# <<<<<<<<<<<<<<<<<<<< TODO 2：结束 <<<<<<<<<<<<<<<<<<<<<<


# ==================== 03 系统配置 ====================
# 通常无需修改。模块编号和引脚沿用现有Demo，按实训箱实际连接核对。
# 实际I2C协议沿用旧LightSensor_OPT3001_Demo1.py的BH170Sensor实现。
# 不根据文件名将地址改为0x44，否则与当前原厂模块协议不一致。
ROOT = Path(__file__).resolve().parent
LIGHT_MODULE_INDEX = 10
SCL_PIN = 22
SDA_PIN = 23
I2C_ADDRESS = 0x23
I2C_FREQUENCY = 100000
SAMPLE_COUNT = 10      # 采集次数。
SCAN_WAIT = 2.0
SENSOR_SETTLE_TIME = 0.2
SENSOR_LIB = ROOT / 'libSmartSensorDriver.so'
DATA_PATH = ROOT / 'student_data/student_data.json'
UDP_DEST_ADDR = ('127.0.0.1', 8088)
ENABLE_UDP = True


# ==================== 04 配置采集 ====================
def teaching_config():
    return {key: globals()[key] for key in (
        'SLEEP_TIME', 'LIGHT_TARGET_VALUE', 'SAMPLE_COUNT', 'LIGHT_MODULE_INDEX',
        'SCL_PIN', 'SDA_PIN', 'I2C_ADDRESS', 'I2C_FREQUENCY',
        'SCAN_WAIT', 'SENSOR_SETTLE_TIME', 'SENSOR_LIB',
        'DATA_PATH', 'UDP_DEST_ADDR', 'ENABLE_UDP')}


# ==================== 05 程序入口 ====================
# 运行：python3 BRICS2026_Final_Sample_Light.py
# 静态检查：python3 BRICS2026_Final_Sample_Light.py --check（不连接硬件、不生成成果）。
# 一次只运行一个入口，退出其他占用光照模块的程序。
# 成果：当前设备用户桌面/成果输出/任务编号/任务名称/，保存CSV与本次实际入口源码。
def main(argv=None):
    return launch(experiment_info, teaching_config(), __file__, argv, description='光照数据采集练习')


if __name__ == '__main__':
    raise SystemExit(main())
