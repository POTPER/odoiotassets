"""Read-only, verified file comparison and an isolated comparison demonstration."""
import difflib
import hashlib
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from core import (SyncError, check_cancel, content_matches, equivalent, fingerprints,
                  hash_field, managed, relative_path, validate_manifest, Engine, Source)

TEXT_LIMIT = 16 * 1024 * 1024
DIFF_INPUT_LIMIT = 1024 * 1024
DIFF_LINE_LIMIT = 10000
DIFF_OUTPUT_LINES = 2000
DIFF_OUTPUT_CHARS = 250000


def text_diff(local, remote, path, local_exists=True, remote_exists=True, cancel=None,
              old_label="本地", new_label="远端"):
    """Preview local -> remote changes. Normalize CRLF/BOM for display only."""
    check_cancel(cancel)
    result = {"rows": [], "added": 0, "deleted": 0, "truncated": False, "kind": "same", "note": "文本内容一致，没有逐行变更。"}
    local, remote = local if local_exists else b"", remote if remote_exists else b""
    if local is not None and local == remote and local_exists == remote_exists:
        if not local_exists:
            result["note"] = "双方文件都不存在，无文本可比较。"
        return result
    if local is None or remote is None or max(len(local), len(remote)) > DIFF_INPUT_LIMIT:
        result.update(kind="limited", note="逐行预览限每侧 1 MiB；文件超过限制，仅保留诊断摘要。")
        return result
    if b"\x00" in local or b"\x00" in remote:
        result.update(kind="binary", note="文件含 NUL 字节，不作为普通文本显示差异。")
        return result
    try:
        left, right = local.decode("utf-8-sig"), remote.decode("utf-8-sig")
    except UnicodeError:
        result.update(kind="binary", note="至少一侧不是有效 UTF-8 文本，无法显示逐行文本差异。")
        return result
    left, right = left.replace("\r\n", "\n"), right.replace("\r\n", "\n")
    if left == right and local_exists == remote_exists:
        if local != remote:
            result.update(kind="format_only", note=text_reason(local, remote) + "；文字内容一致，无其他逐行变更。")
        return result
    line_counts = [value.count("\n") + int(bool(value) and not value.endswith("\n")) for value in (left, right)]
    if max(line_counts) > DIFF_LINE_LIMIT:
        result.update(kind="limited", note="逐行预览限每侧 10000 行；文件超过限制，仅保留诊断摘要。")
        return result
    def split_lines(value):
        parts = value.split("\n")
        return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    old_name, new_name = old_label + "/" + path if local_exists else "/dev/null", new_label + "/" + path if remote_exists else "/dev/null"
    result.update(kind="changes", note="以{}为旧版、{}为新版。- 红色表示{}被删除的行；+ 绿色表示{}新增的行。上下文保留 3 行。".format(
        old_label, new_label, old_label, new_label))
    old_line, new_line, chars = None, None, 0
    for index, line in enumerate(difflib.unified_diff(split_lines(left), split_lines(right), fromfile=old_name, tofile=new_name, n=3)):
        check_cancel(cancel)
        if len(result["rows"]) >= DIFF_OUTPUT_LINES or chars + len(line) > DIFF_OUTPUT_CHARS:
            result["truncated"] = True
            break
        row = {"text": line[:-1] if line.endswith("\n") else line, "old_line": None, "new_line": None}
        if index < 2:
            row["kind"] = "header"
        elif line.startswith("@@"):
            row["kind"] = "hunk"
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            old_line, new_line = int(match[1]), int(match[2])
        elif line.startswith("+"):
            row.update(kind="add", new_line=new_line)
            new_line += 1
            result["added"] += 1
        elif line.startswith("-"):
            row.update(kind="delete", old_line=old_line)
            old_line += 1
            result["deleted"] += 1
        else:
            row.update(kind="context", old_line=old_line, new_line=new_line)
            old_line += 1
            new_line += 1
        result["rows"].append(row)
        chars += len(line)
        if row["kind"] in ("add", "delete", "context") and not line.endswith("\n"):
            note = "\\ No newline at end of file"
            if len(result["rows"]) >= DIFF_OUTPUT_LINES or chars + len(note) > DIFF_OUTPUT_CHARS:
                result["truncated"] = True
                break
            result["rows"].append({"kind": "note", "text": note, "old_line": None, "new_line": None})
            chars += len(note)
    if not result["rows"] and not result["truncated"]:
        result["rows"] = [{"kind": "header", "text": "--- " + old_name}, {"kind": "header", "text": "+++ " + new_name}]
        result["note"] = "空文件的新增或删除，没有可显示的文本行。"
    if result["truncated"]:
        result["note"] += " 预览已截断，新增/删除数量仅统计已显示部分。"
    return result


