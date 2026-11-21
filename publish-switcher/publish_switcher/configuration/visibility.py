"""配置可见性规则。

解析 versions.json：前缀规则与逐目录覆盖，只影响用户界面列表，不改文件权限。
"""
import hashlib
import json

from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import atomic_json, relative_path

POLICY_FILE = "versions.json"
DEFAULT_POLICY = {"default_user_visible": True, "rules": [], "versions": {}}
METADATA_FIELDS = {"release_version": 64, "updated_at": 64, "description": 512}


def validate_policy(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_POLICY):
        raise SyncError("versions.json 只支持 default_user_visible、rules 和 versions 字段。")
    default = value.get("default_user_visible", True)
    rules = value.get("rules", [])
    versions = value.get("versions", {})
    if type(default) is not bool or not isinstance(rules, list) or not isinstance(versions, dict):
        raise SyncError("版本显示规则格式无效，请检查默认可见性、规则数组和目录设置。")
    for rule in rules:
        if (not isinstance(rule, dict) or set(rule) != {"prefix", "user_visible"}
                or not isinstance(rule["prefix"], str) or not rule["prefix"]
                or type(rule["user_visible"]) is not bool):
            raise SyncError("每条前缀规则需要非空 prefix 和布尔值 user_visible。")
    for name, options in versions.items():
        relative_path(name)
        if "/" in name or "\\" in name or not isinstance(options, dict) or set(options) - ({"user_visible", "display_name", "order"} | set(METADATA_FIELDS)):
            raise SyncError("目录设置仅支持显示规则及 release_version、updated_at、description 元数据。")
        if "user_visible" in options and type(options["user_visible"]) is not bool:
            raise SyncError(name + " 的 user_visible 必须为 true 或 false。")
        if "display_name" in options and (not isinstance(options["display_name"], str) or not options["display_name"].strip()):
            raise SyncError(name + " 的 display_name 必须是非空文字。")
        if "order" in options and type(options["order"]) is not int:
            raise SyncError(name + " 的 order 必须是整数。")
        for field, limit in METADATA_FIELDS.items():
            if field in options and (not isinstance(options[field], str) or len(options[field]) > limit
                                     or any(ord(c) < 32 for c in options[field])):
                raise SyncError("{} 的 {} 必须是 {} 字以内的单行文字。".format(name, field, limit))
    return json.loads(json.dumps({"default_user_visible": default, "rules": rules, "versions": versions}))


def resolve_version(policy, name):
    visible = False if name.startswith((".", "F")) else policy["default_user_visible"]
    for rule in policy["rules"]:
        if name.startswith(rule["prefix"]):
            visible = rule["user_visible"]
            break
    options = policy["versions"].get(name, {})
    return dict({"user_visible": options.get("user_visible", visible),
                 "display_name": options.get("display_name", name), "order": options.get("order", 0)},
                **{field: options.get(field, "") for field in METADATA_FIELDS})


def read_policy(engine):
    root = engine.target / "config"
    path = root / POLICY_FILE
    if root.is_symlink() or path.is_symlink():
        raise SyncError("版本显示规则路径不能包含符号链接。")
    if not path.exists():
        return validate_policy({}), None
    try:
        if path.stat().st_size > 1024 * 1024:
            raise SyncError("versions.json 大于 1 MiB。")
        raw = path.read_bytes()
        policy = validate_policy(json.loads(raw.decode("utf-8-sig")))
        return policy, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError) as exc:
        raise SyncError("无法读取版本显示规则 versions.json：" + str(exc)) from exc


def require_visible(engine, name):
    policy, snapshot = read_policy(engine)
    result = resolve_version(policy, name)
    if not result["user_visible"]:
        raise SyncError("该配置未对用户开放，请刷新版本列表。")
    return result, snapshot


def save_policy(engine, policy, expected):
    policy = validate_policy(policy)
    with engine.lock():
        _, current = read_policy(engine)
        if current != expected:
            raise SyncError("编辑期间 versions.json 发生变化，请关闭窗口后重新打开。")
        root = engine.target / "config"
        root.mkdir(exist_ok=True)
        atomic_json(root / POLICY_FILE, policy)
