# 2026年金砖总决赛光照样题模块

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
