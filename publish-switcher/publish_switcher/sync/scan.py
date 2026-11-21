"""扫描本地 publish 目录。

枚举受管文件并计算指纹，供预览差异与严格更新删除多余文件使用。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from publish_switcher.common.errors import SyncError, check_cancel
from publish_switcher.sync.hashes import fingerprints
from publish_switcher.sync.manifests import managed


def scan(root, cancel=None, scoped=False, hash_filter=None):
    result = {}

    def visit(directory):
        with os.scandir(directory) as children:
            for child in children:
                check_cancel(cancel)
                path = Path(child.path)
                rel = path.relative_to(root).as_posix()
                s = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(s.st_mode):
                    result[rel] = {"type": "symlink", "target": os.readlink(path)}
                elif stat.S_ISDIR(s.st_mode):
                    if os.path.ismount(path):
                        raise SyncError(f"目录中存在嵌套挂载点，不能整体替换：{rel}")
                    result[rel] = {"type": "directory", "mode": f"0{stat.S_IMODE(s.st_mode) & 0o777:03o}"}
                    visit(path)
                elif stat.S_ISREG(s.st_mode):
                    sha256, git_sha1 = fingerprints(path, cancel) if not scoped or (hash_filter or managed)(rel) else (None, None)
                    result[rel] = {"type": "file", "mode": f"0{stat.S_IMODE(s.st_mode) & 0o777:03o}",
                                   "size": s.st_size, "sha256": sha256, "git_sha1": git_sha1}
                else:
                    raise SyncError(f"目录中存在不支持的特殊文件：{rel}")
    visit(root)
    return result