def visible_diff_line(text):
    # Make control characters visible; never allow source text to inject terminal escapes.
    return "".join(c if (ord(c) >= 32 and not 127 <= ord(c) <= 159) or c == "\t" else "\\x{:02x}".format(ord(c)) for c in text)


def format_diff(diff, color=False):
    colors = {"add": "\x1b[32m", "delete": "\x1b[31m", "hunk": "\x1b[36m"}
    lines = [diff["note"], "{}新增 {} 行，删除 {} 行。".format("已显示：" if diff["truncated"] else "", diff["added"], diff["deleted"])]
    for row in diff["rows"]:
        line = visible_diff_line(row["text"])
        prefix = colors.get(row["kind"], "") if color else ""
        lines.append(prefix + line + ("\x1b[0m" if prefix else ""))
    return "\n".join(lines)


def text_reason(local, remote):
    if local == remote:
        return "字节完全一致"
    try:
        left, right = local.decode("utf-8"), remote.decode("utf-8")
    except UnicodeError:
        return "字节不同，至少一侧不是有效 UTF-8 文本"
    if left.replace("\r\n", "\n") == right.replace("\r\n", "\n"):
        return "仅换行不同（CRLF / LF）"
    left_bom = left[1:] if left.startswith("\ufeff") else left
    right_bom = right[1:] if right.startswith("\ufeff") else right
    if left_bom == right_bom:
        return "仅 UTF-8 BOM 不同"
    if left_bom.replace("\r\n", "\n") == right_bom.replace("\r\n", "\n"):
        return "仅 UTF-8 BOM 和换行不同"
    return "UTF-8 文本存在其他差异（可能是代码、数据、空格或格式）"


def _inspect(path, cancel=None):
    before = path.stat()
    sha256, git_sha1 = fingerprints(path, cancel)
    with path.open("rb") as stream:
        raw = stream.read(TEXT_LIMIT + 1)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino, before.st_mode) != (after.st_size, after.st_mtime_ns, after.st_ino, after.st_mode):
        raise SyncError("诊断期间文件发生变化，请重新诊断：" + str(path))
    if len(raw) <= TEXT_LIMIT and hashlib.sha256(raw).hexdigest() != sha256:
        raise SyncError("诊断期间文件发生变化，请重新诊断：" + str(path))
    return {"type": "file", "size": after.st_size, "sha256": sha256, "git_sha1": git_sha1,
            "mode": "0{:03o}".format(stat.S_IMODE(after.st_mode) & 0o777)}, raw if len(raw) <= TEXT_LIMIT else None


def diagnose_file(engine, manifest, source, path, offline=False, cancel=None, sync_permissions=False):
    validate_manifest(manifest)
    relative_path(path)
    if not engine.manages(path):
        raise SyncError("该文件格式未勾选，请先在同步格式中选择。")
    entry = next((e for e in manifest["entries"] if e["path"] == path and e["type"] == "file"), None)
    with engine.lock():
        if engine.journal.exists() or (engine.state / "config-transaction.json").exists() or (engine.state / "assets-transaction.json").exists():
            raise SyncError("存在未完成的切换，请先在工具中恢复事务，再运行只读诊断。")
        if engine.target.is_symlink():
            raise SyncError("目标目录不能是符号链接。")
        current = engine.target
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                raise SyncError("诊断路径含符号链接：" + path)
        local_path = engine.target / path
        if local_path.exists() and not local_path.is_file():
            raise SyncError("本地目标不是普通文件：" + path)
        local, local_raw = _inspect(local_path, cancel) if local_path.exists() else (None, None)
        report = {"path": path, "local_path": str(local_path), "profile": manifest.get("name", manifest["id"]),
                  "version": manifest["version"], "commit": source.commit, "local": local, "remote": None,
                  "sync_permissions": bool(sync_permissions)}
        if entry is None:
            report.update(status="仅本地" if local else "双方均缺失", reason="所选方案不包含这个文件", origin="无远端条目")
            report["diff"] = text_diff(local_raw, b"", path, local_exists=local is not None, remote_exists=False, cancel=cancel)
            return report
        check_cancel(cancel)
        # Downloads are verified against this exact manifest, outside publish, and removed afterwards.
        with tempfile.TemporaryDirectory(prefix="diagnose-", dir=engine.state) as directory:
            remote_path = engine._object(entry)
            if engine.cached(entry, cancel):
                origin = "已校验缓存"
            else:
                if offline:
                    raise SyncError("离线诊断需要完整缓存该文件；请联网诊断一次或先缓存方案。")
                remote_path = Path(directory) / "remote"
                key = hash_field(entry)
                expected = ("git:" if key == "git_sha1" else "") + entry[key]
                source.download(entry["source"], remote_path, entry["size"], expected, cancel, lambda count: None)
                origin = "本地导入来源" if source.local else "远端固定提交下载"
            remote, remote_raw = _inspect(remote_path, cancel)
            if not content_matches(remote, entry):
                raise SyncError("诊断来源内容与所选方案校验值不匹配。")
            remote["mode"] = entry["mode"]
            if local is None:
                status, reason = "新增", "本地文件不存在"
            elif content_matches(local, entry):
                status = "相同" if equivalent(local, entry) else "权限不同"
                reason = "字节完全一致" if status == "相同" else "字节完全一致，仅 Linux 权限不同"
            else:
                status = "内容不同"
                reason = text_reason(local_raw, remote_raw) if local_raw is not None and remote_raw is not None else "内容不同；超过 16 MiB，未进行文本原因分析"
            report.update(remote=remote, status=status, reason=reason, origin=origin, source=str(source.url(entry["source"])))
            report["diff"] = text_diff(local_raw, remote_raw, path, local_exists=local is not None, cancel=cancel)
            check_cancel(cancel)
            return report


