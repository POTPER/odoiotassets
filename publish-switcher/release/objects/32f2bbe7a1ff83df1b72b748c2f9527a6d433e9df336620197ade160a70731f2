"""同步与更新相关错误。

SyncError：业务失败（路径非法、进程占用、校验失败等）。
Cancelled：用户或父进程取消；check_cancel 在长时间任务中检查取消标志。
"""
from __future__ import annotations


class SyncError(Exception):
    """可展示给用户的同步/更新失败。"""


class Cancelled(SyncError):
    """操作被取消，通常应回滚未提交的准备阶段。"""


def check_cancel(cancel):
    """若 cancel 事件已置位则抛出 Cancelled。"""
    if cancel and cancel.is_set():
        raise Cancelled("操作已取消，当前 publish 未修改。")
