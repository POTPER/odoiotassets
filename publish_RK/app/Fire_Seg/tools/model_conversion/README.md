# V20 模型转换参考

这份资料用于之后替换模型。现有 V20 模型已经有 RK3588 的运行记录，本次整理未重新转换、未修改现用模型，也没有替换板端环境。仅完成本赛题时直接使用现有 RKNN 即可。

## 现用模型的真实约定

依据 `../../model/fire_yolo26.json`：

| 项目 | 当前配置 |
|---|---|
| 任务 | 火焰/烟雾目标检测，入口仅处理火焰 |
| 类别顺序 | `0=fire`、`1=smoke` |
| 目标平台 | `rk3588` |
| 输入 | 640×640，NHWC、uint8、RGB |
| 归一化 | 模型内嵌 mean=0、std=255，不能在外部重复除以255 |
| 补边颜色 | 114 |
| 输出 | 单输出 `(1, 6, 8400)`，`ultralytics_raw`，非归一化坐标 |
| 精度及编译器记录 | FP16，2.3.2 |
| 绑定的 RKNN SHA256 | `31f07bc29c7366b0ae86730084ed89b30bd0c347d4771d0350719f1ccea5dc5f` |

模型与元数据必须成套保留。不要把旧 YOLOv6 的 ONNX/RKNN 改名当作 YOLO26，也不能用通用 COCO 权重替代已经训练好 `fire/smoke` 的模型。

## 两条转换路线不能混用

### 路线 A：Ultralytics 官方 RKNN 导出

适合拿到自己训练完成的 YOLO26 检测 `best.pt` 后，在独立转换环境中尝试官方导出。官方支持 RK3588，并区分浮点和 INT8 导出，参数以实际安装版本为准。[官方 RKNN 导出说明](https://docs.ultralytics.com/integrations/rockchip-rknn)

以下为当前官方接口的 FP16 参考写法，在装好匹配工具链的转换电脑上执行：

```python
from ultralytics import YOLO

model = YOLO("/data/fire_training/weights/best.pt")
model.export(format="rknn", name="rk3588", imgsz=640, batch=1, quantize=16)
```

使用自己的本地权重和独立工作目录，保留导出目录内的真实元数据。先查看输出结构，再判断是否满足 V20 `detector.py` 的输入输出约定，不能仅凭 `.rknn` 后缀判断兼容。

特别注意：当前官方转换说明中的 INT8 路径会拆分出需要主机后处理的 `tail.onnx`。V20 没有实现这条 RKNN 加 `tail.onnx` 的执行链，不能直接将这种导出当成现用模型替换；本任务优先验证 FP16 单独 RKNN 路线。[官方 INT8 输出说明](https://docs.ultralytics.com/integrations/rockchip-rknn)

### 路线 B：瑞芯微 one2one 双输出参考

本目录的 `prepare_model.py` 从旧项目整理，针对 **YOLO26 one2one 检测头的两个分支**：类别分数和已解码 xyxy 框。瑞芯微示例使用这种结构，并采用置信度筛选及 TopK 后处理。[瑞芯微 YOLO26 示例](https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolo26/README.md)

在本次两类、640输入条件下，对应结构应为：

- 类别分数 `(1, 2, 8400)`。
- 像素坐标 xyxy 框 `(1, 4, 8400)`。

**该参考脚本不用于直接重转现用单输出 `(1, 6, 8400)` ONNX。** 它会核验检测头、分支来源和形状，结构不符合时拒绝继续，不会猜测输出节点或编造类别名称。V20 解析器另有 `rockchip_yolo26` 分支，但仍需实际转换和板端验证。

## 参考脚本用法

所有命令从 V20 根目录执行，转换本身在单独的 **x86_64 Linux** 电脑完成。板端无需安装转换依赖。

查看帮助不会加载转换库或下载模型：

```bash
python3 tools/model_conversion/prepare_model.py --help
```

从自己训练的 YOLO26 `.pt` 导出并转换：

```bash
python3 tools/model_conversion/prepare_model.py \
  --weights /data/fire_training/weights/best.pt \
  --labels tools/model_conversion/labels.example.json \
  --output tools/model_conversion/converted/fire_candidate.rknn
```

如果已经有符合上述双分支要求的 ONNX：

```bash
python3 tools/model_conversion/prepare_model.py \
  --onnx /data/fire_export/fire_one2one.onnx \
  --labels tools/model_conversion/labels.example.json \
  --output tools/model_conversion/converted/fire_candidate.rknn
```

`--weights`、`--onnx` 二选一且必须明确提供本地文件。标签示例是当前项目的 `fire、smoke` 顺序，新训练顺序不同必须修改；脚本不会自动使用通用权重或猜测标签。

默认 FP16。INT8 参考需另外提供真实部署画面的标定列表：

```bash
python3 tools/model_conversion/prepare_model.py \
  --onnx /data/fire_export/fire_one2one.onnx \
  --labels tools/model_conversion/labels.example.json \
  --quantize --dataset /data/fire_calibration/dataset.txt \
  --output tools/model_conversion/converted/fire_candidate_int8.rknn
```

标定列表每行一个图片路径，相对路径以列表所在目录为基准。脚本按推理约定制作补边后的临时标定输入。应包含真实摄像头条件下的火焰、无火、烟雾和不同光照画面；随附三张测试图不构成可靠标定集。

转换输出为新 `.rknn` 和同名 `.json`，后者标记 `rockchip_yolo26`、输出分支索引及真实类别。默认目录是本目录下的 `converted/`，不指向现用 `model/`。目标 RKNN 或 JSON 已存在时拒绝覆盖，应换一个候选名称。

## 版本与环境边界

`requirements-export-reference.txt` 是从旧项目保留的**历史依赖参考**，不是已经验证的 V20 新模型转换环境。不要把它当作最新兼容版本组合直接覆盖现有环境。转换脚本不自动安装依赖。

教师应在独立环境中按所选路线准备支持 YOLO26 的 Ultralytics/PyTorch、ONNX，以及匹配的 RKNN-Toolkit2；具体版本以官方兼容说明和板端 Runtime 为准。[RKNN-Toolkit2 官方仓库](https://github.com/airockchip/rknn-toolkit2)

现用模型的 2.3.2 编译记录及此前板端成功运行，不代表任意新导出图都能由 2.3.2 转换，也不代表最新编译器产物能被旧 Runtime 加载。若决定升级工具链，应先用候选模型验证，不直接替换当前可用环境。

## 放到板端前后怎么核对

1. 保存候选模型和它的真实元数据，记录导出库、编译器、输入输出形状、精度和类别顺序。不要复制现用 JSON 伪装成新模型元数据。
2. 复制候选文件到板端独立目录。先只读检查，再显式执行 NPU 探测：

   ```bash
   python3 tools/check_device.py --model tools/model_conversion/converted/fire_candidate.rknn
   python3 tools/check_device.py --model tools/model_conversion/converted/fire_candidate.rknn --npu-test --core all
   ```

3. 单张图检查框的位置、类别和置信度，再运行摄像头进行同画面比较：

   ```bash
   python3 fire_yolo26_v20_answer.py --model tools/model_conversion/converted/fire_candidate.rknn --source testimg/fire1.jpg
   ```

4. 再做静止、移动、区域边界及四种授权/声音场景。只有确认输出解析、火焰精度、延迟和现场声音均符合要求，才考虑替换正式模型并保留旧模型备份。

本次仅整理资料和参考脚本，没有执行训练、ONNX 导出、RKNN 编译或实机候选模型验证。
