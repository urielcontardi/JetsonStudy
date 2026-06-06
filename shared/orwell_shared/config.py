from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class CameraConfig(BaseModel):
    id: str
    argus_sensor_id: int
    name: str | None = None


class CaptureProfile(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "h265"
    encoder: str = "hw"
    gop_seconds: float = 1.0
    segment_seconds: float = 4.0
    bitrate_kbps: int = 8000

    @model_validator(mode="after")
    def _reject_h265_software(self) -> "CaptureProfile":
        if self.codec == "h265" and self.encoder == "sw":
            raise ValueError(
                "codec=h265 com encoder=sw é inviável em tempo real; "
                "use encoder=hw (NVENC) ou codec=h264 para software"
            )
        return self


class RetentionConfig(BaseModel):
    data_dir: str = "/var/lib/orwell/data"
    events_dir: str = "/var/lib/orwell/events"
    disk_high_watermark_pct: int = 85


class AIConfig(BaseModel):
    enabled: bool = False
    inference_fps: int = 8
    confidence_threshold: float = 0.6
    input_width: int = 640
    input_height: int = 360
    model_path: str = "/models/detector.engine"


class EventBufferConfig(BaseModel):
    enabled: bool = True
    buffer_seconds: int = 60
    bitrate_kbps: int = 8000
    tmpfs_dir: str = "/dev/shm/orwell"


class PreviewConfig(BaseModel):
    enabled: bool = False
    rtsp_base_url: str = "rtsp://preview:8554"


class OrwellConfig(BaseModel):
    device_name: str = "orwell-dev"
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureProfile = Field(default_factory=CaptureProfile)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    event_buffer: EventBufferConfig = Field(default_factory=EventBufferConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)


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
