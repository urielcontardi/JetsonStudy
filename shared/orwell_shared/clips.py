from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .index import Segment, SegmentIndex


class NoSegments(Exception):
    """Nenhum segmento cobre a janela pedida."""


def select_segments(index: SegmentIndex, camera_id: str, start: float, end: float) -> list[Segment]:
    return index.query(camera_id, start, end)


def _write_concat_list(segments: list[Segment], listfile: Path) -> None:
    lines = [f"file '{seg.path}'" for seg in segments]
    listfile.write_text("\n".join(lines) + "\n")


def build_ffmpeg_cmd(listfile: Path, out_path: Path) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(listfile),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]


def extract_clip(index: SegmentIndex, camera_id: str, start: float, end: float,
                 out_path: str | Path, init_path: str | Path | None = None,
                 runner: Callable = subprocess.run) -> Path:
    segments = select_segments(index, camera_id, start, end)
    if not segments:
        raise NoSegments(f"camera={camera_id} window=[{start},{end}]")
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as td:
        listfile = Path(td) / "concat.txt"
        _write_concat_list(segments, listfile)
        cmd = build_ffmpeg_cmd(listfile, out_path)
        result = runner(cmd, capture_output=True)
        if getattr(result, "returncode", 0) != 0:
            raise RuntimeError(f"ffmpeg failed: {getattr(result, 'stderr', b'')!r}")
    return out_path
