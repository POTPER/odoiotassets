"""Build the single installer ZIP and its publishable update information."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_update import https_url, validate_release
from version import VERSION
from compat import is_relative_to


def build(root, output, url):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "publish-switcher.zip"
    manifest = output / "switcher-update.json"
    files = sorted(path for path in root.rglob("*") if path.is_file()
                   and not set(path.relative_to(root).parts) & {".git", ".tmp", "__pycache__"}
                   and path.suffix not in (".pyc", ".pyo", ".tmp")
                   and not is_relative_to(path, root / "release")
                   and not (output != root and is_relative_to(path, output))
                   and path not in (archive, manifest))
    with tempfile.NamedTemporaryFile(dir=output, prefix="switcher-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as package:
            for path in files:
                package.write(path, "publish-switcher/" + path.relative_to(root).as_posix())
        with zipfile.ZipFile(temporary) as package:
            if package.testzip():
                raise RuntimeError("安装包校验失败。")
        temporary.replace(archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    release = validate_release({"schema_version": 1, "product": "publish-switcher", "version": VERSION,
                                "url": https_url(url), "package_file": archive.name, "size": archive.stat().st_size,
                                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                "notes": "小窗一键更新 Switcher 与 RK publish，自动检查并严格同步已选格式；用户配置列表默认隐藏 . / F 前缀，可由 JSON 明确开放。"})
    manifest.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive, manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 publish-switcher.zip 与 switcher-update.json，请一起发布。")
    parser.add_argument("--url", default="https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/publish-switcher.zip",
                        help="设备可访问的 HTTPS 安装包地址，可用 Releases 或对象存储")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "release"))
    options = parser.parse_args()
    for result in build(Path(__file__).resolve().parents[1], options.output, options.url):
        print(result)
