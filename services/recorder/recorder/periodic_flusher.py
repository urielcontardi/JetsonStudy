from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path

from orwell_shared.clips import NoSegments, extract_clip
from orwell_shared.events import Event, EventIndex
from orwell_shared.index import SegmentIndex
from recorder.event_handler import finalize_event_buffer

logger = logging.getLogger(__name__)


class PeriodicFlusher:
    def __init__(
        self,
        cameras: list[str],
        tmpfs_dir: str,
        events_dir: str,
        event_index: EventIndex,
        interval_s: float,
        enabled: bool,
        segment_index: SegmentIndex | None = None,
        clip_duration_s: float = 10.0,
    ) -> None:
        self._cameras = cameras
        self._tmpfs_dir = tmpfs_dir
        self._events_dir = events_dir
        self._index = event_index
        self._segment_index = segment_index
        self._clip_duration_s = clip_duration_s
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

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)

    def update_config(self, enabled: bool, interval_s: float) -> None:
        with self._lock:
            self._enabled = enabled
            self._interval_s = interval_s

    def _loop(self) -> None:
        last_flush = time.time()
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
            clip = self._make_clip(camera_id, event_id, t_now)
            if clip is None:
                # Não pode ser silencioso: foi exatamente isto (ffmpeg quebrado →
                # probe_media sempre False → NoSegments) que deixou o envio
                # periódico parado por horas sem nenhum alarme em 2026-06-09.
                logger.warning(
                    "periodic flush para camera=%s não gerou clipe "
                    "(buffer vazio ou fragmentos inválidos — checar ffmpeg/ffprobe)",
                    camera_id,
                )
                continue
            self._index.add_event(Event(
                id=event_id,
                camera_id=camera_id,
                t_evento=t_now,
                label="periodic",
                confidence=1.0,
                clip_path=str(clip),
                trigger_type="periodic",
            ))

    def _make_clip(self, camera_id: str, event_id: str, t_now: float) -> Path | None:
        if self._segment_index is None:
            return finalize_event_buffer(
                tmpfs_dir=self._tmpfs_dir,
                events_dir=self._events_dir,
                event_id=event_id,
                camera_id=camera_id,
            )

        event_dir = Path(self._events_dir) / event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        clip = event_dir / "clip.mp4"
        try:
            return extract_clip(
                self._segment_index,
                camera_id,
                t_now - self._clip_duration_s,
                t_now,
                clip,
            )
        except NoSegments:
            event_dir.rmdir()
            return None
