from __future__ import annotations

import logging
import threading
from pathlib import Path

from orwell_shared.events import EventIndex

logger = logging.getLogger(__name__)


class UploadWorker:
    def __init__(
        self,
        event_index: EventIndex,
        uploader,
        upload_interval_s: float = 30.0,
        status_interval_s: float = 300.0,
    ) -> None:
        self._index = event_index
        self._uploader = uploader
        self._upload_interval = upload_interval_s
        self._status_interval = status_interval_s
        self._stop_event = threading.Event()
        self._upload_thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None

    def start(self) -> None:
        self._upload_thread = threading.Thread(
            target=self._upload_loop, daemon=True, name="UploadWorker"
        )
        self._upload_thread.start()
        self._status_thread = threading.Thread(
            target=self._status_loop, daemon=True, name="StatusWorker"
        )
        self._status_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _upload_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_pending()
            except Exception:
                logger.exception("unexpected error in upload loop")
            self._stop_event.wait(self._upload_interval)

    def _status_loop(self) -> None:
        # Espera o intervalo antes do primeiro envio para não disparar no boot imediato.
        while not self._stop_event.wait(self._status_interval):
            try:
                self._send_status()
            except Exception:
                logger.exception("unexpected error in status loop")

    def _process_pending(self) -> None:
        pending = self._index.pending_uploads()
        for event in pending:
            if self._stop_event.is_set():
                break
            clip_path = Path(event.clip_path) if event.clip_path else None
            if clip_path is None or not clip_path.exists():
                logger.warning("clip not found for event %s, marking as failed", event.id)
                self._index.mark_upload_failed(event.id)
                continue
            try:
                self._uploader.upload(
                    event_id=event.id,
                    clip_path=clip_path,
                    metadata={
                        "camera_id": event.camera_id,
                        "label": event.label,
                        "confidence": event.confidence,
                        "bbox": event.bbox_json,
                        "t_evento": event.t_evento,
                        "trigger_type": event.trigger_type,
                    },
                )
                self._index.mark_uploaded(event.id)
                logger.info("uploaded event %s", event.id)
            except Exception:
                logger.warning("upload failed for event %s, will retry", event.id, exc_info=True)

    def _send_status(self) -> None:
        try:
            import psutil
            metrics = {
                "cpu": psutil.cpu_percent(interval=0.1),
                "memory": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage("/").percent,
            }
        except ImportError:
            metrics = {}
        self._uploader.upload_status(metrics)
