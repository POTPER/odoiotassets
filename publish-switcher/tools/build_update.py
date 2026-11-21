"""Build the single installer ZIP and its publishable update information."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_switcher.updates.package import archive_entries, https_url, validate_payload, validate_release
from publish_switcher.version import VERSION


INSTALLER = Path("install/install_online.py")
LEGACY_ENTRIES = (
    "app.py", "core.py", "generate.py", "iot_runner.py", "permission_presets.py",
    "reference_ui.py", "ui_assets.py", "unified_update.py", "update_channels.py", "update_dialog.py",
)
DISTRIBUTION_GROUPS = {
    "publish_switcher": {".py"},
    "assets": {".png"},
    "icons": {".png", ".svg", ".ico"},
    "comparison-samples": {".py", ".json", ".md"},
    "docs": {".md"},
    "debs": {".deb", ".tsv"},
    "repository-template": {".json", ".md"},
}


def distribution_files(root):
    entries = {name: root / name for name in ("switcher.py", "README.md", "debs/SHA256SUMS")}
    entries.update({name: root / "tools/packaging/legacy" / name for name in LEGACY_ENTRIES})
    entries.update({name: root / "install" / name
                    for name in ("install.sh", "install_offline_debs.sh", "install_online.py")})
    entries["tool_update.py"] = root / "publish_switcher/updates/bootstrap.py"
    entries["version.py"] = root / "publish_switcher/version.py"
    for directory, suffixes in DISTRIBUTION_GROUPS.items():
        for path in (root / directory).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                entries[path.relative_to(root).as_posix()] = path
    return sorted(entries.items())


def installer_source(root):
    script = root / INSTALLER
    canonical = root / "publish_switcher/updates/package.py"
    source = script.read_text(encoding="utf-8")
    module_source = canonical.read_text(encoding="utf-8")
    tree = ast.parse(module_source)
    docstring_lines = tree.body[0].end_lineno if ast.get_docstring(tree) is not None else 0
    checks = "\n".join(module_source.splitlines()[docstring_lines:]).lstrip("\n").rstrip()
    start, end = "# BEGIN GENERATED PACKAGE CHECKS\n", "# END GENERATED PACKAGE CHECKS"
    before = source.split(start, 1)[0]
    after = source.split(end, 1)[1]
    return before + start + checks + "\n" + end + after


def verify_distribution(root):
    sizes = (16, 24, 32, 48, 64, 128, 256, 512)
    required = (
        "icons/swicher-v10.svg",
        *(f"icons/swicher-v10-{size}.png" for size in sizes),
        *(f"assets/ui/{name}.png" for name in (
            "sidebar-background-v10", "update-hero-64", "update-hero-112",
            "update-icon-24", "update-icon-40", "config-icon-24", "config-icon-40",
        )),
        *(f"comparison-samples/{side}/{name}.py" for side in ("local", "remote")
          for name in ("changed", "empty", "newlines", "permissions", "same")),
        "comparison-samples/remote/missing.json",
        "debs/PACKAGES.tsv", "debs/SHA256SUMS",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise RuntimeError("安装包缺少资源：" + "、".join(missing))
    checksums = (root / "debs/SHA256SUMS").read_text(encoding="utf-8").splitlines()
    if not checksums:
        raise RuntimeError("离线依赖校验清单为空。")
    for line in checksums:
        digest, name = line.split(maxsplit=1)
        dependency = root / "debs" / Path(name).name
        if not dependency.is_file() or hashlib.sha256(dependency.read_bytes()).hexdigest() != digest:
            raise RuntimeError("离线依赖校验失败：" + name)


def build(root, output, url):
    root, output = Path(root).resolve(), Path(output).resolve()
    if installer_source(root) != (root / INSTALLER).read_text(encoding="utf-8"):
        raise RuntimeError("独立安装脚本的校验代码已过期，请使用 --sync-installer 生成。")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "publish-switcher.zip"
    manifest = output / "switcher-update.json"
    files = distribution_files(root)
    with tempfile.NamedTemporaryFile(dir=output, prefix="switcher-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as package:
            for name, path in files:
                package.write(path, "publish-switcher/" + name)
        with tempfile.TemporaryDirectory(dir=output, prefix="verify-") as verification:
            with zipfile.ZipFile(temporary) as package:
                package.extractall(verification, members=archive_entries(package))
            contents = Path(verification) / "publish-switcher"
            validate_payload(contents, VERSION)
            verify_distribution(contents)
        release = validate_release({"schema_version": 1, "product": "publish-switcher", "version": VERSION,
                                    "url": https_url(url), "package_file": archive.name, "size": temporary.stat().st_size,
                                    "sha256": hashlib.sha256(temporary.read_bytes()).hexdigest(),
                                    "notes": "归类源码中的安装脚本和升级入口，按清单构建单包并保留旧版升级路径。"})
        with tempfile.NamedTemporaryFile(dir=output, prefix="manifest-", suffix=".tmp", delete=False,
                                         mode="w", encoding="utf-8") as stream:
            temporary_manifest = Path(stream.name)
            json.dump(release, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        try:
            temporary.replace(archive)
            temporary_manifest.replace(manifest)
        finally:
            if temporary_manifest.exists():
                temporary_manifest.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()
    return archive, manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 publish-switcher.zip 与 switcher-update.json，请一起发布。")
    parser.add_argument("--url", default="https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/publish-switcher.zip",
                        help="设备可访问的 HTTPS 安装包地址，可用 Releases 或对象存储")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "release"))
    parser.add_argument("--sync-installer", action="store_true", help="同步独立安装脚本中的共享校验代码")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if options.sync_installer:
        (root / INSTALLER).write_text(installer_source(root), encoding="utf-8")
        sys.exit(0)
    for result in build(root, options.output, options.url):
        print(result)
