# 空气质量传感器标准实训

标准入口为 [AirQualitySensor_standard.py](AirQualitySensor_standard.py)，原厂入口 [AirQualitySensor_Demo1.py](AirQualitySensor_Demo1.py) 保留。标准入口增加实验信息、配置检查、完整 CSV、同次源码归档和退出清理，并沿用原厂 JSON/UDP 字段。

## 开始实验

在 RK3588 Linux 板端的本模块目录运行，需要 Python 3、本目录配套 Python 文件和 `libSmartSensorDriver.so`。模块地址14，串口通道2，TX/RX为22/23，原厂封装配置为9600、8N1。实际接线以实训台为准。

```bash
python3 AirQualitySensor_standard.py --help
python3 AirQualitySensor_standard.py --check
python3 AirQualitySensor_standard.py
# 指定成果根目录
python3 AirQualitySensor_standard.py --output-root ./成果输出
```

先填写入口顶部 `experiment_info`，按任务修改 `SLEEP_TIME` 和三个 `*_TARGET_VALUE`。默认间隔1秒，任务要求改为2秒；目标值默认0，仅记录和上报，不触发报警。观察至少10次有效采样后按 Ctrl+C 结束。间隔是每次采集结束后的等待时间，串口读取和上报会增加实际采样周期。

## 数据与成果

PM2.5、PM10 沿用原厂回包偏移6～9的无符号大端整数。TSP 为 `round(PM10 * 1.2, 1)`，属于估算值，不是第三路独立实测。原厂源码未给出量程、单位及完整帧协议，现场应根据传感器铭牌/手册核对，不据此判定空气质量等级或健康风险。

CSV 默认保存到当前运行用户桌面的 `成果输出/考试编号/项目名称/`，文件名含微秒时间戳；同名 `.py` 为本次运行入口源码。`--output-root` 替换“桌面/成果输出”根目录。提交同次 CSV 和 `.py`，配套驱动仍使用本目录文件。

CSV 包含实验信息，以及 `记录时间、采样序号、模块编号、PM2.5、PM10、TSP估算值、PM2.5目标、PM10目标、TSP目标、采集间隔(秒)、记录类型、结果、错误信息`。每次有效采样一行，初始化、停止、运行异常、上报失败和清理失败另记事件行。事件行的测量字段为空；0是有效数值，不代表读取失败。采样序号表示尝试次数。文本字段以公式字符开头时加单引号，便于表格软件安全查看。

`student_data/student_data.json` 仅保留最近5条，UDP按原厂 `UdpPackage` 向 `127.0.0.1:8088` 分包发送。名称为 `AirQuality`，数值和目标字段为 `PM2.5_value、PM10_value、TSP_value`。正常采样三个状态均为1；结束或失败时发送零值及状态0，应结合状态解释。CSV保留完整历史，JSON不是完整实验成果。UDP发送成功不证明接收端已收到。

## 异常与验收

程序等待扫描2秒，检查模块在线并连接，初始化串口后发送原厂问询模式指令。读取返回非正数、超出缓冲区或数据不足10字节时停止并记录失败，不补零伪造采样。模式指令仅检查有响应；环境帧仅检查长度，尚未验证帧头、校验和、应答内容及数据精度。串口返回值是否表示字节数需板端确认。

退出时依次尝试释放串口、断开模块、注销驱动库和关闭UDP；单项清理失败仍继续其余步骤。运行、上报或清理失败返回非零退出码。

验收时核对实验信息、参数、至少10行成功采样、TSP估算关系、JSON字段和接收端显示；停止后核对停止记录与离线状态。串口、动态库、接线、响应格式和测量精度均需板端实测。`--check` 只检查配置、配套文件存在与 Python 语法，不加载驱动，也不证明硬件可用。
