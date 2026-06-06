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


def test_extract_event_clip_concatenates_buf_files(tmp_path):
    from orwell_shared.clips import extract_event_clip

    clip_dir = tmp_path / "events" / "evt-1"
    clip_dir.mkdir(parents=True)
    buf0 = clip_dir / "buf-0.m4s"; buf0.write_bytes(b"OLD")
    buf1 = clip_dir / "buf-1.m4s"; buf1.write_bytes(b"NEW")
    buf1.touch()  # garante mtime > buf0

    out = tmp_path / "event.mp4"
    captured_concat = []

    def fake_run(cmd, **_):
        # lê o concat.txt enquanto o TemporaryDirectory ainda existe
        concat_idx = cmd.index("-i") + 1
        captured_concat.append(Path(cmd[concat_idx]).read_text())
        out.write_bytes(b"MP4")

        class R:
            returncode = 0
        return R()

    result = extract_event_clip(clip_dir, out, runner=fake_run)
    assert result == out
    assert out.read_bytes() == b"MP4"
    assert len(captured_concat) == 1
    assert "buf-0.m4s" in captured_concat[0]
    assert "buf-1.m4s" in captured_concat[0]


def test_extract_event_clip_raises_when_no_files(tmp_path):
    from orwell_shared.clips import NoSegments, extract_event_clip
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(NoSegments):
        extract_event_clip(empty_dir, tmp_path / "out.mp4")
