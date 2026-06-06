from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class UploaderBackend(Protocol):
    def upload(self, event_id: str, clip_path: Path, metadata: dict) -> str:
        """Envia o clip do evento para a nuvem. Retorna a URI do clip."""
        ...
