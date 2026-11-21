# 功能模块中文地图

注释写在各文件模块头与包 `__init__.py` 中，按下表对照即可。

```mermaid
flowchart TB
    subgraph 入口
      A[switcher.py / app.py]
    end
    subgraph 包 publish_switcher
      B[cli 命令行]
      C[gui 图形界面]
      D[sync 文件同步]
      E[repositories 仓库]
      F[configuration 配置切换]
      G[updates 程序更新]
      H[demo IoT Demo]
      I[common 公共基础]
    end
    A --> B
    A --> C
    C --> D
    C --> F
    C --> G
    C --> H
    B --> D
    D --> E
    G --> D
```

| 功能 | 主要位置 |
|------|----------|
| 文件同步 / 严格更新 | `sync/` |
| 资源仓库与多通道 | `repositories/`、`updates/channels.py` |
| 配置切换与可见性 | `configuration/` |
| 启动自动更新与进度窗口 | `updates/startup.py`、`gui/startup.py` |
| 一键更新与独立恢复 | `updates/unified.py`、`updates/bootstrap.py` |
| IoT Demo | `demo/` |
| 用户界面 / 工程师面板 | `gui/` |
| SSH 菜单 | `cli/` |
