# RK3588 YOLO26 安全带识别

独立目录，入口为 `safety_harness.py`，推理后端改编自仓库已有的火焰识别项目。板端使用 **RKNNLite + RK3588 NPU**，无需安装 PyTorch 或 Ultralytics。

根据提供的类别截图，模型原始类别为 **0=Harness、1=Helmet**。程序在后处理筛选阶段仅保留 ID 0；画面、日志和图片结果 JSON 均只显示安全带。不能删掉模型的 Helmet 类或把类别数改成 1，否则会造成输出解析错误。

已接入提供的 `model/safety-harness-rk3588.rknn`，默认启动使用此文件。已完成模型文件、配套说明及代码的离线核对，**尚未完成 RK3588 实机推理和识别效果验证**。安全带数量是当前帧的目标框数量，不是工人数；模型没有“人员”和“未佩戴”类别，无法据此判断未系安全带人数或安全带是否正确挂接。

## 放入模型

当前模型与配置已放在 `model/`，复制整个项目目录到板子即可。模型文件为 `safety-harness-rk3588.rknn`，同名 `safety-harness-rk3588.json` 记录参数并绑定模型 SHA256。也可以使用 `--model /实际路径/模型.rknn` 指定其他模型。

已根据原始导出目录的 `metadata.yaml` 和模型内嵌信息核对：

| 项目 | 当前模型 |
| --- | --- |
| 模型 | Ultralytics YOLO26n，目标检测 |
| 导出版本 | Ultralytics 8.4.192 |
| RKNN 编译器 / 目标 | 2.3.2 / rk3588 |
| 精度 | FP16（quantize=16） |
| 原始输入张量 | `[1,3,640,640]`，运行接口传入 RGB uint8 NHWC |
| 编入模型的归一化 | mean=`[0,0,0]`，std=`[255,255,255]` |
| 输出 | 单输出 `[1,6,8400]`，raw 检测头，end2end=false |
| 类别 | 0=Harness、1=Helmet；仅保留0 |

上述核对未执行 NPU。模型文件约7.32 MB，SHA256 为 `05653cf93eca673cb4ac6da30fd1e63737044d719e2065ce1c74fa5761d3e632`。

`model/labels.txt` 已按截图配置为：

```text
Harness
Helmet
```

更换模型时，请一起更换同名 JSON、YAML 或导出目录中的 `metadata.yaml`；程序会读取其中的类别和输入尺寸。类别顺序以实际导出模型为准。若与截图不一致，请同步修改配置，并用 `--harness-class` 指定安全带原始 ID。模型更换后旧 JSON 的 SHA256 校验会拒绝不匹配的文件，应更新为新模型的真实配置。

`model/safety-harness.example.json` **仅为其他模型的配置示例，不会自动应用**。当前模型使用已核对的 `safety-harness-rk3588.json`，无需复制示例。若其他模型没有配置文件，使用 `labels.txt`、640×640 输入、114 补边、像素坐标；输入尺寸可用 `--imgsz 高 宽` 设置，模型说明文件中的尺寸优先。

当前 RKNN 输入约定：等比例缩放补边、BGR 转 RGB、uint8 NHWC，`/255` 已编入 RKNN。若你的导出使用其他约定，需要对应调整。

## 板端环境

Python 3.8+，需要 `numpy`、`cv2` 和 `rknnlite.api`。优先使用板卡厂商已有的兼容环境；缺少 NumPy/OpenCV 时，Debian/Ubuntu 可执行：

```bash
sudo apt-get install python3-numpy python3-opencv
```

从[瑞芯微官方 wheel 目录](https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit-lite2/packages)选择与板端 Python、ARM64 系统匹配的 RKNNLite 包，并用运行脚本的同一个 Python 安装：

```bash
python3 -m pip install /实际路径/匹配版本的rknn_toolkit_lite2.whl
```

仅读取 YAML 说明文件时需要 PyYAML；当前配套配置为 JSON。此模型使用 RKNN 编译器2.3.2，板端 RKNNLite、`librknnrt.so` 与 NPU 驱动需兼容。

## 使用

### 摄像头实时识别 demo

在 RK3588 Ubuntu 桌面终端进入本项目目录，直接运行下面的命令。默认打开实训台摄像头 `/dev/video41`，在预览窗口显示安全带检测框、数量、耗时和帧率。

