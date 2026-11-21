"""有界文本对比。

生成可读的差异摘要，限制输出体积，供工程师诊断文件内容差异。
"""
import difflib
import re
from publish_switcher.common.errors import check_cancel


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
