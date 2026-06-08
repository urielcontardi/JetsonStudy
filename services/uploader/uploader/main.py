"""Uploader service — lê EventIndex (SQLite), envia via VSTP, marca como uploaded.

Roda como container separado (sem NVIDIA runtime). Compartilha volumes /data e /events
com o recorder e o clip-api via HostPath no NVMe.
"""
from __future__ import annotations

import logging
import os
import time

from orwell_shared.config import load_config
from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.conveyor_uploader import ConveyorUploader
from orwell_shared.device_id import get_ext_id
from orwell_shared.events import EventIndex
from orwell_shared.upload_worker import UploadWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("uploader")


def main() -> None:
    config_path = os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml")
    config = load_config(config_path)
    db_path = os.environ.get("ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite")

    if not config.conveyor.enabled:
        logger.info("conveyor.enabled=false — uploader em modo idle (aguardando config)")
        while True:
            time.sleep(60)

    gateway_ext_id = config.conveyor.gateway_ext_id
    sensor_ext_id = config.conveyor.sensor_ext_id or get_ext_id()
    logger.info("gateway_ext_id=%s sensor_ext_id=%s", gateway_ext_id, sensor_ext_id)

    client = ConveyorClient(
        host=config.conveyor.host,
        port=config.conveyor.port,
        gateway_ext_id=gateway_ext_id,
        sensor_ext_id=sensor_ext_id,
    )
    uploader = ConveyorUploader(client=client, sensor_ext_id=sensor_ext_id)
    event_index = EventIndex(db_path)

    worker = UploadWorker(
        event_index=event_index,
        uploader=uploader,
        upload_interval_s=config.conveyor.upload_interval_s,
        status_interval_s=config.conveyor.status_interval_s,
    )
    worker.start()
    logger.info(
        "UploadWorker iniciado (host=%s:%s, poll=%ss)",
        config.conveyor.host, config.conveyor.port, config.conveyor.upload_interval_s,
    )

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        worker.stop()
        logger.info("uploader parado")


if __name__ == "__main__":
    main()