```bash
python3 detect_camera.py
```

如果摄像头对应 `/dev/video0`，运行 `python3 detect_camera.py --source 0`。在预览窗口按 `q` 或 `Esc` 可退出，也可以在终端按 `Ctrl+C`。摄像头 demo 使用项目已有的 RKNN 模型和 OpenCV。

### 实时识别Ubuntu桌面屏幕

`detect_screen.py` 捕获桌面屏幕像素，用同一个RKNN模型只识别安全带。可用于屏幕上显示的图片、网页或播放的视频；输入来源是屏幕，不调用摄像头。**新版已附带vendor目录中的MSS依赖，不再需要执行pip安装MSS。** 请将整个项目目录（包括vendor和model）复制到板子。

在 **RK3588 Ubuntu桌面内的终端** 执行：

```bash
cd ~/safety-harness

# 连续识别第一块显示器，终端输出检测数量与置信度。
python3 detect_screen.py

# 先试一次屏幕截图，保存标注图和JSON后退出。
python3 detect_screen.py --once

# 只识别桌面中左上角(100,100)、宽800、高600的区域，并打开标注预览。
python3 detect_screen.py --region 100 100 800 600 --show

# 查看显示器编号与桌面像素范围，不加载模型。
python3 detect_screen.py --list-monitors
```

默认每0.2秒最多捕获一次，实际速度受NPU推理和屏幕分辨率影响，可用 `--interval 0.5` 调整。打开要测试的图片或视频，保持可见后运行。终端每秒输出当前安全带数量、置信度和桌面坐标。

Ctrl+C或SIGTERM停止后，最后一次成功识别的标注屏幕和JSON保存到 `output/screen/`，文件名带时间。预览窗口可按 `s` 保存当前结果，按 `q` 或Esc停止；`--max-frames 100` 可限制帧数。JSON的 `box` 是截图内坐标，`screen_box` 是桌面全局坐标，支持多屏负坐标。只记录检测框数量，不推断未佩戴人数。

默认不弹出预览，避免整屏捕获时反复识别自己的预览画面。需要预览时，建议用 `--region` 限定图片/视频区域，并把预览窗口移到区域外；整屏模式也会包含屏幕上可见的程序窗口，遮挡内容不会被识别。

**桌面会话要求：X11/Xorg。** 当前捕获后端使用MSS 9.0.2的X11接口；Wayland会明确报错。需要时退出登录，在登录界面选择“Ubuntu on Xorg”后重新登录。纯SSH、无桌面或无法访问桌面DISPLAY时不能直接捕获屏幕。不需要使用sudo运行，也不修改桌面权限。

