# 施工许可证演示卡 OCR

适用于随附 `sample.png` 的单面版式。可以识别一张整卡图片，也可以用摄像头抓拍整张卡。安装依赖后由 RapidOCR 在本机 CPU 上识别，模型随安装包提供。

## RK3588 离线安装

离线配置放在 `Permit_OCR/` 下。`wheels/` 存放 Python 依赖和 pip 安装器，`requirements-rk3588.lock` 记录版本和 SHA-256 校验值。中文 OCR 模型随 RapidOCR wheel 提供。适用环境为 ARM64（`aarch64`）、Python 3.8.x 和 glibc 2.27 或更新版本。

将 `Permit_OCR/` 连同 `wheels/` 拷到板上，或拷贝目录里的 `Permit_OCR_RK3588_ARM64_Python38_offline.zip` 并解压。压缩包内已有一份完整的 `Permit_OCR/`。

```bash
python3 -m zipfile -e Permit_OCR_RK3588_ARM64_Python38_offline.zip .
```

在板上进入 `Permit_OCR/` 后，运行 `install.py` 安装一次，再用 `--sample` 识别样图：

```bash
python3 install.py
python3 demo.py --sample
```

`install.py` 使用随包的 pip，从 `wheels/` 安装并校验依赖，安装目录为 `.python-deps/`，普通用户即可执行。同版本重复运行会直接提示已安装。系统须已有 ARM64 Python 3.8 和 OpenCV 所需的系统库。若提示缺少 `libGL.so.1` 或 `libgthread-2.0.so.0`，需从与板卡 Ubuntu 版本一致的软件源另行准备提供这些库的 ARM64 `.deb` 包及其依赖。在 Ubuntu 20.04 上对应 `libgl1` 和 `libglib2.0-0`。

## 联网安装与运行样图

将整个 `Permit_OCR` 目录放到电脑或 RK3588 板卡上，进入该目录后运行以下命令。使用 Python 3.8 或更新版本。Ubuntu 上可将 `python` 换成 `python3`。

```bash
python -m pip install -r requirements.txt
python demo.py --sample
```

控制台会显示结构化字段，完整结果保存为 `output/permit.json`。样图应识别出编号 `DEMO-2026-001`、工程名称「智能物联网综合实训中心建设工程」、合同价格「3600万元」及五家参建单位各自的职务和姓名。

## 识别自己的图片

```bash
python demo.py --image 整张卡牌.png --output output/我的卡牌.json
```

## 摄像头抓拍

```bash
# RK3588 图形桌面，默认使用 /dev/video41
python3 demo.py

# camera.py 也可以直接启动摄像头识别
python3 camera.py

# 板上的摄像头编号为 0 时，显式指定设备
python3 camera.py --camera /dev/video0
```

摄像头窗口左侧显示实时画面和最近一次抓拍的绿色文字框，右侧显示默认信息表。让卡面左右两栏完整入镜并对焦，按一次 **空格**扫描整张卡。识别到的字段自动填入表格并标为「已填写」，空项显示「待扫描」。

OCR 在后台运行，识别时实时预览仍会刷新。识别完成后，再按 **空格**即可开始下一次整卡扫描，每次都根据本次抓拍重新填写表格。

- **缺少必填项 · 待重拍** 表示本次还有必填项未识别，请对准整张卡重新扫描。
- **已录入** 表示许可证编号及各参建单位的名称、职务和姓名已齐全，并已自动保存到 `output/records.json`。
- **该编号已录入** 表示历史里已有同一编号，窗口会显示首次录入时间。历史按编号保存每张卡首次自动录入时的表格。

`output/permit.json` 保存最近一次识别的字段、OCR 原文和录入状态，`output/permit-marked.png` 保存最新标注图。使用 `--output` 时，历史和标注图与指定的 JSON 位于同一目录。样图和图片命令可用于核对 OCR 输出。

按 **R** 清空当前信息表，按 **Q** 或 **Esc** 退出。清空或退出时，正在处理的抓拍会被丢弃。

RK3588 请从图形桌面的终端启动预览。若提示无法打开 `/dev/video41`，可运行 `ls /dev/video*` 查看设备，再用 `--camera` 指定实际编号，并确认摄像头未被其他程序占用。Windows 默认使用设备 `0`。

## 输出字段

- 证件名称、许可证编号（JSON 键 `编号`）、发证机构、发证日期。
- 建设单位、工程名称、建设地址、建设规模、合同工期、合同价格、备注。
- 勘察、设计、施工、监理、工程总承包单位各自的单位名称、职务、姓名。

未提取到的值写为 `null`，字段名列在 `未识别字段`。同一张图内，同一字段多次匹配时取评分较高的结果。JSON 的 `原始识别` 保留本次图片的 OCR 文本、四边形坐标和置信度，便于核对。编号符合 `DEM0-四位年份-三位序号` 时，按演示卡的编号格式把前缀校正为 `DEMO`。

## 代码编辑区

打开 `permit_fields.py`，在顶部的「代码编辑区」修改需要保存到 JSON 的字段。字段名本身也能作为卡面标签，括号内可列出卡面上的其他写法。标签和值可用冒号或空格分隔，也可以位于表格同一行的相邻单元格。

- 在 `FIELD_LABELS` 中加入 `"建设性质": ("工程性质",),` 后，识别到任一标签都会写入 JSON 的 `建设性质`。
- 在 `PARTICIPANT_LABELS` 中增加单位类别，在 `ROLES` 中增加卡面上的负责人职务。遇到分两行的单位标签，可以填入 `WRAPPED_UNIT_LABELS`。
- 在 `PARTICIPANT_EXTRA_LABELS` 中取消 `"联系电话": ("电话",),` 的注释后，每个单位的 JSON 会增加 `联系电话` 字段，从该单位所在行读取。
- 在 `REQUIRED_EXTRA_FIELDS` 中添加顶层字段名，可以让自动录入也等待这些字段填写。

修改后重新运行 `python3 demo.py --sample` 可核对输出结构，或用 `--image` 检查自己的卡片。新增字段会进入 JSON 和抓拍标注。将顶层字段名放进 `JSON_ONLY_FIELDS` 可以只保留 JSON 输出。

模型和依赖包见 [RapidOCR 1.2.3](https://pypi.org/project/rapidocr-onnxruntime/1.2.3/)、[ONNX Runtime](https://pypi.org/project/onnxruntime/1.16.3/) 和 [OpenCV](https://pypi.org/project/opencv-python/4.10.0.84/)。

录入表自带思源黑体，许可见 `fonts/OFL.txt`。[Adobe Source Han Sans 2.005R](https://github.com/adobe-fonts/source-han-sans/tree/2.005R)
