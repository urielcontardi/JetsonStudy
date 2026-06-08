from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from orwell_shared.events import Event, EventIndex
from recorder.event_handler import flush_event_buffer


class PeriodicFlusher:
    def __init__(
        self,
        cameras: list[str],
        tmpfs_dir: str,
        events_dir: str,
        event_index: EventIndex,
        interval_s: float,
        enabled: bool,
    ) -> None:
        self._cameras = cameras
        self._tmpfs_dir = tmpfs_dir
        self._events_dir = events_dir
        self._index = event_index
        self._lock = threading.Lock()
        self._interval_s = interval_s
        self._enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="PeriodicFlusher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def update_config(self, enabled: bool, interval_s: float) -> None:
        with self._lock:
            self._enabled = enabled
            self._interval_s = interval_s

    def _loop(self) -> None:
        last_flush = 0.0
        while not self._stop.wait(0.05):
            now = time.time()
            with self._lock:
                enabled = self._enabled
                interval = self._interval_s
            if enabled and (now - last_flush) >= interval:
                try:
                    self._flush_all()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("periodic flush error")
                last_flush = now

    def _flush_all(self) -> None:
        if not self._enabled:
            return
        t_now = time.time()
        for camera_id in self._cameras:
            event_id = str(uuid.uuid4())
            clip_files = flush_event_buffer(
                tmpfs_dir=self._tmpfs_dir,
                events_dir=self._events_dir,
                event_id=event_id,
                camera_id=camera_id,
            )
            if not clip_files:
                continue
            clip_path = str(clip_files[0].parent)
            self._index.add_event(Event(
                id=event_id,
                camera_id=camera_id,
                t_evento=t_now,
                label="periodic",
                confidence=1.0,
                clip_path=clip_path,
                trigger_type="periodic",
            ))
