from __future__ import annotations

import os
from pathlib import Path

# Prefixos de interfaces virtuais para ignorar.
_SKIP_PREFIXES = ("lo", "docker", "veth", "br-", "l4tbr", "tailscale", "usb", "can")


def _mac_of(iface: str) -> str | None:
    """Lê o MAC de /sys/class/net/{iface}/address. Retorna None se inválido."""
    try:
        addr = (Path("/sys/class/net") / iface / "address").read_text().strip()
        # Pula MACs zerados, broadcast ou inválidos
        if addr in ("", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
            return None
        return addr.replace(":", "").lower()
    except FileNotFoundError:
        return None


def get_ext_id() -> str:
    """Retorna o extId do dispositivo: MAC da interface física principal (12 hex chars).

    Ordem de preferência: eth/en > wl > qualquer outra física.
    Fallback: ORWELL_DEVICE_ID env var (dev / CI / macOS).

    Exemplos:
        Jetson Orin NX : 4cbb47c1331a
        macOS dev      : export ORWELL_DEVICE_ID=mymacdevice
    """
    net_root = Path("/sys/class/net")

    try:
        ifaces = [p.name for p in net_root.iterdir()]
    except FileNotFoundError:
        ifaces = []

    # Filtra interfaces virtuais
    physical = [
        i for i in ifaces
        if not any(i.startswith(pfx) for pfx in _SKIP_PREFIXES)
    ]

    # Prefere Ethernet (en/eth) → WiFi (wl) → resto
    def _priority(name: str) -> int:
        if name.startswith(("eth", "enP", "enp", "eno", "ens")):
            return 0
        if name.startswith("wl"):
            return 1
        return 2

    for iface in sorted(physical, key=_priority):
        mac = _mac_of(iface)
        if mac:
            return mac

    # Fallback para env var (dev / CI)
    fallback = os.environ.get("ORWELL_DEVICE_ID", "").strip()
    if fallback:
        return fallback

    raise RuntimeError(
        "Nenhuma interface de rede física encontrada e ORWELL_DEVICE_ID não definido.\n"
        "Em dev/CI: export ORWELL_DEVICE_ID=<id>"
    )
