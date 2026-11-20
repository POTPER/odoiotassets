# 风向传感器标准实训

标准入口为 [WindDirectionSensor_standard.py](WindDirectionSensor_standard.py)，原厂 [WindDirectionSensor_Demo1.py](WindDirectionSensor_Demo1.py)、[WindDirectionSensor.py](WindDirectionSensor.py) 保留。标准入口提供实验信息、配置检查、完整 CSV、同次源码归档、JSON/UDP 上报和退出清理；不采集风速。

## 开始实验

在 RK3588 Linux 板端本模块目录执行，需要 Python 3、`SensorModule.py`、`RS232Module.py`、`UdpPackage.py` 和 `libSmartSensorDriver.so`。沿用原厂模块地址15、串口通道2、TX=23、RX=22、9600及8N1参数，接线和串口参数含义以设备资料及现场为准。

```bash
python3 WindDirectionSensor_standard.py --help
python3 WindDirectionSensor_standard.py --check
python3 WindDirectionSensor_standard.py
python3 WindDirectionSensor_standard.py --output-root ./成果输出
```

先填写入口顶部 `experiment_info`，将 `SLEEP_TIME` 从默认1秒改为任务要求的2秒。缓慢转动风向标，至少观察10次有效采样，包含北、东、南、西附近的读数，按 Ctrl+C 结束。间隔为每次采集结束后的等待时间，串口问询和上报耗时会增加实际周期。

`WIND_DIRECTION_TARGET_VALUE` 和 `WIND_DIRECTION_MAXIMUM_VALUE` 默认0，配置范围均为 `[0, 360)`，仅记录和上报，不执行超限、连续次数统计或报警；0作为配置占位值。测量值0度则是有效的北向读数。

## 读数和方位

沿用原厂问询 `01 03 00 00 00 02 C4 0B`，从9字节响应的偏移5、6取大端无符号原始值，除以100得到角度。角度必须满足 `0 ≤ 角度 < 360`；360度及以上作为异常，不自动归零。此换算来自原厂实现，实际量程和精度须板端核对。

方向沿用原程序从0度起、每22.5度一段的规则，左闭右开；未采用以各罗盘方位为中心的划分。

| 角度范围（度） | 方位 | 角度范围（度） | 方位 |
| --- | --- | --- | --- |
| [0, 22.5) | 北 N | [180, 202.5) | 南 S |
| [22.5, 45) | 东北偏北 NNE | [202.5, 225) | 南偏西 SSW |
| [45, 67.5) | 东北 NE | [225, 247.5) | 西南 SW |
| [67.5, 90) | 东偏北 ENE | [247.5, 270) | 西偏南 WSW |
| [90, 112.5) | 东 E | [270, 292.5) | 西 W |
| [112.5, 135) | 东南偏东 ESE | [292.5, 315) | 西北偏西 WNW |
| [135, 157.5) | 东南 SE | [315, 337.5) | 西北 NW |
| [157.5, 180) | 南偏东 SSE | [337.5, 360) | 北偏西 NNW |

标准入口修正了原厂 `NBNE、EBNE、SEB、SBSE、WBSS、NBW` 等缩写，其中南偏东与南偏西原先均为 `SBSE`。原厂文件不改动。标准入口直接调用串口接口，避免原厂高层封装将短回包缓冲区中的零值解释为有效北向。

## 成果与上报

CSV 默认位于当前运行用户桌面的 `成果输出/考试编号/项目名称/`，文件名含微秒时间戳，同名 `.py` 是本次运行入口源码。`--output-root` 替换“桌面/成果输出”根目录。归档入口仍需要本模块配套驱动文件。提交同次 CSV、`.py` 和现场观察记录。

CSV 包含实验信息，以及 `记录时间、采样序号、模块编号、风向原始值、风向角度(度)、风向名称、风向目标(度)、风向最大值(度)、采集间隔(秒)、记录类型、结果、错误信息`。每次有效采样一行；初始化、停止、运行失败、上报失败及清理失败为独立事件行，测量字段为空。采样序号是采样尝试次数，一次尝试最多含3次无响应问询。文本以公式字符开头时加单引号，便于表格软件查看。

`student_data/student_data.json` 保留最近5条上报，CSV保留完整采样历史。沿用原厂字段：`Name=WindDirectionSensor`，`Answer.Wind_Direction` 为“方位名称 角度°”，`Target_Value.WindDirectionSensor` 和 `Maximum_Value.WindDirectionSensor` 为配置值，`Exceeding_Limit_Times=3` 为兼容字段。正常采样三个状态均为1；停止或失败时上报“未知方向”与三个状态0。离线状态不作为有效测量写入CSV。

UDP 通过原厂 `UdpPackage` 分包发送至 `127.0.0.1:8088`，每片数据最多1000字节，另带16字节小端包头。发送成功不证明接收端已收到。

## 异常与验收

程序扫描等待2秒，确认模块在线并连接后初始化串口。读取返回0时最多问询3次，负值立即报错；正值必须等于9，否则报错停止。解析后还检查角度范围，失败时不补零生成采样。尚未验证响应地址、功能码、字节数字段和CRC；驱动返回值是否表示实际接收字节数、超时参数单位，以及完整帧协议均需板端确认。

退出时依次尝试释放串口、断开模块、注销驱动库和关闭UDP，单项驱动清理失败仍继续其余步骤。运行、上报或清理失败返回非零退出码；正常 Ctrl+C 停止返回0。

验收时核对实验信息、2秒间隔配置、至少10行成功采样、原始值/100与角度关系、上述方位边界、接收端显示和停止后的离线状态。接线、动态库兼容性、方向标定和测量精度需现场确认。`--check` 仅验证配置、文件存在与Python语法，不加载动态库，不证明硬件可用。
