import time
from pathlib import Path

import pytest

from orwell_shared.events import EventIndex
from recorder.periodic_flusher import PeriodicFlusher


@pytest.fixture
def setup(tmp_path):
    tmpfs = tmp_path / "shm"
    events_dir = tmp_path / "events"
    db = tmp_path / "idx.sqlite"

    for cam in ("cam0", "cam1"):
        buf_dir = tmpfs / cam
        buf_dir.mkdir(parents=True)
        (buf_dir / "buf-0.m4s").write_bytes(b"SEGMENT0-" + cam.encode())
        (buf_dir / "buf-1.m4s").write_bytes(b"SEGMENT1-" + cam.encode())

    idx = EventIndex(db)
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
        clip_dir = Path(ev.clip_path)
        assert (clip_dir / "buf-0.m4s").exists()


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
