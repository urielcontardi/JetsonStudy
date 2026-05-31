from pathlib import Path

from orwell_shared.paths import init_path, parse_segment_epoch_ms, segment_path


def test_segment_path_layout():
    # 2026-05-31T14:00:00Z = 1780236000 s = 1780236000000 ms
    p = segment_path("/data", "0", 1780236000000)
    assert p == Path("/data/0/2026/05/31/14/seg-1780236000000.m4s")


def test_parse_segment_epoch_ms_roundtrip():
    p = segment_path("/data", "1", 1780236004500)
    assert parse_segment_epoch_ms(p) == 1780236004500


def test_init_path():
    assert init_path("/data", "0") == Path("/data/0/init.mp4")
