#!/usr/bin/env python3
"""Smoke test: verifica comunicação com o Conveyor via VSTP dev routes.

Usa o gateway virtual do iot-emulator (extId = 000011113333 por padrão).
Não precisa de Jetson, GStreamer ou câmera — só rede até o Conveyor.

Uso:
    python tests/smoke_conveyor.py
    python tests/smoke_conveyor.py --host conveyor.tractian.dev
    python tests/smoke_conveyor.py --ext-id 000011112222

Env vars:
    ORWELL_DEVICE_ID   — sobrescreve --ext-id
    CONVEYOR_HOST      — sobrescreve --host
"""
import argparse
import json
import os
import sys
import time
import uuid

# Garante que shared/ está no path quando rodado da raiz do repo.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "shared"))

from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.conveyor_uploader import ConveyorUploader
from orwell_shared.samples_pb2 import Package


def _sep(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print('─' * 50)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("CONVEYOR_HOST", "conveyor.tractian.com"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--ext-id", default=os.environ.get("ORWELL_DEVICE_ID", "000011113333"),
                        help="extId do gateway virtual (default: 000011113333)")
    args = parser.parse_args()

    ext_id = args.ext_id
    host = args.host

    print(f"Conveyor smoke test")
    print(f"  host   : {host}:{args.port}")
    print(f"  ext_id : {ext_id}")

    # ── 1. Auth ──────────────────────────────────────────────────────────────
    _sep("1/3  Auth (ggt)")
    try:
        client = ConveyorClient(host=host, port=args.port, ext_id=ext_id)
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

    # ── 3. pdevsample — Package mínimo ───────────────────────────────────────
    _sep("3/3  pdevsample (Package orwell.smoke.v1)")
    try:
        uploader = ConveyorUploader(client=client, ext_id=ext_id)

        # Cria um Package de smoke sem clip real
        from google.protobuf.timestamp_pb2 import Timestamp
        from orwell_shared.samples_pb2 import Parameter, TriggerType

        ts = Timestamp()
        ts.seconds = int(time.time())

        pkg = Package()
        pkg.device_id = ext_id.encode()
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
        print(f"    format : {pkg.format}")
        print(f"    data_id: {pkg.data_id.hex()}")
        print(f"    S3 path esperado: {ext_id}/samples/<data>/<uuid>.bin")
    except Exception as e:
        print(f"  ✗ FALHA: {e}")
        return 1

    print(f"\n{'═' * 50}")
    print(f"  TUDO OK — comunicação com Conveyor funcionando.")
    print(f"{'═' * 50}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
