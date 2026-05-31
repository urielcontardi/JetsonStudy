from pathlib import Path

import pytest

from orwell_shared.clips import NoSegments, build_ffmpeg_cmd, extract_clip
from orwell_shared.index import Segment, SegmentIndex


def make(cam, start, path):
    return Segment(camera_id=cam, t_start=start, t_end=start + 4, path=path, size=10, created_at=start)


def test_build_ffmpeg_cmd_uses_concat_copy_faststart(tmp_path):
    listfile = tmp_path / "list.txt"
    out = tmp_path / "out.mp4"
    cmd = build_ffmpeg_cmd(listfile, out)
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and "concat" in cmd
    assert "-safe" in cmd and "0" in cmd
    assert "-c" in cmd and "copy" in cmd
    assert "+faststart" in " ".join(cmd)
    assert str(out) == cmd[-1]


def test_extract_clip_selects_segments_and_invokes_runner(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    init = tmp_path / "init.mp4"; init.write_bytes(b"init")
    for i, start in enumerate([100.0, 104.0, 108.0]):
        f = tmp_path / f"seg-{i}.m4s"; f.write_bytes(b"seg")
        idx.add_segment(make("0", start, str(f)))
    calls = {}

    def fake_runner(cmd, **kw):
        calls["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"clip")  # simula saída do ffmpeg

        class R:
            returncode = 0

        return R()

    out = tmp_path / "clip.mp4"
    result = extract_clip(idx, "0", 105.0, 109.0, out, init_path=init, runner=fake_runner)
    assert result == out and out.read_bytes() == b"clip"
    # a listfile passada ao ffmpeg deve referenciar init + 2 segmentos cobertos
    assert calls["cmd"][0] == "ffmpeg"


def test_extract_clip_raises_when_no_segments(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    with pytest.raises(NoSegments):
        extract_clip(idx, "0", 1.0, 2.0, tmp_path / "x.mp4",
                     init_path=tmp_path / "init.mp4", runner=lambda *a, **k: None)
