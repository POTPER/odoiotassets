# RK3588 第 11 模块 · 噪声传感器实训

## standard 标准版

[NoiseSensor_standard.py](NoiseSensor_standard.py) 是独立单文件入口，仅需同目录的 `libSmartSensorDriver.so`，运行环境为 RK3588 Linux ARM64、Python 3.8 或更高版本。持续采样，按 Ctrl+C 或收到 SIGTERM 后关闭串口、断开本次模块连接并注销驱动。

在「02 用户设置与教学任务」填写 `experiment_info`，可追加自定义实验信息字段。默认 `NOISE_TARGET_VALUE = 50` dB、`SLEEP_TIME = 1` 秒；任务要求改为 60 dB、2 秒，观察两种声环境并至少保留 10 条有效采样。读数**高于**目标值为「超限」，等于或低于为「正常」。等待时间从本次采集、归档和上报处理完成后开始，因此相邻采样实际间隔还包括处理耗时。

在模块目录执行：

```bash
python3 NoiseSensor_standard.py --check
python3 NoiseSensor_standard.py
# 可选：指定模块编号和成果根目录
python3 NoiseSensor_standard.py --module 11 --output-dir ./成果输出
```

`--check` 只检查实验信息、参数及驱动文件存在性，不加载动态库或连接硬件。串口沿用原厂配置：通道 2、TX=22、RX=23、115200、8N1，请求 `01 02 00 00 00 00 78 0A`，8 字节缓冲区第 4 字节作为 dB 读数。驱动正返回值沿用原示例的成功约定，返回值是否代表字节数、回包完整性和校验规则待板端及协议核对。

成果默认保存在当前用户桌面的 `成果输出/考试编号/项目名称/`，包含同名 CSV 与本次完整 Python 源码。CSV 保存实验信息及「记录时间」「实验累计毫秒」「模块编号」「采样序号」「动作」「采集间隔(秒/次)」「噪声读数(dB)」「噪声目标值(dB)」「判定」「执行结果」「错误信息」。每次采样一行，初始化、停止、清理及上报异常另有事件行；非采样事件读数为空、判定为「未知」。读取失败记录空读数后停止并清理，不将失败当作 0 dB。

`student_data/student_data.json` 保留最近 5 条事件，并通过 `127.0.0.1:8088` 按原分包协议上报，沿用 `Answer.noise_decibel`、`Target_Value.NoiseSensor` 等平台字段。初始化、失败、停止与清理事件的读数为「未知」，通信与输出状态为 0；连接状态表示程序是否尚持有连接，不能作为实时在线探测。JSON/UDP 异常另记 CSV。现场验收需观察声环境变化、核对实际采样间隔，并在退出后重启确认可重连。

## 原有教学版本

两道题都以「施工通道01」为监测点。基础题练习配置固定间隔和阈值，进阶题要求学生编写自动切换逻辑，并用采样记录说明何时加快、何时恢复。

## 入口

| 用途 | 文件 | 任务 |
| --- | --- | --- |
| 学生基础题 | [NoiseSensor_Teaching.py](NoiseSensor_Teaching.py) | 配置固定间隔和阈值，观察两种声环境下的判定 |
| 学生进阶题 | [NoiseSensor_Adaptive.py](NoiseSensor_Adaptive.py) | 配置慢采和快采，补写 `next_sampling_mode` |
| 教师对照 | [NoiseSensor_Adaptive_Answer.py](NoiseSensor_Adaptive_Answer.py) | 运行完整切换逻辑，按[教师解析](NoiseSensor_Adaptive_解析.md)核对结果 |
| 实训台原演示 | [NoiseSensor_Demo1.py](NoiseSensor_Demo1.py) | 当前实训台菜单配置指向的演示入口 |

## 题面与修改位置

两道题的题面都在脚本顶部「02 用户设置」。在 `experiment_info` 填写本人「考试编号」，把「项目位置」设为「施工通道01」，「项目名称」使用对应题名。

| 题目 | 修改位置 | 脚本初始值 | 题面要求 |
| --- | --- | --- | --- |
| 施工通道噪声监测 | `NOISE_TARGET_VALUE`、`SLEEP_TIME` | 50 dB、1 秒 | 60 dB、每 2 秒采一次，共 10 次采样尝试 |
| 施工通道噪声自适应采样 | TODO 1，`NOISE_TARGET_VALUE`、`NORMAL_INTERVAL_SECONDS`、`FAST_INTERVAL_SECONDS`、`RECOVERY_SAMPLES` | 50 dB、慢采 4 秒、快采 2 秒、连续 2 次 | 60 dB、慢采 5 秒、快采 1 秒、连续 3 次，共 12 次采样尝试 |
| 施工通道噪声自适应采样 | TODO 2，`next_sampling_mode` | 占位函数返回 `None` | 根据本次模式、此前连续正常次数和本次读数，返回下次模式及更新后的计数 |

基础题已提供判断逻辑，读数高于所设阈值时记为「超限」，等于或低于时记为「正常」。进阶题从慢采开始，高于阈值时决定从下一次起快采。快采期间连续三次有效读数等于或低于阈值后，下一次恢复慢采。读取失败时保持当前模式并将连续计数清零。学生负责实现这些规则，程序根据返回值调度下一次采样。保留占位时仍可观察慢采，有效读数会标为「切换逻辑待完成」。两题的 60 dB 均为课堂调试阈值。

## 板端运行

在 RK3588 Linux ARM64 的终端进入 `11-NoiseSensor` 目录，使用 Python 3.8 或更高版本。基础题需要同目录的 `libSmartSensorDriver.so`。进阶题还依赖 `NoiseSensor_Teaching.py`，教师版需和两个学生脚本一起复制。一次运行一个占用 11 号模块的程序。

```bash
python3 NoiseSensor_Teaching.py --check
python3 NoiseSensor_Teaching.py
```

```bash
python3 NoiseSensor_Adaptive.py --check
python3 NoiseSensor_Adaptive.py
```

`--check` 校验用户设置和驱动文件，可在无板环境执行。板端启动后达到采样次数会自动退出，也可按 Ctrl+C 提前结束，已写入的记录会保留。

## 成果与现场验收

提交同一次运行生成的 **CSV 和 Python 源码**。两者同名，默认保存在当前用户桌面的 `成果输出/考试编号/项目名称/`，文件名包含运行时间。`--output-dir` 可指定成果根目录。成功读数另存到模块目录的 `student_data/student_data.json`，保留最近五条并通过 `127.0.0.1:8088` 上报。

- **基础题**每次采样尝试占一行。核对「噪声目标值(dB)」和「监测间隔(秒/次)」是否符合题面，用相邻两行的「实验累计毫秒」核对实际间隔。比较两种声环境下的「噪声读数(dB)」和「判定」。阈值设为 60 dB 时，等于阈值的读数应判为「正常」。
- **进阶题**每次采样尝试占一行。对照触发行的「下次模式」「下次设定间隔(秒)」与下一行的「本次模式」「实际间隔(秒)」。找到一次加快和一次恢复，并说明快采阶段记录到了哪些短时变化。首行的「实际间隔(秒)」留空。
- **失败记录**的「判定」为「读取失败」，读数留空，原因在「错误信息」列。有效读数如遇 JSON 保存或 UDP 上报失败，仍保留读数和判定，错误也写入同一列。

板端验收时观察读数是否随声环境变化，并在退出后再次运行确认模块能重连。采样切换已用替身驱动验证，实际读数、采样间隔和重连表现待 RK3588 实机核对。
