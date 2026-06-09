from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
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


def probe_media(path: Path, runner: Callable = subprocess.run) -> bool:
    result = runner(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
    )
    return getattr(result, "returncode", 1) == 0 and b"video" in getattr(result, "stdout", b"")


def publish_event_clip(
    source_dir: Path,
    events_dir: Path,
    event_id: str,
    runner: Callable = subprocess.run,
    probe_runner: Callable = subprocess.run,
) -> Path:
    """Snapshot closed fragments, remux them, then publish clip.mp4 atomically."""
    candidates = []
    for path in Path(source_dir).glob("buf-*"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except FileNotFoundError:
            continue
    source_files = [path for _, path in sorted(candidates)]
    if not source_files:
        raise NoSegments(f"no buffer fragments in {source_dir}")

    events_dir = Path(events_dir)
    events_dir.mkdir(parents=True, exist_ok=True)
    final_dir = events_dir / event_id
    staging_dir = events_dir / f".{event_id}.{uuid.uuid4().hex}.tmp"
    fragments_dir = staging_dir / "fragments"
    fragments_dir.mkdir(parents=True)

    try:
        snapshots = []
        for index, source in enumerate(source_files):
            snapshot = fragments_dir / f"{index:04d}{source.suffix}"
            try:
                shutil.copy2(source, snapshot)
            except FileNotFoundError:
                continue
            if probe_media(snapshot, runner=probe_runner):
                snapshots.append(snapshot)
            else:
                snapshot.unlink()

        if not snapshots:
            raise NoSegments(f"no finalized buffer fragments in {source_dir}")

        listfile = staging_dir / "concat.txt"
        listfile.write_text("\n".join(f"file '{path}'" for path in snapshots) + "\n")
        clip_path = staging_dir / "clip.mp4"
        result = runner(build_ffmpeg_cmd(listfile, clip_path), capture_output=True)
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(f"ffmpeg failed: {getattr(result, 'stderr', b'')!r}")
        if not probe_media(clip_path, runner=probe_runner):
            raise RuntimeError("ffmpeg produced an invalid event clip")

        shutil.rmtree(fragments_dir)
        listfile.unlink()
        os.replace(staging_dir, final_dir)
        return final_dir / "clip.mp4"
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


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


def extract_event_clip(
    clip_dir: Path,
    out_path: Path,
    runner: Callable = subprocess.run,
) -> Path:
    """Remux legacy event fragments, ordered by mtime, into one MP4."""
    buf_files = sorted(Path(clip_dir).glob("buf-*"), key=lambda f: f.stat().st_mtime)
    if not buf_files:
        raise NoSegments(f"no buf files in {clip_dir}")
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as td:
        listfile = Path(td) / "concat.txt"
        listfile.write_text("\n".join(f"file '{f}'" for f in buf_files) + "\n")
        cmd = build_ffmpeg_cmd(listfile, out_path)
        result = runner(cmd, capture_output=True)
        if getattr(result, "returncode", 0) != 0:
            raise RuntimeError(f"ffmpeg failed: {getattr(result, 'stderr', b'')!r}")
    return out_path
