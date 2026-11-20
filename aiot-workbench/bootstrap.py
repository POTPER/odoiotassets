"""Explicit import paths for every executable, including detached sessions."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def configure():
    for directory in (ROOT, ROOT / "launcher", ROOT / "engineer", ROOT / "shared"):
        value = str(directory)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)
