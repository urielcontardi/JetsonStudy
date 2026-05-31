from __future__ import annotations

import os

import paho.mqtt.client as mqtt

from orwell_shared.config import load_config
from orwell_shared.index import SegmentIndex
from orwell_shared.storage import get_backend

from .handler import handle_event_payload


def main() -> None:
    cfg = load_config(os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml"))
    index = SegmentIndex(os.environ.get("ORWELL_INDEX_DB",
                                        f"{cfg.retention.data_dir}/index.sqlite"))
    storage = get_backend(cfg.cloud)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(cfg.broker.events_topic)

    def on_message(client, userdata, msg):
        try:
            uri = handle_event_payload(msg.payload.decode(), index, storage,
                                       data_dir=cfg.retention.data_dir)
            print(f"uploaded: {uri}", flush=True)
        except Exception as exc:  # noqa: BLE001 - loop não pode morrer por 1 evento
            print(f"event error: {exc}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(cfg.broker.host, cfg.broker.port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
