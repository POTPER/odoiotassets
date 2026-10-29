# 2026年金砖总决赛光照样题模块

## 目录约定

- 设计目录：`Inbox/IoT/10-LightSensor/`，后续在此修改和调试。
- 发布归档目录：`项目结构/linux-arm64/publish/IoT/10-LightSensor/`，从设计目录同步当前模块及配套文件。

## 文件对应

| 文件 | 用途 |
| --- | --- |
| `BRICS2026_Final_Sample_Light.py` | 学生入口，按题面填写实验信息、目标值及采集间隔 |
| `BRICS2026_Final_Sample_Light_anser.py` | 参考答案入口，已配置100 lx、2秒/次和题面项目、点位；考试编号仍需填写 |
| `light_teaching_support.py` | 共用运行模块，负责硬件采集、判别、通信和成果保存 |
| `LightSensor_OPT3001_Demo1.py` | 原演示入口 |
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

学生入口保留50 lx、1秒/次的练习初始值，应按题面修改；参考答案为100 lx、2秒/次。采集10次后自动结束，成果保存在运行设备用户桌面的`成果输出/考试编号/项目名称/`，包含CSV和同次实际入口源码。

当前协议参数沿用原Demo1：模块10、SCL 22、SDA 23、I2C地址0x23。硬件连接、驱动加载及实测读数需在实训箱验证。

## 发布归档范围

归档前先备份并清空发布目录，再按设计目录同步程序、驱动、诊断工具及文档；不复制Python缓存和运行生成的数据。旧发布内容保存在项目根目录的 `output/module-backups/` 下。
