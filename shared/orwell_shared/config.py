from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    id: str
    argus_sensor_id: int
    name: str | None = None


class CaptureProfile(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 15
    codec: str = "h264"
    gop_seconds: float = 1.0
    segment_seconds: float = 4.0
    bitrate_kbps: int = 6000


class RetentionConfig(BaseModel):
    data_dir: str = "/var/lib/orwell/data"
    disk_high_watermark_pct: int = 85


class BrokerConfig(BaseModel):
    host: str = "broker"
    port: int = 1883
    events_topic: str = "orwell/events"


class CloudConfig(BaseModel):
    backend: str = "s3"           # s3 | local
    bucket: str | None = None
    prefix: str = "orwell/"
    local_dir: str = "/var/lib/orwell/uploads"


class OrwellConfig(BaseModel):
    device_name: str = "orwell-dev"
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureProfile = Field(default_factory=CaptureProfile)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)


def _apply_env_overrides(data: dict) -> dict:
    """ORWELL_FOO=bar -> data['foo']; ORWELL_SECTION__KEY=val -> data['section']['key']."""
    for env_key, value in os.environ.items():
        if not env_key.startswith("ORWELL_"):
            continue
        path = env_key[len("ORWELL_"):].lower().split("__")
        cursor = data
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    return data


def load_config(path: str | Path) -> OrwellConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    raw = _apply_env_overrides(raw)
    return OrwellConfig.model_validate(raw)
