from pathlib import Path

from orwell_shared.config import CaptureProfile
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import segment_path
from recorder.indexer import build_playlist, list_segment_files, reflect_segments


def _make_seg(data_dir: str, camera_id: str, epoch_ms: int, size: int = 100) -> Path:
    p = segment_path(data_dir, camera_id, epoch_ms)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def test_reflect_segments_indexes_all_but_latest(tmp_path):
    data = str(tmp_path)
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    # 3 segmentos; o mais recente é pulado (pode estar sendo escrito)
    _make_seg(data, "0", 1780236000000)
    _make_seg(data, "0", 1780236004000)
    _make_seg(data, "0", 1780236008000)
    known: set[str] = set()
    added = reflect_segments(idx, data, "0", CaptureProfile(segment_seconds=4.0), known)
    assert len(added) == 2
    res = idx.query("0", 1780236000.0, 1780236010.0)
    assert len(res) == 2
    assert res[0].t_start == 1780236000.0
    assert res[0].t_end == 1780236004.0


def test_reflect_segments_is_incremental(tmp_path):
    data = str(tmp_path)
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    _make_seg(data, "0", 1000000)
    _make_seg(data, "0", 1004000)
    known: set[str] = set()
    reflect_segments(idx, data, "0", CaptureProfile(segment_seconds=4.0), known)
    # adiciona mais um e re-roda: só o novo (menos o latest) entra
    _make_seg(data, "0", 1008000)
    added2 = reflect_segments(idx, data, "0", CaptureProfile(segment_seconds=4.0), known)
    assert added2 == [str(segment_path(data, "0", 1004000))]


def test_build_playlist_has_map_and_relative_paths(tmp_path):
    data = str(tmp_path)
    _make_seg(data, "0", 1780236000000)
    _make_seg(data, "0", 1780236004000)
    files = list_segment_files(data, "0")
    pl = build_playlist(data, "0", files, segment_seconds=4.0)
    assert pl.startswith("#EXTM3U")
    assert '#EXT-X-MAP:URI="init.mp4"' in pl
    assert "#EXT-X-TARGETDURATION:4" in pl
    # caminho relativo à raiz da câmera (inclui a hierarquia de data)
    assert "2026/05/31/14/seg-1780236000000.m4s" in pl
