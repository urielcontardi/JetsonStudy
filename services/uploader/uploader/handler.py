from __future__ import annotations

import tempfile
from pathlib import Path

from orwell_shared.clips import extract_clip
from orwell_shared.events import DetectionEvent
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import init_path


def handle_event_payload(payload: str, index: SegmentIndex, storage,
                         data_dir: str, extract_fn=extract_clip) -> str:
    ev = DetectionEvent.model_validate_json(payload)
    start, end = ev.clip_window()
    out = Path(tempfile.gettempdir()) / f"event-{ev.camera_id}-{int(ev.ts_event)}.mp4"
    extract_fn(index, ev.camera_id, start, end, out,
               init_path=init_path(data_dir, ev.camera_id))
    key = f"events/{ev.camera_id}/{int(ev.ts_event)}.mp4"
    metadata = {"camera": ev.camera_id, "label": ev.label, "score": str(ev.score),
                "ts_event": str(ev.ts_event)}
    return storage.put(str(out), key, metadata)
