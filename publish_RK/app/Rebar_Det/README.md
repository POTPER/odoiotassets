# RK3588 YOLO26 钢筋计数

把整个 `Rebar_Det` 目录复制到 RK3588。将训练导出的 RK3588 `.rknn` 放进 `model/`，同时放入原始 `metadata.yaml` 或同名 JSON。目录默认只应有一个 RKNN 文件。也可用 `--model` 指定已有模型文件或导出目录。

该示例使用单类别 `0 = rebar`。如果只有 RKNN 文件，把它放在 `model/labels.txt` 旁边即可使用预置类别。缺少输入尺寸配置时默认输入为 640 × 640，可用 `--imgsz` 指定实际尺寸。支持火焰示例的三种解码后输出，即 Ultralytics 原始检测张量、端到端检测列表和 Rockchip 坐标与分数双输出。请保留原始导出配置以核对模型格式。

板端需要 Python 3.8 或更高版本、OpenCV、NumPy，以及与板端 Python 和 Runtime 匹配的 RKNNLite。读取 YAML 模型配置还需要 PyYAML。[瑞芯微 RKNNLite 安装包](https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit-lite2/packages)

## 终端启动摄像头

在 RK3588 图形桌面的终端进入 `Rebar_Det` 目录，执行下面的命令。程序默认打开摄像头 41，用检测框标出检出的钢筋，画面左上角的 `Count` 显示当前帧数量。横放、竖放和端面的钢筋都按模型检测结果计数。默认置信度为 0.25，可用 `--conf` 调整。

```bash
python3 demo_camera.py
```

启动后在终端输入 `1` 选择普通模式，输入 `2` 选择精细模式。直接回车使用普通模式，输入 `0` 退出。

窗口标题为 `Rebar detection`，按 Q、Esc 或在终端按 Ctrl+C 退出。模型从本目录的 `model/` 自动读取。摄像头或模型目录不同，可以通过参数指定。

```bash
python3 demo_camera.py --source /dev/video0 --model models
```

## 密集钢筋精细计数

在摄像头启动菜单中选择 `2`。精细模式保留一次整帧推理，再对最多四个重叠区域放大推理，让较小的钢筋端面在模型输入中占更多像素。分块结果映射回原画面，先去掉内部边缘被截断的框，再对重复框去重。分块推理会增加每帧耗时，适合对固定画面或密集目标做对比计数。[Ultralytics 分块推理说明](https://docs.ultralytics.com/guides/high-resolution-tiling/)

也可以对同一张照片用 `python3 detect.py --source rebar.jpg --conf 0.25 --detail` 复核。对比时使用相同的 `--conf`，以人工清点的根数为准。数量达到单帧上限时可用 `--max-det` 提高上限。

## 图片和视频识别

```bash
# 将 rebar.jpg 换成实际测试图路径。
python3 detect.py --source rebar.jpg

# 摄像头识别。本地有桌面时加 --show。
python3 detect.py --source /dev/video41 --show

# 在密集场景中提高单帧保留上限。
python3 detect.py --source rebar.jpg --conf 0.4 --max-det 800
```

单图识别在 `output/` 中保存标注 JPEG 和 JSON。JSON 包含本图钢筋数量、目标置信度和原图像素坐标 `[x1,y1,x2,y2]`。视频也可用 `--source sample.mp4` 输入，窗口显示检测框和当前帧数量。数量按帧计算。

视频默认沿用火焰示例的 UDP 封包，向 `127.0.0.1:8088` 发标注 JPEG，向 `8089` 发 UTF-8 的“有”或“无”，表示当前帧是否检测到钢筋。可用 `--host` 指定接收端，或用 `--no-udp` 关闭回传。终端按 Ctrl+C 退出，本地窗口可按 Q 或 Esc 退出视频。

