# 温湿度传感器标准实训

标准入口为 [TemperatureHumiditySensor_standard.py](TemperatureHumiditySensor_standard.py)。它沿用 Demo10 的 AHT20 采集参数及 JSON/UDP 协议，增加实验信息、配置检查、完整 CSV、同次源码归档和退出清理。原有 Demo 与赛事入口保留。

## 开始实验

在 RK3588 Linux 板端本模块目录运行，需要 Python 3 和同目录 `libSmartSensorDriver.so`；标准入口直接调用驱动，无需导入原厂 Python 封装。默认模块地址9，I²C地址 `0x38`，SCL/SDA为22/23，速率100000 Hz，地址长度参数7。实际设备与接线需现场核对。

```bash
python3 TemperatureHumiditySensor_standard.py --help
python3 TemperatureHumiditySensor_standard.py --check
python3 TemperatureHumiditySensor_standard.py
python3 TemperatureHumiditySensor_standard.py --module 9 --output-root ./成果输出
```

填写顶部 `experiment_info` 中的考试编号、项目名称和项目位置，将 `sleep_time` 从默认1秒改为任务要求的2秒；温度目标 `degrees_sensor_target_value`、湿度目标 `humidity_sensor_target_value` 按教师任务填写。目标默认均为0，仅记录和上报，不控制报警。湿度目标须为0～100 %RH，温度目标允许负数，所有数值须有限，采集间隔须为正数。

观察至少10次有效采样后按 Ctrl+C 结束。间隔从每轮采集开始计时，包含测量、写盘和上报耗时；测量本身保留原厂1秒等待，实际周期可能超过设置值。

## 数据与成果

CSV 默认保存到当前运行用户桌面的 `成果输出/考试编号/项目名称/`，文件名含微秒时间戳；同名 `.py` 是本次运行入口源码。`--output-root`（别名 `--output-dir`）替换“桌面/成果输出”根目录。归档源码运行时仍需配套动态库。

CSV包含实验信息，以及 `记录时间、实验累计毫秒、采样序号、模块编号、温度(°C)、湿度(%RH)、温度目标(°C)、湿度目标(%RH)、采集间隔(秒)、记录类型、结果、错误信息`。每次有效采样一行；初始化、停止、运行异常、上报异常和资源清理另记事件行。事件行测量字段为空，数值0可以是有效测量；采样序号表示尝试次数，事件行沿用当前序号。累计毫秒从创建记录器开始计算。文本字段以公式字符开头时添加单引号。

温度由20位原始值换算为 `raw / 1048576 * 200 - 50` °C，湿度为 `raw / 1048576 * 100` %RH，CSV与JSON均保留两位小数。

`student_data/student_data.json` 保留最近5条兼容记录，不是完整实验历史。名称沿用 `TempHumitySensor`；`Answer` 包含 `degrees_value`、`humidity_value`，`Target_Value` 的键沿用带空格的 `degrees value`、`humidity value`。每次保存后将相同历史列表发送到 `127.0.0.1:8088`，包头为四个小端无符号32位整数：组号、总包数、包序号、数据长度，每包数据不超过1000字节。

成功采样时三个状态均为1；结束或失败时发送零值与状态0，表示本次采集停止，不能将零值解释为实测值，也不能据此断言设备物理掉线。UDP发送成功不证明接收端已收到。

## 异常与验收

程序等待扫描2秒后检查在线状态并连接。初始化失败、I²C读写返回负数、返回忙状态或测量无效时记录错误并停止，不以零值填充成功采样。程序不自动重连；排查后重新运行。JSON/UDP上报失败记录事件并继续采集，但最终返回非零退出码。

退出时依次尝试释放I²C、断开模块、注销驱动和关闭UDP；单项失败仍继续后续清理。Ctrl+C和SIGTERM均进入清理流程。运行、记录、上报或清理失败返回非零退出码。

验收时核对实验信息、参数、至少10行成功采样、现场温湿度变化、JSON双值字段和接收端显示，再核对停止与清理记录，提交同次CSV、归档源码和现场观察记录。

`--check` 只检查配置、动态库文件存在及入口语法，不加载驱动。I²C返回值沿用原厂“负数失败”的判定，未核验返回字节数、CRC或校准状态；动态库兼容性、硬件时序、实测精度和UDP接收均需板端验证。
