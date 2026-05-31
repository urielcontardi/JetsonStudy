from orwell_shared.index import Segment, SegmentIndex
from orwell_shared.retention import plan_eviction, run_eviction


def make(cam, start, path, size):
    return Segment(camera_id=cam, t_start=start, t_end=start + 4, path=path, size=size, created_at=start)


def test_plan_eviction_returns_oldest_until_under_watermark():
    # capacidade 1000, uso atual 900 (90%), watermark 85% -> alvo <=850
    # precisa liberar >=50; remove os mais antigos primeiro
    oldest_first = [
        ("a.m4s", 30),
        ("b.m4s", 30),
        ("c.m4s", 30),
    ]
    to_delete = plan_eviction(used_bytes=900, capacity_bytes=1000,
                              high_watermark_pct=85, oldest_first=oldest_first)
    # remove a (870) e b (840 <=850) -> para
    assert to_delete == ["a.m4s", "b.m4s"]


def test_plan_eviction_noop_when_under_watermark():
    assert plan_eviction(800, 1000, 85, [("a.m4s", 30)]) == []


def test_run_eviction_deletes_files_and_index(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    paths = []
    for i in range(3):
        f = data / f"seg-{i}.m4s"
        f.write_bytes(b"x" * 100)
        idx.add_segment(make("0", float(i), str(f), 100))
        paths.append(str(f))
    # força "uso" alto via função injetada
    deleted = run_eviction(idx, used_bytes=300, capacity_bytes=300,
                           high_watermark_pct=50)
    # alvo <=150 -> remove seg-0 (200) e seg-1 (100<=150)
    assert deleted == [paths[0], paths[1]]
    assert idx.oldest().path == paths[2]
    assert not (data / "seg-0.m4s").exists()
