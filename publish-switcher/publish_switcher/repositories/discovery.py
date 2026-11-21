"""多仓库顺序探测。

按工程师保存的仓库列表依次检测可达性；应用更新过程中不改换数据源。
"""
import urllib.parse
import urllib.error

from publish_switcher.repositories.source import Source
from publish_switcher.common.errors import SyncError, Cancelled, check_cancel
from publish_switcher.repositories.catalog import DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY, repository_from_settings, remote_profiles


def normalize(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise SyncError("请设置 1 至 16 个按顺序查询的仓库。")
    result, seen = [], set()
    for value in values:
        value = {"url": value} if isinstance(value, str) else value
        if not isinstance(value, dict) or not isinstance(value.get("url"), str) or not isinstance(value.get("branch", ""), str):
            raise SyncError("仓库设置须包含 url 与可选 branch。")
        address, branch = value["url"].strip().rstrip("/"), value.get("branch", "").strip()
        if address.endswith(".git"):
            address = address[:-4]
        parsed = urllib.parse.urlsplit(address)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or len(parsed.path.strip("/").split("/")) < 2:
            raise SyncError("请输入不含登录信息或查询参数的完整 HTTPS 项目地址，不能仅填网站首页。")
        key = (address, branch)
        if key in seen:
            raise SyncError("仓库与分支重复：" + address)
        seen.add(key)
        result.append({"url": address, "branch": branch})
    return result


def candidates(config, primary=None, branch=None, explicit=False, extra=None):
    address = primary or repository_from_settings(config)
    first_branch = branch if branch is not None else config.get("branch", "")
    if explicit:
        return normalize([{"url": address, "branch": first_branch}] + list(extra or []))
    values = config.get("repository_sources")
    if values is None:
        values = [{"url": address, "branch": first_branch}]
        if address.rstrip("/") == DEFAULT_REPOSITORY:
            values.append({"url": LEGACY_DEFAULT_REPOSITORY, "branch": ""})
    else:
        values = normalize(values)
        if primary is not None:
            first = normalize([{"url": address, "branch": first_branch}])[0]
            values = [first] + [item for item in values if item["url"] != first["url"]]
        elif branch is not None:
            values[0] = dict(values[0], branch=branch)
    return normalize(values)


class ProfileUnavailable(SyncError):
    pass


def discover(values, presets, log=lambda message: None, cancel=None, profile=None, version=None, all_results=False):
    values = normalize(values)
    failures, results = [], []
    for number, item in enumerate(values, 1):
        check_cancel(cancel)
        address = item["url"]
        log("查询仓库 {}/{}：{}".format(number, len(values), address))
        try:
            source = Source.remote(address, item["branch"])
            source.cancel_event = cancel
            check_cancel(cancel)
            profiles = remote_profiles(source, presets)
            if profile is not None:
                profiles = [entry for entry in profiles if (entry.get("manifest") or entry["profile"])["id"] == profile
                            and (version is None or (entry.get("manifest") or entry["profile"])["version"] == version)]
            if not profiles:
                raise ProfileUnavailable("仓库中没有所需的可用方案。")
            log("仓库可用，已选定固定提交：{} / {}".format(address, source.commit[:12]))
            if not all_results:
                return profiles
            results.append(dict(item, status="可用", commit=source.commit, error=""))
        except Cancelled:
            raise
        except (SyncError, urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            last_failure = exc
            check_cancel(cancel)
            reason = str(exc)
            log("仓库不可用：{}；{}".format(address, reason))
            failures.append(address + "：" + reason)
            results.append(dict(item, status="失败", commit="", error=reason))
    if all_results:
        return results
    raise SyncError("所有仓库均不可用，尚未修改 publish：\n" + "\n".join(failures)) from last_failure
