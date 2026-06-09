import json
from pathlib import Path

import pytest

from orwell_shared.events import EventIndex
from recorder.event_handler import finalize_event_buffer, handle_detection


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmpfs = tmp_path / "shm"
    buf_dir = tmpfs / "cam0"
    buf_dir.mkdir(parents=True)
    (buf_dir / "buf-0001.mp4").write_bytes(b"DATA0")
    (buf_dir / "buf-0002.mp4").write_bytes(b"DATA1")
    events_dir = tmp_path / "events"
    idx = EventIndex(tmp_path / "idx.sqlite")

    def fake_publish(_source_dir, target_dir, event_id):
        clip = Path(target_dir) / event_id / "clip.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"FINALIZED")
        return clip

    monkeypatch.setattr("recorder.event_handler.publish_event_clip", fake_publish)
    return tmpfs, events_dir, idx


def test_finalize_publishes_standalone_clip(setup):
    tmpfs, events_dir, _ = setup
    result = finalize_event_buffer(str(tmpfs), str(events_dir), "evt-abc", "cam0")
    assert result == events_dir / "evt-abc" / "clip.mp4"
    assert result.read_bytes() == b"FINALIZED"


def test_finalize_returns_none_without_closed_fragments(tmp_path, monkeypatch):
    from orwell_shared.clips import NoSegments

    tmpfs = tmp_path / "shm"
    buf_dir = tmpfs / "cam0"
    buf_dir.mkdir(parents=True)

    def no_segments(*_args):
        raise NoSegments("active fragment only")

    monkeypatch.setattr("recorder.event_handler.publish_event_clip", no_segments)
    result = finalize_event_buffer(str(tmpfs), str(tmp_path / "events"), "evt-1", "cam0")
    assert result is None


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
    assert Path(ev.clip_path).name == "clip.mp4"
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
