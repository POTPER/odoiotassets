"""Shared rotating logs for SSH and desktop entry points (Python 3.8+)."""
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path


def settings_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "publish-switcher/settings.json"


def default_log_path():
    return settings_path().parent / "logs/switcher.log"


def setup_logging(path=None, console=False):
    path = Path(path).expanduser().absolute() if path else default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("publish-switcher")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler = RotatingFileHandler(str(path), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    return logger, path
