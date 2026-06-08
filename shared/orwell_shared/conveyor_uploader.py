from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from google.protobuf.timestamp_pb2 import Timestamp

from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.samples_pb2 import Package, Parameter, TriggerType


def _param(key: str, **kwargs) -> Parameter:
    p = Parameter()
    p.key = key
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


class ConveyorUploader:
    def __init__(
        self,
        client: ConveyorClient,
        sensor_ext_id: str,
        hardware_id: str = "orwell-nx-v1",
    ) -> None:
        self._client = client
        self._sensor_ext_id = sensor_ext_id
        self._hardware_id = hardware_id

    def upload(self, event_id: str, clip_path: Path, metadata: dict) -> str:
        buf0 = (clip_path / "buf-0.m4s").read_bytes()
        buf1_path = clip_path / "buf-1.m4s"
        buf1 = buf1_path.read_bytes() if buf1_path.exists() else b""

        t_evento = float(metadata.get("t_evento", time.time()))
        ts = Timestamp()
        ts.seconds = int(t_evento)

        pkg = Package()
        pkg.device_id = self._sensor_ext_id.encode()
        pkg.hardware_id = self._hardware_id.encode()
        pkg.data_id = uuid.UUID(event_id).bytes if _is_uuid(event_id) else event_id.encode()
        pkg.format = "orwell.video-clip.v1"
        pkg.started_at.CopyFrom(ts)
        pkg.duration_us = 10_000_000
        pkg.trigger_type = TriggerType.Value("TRIGGER_TYPE_EVENT")

        camera_id = metadata.get("camera_id", "cam0")
        camera_index = int(camera_id.replace("cam", "")) if camera_id.startswith("cam") else 0
        pkg.trigger_source.append(camera_index)

        pkg.trigger_parameters.append(_param("label", string_value=str(metadata.get("label", ""))))
        pkg.trigger_parameters.append(_param("confidence", real_value=float(metadata.get("confidence", 0.0))))

        bbox = metadata.get("bbox")
        if bbox is not None:
            pkg.trigger_parameters.append(_param("bbox", string_value=json.dumps(bbox)))

        pkg.package_parameters.append(_param("event_id", string_value=event_id))
        pkg.package_parameters.append(_param("camera_id", string_value=camera_id))

        pkg.data = buf0 + buf1

        self._client.send_dev_sample(pkg.SerializeToString())
        return f"conveyor://{self._sensor_ext_id}/samples/{event_id}"

    def upload_status(self, metrics: dict) -> None:
        ts = Timestamp()
        ts.seconds = int(time.time())

        pkg = Package()
        pkg.device_id = self._sensor_ext_id.encode()
        pkg.hardware_id = self._hardware_id.encode()
        pkg.data_id = uuid.uuid4().bytes
        pkg.format = "orwell.status.v1"
        pkg.started_at.CopyFrom(ts)
        pkg.trigger_type = TriggerType.Value("TRIGGER_TYPE_PERIODIC")
        pkg.data = json.dumps(metrics).encode()

        self._client.send_dev_status(pkg.SerializeToString())
