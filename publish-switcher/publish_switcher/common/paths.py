"""安装根目录与随包资源路径。

INSTALL_ROOT 指向工具安装目录（含 icons、assets），用于定位图标与发布资源。
"""
from pathlib import Path


INSTALL_ROOT = Path(__file__).resolve().parents[2]
