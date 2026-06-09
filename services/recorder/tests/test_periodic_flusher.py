import time
from pathlib import Path

import pytest

from orwell_shared.events import EventIndex
from orwell_shared.index import Segment, SegmentIndex
from recorder.periodic_flusher import PeriodicFlusher


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmpfs = tmp_path / "shm"
    events_dir = tmp_path / "events"
    db = tmp_path / "idx.sqlite"

    for cam in ("cam0", "cam1"):
        buf_dir = tmpfs / cam
        buf_dir.mkdir(parents=True)
        (buf_dir / "buf-0001.mp4").write_bytes(b"SEGMENT0-" + cam.encode())
        (buf_dir / "buf-0002.mp4").write_bytes(b"SEGMENT1-" + cam.encode())

    idx = EventIndex(db)

    def fake_publish(_source_dir, target_dir, event_id):
        clip = Path(target_dir) / event_id / "clip.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"FINALIZED")
        return clip

    monkeypatch.setattr("recorder.event_handler.publish_event_clip", fake_publish)
    return tmpfs, events_dir, idx


def test_flush_copies_buffer_files(setup, tmp_path):
    tmpfs, events_dir, idx = setup
    cameras = ["cam0", "cam1"]
    flusher = PeriodicFlusher(
        cameras=cameras,
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=9999,
        enabled=True,
    )
    flusher._flush_all()

    pending = idx.pending_uploads()
    assert len(pending) == 2
    for ev in pending:
        assert ev.trigger_type == "periodic"
        assert ev.label == "periodic"
        clip = Path(ev.clip_path)
        assert clip.name == "clip.mp4"
        assert clip.exists()


def test_flush_uses_dvr_segments_when_index_is_provided(setup, monkeypatch):
    tmpfs, events_dir, event_idx = setup
    segment_idx = SegmentIndex(events_dir.parent / "segments.sqlite")
    segment = events_dir.parent / "seg.mp4"
    segment.write_bytes(b"SEGMENT")
    segment_idx.add_segment(Segment("cam0", 90.0, 100.0, str(segment), 7, 90.0))
    calls = []

    def fake_extract(index, camera, start, end, out):
        calls.append((index, camera, start, end))
        out.write_bytes(b"SMALL_DVR_CLIP")
        return out

    monkeypatch.setattr("recorder.periodic_flusher.extract_clip", fake_extract)
    monkeypatch.setattr("recorder.periodic_flusher.time.time", lambda: 100.0)
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=event_idx,
        interval_s=9999,
        enabled=True,
        segment_index=segment_idx,
        clip_duration_s=10,
    )

    flusher._flush_all()

    pending = event_idx.pending_uploads()
    assert len(pending) == 1
    assert Path(pending[0].clip_path).read_bytes() == b"SMALL_DVR_CLIP"
    assert calls == [(segment_idx, "cam0", 90.0, 100.0)]


def test_flush_disabled_does_nothing(setup):
    tmpfs, events_dir, idx = setup
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=9999,
        enabled=False,
    )
    flusher._flush_all()
    assert idx.pending_uploads() == []


def test_flusher_runs_on_timer(setup):
    tmpfs, events_dir, idx = setup
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=0.1,
        enabled=True,
    )
    flusher.start()
    time.sleep(0.35)
    flusher.stop()

    pending = idx.pending_uploads()
    assert len(pending) >= 2


def test_update_config_changes_interval(setup):
    tmpfs, events_dir, idx = setup
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=9999,
        enabled=False,
    )
    flusher.update_config(enabled=True, interval_s=0.1)
    flusher.start()
    time.sleep(0.35)
    flusher.stop()
    assert len(idx.pending_uploads()) >= 2
