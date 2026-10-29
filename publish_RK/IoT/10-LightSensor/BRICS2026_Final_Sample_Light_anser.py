#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# V5 参考答案版：已按题面设置实验信息和采集参数，考试编号请填写本人实际考号。

# ==================== 01 程序依赖 ====================
from pathlib import Path

# 导入时不加载.so或连接设备，Windows也可使用 --check 检查配置和文件。
from light_teaching_support import launch


# ==================== 02 用户设置 ====================
# ==================== 考试任务：施工通道照明监测 ====================
# 某施工项目拟根据施工通道的光照变化自动开启照明灯。正式接入照明控制前，
# 项目部将本次工作定名为“通道照明监测”，选取“施工通道01”开展光照采集与判别调试。
#
# 本次调试约定：每2秒采集一次光照强度；照度低于100 lx时，标记“照度不足”；
# 照度达到或超过100 lx时，正常记录，为后续自动照明提供判断依据。
# 100 lx仅为本次模拟调试阈值。
#
# 现由你使用实训箱中的光照传感器完成模拟调试，依据上述安排配置程序，连续采集10次，
# 通过遮挡与补光检查光照数据及照度不足标记。记录应包含采集时间、监测点位、光照强度及判别结果，
# 并提交本次调试的程序源码和CSV数据记录文件。
# ====================================================
# TODO：阅读与题面一致的实验信息、光照目标值及监测间隔，并填写本人考号。
# 与温度监测任务相同，判别与记录由系统完成，其他参数和程序逻辑无需修改。
# 先保存再运行，运行过程中不要编辑代码；采集10次后自动结束。

experiment_info = {
    "考试编号": "考号",
    "项目名称": "通道照明监测",
    "监测点位": "施工通道01",
}

LIGHT_TARGET_VALUE = 100  # 光照目标值，单位lx。
SLEEP_TIME = 2            # 监测间隔，秒/次。


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
SAMPLE_COUNT = 10      # 本次固定采集10次，不作为学生编程考点。
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
# 运行：python3 BRICS2026_Final_Sample_Light_anser.py
# 静态检查：python3 BRICS2026_Final_Sample_Light_anser.py --check（不连接硬件、不生成成果）。
# 一次只运行一个入口，退出其他占用光照模块的程序。
# 成果：当前设备用户桌面/成果输出/考试编号/项目名称/，保存CSV与本次实际入口源码。
def main(argv=None):
    return launch(experiment_info, teaching_config(), __file__, argv)


if __name__ == '__main__':
    raise SystemExit(main())
