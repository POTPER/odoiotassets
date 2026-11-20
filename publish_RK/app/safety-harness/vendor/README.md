# 屏幕捕获离线依赖

`mss-9.0.2-py3-none-any.whl` 来自 [PyPI官方MSS 9.0.2发布](https://pypi.org/project/mss/9.0.2/)，为纯Python wheel，支持Python 3.8+。无已安装的MSS时，`detect_screen.py` 校验SHA256后直接从wheel导入，不需要在板端下载、安装或解压，不修改系统Python。

- 大小：23867字节。
- SHA256：`685fa442cc96d8d88b4eb7aadbcccca7b858e789c9259b603e1ef0e435b60425`。
- [官方发布文件信息及哈希](https://pypi.org/pypi/mss/9.0.2/json)。
- 原始MIT许可证保存在wheel中的 `mss-9.0.2.dist-info/licenses/LICENSE.txt`。

复制项目到RK3588时请保留整个vendor目录。离线依赖解决MSS的下载和pip安装问题；OpenCV、NumPy、RKNNLite、X11桌面环境仍需在板子上具备。
