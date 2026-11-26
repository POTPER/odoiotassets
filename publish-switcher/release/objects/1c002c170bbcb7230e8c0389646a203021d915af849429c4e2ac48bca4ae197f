# 配置与资源仓库

这是公开资源仓库的初始模板。`catalog.json` 的列表初始为空。

在仓库外放置完整的 publish 副本，用工具的 `generate.py` 将方案生成到本仓库目录：

```bash
python3 /path/to/publish-switcher/generate.py /path/to/complete/publish /path/to/this-repository --id competition --name 比赛版 --version 1.0.0
```

生成后上传输出目录。生成器会复制 .py/.json/.ttf 和 Assets 目录内的普通资源文件，其他文件只记录提示信息。Switcher 的“更新文件”页处理勾选格式，“Assets 资源”页比较内容并只下载缺失资源，已有同名文件和本地额外资源保留。

Assets 大文件可以用 generate.py --external-map 映射到 Releases HTTPS 地址，映射格式为相对文件路径到下载地址的 JSON 对象；实际文件留在完整 publish 源副本中用于生成大小和 SHA-256，映射文件不会再复制进输出仓库。不要以 Git LFS 指针代替实际资源，工具会拒绝部署指针。

工具默认不勾选主程序、模型或驱动；客户端可以自行选择格式。发布额外格式请用 generate.py --extensions .py,.json,.ttf,.otf 制作新版本，未发布的条目标记 payload_available=false，只提示不下载。不要把备份、工具设置或凭证放进公开仓库。
