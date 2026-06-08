#!/usr/bin/env python3
"""Smoke test: verifica comunicação com o Conveyor via VSTP dev routes.

Gateway virtual = mesmo extId do iot-emulator (000011113333).
SensorExtId = blake3(eMMC CID) do dispositivo, ou ORWELL_DEVICE_ID em dev.
Não precisa de Jetson, GStreamer ou câmera — só rede até o Conveyor.

Uso:
    python tests/smoke_conveyor.py
    python tests/smoke_conveyor.py --host conveyor.tractian.dev
    python tests/smoke_conveyor.py --gateway-ext-id 000011112222
    python tests/smoke_conveyor.py --sensor-ext-id meu-device-id

Env vars:
    ORWELL_DEVICE_ID   — sensor_ext_id (sobrescreve --sensor-ext-id)
    CONVEYOR_HOST      — sobrescreve --host
"""
import argparse
import json
import os
import sys
import time
import uuid

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "shared"))

from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.samples_pb2 import Package


def _sep(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print('─' * 55)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("CONVEYOR_HOST", "conveyor.tractian.com"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--gateway-ext-id", default="000011113333",
                        help="extId do gateway virtual cadastrado no Conveyor")
    parser.add_argument("--sensor-ext-id",
                        default=os.environ.get("ORWELL_DEVICE_ID", ""),
                        help="extId do sensor (device). Vazio = tenta eMMC CID")
    args = parser.parse_args()

    gateway_ext_id = args.gateway_ext_id

    if args.sensor_ext_id:
        sensor_ext_id = args.sensor_ext_id
    else:
        try:
            from orwell_shared.device_id import get_ext_id
            sensor_ext_id = get_ext_id()
        except RuntimeError:
            sensor_ext_id = f"smoke-test-{uuid.uuid4().hex[:8]}"
            print(f"  [aviso] eMMC CID não disponível, usando sensor_ext_id temporário: {sensor_ext_id}")

    print(f"Conveyor smoke test")
    print(f"  host           : {args.host}:{args.port}")
    print(f"  gateway_ext_id : {gateway_ext_id}  (auth)")
    print(f"  sensor_ext_id  : {sensor_ext_id}  (S3 path)")

    # ── 1. Auth ──────────────────────────────────────────────────────────────
    _sep("1/3  Auth (ggt)")
    try:
        client = ConveyorClient(
            host=args.host,
            port=args.port,
            gateway_ext_id=gateway_ext_id,
            sensor_ext_id=sensor_ext_id,
        )
        print(f"  ✓ token obtido  num_requests={client._token['num_requests']}")
    except Exception as e:
        print(f"  ✗ FALHA: {e}")
        return 1

    # ── 2. Ping ───────────────────────────────────────────────────────────────
    _sep("2/3  Ping")
    try:
        ok = client.ping()
        print(f"  ✓ ping={'OK' if ok else 'FAIL'}")
    except Exception as e:
        print(f"  ✗ FALHA: {e}")
        return 1

    # ── 3. pdevsample — Package de smoke ─────────────────────────────────────
    _sep("3/3  pdevsample (format=orwell.smoke.v1)")
    try:
        from google.protobuf.timestamp_pb2 import Timestamp
        from orwell_shared.samples_pb2 import Parameter, TriggerType

        ts = Timestamp()
        ts.seconds = int(time.time())

        pkg = Package()
        pkg.device_id = sensor_ext_id.encode()
        pkg.hardware_id = b"orwell-smoke-test"
        pkg.data_id = uuid.uuid4().bytes
        pkg.format = "orwell.smoke.v1"
        pkg.started_at.CopyFrom(ts)
        pkg.duration_us = 0
        pkg.trigger_type = TriggerType.Value("TRIGGER_TYPE_MANUAL")

        note = Parameter()
        note.key = "note"
        note.string_value = "smoke test — sem clip real"
        pkg.package_parameters.append(note)

        pkg.data = json.dumps({"smoke": True, "ts": ts.seconds}).encode()

        client.send_dev_sample(pkg.SerializeToString())

        print(f"  ✓ pdevsample enviado")
        print(f"    sensor_ext_id  : {sensor_ext_id}")
        print(f"    S3 path esperado: {sensor_ext_id}/samples/<data>/<uuid>.bin")
    except Exception as e:
        print(f"  ✗ FALHA: {e}")
        return 1

    print(f"\n{'═' * 55}")
    print(f"  TUDO OK — comunicação com Conveyor funcionando.")
    print(f"{'═' * 55}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
