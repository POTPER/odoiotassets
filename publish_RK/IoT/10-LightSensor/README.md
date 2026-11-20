# 2026年金砖总决赛光照样题模块

## standard 标准版

新增单文件入口 [LightSensor_standard.py](LightSensor_standard.py)，沿用相邻模块的实验信息、连续采集、CSV及同次源码归档方式。仅需同目录的 `libSmartSensorDriver.so`，不依赖其他 Python 驱动文件或 NumPy。原样题入口保持原有行为。

标准版顶部提供独立教学任务：填写考试编号，将项目名称设为“施工通道光照监测”、项目位置设为“施工通道01”，把 `LIGHT_TARGET_VALUE` 从初始 50 lx 改为 100 lx，把 `SLEEP_TIME` 从初始 1 秒改为 2 秒。观察遮挡、照明和恢复过程，各保留至少 3 条有效采样，按 Ctrl+C 结束。标准版持续采集，不按 10 次自动结束。

在 RK3588 Linux ARM64 上使用 Python 3.8 或以上版本运行：

```bash
python3 LightSensor_standard.py --check
python3 LightSensor_standard.py
python3 LightSensor_standard.py --module 10 --output-dir ./成果输出
```

`--help` 和 `--check` 不加载动态库，不连接硬件，也不生成成果。`--check` 验证实验信息、间隔、目标值、过滤阈值、模块编号和非空驱动文件；不能确认驱动架构、传感器型号或实测精度。一次只运行一个占用该模块的程序。

标准版沿用 `BH170Sensor.py` 的实际协议：模块 10、SCL 22、SDA 23、地址 `0x23`、100 kHz；写入 `0x01` 后等待 0.2 秒，再写入 `0x10` 并等待 0.2 秒后开始读取。两字节按高字节在前组合后除以 1.2，严格低于 10 lx 时归零，否则保留两位小数。判定使用处理后的照度：低于目标为“照度不足”，达到或超过目标为“正常”。旧演示文件名包含 OPT3001，但标准版依据当前驱动实现，不由文件名推断硬件型号。

成果默认位于当前用户桌面 `成果输出/考试编号/项目名称/`，可用 `--output-dir` 替换根目录。同次 CSV 和标准入口源码同名，重名自动递增。归档源码复现时仍需原厂动态库与硬件。

CSV 每行表示一次采样、初始化、停止或清理事件，记录实验信息及“记录时间、实验累计毫秒、模块编号、采样序号、动作、采集间隔(秒/次)、原始计数、光照强度(lx)、光照目标值(lx)、判定、执行结果、错误信息”。采样序号从 1 开始，生命周期事件为 0；非采样和读取失败行的读数留空、判定为“未知”，不能当作零照度。原始计数除以 1.2 可核对过滤前读数。采集间隔是每次处理后的等待时间，实际间隔还包含读取、保存及通信耗时，可用“实验累计毫秒”核对。

成功读数先写 CSV，再保存 JSON 并上报 UDP。`student_data/student_data.json` 保留最近最多 5 条事件，沿用 `Name=LightSensor`、`Answer.light_lux`、`Target_Value.LightSensor` 等字段，按 16 字节小端包头和每包最多 1000 字节数据发送到 `127.0.0.1:8088`。失败、初始化和清理事件上报照度“未知”，通信与输出状态为 0；连接状态仅表示软件连接过程。JSON 或 UDP 失败另记 CSV，不丢弃已记录的有效采样；UDP 发送成功不证明接收端已收到。

读取失败会记录错误并停止。Ctrl+C、SIGTERM 及运行异常均进入清理流程，依次尝试关闭 I2C、断开模块、注销驱动、关闭 UDP；某项失败后继续后续清理。板端验收需观察光照变化及阈值判定、核对采样间隔，并在退出后再次运行确认模块可重连。板端读数、实际时序与重连尚未实测。

本次通过 Python 3.8 语法兼容检查、`--help`、`--check` 与替身驱动验证，覆盖换算、过滤及目标值边界、CSV/源码归档、JSON/UDP 格式、读取失败、初始化失败、清理失败和非法参数。上述验证不代表板端实测。

本次仅增加设计目录标准入口与说明，未修改菜单或同步发布归档。

## 目录约定

- 设计目录：`Inbox/IoT/10-LightSensor/`，后续在此修改和调试。
- 发布归档目录：`项目结构/linux-arm64/publish/IoT/10-LightSensor/`，从设计目录同步当前模块及配套文件。

## 文件对应

| 文件 | 用途 |
| --- | --- |
| `BRICS2026_Final_Sample_Light.py` | 练习入口，按TODO编写任务编号、任务名称，并设置目标值及采集间隔 |
| `BRICS2026_Final_Sample_Light_anser.py` | 参考答案入口，已配置100 lx、2秒/次和题面项目、点位；考试编号仍需填写 |
| `light_teaching_support.py` | 共用运行模块，负责硬件采集、判别、通信和成果保存 |
| `LightSensor_OPT3001_Demo1.py` | 原演示入口，新增完整CSV历史及同次源码自动归档，保留原JSON/UDP流程 |
| `BH170Sensor.py`、`SensorModule.py`、`UdpPackage.py`、`libSmartSensorDriver.so` | 配套驱动及通信文件 |
| `tools/check_device.py` | 两个样题入口的静态检查工具 |
| `docs/V5_赛题解析.md` | 样题正文、学生修改范围及验收说明 |

## 检查和运行

在模块目录下执行，使用Python 3.8或以上版本：

```bash
python3 tools/check_device.py
python3 BRICS2026_Final_Sample_Light.py --check
python3 BRICS2026_Final_Sample_Light_anser.py --check
```

静态检查验证语法、配置和配套文件，不连接硬件。实际采集在Linux ARM64实训箱上运行对应入口，一次启动一个：

```bash
python3 BRICS2026_Final_Sample_Light.py
```

练习入口保留50 lx、1秒/次的初始值，按TODO要求调整参数。采集10次后自动结束，成果保存在运行设备用户桌面的 `成果输出/任务编号/任务名称/`，包含CSV和同次实际入口源码。主CSV与异常CSV的基础信息均为“任务编号、任务名称”，不再包含“考试编号、项目名称、监测点位”。其他入口继续使用各自原有字段与归档方式。

当前协议参数沿用原Demo1：模块10、SCL 22、SDA 23、I2C地址0x23。硬件连接、驱动加载及实测读数需在实训箱验证。

## 发布归档范围

Demo1的成果默认保存在运行设备桌面的 `成果输出/演示/光照采集/`，正常生成同名CSV与本次源码，异常时另存异常CSV。CSV记录采集时间、序号、模块编号、光照强度、目标值及采集间隔，保留全部采集历史；原 `student_data/student_data.json` 仍按原流程滚动保留最近五条。读取成功的数据先写入CSV，再执行原JSON保存及UDP上报。`RESULTS_DIR` 可指定其他成果根目录。程序仍使用真实传感器和原有低照度过滤，不新增灯光联动或判别题目。

归档前先备份并清空发布目录，再按设计目录同步程序、驱动、诊断工具及文档；不复制Python缓存和运行生成的数据。旧发布内容保存在项目根目录的 `output/module-backups/` 下。
