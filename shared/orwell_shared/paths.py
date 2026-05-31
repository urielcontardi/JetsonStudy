from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_SEG_RE = re.compile(r"seg-(\d+)\.m4s$")


def segment_dir(data_dir: str | Path, camera_id: str, epoch_ms: int) -> Path:
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return Path(data_dir) / camera_id / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}" / f"{dt:%H}"


def segment_path(data_dir: str | Path, camera_id: str, epoch_ms: int) -> Path:
    return segment_dir(data_dir, camera_id, epoch_ms) / f"seg-{epoch_ms}.m4s"


def parse_segment_epoch_ms(path: str | Path) -> int:
    m = _SEG_RE.search(str(path))
    if not m:
        raise ValueError(f"not a segment path: {path}")
    return int(m.group(1))


def init_path(data_dir: str | Path, camera_id: str) -> Path:
    return Path(data_dir) / camera_id / "init.mp4"


def playlist_path(data_dir: str | Path, camera_id: str) -> Path:
    return Path(data_dir) / camera_id / "live.m3u8"
