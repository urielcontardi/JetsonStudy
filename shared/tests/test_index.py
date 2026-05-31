from orwell_shared.index import Segment, SegmentIndex


def make(cam, start, end, path, size=1000):
    return Segment(camera_id=cam, t_start=start, t_end=end, path=path, size=size, created_at=end)


def test_add_and_query_overlap(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/seg-100000.m4s"))
    idx.add_segment(make("0", 104.0, 108.0, "/d/0/seg-104000.m4s"))
    idx.add_segment(make("0", 108.0, 112.0, "/d/0/seg-108000.m4s"))
    idx.add_segment(make("1", 100.0, 104.0, "/d/1/seg-100000.m4s"))
    # janela [105,109] cobre os segmentos 104-108 e 108-112 da câmera 0
    res = idx.query("0", 105.0, 109.0)
    assert [s.path for s in res] == ["/d/0/seg-104000.m4s", "/d/0/seg-108000.m4s"]


def test_cameras_and_total_size(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/a.m4s", size=10))
    idx.add_segment(make("1", 100.0, 104.0, "/d/1/a.m4s", size=20))
    assert sorted(idx.cameras()) == ["0", "1"]
    assert idx.total_size() == 30


def test_oldest_and_delete(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/old.m4s"))
    idx.add_segment(make("0", 200.0, 204.0, "/d/0/new.m4s"))
    assert idx.oldest().path == "/d/0/old.m4s"
    idx.delete("/d/0/old.m4s")
    assert idx.oldest().path == "/d/0/new.m4s"


def test_add_is_idempotent_on_path(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/a.m4s", size=10))
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/a.m4s", size=99))  # mesmo path
    assert idx.total_size() == 99  # upsert
