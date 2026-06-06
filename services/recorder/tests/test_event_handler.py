import json

import pytest

from orwell_shared.events import EventIndex
from recorder.event_handler import flush_event_buffer, handle_detection


@pytest.fixture
def setup(tmp_path):
    tmpfs = tmp_path / "shm"
    buf_dir = tmpfs / "cam0"
    buf_dir.mkdir(parents=True)
    (buf_dir / "buf-0.m4s").write_bytes(b"DATA0")
    (buf_dir / "buf-1.m4s").write_bytes(b"DATA1")
    events_dir = tmp_path / "events"
    idx = EventIndex(tmp_path / "idx.sqlite")
    return tmpfs, events_dir, idx


def test_flush_copies_both_buf_files(setup):
    tmpfs, events_dir, _ = setup
    result = flush_event_buffer(str(tmpfs), str(events_dir), "evt-abc", "cam0")
    assert len(result) == 2
    assert all(f.exists() for f in result)
    assert all(f.parent.name == "evt-abc" for f in result)


def test_flush_skips_missing_files(tmp_path):
    tmpfs = tmp_path / "shm"
    buf_dir = tmpfs / "cam0"
    buf_dir.mkdir(parents=True)
    (buf_dir / "buf-0.m4s").write_bytes(b"x")

    result = flush_event_buffer(str(tmpfs), str(tmp_path / "events"), "evt-1", "cam0")
    assert len(result) == 1


def test_flush_empty_buf_returns_empty(tmp_path):
    tmpfs = tmp_path / "shm"
    (tmpfs / "cam0").mkdir(parents=True)
    result = flush_event_buffer(str(tmpfs), str(tmp_path / "events"), "evt-0", "cam0")
    assert result == []


def test_handle_detection_persists_event(setup):
    tmpfs, events_dir, idx = setup
    event_id = handle_detection(
        camera_id="cam0",
        t_evento=1000.0,
        label="smoke",
        confidence=0.9,
        bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
    )
    ev = idx.get(event_id)
    assert ev is not None
    assert ev.label == "smoke"
    assert ev.camera_id == "cam0"
    assert abs(ev.t_evento - 1000.0) < 0.001
    assert ev.confidence == 0.9
    assert ev.clip_path is not None
    bbox = json.loads(ev.bbox_json)
    assert bbox["x"] == pytest.approx(0.1)


def test_handle_detection_no_bbox(setup):
    tmpfs, events_dir, idx = setup
    event_id = handle_detection(
        camera_id="cam0", t_evento=2000.0, label="fault",
        confidence=0.7, bbox=None,
        tmpfs_dir=str(tmpfs), events_dir=str(events_dir),
        event_index=idx,
    )
    ev = idx.get(event_id)
    assert ev.bbox_json is None


def test_handle_detection_returns_unique_ids(setup):
    tmpfs, events_dir, idx = setup
    id1 = handle_detection("cam0", 1000.0, "smoke", 0.8, None,
                            str(tmpfs), str(events_dir), idx)
    id2 = handle_detection("cam0", 2000.0, "smoke", 0.8, None,
                            str(tmpfs), str(events_dir), idx)
    assert id1 != id2
