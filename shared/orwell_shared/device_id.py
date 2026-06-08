from __future__ import annotations

import os
from pathlib import Path

from blake3 import blake3

# Jetson Orin NX com NVMe: serial único gravado no SoC (device-tree do Tegra).
# Jetson com eMMC (Nano, AGX): CID da eMMC como fallback.
_SERIAL_PATH = "/proc/device-tree/serial-number"
_EMMC_CID_PATH = "/sys/block/mmcblk0/device/cid"


def get_ext_id(
    serial_path: str = _SERIAL_PATH,
    cid_path: str = _EMMC_CID_PATH,
) -> str:
    """Deriva o extId do dispositivo a partir de um identificador único de hardware.

    Ordem de tentativa:
      1. /proc/device-tree/serial-number  — serial do SoC Tegra (NX com NVMe)
      2. /sys/block/mmcblk0/device/cid    — CID da eMMC (Nano/AGX com eMMC)
      3. ORWELL_DEVICE_ID env var          — override para dev/CI (macOS, container)
    """
    # 1. Device-tree serial (Jetson Orin NX / NVMe)
    try:
        serial = Path(serial_path).read_bytes().strip(b"\x00\n ").decode()
        if serial:
            return blake3(serial.encode()).hexdigest()
    except FileNotFoundError:
        pass

    # 2. eMMC CID (Jetson Nano / AGX)
    try:
        cid_hex = Path(cid_path).read_text().strip()
        if cid_hex:
            return blake3(bytes.fromhex(cid_hex)).hexdigest()
    except FileNotFoundError:
        pass
    except ValueError as exc:
        raise RuntimeError(f"CID inválido em {cid_path}: {exc}") from exc

    # 3. Env var (dev / CI)
    fallback = os.environ.get("ORWELL_DEVICE_ID", "").strip()
    if fallback:
        return fallback

    raise RuntimeError(
        "Identificador de hardware não encontrado.\n"
        f"  Jetson NX/NVMe : {serial_path}\n"
        f"  Jetson eMMC    : {cid_path}\n"
        "  Dev/CI         : export ORWELL_DEVICE_ID=<id>"
    )
