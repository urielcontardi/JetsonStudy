from pathlib import Path

from fastapi.testclient import TestClient

from orwell_shared.index import Segment, SegmentIndex


def _build_client(tmp_path, monkeypatch):
    # índice com 2 segmentos da câmera "0" cobrindo [100,108]
    idx_path = tmp_path / "idx.sqlite"
    idx = SegmentIndex(idx_path)
    init = tmp_path / "0" / "init.mp4"; init.parent.mkdir(parents=True); init.write_bytes(b"i")
    for i, start in enumerate([100.0, 104.0]):
        f = tmp_path / "0" / f"seg-{i}.m4s"; f.write_bytes(b"s")
        idx.add_segment(Segment("0", start, start + 4, str(f), 10, start))
    monkeypatch.setenv("ORWELL_INDEX_DB", str(idx_path))
    monkeypatch.setenv("ORWELL_DATA_DIR", str(tmp_path))
    from clip_api.main import create_app

    # injeta um extrator fake p/ não depender de ffmpeg neste teste
    from orwell_shared.clips import NoSegments
    def fake_extract(index, camera, start, end, out_path, init_path=None, runner=None):
        if not index.query(camera, start, end):
            raise NoSegments(f"camera={camera}")
        Path(out_path).write_bytes(b"CLIP"); return Path(out_path)

    app = create_app(extract_fn=fake_extract)
    return TestClient(app)


def test_healthz(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    assert c.get("/healthz").json() == {"status": "ok"}


def test_cameras(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    assert c.get("/cameras").json() == ["0"]


def test_get_clip_returns_mp4(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    r = c.get("/clips", params={"camera": "0",
                                "start": "1970-01-01T00:01:45Z",   # 105s
                                "end": "1970-01-01T00:01:47Z"})    # 107s
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.content == b"CLIP"


def test_get_clip_404_when_empty(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    r = c.get("/clips", params={"camera": "0",
                                "start": "2000-01-01T00:00:00Z",
                                "end": "2000-01-01T00:00:05Z"})
    assert r.status_code == 404


def test_range_empty(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    r = c.get("/range?camera=99")
    assert r.status_code == 200
    assert r.json() == {"camera": "99", "first": None, "last": None}


def test_range_with_segments(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    r = c.get("/range?camera=0")
    assert r.status_code == 200
    data = r.json()
    assert data["camera"] == "0"
    assert data["first"] == "1970-01-01T00:01:40Z"  # t_start=100.0
    assert data["last"]  == "1970-01-01T00:01:48Z"  # t_end=108.0
