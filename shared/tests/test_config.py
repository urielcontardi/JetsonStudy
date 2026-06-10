from pathlib import Path

import pytest
from pydantic import ValidationError

from orwell_shared.config import CaptureProfile, OrwellConfig, load_config

YAML = """
device_name: orwell-01
cameras:
  - id: "0"
    argus_sensor_id: 0
    name: front
  - id: "1"
    argus_sensor_id: 1
capture:
  width: 1920
  height: 1080
  fps: 15
  segment_seconds: 4.0
  gop_seconds: 1.0
retention:
  data_dir: /var/lib/orwell/data
  disk_high_watermark_pct: 85
"""


def test_load_config_parses_yaml(tmp_path: Path):
    p = tmp_path / "orwell.yaml"
    p.write_text(YAML)
    cfg = load_config(p)
    assert isinstance(cfg, OrwellConfig)
    assert cfg.device_name == "orwell-01"
    assert len(cfg.cameras) == 2
    assert cfg.cameras[0].id == "0"
    assert cfg.capture.segment_seconds == 4.0
    assert cfg.retention.disk_high_watermark_pct == 85


def test_env_overrides_scalar(tmp_path: Path, monkeypatch):
    p = tmp_path / "orwell.yaml"
    p.write_text(YAML)
    monkeypatch.setenv("ORWELL_RETENTION__DISK_HIGH_WATERMARK_PCT", "70")
    monkeypatch.setenv("ORWELL_DEVICE_NAME", "orwell-99")
    cfg = load_config(p)
    assert cfg.retention.disk_high_watermark_pct == 70
    assert cfg.device_name == "orwell-99"


def test_capture_defaults_to_h265_hw():
    prof = CaptureProfile()
    assert prof.codec == "h265"
    assert prof.encoder == "hw"
    assert prof.fps == 30


def test_h265_software_is_rejected():
    with pytest.raises(ValidationError):
        CaptureProfile(codec="h265", encoder="sw")


def test_h264_software_is_allowed():
    prof = CaptureProfile(codec="h264", encoder="sw")
    assert prof.encoder == "sw"


def test_camera_ai_default_disabled():
    from orwell_shared.config import CameraConfig
    cam = CameraConfig(id="0", argus_sensor_id=0)
    assert cam.ai.enabled is False
    assert cam.ai.model_path == "/models/detector.engine"


def test_camera_ai_instances_are_independent():
    from orwell_shared.config import CameraConfig
    cam1 = CameraConfig(id="0", argus_sensor_id=0)
    cam2 = CameraConfig(id="1", argus_sensor_id=1)
    cam1.ai.enabled = True
    assert cam2.ai.enabled is False


def test_preview_default_disabled():
    cfg = OrwellConfig()
    assert cfg.preview.enabled is False


def test_camera_ai_parsed_from_yaml(tmp_path):
    from orwell_shared.config import load_config
    p = tmp_path / "orwell.yaml"
    p.write_text("""
cameras:
  - id: "0"
    argus_sensor_id: 0
    ai:
      enabled: true
      model_path: /models/cam0/detector.engine
      confidence_threshold: 0.8
  - id: "1"
    argus_sensor_id: 1
    ai:
      enabled: false
      model_path: /models/cam1/classifier.engine
""")
    cfg = load_config(p)
    assert cfg.cameras[0].ai.enabled is True
    assert cfg.cameras[0].ai.model_path == "/models/cam0/detector.engine"
    assert cfg.cameras[0].ai.confidence_threshold == 0.8
    assert cfg.cameras[1].ai.enabled is False


def test_orwell_config_has_no_global_ai():
    cfg = OrwellConfig()
    assert not hasattr(cfg, "ai")


def test_event_buffer_config_defaults():
    from orwell_shared.config import EventBufferConfig
    c = EventBufferConfig()
    assert c.enabled is True
    assert c.buffer_seconds == 60
    assert c.bitrate_kbps == 8000
    assert c.tmpfs_dir == "/dev/shm/orwell"


def test_retention_config_has_events_dir():
    from orwell_shared.config import RetentionConfig
    c = RetentionConfig()
    assert c.events_dir == "/var/lib/orwell/events"


def test_ai_config_new_fields():
    from orwell_shared.config import AIConfig
    c = AIConfig()
    assert c.inference_fps == 8
    assert c.confidence_threshold == 0.6
    assert c.input_width == 640
    assert c.input_height == 360
    assert c.model_path == "/models/detector.engine"


def test_orwell_config_has_event_buffer():
    cfg = OrwellConfig()
    assert hasattr(cfg, "event_buffer")
    assert cfg.event_buffer.buffer_seconds == 60


def test_conveyor_config_defaults_periodic():
    from orwell_shared.config import ConveyorConfig
    cfg = ConveyorConfig()
    assert cfg.periodic_upload_enabled is True
    assert cfg.periodic_upload_interval_s == 600


def test_conveyor_config_periodic_from_yaml(tmp_path):
    import yaml
    from orwell_shared.config import load_config
    cfg_file = tmp_path / "orwell.yaml"
    cfg_file.write_text(yaml.dump({
        "conveyor": {
            "enabled": True,
            "periodic_upload_enabled": False,
            "periodic_upload_interval_s": 300,
        }
    }))
    cfg = load_config(cfg_file)
    assert cfg.conveyor.periodic_upload_enabled is False
    assert cfg.conveyor.periodic_upload_interval_s == 300
