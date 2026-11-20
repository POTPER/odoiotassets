# RK3588 YOLO26 管材与方形件识别

把整个 `Pipeline_Det` 目录复制到 RK3588 后，在该目录运行命令。板端需要 Python 3.8 或更高版本、OpenCV、NumPy、PyYAML，以及与板端 Python 和 Runtime 匹配的 RKNNLite。[瑞芯微 RKNNLite 安装包](https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit-lite2/packages)

## 终端启动摄像头计数

在 RK3588 图形桌面的终端进入 `Pipeline_Det`，运行下面的命令。默认打开摄像头 41，用检测框标记检出目标，画面左上角的 `Count` 显示当前帧六类目标的合计。默认置信度为 0.25。

```bash
python3 demo_camera.py
```

摄像头编号不同可用 `--source /dev/video0` 指定。按 Q、Esc 或在终端按 Ctrl+C 退出。

## 图片和视频识别

```bash
# 单图识别。将 test.jpg 换成实际测试图路径。
python3 detect.py --source test.jpg

# 摄像头识别。本地有桌面时加 --show，设备编号按实际情况调整。
python3 detect.py --source 41 --show

# 从终端处理视频，仅查看日志。
python3 detect.py --source sample.mp4 --no-udp --max-frames 100
```

默认使用 `model/` 里从 `RKmodel/pipeline.zip` 提取的 RK3588 模型和原始 `metadata.yaml`。类别 ID 以该配置为准。

| ID | 模型标签 |
| --- | --- |
| 0 | `pipabesar` |
| 1 | `pipakecil` |
| 2 | `persegibesar` |
| 3 | `persegikecil` |
| 4 | `kotakbesar` |
| 5 | `kotakkecil` |

单图识别在 `output/` 中保存标注 JPEG 和 JSON。JSON 包含每类数量、目标类别 ID、置信度和原图像素坐标 `[x1,y1,x2,y2]`。视频窗口显示检测框和当前帧的总数。数量按帧计算。

视频默认沿用火焰示例的 UDP 封包，向 `127.0.0.1:8088` 发标注 JPEG，向 `8089` 发 UTF-8 的“有”或“无”，表示当前帧是否检测到目标。可用 `--host` 指定接收端，或用 `--no-udp` 关闭回传。终端按 Ctrl+C 退出，本地窗口可按 Q 或 Esc 退出视频。

在装有 ONNX Runtime 的电脑上，从仓库内的本目录运行以下命令，可以用现有 ONNX 走 CPU 调试同一套预处理和后处理。

```bash
python detect.py --model ../../../../RKmodel/pipeline/pipeline.onnx --source test.jpg
```

用 `--conf` 调整置信度，用 `--max-det` 调整单帧保留上限。首次推理会打印模型的实际输出形状。
