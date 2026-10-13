# config.py

# 定义电压的最小值（无烟雾时约0.1-0.3V）
VOLTAGE_MIN = 0.1

# 定义电压的最大值（工作电压5V，高浓度时接近5V）
VOLTAGE_MAX = 5.0

# 定义烟雾浓度的最小值 (ppm)
SMOKE_CONC_MIN = 300

# 定义烟雾浓度的最大值 (ppm)
# 传感器检测范围：300-10000 ppm
SMOKE_CONC_MAX = 10000

# 定义烟雾传感器放大倍数（用于缩放到合适范围）
SMOKE_GAIN = 1

# 无烟雾时的基准电压（用于零点校准）
# 根据实际传感器测量值调整，不同传感器/环境可能不同
VOLTAGE_BASELINE = 0.6
