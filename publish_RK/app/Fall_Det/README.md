# RK3588 YOLO26 人员跌倒检测

| 入口 | 模型类别 | 标记为跌倒 |
| --- | --- | --- |
| `demo_fall_5class.py` | Walking、Sleeping、falling、Standing、Sitting | falling |
| `demo_fall_2class.py` | non-fall、fall | fall |

两个入口各自加载一个用人体框标注训练的 YOLO26 检测模型。类别 ID 取自转换生成的同名 JSON，类别顺序与训练模型一致。画面显示类别和置信度，跌倒框标红。状态和人数按当前帧计算。

## 转换训练好的权重

在安装好 Ultralytics 和 RKNN-Toolkit2 的 x86_64 Linux 环境中，从仓库根目录运行。将下列 `best.pt` 路径替换为两个训练结果。转换环境可参考仓库里的 [依赖说明](../../../../vision-switcher/projects/fgy_yolo26/README.md#2-先准备一个通用模型试跑)。

```bash
demo_dir='RK3588实训台设计归档/RK3588IOT及app设计/app/Fall_Det'

python vision-switcher/projects/fgy_yolo26/prepare_model.py \
  --weights /path/to/five-class/best.pt \
  --output "$demo_dir/model/fall_5class_rk3588.rknn"

python vision-switcher/projects/fgy_yolo26/prepare_model.py \
  --weights /path/to/two-class/best.pt \
  --output "$demo_dir/model/fall_2class_rk3588.rknn"
```

该流程默认生成 FP16 模型，使用瑞芯微 YOLO26 one2one 检测头的双输出，包含像素坐标和每类分数。请把生成的两个 `.rknn` 和各自同名的 `.json` 随 `Fall_Det` 目录一起复制到 RK3588。板端依赖 Python 3.8+、OpenCV、NumPy，以及与板端 Python 和 RKNN Runtime 匹配的 ARM64 RKNNLite。[瑞芯微 YOLO26 示例](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolo26) · [RKNNLite 安装包](https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit-lite2/packages)

## 在板端运行

进入板端的 `Fall_Det` 目录。在图形桌面的终端运行，按实际摄像头编号修改 `--source`。默认设备号为 41。视频预览按 Q 或 Esc 退出。

```bash
python3 demo_fall_5class.py --source /dev/video41
python3 demo_fall_2class.py --source /dev/video41
```

也可以识别图片或视频。无图形桌面时加 `--no-show`，终端会打印识别状态。

```bash
python3 demo_fall_5class.py --source test.jpg --no-show --output result.jpg
python3 demo_fall_2class.py --source test.mp4 --no-show --max-frames 100
```

用 `--model` 指定其他位置的 RKNN 文件，模型旁需保留同名 JSON。用 `--conf` 调整置信度阈值，默认 0.5。
