from pathlib import Path

from orwell_shared.config import OrwellConfig, load_config

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
broker:
  host: broker
  events_topic: orwell/events
cloud:
  backend: s3
  bucket: my-bucket
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
    assert cfg.cloud.bucket == "my-bucket"


def test_env_overrides_scalar(tmp_path: Path, monkeypatch):
    p = tmp_path / "orwell.yaml"
    p.write_text(YAML)
    monkeypatch.setenv("ORWELL_RETENTION__DISK_HIGH_WATERMARK_PCT", "70")
    monkeypatch.setenv("ORWELL_DEVICE_NAME", "orwell-99")
    cfg = load_config(p)
    assert cfg.retention.disk_high_watermark_pct == 70
    assert cfg.device_name == "orwell-99"