依赖与平台依据：[MSS 9.0.2的Python版本要求](https://github.com/BoboTiG/python-mss/blob/v9.0.2/pyproject.toml)、[Linux X11捕获实现](https://github.com/BoboTiG/python-mss/blob/v9.0.2/src/mss/linux.py)。当前编写环境为Windows，尚未在RK3588 Ubuntu上实测桌面捕获和NPU识别。

如果旧版安装时出现 `ReadTimeoutError` / `files.pythonhosted.org ... Read timed out`，表示下载超时。推荐使用带vendor目录的新版直接运行，无需重试pip。也可在旧版本目录中换源安装：

```bash
python3 -m pip install mss==9.0.2 -i https://mirrors.aliyun.com/pypi/simple/ --timeout 120 --retries 5
```

离线包只解决MSS安装；如果运行时报告OpenCV、NumPy、RKNNLite缺失，或Wayland/DISPLAY错误，需要分别按实际报错处理。

### 仅测试图片

新增独立入口 `detect_image.py`，只读取一张本地图片，不打开摄像头，不发送 UDP，默认无需桌面。仍需在安装了 RKNNLite 的 RK3588 上运行。

```bash
cd ~/safety-harness
python3 detect_image.py --image /实际路径/test.jpg
```

也可以把图片放到 `detect_image.py` 旁边并命名为 `test.jpg`，然后直接运行：

```bash
python3 detect_image.py
```

终端会输出安全带目标数量、每个框的置信度及原图像素坐标（左、上、右、下）、识别耗时和结果文件路径。默认保存 `output/images/test_harness.jpg` 与 `output/images/test_harness.json`；同一文件名重复测试会覆盖上一次结果，可用 `--output` 指定其他目录。没有检测到安全带时同样保存结果，数量为0，不推断未佩戴人数。

```bash
# 调整阈值或输出目录。
python3 detect_image.py --image /实际路径/test.jpg --conf 0.4 --output ./image-results

# 有桌面时可选弹窗预览，按任意键关闭。
python3 detect_image.py --image /实际路径/test.jpg --show
```

脚本顶部的 `IMAGE_PATH`、`MODEL_PATH` 也可直接修改。模型默认使用已接入的 `model/safety-harness-rk3588.rknn`；入口固定仅识别类别0（Harness）。

### 图片、摄像头及视频通用入口

复制整个新目录到板子，例如 `~/safety-harness`：

```bash
cd ~/safety-harness

# 文件和依赖检查；不执行推理。
python3 safety_harness.py --check

# 先测试图片，保存 output/test_harness.jpg 和同名 JSON。
python3 safety_harness.py --source /实际路径/test.jpg

# 摄像头实时预览，原项目摄像头为41，按实际设备修改。
python3 safety_harness.py --source 41 --show

# 无桌面时只输出日志，处理100帧后退出。
python3 safety_harness.py --source /dev/video41 --max-frames 100

# 视频文件或 RTSP。
python3 safety_harness.py --source /实际路径/video.mp4 --show
python3 safety_harness.py --source rtsp://camera/stream --show

# 指定其他模型路径和无说明文件时的输入高宽。
python3 safety_harness.py --model /实际路径/best.rknn --imgsz 640 640 --source 41 --show
```

默认置信度 `0.5`，用 `--conf 0.4` 调整。`--core auto/0/1/2/all` 选择 NPU 核心，性能需实测。实时预览时按 `q`、空格或 Esc 退出，也支持 Ctrl+C、SIGTERM 释放资源。图片预览处理一帧后自动结束，标注图保存在 output 目录。

仅图片输入保存标注 JPEG 与结果 JSON，视频输入默认打印每秒日志。JSON 中 `harness_count` 为安全带框数量，`detections` 仅包含安全带，`labels` 保留完整的模型类别表便于核对。`AI` 耗时包括预处理、推理调用和后处理；`loop FPS` 是上一完整循环速度。

## 与原画面接收端配合

```bash
python3 safety_harness.py --source 41 --udp
python3 safety_harness.py --source 41 --udp --host 接收端IP --image-port 8088
```

UDP 默认关闭，开启后仅发送标注 JPEG。使用现有视觉项目的分片协议：16 字节头，四个小端 uint32 依次为组号、总分片数、从 0 开始的序号、当前分片数据长度；每片数据最多 60000 字节。接收端需要自行重组；发送不会自动打开窗口。程序不发送火焰报警或穿戴人数协议。

## 输出格式与模型适配

支持下列**已解码的目标检测输出**：

| 参数 | 输出 | 后处理 |
| --- | --- | --- |
| `ultralytics_raw` | `[1,4+C,N]`，前4项为像素 cxcywh，其余为类别概率 | 筛选 Harness，执行同类 NMS |
| `end2end` | `[1,N,6]`，xyxy、置信度、类别ID | 筛选 Harness，不重复 NMS |
| `rockchip_yolo26` | `[1,C,N]` 概率和 `[1,4,N]` 像素 xyxy，两分支 one2one | 筛选 Harness，不重复 NMS |

本模型 `C=2`。默认 `auto` 根据输出形状选择；有歧义时必须显式设置 `--output-format`。首帧日志打印实际输出形状和类型，报错时加 `--debug`。

若是归一化坐标，在核实后将同名 JSON 中 `normalized_boxes` 设为 `true`。INT8 模型的坐标单位不能只凭量化类型推断。含 `tail.onnx` 的新导出流程和其他未解码的多尺度输出目前不支持，需要提供完整导出信息后适配。不要单凭“YOLO26”名称假定输出一致。

格式参考：[Ultralytics RKNN 部署说明](https://docs.ultralytics.com/integrations/rockchip-rknn)、[瑞芯微 YOLO26 示例](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolo26)。

## 离线验证

```bash
python -m unittest discover -s tests -v
```

测试使用合成输出和模拟 RKNNLite，覆盖仅筛选安全带、坐标还原、NMS、图片保存、UDP 分片及异常资源释放。不能代替实际模型精度、摄像头和 NPU 测试。
