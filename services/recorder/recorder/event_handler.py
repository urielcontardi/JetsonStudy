from __future__ import annotations

import json
import uuid
from pathlib import Path

from orwell_shared.clips import NoSegments, publish_event_clip
from orwell_shared.events import Event, EventIndex


def finalize_event_buffer(
    tmpfs_dir: str,
    events_dir: str,
    event_id: str,
    camera_id: str,
) -> Path | None:
    """Materialize a standalone MP4 before making the event visible."""
    buf_dir = Path(tmpfs_dir) / camera_id
    try:
        return publish_event_clip(buf_dir, Path(events_dir), event_id)
    except NoSegments:
        return None


def handle_detection(
    camera_id: str,
    t_evento: float,
    label: str,
    confidence: float,
    bbox: dict | None,
    tmpfs_dir: str,
    events_dir: str,
    event_index: EventIndex,
) -> str:
    """Persiste evento no índice e faz flush do event buffer. Retorna o event_id."""
    event_id = str(uuid.uuid4())
    clip = finalize_event_buffer(tmpfs_dir, events_dir, event_id, camera_id)
    event_index.add_event(Event(
        id=event_id,
        camera_id=camera_id,
        t_evento=t_evento,
        label=label,
        confidence=confidence,
        bbox_json=json.dumps(bbox) if bbox is not None else None,
        clip_path=str(clip) if clip else None,
    ))
    return event_id
