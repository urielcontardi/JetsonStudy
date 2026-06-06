import time
from pathlib import Path
from unittest.mock import MagicMock

from orwell_shared.events import Event, EventIndex
from orwell_shared.upload_worker import UploadWorker


def _make_index(tmp_path):
    return EventIndex(tmp_path / "events.db")


def _make_event(tmp_path, event_id="evt-1", camera_id="cam0") -> tuple[Event, Path]:
    clip_dir = tmp_path / "events" / event_id
    clip_dir.mkdir(parents=True)
    (clip_dir / "buf-0.m4s").write_bytes(b"SEG0")
    (clip_dir / "buf-1.m4s").write_bytes(b"SEG1")
    event = Event(
        id=event_id,
        camera_id=camera_id,
        t_evento=time.time(),
        label="pessoa",
        confidence=0.9,
        clip_path=str(clip_dir),
    )
    return event, clip_dir


def test_worker_uploads_pending_event(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    mock_uploader = MagicMock()
    mock_uploader.upload.return_value = "conveyor://dev/samples/evt-1"

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    mock_uploader.upload.assert_called_once()
    call_args = mock_uploader.upload.call_args
    assert call_args[1]["event_id"] == "evt-1" or call_args[0][0] == "evt-1"


def test_worker_marks_event_as_uploaded(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    mock_uploader = MagicMock()
    mock_uploader.upload.return_value = "conveyor://dev/samples/evt-1"

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    updated = index.get("evt-1")
    assert updated.uploaded_at is not None
    assert updated.uploaded_at > 0


def test_worker_skips_event_when_clip_not_found(tmp_path):
    index = _make_index(tmp_path)
    event = Event(
        id="evt-missing",
        camera_id="cam0",
        t_evento=time.time(),
        label="x",
        confidence=0.5,
        clip_path="/nonexistent/path/evt-missing",
    )
    index.add_event(event)

    mock_uploader = MagicMock()
    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    mock_uploader.upload.assert_not_called()
    updated = index.get("evt-missing")
    assert updated.uploaded_at == -1.0


def test_worker_retries_failed_upload(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    call_count = [0]

    def flaky_upload(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("network error")
        return "conveyor://dev/samples/evt-1"

    mock_uploader = MagicMock()
    mock_uploader.upload.side_effect = flaky_upload

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.4)
    worker.stop()

    assert call_count[0] >= 2
    updated = index.get("evt-1")
    assert updated.uploaded_at is not None and updated.uploaded_at > 0


def test_worker_does_not_re_upload(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    mock_uploader = MagicMock()
    mock_uploader.upload.return_value = "conveyor://ok"

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.3)
    worker.stop()

    assert mock_uploader.upload.call_count == 1
