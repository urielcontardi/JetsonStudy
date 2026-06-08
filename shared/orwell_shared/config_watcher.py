from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from orwell_shared.config import OrwellConfig, load_config

logger = logging.getLogger(__name__)


class ConfigWatcher:
    def __init__(
        self,
        config_path: str | Path,
        on_change: Callable[[OrwellConfig], None],
        poll_interval_s: float = 30.0,
    ) -> None:
        self._path = Path(config_path)
        self._on_change = on_change
        self._poll_interval = poll_interval_s
        self._last_mtime: float = self._path.stat().st_mtime
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="ConfigWatcher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_interval):
            try:
                mtime = self._path.stat().st_mtime
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    cfg = load_config(self._path)
                    self._on_change(cfg)
            except Exception:
                logger.exception("config watcher error")
