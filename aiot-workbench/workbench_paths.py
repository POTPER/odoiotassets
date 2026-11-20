"""Shared first-run path defaults; saved deployment paths always take priority."""
from pathlib import Path

DEFAULT_PUBLISH = Path("/home/ubuntu/linux-arm64/publish")
ALTERNATE_PUBLISH = Path("/home/ubuntu/linux_arm64/publish")


def default_publish():
    for path in (DEFAULT_PUBLISH, ALTERNATE_PUBLISH):
        if path.is_dir():
            return str(path)
    return str(DEFAULT_PUBLISH)
