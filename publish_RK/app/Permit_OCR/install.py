"""在 RK3588 上从随附的 wheel 离线安装 Demo 依赖。"""

import argparse
import errno
import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


DEMO_DIR = Path(__file__).resolve().parent
LOCK_FILE = DEMO_DIR / "requirements-rk3588.lock"
WHEELS = DEMO_DIR / "wheels"
PIP_WHEEL = WHEELS / "pip-25.0.1-py3-none-any.whl"
DEPS_ROOT = DEMO_DIR / ".python-deps"


def supports_offline_bundle():
    return (
        sys.platform == "linux"
        and platform.machine().lower() in {"aarch64", "arm64"}
        and sys.implementation.name == "cpython"
        and sys.version_info[:2] == (3, 8)
    )


def dependency_path():
    digest = hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest()
    return DEPS_ROOT / digest[:16]


def local_dependencies():
    if supports_offline_bundle() and LOCK_FILE.is_file():
        installed = dependency_path()
        if installed.is_dir():
            return installed
        # 兼容此前按 README 直接安装到 .python-deps 的环境。
        if (DEPS_ROOT / "rapidocr_onnxruntime").is_dir():
            return DEPS_ROOT
    return None


def install():
    if not supports_offline_bundle():
        raise RuntimeError("请在 RK3588 的 ARM64 Linux 上使用 Python 3.8 运行 install.py。")
    if not LOCK_FILE.is_file():
        raise RuntimeError(f"缺少 {LOCK_FILE.name}，请重新解压完整离线包。")

    destination = dependency_path()
    if destination.is_dir():
        print("当前版本的依赖已安装。可以运行 python3 demo.py。")
        return
    if not PIP_WHEEL.is_file():
        raise RuntimeError("缺少离线安装器，请将完整的 wheels 目录复制到 Permit_OCR 下。")

    DEPS_ROOT.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(PIP_WHEEL), "PIP_CONFIG_FILE": os.devnull}
    print("正在从 wheels 目录离线安装 OCR 依赖…", flush=True)
    with TemporaryDirectory(dir=DEPS_ROOT) as staging:
        staged = Path(staging) / "packages"
        command = [
            sys.executable, "-S", "-m", "pip", "--isolated", "--disable-pip-version-check",
            "install", "--no-index", "--find-links", str(WHEELS), "--only-binary=:all:",
            "--require-hashes", "--target", str(staged), "-r", str(LOCK_FILE),
        ]
        subprocess.run(command, cwd=DEMO_DIR, env=env, check=True)
        try:
            staged.rename(destination)
        except OSError as exc:
            # 另一个安装进程可能已先完成同一版本的安装。
            if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY} or not destination.is_dir():
                raise

    print("离线安装完成。可以运行 python3 demo.py。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线安装 RK3588 版 OCR Demo 的 Python 依赖")
    parser.parse_args(argv)
    try:
        install()
    except subprocess.CalledProcessError as exc:
        print("离线安装失败。请查看上方的 pip 错误，并核对 wheels 目录是否完整。", file=sys.stderr)
        return exc.returncode if exc.returncode > 0 else 1
    except (OSError, RuntimeError) as exc:
        print(f"离线安装失败。{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
