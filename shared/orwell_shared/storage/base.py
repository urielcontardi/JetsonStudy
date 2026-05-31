from __future__ import annotations

from typing import Protocol


class StorageBackend(Protocol):
    def put(self, local_path: str, key: str, metadata: dict) -> str:
        """Envia `local_path` para `key`; retorna a URI resultante."""
        ...
