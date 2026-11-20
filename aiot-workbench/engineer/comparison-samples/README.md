# 文件比较样例

这是自测数据，不是要部署到 publish 的业务资源。不要执行样例中的脚本，也无需将这些文件上传到资源仓库。

在工具目录运行 `python3 switcher.py self-test`，或点击 GUI 的“运行比较自测”。工具将 local / remote 文件复制到临时目录验证，测试结束后删除临时目录，不读取或修改你的 publish。

| 文件 | 本地与来源的关系 | 预期结果 |
|---|---|---|
| same.py | 完全一致 | 相同，GUI 对应绿色 |
| newlines.py | 本地 CRLF、来源 LF | 内容不同，原因仅换行不同 |
| changed.py | print 中的字符串不同 | 内容不同，其他文本差异 |
| permissions.py | 内容一致，自测时设置本地 0755、远端 0644 | Linux 权限不同；Windows 相同 |
| empty.py | 本地零字节、来源完整 | 内容不同 |
| missing.json | 仅来源存在 | 新增 |

newlines.py 的换行是有意设计的。搬运工具时请保留原始字节；自测会检查换行识别是否正确。
