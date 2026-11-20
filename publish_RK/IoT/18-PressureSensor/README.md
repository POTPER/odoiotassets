# 18 压力传感器标准实训

标准入口为 [PressureSensor_standard.py](PressureSensor_standard.py)，原厂入口 [PressureSensor_Demo1.py](PressureSensor_Demo1.py) 保留。标准版提供教学参数、配置检查、ADC均值与质量估算、完整CSV、同次源码归档和退出清理。

## 开始实验

填写入口顶部 `experiment_info`，将 `SLEEP_TIME` 从1秒改为2秒，按教师任务设置 `PRESSURE_TARGET_VALUE` 和 `PRESSURE_MAXIMUM_VALUE`。目标值只记录和上报；最大值为0表示未设置，非零时累计统计估算值严格大于最大值的采样次数，等于不计数，持续超限会逐次计数，不触发执行器。

在RK3588 Linux板端进入本目录运行，需要Python 3和同目录 `UdpPackage.py`、`libSmartSensorDriver.so`，无第三方Python包依赖：

```bash
python3 PressureSensor_standard.py --help
python3 PressureSensor_standard.py --check
python3 PressureSensor_standard.py
python3 PressureSensor_standard.py --output-root ./成果输出
```

模块地址默认15，沿用原厂 `modIndex=15`，与目录序号18不同；按实际接线核对 `MODULE_INDEX`。ADC通道0对应原厂GPIO32，位宽枚举3表示12位。扫描等待2秒后检查在线并连接，通过绝对路径加载动态库。`--help` 和 `--check` 不加载驱动；后者仅检查配置、依赖文件存在与入口及UDP封装语法。

空载、轻压、逐步加压并释放，至少观察10次有效采样，按Ctrl+C结束。每组读取3次，每次后等待20毫秒，然后取算术平均；采集、记录和上报结束后再等待 `SLEEP_TIME`，实际周期会更长。任何一次ADC返回负值即作废整组，记录异常并退出，不以部分样本或0冒充成功采样。

## 换算与边界

沿用原厂两点线性估算：ADC值3100对应20 g，ADC值0对应2000 g，两端均包含；中点1550对应1010 g。计算结果绝对值小于 `DEAD_ZONE=0.5` 时置零，再保留两位小数。默认标定下区间内结果均不低于20 g，因此死区不会产生空载零点；程序未执行去皮。ADC接口单位未确认，CSV使用“ADC均值”，不标为V或mV。

ADC均值在两个标定值之外时，CSV保留ADC、质量估算留空、标记“超出标定区间”，程序继续采样；该条JSON发送0和状态0，不能将其解释为测得0 g。原厂对此返回0，标准版改为显式区分。

原厂 `PressureSensor.py` 注释称有效范围20 g～1 kg，实际常量却用20 g与2000 g换算，尚有冲突。标准版保留实际常量，不据此确认传感器量程或测量精度。字段虽沿用“压力”，数值是质量估算g，不是Pa。标定点应根据实物与已知载荷现场核对；`config.py` 未被原厂压力换算或标准入口使用。

## 成果与验收

默认成果位于当前运行用户桌面 `成果输出/考试编号/项目名称/`，文件名含微秒时间戳；`--output-root` 替换成果根目录。同名 `.csv` 和 `.py` 分别是完整记录与本次入口源码快照，复现仍需本目录UDP封装和驱动库。

CSV包含实验信息及 `记录时间、采样序号、模块编号、ADC均值、质量估算(g)、量程状态、压力目标值(g)、压力最大值(g)、超限累计次数、采集间隔(秒)、记录类型、结果、错误信息`。每组采样一行；初始化、停止、运行异常、上报失败、清理失败与结束另记事件行。序号表示采样尝试次数，事件行测量字段为空。文本以公式字符开头时加单引号，便于表格软件查看。

`student_data/student_data.json` 保留最近最多5条，沿用 `Name=LiftingLoadSensor` 及 `Answer/Target_Value/Maximum_Value` 中的 `LiftingLoadSensor`，并保留 `Output_Frequency、Exceeding_Limit_Times、Status`。原厂超限次数固定为3，标准版改为本次有效采样的累计次数。正常采样三个状态为1；区间外、结束或失败时三个状态为0并发送0值，表示本条数据不可用，不能仅据连接状态判断物理连线。UDP沿用四个小端32位无符号整数包头、每包最多1000字节数据，发送至 `127.0.0.1:8088`；发送成功不证明接收端收到。JSON不替代完整CSV。

Ctrl+C、SIGTERM和运行异常触发释放ADC、断开模块、注销驱动库与关闭UDP，各项独立尝试。运行、上报或清理失败返回非零退出码；强制终止、断电不能保证清理。ADC初始化/读取/释放及断开以负返回值判为失败，连接要求正值，在线查询要求1；返回码语义仍需配套驱动实测确认。

提交同次CSV、源码快照和现场观察记录，核对至少10组有效采样、按压与释放趋势、参数、超限计数和接收端显示。已完成静态检查、帮助及模拟驱动验证；动态库ABI、ADC单位、标定、量程与精度尚未板端实测。