def format_report(report, include_diff=True, color=False):
    lines = ["文件诊断：" + report["path"], "方案：{} / {}".format(report["profile"], report["version"]),
             "结果：" + report["status"], "原因：" + report["reason"], "本地：" + report["local_path"],
             "来源：" + report["origin"]]
    if report.get("commit"):
        lines.append("固定提交：" + report["commit"])
    if report.get("source"):
        lines.append("来源地址：" + report["source"])
    for label, item in (("本地", report["local"]), ("远端", report["remote"])):
        if item is None:
            lines.append(label + "文件：不存在")
        else:
            lines.extend(["{}：{} 字节；权限 {}".format(label, item["size"], item["mode"]),
                          label + " SHA-256：" + item["sha256"], label + " Git blob SHA-1：" + item["git_sha1"]])
    lines.append("权限为读/写/执行位，远端权限来自清单或 Git 文件模式；Windows 不比较 Linux 权限。")
    lines.append("权限策略：" + ("严格更新按仓库同步权限；增量仍跳过已有文件。" if report.get("sync_permissions") else "默认保留本地已有文件权限；新文件采用仓库权限。权限差异本身不会触发替换。"))
    lines.append("只读诊断：不上传本地内容，不修改 publish；仅换行不同仍按原规则显示内容不同。")
    if include_diff and report.get("diff"):
        lines.extend(["", "逐行文本差异（本地 → 远端）：", format_diff(report["diff"], color=color)])
    elif report.get("diff"):
        diff = report["diff"]
        lines.append("文本预览：" + diff["note"])
        if diff["kind"] == "changes":
            lines.append("已显示新增 {} 行，删除 {} 行。".format(diff["added"], diff["deleted"]))
    return "\n".join(lines)


def comparison_self_test(cancel=None):
    fixtures = Path(__file__).parent / "comparison-samples"
    with tempfile.TemporaryDirectory(prefix="publish-switcher-self-test-") as directory:
        base = Path(directory)
        target, remote = base / "publish", base / "remote"
        shutil.copytree(fixtures / "local", target)
        shutil.copytree(fixtures / "remote", remote)
        for path in target.iterdir():
            os.chmod(path, 0o644)
        os.chmod(target / "permissions.py", 0o755)
        entries = [{"type": "file", "path": p.name, "source": p.name, "size": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "mode": "0644"} for p in sorted(remote.iterdir())]
        manifest = {"schema_version": 1, "id": "self-test", "name": "独立比较自测", "version": "1", "entries": entries}
        engine, source = Engine(target), Source(local=remote)
        expected = {"same.py": "相同", "newlines.py": "内容不同", "changed.py": "内容不同",
                    "empty.py": "内容不同", "missing.json": "新增",
                    "permissions.py": "权限不同" if os.name == "posix" else "相同"}
        comparison = {r["path"]: r["status"] for r in engine.preview(manifest, sync_permissions=True)["comparison"]}
        lines = ["比较自测：使用随工具提供的样例，在独立临时目录执行，不读取你的 publish。"]
        for name, status in expected.items():
            check_cancel(cancel)
            report = diagnose_file(engine, manifest, source, name, cancel=cancel, sync_permissions=True)
            if comparison[name] != status or report["status"] != status:
                raise SyncError("比较自测失败：" + name)
            if name == "newlines.py" and report["reason"] != "仅换行不同（CRLF / LF）":
                raise SyncError("换行识别自测失败。")
            lines.append("通过：{} → {}；{}".format(name, status, report["reason"]))
        lines.append("全部 6 项通过。Windows 的权限样例仅验证内容；Linux 会验证权限差异。")
        preserved = engine.preview(manifest)
        if ("替换", "permissions.py") in preserved["changes"]:
            raise SyncError("默认保留权限策略自测失败。")
        lines.append("通过：默认保留本地权限，不因权限差异替换文件。")
        return "\n".join(lines)
