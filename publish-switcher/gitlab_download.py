"""Public GitLab/JiHu and self-hosted HTTPS GitLab API v4 adapters, Python 3.8."""
import json
import re
import urllib.parse

from core import Source, SyncError, relative_path, check_cancel


def connect(address, branch=""):
    parsed = urllib.parse.urlsplit(address.strip())
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SyncError("请输入完整 HTTPS 仓库项目地址，不接受登录信息或网页查询参数。")
    parts = path.split("/")
    if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", item) or item in (".", "..", "-") for item in parts):
        raise SyncError("GitLab/极狐地址须包含命名空间和项目，例如 https://jihulab.com/组织/项目。")
    source = Source(owner="/".join(parts[:-1]), repo=parts[-1], provider="gitlab", base_url=parsed.scheme + "://" + parsed.netloc)
    if not branch.strip():
        project = json.loads(source.fetch_bytes(source.api_base))
        branch = project.get("default_branch", "")
    if not isinstance(branch, str) or not branch.strip():
        raise SyncError("GitLab 项目没有有效的默认分支。")
    data = json.loads(source.fetch_bytes(source.api_base + "/repository/branches/" + urllib.parse.quote(branch.strip(), safe="")))
    commit = data.get("commit", {}).get("id", "")
    if data.get("name") != branch.strip() or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SyncError("GitLab 分支或提交校验失败。")
    source.commit = commit
    return source


def tree(source, cancel=None):
    nodes, seen, sizes = [], set(), {}
    for page in range(1, 1001):
        check_cancel(cancel)
        data = json.loads(source.fetch_bytes(source.tree_url() + "&page=" + str(page), cancel=cancel))
        if not isinstance(data, list):
            raise SyncError("GitLab 目录树响应无效，禁止对不完整目录同步。")
        if not data:
            return {"tree": nodes, "truncated": False}
        for entry in data:
            check_cancel(cancel)
            path = relative_path(entry.get("path"))
            if path in seen:
                raise SyncError("GitLab 分页返回重复路径，禁止同步不完整目录。")
            seen.add(path)
            node = {"path": path, "sha": entry.get("id"), "type": entry.get("type"), "mode": entry.get("mode")}
            if node["type"] == "blob":
                if node["sha"] not in sizes:
                    headers = source.head(source.api_base + "/repository/files/" + urllib.parse.quote(path, safe="") + "?ref=" + source.commit)
                    size = headers.get("x-gitlab-size", "")
                    if not size.isdigit() or headers.get("x-gitlab-blob-id") != node["sha"]:
                        raise SyncError("GitLab 文件元数据与固定提交不一致：" + path)
                    sizes[node["sha"]] = int(size)
                node["size"] = sizes[node["sha"]]
            nodes.append(node)
    raise SyncError("GitLab 目录树超过分页上限，禁止对不完整目录同步。")
