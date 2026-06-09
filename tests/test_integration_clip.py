import shutil
import subprocess
from pathlib import Path

import pytest

from orwell_shared.clips import extract_clip, publish_event_clip
from orwell_shared.index import Segment, SegmentIndex

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe ausentes")
def test_extract_real_clip_produces_playable_mp4(sample_segments, tmp_path):
    data_dir, paths = sample_segments
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    for p, start in paths:
        idx.add_segment(Segment("0", start, start + 2, p, Path(p).stat().st_size, start))
    out = tmp_path / "clip.mp4"
    init = data_dir / "0" / "init.mp4"
    extract_clip(idx, "0", 101.0, 105.0, out, init_path=init)
    assert out.exists() and out.stat().st_size > 0
    # ffprobe confirma que é um vídeo legível
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0
    assert float(probe.stdout.strip()) > 0


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe ausentes")
def test_publish_event_clip_produces_single_playable_mp4(tmp_path):
    source = tmp_path / "buffer" / "0"
    source.mkdir(parents=True)
    for index, color in enumerate(("blue", "red")):
        fragment = source / f"buf-{index:04d}.mp4"
        subprocess.run(
            [
                FFMPEG, "-y",
                "-f", "lavfi",
                "-i", f"color=c={color}:s=320x240:d=1:r=15",
                "-c:v", "libx264",
                "-g", "15",
                "-movflags", "+faststart",
                "-f", "mp4",
                str(fragment),
            ],
            check=True,
            capture_output=True,
        )

    clip = publish_event_clip(source, tmp_path / "events", "evt-real")
    probe = subprocess.run(
        [
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(clip),
        ],
        capture_output=True,
        text=True,
    )

    assert clip == tmp_path / "events" / "evt-real" / "clip.mp4"
    assert probe.returncode == 0
    assert float(probe.stdout.strip()) >= 1.9
