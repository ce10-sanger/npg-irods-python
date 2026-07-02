from pathlib import Path

from datetime import datetime, tzinfo


def get_now(tz: tzinfo | None=None):
    return datetime.now(tz=tz)

def get_mtime(path: Path) -> float:
    return path.stat().st_mtime

def get_ctime(path: Path) -> float:
    return path.stat().st_ctime