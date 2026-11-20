"""Small stdlib compatibility helpers for Ubuntu's Python 3.8."""
from pathlib import Path


def is_relative_to(path, root):
    """Equivalent to Path.is_relative_to (introduced after Python 3.8)."""
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def remove_suffix(value, suffix):
    """Equivalent to str.removesuffix, including the empty-suffix case."""
    return value[:-len(suffix)] if suffix and value.endswith(suffix) else value
