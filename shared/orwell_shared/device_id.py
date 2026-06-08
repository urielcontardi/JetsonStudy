from __future__ import annotations

import os
from pathlib import Path

from blake3 import blake3

# eMMC é sempre mmcblk0 no Jetson (não é SD card nem NVMe).
_CID_PATH = "/sys/block/mmcblk0/device/cid"


def get_ext_id(cid_path: str = _CID_PATH) -> str:
    """Deriva o extId do dispositivo a partir do eMMC CID.

    No Jetson: lê /sys/block/mmcblk0/device/cid (32 hex chars, único por placa).
    Fora do Jetson (dev/CI): usa a env var ORWELL_DEVICE_ID.
    """
    try:
        cid_hex = Path(cid_path).read_text().strip()
        return blake3(bytes.fromhex(cid_hex)).hexdigest()
    except FileNotFoundError:
        pass
    except ValueError as exc:
        raise RuntimeError(f"CID inválido em {cid_path}: {exc}") from exc

    fallback = os.environ.get("ORWELL_DEVICE_ID", "").strip()
    if fallback:
        return fallback

    raise RuntimeError(
        f"eMMC CID não encontrado em {cid_path} e ORWELL_DEVICE_ID não definido.\n"
        "No Jetson este arquivo deve existir. Em dev, defina ORWELL_DEVICE_ID=<id>."
    )
