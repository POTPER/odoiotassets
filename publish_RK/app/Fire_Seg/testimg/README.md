# V20 测试图片

`fire1.jpg`、`fire2.jpg`、`fire3.jpg` 原样复制自旧项目 `Fire_Seg_yolo26/testimg/`，用于沿用已有样例，不改动图片内容。

从 V20 根目录做一次 NPU 探测：

```bash
python3 tools/check_device.py --npu-test --image testimg/fire1.jpg --core all
```

查看单张图片识别结果：

```bash
python3 fire_yolo26_v20.py --source testimg/fire1.jpg
```

可分别将文件名换成 `fire2.jpg` 或 `fire3.jpg`。这里只做指定单图，不增加文件夹批量识别。单张图片不能完成四行教学 CSV：仍需在摄像头下分别展示三区及钢筋区授权前后，并稳定达到确认时间。

这些图片不是带标注的精度评估集，也不应仅凭三张图片验证模型准确率或建立 INT8 标定集。
