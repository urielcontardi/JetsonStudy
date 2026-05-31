from __future__ import annotations

import shutil
from pathlib import Path


class LocalStorageBackend:
    def __init__(self, dest_dir: str):
        self.dest_dir = Path(dest_dir)

    def put(self, local_path: str, key: str, metadata: dict) -> str:
        target = self.dest_dir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)
        return f"file://{target}"
