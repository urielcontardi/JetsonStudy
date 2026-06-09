import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from orwell_shared.samples_pb2 import Package, TriggerType
from orwell_shared.conveyor_uploader import ConveyorUploader


def _make_clip(tmp_path: Path) -> Path:
    clip_dir = tmp_path / "events" / "evt-123"
    clip_dir.mkdir(parents=True)
    clip = clip_dir / "clip.mp4"
    clip.write_bytes(b"FINALIZED_MP4")
    return clip


def test_upload_calls_send_dev_sample(tmp_path):
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, sensor_ext_id="aabbccddee00")
    clip = _make_clip(tmp_path)

    uploader.upload(
        event_id="evt-123",
        clip_path=clip,
        metadata={
            "camera_id": "cam0",
            "label": "pessoa",
            "confidence": 0.92,
            "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.8},
            "t_evento": 1748906400.0,
        },
    )

    mock_client.send_dev_sample.assert_called_once()


def test_upload_sends_finalized_clip_file(tmp_path):
    sent_bytes = []
    mock_client = MagicMock()
    mock_client.send_dev_sample.side_effect = lambda b: sent_bytes.append(b)

    uploader = ConveyorUploader(mock_client, sensor_ext_id="aabbccddee00")
    clip = _make_clip(tmp_path)

    uploader.upload("evt-123", clip, {
        "camera_id": "cam0", "label": "foo", "confidence": 0.5,
        "bbox": None, "t_evento": time.time(),
    })

    assert len(sent_bytes) == 1
    pkg = Package()
    pkg.ParseFromString(sent_bytes[0])
    assert pkg.data == b"FINALIZED_MP4"


def test_upload_rejects_fragment_directory(tmp_path):
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, sensor_ext_id="aabbccddee00")
    clip_dir = tmp_path / "events" / "legacy"
    clip_dir.mkdir(parents=True)

    try:
        uploader.upload("evt-123", clip_dir, {})
    except ValueError as exc:
        assert "finalized file" in str(exc)
    else:
        raise AssertionError("expected directory clip_path to be rejected")


def test_upload_package_format(tmp_path):
    sent_bytes = []
    mock_client = MagicMock()
    mock_client.send_dev_sample.side_effect = lambda b: sent_bytes.append(b)

    uploader = ConveyorUploader(mock_client, sensor_ext_id="aabbccddee00")
    clip = _make_clip(tmp_path)

    uploader.upload("evt-123", clip, {
        "camera_id": "cam0", "label": "pessoa", "confidence": 0.92,
        "bbox": {"x1": 0.1}, "t_evento": 1748906400.0,
    })

    pkg = Package()
    pkg.ParseFromString(sent_bytes[0])

    assert pkg.format == "orwell.video-clip.v1"
    assert pkg.trigger_type == TriggerType.Value("TRIGGER_TYPE_EVENT")
    assert pkg.device_id == b"aabbccddee00"
    assert pkg.started_at.seconds == 1748906400

    param_keys = {p.key: p for p in pkg.trigger_parameters}
    assert param_keys["label"].string_value == "pessoa"
    assert abs(param_keys["confidence"].real_value - 0.92) < 1e-6
    assert json.loads(param_keys["bbox"].string_value) == {"x1": 0.1}

    pkg_param_keys = {p.key: p for p in pkg.package_parameters}
    assert pkg_param_keys["event_id"].string_value == "evt-123"


def test_upload_returns_uri(tmp_path):
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, sensor_ext_id="aabbccddee00")
    clip = _make_clip(tmp_path)

    uri = uploader.upload("evt-123", clip, {
        "camera_id": "cam0", "label": "x", "confidence": 0.5,
        "bbox": None, "t_evento": time.time(),
    })

    assert "aabbccddee00" in uri
    assert "evt-123" in uri


def test_upload_status_calls_send_dev_status():
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, sensor_ext_id="aabbccddee00")

    uploader.upload_status({"cpu": 10.5, "memory": 45.2, "disk": 60.0})

    mock_client.send_dev_status.assert_called_once()
    sent = mock_client.send_dev_status.call_args[0][0]
    pkg = Package()
    pkg.ParseFromString(sent)
    assert pkg.format == "orwell.status.v1"
    data = json.loads(pkg.data.decode())
    assert data["cpu"] == 10.5


def test_upload_periodic_uses_trigger_type_periodic(tmp_path):
    from unittest.mock import MagicMock
    from orwell_shared.conveyor_uploader import ConveyorUploader
    from orwell_shared.samples_pb2 import Package, TriggerType

    clip_dir = tmp_path / "events" / "evt-p"
    clip_dir.mkdir(parents=True)
    clip = clip_dir / "clip.mp4"
    clip.write_bytes(b"FINALIZED")

    mock_client = MagicMock()
    uploader = ConveyorUploader(client=mock_client, sensor_ext_id="test-sensor")

    uploader.upload(
        event_id="12345678-1234-5678-1234-567812345678",
        clip_path=clip,
        metadata={
            "camera_id": "cam0",
            "label": "periodic",
            "confidence": 1.0,
            "bbox": None,
            "t_evento": 1000.0,
            "trigger_type": "periodic",
        },
    )

    assert mock_client.send_dev_sample.called
    pkg = Package()
    pkg.ParseFromString(mock_client.send_dev_sample.call_args[0][0])
    assert pkg.trigger_type == TriggerType.Value("TRIGGER_TYPE_PERIODIC")
